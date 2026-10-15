import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/network/api_client.dart';
import '../../core/util/json.dart';
import '../auth/auth_controller.dart';
import '../help/help_screen.dart';
import '../notifications/notifications_screen.dart';
import '../system_status/presentation/system_status_screen.dart';

/// Unread notifications, polled every minute while the app is open (the server also turns due reminders
/// into notifications when this is called). No push service is used.
final unreadProvider = StreamProvider.autoDispose<int>((ref) async* {
  final api = ref.watch(apiProvider);
  while (true) {
    try {
      yield (await api.getObj('/notifications/unread-count')).intVal('unread');
    } catch (_) {
      // offline: keep the last value
    }
    await Future<void>.delayed(const Duration(minutes: 1));
  }
});

class NotificationBell extends ConsumerWidget {
  const NotificationBell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(unreadProvider).valueOrNull ?? 0;
    return IconButton(
      tooltip: 'Notifications',
      // one clear spoken label ("Notifications, 2 unread"); without this, screen readers announced only "2"
      icon: Semantics(
        label: unread > 0 ? 'Notifications, $unread unread' : 'Notifications',
        excludeSemantics: true,
        child: Badge(isLabelVisible: unread > 0, label: Text('$unread'), child: const Icon(Icons.notifications_outlined)),
      ),
      onPressed: () async {
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const NotificationsScreen()));
        ref.invalidate(unreadProvider);
      },
    );
  }
}

class AccountMenu extends ConsumerWidget {
  const AccountMenu({super.key, this.extra = const []});

  final List<PopupMenuEntry<String>> extra;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    return PopupMenuButton<String>(
      tooltip: 'Account',
      icon: const Icon(Icons.account_circle_outlined),
      onSelected: (v) async {
        switch (v) {
          case 'help':
            unawaited(Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const HelpScreen())));
          case 'status':
            unawaited(Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const SystemStatusScreen())));
          case 'logout':
            await ref.read(authProvider.notifier).logout();
            if (context.mounted) context.go('/login');
          case 'lang-en':
          case 'lang-kn':
            await ref.read(apiProvider).patch('/farmers/me', {'preferred_language': v.substring(5)});
            await ref.read(authProvider.notifier).refreshUser();
        }
      },
      itemBuilder: (context) => [
        PopupMenuItem<String>(enabled: false, child: Text('${auth.name} (${auth.role})')),
        if (auth.role == 'farmer') ...[
          const PopupMenuItem(value: 'lang-en', child: Text('Assistant language: English')),
          const PopupMenuItem(value: 'lang-kn', child: Text('Assistant language: ಕನ್ನಡ')),
        ],
        ...extra,
        const PopupMenuItem(value: 'help', child: Text('Help & guide')),
        const PopupMenuItem(value: 'status', child: Text('Server status')),
        const PopupMenuItem(value: 'logout', child: Text('Sign out')),
      ],
    );
  }
}
