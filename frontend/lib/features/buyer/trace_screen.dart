import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';

/// Full traceability: Order -> Pool -> Farm Allocation -> Harvest -> Collection Batch -> Quality -> Fulfilment.
class TraceScreen extends ConsumerWidget {
  const TraceScreen({super.key, required this.orderId});

  final String orderId;

  static IconData _icon(String step) => switch (step) {
        'allocation' => Icons.hub_outlined,
        'farmer_participation' => Icons.handshake_outlined,
        'predictions' => Icons.insights,
        'harvest' => Icons.grass,
        'collection_batch' => Icons.local_shipping_outlined,
        'quality' => Icons.fact_check_outlined,
        'fulfilment' => Icons.task_alt,
        'prediction_feedback' => Icons.analytics_outlined,
        _ => Icons.circle_outlined,
      };

  static String _summary(Map<String, dynamic> s) {
    final d = s.obj('detail');
    return switch (s.str('step')) {
      'allocation' => '${kg(d.numVal('quantity_kg'))} · ${d.objs('ledger').length} ledger entries',
      'farmer_participation' => label(d.str('status')),
      'predictions' => d
          .objs('versions')
          .map((v) => 'v${v.intVal('version')}: ${kg(v.numOrNull('p10_kg'))}–${kg(v.numOrNull('p90_kg'))}')
          .join('\n'),
      'harvest' => kg(d.numOrNull('quantity_kg')),
      'collection_batch' => '${d.str('code')} · ${kg(d.numVal('received_kg'))} at ${d.str('hub')}',
      'quality' => d.strOrNull('result') == null
          ? 'pending'
          : '${label(d.str('result'))} · grade ${d.str('grade', '-')} · accepted ${kg(d.numOrNull('accepted_kg'))}',
      'fulfilment' => '${kg(d.numVal('fulfilled_kg'))} · ${label(d.str('item_status'))}',
      'prediction_feedback' => d
          .objs('versions')
          .map((v) => 'v${v.intVal('version')}: off by ${number(v.numOrNull('abs_pct_error'))}%')
          .join('\n'),
      _ => '',
    };
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Traceability')),
      body: Reloadable<Map<String, dynamic>>(
        load: () => api.cached(
          'trace:$orderId',
          () => api.getObj('/orders/$orderId/trace'),
          (j) => j is Map<String, dynamic> ? j : <String, dynamic>{},
        ),
        builder: (context, t, reload) => ListView(
          padding: const EdgeInsets.only(bottom: 32),
          children: [
            ListTile(
              title: Text('${t.str('crop_name')} · ${kg(t.numVal('fulfilled_kg'))} of ${kg(t.numVal('ordered_kg'))} delivered'),
              subtitle: Text(t.str('chain')),
            ),
            SectionCard(
              title: 'Pool reallocations (${t.objs('reallocations').length})',
              icon: Icons.sync_alt,
              child: Column(
                children: [
                  for (final r in t.objs('reallocations'))
                    KeyValue(
                      '${label(r.str('trigger'))} · ${day(r.str('at'))}',
                      '${label(r.str('outcome'))}: −${kg(r.numVal('shortage_kg'))} / +${kg(r.numVal('replaced_kg'))}',
                    ),
                ],
              ),
            ),
            for (final item in t.objs('items'))
              SectionCard(
                title: 'Farm ${item.str('farm_ref')} · ${label(item.str('status'))}',
                icon: Icons.agriculture_outlined,
                child: Column(
                  children: [
                    for (final s in item.objs('steps'))
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(_icon(s.str('step'))),
                        title: Text(label(s.str('step'))),
                        subtitle: Text(_summary(s)),
                        trailing: DataKindChip(s.str('data_kind')),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
