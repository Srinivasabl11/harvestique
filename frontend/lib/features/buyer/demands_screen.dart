import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/record_actions.dart';
import 'pool_screen.dart';
import 'search_screen.dart';
import 'supply_status.dart';

class DemandsScreen extends ConsumerStatefulWidget {
  const DemandsScreen({super.key});

  @override
  ConsumerState<DemandsScreen> createState() => _DemandsScreenState();
}

class _DemandsScreenState extends ConsumerState<DemandsScreen> {
  Key _key = UniqueKey();

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Reloadable<List<Map<String, dynamic>>>(
      key: _key,
      load: () => api.cached('demands', () => api.getPage('/buyer-demands'), asObjects),
      builder: (context, demands, reload) => ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: FilledButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('New demand'),
              onPressed: () async {
                final created =
                    await showDialog<Map<String, dynamic>>(context: context, builder: (_) => const _DemandDialog());
                if (created != null && context.mounted) {
                  await Navigator.of(context)
                      .push(MaterialPageRoute<void>(builder: (_) => DemandDetailScreen(demand: created)));
                  setState(() => _key = UniqueKey());
                }
              },
            ),
          ),
          if (demands.isEmpty)
            const EmptyPanel(message: 'No demands yet. Say what crop, how much, which grade and when.'),
          for (final d in demands)
            Card(
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: ListTile(
                title: Text('${d.str('crop_name', 'Crop')} · ${kg(d.numVal('quantity_kg'))}'),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${day(d.str('window_start'))} – ${day(d.str('window_end'))} · grade ${d.str('min_grade')}+'),
                    StageChip(demand: d),
                    if (demandShortage(d) > 0) Text('Short by ${kg(demandShortage(d))}'),
                  ],
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  await Navigator.of(context)
                      .push(MaterialPageRoute<void>(builder: (_) => DemandDetailScreen(demand: d)));
                  await reload();
                },
              ),
            ),
        ],
      ),
    );
  }
}

/// Why a maximum delivery distance is not acceptable, or null when it is.
String? validateMaxDistance(String text) {
  final v = double.tryParse(text.trim());
  if (v == null || v <= 0) return 'Enter the maximum distance in km (a number above 0).';
  if (v > 2000) return 'Enter a distance of at most 2,000 km.';
  return null;
}

class _DemandDialog extends ConsumerStatefulWidget {
  const _DemandDialog();

  @override
  ConsumerState<_DemandDialog> createState() => _DemandDialogState();
}

class _DemandDialogState extends ConsumerState<_DemandDialog> {
  final _qty = TextEditingController();
  String? _crop;
  String _grade = 'B';
  DateTime _from = DateTime.now().add(const Duration(days: 30));
  DateTime _to = DateTime.now().add(const Duration(days: 90));
  late final Future<List<Map<String, dynamic>>> _crops = ref.read(apiProvider).getAll('/crops');
  // optional delivery point: a collection hub with a known location, and how far farms may be from it
  late final Future<List<Map<String, dynamic>>> _hubs = ref
      .read(apiProvider)
      .getList('/hubs')
      .then((hubs) => hubs.where((h) => h.numOrNull('latitude') != null && h.numOrNull('longitude') != null).toList())
    ..ignore();
  Map<String, dynamic>? _hub;
  final _distance = TextEditingController(text: '100');
  String? _problem;
  bool _saving = false; // a second tap must not create a duplicate demand

  @override
  void dispose() {
    _qty.dispose();
    _distance.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    if (_saving) return;
    final problem = validateHarvestSearch(cropId: _crop, quantity: _qty.text) ??
        (_hub == null ? null : validateMaxDistance(_distance.text));
    setState(() => _problem = problem);
    if (problem != null) return;
    setState(() => _saving = true);
    Map<String, dynamic>? created;
    await runAction(context, () async {
      created = await ref.read(apiProvider).post(
        '/buyer-demands',
        body: {
          'crop_id': _crop,
          'quantity_kg': double.parse(_qty.text.trim()),
          'min_grade': _grade,
          'window_start': isoDate(_from),
          'window_end': isoDate(_to),
          if (_hub != null) ...{
            'latitude': _hub!.numVal('latitude'),
            'longitude': _hub!.numVal('longitude'),
            'max_distance_km': double.parse(_distance.text.trim()),
            'notes': 'Deliver near collection hub: ${_hub!.str('name')}',
          },
        },
      );
    });
    if (!mounted) return;
    if (created != null) {
      Navigator.pop(context, created);
    } else {
      setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('New demand'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            FutureBuilder<List<Map<String, dynamic>>>(
              future: _crops,
              builder: (context, snap) {
                if (snap.hasError) return const Text('Crops could not be loaded. Close this and try again.');
                final crops = [...snap.data ?? <Map<String, dynamic>>[]]
                  ..sort((a, b) => a.str('name').compareTo(b.str('name')));
                return DropdownButtonFormField<String>(
                  initialValue: _crop,
                  isExpanded: true,
                  decoration: InputDecoration(labelText: 'Crop', helperText: snap.hasData ? null : 'Loading crops…'),
                  items: [
                    for (final c in crops) DropdownMenuItem(value: c.str('id'), child: Text(c.str('name'))),
                  ],
                  onChanged: (v) => setState(() {
                    _crop = v;
                    _problem = null;
                  }),
                );
              },
            ),
            FormText(controller: _qty, label: 'Quantity (kg)', keyboard: TextInputType.number),
            DropdownButtonFormField<String>(
              initialValue: _grade,
              decoration: const InputDecoration(labelText: 'Minimum grade'),
              items: const [
                DropdownMenuItem(value: 'A', child: Text('A')),
                DropdownMenuItem(value: 'B', child: Text('B or better')),
                DropdownMenuItem(value: 'C', child: Text('C or better')),
              ],
              onChanged: (v) => setState(() => _grade = v ?? 'B'),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Delivery window'),
              subtitle: Text('${day(isoDate(_from))} – ${day(isoDate(_to))}'),
              onTap: () async {
                final r = await showDateRangePicker(
                  context: context,
                  firstDate: DateTime.now(),
                  lastDate: DateTime.now().add(const Duration(days: 730)),
                  initialDateRange: DateTimeRange(start: _from, end: _to),
                );
                if (r != null) {
                  setState(() {
                    _from = r.start;
                    _to = r.end;
                  });
                }
              },
            ),
            FutureBuilder<List<Map<String, dynamic>>>(
              future: _hubs,
              builder: (context, snap) {
                final hubs = snap.data ?? <Map<String, dynamic>>[];
                if (snap.hasError || (snap.hasData && hubs.isEmpty)) return const SizedBox.shrink();
                return DropdownButtonFormField<String>(
                  initialValue: _hub?.str('id') ?? '',
                  isExpanded: true,
                  decoration: InputDecoration(
                    labelText: 'Deliver near (optional)',
                    helperText: snap.hasData ? 'Only farms within the distance below are matched' : 'Loading hubs…',
                  ),
                  items: [
                    const DropdownMenuItem(value: '', child: Text('Anywhere')),
                    for (final h in hubs) DropdownMenuItem(value: h.str('id'), child: Text(h.str('name'))),
                  ],
                  onChanged: (v) => setState(() {
                    _hub = hubs.where((h) => h.str('id') == v).firstOrNull;
                    _problem = null;
                  }),
                );
              },
            ),
            if (_hub != null)
              FormText(controller: _distance, label: 'Maximum distance from the hub (km)', keyboard: TextInputType.number),
            if (_problem != null) Text(_problem!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: _saving ? null : _create,
          child: Text(_saving ? 'Creating…' : 'Create'),
        ),
      ],
    );
  }
}

/// A demand: ranked matching supply and its harvest pool.
class DemandDetailScreen extends ConsumerStatefulWidget {
  const DemandDetailScreen({super.key, required this.demand});

  final Map<String, dynamic> demand;

  @override
  ConsumerState<DemandDetailScreen> createState() => _DemandDetailScreenState();
}

class _DemandDetailScreenState extends ConsumerState<DemandDetailScreen> {
  Key _key = UniqueKey();
  bool _research = false;
  bool _withdrawing = false;
  bool _cancelled = false;

  Future<void> _withdraw(Map<String, dynamic> d) async {
    final ok = await confirmAction(
      context,
      title: 'Withdraw this demand?',
      message: 'Farmers will no longer see it. This cannot be undone, but you can create a new demand later.',
      confirm: 'Withdraw',
    );
    if (!ok || !mounted) return;
    setState(() => _withdrawing = true);
    final done = await runAction(
      context,
      () => ref.read(apiProvider).post('/buyer-demands/${d.str('id')}/cancel'),
      success: 'Demand withdrawn.',
    );
    if (!mounted) return;
    setState(() {
      _withdrawing = false;
      _cancelled = done;
    });
  }

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final id = widget.demand.str('id');
    final r = await Future.wait([
      api.getObj('/buyer-demands/$id/matches'),
      api.getPage('/pools'),
      api.getObj('/buyer-demands/$id'), // fresh stage: the demand passed in may be from before a pool or order
    ]);
    final pools = (r[1] as List<Map<String, dynamic>>).where((p) => p.str('demand_id') == id).toList();
    return {'matches': r[0], if (pools.isNotEmpty) 'pool': pools.first, 'demand': r[2]};
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    final d = widget.demand;
    return Scaffold(
      appBar: AppBar(title: Text('${d.str('crop_name', 'Demand')} · ${kg(d.numVal('quantity_kg'))}')),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () => live(_load(api)),
        builder: (context, data, reload) {
          final m = data.obj('matches');
          final pool = data.objOrNull('pool');
          final fresh = data.obj('demand');
          // the server's latest view of the demand; the list's copy if the reload did not return this demand
          final current = fresh.str('id') == d.str('id') ? fresh : d;
          final stage = demandStage(_cancelled ? const {'stage': 'cancelled'} : current);
          final nothingToReserve = fulfilmentOf(m) == 'none';
          return ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              Card(
                margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                child: ListTile(
                  leading: Icon(stage.icon, color: stage.level.isEmpty ? null : levelColor(stage.level)),
                  title: Text(stage.title),
                  subtitle: stage.detail.isEmpty ? null : Text(stage.detail),
                ),
              ),
              if (pool != null)
                Card(
                  margin: const EdgeInsets.all(12),
                  child: ListTile(
                    leading: const Icon(Icons.hub_outlined),
                    title: Text('Harvest pool · ${label(pool.str('status'))}'),
                    subtitle: Text(
                      '${kg(pool.numVal('allocated_kg'))} of ${kg(pool.numVal('demand_kg'))} allocated'
                      '${pool.numVal('unfilled_kg') > 0 ? ' · ${kg(pool.numVal('unfilled_kg'))} not yet covered' : ''}',
                    ),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.of(context)
                        .push(MaterialPageRoute<void>(builder: (_) => PoolScreen(poolId: pool.str('id')))),
                  ),
                )
              else if (_cancelled || current.str('status') == 'cancelled')
                const Card(
                  margin: EdgeInsets.all(12),
                  child: ListTile(
                    leading: Icon(Icons.block),
                    title: Text('This demand was withdrawn'),
                    subtitle: Text('Farmers no longer see it. Create a new demand if you need this crop again.'),
                  ),
                )
              else
                SectionCard(
                  title: 'Create a harvest pool',
                  icon: Icons.hub_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                          'Combines predicted supply from several farms. Only each farm\'s pessimistic (p10) quantity is used, '
                          'and supply is replaced automatically if a prediction falls.'),
                      if (nothingToReserve)
                        const Padding(
                          padding: EdgeInsets.only(top: 8),
                          child: Text(
                            'There is no eligible supply to reserve yet, so no pool can be created. Your demand stays '
                            'open: farmers growing this crop have been told, and you can check again later.',
                          ),
                        )
                      else ...[
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Research mode: risk-capped optimiser'),
                          subtitle:
                              const Text('Default is greedy allocation, which did better in our simulated evaluation.'),
                          value: _research,
                          onChanged: (v) => setState(() => _research = v),
                        ),
                        FilledButton(
                          onPressed: () async {
                            final ok = await runAction(
                              context,
                              () => api.post(
                                '/buyer-demands/${d.str('id')}/pool',
                                body: {'algorithm': _research ? 'lp' : 'greedy'},
                                idempotencyKey: 'pool-${d.str('id')}',
                              ),
                              success: 'Pool created',
                            );
                            if (ok) setState(() => _key = UniqueKey());
                          },
                          child: Text(
                            fulfilmentOf(m) == 'partial'
                                ? 'Create pool for the available ${kg(m.numVal('eligible_supply_kg'))}'
                                : 'Create pool',
                          ),
                        ),
                      ],
                      TextButton.icon(
                        icon: const Icon(Icons.block),
                        label: Text(_withdrawing ? 'Withdrawing…' : 'Withdraw this demand'),
                        onPressed: _withdrawing ? null : () => _withdraw(d),
                      ),
                    ],
                  ),
                ),
              if (pool == null || m.numVal('need_kg') > 0) SupplySummaryCard(matches: m, pooled: pool != null),
              if (pool == null && !nothingToReserve && shortageOf(m) > 0)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: Text(
                    'A pool can still be created for the eligible supply; the missing ${kg(shortageOf(m))} stays '
                    'visible as not covered and is added if more eligible supply appears.',
                    style: TextStyle(color: levelColor('medium')),
                  ),
                )
              else if (pool == null && !nothingToReserve)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: Text(
                    'Creating the pool reserves only the ${kg(m.numVal('need_kg'))} you need, '
                    'and each farmer must still accept after you place the order.',
                  ),
                ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Text(m.str('note'), style: Theme.of(context).textTheme.bodySmall),
              ),
              for (final x in m.objs('matches'))
                Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: MatchTile(match: x)),
            ],
          );
        },
      ),
    );
  }
}
