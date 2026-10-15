import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/record_actions.dart';

/// The server's activity types (ActivityType).
const activityTypes = [
  'land_preparation',
  'sowing',
  'irrigation',
  'fertilizing',
  'pest_control',
  'weeding',
  'pruning',
  'harvesting',
  'other',
];

IconData activityIcon(String type) => switch (type) {
      'land_preparation' => Icons.agriculture_outlined,
      'sowing' => Icons.grass,
      'irrigation' => Icons.water_drop_outlined,
      'fertilizing' => Icons.science_outlined,
      'pest_control' => Icons.bug_report_outlined,
      'weeding' => Icons.content_cut,
      'pruning' => Icons.park_outlined,
      'harvesting' => Icons.shopping_basket_outlined,
      _ => Icons.task_alt,
    };

/// Checks the form before it is sent (the server applies the same rules). Returns the first problem, or null.
String? validateActivity({required String? type, required DateTime date, required DateTime today}) {
  if (type == null) return 'Choose what work was done.';
  if (DateTime(date.year, date.month, date.day).isAfter(DateTime(today.year, today.month, today.day))) {
    return 'The date cannot be in the future. Use a reminder for planned work.';
  }
  return null;
}

/// Field work done on a farm (irrigation, weeding, spraying…), or on one crop when [cycleId] is given: list, add,
/// edit and delete.
class ActivitiesScreen extends ConsumerStatefulWidget {
  const ActivitiesScreen({super.key, required this.farmId, this.cycleId, this.title = 'Field work log'});

  final String farmId;
  final String? cycleId;
  final String title;

  @override
  ConsumerState<ActivitiesScreen> createState() => _ActivitiesScreenState();
}

class _ActivitiesScreenState extends ConsumerState<ActivitiesScreen> {
  Key _key = UniqueKey();
  final _busy = <String>{}; // deletes in flight

  void _refresh() => setState(() => _key = UniqueKey());

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final r = await Future.wait([
      api.getObj(
        '/farms/${widget.farmId}/activities',
        query: {'limit': 100, if (widget.cycleId != null) 'crop_cycle_id': widget.cycleId},
      ),
      api.getPage('/farms/${widget.farmId}/crop-cycles'),
    ]);
    return {'page': r[0], 'cycles': r[1]};
  }

  Future<void> _edit(List<Map<String, dynamic>> cycles, [Map<String, dynamic>? activity]) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) =>
            ActivityFormScreen(farmId: widget.farmId, cycles: cycles, cycleId: widget.cycleId, activity: activity),
      ),
    );
    if (saved == true && mounted) _refresh();
  }

  Future<void> _delete(Map<String, dynamic> a) async {
    final id = a.str('id');
    if (_busy.contains(id)) return;
    final sure = await confirmAction(
      context,
      title: 'Delete this entry?',
      message: '${label(a.str('activity_type'))} on ${day(a.str('activity_date'))}',
    );
    if (!sure || !mounted) return;
    setState(() => _busy.add(id));
    final ok = await runAction(context, () => ref.read(apiProvider).delete('/activities/$id'), success: 'Entry deleted');
    if (!mounted) return;
    setState(() => _busy.remove(id));
    if (ok) _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () => api.cached(
          'activities:${widget.farmId}:${widget.cycleId ?? 'all'}',
          () => _load(api),
          (j) => j is Map<String, dynamic> ? j : <String, dynamic>{},
        ),
        builder: (context, d, reload) {
          final page = d.obj('page');
          final items = page.objs('items');
          final cycles = d.objs('cycles');
          final names = {for (final c in cycles) c.str('id'): c.str('crop_name')};
          return ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton.icon(
                  onPressed: () => _edit(cycles),
                  icon: const Icon(Icons.add),
                  label: const Text('Add field work'),
                ),
              ),
              if (items.isEmpty)
                const EmptyPanel(
                  icon: Icons.task_alt,
                  message: 'Nothing recorded yet. Tap "Add field work" after irrigating, weeding, spraying and so on.',
                ),
              if (page.intVal('total') > items.length)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Text('Showing the latest ${items.length} of ${page.intVal('total')} entries.'),
                ),
              for (final a in items)
                ListTile(
                  leading: Icon(activityIcon(a.str('activity_type'))),
                  title: Text(label(a.str('activity_type'))),
                  subtitle: Text(
                    [
                      day(a.str('activity_date')),
                      if (widget.cycleId == null)
                        a.strOrNull('crop_cycle_id') == null ? 'Whole farm' : names[a.str('crop_cycle_id')] ?? 'Crop',
                      if (a.str('description').isNotEmpty) a.str('description'),
                    ].join(' · '),
                  ),
                  onTap: () => _edit(cycles, a),
                  trailing: IconButton(
                    tooltip: 'Delete',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: _busy.contains(a.str('id')) ? null : () => _delete(a),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// Record or edit one piece of field work.
class ActivityFormScreen extends ConsumerStatefulWidget {
  const ActivityFormScreen({super.key, required this.farmId, required this.cycles, this.cycleId, this.activity});

  /// The entry being edited; null when adding.
  final Map<String, dynamic>? activity;
  final String farmId;
  final List<Map<String, dynamic>> cycles;
  final String? cycleId;

  @override
  ConsumerState<ActivityFormScreen> createState() => _ActivityFormScreenState();
}

class _ActivityFormScreenState extends ConsumerState<ActivityFormScreen> {
  late final _note = TextEditingController(text: widget.activity?.str('description') ?? '');
  late String? _type = widget.activity?.strOrNull('activity_type');
  late String? _cycleId = widget.activity == null ? widget.cycleId : widget.activity!.strOrNull('crop_cycle_id');
  late DateTime _date = DateTime.tryParse(widget.activity?.str('activity_date') ?? '') ?? _today();
  String? _error;
  bool _saving = false;

  static DateTime _today() {
    final n = DateTime.now();
    return DateTime(n.year, n.month, n.day);
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final d = await showDatePicker(
      context: context,
      initialDate: _date.isAfter(_today()) ? _today() : _date,
      firstDate: DateTime(2020),
      lastDate: _today(),
    );
    if (d == null || !mounted) return;
    setState(() {
      _date = d;
      _error = null;
    });
  }

  Future<void> _save() async {
    if (_saving) return;
    final problem = validateActivity(type: _type, date: _date, today: _today());
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final note = _note.text.trim();
    try {
      if (widget.activity == null) {
        await ref.read(apiProvider).post(
          '/farms/${widget.farmId}/activities',
          body: {
            'activity_type': _type,
            'activity_date': isoDate(_date),
            if (_cycleId != null) 'crop_cycle_id': _cycleId,
            if (note.isNotEmpty) 'description': note,
          },
        );
      } else {
        await ref.read(apiProvider).patch('/activities/${widget.activity!.str('id')}', {
          'activity_type': _type,
          'activity_date': isoDate(_date),
          'crop_cycle_id': _cycleId, // null moves it to the whole farm
          'description': note.isEmpty ? null : note,
        });
      }
      if (!mounted) return;
      showMessage(context, widget.activity == null ? '${label(_type!)} recorded' : 'Entry updated');
      Navigator.of(context).pop(true);
    } catch (e) {
      final f = e is AppFailure ? e : mapDioError(e);
      if (mounted) {
        setState(() {
          _error = f.message;
          _saving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(widget.activity == null ? 'Add field work' : 'Edit field work')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null)
            Card(
              color: scheme.errorContainer,
              child: ListTile(
                leading: Icon(Icons.error_outline, color: scheme.onErrorContainer),
                title: Text(_error!, style: TextStyle(color: scheme.onErrorContainer)),
              ),
            ),
          Text('1. Work done', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final t in activityTypes)
                ChoiceChip(
                  avatar: Icon(activityIcon(t), size: 18),
                  label: Text(label(t)),
                  selected: _type == t,
                  onSelected: (_) => setState(() {
                    _type = t;
                    _error = null;
                  }),
                ),
            ],
          ),
          const Divider(height: 32),
          Text('2. When', style: Theme.of(context).textTheme.titleMedium),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Date'),
            subtitle: Text(day(isoDate(_date))),
            trailing: const Icon(Icons.edit_calendar),
            onTap: _pickDate,
          ),
          const Divider(height: 32),
          Text('3. For which crop (optional)', style: Theme.of(context).textTheme.titleMedium),
          DropdownButtonFormField<String?>(
            initialValue: _cycleId,
            isExpanded: true,
            items: [
              const DropdownMenuItem<String?>(child: Text('Whole farm (not one crop)')),
              for (final c in widget.cycles)
                DropdownMenuItem<String?>(
                  value: c.str('id'),
                  child: Text(
                    '${c.str('crop_name')} · ${label(c.str('status')).toLowerCase()} · sown ${day(c.str('sowing_date'))}',
                  ),
                ),
            ],
            onChanged: (v) => setState(() => _cycleId = v),
          ),
          const SizedBox(height: 16), // keeps the note's floating label clear of the dropdown border
          TextField(
            controller: _note,
            maxLength: 1000,
            decoration: const InputDecoration(labelText: 'Note (optional)', hintText: 'e.g. drip, 2 hours'),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: _saving
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.save),
            label: Text(_saving ? 'Saving…' : 'Save'),
          ),
        ],
      ),
    );
  }
}
