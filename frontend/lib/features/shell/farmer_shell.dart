import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../assistant/assistant_screen.dart';
import '../farm/farms_screen.dart';
import '../harvest/harvest_screen.dart';
import '../home/farmer_home_screen.dart';
import '../market/farmer_market_screen.dart';
import '../reminders/reminders_screen.dart';
import '../onboarding/tour.dart';
import 'shell_actions.dart';
import 'shell_navigation.dart';

/// Farmer app: Home, My Farm, Market, Harvest, Reminders. The assistant is one tap away everywhere.
class FarmerShell extends ConsumerStatefulWidget {
  const FarmerShell({super.key});

  static const routePath = '/farmer';

  @override
  ConsumerState<FarmerShell> createState() => _FarmerShellState();
}

class _FarmerShellState extends ConsumerState<FarmerShell> {
  int _index = 0;
  static const _titles = ['Home', 'My Farm', 'Market', 'Harvest', 'Reminders'];
  // a new key reloads a tab when it is opened again, so a change made in one tab (e.g. accepting an order in Market)
  // shows in the others (e.g. Harvest) instead of the data loaded at sign-in
  final _tabKeys = List<Key>.generate(5, (_) => UniqueKey());

  void _select(int i) => setState(() {
        if (i != _index) _tabKeys[i] = UniqueKey();
        _index = i;
      });

  @override
  Widget build(BuildContext context) {
    ref.listen<String?>(shellTabRequestProvider, (_, target) {
      final i = farmerTabs[target];
      if (target == null || i == null) return;
      _select(i);
      ref.read(shellTabRequestProvider.notifier).state = null;
    });
    return TourGate(
      child: Scaffold(
        appBar: AppBar(
          title: Text(_titles[_index]),
          actions: const [NotificationBell(), AccountMenu()],
        ),
        body: IndexedStack(
          index: _index,
          children: [
            KeyedSubtree(key: _tabKeys[0], child: const FarmerHomeScreen()),
            KeyedSubtree(key: _tabKeys[1], child: const FarmsScreen()),
            KeyedSubtree(key: _tabKeys[2], child: const FarmerMarketScreen()),
            KeyedSubtree(key: _tabKeys[3], child: const HarvestScreen()),
            KeyedSubtree(key: _tabKeys[4], child: const RemindersScreen()),
          ],
        ),
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
            NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Home'),
            NavigationDestination(
                icon: Icon(Icons.agriculture_outlined), selectedIcon: Icon(Icons.agriculture), label: 'My Farm',),
            NavigationDestination(icon: Icon(Icons.storefront_outlined), selectedIcon: Icon(Icons.storefront), label: 'Market'),
            NavigationDestination(
                icon: Icon(Icons.inventory_2_outlined), selectedIcon: Icon(Icons.inventory_2), label: 'Harvest',),
            NavigationDestination(icon: Icon(Icons.alarm_outlined), selectedIcon: Icon(Icons.alarm), label: 'Reminders'),
          ],
        ),
      ),
    );
  }
}
