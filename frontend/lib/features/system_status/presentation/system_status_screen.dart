import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../data/system_status_repository.dart';

/// Phase 0 screen: proves the app <-> backend <-> database path works end to end.
class SystemStatusScreen extends ConsumerWidget {
  const SystemStatusScreen({super.key});

  static const routePath = '/';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(systemStatusProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Harvestique')),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(systemStatusProvider.future),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('Backend: ${AppConfig.apiBaseUrl}', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 16),
            status.when(
              loading: () => const Center(child: CircularProgressIndicator(semanticsLabel: 'Loading')),
              error: (e, _) => ListTile(
                key: const Key('status-error'),
                leading: const Icon(Icons.cloud_off),
                title: const Text('Server unreachable'),
                subtitle: Text('$e'),
              ),
              data: (s) => Column(
                children: [
                  ListTile(
                    key: const Key('status-overall'),
                    leading: Icon(s.isReady ? Icons.check_circle : Icons.warning_amber),
                    title: Text('System ${s.status}'),
                  ),
                  for (final c in s.components)
                    ListTile(
                      dense: true,
                      title: Text(c.name),
                      trailing: Text(c.status),
                      subtitle: Text(c.critical ? 'critical' : 'optional'),
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
