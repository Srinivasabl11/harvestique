import 'package:flutter/material.dart';

import '../buyer/orders_screen.dart';
import '../shell/shell_actions.dart';
import 'admin_screens.dart';

class AdminShell extends StatefulWidget {
  const AdminShell({super.key});

  static const routePath = '/admin';

  @override
  State<AdminShell> createState() => _AdminShellState();
}

class _AdminShellState extends State<AdminShell> {
  int _index = 0;
  static const _titles = ['Dashboard', 'Orders', 'Quality queue', 'Hubs', 'Testers'];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_titles[_index]), actions: const [NotificationBell(), AccountMenu()]),
      body: IndexedStack(
        index: _index,
        children: const [DashboardScreen(), OrdersScreen(), QualityQueueScreen(), HubsScreen(), TestersScreen()],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), label: 'Dashboard'),
          NavigationDestination(icon: Icon(Icons.receipt_long_outlined), label: 'Orders'),
          NavigationDestination(icon: Icon(Icons.fact_check_outlined), label: 'Quality'),
          NavigationDestination(icon: Icon(Icons.warehouse_outlined), label: 'Hubs'),
          NavigationDestination(icon: Icon(Icons.verified_user_outlined), label: 'Testers'),
        ],
      ),
    );
  }
}
