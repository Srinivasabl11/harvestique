import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';

/// Farmer marketplace: buyer demand for crops you grow, and supply requests to accept or decline.
/// Quantities only: Harvestique shows no prices.
class FarmerMarketScreen extends ConsumerStatefulWidget {
  const FarmerMarketScreen({super.key});

  @override
  ConsumerState<FarmerMarketScreen> createState() => _FarmerMarketScreenState();
}

/// "#1A2B3C4D": the order ID as shown in notifications.
String orderRef(String id) => '#${id.length >= 8 ? id.substring(0, 8).toUpperCase() : id.toUpperCase()}';

class _FarmerMarketScreenState extends ConsumerState<FarmerMarketScreen> {
  Key _key = UniqueKey();
  final _busy = <String>{}; // participations with a request in flight (no double submissions)

  Future<void> _act(String id, Future<void> Function() action, String success) async {
    if (_busy.contains(id)) return;
    setState(() => _busy.add(id));
    final ok = await runAction(context, action, success: success);
    if (!mounted) return;
    setState(() {
      _busy.remove(id);
      if (ok) _key = UniqueKey();
    });
  }

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final r = await Future.wait([api.getList('/market/opportunities'), api.getPage('/participations')]);
    return {'opportunities': r[0], 'participations': r[1]};
  }

  Future<void> _decline(Map<String, dynamic> p) async {
    final reason = TextEditingController();
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Decline this request?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Your reserved quantity is released and Harvestique tries to find it from other farms.'),
            TextField(
              controller: reason,
              maxLength: 255, // the server's limit
              decoration: const InputDecoration(labelText: 'Reason (shown to the buyer as a short note)'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Decline')),
        ],
      ),
    );
    final text = reason.text.trim().isEmpty ? 'Not available' : reason.text.trim();
    if (go != true || !mounted) return;
    await _act(
      p.str('id'),
      () => ref.read(apiProvider).post('/participations/${p.str('id')}/decline', body: {'reason': text}),
      'Declined. The buyer has been told.',
    );
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Reloadable<Map<String, dynamic>>(
      key: _key,
      load: () => api.cached('farmer_market', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
      builder: (context, d, reload) {
        final parts = d.objs('participations');
        final pending = parts.where((p) => p.str('status') == 'pending').toList();
        final active = parts.where((p) => p.str('status') == 'accepted' && p.str('item_status') == 'accepted').toList();
        final others = parts.where((p) => p.str('status') != 'pending' && !active.contains(p)).toList();
        final ops = d.objs('opportunities');
        return ListView(
          padding: const EdgeInsets.only(bottom: 96),
          children: [
            SectionCard(
              title: 'Requests for your harvest (${pending.length})',
              icon: Icons.handshake_outlined,
              child: pending.isEmpty
                  ? const Text('No requests waiting for you.')
                  : Column(
                      children: [
                        for (final p in pending)
                          Card(
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Order ${orderRef(p.str('order_id'))} · ${p.str('crop_name')} · ${kg(p.numVal('quantity_kg'))}',
                                    style: Theme.of(context).textTheme.titleMedium,
                                  ),
                                  Text('${p.str('buyer_business')} (${label(p.str('buyer_type'))})'),
                                  Text(
                                    'Deliver between ${day(p.str('window_start'))} and ${day(p.str('window_end'))}, grade ${p.str('min_grade')} or better',
                                  ),
                                  const Text(
                                    'This is your pessimistic (p10) predicted quantity: what you can safely promise.',
                                    style: TextStyle(fontSize: 12),
                                  ),
                                  const SizedBox(height: 8),
                                  Row(
                                    children: [
                                      Expanded(
                                        child: OutlinedButton(
                                          onPressed: _busy.contains(p.str('id')) ? null : () => _decline(p),
                                          child: const Text('Decline'),
                                        ),
                                      ),
                                      const SizedBox(width: 12),
                                      Expanded(
                                        child: FilledButton(
                                          onPressed: _busy.contains(p.str('id'))
                                              ? null
                                              : () => _act(
                                                    p.str('id'),
                                                    () => api.post('/participations/${p.str('id')}/accept'),
                                                    'Accepted. The buyer has been told.',
                                                  ),
                                          child: const Text('Accept'),
                                        ),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ),
                      ],
                    ),
            ),
            if (active.isNotEmpty)
              SectionCard(
                title: 'Your accepted orders (${active.length})',
                icon: Icons.inventory_2_outlined,
                child: Column(
                  children: [
                    for (final p in active)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title:
                            Text('Order ${orderRef(p.str('order_id'))} · ${p.str('crop_name')} · ${kg(p.numVal('quantity_kg'))}'),
                        subtitle: Text(
                          '${p.str('buyer_business')} · order ${label(p.str('order_status')).toLowerCase()}'
                          '\nYour progress: ${p.strOrNull('progress') == null ? 'not started' : label(p.str('progress'))}',
                        ),
                        isThreeLine: true,
                        trailing: p.str('progress') == 'ready'
                            ? const Chip(label: Text('Ready'), avatar: Icon(Icons.check_circle, size: 18))
                            : FilledButton.tonal(
                                onPressed: _busy.contains(p.str('id'))
                                    ? null
                                    : () {
                                        final next = p.strOrNull('progress') == null ? 'preparing' : 'ready';
                                        _act(
                                          p.str('id'),
                                          () => api.post('/participations/${p.str('id')}/progress', body: {'stage': next}),
                                          next == 'ready'
                                              ? 'Marked ready. The buyer has been told.'
                                              : 'Marked preparing. The buyer has been told.',
                                        );
                                      },
                                child: Text(p.strOrNull('progress') == null ? 'Mark preparing' : 'Mark ready'),
                              ),
                      ),
                  ],
                ),
              ),
            SectionCard(
              title: 'Buyers looking for your crops',
              icon: Icons.storefront_outlined,
              child: ops.isEmpty
                  ? const Text('No open buyer demand for the crops you grow right now.')
                  : Column(
                      children: [
                        for (final o in ops)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text('${o.str('crop_name')} · ${kg(o.numVal('quantity_kg'))}'),
                            subtitle: Text(
                                '${day(o.str('window_start'))} – ${day(o.str('window_end'))} · grade ${o.str('min_grade')}+ · ${label(o.str('buyer_type'))}'
                                '${o.boolVal('pooled') ? ' · already pooled' : ''}'),
                          ),
                        const Text(
                          'To be considered, open Harvest and switch "Offer to buyers" on for that crop.',
                          style: TextStyle(fontSize: 12),
                        ),
                      ],
                    ),
            ),
            if (others.isNotEmpty)
              SectionCard(
                title: 'Earlier requests',
                icon: Icons.history,
                child: Column(
                  children: [
                    for (final p in others)
                      KeyValue(
                        '${orderRef(p.str('order_id'))} · ${p.str('crop_name')} ${kg(p.numVal('quantity_kg'))}',
                        '${label(p.str('status'))} · ${label(p.str('item_status'))}',
                      ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }
}
