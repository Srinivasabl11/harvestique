import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'add_crop_screen.dart';
import '../../core/widgets/record_actions.dart';
import 'cycle_detail_screen.dart';
import 'edit_dialogs.dart';
import 'activities_screen.dart';
import 'expenses_screen.dart';

class FarmDetailScreen extends ConsumerStatefulWidget {
  const FarmDetailScreen({super.key, required this.farmId});

  final String farmId;

  @override
  ConsumerState<FarmDetailScreen> createState() => _FarmDetailScreenState();
}

class _FarmDetailScreenState extends ConsumerState<FarmDetailScreen> {
  Key _key = UniqueKey();

  /// Opens the Add Crop screen for one plot; reloads the farm when a crop was saved.
  Future<void> _addCrop(Map<String, dynamic> plot, List<Map<String, dynamic>> cycles) async {
    final onPlot = cycles.where((c) => c.str('plot_id') == plot.str('id')).toList();
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(builder: (_) => AddCropScreen(plot: plot, plotCycles: onPlot)),
    );
    if (saved == true && mounted) setState(() => _key = UniqueKey());
  }

  Future<void> _editFarm(Map<String, dynamic> farm) async {
    if (await showDialog<bool>(context: context, builder: (_) => EditFarmDialog(farm: farm)) == true && mounted) {
      showMessage(context, 'Farm updated');
      setState(() => _key = UniqueKey());
    }
  }

  Future<void> _setFarmActive(bool active) async {
    try {
      await ref.read(apiProvider).patch('/farms/${widget.farmId}', {'is_active': active});
      if (!mounted) return;
      showMessage(context, active ? 'Farm restored' : 'Farm archived');
      setState(() => _key = UniqueKey());
    } catch (e) {
      if (mounted) showMessage(context, (e is AppFailure ? e : mapDioError(e)).message, retry: () => _setFarmActive(active));
    }
  }

  Future<void> _deleteFarm() async {
    final api = ref.read(apiProvider);
    final result = await deleteOrFallback(
      context,
      what: 'this farm',
      delete: () => api.delete('/farms/${widget.farmId}'),
      historyCodes: {'farm_not_empty'},
      fallbackLabel: 'Archive farm',
      fallback: () => api.patch('/farms/${widget.farmId}', {'is_active': false}),
    );
    if (!mounted) return;
    if (result == RemoveResult.deleted) Navigator.of(context).pop();
    if (result == RemoveResult.fallback) setState(() => _key = UniqueKey());
  }

  Future<void> _plotAction(String action, Map<String, dynamic> plot) async {
    final api = ref.read(apiProvider);
    final id = plot.str('id');
    if (action == 'edit') {
      if (await showDialog<bool>(context: context, builder: (_) => EditPlotDialog(plot: plot)) == true && mounted) {
        showMessage(context, 'Plot updated');
        setState(() => _key = UniqueKey());
      }
      return;
    }
    final result = await deleteOrFallback(
      context,
      what: 'plot "${plot.str('name')}"',
      delete: () => api.delete('/plots/$id'),
      historyCodes: {'plot_not_empty'},
      fallbackLabel: 'Archive plot',
      fallback: () => api.patch('/plots/$id', {'is_active': false}),
    );
    if (mounted && (result == RemoveResult.deleted || result == RemoveResult.fallback)) setState(() => _key = UniqueKey());
  }

  /// "Add crop" from the Crops section: asks which plot when the farm has more than one.
  Future<void> _addCropFromCrops(List<Map<String, dynamic>> plots, List<Map<String, dynamic>> cycles) async {
    if (plots.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Add a plot first, then add crops to it.')),
      );
      return;
    }
    final plot = plots.length == 1
        ? plots.first
        : await showDialog<Map<String, dynamic>>(
            context: context,
            builder: (context) => SimpleDialog(
              title: const Text('Add the crop to which plot?'),
              children: [
                for (final p in plots)
                  SimpleDialogOption(
                    onPressed: () => Navigator.pop(context, p),
                    child: Padding(
                      padding: const EdgeInsets.all(8),
                      child: Text('${p.str('name')} · ${number(p.numVal('area_acres'))} acres'),
                    ),
                  ),
              ],
            ),
          );
    if (plot != null && mounted) await _addCrop(plot, cycles);
  }

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final id = widget.farmId;
    final base = await Future.wait([
      api.getObj('/farms/$id'),
      api.getPage('/farms/$id/plots'),
      api.getPage('/farms/$id/crop-cycles'),
    ]);
    Map<String, dynamic>? weather;
    Map<String, dynamic>? risk;
    try {
      weather = await api.getObj('/farms/$id/weather');
    } catch (_) {
      weather = null;
    }
    try {
      risk = await api.getObj('/farms/$id/risk');
    } catch (_) {
      risk = null;
    }
    return {
      'farm': base[0],
      'plots': base[1],
      'cycles': base[2],
      if (weather != null) 'weather': weather,
      if (risk != null) 'risk': risk,
    };
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Farm')),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () =>
            api.cached('farm:${widget.farmId}', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
        builder: (context, d, reload) {
          final farm = d.obj('farm');
          final plots = d.objs('plots');
          final cycles = d.objs('cycles');
          return ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              ListTile(
                title: Text(farm.str('name'), style: Theme.of(context).textTheme.headlineSmall),
                subtitle: Text(
                  '${number(farm.numVal('total_area_acres'))} acres'
                  '${farm.boolVal('is_active', true) ? '' : ' · ARCHIVED'}'
                  '${farm.numOrNull('latitude') == null ? ' · no location: edit the farm to add it for weather' : ''}',
                ),
                trailing: PopupMenuButton<String>(
                  tooltip: 'Farm actions',
                  onSelected: (v) => switch (v) {
                    'edit' => _editFarm(farm),
                    'archive' => _setFarmActive(false),
                    'restore' => _setFarmActive(true),
                    _ => _deleteFarm(),
                  },
                  itemBuilder: (context) => [
                    const PopupMenuItem(
                      value: 'edit',
                      child: ListTile(leading: Icon(Icons.edit_outlined), title: Text('Edit farm')),
                    ),
                    if (farm.boolVal('is_active', true))
                      const PopupMenuItem(
                        value: 'archive',
                        child: ListTile(leading: Icon(Icons.archive_outlined), title: Text('Archive farm')),
                      )
                    else
                      const PopupMenuItem(
                        value: 'restore',
                        child: ListTile(leading: Icon(Icons.unarchive_outlined), title: Text('Restore farm')),
                      ),
                    const PopupMenuItem(
                      value: 'delete',
                      child: ListTile(leading: Icon(Icons.delete_outline), title: Text('Delete farm')),
                    ),
                  ],
                ),
              ),
              if (d.objOrNull('weather') != null) _WeatherSection(weather: d.obj('weather')),
              if (d.objOrNull('risk') != null) _RiskSection(risk: d.obj('risk')),
              SectionCard(
                title: 'Plots',
                icon: Icons.grid_view,
                action: IconButton(
                  tooltip: 'Add plot',
                  icon: const Icon(Icons.add),
                  onPressed: () async {
                    if (await showDialog<bool>(context: context, builder: (_) => _AddPlotDialog(farmId: widget.farmId)) == true) {
                      setState(() => _key = UniqueKey());
                    }
                  },
                ),
                child: plots.isEmpty
                    ? const Text('No plots yet.')
                    : Column(
                        children: [
                          for (final p in plots)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(p.str('name')),
                              subtitle: Text(
                                '${number(p.numVal('area_acres'))} acres · ${label(p.str('irrigation_type', 'irrigation not set'))}'
                                '${_cropsOn(p, cycles)}',
                              ),
                              isThreeLine: _cropsOn(p, cycles).isNotEmpty,
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  TextButton(
                                    onPressed: () => _addCrop(p, cycles),
                                    child: const Text('Add crop'),
                                  ),
                                  PopupMenuButton<String>(
                                    tooltip: 'Plot actions',
                                    onSelected: (v) => _plotAction(v, p),
                                    itemBuilder: (context) => const [
                                      PopupMenuItem(
                                        value: 'edit',
                                        child: ListTile(leading: Icon(Icons.edit_outlined), title: Text('Edit plot')),
                                      ),
                                      PopupMenuItem(
                                        value: 'delete',
                                        child: ListTile(leading: Icon(Icons.delete_outline), title: Text('Delete plot')),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                        ],
                      ),
              ),
              SectionCard(
                title: 'Crops',
                icon: Icons.spa_outlined,
                action: TextButton.icon(
                  onPressed: () => _addCropFromCrops(plots, cycles),
                  icon: const Icon(Icons.add),
                  label: const Text('Add crop'),
                ),
                child: cycles.isEmpty
                    ? Text(
                        plots.isEmpty ? 'No crops yet. Add a plot first, then add crops to it.' : 'No crops yet. Tap "Add crop".',
                      )
                    : Column(
                        children: [
                          for (final c in cycles)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              leading: const Icon(Icons.spa),
                              title: Text(c.str('crop_name')),
                              subtitle: Text(
                                '${_plotName(plots, c.str('plot_id'))} · ${label(c.str('status'))} · '
                                '${number(c.numVal('area_acres'))} acres · sown ${day(c.str('sowing_date'))}',
                              ),
                              trailing: const Icon(Icons.chevron_right),
                              onTap: () async {
                                await Navigator.of(context)
                                    .push(MaterialPageRoute<void>(builder: (_) => CycleDetailScreen(cycleId: c.str('id'))));
                                await reload();
                              },
                            ),
                        ],
                      ),
              ),
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: ListTile(
                  leading: const Icon(Icons.receipt_long_outlined),
                  title: const Text('Expenses'),
                  subtitle: const Text('Seed, fertilizer, labour and other costs for this farm'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ExpensesScreen(farmId: widget.farmId, title: 'Expenses · ${farm.str('name')}'),
                    ),
                  ),
                ),
              ),
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: ListTile(
                  leading: const Icon(Icons.task_alt),
                  title: const Text('Field work log'),
                  subtitle: const Text('Irrigation, weeding, spraying and other work done on this farm'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ActivitiesScreen(farmId: widget.farmId, title: 'Field work · ${farm.str('name')}'),
                    ),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  static String _cropsOn(Map<String, dynamic> plot, List<Map<String, dynamic>> cycles) {
    final names = cycles
        .where((c) => c.str('plot_id') == plot.str('id') && c.str('status') != 'abandoned')
        .map((c) => '${c.str('crop_name')} (${label(c.str('status')).toLowerCase()})')
        .toList();
    return names.isEmpty ? '' : '\nCrops: ${names.join(', ')}';
  }

  static String _plotName(List<Map<String, dynamic>> plots, String plotId) {
    for (final p in plots) {
      if (p.str('id') == plotId) return p.str('name');
    }
    return 'Plot';
  }
}

class _WeatherSection extends StatelessWidget {
  const _WeatherSection({required this.weather});

  final Map<String, dynamic> weather;

  @override
  Widget build(BuildContext context) {
    final forecast = weather.objs('forecast');
    return SectionCard(
      title: 'Weather (${weather.str('status')})',
      icon: Icons.wb_cloudy_outlined,
      action: const DataKindChip('estimate'),
      child: forecast.isEmpty
          ? Text(weather.str('note'))
          : Column(
              children: [
                for (final d in forecast)
                  KeyValue(
                    day(d.str('day')),
                    '${number(d.numVal('tmin_c'))}–${number(d.numVal('tmax_c'))}°C · rain ${number(d.numVal('rain_mm'))} mm',
                  ),
                Text(weather.str('note'), style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
    );
  }
}

class _RiskSection extends StatelessWidget {
  const _RiskSection({required this.risk});

  final Map<String, dynamic> risk;

  @override
  Widget build(BuildContext context) {
    final worst = risk.obj('worst_by_category');
    return SectionCard(
      title: 'Risk',
      icon: Icons.shield_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          RiskChip(level: risk.str('overall_level'), score: risk.numOrNull('overall_score')),
          for (final e in worst.entries)
            KeyValue(label(e.key), e.value == null ? 'not assessed' : number(e.value is num ? e.value as num : null)),
          Text(risk.str('note'), style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}

class _AddPlotDialog extends ConsumerStatefulWidget {
  const _AddPlotDialog({required this.farmId});

  final String farmId;

  @override
  ConsumerState<_AddPlotDialog> createState() => _AddPlotDialogState();
}

class _AddPlotDialogState extends ConsumerState<_AddPlotDialog> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _area = TextEditingController();
  String _irrigation = 'rainfed';

  @override
  void dispose() {
    _name.dispose();
    _area.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const types = ['rainfed', 'borewell', 'canal', 'drip', 'sprinkler', 'tank', 'river', 'other'];
    return AlertDialog(
      title: const Text('Add plot'),
      content: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            FormText(controller: _name, label: 'Plot name', validator: requiredText),
            FormText(controller: _area, label: 'Area (acres)', keyboard: TextInputType.number, validator: positiveNumber),
            DropdownButtonFormField<String>(
              initialValue: _irrigation,
              decoration: const InputDecoration(labelText: 'Irrigation'),
              items: [for (final t in types) DropdownMenuItem(value: t, child: Text(label(t)))],
              onChanged: (v) => setState(() => _irrigation = v ?? 'rainfed'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          onPressed: () async {
            if (!_form.currentState!.validate()) return;
            final ok = await runAction(
              context,
              () => ref.read(apiProvider).post(
                '/farms/${widget.farmId}/plots',
                body: {
                  'name': _name.text.trim(),
                  'area_acres': double.parse(_area.text.trim()),
                  'irrigation_type': _irrigation,
                },
              ),
            );
            if (ok && context.mounted) Navigator.pop(context, true);
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}
