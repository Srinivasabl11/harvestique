import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';

const soilTypes = ['red', 'black', 'alluvial', 'laterite', 'sandy', 'loamy', 'clay', 'other'];
const irrigationTypes = ['rainfed', 'borewell', 'canal', 'drip', 'sprinkler', 'tank', 'river', 'other'];
const growthStages = ['germination', 'vegetative', 'flowering', 'fruiting', 'maturity'];
const healthStatuses = ['healthy', 'stressed', 'pest_affected', 'disease_affected', 'damaged'];

double? _num(String t) => t.trim().isEmpty ? null : double.tryParse(t.trim());

/// Farm coordinates: both or neither, each in range. Returns a problem or null.
String? validateCoordinates(String lat, String lon) {
  final a = _num(lat), b = _num(lon);
  if (lat.trim().isEmpty != lon.trim().isEmpty) return 'Enter both latitude and longitude, or leave both empty.';
  if (lat.trim().isEmpty) return null;
  if (a == null || b == null) return 'Latitude and longitude must be numbers, e.g. 12.2958 and 76.6394.';
  if (a < -90 || a > 90) return 'Latitude must be between -90 and 90.';
  if (b < -180 || b > 180) return 'Longitude must be between -180 and 180.';
  return null;
}

/// Shared shape of the edit dialogs: an error line, a saving state (one submission at a time) and Save/Cancel.
abstract class _EditState<T extends ConsumerStatefulWidget> extends ConsumerState<T> {
  String? error;
  bool saving = false;

  String get title;
  List<Widget> fields(BuildContext context);
  String? validate();
  Future<void> send(ApiClient api);

  Future<void> save() async {
    if (saving) return;
    final problem = validate();
    if (problem != null) {
      setState(() => error = problem);
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await send(ref.read(apiProvider));
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      final f = e is AppFailure ? e : mapDioError(e);
      if (mounted) {
        setState(() {
          error = f.message;
          saving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(title),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
              ...fields(context),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: saving ? null : () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: saving ? null : save, child: Text(saving ? 'Saving…' : 'Save')),
        ],
      );
}

Widget _text(TextEditingController c, String label, {bool number = false, int? max, String? helper}) => TextField(
      controller: c,
      maxLength: max,
      keyboardType: number ? const TextInputType.numberWithOptions(decimal: true, signed: true) : null,
      decoration: InputDecoration(labelText: label, helperText: helper, helperMaxLines: 3),
    );

Widget _dateTile(BuildContext context, String label, DateTime? value, ValueChanged<DateTime> onPick, {DateTime? last}) =>
    ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(label),
      subtitle: Text(value == null ? 'Not set' : day(isoDate(value))),
      trailing: const Icon(Icons.edit_calendar),
      onTap: () async {
        final d = await showDatePicker(
          context: context,
          initialDate: value ?? DateTime.now(),
          firstDate: DateTime(2000),
          lastDate: last ?? DateTime(2100),
        );
        if (d != null) onPick(d);
      },
    );

// ------------------------------------------------------------------ farm
class EditFarmDialog extends ConsumerStatefulWidget {
  const EditFarmDialog({super.key, required this.farm});

  final Map<String, dynamic> farm;

  @override
  ConsumerState<EditFarmDialog> createState() => _EditFarmState();
}

class _EditFarmState extends _EditState<EditFarmDialog> {
  late final _name = TextEditingController(text: widget.farm.str('name'));
  late final _village = TextEditingController(text: widget.farm.str('village'));
  late final _district = TextEditingController(text: widget.farm.str('district'));
  late final _area = TextEditingController(text: number(widget.farm.numVal('total_area_acres'), decimals: 3));
  late final _lat = TextEditingController(text: widget.farm.strOrNull('latitude') ?? '');
  late final _lon = TextEditingController(text: widget.farm.strOrNull('longitude') ?? '');

  @override
  String get title => 'Edit farm';

  @override
  List<Widget> fields(BuildContext context) => [
        _text(_name, 'Farm name', max: 120),
        _text(_village, 'Village (optional)', max: 100),
        _text(_district, 'District (optional)', max: 100),
        _text(_area, 'Total area (acres)', number: true),
        _text(
          _lat,
          'Latitude (optional)',
          number: true,
          helper: 'Needed for weather. In Google Maps, press and hold your field; the numbers shown are latitude, longitude.',
        ),
        _text(_lon, 'Longitude (optional)', number: true),
      ];

  @override
  String? validate() {
    if (_name.text.trim().isEmpty) return 'Give the farm a name.';
    final area = _num(_area.text);
    if (area == null || area <= 0) return 'Enter the total area in acres (more than 0).';
    return validateCoordinates(_lat.text, _lon.text);
  }

  @override
  Future<void> send(ApiClient api) async {
    String? opt(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
    await api.patch('/farms/${widget.farm.str('id')}', {
      'name': _name.text.trim(),
      'village': opt(_village),
      'district': opt(_district),
      'total_area_acres': _num(_area.text),
      'latitude': _num(_lat.text),
      'longitude': _num(_lon.text),
    });
  }
}

// ------------------------------------------------------------------ plot
class EditPlotDialog extends ConsumerStatefulWidget {
  const EditPlotDialog({super.key, required this.plot});

  final Map<String, dynamic> plot;

  @override
  ConsumerState<EditPlotDialog> createState() => _EditPlotState();
}

class _EditPlotState extends _EditState<EditPlotDialog> {
  late final _name = TextEditingController(text: widget.plot.str('name'));
  late final _area = TextEditingController(text: number(widget.plot.numVal('area_acres'), decimals: 3));
  late String? _irrigation = widget.plot.strOrNull('irrigation_type');
  late String? _soil = widget.plot.strOrNull('soil_type');

  @override
  String get title => 'Edit plot';

  @override
  List<Widget> fields(BuildContext context) => [
        _text(_name, 'Plot name', max: 100),
        _text(_area, 'Area (acres)', number: true),
        DropdownButtonFormField<String?>(
          initialValue: _irrigation,
          decoration: const InputDecoration(labelText: 'Irrigation'),
          items: [
            const DropdownMenuItem<String?>(child: Text('Not set')),
            for (final t in irrigationTypes) DropdownMenuItem(value: t, child: Text(label(t))),
          ],
          onChanged: (v) => setState(() => _irrigation = v),
        ),
        DropdownButtonFormField<String?>(
          initialValue: _soil,
          decoration: const InputDecoration(labelText: 'Soil'),
          items: [
            const DropdownMenuItem<String?>(child: Text('Not set')),
            for (final t in soilTypes) DropdownMenuItem(value: t, child: Text(label(t))),
          ],
          onChanged: (v) => setState(() => _soil = v),
        ),
      ];

  @override
  String? validate() {
    if (_name.text.trim().isEmpty) return 'Give the plot a name.';
    final area = _num(_area.text);
    if (area == null || area <= 0) return 'Enter the area in acres (more than 0).';
    return null;
  }

  @override
  Future<void> send(ApiClient api) => api.patch('/plots/${widget.plot.str('id')}', {
        'name': _name.text.trim(),
        'area_acres': _num(_area.text),
        'irrigation_type': _irrigation,
        'soil_type': _soil,
      });
}

// ------------------------------------------------------------------ crop cycle
class EditCycleDialog extends ConsumerStatefulWidget {
  const EditCycleDialog({super.key, required this.cycle});

  final Map<String, dynamic> cycle;

  @override
  ConsumerState<EditCycleDialog> createState() => _EditCycleState();
}

class _EditCycleState extends _EditState<EditCycleDialog> {
  late final _variety = TextEditingController(text: widget.cycle.str('variety'));
  late final _area = TextEditingController(text: number(widget.cycle.numVal('area_acres'), decimals: 3));
  late final _notes = TextEditingController(text: widget.cycle.str('notes'));
  late DateTime? _sowing = DateTime.tryParse(widget.cycle.str('sowing_date'));
  late DateTime? _expected = DateTime.tryParse(widget.cycle.str('expected_harvest_date'));

  @override
  String get title => 'Edit ${widget.cycle.str('crop_name')}';

  @override
  List<Widget> fields(BuildContext context) => [
        _text(_variety, 'Variety (optional)', max: 80),
        _text(_area, 'Area (acres)', number: true),
        _dateTile(context, 'Sowing date', _sowing, (d) => setState(() => _sowing = d)),
        _dateTile(context, 'Expected harvest date (optional)', _expected, (d) => setState(() => _expected = d)),
        TextField(controller: _notes, maxLines: 2, decoration: const InputDecoration(labelText: 'Notes (optional)')),
      ];

  @override
  String? validate() {
    final area = _num(_area.text);
    if (area == null || area <= 0) return 'Enter the area in acres (more than 0).';
    if (_sowing == null) return 'Choose the sowing date.';
    if (_expected != null && !_expected!.isAfter(_sowing!)) return 'The expected harvest must be after sowing.';
    return null;
  }

  @override
  Future<void> send(ApiClient api) => api.patch('/crop-cycles/${widget.cycle.str('id')}', {
        'variety': _variety.text.trim().isEmpty ? null : _variety.text.trim(),
        'area_acres': double.parse(_num(_area.text)!.toStringAsFixed(3)),
        'sowing_date': isoDate(_sowing!),
        'expected_harvest_date': _expected == null ? null : isoDate(_expected!),
        'notes': _notes.text.trim().isEmpty ? null : _notes.text.trim(),
      });
}

// ------------------------------------------------------------------ observation
class ObservationDialog extends ConsumerStatefulWidget {
  const ObservationDialog({super.key, required this.cycleId, this.observation});

  final String cycleId;
  final Map<String, dynamic>? observation;

  @override
  ConsumerState<ObservationDialog> createState() => _ObservationState();
}

class _ObservationState extends _EditState<ObservationDialog> {
  late DateTime _date = DateTime.tryParse(widget.observation?.str('observed_on') ?? '') ?? DateTime.now();
  late String _health = widget.observation?.str('health_status', 'healthy') ?? 'healthy';
  late String? _stage = widget.observation?.strOrNull('growth_stage');
  late final _loss = TextEditingController(text: widget.observation?.strOrNull('estimated_loss_percent') ?? '');
  late final _notes = TextEditingController(text: widget.observation?.str('notes') ?? '');

  @override
  String get title => widget.observation == null ? 'New field observation' : 'Edit observation';

  @override
  List<Widget> fields(BuildContext context) => [
        _dateTile(context, 'Date seen', _date, (d) => setState(() => _date = d), last: DateTime.now()),
        DropdownButtonFormField<String>(
          initialValue: _health,
          decoration: const InputDecoration(labelText: 'How does the crop look?'),
          items: [for (final h in healthStatuses) DropdownMenuItem(value: h, child: Text(label(h)))],
          onChanged: (v) => setState(() => _health = v ?? 'healthy'),
        ),
        DropdownButtonFormField<String?>(
          initialValue: _stage,
          decoration: const InputDecoration(labelText: 'Growth stage (optional)'),
          items: [
            const DropdownMenuItem<String?>(child: Text('Not set')),
            for (final s in growthStages) DropdownMenuItem(value: s, child: Text(label(s))),
          ],
          onChanged: (v) => setState(() => _stage = v),
        ),
        _text(_loss, 'Estimated loss % (optional)', number: true),
        TextField(controller: _notes, maxLines: 2, decoration: const InputDecoration(labelText: 'Notes (optional)')),
      ];

  @override
  String? validate() {
    final loss = _num(_loss.text);
    if (_loss.text.trim().isNotEmpty && (loss == null || loss < 0 || loss > 100)) {
      return 'Loss must be a percentage from 0 to 100.';
    }
    return null;
  }

  @override
  Future<void> send(ApiClient api) async {
    final body = <String, dynamic>{
      'observed_on': isoDate(_date),
      'health_status': _health,
      'growth_stage': _stage,
      'estimated_loss_percent': _num(_loss.text),
      'notes': _notes.text.trim().isEmpty ? null : _notes.text.trim(),
    };
    if (widget.observation == null) {
      body.removeWhere((k, v) => v == null);
      await api.post('/crop-cycles/${widget.cycleId}/observations', body: body);
    } else {
      await api.patch('/observations/${widget.observation!.str('id')}', body);
    }
  }
}

// ------------------------------------------------------------------ harvest correction
class HarvestCorrectionDialog extends ConsumerStatefulWidget {
  const HarvestCorrectionDialog({super.key, required this.cycleId, required this.currentKg});

  final String cycleId;
  final double currentKg;

  @override
  ConsumerState<HarvestCorrectionDialog> createState() => _HarvestCorrectionState();
}

class _HarvestCorrectionState extends _EditState<HarvestCorrectionDialog> {
  late final _qty = TextEditingController(text: number(widget.currentKg, decimals: 3));
  final _reason = TextEditingController();

  @override
  String get title => 'Correct the recorded harvest';

  @override
  List<Widget> fields(BuildContext context) => [
        const Text(
          'Only possible before any of this harvest is received at a collection hub. The old value, the time and '
          'your reason are kept, and every prediction is re-checked against the corrected quantity.',
          style: TextStyle(fontSize: 12),
        ),
        _text(_qty, 'Correct quantity (kg)', number: true),
        _text(_reason, 'Why the change? (required)', max: 255),
      ];

  @override
  String? validate() {
    final q = _num(_qty.text);
    if (q == null || q < 0) return 'Enter the weighed quantity in kg (0 or more).';
    if (_reason.text.trim().length < 3) return 'Write a short reason (at least 3 characters).';
    return null;
  }

  @override
  Future<void> send(ApiClient api) => api.patch(
        '/crop-cycles/${widget.cycleId}/harvest-actual',
        {'quantity_kg': _num(_qty.text), 'reason': _reason.text.trim()},
      );
}
