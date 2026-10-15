import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/record_actions.dart';
import '../crop_health/crop_health_screen.dart';
import 'edit_dialogs.dart';
import 'activities_screen.dart';
import 'expenses_screen.dart';

/// One crop cycle: prediction (with confidence, risk and data sources), observations, crop health, harvest
/// recording and prediction feedback.
class CycleDetailScreen extends ConsumerStatefulWidget {
  const CycleDetailScreen({super.key, required this.cycleId});

  final String cycleId;

  @override
  ConsumerState<CycleDetailScreen> createState() => _CycleDetailScreenState();
}

class _CycleDetailScreenState extends ConsumerState<CycleDetailScreen> {
  Key _key = UniqueKey();

  void _refresh() => setState(() => _key = UniqueKey());

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final id = widget.cycleId;
    final r = await Future.wait([
      api.getObj('/crop-cycles/$id'),
      api.getPage('/crop-cycles/$id/predictions'),
      api.getPage('/crop-cycles/$id/observations'),
      api.getList('/crop-health/analyses', query: {'crop_cycle_id': id}),
    ]);
    Map<String, dynamic>? feedback;
    if (r[0] is Map<String, dynamic> && (r[0] as Map<String, dynamic>).str('status') == 'harvested') {
      try {
        feedback = await api.getObj('/crop-cycles/$id/feedback');
      } catch (_) {
        feedback = null;
      }
    }
    final preds = (r[1] as List<Map<String, dynamic>>)..sort((a, b) => b.intVal('version').compareTo(a.intVal('version')));
    return {
      'cycle': r[0],
      'predictions': preds,
      'observations': r[2],
      'health': r[3],
      if (feedback != null) 'feedback': feedback,
    };
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Crop')),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () =>
            api.cached('cycle:${widget.cycleId}', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
        builder: (context, d, reload) {
          final c = d.obj('cycle');
          final preds = d.objs('predictions');
          final growing = c.str('status') == 'growing' || c.str('status') == 'planned';
          return ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              ListTile(
                title: Text(c.str('crop_name'), style: Theme.of(context).textTheme.headlineSmall),
                subtitle: Text(
                    '${label(c.str('status'))} · ${number(c.numVal('area_acres'))} acres · sown ${day(c.str('sowing_date'))}'
                    '${c.strOrNull('expected_harvest_date') == null ? '' : ' · you expect harvest ${day(c.str('expected_harvest_date'))}'}'),
                trailing: PopupMenuButton<String>(
                  tooltip: 'Crop actions',
                  onSelected: (v) => _cropAction(v, c),
                  itemBuilder: (context) => [
                    if (growing) ...[
                      const PopupMenuItem(
                        value: 'edit',
                        child: ListTile(leading: Icon(Icons.edit_outlined), title: Text('Edit crop details')),
                      ),
                      const PopupMenuItem(
                        value: 'abandon',
                        child: ListTile(leading: Icon(Icons.block), title: Text('Mark abandoned')),
                      ),
                    ],
                    if (d.objOrNull('feedback') != null && d.obj('feedback').objOrNull('actual') != null)
                      const PopupMenuItem(
                        value: 'correct',
                        child: ListTile(leading: Icon(Icons.scale), title: Text('Correct recorded harvest')),
                      ),
                    const PopupMenuItem(
                      value: 'delete',
                      child: ListTile(leading: Icon(Icons.delete_outline), title: Text('Delete crop')),
                    ),
                  ],
                ),
              ),
              if (preds.isEmpty)
                SectionCard(
                  title: 'Harvest prediction',
                  icon: Icons.insights,
                  action: growing ? _predictButton(context) : null,
                  child: const Text('No prediction yet. Add your own estimate for a better first prediction.'),
                )
              else
                _PredictionCard(p: preds.first, action: growing ? _predictButton(context) : null),
              if (preds.length > 1)
                SectionCard(
                  title: 'Prediction history',
                  icon: Icons.history,
                  child: Column(
                    children: [
                      for (final p in preds)
                        KeyValue(
                          'v${p.intVal('version')} · ${day(p.str('created_at'))}',
                          p.objOrNull('quantity_kg') == null
                              ? 'not enough data'
                              : '${kg(p.obj('quantity_kg').numVal('p10'))} – ${kg(p.obj('quantity_kg').numVal('p90'))}',
                        ),
                    ],
                  ),
                ),
              _ObservationsCard(cycleId: widget.cycleId, observations: d.objs('observations'), onChanged: _refresh),
              SectionCard(
                title: 'Expenses',
                icon: Icons.receipt_long_outlined,
                action: TextButton(onPressed: () => _openExpenses(c), child: const Text('Open')),
                child: const Text('Record what you spend on this crop: seed, fertilizer, labour and more.'),
              ),
              SectionCard(
                title: 'Field work',
                icon: Icons.task_alt,
                action: TextButton(onPressed: () => _openActivities(c), child: const Text('Open')),
                child: const Text('Log irrigation, weeding, spraying and other work on this crop.'),
              ),
              SectionCard(
                title: 'Crop health checks',
                icon: Icons.eco_outlined,
                action: TextButton(
                  onPressed: () async {
                    await Navigator.of(context)
                        .push(MaterialPageRoute<void>(builder: (_) => CropHealthScreen(cycleId: widget.cycleId)));
                    _refresh();
                  },
                  child: const Text('New photo'),
                ),
                child: d.objs('health').isEmpty
                    ? const Text('No photo checks yet.')
                    : Column(
                        children: [
                          for (final h in d.objs('health').take(5))
                            KeyValue(day(h.str('created_at')), label(h.str('label')), kind: 'estimate'),
                        ],
                      ),
              ),
              if (growing)
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.scale),
                    label: const Text('Record harvest (weighed quantity)'),
                    onPressed: () async {
                      if (await showDialog<bool>(context: context, builder: (_) => _HarvestDialog(cycleId: widget.cycleId)) ==
                          true) {
                        _refresh();
                      }
                    },
                  ),
                ),
              if (d.objOrNull('feedback') != null) _FeedbackCard(report: d.obj('feedback')),
            ],
          );
        },
      ),
    );
  }

  /// Expenses are filed under the farm; a crop cycle only knows its plot, so look the farm up first.
  Future<void> _openExpenses(Map<String, dynamic> cycle) async {
    String? farmId;
    final ok = await runAction(context, () async {
      farmId = (await ref.read(apiProvider).getObj('/plots/${cycle.str('plot_id')}')).strOrNull('farm_id');
    });
    if (!ok || farmId == null || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ExpensesScreen(farmId: farmId!, cycleId: widget.cycleId, title: 'Expenses · ${cycle.str('crop_name')}'),
      ),
    );
  }

  Future<void> _openActivities(Map<String, dynamic> cycle) async {
    String? farmId;
    final ok = await runAction(context, () async {
      farmId = (await ref.read(apiProvider).getObj('/plots/${cycle.str('plot_id')}')).strOrNull('farm_id');
    });
    if (!ok || farmId == null || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) =>
            ActivitiesScreen(farmId: farmId!, cycleId: widget.cycleId, title: 'Field work · ${cycle.str('crop_name')}'),
      ),
    );
  }

  Future<void> _cropAction(String action, Map<String, dynamic> c) async {
    final api = ref.read(apiProvider);
    switch (action) {
      case 'edit':
        if (await showDialog<bool>(context: context, builder: (_) => EditCycleDialog(cycle: c)) == true && mounted) {
          showMessage(context, 'Crop updated');
          _refresh();
        }
      case 'abandon':
        if (!await confirmAction(
              context,
              title: 'Mark ${c.str('crop_name')} as abandoned?',
              message: 'Use this when the crop failed or was removed. Its land becomes free; its records are kept.',
              confirm: 'Mark abandoned',
            ) ||
            !mounted) {
          return;
        }
        await runAction(
          context,
          () => api.patch('/crop-cycles/${widget.cycleId}', {'status': 'abandoned'}),
          success: 'Marked abandoned',
        );
        _refresh();
      case 'correct':
        final actual = (await api.getObj('/crop-cycles/${widget.cycleId}/feedback')).obj('actual');
        if (!mounted) return;
        final ok = await showDialog<bool>(
          context: context,
          builder: (_) => HarvestCorrectionDialog(cycleId: widget.cycleId, currentKg: actual.numVal('quantity_kg')),
        );
        if (ok == true && mounted) {
          showMessage(context, 'Harvest corrected');
          _refresh();
        }
      case 'delete':
        final result = await deleteOrFallback(
          context,
          what: 'this crop',
          delete: () => api.delete('/crop-cycles/${widget.cycleId}'),
          historyCodes: {'cycle_not_empty'},
          fallbackLabel: 'Mark abandoned',
          fallback: () => api.patch('/crop-cycles/${widget.cycleId}', {'status': 'abandoned'}),
        );
        if (!mounted) return;
        if (result == RemoveResult.deleted) Navigator.of(context).pop();
        if (result == RemoveResult.fallback) _refresh();
    }
  }

  Widget _predictButton(BuildContext context) => TextButton.icon(
        icon: const Icon(Icons.refresh),
        label: const Text('Predict'),
        onPressed: () async {
          if (await showDialog<bool>(context: context, builder: (_) => _PredictDialog(cycleId: widget.cycleId)) == true) {
            _refresh();
          }
        },
      );
}

class _PredictionCard extends StatelessWidget {
  const _PredictionCard({required this.p, this.action});

  final Map<String, dynamic> p;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final q = p.objOrNull('quantity_kg');
    final t = p.obj('timing');
    final conf = p.obj('confidence');
    final risk = p.obj('risk');
    final kind = p.str('output_kind', 'estimate');
    return SectionCard(
      title: 'Harvest prediction (v${p.intVal('version')})',
      icon: Icons.insights,
      action: action,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              DataKindChip(kind),
              const SizedBox(width: 8),
              Expanded(child: Text(p.str('model_name'), style: Theme.of(context).textTheme.bodySmall)),
            ],
          ),
          const SizedBox(height: 8),
          if (q == null)
            const Text('Not enough data to predict a quantity yet. Add your own estimate or record past harvests.')
          else ...[
            Text('${kg(q.numVal('p10'))} – ${kg(q.numVal('p90'))}', style: Theme.of(context).textTheme.headlineSmall),
            Text(
              'Middle estimate ${kg(q.numVal('p50'))}. Buyers can only be promised the lower figure (${kg(q.numVal('p10'))}).',
            ),
          ],
          const SizedBox(height: 8),
          KeyValue('Harvest may start', '${day(t.str('start_p10'))} – ${day(t.str('start_p90'))}', kind: 'estimate'),
          const SizedBox(height: 8),
          ConfidenceBadge(score: conf.numVal('score'), level: conf.str('level'), basis: conf.str('basis')),
          const SizedBox(height: 8),
          RiskChip(level: risk.str('overall_level'), score: risk.numOrNull('overall_score')),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('Why this prediction?'),
            children: [
              for (final s in p.objs('sources').where((s) => s.boolVal('used')))
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(s.str('name')),
                  subtitle: Text(s.str('detail')),
                  trailing: DataKindChip(s.str('kind')),
                ),
              for (final e in p.strs('explanations'))
                ListTile(dense: true, contentPadding: EdgeInsets.zero, leading: const Icon(Icons.info_outline), title: Text(e)),
              for (final w in p.strs('warnings'))
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.warning_amber_rounded),
                  title: Text(w),
                ),
            ],
          ),
          Text(p.str('disclaimer'), style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}

class _PredictDialog extends ConsumerStatefulWidget {
  const _PredictDialog({required this.cycleId});

  final String cycleId;

  @override
  ConsumerState<_PredictDialog> createState() => _PredictDialogState();
}

class _PredictDialogState extends ConsumerState<_PredictDialog> {
  final _low = TextEditingController();
  final _expected = TextEditingController();
  final _high = TextEditingController();

  @override
  void dispose() {
    _low.dispose();
    _expected.dispose();
    _high.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Predict harvest'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Optional: your own yield estimate per acre (kg). It is combined with your past harvests, '
                'weather and the crop reference, and labelled as your estimate.'),
            FormText(controller: _low, label: 'Bad year (kg/acre)', keyboard: TextInputType.number),
            FormText(controller: _expected, label: 'Normal year (kg/acre)', keyboard: TextInputType.number),
            FormText(controller: _high, label: 'Good year (kg/acre)', keyboard: TextInputType.number),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          onPressed: () async {
            final lo = double.tryParse(_low.text.trim());
            final ex = double.tryParse(_expected.text.trim());
            final hi = double.tryParse(_high.text.trim());
            final body = <String, dynamic>{
              if (lo != null && ex != null && hi != null) 'farmer_estimate_per_acre': {'low': lo, 'expected': ex, 'high': hi},
            };
            final ok = await runAction(
              context,
              () => ref.read(apiProvider).post('/crop-cycles/${widget.cycleId}/predictions', body: body),
              success: 'New prediction saved',
            );
            if (ok && context.mounted) Navigator.pop(context, true);
          },
          child: const Text('Predict'),
        ),
      ],
    );
  }
}

class _ObservationsCard extends ConsumerWidget {
  const _ObservationsCard({required this.cycleId, required this.observations, required this.onChanged});

  final String cycleId;
  final List<Map<String, dynamic>> observations;
  final VoidCallback onChanged;

  Future<void> _observationAction(BuildContext context, WidgetRef ref, Map<String, dynamic> o) async {
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Edit observation'),
              onTap: () => Navigator.pop(context, 'edit'),
            ),
            ListTile(
              leading: const Icon(Icons.delete_outline),
              title: const Text('Delete observation'),
              onTap: () => Navigator.pop(context, 'delete'),
            ),
          ],
        ),
      ),
    );
    if (!context.mounted || action == null) return;
    if (action == 'edit') {
      final ok = await showDialog<bool>(context: context, builder: (_) => ObservationDialog(cycleId: cycleId, observation: o));
      if (ok == true && context.mounted) {
        showMessage(context, 'Observation updated');
        onChanged();
      }
      return;
    }
    if (!await confirmAction(
      context,
      title: 'Delete this observation?',
      message: '${day(o.str('observed_on'))}: ${label(o.str('health_status'))}',
    )) {
      return;
    }
    if (!context.mounted) return;
    final ok = await runAction(
      context,
      () => ref.read(apiProvider).delete('/observations/${o.str('id')}'),
      success: 'Observation deleted',
    );
    if (ok) onChanged();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SectionCard(
      title: 'Field observations',
      icon: Icons.visibility_outlined,
      action: TextButton(
        onPressed: () async {
          final ok = await showDialog<bool>(context: context, builder: (_) => ObservationDialog(cycleId: cycleId));
          if (ok == true && context.mounted) {
            showMessage(context, 'Observation saved');
            onChanged();
          }
        },
        child: const Text('Add'),
      ),
      child: observations.isEmpty
          ? const Text('No observations yet. Regular checks improve predictions.')
          : Column(
              children: [
                for (final o in observations.take(5))
                  InkWell(
                    onTap: () => _observationAction(context, ref, o),
                    child: KeyValue(
                      day(o.str('observed_on')),
                      '${label(o.str('health_status'))}${o.strOrNull('notes') == null ? '' : ' · ${o.str('notes')}'}',
                      kind: 'measured',
                    ),
                  ),
                if (observations.isNotEmpty)
                  Text('Tap an observation to edit or delete it.', style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
    );
  }
}

class _HarvestDialog extends ConsumerStatefulWidget {
  const _HarvestDialog({required this.cycleId});

  final String cycleId;

  @override
  ConsumerState<_HarvestDialog> createState() => _HarvestDialogState();
}

class _HarvestDialogState extends ConsumerState<_HarvestDialog> {
  final _qty = TextEditingController();
  DateTime _date = DateTime.now();

  @override
  void dispose() {
    _qty.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Record harvest'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('Enter the weighed quantity. It is used for delivery, and to measure how accurate the predictions were.'),
          FormText(controller: _qty, label: 'Harvested quantity (kg)', keyboard: TextInputType.number),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Harvest date'),
            subtitle: Text(day(isoDate(_date))),
            trailing: const Icon(Icons.edit_calendar),
            onTap: () async {
              final d = await pickDate(context, _date);
              if (d != null) setState(() => _date = d);
            },
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          onPressed: () async {
            final q = double.tryParse(_qty.text.trim());
            if (q == null || q < 0) return;
            final api = ref.read(apiProvider);
            final ok = await runAction(
              context,
              () async {
                await api.patch('/crop-cycles/${widget.cycleId}', {'status': 'harvested', 'actual_harvest_date': isoDate(_date)});
                await api.post(
                  '/crop-cycles/${widget.cycleId}/harvest-actual',
                  body: {'quantity_kg': q, 'harvest_start_date': isoDate(_date)},
                );
              },
              success: 'Harvest recorded',
            );
            if (ok && context.mounted) Navigator.pop(context, true);
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class _FeedbackCard extends StatelessWidget {
  const _FeedbackCard({required this.report});

  final Map<String, dynamic> report;

  @override
  Widget build(BuildContext context) {
    final actual = report.obj('actual');
    return SectionCard(
      title: 'How accurate were the predictions?',
      icon: Icons.fact_check_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          KeyValue('Measured harvest', kg(actual.numOrNull('quantity_kg')), kind: 'measured'),
          for (final f in report.objs('feedback'))
            KeyValue(
              'v${f.intVal('prediction_version')} predicted ${kg(f.obj('predicted').numVal('p50'))}',
              f.numOrNull('abs_pct_error') == null
                  ? '—'
                  : 'off by ${number(f.numVal('abs_pct_error'))}%${f.boolVal('within_interval') ? ' (inside range)' : ''}',
            ),
          Text(report.str('note'), style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
