import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/features/system_status/data/system_status_repository.dart';
import 'package:harvestique/features/system_status/domain/system_status.dart';
import 'package:harvestique/features/system_status/presentation/system_status_screen.dart';

class _FakeRepo implements SystemStatusRepository {
  _FakeRepo(this._result);
  final Object _result;

  @override
  Future<SystemStatus> fetchReadiness() async {
    final r = _result;
    if (r is SystemStatus) return r;
    throw r;
  }
}

Widget _wrap(SystemStatusRepository repo) => ProviderScope(
      overrides: [systemStatusRepositoryProvider.overrideWithValue(repo)],
      child: const MaterialApp(home: SystemStatusScreen()),
    );

void main() {
  testWidgets('shows ready status from repository', (tester) async {
    await tester.pumpWidget(
      _wrap(
        _FakeRepo(
          SystemStatus.fromJson({
            'status': 'ready',
            'components': [
              {'name': 'database', 'status': 'ok', 'critical': true},
            ],
          }),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('System ready'), findsOneWidget);
    expect(find.text('database'), findsOneWidget);
  });

  testWidgets('shows error when server unreachable', (tester) async {
    await tester.pumpWidget(_wrap(_FakeRepo(const AppFailure('network', 'down'))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('status-error')), findsOneWidget);
  });
}
