import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'collection_actions.dart';

/// Platform counts from the database (real data only; nothing estimated here).
class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    return Reloadable<Map<String, dynamic>>(
      load: () => api.cached(
        'dashboard',
        () => api.getObj('/admin/dashboard'),
        (j) => j is Map<String, dynamic> ? j : <String, dynamic>{},
      ),
      builder: (context, d, reload) {
        Widget counts(String title, IconData icon, Map<String, dynamic> m) => SectionCard(
              title: title,
              icon: icon,
              child: m.isEmpty
                  ? const Text('None yet.')
                  : Column(children: [for (final e in m.entries) KeyValue(label(e.key), '${e.value}')]),
            );
        final q = d.obj('quality');
        return ListView(
          padding: const EdgeInsets.only(bottom: 32),
          children: [
            ListTile(title: const Text('Generated'), subtitle: Text(dateTime(d.str('generated_at')))),
            counts('Users', Icons.people_outline, d.obj('users')),
            SectionCard(
              title: 'Farms and supply',
              icon: Icons.agriculture_outlined,
              child: Column(
                children: [
                  KeyValue('Farms', '${d.intVal('farms')}'),
                  KeyValue('Active crop cycles', '${d.intVal('active_cycles')}'),
                  KeyValue('Supply on offer', kg(d.numVal('available_kg')), kind: 'estimate'),
                ],
              ),
            ),
            counts('Lots', Icons.inventory_2_outlined, d.obj('lots')),
            counts('Demands', Icons.request_quote_outlined, d.obj('demands')),
            counts('Pools', Icons.hub_outlined, d.obj('pools')),
            counts('Orders', Icons.receipt_long_outlined, d.obj('orders')),
            counts('Reallocations (30 days)', Icons.sync_alt, d.obj('reallocation_events_30d')),
            SectionCard(
              title: 'Collection and quality',
              icon: Icons.fact_check_outlined,
              child: Column(
                children: [
                  KeyValue('Batches awaiting quality', '${d.intVal('batches_awaiting_quality')}'),
                  KeyValue('Received', kg(q.numVal('received_kg')), kind: 'measured'),
                  KeyValue('Accepted', kg(q.numVal('accepted_kg')), kind: 'measured'),
                  KeyValue('Rejected', kg(q.numVal('rejected_kg')), kind: 'measured'),
                ],
              ),
            ),
            SectionCard(
              title: 'Prediction accuracy',
              icon: Icons.analytics_outlined,
              child: Text(d.str('calibration_note')),
            ),
          ],
        );
      },
    );
  }
}

class QualityQueueScreen extends ConsumerStatefulWidget {
  const QualityQueueScreen({super.key});

  @override
  ConsumerState<QualityQueueScreen> createState() => _QualityQueueScreenState();
}

class _QualityQueueScreenState extends ConsumerState<QualityQueueScreen> {
  Key _key = UniqueKey();

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Reloadable<List<Map<String, dynamic>>>(
      key: _key,
      load: () => live(api.getPage('/admin/batches', query: {'awaiting_quality': true})),
      isEmpty: (b) => b.isEmpty,
      emptyMessage: 'No batches are waiting for a quality check.',
      builder: (context, batches, reload) => ListView(
        children: [
          for (final b in batches)
            Card(
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: ListTile(
                leading: const Icon(Icons.local_shipping_outlined),
                title: Text('${b.str('code')} · ${kg(b.numVal('received_kg'))}'),
                subtitle: Text('${b.str('hub_name')} · ${dateTime(b.str('received_at'))}'),
                trailing: FilledButton(
                  onPressed: () async {
                    if (await showDialog<bool>(context: context, builder: (_) => QualityDialog(batch: b)) == true) {
                      setState(() => _key = UniqueKey());
                    }
                  },
                  child: const Text('Check'),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class HubsScreen extends ConsumerStatefulWidget {
  const HubsScreen({super.key});

  @override
  ConsumerState<HubsScreen> createState() => _HubsScreenState();
}

class _HubsScreenState extends ConsumerState<HubsScreen> {
  Key _key = UniqueKey();

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Reloadable<List<Map<String, dynamic>>>(
      key: _key,
      load: () => live(api.getList('/hubs', query: {'include_inactive': true})),
      builder: (context, hubs, reload) => ListView(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: FilledButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Add collection hub'),
              onPressed: () async {
                final name = TextEditingController();
                final district = TextEditingController();
                final ok = await showDialog<bool>(
                  context: context,
                  builder: (context) => AlertDialog(
                    title: const Text('New hub'),
                    content: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [FormText(controller: name, label: 'Name'), FormText(controller: district, label: 'District')],
                    ),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
                      FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
                    ],
                  ),
                );
                if (ok != true || name.text.trim().length < 2 || !context.mounted) return;
                await runAction(
                  context,
                  () => api.post(
                    '/admin/hubs',
                    body: {
                      'name': name.text.trim(),
                      if (district.text.trim().isNotEmpty) 'district': district.text.trim(),
                    },
                  ),
                );
                setState(() => _key = UniqueKey());
              },
            ),
          ),
          for (final h in hubs)
            SwitchListTile(
              title: Text(h.str('name')),
              subtitle: Text(h.str('district', '—')),
              value: h.boolVal('is_active'),
              onChanged: (v) async {
                await runAction(context, () => api.patch('/admin/hubs/${h.str('id')}', {'is_active': v}));
                await reload();
              },
            ),
        ],
      ),
    );
  }
}
