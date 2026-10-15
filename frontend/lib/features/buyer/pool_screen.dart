import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'order_detail_screen.dart';

/// A harvest pool: allocations per farm, shortage, reallocation events (why and before/after) and the ledger.
class PoolScreen extends ConsumerStatefulWidget {
  const PoolScreen({super.key, required this.poolId});

  final String poolId;

  @override
  ConsumerState<PoolScreen> createState() => _PoolScreenState();
}

class _PoolScreenState extends ConsumerState<PoolScreen> {
  Key _key = UniqueKey();

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final id = widget.poolId;
    final r = await Future.wait([
      api.getObj('/pools/$id'),
      api.getList('/pools/$id/events'),
      api.getList('/pools/$id/ledger'),
      api.getPage('/orders'),
    ]);
    final orders = (r[3] as List<Map<String, dynamic>>).where((o) => o.str('pool_id') == id).toList();
    return {'pool': r[0], 'events': r[1], 'ledger': r[2], if (orders.isNotEmpty) 'order': orders.first};
  }

  Future<void> _placeOrder(ApiClient api) async {
    final hubs = await api.getList('/hubs');
    if (!mounted) return;
    final hub = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('Deliver to which collection hub?'),
        children: [
          for (final h in hubs)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, h.str('id')),
              child: Padding(padding: const EdgeInsets.all(8), child: Text(h.str('name'))),
            ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, ''),
            child: const Padding(padding: EdgeInsets.all(8), child: Text('Decide later')),
          ),
        ],
      ),
    );
    if (hub == null || !mounted) return;
    final ok = await runAction(
      context,
      () => api.post(
        '/orders',
        body: {'pool_id': widget.poolId, if (hub.isNotEmpty) 'delivery_hub_id': hub},
        idempotencyKey: 'order-${widget.poolId}',
      ),
      success: 'Order placed: the farms are asked to confirm',
    );
    if (ok) setState(() => _key = UniqueKey());
  }

  bool _checking = false; // one supply check at a time

  /// Runs the pool's reallocation now: picks up supply offered since the pool was created (or since the last check)
  /// for the part of the demand not yet covered. New farms are asked to accept through the order as usual.
  Future<void> _checkSupply(ApiClient api) async {
    if (_checking) return;
    setState(() => _checking = true);
    Map<String, dynamic>? event;
    await runAction(context, () async {
      event = await api.post(
        '/pools/${widget.poolId}/rebalance',
        idempotencyKey: 'check-${widget.poolId}-${DateTime.now().millisecondsSinceEpoch}',
      );
    });
    if (!mounted) return;
    setState(() => _checking = false);
    final e = event;
    if (e == null) return;
    final added = e.numVal('topped_up_kg') + e.numVal('replaced_kg');
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(
          added > 0
              ? 'Found ${kg(added)} more eligible supply. New farms must accept before it counts as confirmed.'
              : 'No new eligible supply yet.',
        ),
      ),);
    setState(() => _key = UniqueKey());
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Harvest pool')),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () =>
            api.cached('pool:${widget.poolId}', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
        builder: (context, d, reload) {
          final p = d.obj('pool');
          final order = d.objOrNull('order');
          final shortage = p.numVal('shortage_kg');
          final unfilled = p.numVal('unfilled_kg');
          final closed = p.boolVal('closed');
          return ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              SectionCard(
                title: 'Status: ${label(p.str('status'))}',
                icon: p.str('status') == 'at_risk' ? Icons.warning_amber_rounded : Icons.hub_outlined,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    KeyValue('Demand', kg(p.numVal('demand_kg'))),
                    KeyValue('Allocated (p10 predictions)', kg(p.numVal('allocated_kg')), kind: 'estimate'),
                    if (unfilled > 0) KeyValue('Not yet covered (shortage)', kg(unfilled)),
                    if (shortage > 0) KeyValue('… of which lost when predictions fell', kg(shortage)),
                    if (unfilled > 0)
                      Text(
                        'Only ${kg(p.numVal('allocated_kg'))} of ${kg(p.numVal('demand_kg'))} has supply. '
                        'Allocated supply is a reservation, not a confirmation: farmers accept after the order is placed.',
                        style: TextStyle(color: levelColor('high')),
                      ),
                    if (unfilled > 0 && !closed)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton.icon(
                          onPressed: _checking ? null : () => _checkSupply(api),
                          icon: const Icon(Icons.refresh),
                          label: Text(_checking ? 'Checking…' : 'Check for new supply'),
                        ),
                      ),
                    KeyValue(
                      'Allocation method',
                      p.str('algorithm') == 'greedy' ? 'Greedy + dynamic reallocation' : 'Risk-capped optimiser (research)',
                    ),
                    const SizedBox(height: 8),
                    if (order == null)
                      FilledButton.icon(
                        onPressed: () => _placeOrder(api),
                        icon: const Icon(Icons.shopping_cart_checkout),
                        label: const Text('Place order'),
                      )
                    else
                      OutlinedButton.icon(
                        onPressed: () => Navigator.of(context)
                            .push(MaterialPageRoute<void>(builder: (_) => OrderDetailScreen(orderId: order.str('id')))),
                        icon: const Icon(Icons.receipt_long_outlined),
                        label: Text('Order: ${label(order.str('status'))}'),
                      ),
                  ],
                ),
              ),
              SectionCard(
                title: 'Farms in this pool',
                icon: Icons.agriculture_outlined,
                child: Column(
                  children: [
                    for (final a in p.objs('allocations'))
                      KeyValue(
                        'Farm lot ${a.str('lot_id').substring(0, 8)} · risk ${a.str('risk_level')}',
                        '${kg(a.numVal('quantity_kg'))} · ${label(a.str('status'))}',
                      ),
                  ],
                ),
              ),
              SectionCard(
                title: 'Changes (dynamic reallocation)',
                icon: Icons.sync_alt,
                child: d.objs('events').isEmpty
                    ? const Text('No changes since the pool was created.')
                    : Column(
                        children: [
                          for (final e in d.objs('events').reversed)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(
                                '${label(e.str('outcome'))} · shortage ${kg(e.numVal('shortage_kg'))}, replaced ${kg(e.numVal('replaced_kg'))}',
                              ),
                              subtitle: Text('${e.str('reason')}\n${dateTime(e.str('created_at'))} · ${label(e.str('trigger'))}'),
                              isThreeLine: true,
                            ),
                        ],
                      ),
              ),
              ExpansionTile(
                title: const Text('Audit ledger'),
                children: [
                  for (final l in d.objs('ledger'))
                    ListTile(
                      dense: true,
                      title: Text(
                        '${label(l.str('action'))}: ${kg(l.numVal('quantity_before'))} → ${kg(l.numVal('quantity_after'))}',
                      ),
                      subtitle: Text('${l.str('reason')} · ${dateTime(l.str('created_at'))}'),
                    ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}
