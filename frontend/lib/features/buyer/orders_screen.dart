import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../market/farmer_market_screen.dart' show orderRef;
import 'order_detail_screen.dart';

/// Orders (buyers: their own; admins: all).
class OrdersScreen extends ConsumerWidget {
  const OrdersScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    return Reloadable<List<Map<String, dynamic>>>(
      load: () => api.cached('orders', () => api.getPage('/orders'), asObjects),
      isEmpty: (o) => o.isEmpty,
      emptyMessage: 'No orders yet. Create a demand, pool it and place an order.',
      builder: (context, orders, reload) => ListView(
        children: [
          for (final o in orders)
            Card(
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: ListTile(
                leading: const Icon(Icons.receipt_long_outlined),
                title: Text('${orderRef(o.str('id'))} · ${o.str('crop_name')} · ${kg(o.numVal('ordered_kg'))}'),
                subtitle: Text(
                  '${label(o.str('status'))} · confirmed ${kg(o.numVal('confirmed_kg'))} of ${kg(o.numVal('ordered_kg'))}'
                  '${o.numVal('awaiting_kg') > 0 ? ' · waiting ${kg(o.numVal('awaiting_kg'))}' : ''}'
                  '${o.numVal('uncovered_kg') > 0 ? ' · short ${kg(o.numVal('uncovered_kg'))}' : ''}'
                  ' · delivered ${kg(o.numVal('fulfilled_kg'))}',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  await Navigator.of(context)
                      .push(MaterialPageRoute<void>(builder: (_) => OrderDetailScreen(orderId: o.str('id'))));
                  await reload();
                },
              ),
            ),
        ],
      ),
    );
  }
}
