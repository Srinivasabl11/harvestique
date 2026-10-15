import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

/// Tester access: approve new sign-ups, suspend (sessions kept) or revoke (signed out) individual accounts, and
/// reset a forgotten password (one-time temporary password). The server enforces every decision; this screen only
/// asks for it.
class TestersScreen extends ConsumerStatefulWidget {
  const TestersScreen({super.key});

  @override
  ConsumerState<TestersScreen> createState() => _TestersScreenState();
}

class _TestersScreenState extends ConsumerState<TestersScreen> {
  static const _filters = {'pending': 'Waiting', 'approved': 'Approved', 'suspended': 'Suspended', 'revoked': 'Revoked'};
  static const _actions = {'approved': 'Approve', 'suspended': 'Suspend', 'revoked': 'Revoke access'};
  static const _done = {'approved': 'approved', 'suspended': 'suspended', 'revoked': 'access revoked'};
  String _filter = 'pending';
  Key _key = UniqueKey();

  Future<void> _set(Map<String, dynamic> user, String status) async {
    if (status == 'reset') return _resetPassword(user);
    if (status == 'revoked') {
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Revoke access?'),
          content: Text('${user.str('full_name')} is signed out on every phone and cannot sign in until approved again.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Revoke')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    final api = ref.read(apiProvider);
    await runAction(
      context,
      () => api.post('/admin/users/${user.str('id')}/access', body: {'status': status}),
      success: '${user.str('full_name')}: ${_done[status]}',
    );
    if (mounted) setState(() => _key = UniqueKey());
  }

  /// Sign-in has no SMS step, so check who is asking (e.g. call their number) before resetting.
  Future<void> _resetPassword(Map<String, dynamic> user) async {
    final name = user.str('full_name');
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Reset password?'),
        content: Text(
          'Only do this after checking that the request really comes from $name (for example by calling '
          '${user.str('phone')}). They are signed out on every phone and get a temporary password, which they '
          'must replace at their next sign-in.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Reset')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    Map<String, dynamic>? out;
    await runAction(context, () async {
      out = await ref.read(apiProvider).post('/admin/users/${user.str('id')}/password-reset');
    });
    final result = out;
    if (result == null || !mounted) return;
    final temporary = result.str('temporary_password');
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text('Temporary password for $name'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SelectableText(temporary, style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 12),
            Text(result.str('message')),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Clipboard.setData(ClipboardData(text: temporary)),
            child: const Text('Copy'),
          ),
          FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Done')),
        ],
      ),
    );
    if (mounted) setState(() => _key = UniqueKey());
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Column(
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: Wrap(
            spacing: 8,
            children: [
              for (final f in _filters.entries)
                ChoiceChip(
                  label: Text(f.value),
                  selected: _filter == f.key,
                  onSelected: (_) => setState(() {
                    _filter = f.key;
                    _key = UniqueKey();
                  }),
                ),
            ],
          ),
        ),
        Expanded(
          child: Reloadable<List<Map<String, dynamic>>>(
            key: _key,
            load: () => live(api.getPage('/admin/users', query: {'access': _filter})),
            isEmpty: (u) => u.isEmpty,
            emptyMessage: _filter == 'pending' ? 'Nobody is waiting for approval.' : 'No accounts here.',
            builder: (context, users, reload) => ListView(
              children: [
                for (final u in users)
                  Card(
                    margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    child: ListTile(
                      leading: Icon(u.str('role') == 'buyer' ? Icons.storefront_outlined : Icons.agriculture_outlined),
                      title: Text(u.str('full_name')),
                      subtitle: Text(
                        '${u.str('role')} · ${u.str('phone')}\nJoined ${dateTime(u.str('created_at'))}'
                        '${u.boolVal('must_change_password') ? ' · temporary password not yet changed' : ''}',
                      ),
                      isThreeLine: true,
                      trailing: u.str('role') == 'admin'
                          ? null
                          : PopupMenuButton<String>(
                              tooltip: 'Change access',
                              onSelected: (s) => _set(u, s),
                              itemBuilder: (_) => [
                                for (final a in _actions.entries)
                                  if (a.key != u.str('access_status')) PopupMenuItem(value: a.key, child: Text(a.value)),
                                const PopupMenuItem(value: 'reset', child: Text('Reset password')),
                              ],
                            ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
