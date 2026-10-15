import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'plan_forms.dart';
import 'plan_item_screen.dart';

/// Income plans (Phase 3 planner): every figure is a low / expected / high range from the farmer's own inputs.
class PlansScreen extends ConsumerStatefulWidget {
  const PlansScreen({super.key});

  @override
  ConsumerState<PlansScreen> createState() => _PlansScreenState();
}

class _PlansScreenState extends ConsumerState<PlansScreen> {
  Key _key = UniqueKey();

  Future<void> _open(BuildContext context, String id, String name) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => PlanDetailScreen(planId: id, name: name)));
    if (mounted) setState(() => _key = UniqueKey());
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Income plans')),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('New plan'),
        onPressed: () async {
          final created = await Navigator.of(context).push<Map<String, dynamic>>(
            MaterialPageRoute<Map<String, dynamic>>(builder: (_) => const NewPlanScreen()),
          );
          if (created != null && context.mounted) await _open(context, created.str('id'), created.str('name'));
        },
      ),
      body: Reloadable<List<Map<String, dynamic>>>(
        key: _key,
        load: () => api.cached('plans', () => api.getPage('/crop-plans'), asObjects),
        isEmpty: (p) => p.isEmpty,
        emptyMessage: 'No income plans yet. Tap "New plan", then add the crops you want to grow.',
        builder: (context, plans, reload) => ListView(
          padding: const EdgeInsets.only(bottom: 96),
          children: [
            for (final p in plans)
              ListTile(
                leading: const Icon(Icons.calculate_outlined),
                title: Text(p.str('name')),
                subtitle: Text(
                  '${label(p.str('season'))} · ${number(p.numVal('available_land_acres'))} acres · '
                  '${p.intVal('item_count')} ${p.intVal('item_count') == 1 ? 'crop' : 'crops'}',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(context, p.str('id'), p.str('name')),
              ),
          ],
        ),
      ),
    );
  }
}

/// Create a plan: name, optional farm (its area becomes the default land), season, land and optional budget.
/// Returns the created plan.
class NewPlanScreen extends ConsumerStatefulWidget {
  const NewPlanScreen({super.key});

  @override
  ConsumerState<NewPlanScreen> createState() => _NewPlanScreenState();
}

class _NewPlanScreenState extends ConsumerState<NewPlanScreen> {
  late final Future<List<Map<String, dynamic>>> _farms = ref.read(apiProvider).getPage('/farms');
  final _name = TextEditingController();
  final _land = TextEditingController();
  final _budget = TextEditingController();
  Map<String, dynamic>? _farm;
  String _season = 'year_round';
  String? _error;
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    _land.dispose();
    _budget.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final farmArea = _farm?.numVal('total_area_acres');
    final problem = validateNewPlan(name: _name.text, landText: _land.text, farmArea: farmArea, budgetText: _budget.text);
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final budget = parseNumber(_budget.text);
      final created = await ref.read(apiProvider).post(
        '/crop-plans',
        body: {
          'name': _name.text.trim(),
          if (_farm != null) 'farm_id': _farm!.str('id'),
          'available_land_acres': parseNumber(_land.text),
          'season': _season,
          if (budget != null) 'budget_inr': budget,
        },
      );
      if (mounted) Navigator.of(context).pop(created);
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
      appBar: AppBar(title: const Text('New income plan')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _farms,
        builder: (context, snap) {
          final farms = snap.data ?? const <Map<String, dynamic>>[];
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
              TextField(
                controller: _name,
                maxLength: 120,
                decoration: const InputDecoration(labelText: 'Plan name', hintText: 'e.g. Kharif 2026'),
              ),
              if (snap.connectionState != ConnectionState.done) const LinearProgressIndicator(),
              if (farms.isNotEmpty)
                DropdownButtonFormField<String?>(
                  initialValue: _farm?.str('id'),
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Farm (optional)'),
                  items: [
                    const DropdownMenuItem<String?>(child: Text('Not linked to a farm')),
                    for (final f in farms)
                      DropdownMenuItem<String?>(
                        value: f.str('id'),
                        child: Text('${f.str('name')} · ${number(f.numVal('total_area_acres'))} acres'),
                      ),
                  ],
                  onChanged: (id) => setState(() {
                    _farm = id == null ? null : farms.firstWhere((f) => f.str('id') == id);
                    if (_farm != null) _land.text = number(_farm!.numVal('total_area_acres'), decimals: 3);
                    _error = null;
                  }),
                ),
              DropdownButtonFormField<String>(
                initialValue: _season,
                decoration: const InputDecoration(labelText: 'Season'),
                items: [for (final s in planSeasons) DropdownMenuItem(value: s, child: Text(label(s)))],
                onChanged: (v) => setState(() => _season = v ?? 'year_round'),
              ),
              TextField(
                controller: _land,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: 'Land available (acres)',
                  helperText: _farm == null ? null : 'At most the farm\'s ${number(_farm!.numVal('total_area_acres'))} acres',
                ),
              ),
              TextField(
                controller: _budget,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Budget (₹, optional)', prefixText: '₹ '),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: const Icon(Icons.arrow_forward),
                label: Text(_saving ? 'Creating…' : 'Create plan, then add crops'),
              ),
            ],
          );
        },
      ),
    );
  }
}

/// One plan: its crops (add, edit, delete), the estimated totals from the planning engine and, for a plan linked to
/// a farm, the expenses actually recorded, labelled separately from the estimates.
class PlanDetailScreen extends ConsumerStatefulWidget {
  const PlanDetailScreen({super.key, required this.planId, required this.name});

  final String planId;
  final String name;

  @override
  ConsumerState<PlanDetailScreen> createState() => _PlanDetailScreenState();
}

class _PlanDetailScreenState extends ConsumerState<PlanDetailScreen> {
  Key _key = UniqueKey();

  void _refresh() => setState(() => _key = UniqueKey());

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final plan = await api.getObj('/crop-plans/${widget.planId}');
    final items = plan.objs('items');
    // an empty plan has nothing to evaluate (the server answers 409): show the plan and ask for crops instead
    final evaluation = items.isEmpty ? null : await api.getObj('/crop-plans/${widget.planId}/evaluation');
    Map<String, dynamic>? actual;
    final farmId = plan.strOrNull('farm_id');
    if (farmId != null) {
      final since = items.map((i) => i.str('sowing_date')).where((s) => s.isNotEmpty).fold<String?>(
            null,
            (min, s) => min == null || s.compareTo(min) < 0 ? s : min,
          );
      final r = await Future.wait([
        api.getObj('/farms/$farmId'),
        api.getObj('/farms/$farmId/expenses', query: {'limit': 100, if (since != null) 'date_from': since}),
      ]);
      actual = {'farm': r[0], 'expenses': r[1], if (since != null) 'since': since};
    }
    return {'plan': plan, if (evaluation != null) 'evaluation': evaluation, if (actual != null) 'actual': actual};
  }

  Future<void> _editItem(Map<String, dynamic> plan, [Map<String, dynamic>? item]) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(builder: (_) => PlanItemScreen(plan: plan, item: item)),
    );
    if (saved == true && mounted) _refresh();
  }

  Future<bool> _sure(String title, String body) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
          ],
        ),
      ) ==
      true;

  Future<void> _deleteItem(Map<String, dynamic> item) async {
    if (!await _sure('Remove ${item.str('crop_name')} from the plan?', 'The plan totals will be recalculated.') || !mounted) {
      return;
    }
    final ok = await runAction(
      context,
      () => ref.read(apiProvider).delete('/crop-plan-items/${item.str('id')}'),
      success: 'Crop removed',
    );
    if (ok && mounted) _refresh();
  }

  Future<void> _deletePlan() async {
    if (!await _sure('Delete this plan?', 'The plan and its crops are deleted. Your farm records are not affected.') ||
        !mounted) {
      return;
    }
    final ok =
        await runAction(context, () => ref.read(apiProvider).delete('/crop-plans/${widget.planId}'), success: 'Plan deleted');
    if (ok && mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.name),
        actions: [IconButton(tooltip: 'Delete plan', icon: const Icon(Icons.delete_outline), onPressed: _deletePlan)],
      ),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () =>
            api.cached('plan:${widget.planId}', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
        builder: (context, d, reload) {
          final plan = d.obj('plan');
          final items = plan.objs('items');
          final ev = d.objOrNull('evaluation');
          final results = ev?.objs('items') ?? const <Map<String, dynamic>>[];
          return ListView(
            padding: const EdgeInsets.only(bottom: 96),
            children: [
              ListTile(
                title: Text(
                  '${label(plan.str('season'))} · ${number(plan.numVal('available_land_acres'))} acres'
                  '${plan.numOrNull('budget_inr') == null ? '' : ' · budget ${rupees(plan.numVal('budget_inr'))}'}',
                ),
                subtitle: d.objOrNull('actual') == null ? null : Text('Farm: ${d.obj('actual').obj('farm').str('name')}'),
              ),
              if (ev != null)
                _EstimateCard(ev: ev)
              else
                const EmptyPanel(
                  icon: Icons.spa_outlined,
                  message:
                      'No crops in this plan yet. Add the crops you want to grow, with your expected yield, price and costs.',
                ),
              _ActualCard(actual: d.objOrNull('actual'), estimatedCost: ev?.obj('totals').obj('cost').numOrNull('expected')),
              for (final f in ev?.objs('findings') ?? const <Map<String, dynamic>>[])
                ListTile(
                  dense: true,
                  leading: Icon(f.str('severity') == 'hard' ? Icons.error_outline : Icons.info_outline),
                  title: Text(f.str('message')),
                ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                child: Row(
                  children: [
                    Expanded(child: Text('Crops (${items.length})', style: Theme.of(context).textTheme.titleMedium)),
                    FilledButton.icon(
                      onPressed: () => _editItem(plan),
                      icon: const Icon(Icons.add),
                      label: const Text('Add crop'),
                    ),
                  ],
                ),
              ),
              for (final (i, it) in items.indexed)
                _ItemCard(
                  item: it,
                  result: i < results.length ? results[i] : null,
                  onEdit: () => _editItem(plan, it),
                  onDelete: () => _deleteItem(it),
                ),
              if (ev != null)
                SectionCard(
                  title: 'Plan quality',
                  icon: Icons.verified_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ConfidenceBadge(score: ev.obj('confidence').numVal('score'), level: ev.obj('confidence').str('level')),
                      const SizedBox(height: 8),
                      RiskChip(level: ev.obj('risk').str('level'), score: ev.obj('risk').numOrNull('score')),
                      if (!ev.boolVal('feasible', true))
                        const Text(
                          'Not feasible as entered (land or budget exceeded).',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                    ],
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

String _triple(Map<String, dynamic> t) =>
    '${rupees(t.numVal('low'))} / ${rupees(t.numVal('expected'))} / ${rupees(t.numVal('high'))}';

class _EstimateCard extends StatelessWidget {
  const _EstimateCard({required this.ev});

  final Map<String, dynamic> ev;

  @override
  Widget build(BuildContext context) {
    final t = ev.obj('totals');
    return SectionCard(
      title: 'Estimated net income',
      icon: Icons.currency_rupee,
      action: const DataKindChip('estimate'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(rupees(t.obj('margin').numVal('expected')), style: Theme.of(context).textTheme.headlineSmall),
          Text('Range: ${rupees(t.obj('margin').numVal('low'))} to ${rupees(t.obj('margin').numVal('high'))}'),
          const SizedBox(height: 8),
          KeyValue('Revenue (low / expected / high)', _triple(t.obj('revenue'))),
          KeyValue(
            'Costs (expected / with overrun)',
            '${rupees(t.obj('cost').numVal('expected'))} / ${rupees(t.obj('cost').numVal('high'))}',
          ),
          KeyValue('Area sown', '${number(t.numVal('area_sown_acres'))} acres'),
          Text(
            'Net income = revenue − costs, calculated from the yields, prices and costs you entered. '
            'An estimate, not a forecast or a guarantee.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _ActualCard extends StatelessWidget {
  const _ActualCard({required this.actual, required this.estimatedCost});

  final Map<String, dynamic>? actual;
  final double? estimatedCost;

  @override
  Widget build(BuildContext context) {
    final a = actual;
    if (a == null) {
      return const SectionCard(
        title: 'Actual so far',
        icon: Icons.receipt_long_outlined,
        child: Text('Link the plan to a farm to compare it with the expenses you record there.'),
      );
    }
    final page = a.obj('expenses');
    final items = page.objs('items');
    final spent = items.fold<double>(0, (s, e) => s + e.numVal('amount'));
    final more = page.intVal('total') > items.length;
    return SectionCard(
      title: 'Actual so far',
      icon: Icons.receipt_long_outlined,
      action: const DataKindChip('actual'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          KeyValue(
            a.strOrNull('since') == null ? 'Expenses recorded on this farm' : 'Expenses recorded since ${day(a.str('since'))}',
            rupees(spent),
          ),
          if (estimatedCost != null && estimatedCost! > 0)
            KeyValue('Share of the estimated costs', '${number(spent / estimatedCost! * 100, decimals: 0)} %'),
          if (more)
            Text(
              'Total of the latest ${items.length} of ${page.intVal('total')} expenses.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          Text(
            'Actual sale income is not recorded in Harvestique yet, so only costs can be compared.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _ItemCard extends StatelessWidget {
  const _ItemCard({required this.item, required this.result, required this.onEdit, required this.onDelete});

  final Map<String, dynamic> item;
  final Map<String, dynamic>? result;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final r = result;
    final y = item.obj('yield_per_acre_kg');
    final p = item.obj('price_per_kg');
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 4, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${item.str('crop_name')} · ${number(item.numVal('area_acres'))} acres',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(tooltip: 'Edit', icon: const Icon(Icons.edit_outlined), onPressed: onEdit),
                IconButton(tooltip: 'Remove', icon: const Icon(Icons.delete_outline), onPressed: onDelete),
              ],
            ),
            Text(
              'Sown ${day(item.str('sowing_date'))} · ${item.intVal('duration_days')} days\n'
              'Yield ${number(y.numVal('expected'))} kg/acre (${number(y.numVal('low'))}–${number(y.numVal('high'))}) · '
              'price ₹${number(p.numVal('expected'), decimals: 2)}/kg (₹${number(p.numVal('low'), decimals: 2)}–₹${number(p.numVal('high'), decimals: 2)})',
            ),
            if (r != null) ...[
              const SizedBox(height: 6),
              KeyValue('Expected revenue', rupees(r.obj('revenue').numVal('expected'))),
              KeyValue('Expected costs', rupees(r.obj('cost').numVal('expected'))),
              KeyValue('Expected net income', rupees(r.obj('margin').numVal('expected')), kind: 'estimate'),
            ],
            if (item.str('notes').isNotEmpty) Text(item.str('notes'), style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
