import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'crop_catalog.dart';

/// Land a plot still has free: plot area minus planned/growing crops on it (the server checks overlapping dates
/// exactly; this is only the starting suggestion).
double freeArea(Map<String, dynamic> plot, List<Map<String, dynamic>> plotCycles) {
  final used = plotCycles
      .where((c) => c.str('status') == 'planned' || c.str('status') == 'growing')
      .fold<double>(0, (sum, c) => sum + c.numVal('area_acres'));
  final free = plot.numVal('area_acres') - used;
  return free < 0 ? 0 : double.parse(free.toStringAsFixed(3));
}

/// Checks the form before it is sent. Returns the first problem, or null when the crop can be saved.
String? validateCrop({
  required Map<String, dynamic>? crop,
  required String status,
  required DateTime sowing,
  required DateTime? expected,
  required double? area,
  required double plotArea,
  required DateTime today,
}) {
  if (crop == null) return 'Choose a crop from the list.';
  if (area == null || area <= 0) return 'Enter the area in acres (more than 0).';
  if (area > plotArea) return 'The area cannot be more than the plot (${number(plotArea)} acres).';
  final day0 = DateTime(today.year, today.month, today.day);
  if (status == 'growing' && sowing.isAfter(day0)) return 'A growing crop cannot have a sowing date in the future.';
  if (expected != null && !expected.isAfter(sowing)) return 'The expected harvest date must be after the sowing date.';
  return null;
}

/// The request body the API expects (POST /plots/{plot_id}/crop-cycles).
Map<String, dynamic> cropBody({
  required Map<String, dynamic> crop,
  required String status,
  required DateTime sowing,
  required DateTime? expected,
  required double area,
}) =>
    {
      'crop_id': crop.str('id'),
      'status': status,
      'sowing_date': isoDate(sowing),
      'area_acres': double.parse(area.toStringAsFixed(3)),
      if (expected != null) 'expected_harvest_date': isoDate(expected),
    };

/// Add a crop to one plot. Full screen (not a dialog) so every choice and every server message is visible.
class AddCropScreen extends ConsumerStatefulWidget {
  const AddCropScreen({super.key, required this.plot, required this.plotCycles});

  final Map<String, dynamic> plot;
  final List<Map<String, dynamic>> plotCycles;

  @override
  ConsumerState<AddCropScreen> createState() => _AddCropScreenState();
}

class _AddCropScreenState extends ConsumerState<AddCropScreen> {
  late Future<List<Map<String, dynamic>>> _crops = _loadCrops();
  final _search = TextEditingController();
  String? _category; // null = all categories
  late final _area = TextEditingController(text: number(_suggestedArea, decimals: 3));
  Map<String, dynamic>? _crop;
  String _status = 'growing';
  DateTime _sowing = _today();
  DateTime? _expected;
  bool _expectedChosen = false; // true once the farmer picks it; until then it follows the crop's duration
  String? _error;
  bool _saving = false;

  static DateTime _today() {
    final n = DateTime.now();
    return DateTime(n.year, n.month, n.day);
  }

  double get _plotArea => widget.plot.numVal('area_acres');

  double get _suggestedArea {
    final free = freeArea(widget.plot, widget.plotCycles);
    return free > 0 ? free : _plotArea;
  }

  Future<List<Map<String, dynamic>>> _loadCrops() => ref.read(apiProvider).getAll('/crops');

  @override
  void dispose() {
    _search.dispose();
    _area.dispose();
    super.dispose();
  }

  void _autoExpected() {
    if (_expectedChosen || _crop == null) return;
    final days = _crop!.intVal('typical_duration_days');
    _expected = days > 0 ? _sowing.add(Duration(days: days)) : null;
  }

  Future<void> _pickSowing() async {
    final last = _status == 'growing' ? _today() : DateTime(2035);
    final d = await showDatePicker(
      context: context,
      initialDate: _sowing.isAfter(last) ? last : _sowing,
      firstDate: DateTime(2020),
      lastDate: last,
    );
    if (d == null || !mounted) return;
    setState(() {
      _sowing = d;
      _autoExpected();
      _error = null;
    });
  }

  Future<void> _pickExpected() async {
    final first = _sowing.add(const Duration(days: 1));
    final initial = _expected != null && _expected!.isAfter(_sowing) ? _expected! : _sowing.add(const Duration(days: 90));
    final d = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: first,
      lastDate: DateTime(2036),
    );
    if (d == null || !mounted) return;
    setState(() {
      _expected = d;
      _expectedChosen = true;
      _error = null;
    });
  }

  Future<void> _save() async {
    final area = double.tryParse(_area.text.trim());
    final problem = validateCrop(
      crop: _crop,
      status: _status,
      sowing: _sowing,
      expected: _expected,
      area: area,
      plotArea: _plotArea,
      today: _today(),
    );
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(apiProvider).post(
            '/plots/${widget.plot.str('id')}/crop-cycles',
            body: cropBody(crop: _crop!, status: _status, sowing: _sowing, expected: _expected, area: area!),
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${_crop!.str('name')} added to ${widget.plot.str('name')}')),
      );
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
    final others = widget.plotCycles.where((c) => c.str('status') == 'planned' || c.str('status') == 'growing').toList();
    return Scaffold(
      appBar: AppBar(title: Text('Add crop · ${widget.plot.str('name')}')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _crops,
        builder: (context, snap) {
          if (snap.hasError) {
            return ErrorPanel(error: snap.error!, onRetry: () => setState(() {
                        _crops = _loadCrops();
                      }),);
          }
          if (!snap.hasData) return const Center(child: CircularProgressIndicator(semanticsLabel: 'Loading'));
          final all = snap.data!;
          if (all.isEmpty) {
            return const EmptyPanel(
              icon: Icons.spa_outlined,
              message: 'No crops are available to choose from yet: the crop list on the server is empty.\n'
                  'It is filled automatically when the server starts. Restart the server, then try again.',
            );
          }
          final shown = filterCrops(all, _search.text, _category);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (_error != null)
                Card(
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: ListTile(
                    leading: Icon(Icons.error_outline, color: Theme.of(context).colorScheme.onErrorContainer),
                    title: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer)),
                  ),
                ),
              Text('1. Crop', style: Theme.of(context).textTheme.titleMedium),
              if (_crop != null)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.check_circle, color: Colors.green),
                  title: Text('Selected: ${_crop!.str('name')}'),
                  subtitle: Text('About ${_crop!.intVal('typical_duration_days')} days from sowing to harvest'),
                  trailing: TextButton(onPressed: () => setState(() => _crop = null), child: const Text('Change')),
                )
              else ...[
                TextField(
                  controller: _search,
                  decoration:
                      const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search crops (English, Kannada or other name)'),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 6),
                CropCategoryChips(crops: all, selected: _category, onSelected: (k) => setState(() => _category = k)),
                if (shown.isEmpty) const Padding(padding: EdgeInsets.all(12), child: Text('No crop matches that search.')),
                for (final c in shown)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.spa_outlined),
                    title: Text(c.str('name')),
                    subtitle: Text(
                      [
                        if (c.str('local_name').isNotEmpty) c.str('local_name'),
                        label(c.str('category')),
                        '${c.intVal('typical_duration_days')} days',
                      ].join(' · '),
                    ),
                    onTap: () => setState(() {
                      _crop = c;
                      _error = null;
                      _autoExpected();
                    }),
                  ),
              ],
              const Divider(height: 32),
              Text('2. Status', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'planned', label: Text('Planned'), icon: Icon(Icons.event_note)),
                  ButtonSegment(value: 'growing', label: Text('Growing now'), icon: Icon(Icons.grass)),
                ],
                selected: {_status},
                onSelectionChanged: (s) => setState(() {
                  _status = s.first;
                  if (_status == 'growing' && _sowing.isAfter(_today())) {
                    _sowing = _today();
                    _autoExpected();
                  }
                  _error = null;
                }),
              ),
              const Divider(height: 32),
              Text('3. Dates', style: Theme.of(context).textTheme.titleMedium),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Sowing date'),
                subtitle: Text(day(isoDate(_sowing))),
                trailing: const Icon(Icons.edit_calendar),
                onTap: _pickSowing,
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Expected harvest date (optional)'),
                subtitle: Text(
                  _expected == null
                      ? 'Not set'
                      : '${day(isoDate(_expected!))}${_expectedChosen ? '' : ' (from the crop\'s usual duration)'}',
                ),
                trailing: const Icon(Icons.edit_calendar),
                onTap: _pickExpected,
              ),
              const Divider(height: 32),
              Text('4. Area', style: Theme.of(context).textTheme.titleMedium),
              TextField(
                controller: _area,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: 'Area (acres)',
                  helperText:
                      'Plot: ${number(_plotArea)} acres · free now: ${number(freeArea(widget.plot, widget.plotCycles))} acres',
                ),
                onChanged: (_) {
                  if (_error != null) setState(() => _error = null);
                },
              ),
              if (others.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Already on this plot: ${others.map((c) => '${c.str('crop_name')} ${number(c.numVal('area_acres'))} ac').join(', ')}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: _saving
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.save),
                label: Text(_saving ? 'Saving…' : 'Save crop'),
              ),
            ],
          );
        },
      ),
    );
  }
}
