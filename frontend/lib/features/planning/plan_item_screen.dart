import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'plan_forms.dart';

/// Add a crop to an income plan, or edit one. Two ways in: the farmer's own numbers, or (for a plan linked to a
/// farm) a crop's saved harvest prediction, whose p10/p50/p90 become the yield range. Full screen so every field
/// and every server message is visible.
class PlanItemScreen extends ConsumerStatefulWidget {
  const PlanItemScreen({super.key, required this.plan, this.item});

  /// The plan as returned by GET /crop-plans/{id} (items included).
  final Map<String, dynamic> plan;

  /// The item being edited; null when adding.
  final Map<String, dynamic>? item;

  @override
  ConsumerState<PlanItemScreen> createState() => _PlanItemScreenState();
}

class _PlanItemScreenState extends ConsumerState<PlanItemScreen> {
  late final Future<Map<String, dynamic>> _refs = _loadRefs();
  final _name = TextEditingController();
  final _area = TextEditingController();
  final _duration = TextEditingController();
  final _yield = [TextEditingController(), TextEditingController(), TextEditingController()];
  final _price = [TextEditingController(), TextEditingController(), TextEditingController()];
  final _cost = {for (final (k, _) in costFields) k: TextEditingController()};
  bool _fromPrediction = false;
  String? _cropId;
  String? _plotId;
  String? _cycleId;
  Map<String, dynamic>? _prediction; // latest usable prediction of _cycleId
  String? _predictionNote;
  DateTime? _sowing;
  String _risk = 'medium';
  String _basis = 'local_knowledge';
  String? _error;
  bool _saving = false;

  bool get _editing => widget.item != null;
  double get _planLand => widget.plan.numVal('available_land_acres');
  String? get _farmId => widget.plan.strOrNull('farm_id');

  @override
  void initState() {
    super.initState();
    final it = widget.item;
    if (it != null) {
      _cropId = it.strOrNull('crop_id');
      _name.text = it.str('crop_name');
      _area.text = number(it.numVal('area_acres'), decimals: 3);
      _duration.text = '${it.intVal('duration_days')}';
      _sowing = DateTime.tryParse(it.str('sowing_date'));
      for (final (i, k) in ['low', 'expected', 'high'].indexed) {
        _yield[i].text = _plain(it.obj('yield_per_acre_kg').numOrNull(k));
        _price[i].text = _plain(it.obj('price_per_kg').numOrNull(k));
      }
      for (final (k, _) in costFields) {
        final v = it.obj('cost').numOrNull(k);
        _cost[k]!.text = v == null || v == 0 ? '' : _plain(v);
      }
      _risk = it.str('declared_risk', 'medium');
      _basis = it.str('estimate_basis', 'local_knowledge');
    }
  }

  static String _plain(double? v) => v == null ? '' : (v == v.roundToDouble() ? v.toStringAsFixed(0) : '$v');

  Future<Map<String, dynamic>> _loadRefs() async {
    final api = ref.read(apiProvider);
    final farm = _farmId;
    final r = await Future.wait([
      api.getAll('/crops'),
      if (farm != null) api.getPage('/farms/$farm/plots') else Future.value(<Map<String, dynamic>>[]),
      if (farm != null) api.getPage('/farms/$farm/crop-cycles') else Future.value(<Map<String, dynamic>>[]),
    ]);
    return {'crops': r[0], 'plots': r[1], 'cycles': r[2]};
  }

  @override
  void dispose() {
    for (final c in [_name, _area, _duration, ..._yield, ..._price, ..._cost.values]) {
      c.dispose();
    }
    super.dispose();
  }

  List<(String, DateTime)> get _otherEntries => [
        for (final it in widget.plan.objs('items'))
          if (it.str('id') != widget.item?.str('id') && DateTime.tryParse(it.str('sowing_date')) != null)
            (it.str('crop_name'), DateTime.parse(it.str('sowing_date'))),
      ];

  Map<String, String> get _costTexts => {for (final e in _cost.entries) e.key: e.value.text};

  Future<void> _pickCycle(String? cycleId) async {
    setState(() {
      _cycleId = cycleId;
      _prediction = null;
      _predictionNote = cycleId == null ? null : 'Loading the latest prediction…';
      _error = null;
    });
    if (cycleId == null) return;
    try {
      final preds = await ref.read(apiProvider).getPage('/crop-cycles/$cycleId/predictions');
      final usable = preds.where((p) => p.objOrNull('yield_per_acre_kg') != null).toList()
        ..sort((a, b) => b.intVal('version').compareTo(a.intVal('version')));
      if (!mounted || _cycleId != cycleId) return;
      setState(() {
        _prediction = usable.isEmpty ? null : usable.first;
        _predictionNote = usable.isEmpty
            ? 'This crop has no usable harvest prediction yet. Open the crop and tap "Predict", or enter your own numbers.'
            : null;
      });
    } catch (e) {
      if (mounted) setState(() => _predictionNote = mapDioError(e).message);
    }
  }

  void _pickCrop(String? id, List<Map<String, dynamic>> crops) {
    setState(() {
      _cropId = id;
      _error = null;
      if (id != null) {
        final c = crops.firstWhere((c) => c.str('id') == id);
        _name.text = c.str('name');
        if (_duration.text.trim().isEmpty || !_editing) _duration.text = '${c.intVal('typical_duration_days')}';
      }
    });
  }

  void _pickPlot(String? id, List<Map<String, dynamic>> plots) {
    setState(() {
      _plotId = id;
      if (id != null) _area.text = number(plots.firstWhere((p) => p.str('id') == id).numVal('area_acres'), decimals: 3);
    });
  }

  Future<void> _save() async {
    final String? problem;
    if (_fromPrediction) {
      problem = _prediction == null
          ? 'Choose a crop that has a harvest prediction.'
          : validateRange('Price', '₹ per kg', _price[0].text, _price[1].text, _price[2].text, maxDecimals: 2) ??
              validateCosts(_costTexts);
    } else {
      problem = validatePlanItem(
        cropName: _name.text,
        areaText: _area.text,
        planLand: _planLand,
        sowing: _sowing,
        durationText: _duration.text,
        yieldTexts: [for (final c in _yield) c.text],
        priceTexts: [for (final c in _price) c.text],
        costTexts: _costTexts,
        otherEntries: _otherEntries,
      );
    }
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final api = ref.read(apiProvider);
    final priceTexts = [for (final c in _price) c.text];
    try {
      if (_fromPrediction) {
        await api.post(
          '/crop-plans/${widget.plan.str('id')}/items/from-prediction',
          body: fromPredictionBody(
            predictionId: _prediction!.str('id'),
            priceTexts: priceTexts,
            costTexts: _costTexts,
            risk: _risk,
          ),
        );
      } else {
        final body = planItemBody(
          cropId: _cropId,
          cropName: _name.text,
          area: parseNumber(_area.text)!,
          sowing: _sowing!,
          durationDays: int.parse(_duration.text.trim()),
          yieldTexts: [for (final c in _yield) c.text],
          priceTexts: priceTexts,
          costTexts: _costTexts,
          risk: _risk,
          basis: _basis,
        );
        if (_editing) {
          if (_cropId == null) body['crop_id'] = null; // a typed crop name unlinks the catalog crop
          await api.patch('/crop-plan-items/${widget.item!.str('id')}', body);
        } else {
          await api.post('/crop-plans/${widget.plan.str('id')}/items', body: body);
        }
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_editing ? 'Crop updated' : 'Crop added to the plan')));
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

  Widget _num(TextEditingController c, String labelText, {String? helper, Key? key}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: TextField(
          key: key,
          controller: c,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(labelText: labelText, helperText: helper),
          onChanged: (_) {
            if (_error != null) setState(() => _error = null);
          },
        ),
      );

  Widget _triple(String title, String unit, List<TextEditingController> cs, String keyPrefix) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 8),
          Text('$title ($unit)', style: Theme.of(context).textTheme.titleSmall),
          Row(
            children: [
              Expanded(child: _num(cs[0], 'Low', key: Key('$keyPrefix-low'))),
              const SizedBox(width: 8),
              Expanded(child: _num(cs[1], 'Expected', key: Key('$keyPrefix-expected'))),
              const SizedBox(width: 8),
              Expanded(child: _num(cs[2], 'High', key: Key('$keyPrefix-high'))),
            ],
          ),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(_editing ? 'Edit crop · ${widget.item!.str('crop_name')}' : 'Add crop to plan')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _refs,
        builder: (context, snap) {
          if (snap.hasError) return ErrorPanel(error: snap.error!, onRetry: () => Navigator.of(context).pop());
          if (!snap.hasData) return const Center(child: CircularProgressIndicator(semanticsLabel: 'Loading'));
          final crops = snap.data!.objs('crops');
          final plots = snap.data!.objs('plots');
          final cycles = snap.data!.objs('cycles').where((c) => c.str('status') != 'abandoned').toList();
          return ListView(
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
              if (!_editing && _farmId != null) ...[
                SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(value: false, label: Text('My own numbers'), icon: Icon(Icons.edit_note)),
                    ButtonSegment(value: true, label: Text('From a prediction'), icon: Icon(Icons.insights)),
                  ],
                  selected: {_fromPrediction},
                  onSelectionChanged: (s) => setState(() {
                    _fromPrediction = s.first;
                    _error = null;
                  }),
                ),
                const SizedBox(height: 12),
              ],
              if (_fromPrediction) ...[
                Text('1. Crop on your farm', style: Theme.of(context).textTheme.titleMedium),
                if (cycles.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(8),
                    child: Text('This farm has no crops yet. Add a crop to a plot first.'),
                  )
                else
                  DropdownButtonFormField<String?>(
                    initialValue: _cycleId,
                    isExpanded: true,
                    hint: const Text('Choose a crop'),
                    items: [
                      for (final c in cycles)
                        DropdownMenuItem<String?>(
                          value: c.str('id'),
                          child: Text(
                            '${c.str('crop_name')} · ${number(c.numVal('area_acres'))} ac · sown ${day(c.str('sowing_date'))}',
                          ),
                        ),
                    ],
                    onChanged: _pickCycle,
                  ),
                if (_predictionNote != null) Padding(padding: const EdgeInsets.all(8), child: Text(_predictionNote!)),
                if (_prediction != null)
                  SectionCard(
                    title: 'Prediction v${_prediction!.intVal('version')} (yield per acre)',
                    icon: Icons.insights,
                    action: const DataKindChip('estimate'),
                    child: Text(
                      '${kg(_prediction!.obj('yield_per_acre_kg').numOrNull('p10'))} / '
                      '${kg(_prediction!.obj('yield_per_acre_kg').numOrNull('p50'))} / '
                      '${kg(_prediction!.obj('yield_per_acre_kg').numOrNull('p90'))}  (low / expected / high)\n'
                      'Area, sowing date and duration come from the crop.',
                    ),
                  ),
              ] else ...[
                Text('1. Crop', style: Theme.of(context).textTheme.titleMedium),
                DropdownButtonFormField<String?>(
                  initialValue: crops.any((c) => c.str('id') == _cropId) ? _cropId : null,
                  isExpanded: true,
                  items: [
                    const DropdownMenuItem<String?>(child: Text('Other crop (type the name below)')),
                    for (final c in crops)
                      DropdownMenuItem<String?>(
                        value: c.str('id'),
                        child: Text([c.str('name'), if (c.str('local_name').isNotEmpty) c.str('local_name')].join(' · ')),
                      ),
                  ],
                  onChanged: (v) => _pickCrop(v, crops),
                ),
                if (_cropId == null)
                  TextField(controller: _name, decoration: const InputDecoration(labelText: 'Crop name'), maxLength: 80),
                if (plots.isNotEmpty)
                  DropdownButtonFormField<String?>(
                    initialValue: _plotId,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Plot (optional: fills in its area)'),
                    items: [
                      const DropdownMenuItem<String?>(child: Text('No particular plot')),
                      for (final p in plots)
                        DropdownMenuItem<String?>(
                          value: p.str('id'),
                          child: Text('${p.str('name')} · ${number(p.numVal('area_acres'))} acres'),
                        ),
                    ],
                    onChanged: (v) => _pickPlot(v, plots),
                  ),
                _num(_area, 'Area (acres)', helper: 'Plan land: ${number(_planLand)} acres'),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Sowing date'),
                  subtitle: Text(_sowing == null ? 'Not chosen' : day(isoDate(_sowing!))),
                  trailing: const Icon(Icons.edit_calendar),
                  onTap: () async {
                    final d = await pickDate(context, _sowing ?? DateTime.now());
                    if (d != null && mounted) setState(() => _sowing = d);
                  },
                ),
                _num(_duration, 'Days from sowing to harvest'),
                _triple('2. Expected yield', 'kg per acre', _yield, 'yield'),
                DropdownButtonFormField<String>(
                  initialValue: _basis,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Where do the yield and price numbers come from?'),
                  items: [for (final (v, t) in estimateBases) DropdownMenuItem(value: v, child: Text(t))],
                  onChanged: (v) => setState(() => _basis = v ?? 'local_knowledge'),
                ),
              ],
              _triple(
                _fromPrediction ? '2. Price you expect' : '3. Price you expect',
                '₹ per kg, after transport and commission',
                _price,
                'price',
              ),
              const SizedBox(height: 12),
              Text(
                _fromPrediction ? '3. Costs (leave empty for 0)' : '4. Costs (leave empty for 0)',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              for (final (k, t) in costFields) _num(_cost[k]!, t),
              DropdownButtonFormField<String>(
                initialValue: _risk,
                decoration: const InputDecoration(labelText: 'How risky is this crop for you?'),
                items: [for (final r in riskLevels) DropdownMenuItem(value: r, child: Text(label(r)))],
                onChanged: (v) => setState(() => _risk = v ?? 'medium'),
              ),
              const SizedBox(height: 8),
              Text(
                'These are your estimates. Harvestique calculates ranges from them; it does not know market prices.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: _saving
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.save),
                label: Text(_saving ? 'Saving…' : (_editing ? 'Save changes' : 'Add to plan')),
              ),
            ],
          );
        },
      ),
    );
  }
}
