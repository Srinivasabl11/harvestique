import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/core/util/format.dart';
import 'package:harvestique/features/farm/expenses_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

/// API double: an in-memory expense list for farm-1 that POST and DELETE change (optionally failing like the server).
class _FakeApi extends ApiClient {
  _FakeApi(this.expenses, {this.failWith}) : super(tokens: _NoTokens(), cache: OfflineCache());

  final List<Map<String, dynamic>> expenses;
  final AppFailure? failWith;
  final posts = <(String, Object?)>[];
  final deletes = <String>[];
  final queries = <Map<String, dynamic>?>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async {
    queries.add(query);
    final cycle = query?['crop_cycle_id'];
    final items = expenses.where((e) => cycle == null || e['crop_cycle_id'] == cycle).toList();
    return {'items': items, 'total': items.length, 'limit': 100, 'offset': 0};
  }

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async => [_cycle];

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    if (failWith != null) throw failWith!;
    final m = body! as Map<String, dynamic>;
    expenses.insert(0, {'id': 'new', 'crop_cycle_id': m['crop_cycle_id'], ...m});
    return expenses.first;
  }

  @override
  Future<void> delete(String path) async {
    deletes.add(path);
    expenses.removeWhere((e) => path == '/expenses/${e['id']}');
  }
}

const _cycle = <String, dynamic>{'id': 'cycle-1', 'crop_name': 'Ragi', 'status': 'growing', 'sowing_date': '2026-09-01'};

Map<String, dynamic> _expense(String id, String category, num amount, {String? cycle}) =>
    {'id': id, 'category': category, 'amount': amount, 'expense_date': '2026-10-01', 'crop_cycle_id': cycle, 'description': null};

Widget _app(ApiClient api, {String? cycleId}) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(home: ExpensesScreen(farmId: 'farm-1', cycleId: cycleId)),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  final today = DateTime(2026, 10, 9);

  group('validateExpense', () {
    String? v({String? category = 'seed', String amount = '1200', DateTime? date}) =>
        validateExpense(category: category, amountText: amount, date: date ?? today, today: today);

    test('accepts a complete expense', () => expect(v(amount: '1200.50'), isNull));
    test('needs a category', () => expect(v(category: null), contains('Choose what')));
    test('needs a positive amount', () {
      expect(v(amount: ''), contains('amount'));
      expect(v(amount: '0'), contains('amount'));
      expect(v(amount: '-5'), contains('amount'));
      expect(v(amount: 'abc'), contains('amount'));
    });
    test('at most 2 decimals (paise)', () => expect(v(amount: '10.555'), contains('2 digits')));
    test('too large for the server', () => expect(v(amount: '10000000000'), contains('too large')));
    test('not in the future', () => expect(v(date: DateTime(2026, 10, 10)), contains('future')));
  });

  test('expenseBody matches the API contract (POST /farms/{id}/expenses)', () {
    expect(
      expenseBody(category: 'labour', amount: 1500.5, date: today, cycleId: 'cycle-1', description: '  2 workers  '),
      {
        'category': 'labour',
        'amount': 1500.5,
        'expense_date': '2026-10-09',
        'crop_cycle_id': 'cycle-1',
        'description': '2 workers',
      },
    );
    final farmWide = expenseBody(category: 'other', amount: 10, date: today, description: ' ');
    expect(farmWide.containsKey('crop_cycle_id'), isFalse);
    expect(farmWide.containsKey('description'), isFalse);
  });

  test('rupees groups thousands and keeps paise only when present', () {
    expect(rupees(1200), '₹1,200');
    expect(rupees(1234567.5), '₹1,234,567.50');
    expect(rupees(null), '—');
  });

  testWidgets('lists the farm expenses with their total and crop', (tester) async {
    final api = _FakeApi([_expense('e1', 'seed', 1200, cycle: 'cycle-1'), _expense('e2', 'labour', 800.5)]);
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    expect(find.text('₹2,000.50'), findsOneWidget);
    expect(find.text('₹1,200 · Seed'), findsOneWidget);
    expect(find.textContaining('Ragi'), findsOneWidget);
    expect(find.textContaining('Whole farm'), findsOneWidget);
    expect(api.queries.first, {'limit': 100});
  });

  testWidgets('a crop page asks only for that crop\'s expenses', (tester) async {
    final api = _FakeApi([_expense('e1', 'seed', 1200, cycle: 'cycle-1'), _expense('e2', 'labour', 800)]);
    await tester.pumpWidget(_app(api, cycleId: 'cycle-1'));
    await tester.pumpAndSettle();
    expect(api.queries.first, {'limit': 100, 'crop_cycle_id': 'cycle-1'});
    expect(find.text('₹1,200'), findsOneWidget);
    expect(find.textContaining('Labour'), findsNothing);
  });

  testWidgets('adding an expense posts it, closes the form and updates the total', (tester) async {
    final api = _FakeApi([]);
    await tester.pumpWidget(_app(api, cycleId: 'cycle-1'));
    await tester.pumpAndSettle();
    expect(find.textContaining('No expenses yet'), findsOneWidget);

    await tester.tap(find.text('Add expense'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Fertilizer'));
    await tester.enterText(find.widgetWithText(TextField, 'Amount (₹)'), '2450.75');
    await tester.enterText(find.widgetWithText(TextField, 'Note (optional)'), '2 bags of urea');
    await tester.scrollUntilVisible(find.text('Save expense').hitTestable(), 200, scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Save expense'));
    await tester.pumpAndSettle();

    expect(api.posts, hasLength(1));
    final (path, body) = api.posts.single;
    expect(path, '/farms/farm-1/expenses');
    final m = body! as Map<String, dynamic>;
    expect(m['category'], 'fertilizer');
    expect(m['amount'], 2450.75);
    expect(m['crop_cycle_id'], 'cycle-1'); // opened from the crop page: linked to that crop by default
    expect(m['description'], '2 bags of urea');
    expect(m['expense_date'], isoDate(DateTime.now()));
    expect(find.text('Save expense'), findsNothing); // form closed
    expect(find.text('₹2,450.75'), findsOneWidget); // list reloaded
  });

  testWidgets('the form explains problems and keeps server rejections on screen', (tester) async {
    const failure = AppFailure('farm_archived', 'This farm is archived; un-archive it to add records');
    final api = _FakeApi([], failWith: failure);
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Add expense'));
    await tester.pumpAndSettle();
    final form = find.byType(Scrollable).first;
    final save = find.text('Save expense');

    await tester.enterText(find.widgetWithText(TextField, 'Amount (₹)'), '500');
    await tester.scrollUntilVisible(save.hitTestable(), 200, scrollable: form);
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty); // no category chosen: nothing is sent
    await tester.scrollUntilVisible(find.text('Choose what the money was spent on.').hitTestable(), -200, scrollable: form);

    await tester.tap(find.text('Seed'));
    await tester.scrollUntilVisible(save.hitTestable(), 200, scrollable: form);
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.posts, hasLength(1));
    expect(api.posts.single.$2, isNot(contains('crop_cycle_id'))); // whole farm by default on the farm page
    await tester.scrollUntilVisible(find.textContaining('archived').hitTestable(), -200, scrollable: form);
    expect(find.textContaining('archived'), findsOneWidget);
    expect(find.widgetWithText(AppBar, 'Add expense'), findsOneWidget); // the form stays open
  });

  testWidgets('deleting asks first, then removes the expense', (tester) async {
    final api = _FakeApi([_expense('e1', 'seed', 1200), _expense('e2', 'labour', 800)]);
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Delete').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Keep'));
    await tester.pumpAndSettle();
    expect(api.deletes, isEmpty);

    await tester.tap(find.byTooltip('Delete').first);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
    await tester.pumpAndSettle();
    expect(api.deletes, ['/expenses/e1']);
    expect(find.text('₹800'), findsOneWidget);
  });
}
