import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../assistant/assistant_screen.dart';

import '../reminders/reminders_screen.dart';
import '../onboarding/tour.dart';
import '../shell/shell_actions.dart';
import '../shell/shell_navigation.dart';
import 'buyer_home_screen.dart';
import 'demands_screen.dart';
import 'orders_screen.dart';

class BuyerShell extends ConsumerStatefulWidget {
  const BuyerShell({super.key});

  static const routePath = '/buyer';

  @override
  ConsumerState<BuyerShell> createState() => _BuyerShellState();
}

class _BuyerShellState extends ConsumerState<BuyerShell> {
  int _index = 0;
  static const _titles = ['Market', 'My demands', 'Orders', 'Reminders'];
  // a new key reloads a tab when it is opened again (fresh order status, demand status...)
  final _tabKeys = List<Key>.generate(4, (_) => UniqueKey());

  void _select(int i) => setState(() {
        if (i != _index) _tabKeys[i] = UniqueKey();
        _index = i;
      });

  @override
  Widget build(BuildContext context) {
    ref.listen<String?>(shellTabRequestProvider, (_, target) {
      final i = buyerTabs[target];
      if (target == null || i == null) return;
      _select(i);
      ref.read(shellTabRequestProvider.notifier).state = null;
    });
    return TourGate(
      child: Scaffold(
        appBar: AppBar(title: Text(_titles[_index]), actions: const [NotificationBell(), AccountMenu()]),
        body: IndexedStack(
          index: _index,
          children: [
            KeyedSubtree(key: _tabKeys[0], child: const BuyerHomeScreen()),
            KeyedSubtree(key: _tabKeys[1], child: const DemandsScreen()),
            KeyedSubtree(key: _tabKeys[2], child: const OrdersScreen()),
            KeyedSubtree(key: _tabKeys[3], child: const RemindersScreen()),
          ],
        ),
        // the same assistant as farmers (orders, market supply, reminders, navigation), in English and Kannada
        floatingActionButton: FloatingActionButton.extended(
          heroTag: 'assistant',
          onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const AssistantScreen())),
          icon: const Icon(Icons.mic),
          label: const Text('Ask'),
        ),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: _select,
          destinations: const [
            NavigationDestination(icon: Icon(Icons.storefront_outlined), label: 'Market'),
            NavigationDestination(icon: Icon(Icons.request_quote_outlined), label: 'Demands'),
            NavigationDestination(icon: Icon(Icons.receipt_long_outlined), label: 'Orders'),
            NavigationDestination(icon: Icon(Icons.alarm_outlined), label: 'Reminders'),
          ],
        ),
      ),
    );
  }
}
