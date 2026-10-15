import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/harvest/harvest_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  bool accepted = false;
  int calls = 0;

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async {
    calls++;
    if (path == '/inventory/lots') return [];
    return accepted
        ? [
            {'order_id': 'a1b2c3d4-0000', 'crop_name': 'Ragi', 'quantity_kg': 50, 'fulfilled_kg': 0, 'window_end': '2027-01-25'},
          ]
        : [];
  }
}

void main() {
  testWidgets('pull to refresh shows a delivery accepted elsewhere', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
        child: const MaterialApp(home: Scaffold(body: HarvestScreen())),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('None yet.'), findsOneWidget);
    api.accepted = true;
    await tester.fling(find.byType(ListView), const Offset(0, 400), 1000);
    await tester.pumpAndSettle();
    expect(api.calls, 4); // loaded again, not served from the screen's old state
    expect(find.textContaining('Ragi'), findsOneWidget);
  });
}
