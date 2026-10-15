import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/notifications/notifications_screen.dart';
import 'package:harvestique/features/reminders/reminders_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  List<Map<String, dynamic>> notifications = [];
  List<Map<String, dynamic>> reminders = [];
  final calls = <(String, String, Object?)>[];
  AppFailure? failNext;
  Completer<void>? slowPost;

  Future<void> _maybeFail() async {
    final f = failNext;
    failNext = null;
    if (f != null) throw f;
  }

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async =>
      path == '/notifications' ? notifications : reminders;

  @override
  Future<List<Map<String, dynamic>>> getList(String path, {Map<String, dynamic>? query}) async => [];

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    calls.add(('POST', path, body));
    if (slowPost != null) await slowPost!.future;
    await _maybeFail();
    if (path.endsWith('/read')) {
      final id = path.split('/')[2];
      notifications = [
        for (final n in notifications) n['id'] == id ? {...n, 'read_at': '2026-10-10T10:00:00Z'} : n,
      ];
    }
    if (path == '/notifications/read-all') {
      notifications = [
        for (final n in notifications) {...n, 'read_at': '2026-10-10T10:00:00Z'},
      ];
    }
    return {};
  }

  @override
  Future<Map<String, dynamic>> patch(String path, Map<String, dynamic> body) async {
    calls.add(('PATCH', path, body));
    await _maybeFail();
    return {};
  }

  @override
  Future<void> delete(String path) async {
    calls.add(('DELETE', path, null));
    await _maybeFail();
    reminders = reminders.where((r) => path != '/reminders/${r['id']}').toList();
  }
}

Map<String, dynamic> _n(String id, String title, {bool read = false}) => {
      'id': id,
      'category': 'order_update',
      'title': title,
      'body': 'Order #A1B2: 300 kg tomato, accepted',
      'severity': 'info',
      'data': <String, dynamic>{},
      'read_at': read ? '2026-10-09T10:00:00Z' : null,
      'created_at': '2026-10-09T09:00:00Z',
    };

Map<String, dynamic> _r(String id, String title) => {
      'id': id,
      'reminder_type': 'irrigation',
      'title': title,
      'notes': null,
      'due_at': DateTime.now().add(const Duration(days: 2)).toUtc().toIso8601String(),
      'recurrence': 'none',
      'status': 'pending',
    };

Widget _app(ApiClient api, Widget home) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
      child: MaterialApp(home: home),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('notifications', () {
    testWidgets('mark one as read: immediate, saved on the server, and the count updates', (tester) async {
      final api = _FakeApi()..notifications = [_n('n1', 'Order accepted'), _n('n2', 'Old news', read: true)];
      await tester.pumpWidget(_app(api, const NotificationsScreen()));
      await tester.pumpAndSettle();
      expect(find.text('1 unread'), findsOneWidget);
      expect(find.byTooltip('Mark as read'), findsOneWidget);
      await tester.tap(find.byTooltip('Mark as read'));
      await tester.pumpAndSettle();
      expect(api.calls.single, ('POST', '/notifications/n1/read', null));
      expect(find.text('All read'), findsOneWidget);
      expect(find.byTooltip('Mark as read'), findsNothing);
    });

    testWidgets('a failed mark-as-read is undone and offers Retry', (tester) async {
      final api = _FakeApi()
        ..notifications = [_n('n1', 'Order accepted')]
        ..failNext = const AppFailure('network', 'Cannot reach the Harvestique server. Check your connection.');
      await tester.pumpWidget(_app(api, const NotificationsScreen()));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Mark as read'));
      await tester.pumpAndSettle();
      expect(find.text('1 unread'), findsOneWidget); // still unread
      expect(find.text('Cannot reach the Harvestique server. Check your connection.'), findsOneWidget);
      await tester.tap(find.text('Retry'));
      await tester.pumpAndSettle();
      expect(find.text('All read'), findsOneWidget);
    });

    testWidgets('mark all read: confirms, and is disabled when nothing is unread', (tester) async {
      final api = _FakeApi()..notifications = [_n('n1', 'A'), _n('n2', 'B')];
      await tester.pumpWidget(_app(api, const NotificationsScreen()));
      await tester.pumpAndSettle();
      expect(find.text('2 unread'), findsOneWidget);
      await tester.tap(find.text('Mark all read'));
      await tester.pumpAndSettle();
      expect(find.text('All notifications marked as read'), findsOneWidget);
      expect(find.text('All read'), findsOneWidget);
      final button = tester.widget<TextButton>(find.ancestor(of: find.text('Mark all read'), matching: find.byType(TextButton)));
      expect(button.onPressed, isNull);
    });
  });

  group('reminders', () {
    test('validation', () {
      final now = DateTime(2026, 10, 10, 9);
      expect(validateReminder(title: ' ', due: now.add(const Duration(hours: 1)), now: now), contains('Write what'));
      expect(validateReminder(title: 'x', due: now.subtract(const Duration(hours: 1)), now: now), contains('already passed'));
      expect(validateReminder(title: 'x' * 161, due: now.add(const Duration(hours: 1)), now: now), contains('160'));
      expect(validateReminder(title: 'Irrigate', due: now.add(const Duration(hours: 1)), now: now), isNull);
    });

    testWidgets('mark done, edit and delete (after confirming)', (tester) async {
      final api = _FakeApi()..reminders = [_r('r1', 'Irrigate north plot')];
      await tester.pumpWidget(_app(api, const Scaffold(body: RemindersScreen())));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Mark done'));
      await tester.pumpAndSettle();
      expect(api.calls.last, ('POST', '/reminders/r1/complete', null));
      expect(find.text('Marked done'), findsOneWidget);

      await tester.tap(find.byTooltip('More actions'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Edit / reschedule'));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(TextField, 'Irrigate north plot'), findsOneWidget); // pre-filled
      await tester.enterText(find.widgetWithText(TextField, 'Irrigate north plot'), 'Irrigate south plot');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(api.calls.last.$1, 'PATCH');
      expect((api.calls.last.$3! as Map)['title'], 'Irrigate south plot');

      await tester.tap(find.byTooltip('More actions'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Keep'));
      await tester.pumpAndSettle();
      expect(api.calls.where((c) => c.$1 == 'DELETE'), isEmpty);
      await tester.tap(find.byTooltip('More actions'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
      await tester.pumpAndSettle();
      expect(api.calls.last, ('DELETE', '/reminders/r1', null));
      expect(find.text('Reminder deleted'), findsOneWidget);
      expect(find.textContaining('Nothing pending'), findsOneWidget);
    });

    testWidgets('a new reminder: empty title is explained, and a double tap saves once', (tester) async {
      final api = _FakeApi();
      await tester.pumpWidget(_app(api, const Scaffold(body: RemindersScreen())));
      await tester.pumpAndSettle();
      await tester.tap(find.text('New reminder'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pump();
      expect(find.text('Write what you want to be reminded about.'), findsOneWidget);
      expect(api.calls, isEmpty);

      await tester.enterText(find.widgetWithText(TextField, 'What to do'), 'Spray neem oil');
      api.slowPost = Completer<void>();
      await tester.tap(find.text('Save'));
      await tester.pump();
      expect(find.text('Saving…'), findsOneWidget);
      await tester.tap(find.text('Saving…'), warnIfMissed: false); // second tap while saving
      await tester.pump();
      api.slowPost!.complete();
      await tester.pumpAndSettle();
      expect(api.calls.where((c) => c.$2 == '/reminders'), hasLength(1));
      expect(find.text('Reminder added'), findsOneWidget);
    });
  });
}
