import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../farm/cycle_detail_screen.dart';
import '../market/farmer_market_screen.dart' show orderRef;

/// Harvest: the virtual inventory (what each crop can safely promise), offering it to buyers, and deliveries.
class HarvestScreen extends ConsumerStatefulWidget {
  const HarvestScreen({super.key});

  @override
  ConsumerState<HarvestScreen> createState() => _HarvestScreenState();
}

class _HarvestScreenState extends ConsumerState<HarvestScreen> {
  Key _key = UniqueKey();

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final r = await Future.wait([
      api.getPage('/inventory/lots'),
      api.getPage('/participations', query: {'status': 'accepted'}),
    ]);
    return {'lots': r[0], 'accepted': r[1]};
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Reloadable<Map<String, dynamic>>(
      key: _key,
      load: () => api.cached('harvest', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
      builder: (context, d, reload) {
        final lots = d.objs('lots');
        final accepted = d.objs('accepted');
        return ListView(
          padding: const EdgeInsets.only(bottom: 96),
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Text(
                'Before harvest, only the pessimistic (p10) prediction can be promised. After you record the harvest, the weighed quantity is used.',
              ),
            ),
            if (lots.isEmpty)
              const EmptyPanel(
                message: 'No inventory yet. Predict a harvest for a crop to create one.',
                icon: Icons.inventory_2_outlined,
              ),
            for (final l in lots) _LotCard(lot: l, onChanged: () => setState(() => _key = UniqueKey())),
            SectionCard(
              title: 'Deliveries you accepted',
              icon: Icons.local_shipping_outlined,
              child: accepted.isEmpty
                  ? const Text('None yet.')
                  : Column(
                      children: [
                        for (final p in accepted)
                          KeyValue(
                            '${orderRef(p.str('order_id'))} · ${p.str('crop_name')} · ${kg(p.numVal('quantity_kg'))}',
                            p.numVal('fulfilled_kg') > 0
                                ? 'Delivered ${kg(p.numVal('fulfilled_kg'))}'
                                : 'Deliver by ${day(p.str('window_end'))}'
                                    '${p.strOrNull('progress') == null ? '' : ' · ${label(p.str('progress'))}'}',
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

/// "Tomato · Plot 1, Green Acres": which crop a lot is.
String lotTitle(Map<String, dynamic> lot) {
  final crop = lot.str('crop_name', 'Crop');
  final where = [lot.str('plot_name'), lot.str('farm_name')].where((s) => s.isNotEmpty).join(', ');
  return where.isEmpty ? crop : '$crop · $where';
}

class _LotCard extends ConsumerStatefulWidget {
  const _LotCard({required this.lot, required this.onChanged});

  final Map<String, dynamic> lot;
  final VoidCallback onChanged;

  @override
  ConsumerState<_LotCard> createState() => _LotCardState();
}

class _LotCardState extends ConsumerState<_LotCard> {
  bool _busy = false; // one change at a time: no double submissions

  Future<void> _update(Map<String, dynamic> change, String success) async {
    if (_busy) return;
    setState(() => _busy = true);
    final ok = await runAction(
      context,
      () => ref.read(apiProvider).patch('/inventory/lots/${widget.lot.str('id')}', change),
      success: success,
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) widget.onChanged();
  }

  @override
  Widget build(BuildContext context) {
    final lot = widget.lot;
    final status = lot.str('status');
    final measured = lot.numOrNull('actual_kg') != null;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text(lotTitle(lot), style: Theme.of(context).textTheme.titleMedium)),
                DataKindChip(measured ? 'measured' : 'estimate'),
              ],
            ),
            Text(
              [
                label(status),
                if (lot.str('sowing_date').isNotEmpty) 'sown ${day(lot.str('sowing_date'))}',
              ].join(' · '),
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (!measured && lot.numOrNull('p50_kg') != null)
              KeyValue('Predicted harvest (most likely)', kg(lot.numVal('p50_kg')), kind: 'estimate'),
            if (measured) KeyValue('Harvested (weighed)', kg(lot.numVal('actual_kg')), kind: 'measured'),
            KeyValue('Can promise', kg(lot.numVal('committable_kg'))),
            KeyValue('Already committed', kg(lot.numVal('committed_kg'))),
            // the split of buyer orders on this lot (sent by newer servers only)
            if (lot.numOrNull('awaiting_confirmation_kg') != null)
              KeyValue('… requested, awaiting your answer', kg(lot.numVal('awaiting_confirmation_kg'))),
            if (lot.numOrNull('confirmed_kg') != null) KeyValue('… confirmed by you', kg(lot.numVal('confirmed_kg'))),
            if (lot.numOrNull('fulfilled_kg') != null) KeyValue('… delivered', kg(lot.numVal('fulfilled_kg'))),
            KeyValue('Still available', kg(lot.numVal('available_kg'))),
            if (!measured && status != 'cancelled')
              Text(
                'Conditions changed? Open the crop and update the prediction. Buyer pools using this crop are '
                'rebalanced automatically, and you are told if a request changes.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            if (lot.numVal('shortfall_kg') > 0)
              Text(
                'Short by ${kg(lot.numVal('shortfall_kg'))}: commitments are above what can now be promised.',
                style: TextStyle(color: levelColor('high')),
              ),
            Text(lot.str('basis'), style: Theme.of(context).textTheme.bodySmall),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Offer to buyers (harvest pools)'),
              subtitle: _busy ? const Text('Saving…') : null,
              value: lot.boolVal('pool_eligible'),
              onChanged: _busy
                  ? null
                  : (v) => _update(
                        {'pool_eligible': v},
                        v ? 'Offered to buyers.' : 'No longer offered to buyers.',
                      ),
            ),
            Row(
              children: [
                const Text('Grade for buyers: '),
                DropdownButton<String>(
                  value: lot.str('expected_grade', 'B'),
                  items: const [
                    DropdownMenuItem(value: 'A', child: Text('A (best)')),
                    DropdownMenuItem(value: 'B', child: Text('B')),
                    DropdownMenuItem(value: 'C', child: Text('C')),
                  ],
                  onChanged: _busy
                      ? null
                      : (v) {
                          if (v == null || v == lot.str('expected_grade', 'B')) return;
                          _update({'expected_grade': v}, 'Grade for buyers set to $v.');
                        },
                ),
                const Spacer(),
                TextButton(
                  onPressed: () => Navigator.of(context)
                      .push(MaterialPageRoute<void>(builder: (_) => CycleDetailScreen(cycleId: lot.str('crop_cycle_id')))),
                  child: const Text('Open crop'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
