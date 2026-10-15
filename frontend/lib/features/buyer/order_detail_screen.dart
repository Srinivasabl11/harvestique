import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/record_actions.dart';
import '../market/farmer_market_screen.dart' show orderRef;
import '../admin/collection_actions.dart';
import '../auth/auth_controller.dart';
import 'trace_screen.dart';

/// Order detail. Buyers can cancel (before produce is received) and trace; admins (hub operators) record
/// batches, quality checks and fulfilment for each accepted farm item.
class OrderDetailScreen extends ConsumerStatefulWidget {
  const OrderDetailScreen({super.key, required this.orderId});

  final String orderId;

  @override
  ConsumerState<OrderDetailScreen> createState() => _OrderDetailScreenState();
}

class _OrderDetailScreenState extends ConsumerState<OrderDetailScreen> {
  Key _key = UniqueKey();

  void _refresh() => setState(() => _key = UniqueKey());

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final r =
        await Future.wait([api.getObj('/orders/${widget.orderId}'), api.getList('/orders/${widget.orderId}/batches')]);
    return {'order': r[0], 'batches': r[1]};
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    final admin = ref.watch(authProvider).role == 'admin';
    return Scaffold(
      appBar: AppBar(
        title: Text('Order ${orderRef(widget.orderId)}'),
        actions: [
          IconButton(
            tooltip: 'Trace',
            icon: const Icon(Icons.timeline),
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(builder: (_) => TraceScreen(orderId: widget.orderId))),
          ),
        ],
      ),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () =>
            api.cached('order:${widget.orderId}', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
        builder: (context, d, reload) {
          final o = d.obj('order');
          final batches = d.objs('batches');
          final status = o.str('status');
          final cancellable = !admin && (status == 'placed' || status == 'confirmed') && batches.isEmpty;
          return ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              SectionCard(
                title: '${o.str('crop_name')} · ${label(status)}',
                icon: Icons.receipt_long_outlined,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    KeyValue('Ordered', kg(o.numVal('ordered_kg'))),
                    KeyValue('Confirmed by farmers', kg(o.numVal('confirmed_kg')), kind: 'estimate'),
                    if (o.numVal('awaiting_kg') > 0)
                      KeyValue('Waiting for farmers to accept', kg(o.numVal('awaiting_kg'))),
                    if (o.numVal('uncovered_kg') > 0)
                      KeyValue('Not yet covered (shortage)', kg(o.numVal('uncovered_kg'))),
                    KeyValue('Delivered (quality-accepted)', kg(o.numVal('fulfilled_kg')), kind: 'measured'),
                    if (status == 'placed' && o.numVal('awaiting_kg') <= 0 && o.numVal('uncovered_kg') > 0)
                      Text(
                        'Not fully confirmed: ${kg(o.numVal('uncovered_kg'))} has no supplier yet. '
                        'Open the harvest pool and tap "Check for new supply" after more farmers offer this crop.',
                        style: TextStyle(color: levelColor('high')),
                      ),
                    KeyValue('Delivery window', '${day(o.str('window_start'))} – ${day(o.str('window_end'))}'),
                    const SizedBox(height: 6),
                    Text(o.str('disclaimer'), style: Theme.of(context).textTheme.bodySmall),
                    if (cancellable)
                      Align(
                        alignment: Alignment.centerRight,
                        child: TextButton(
                          onPressed: () async {
                            // a real order: one stray tap must not cancel it
                            final sure = await confirmAction(
                              context,
                              title: 'Cancel this order?',
                              message:
                                  'The farms are told and their reserved quantity is released. This cannot be undone.',
                              confirm: 'Cancel order',
                              keep: 'Keep order',
                            );
                            if (!sure || !context.mounted) return;
                            final ok = await runAction(
                              context,
                              () => api.post('/orders/${widget.orderId}/cancel'),
                              success: 'Order cancelled',
                            );
                            if (ok) _refresh();
                          },
                          child: const Text('Cancel order'),
                        ),
                      ),
                  ],
                ),
              ),
              for (final it in o.objs('items'))
                SectionCard(
                  title: 'Farm ${it.str('farm_ref')} · ${kg(it.numVal('quantity_kg'))}',
                  icon: Icons.agriculture_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      KeyValue('Farmer', label(it.str('participation_status'))),
                      if (it.strOrNull('farmer_progress') != null)
                        KeyValue('Farm progress', label(it.str('farmer_progress'))),
                      KeyValue('Item', label(it.str('status'))),
                      if (it.numVal('fulfilled_kg') > 0)
                        KeyValue('Delivered', kg(it.numVal('fulfilled_kg')), kind: 'measured'),
                      for (final b in batches.where((b) => b.str('order_item_id') == it.str('id')))
                        Row(
                          children: [
                            Expanded(
                              child: KeyValue(
                                'Batch ${b.str('code')} (${b.str('hub_name')})',
                                '${kg(b.numVal('received_kg'))}${b.objOrNull('quality') == null ? ' · awaiting quality' : ' · ${label(b.obj('quality').str('result'))}'}',
                                kind: 'measured',
                              ),
                            ),
                            if (admin && b.objOrNull('quality') == null)
                              IconButton(
                                tooltip: 'Remove batch (entered by mistake)',
                                icon: const Icon(Icons.delete_outline),
                                onPressed: () async {
                                  if (!await confirmAction(
                                    context,
                                    title: 'Remove batch ${b.str('code')}?',
                                    message: 'Only for a batch entered by mistake. Checked batches cannot be removed.',
                                    confirm: 'Remove',
                                  )) {
                                    return;
                                  }
                                  if (!context.mounted) return;
                                  final ok = await runAction(
                                    context,
                                    () => api.delete('/admin/batches/${b.str('id')}'),
                                    success: 'Batch removed',
                                  );
                                  if (ok) _refresh();
                                },
                              ),
                          ],
                        ),
                      if (admin && it.str('status') == 'accepted')
                        CollectionActions(item: it, batches: batches, onChanged: _refresh),
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
