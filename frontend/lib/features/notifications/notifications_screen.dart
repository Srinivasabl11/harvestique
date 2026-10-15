import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../shell/shell_actions.dart';

IconData notificationIcon(String category) => switch (category) {
      'reminder' => Icons.alarm,
      'participation_request' => Icons.handshake_outlined,
      'participation_response' => Icons.how_to_reg_outlined,
      'shortage' => Icons.warning_amber_rounded,
      'reallocation' => Icons.sync_alt,
      'order_update' => Icons.receipt_long_outlined,
      'collection' => Icons.local_shipping_outlined,
      'quality' => Icons.fact_check_outlined,
      'fulfilment' => Icons.task_alt,
      'buyer_opportunity' => Icons.storefront_outlined,
      _ => Icons.notifications_outlined,
    };

/// The in-app notification feed. Marking as read updates the item at once (and is undone with a message if the
/// server refuses), then refreshes the unread badge.
class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});

  @override
  ConsumerState<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  Key _key = UniqueKey();
  final _readNow = <String>{}; // marked read in this screen (shown read before the reload)
  final _busy = <String>{};
  bool _allBusy = false;

  void _snack(String text, {Future<void> Function()? retry}) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(text),
          action: retry == null ? null : SnackBarAction(label: 'Retry', onPressed: retry),
        ),
      );
  }

  Future<void> _markRead(String id) async {
    if (_busy.contains(id)) return;
    setState(() {
      _busy.add(id);
      _readNow.add(id);
    });
    try {
      await ref.read(apiProvider).post('/notifications/$id/read');
      ref.invalidate(unreadProvider);
    } catch (e) {
      if (!mounted) return;
      setState(() => _readNow.remove(id)); // undo: it is still unread on the server
      _snack((e is AppFailure ? e : mapDioError(e)).message, retry: () => _markRead(id));
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  Future<void> _markAll(List<Map<String, dynamic>> unread) async {
    setState(() => _allBusy = true);
    try {
      await ref.read(apiProvider).post('/notifications/read-all');
      ref.invalidate(unreadProvider);
      if (!mounted) return;
      setState(() {
        _readNow.addAll(unread.map((n) => n.str('id')));
        _key = UniqueKey(); // reload from the server
      });
      _snack('All notifications marked as read');
    } catch (e) {
      if (mounted) _snack((e is AppFailure ? e : mapDioError(e)).message, retry: () => _markAll(unread));
    } finally {
      if (mounted) setState(() => _allBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Notifications')),
      body: Reloadable<List<Map<String, dynamic>>>(
        key: _key,
        load: () => api.cached('notifications', () => api.getPage('/notifications'), asObjects),
        isEmpty: (d) => d.isEmpty,
        emptyMessage: 'No notifications yet. Order updates, reminders and buyer requests appear here.',
        builder: (context, items, reload) {
          bool isUnread(Map<String, dynamic> n) => n.strOrNull('read_at') == null && !_readNow.contains(n.str('id'));
          final unread = items.where(isUnread).toList();
          return ListView.separated(
            itemCount: items.length + 1,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              if (i == 0) {
                return Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
                  child: Row(
                    children: [
                      Expanded(child: Text(unread.isEmpty ? 'All read' : '${unread.length} unread')),
                      TextButton.icon(
                        onPressed: unread.isEmpty || _allBusy ? null : () => _markAll(unread),
                        icon: _allBusy
                            ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.done_all),
                        label: const Text('Mark all read'),
                      ),
                    ],
                  ),
                );
              }
              final n = items[i - 1];
              final id = n.str('id');
              final isNew = isUnread(n);
              final severe = n.str('severity') == 'warning';
              return ListTile(
                tileColor: isNew ? scheme.primaryContainer.withValues(alpha: 0.35) : null,
                leading: Badge(
                  isLabelVisible: isNew,
                  smallSize: 10,
                  child: Icon(notificationIcon(n.str('category')), color: severe ? Colors.orange.shade800 : null),
                ),
                title: Text(n.str('title'), style: TextStyle(fontWeight: isNew ? FontWeight.bold : FontWeight.normal)),
                subtitle: Text('${n.str('body')}\n${dateTime(n.str('created_at'))}${isNew ? ' · New' : ''}'),
                isThreeLine: true,
                onTap: isNew ? () => _markRead(id) : null,
                trailing: isNew
                    ? IconButton(
                        tooltip: 'Mark as read',
                        icon: _busy.contains(id)
                            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.mark_email_read_outlined),
                        onPressed: _busy.contains(id) ? null : () => _markRead(id),
                      )
                    : const Icon(Icons.check, size: 18),
              );
            },
          );
        },
      ),
    );
  }
}
