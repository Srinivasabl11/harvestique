import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/record_actions.dart';
import '../auth/auth_controller.dart';

/// A/B/C quality grade of a recorded harvest. The farmer rates every check (optionally starting from an AI photo
/// proposal), sees the grade the ratings give, and confirms. Nothing is final until confirmed; no grade is possible
/// while a check is open. Indicative grade, not an official one: the hub's quality check decides acceptance.
class GradingScreen extends ConsumerStatefulWidget {
  const GradingScreen({super.key, required this.cycleId});

  final String cycleId;

  @override
  ConsumerState<GradingScreen> createState() => _GradingScreenState();
}

class _GradingScreenState extends ConsumerState<GradingScreen> {
  Map<String, dynamic>? _data;
  Object? _error;
  bool _busy = false;

  String get _path => '/crop-cycles/${widget.cycleId}/grading';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final d = await ref.read(apiProvider).getObj(_path, query: {'language': ref.read(authProvider).language});
      if (mounted) setState(() => _data = d);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _photo(ImageSource source) async {
    final file = await ImagePicker().pickImage(source: source, maxWidth: 1600, maxHeight: 1600, imageQuality: 85);
    if (file == null || !mounted) return;
    setState(() => _busy = true);
    await runAction(context, () async {
      final res = await ref.read(apiProvider).upload(
            '$_path/photo',
            field: 'image',
            bytes: await file.readAsBytes(),
            filename: file.name,
            fields: {'language': ref.read(authProvider).language},
            receiveTimeout: AppConfig.photoCheckTimeout,
          );
      if (mounted) setState(() => _data = res);
    });
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _confirm(Map<String, int> levels, String? grade, String? reason) async {
    setState(() => _busy = true);
    final ok = await runAction(context, () async {
      final res = await ref.read(apiProvider).put(_path, {
        'levels': levels,
        if (grade != null) 'grade': grade,
        if (reason != null) 'reason': reason,
        'language': ref.read(authProvider).language,
      });
      if (mounted) setState(() => _data = res);
    });
    if (mounted) {
      setState(() => _busy = false);
      if (ok) showMessage(context, 'Grade ${_data?.str('grade')} saved');
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    return Scaffold(
      appBar: AppBar(title: const Text('Produce quality grade')),
      body: d == null
          ? (_error != null
              ? ErrorPanel(error: _error!, onRetry: _load)
              : const Center(child: CircularProgressIndicator(semanticsLabel: 'Loading')))
          : GradingForm(
              key: ValueKey('${d.str('status')}${d.obj('proposal').str('proposed_at')}${d.str('confirmed_at')}'),
              data: d,
              busy: _busy,
              onPhoto: _photo,
              onConfirm: _confirm,
            ),
    );
  }
}

/// The worst level over all checks gives the grade: all 0 -> A, worst 1 -> B, any 2 -> C. Null while a check is open.
String? gradeFor(List<String> checks, Map<String, int> levels) {
  if (checks.isEmpty || checks.any((c) => !levels.containsKey(c))) return null;
  final worst = checks.map((c) => levels[c]!).reduce((a, b) => a > b ? a : b);
  return const ['A', 'B', 'C'][worst];
}

class GradingForm extends StatefulWidget {
  const GradingForm({super.key, required this.data, required this.onPhoto, required this.onConfirm, this.busy = false});

  final Map<String, dynamic> data;
  final bool busy;
  final void Function(ImageSource source) onPhoto;
  final void Function(Map<String, int> levels, String? grade, String? reason) onConfirm;

  @override
  State<GradingForm> createState() => _GradingFormState();
}

class _GradingFormState extends State<GradingForm> {
  late final Map<String, int> _levels;
  String? _lower; // a grade below what the ratings give, chosen by the farmer
  final _reason = TextEditingController();

  Map<String, dynamic> get d => widget.data;

  @override
  void initState() {
    super.initState();
    // start from the confirmed ratings, else from the AI proposal (to review), else empty
    final confirmed = d.objOrNull('levels');
    final proposed = d.obj('proposal').obj('levels');
    final start = confirmed ?? proposed;
    _levels = {for (final e in start.entries) if (e.value is num) e.key: (e.value as num).toInt()};
    final grade = d.strOrNull('grade');
    if (grade != null && grade != d.strOrNull('criteria_grade')) {
      _lower = grade;
      _reason.text = d.str('override_reason');
    }
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final criteria = d.obj('criteria');
    final attributes = criteria.objs('attributes');
    final checks = [for (final a in attributes) a.str('id')];
    final proposal = d.objOrNull('proposal');
    final proposed = proposal?.obj('levels') ?? const <String, dynamic>{};
    final locked = d.boolVal('locked');
    final computed = gradeFor(checks, _levels);
    final open = [for (final a in attributes) if (!_levels.containsKey(a.str('id'))) a.str('title')];
    final lowerOptions = computed == null ? <String>[] : ['A', 'B', 'C'].where((g) => g.compareTo(computed) > 0).toList();
    final reasonNeeded = _lower != null;
    final canConfirm = !locked && !widget.busy && computed != null && (!reasonNeeded || _reason.text.trim().length >= 3);
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Text('${d.str('crop_name')} · ${kg(d.numOrNull('harvested_kg'))} harvested', style: theme.textTheme.titleMedium),
        const SizedBox(height: 4),
        if (d.strOrNull('grade') != null)
          _GradeBanner(grade: d.str('grade'), text: d.str('grade_text'), source: d.strOrNull('grade_source')),
        Text(d.str('status_text')),
        for (final w in d.strs('warnings'))
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(w, style: TextStyle(color: theme.colorScheme.error, fontWeight: FontWeight.w600)),
          ),
        const SizedBox(height: 8),
        Text(criteria.str('note'), style: theme.textTheme.bodySmall),
        if (!locked) ...[
          const SizedBox(height: 12),
          const Text('Optional: start from a photo of the harvested produce (a crate, heap or handful, in daylight). '
              'The AI suggests ratings; you check each one.'),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: widget.busy ? null : () => widget.onPhoto(ImageSource.camera),
                  icon: const Icon(Icons.photo_camera),
                  label: const Text('Camera'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: widget.busy ? null : () => widget.onPhoto(ImageSource.gallery),
                  icon: const Icon(Icons.photo_library_outlined),
                  label: const Text('Gallery'),
                ),
              ),
            ],
          ),
        ],
        if (widget.busy)
          const Padding(
            padding: EdgeInsets.all(16),
            child: Center(child: CircularProgressIndicator(semanticsLabel: 'Working')),
          ),
        if (proposal != null)
          SectionCard(
            title: 'AI suggestion (check it)',
            icon: Icons.auto_awesome_outlined,
            action: const DataKindChip('estimate'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(proposal.str('message')),
                if (proposal.str('description').isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text('What the AI saw (may be wrong): ${proposal.str('description')}',
                        style: theme.textTheme.bodySmall,),
                  ),
                if (proposal.strOrNull('proposed_grade') != null)
                  Text('Suggested grade: ${proposal.str('proposed_grade')} (not final)',
                      style: const TextStyle(fontWeight: FontWeight.w600),),
              ],
            ),
          ),
        const SizedBox(height: 8),
        Text('Your checks', style: theme.textTheme.titleMedium),
        Text(criteria.str('rule'), style: theme.textTheme.bodySmall),
        for (final a in attributes)
          _CheckTile(
            attribute: a,
            value: _levels[a.str('id')],
            suggested: proposed[a.str('id')] is num ? (proposed[a.str('id')] as num).toInt() : null,
            enabled: !locked && !widget.busy,
            onChanged: (v) => setState(() {
              _levels[a.str('id')] = v;
              _lower = null;
            }),
          ),
        const SizedBox(height: 8),
        if (computed == null)
          Text('No grade yet. Still open: ${open.join(', ')}.',
              style: const TextStyle(fontWeight: FontWeight.w600),)
        else ...[
          Text('Your ratings give grade $computed. ${criteria.obj('grades').str(computed)}',
              style: const TextStyle(fontWeight: FontWeight.w600),),
          if (!locked && lowerOptions.isNotEmpty)
            Row(
              children: [
                const Text('Give a lower grade: '),
                DropdownButton<String?>(
                  value: lowerOptions.contains(_lower) ? _lower : null,
                  items: [
                    const DropdownMenuItem<String?>(value: null, child: Text('No')),
                    for (final g in lowerOptions) DropdownMenuItem<String?>(value: g, child: Text(g)),
                  ],
                  onChanged: widget.busy ? null : (v) => setState(() => _lower = v),
                ),
              ],
            ),
          if (reasonNeeded)
            TextField(
              controller: _reason,
              maxLength: 255,
              decoration: const InputDecoration(labelText: 'Why lower? (required)'),
              onChanged: (_) => setState(() {}),
            ),
        ],
        const SizedBox(height: 12),
        if (!locked)
          FilledButton.icon(
            onPressed: canConfirm
                ? () => widget.onConfirm(Map.of(_levels), _lower, reasonNeeded ? _reason.text.trim() : null)
                : null,
            icon: const Icon(Icons.verified_outlined),
            label: Text(computed == null ? 'Rate every check to confirm' : 'Confirm grade ${_lower ?? computed}'),
          ),
      ],
    );
  }
}

class _GradeBanner extends StatelessWidget {
  const _GradeBanner({required this.grade, required this.text, this.source});

  final String grade;
  final String text;
  final String? source;

  @override
  Widget build(BuildContext context) {
    final color = switch (grade) {
      'A' => const Color(0xFF2E7D32),
      'B' => const Color(0xFF1565C0),
      _ => const Color(0xFFB26A00),
    };
    final how = switch (source) {
      'photo_confirmed' => 'AI suggestion confirmed by you',
      'photo_corrected' => 'AI suggestion corrected by you',
      _ => 'Graded by you',
    };
    return Semantics(
      container: true,
      label: 'Grade $grade. $text',
      excludeSemantics: true,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.10),
          border: Border.all(color: color),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            CircleAvatar(
              backgroundColor: color,
              child: Text(grade, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [Text(text), Text(how, style: Theme.of(context).textTheme.bodySmall)],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CheckTile extends StatelessWidget {
  const _CheckTile({
    required this.attribute,
    required this.value,
    required this.suggested,
    required this.enabled,
    required this.onChanged,
  });

  final Map<String, dynamic> attribute;
  final int? value;
  final int? suggested;
  final bool enabled;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final a = attribute;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(a.str('title'), style: const TextStyle(fontWeight: FontWeight.w600)),
            if (a['photo_visible'] == false)
              Text('A photo cannot show this: check it yourself.', style: Theme.of(context).textTheme.bodySmall),
            RadioGroup<int>(
              groupValue: value,
              onChanged: (v) {
                if (enabled && v != null) onChanged(v);
              },
              child: Column(
                children: [
                  for (final lv in a.objs('levels'))
                    RadioListTile<int>(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      value: lv.intVal('level'),
                      enabled: enabled,
                      title: Text(lv.str('text')),
                      subtitle: suggested == lv.intVal('level') ? const Text('AI suggestion') : null,
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
