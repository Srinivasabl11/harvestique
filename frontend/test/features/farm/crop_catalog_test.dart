import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/farm/crop_catalog.dart';

final _crops = [
  {'name': 'Tomato', 'local_name': 'ಟೊಮೆಟೊ', 'category': 'vegetable'},
  {'name': 'Mango', 'local_name': 'ಮಾವು', 'category': 'fruit'},
  {'name': 'Napier Grass', 'local_name': null, 'category': 'fodder'},
  {'name': 'Banana', 'local_name': 'ಬಾಳೆ', 'category': 'fruit'},
];

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _PagedApi extends ApiClient {
  _PagedApi(this.total) : super(tokens: _NoTokens(), cache: OfflineCache());

  final int total;
  final offsets = <int>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async {
    final offset = query!['offset'] as int;
    offsets.add(offset);
    final n = (total - offset).clamp(0, 100);
    return {
      'total': total,
      'items': [for (var i = 0; i < n; i++) {'name': 'c${offset + i}'}],
    };
  }
}

void main() {
  test('filter by English or Kannada name and by category, sorted by name', () {
    expect(filterCrops(_crops, '', null).map((c) => c['name']), ['Banana', 'Mango', 'Napier Grass', 'Tomato']);
    expect(filterCrops(_crops, '', 'fruit').map((c) => c['name']), ['Banana', 'Mango']);
    expect(filterCrops(_crops, 'ಮಾವು', null).map((c) => c['name']), ['Mango']);
    final withAliases = [
      {'name': 'Ragi', 'local_name': 'ರಾಗಿ', 'category': 'cereal', 'aliases': ['finger millet'], 'scientific_name': 'Eleusine coracana'},
      {'name': 'Sapota', 'local_name': 'ಸಪೋಟ', 'category': 'fruit', 'aliases': ['chikoo', 'sapodilla']},
      {'name': 'Cassava', 'category': 'vegetable'}, // a new crop: no Kannada name, no aliases sent
    ];
    expect(filterCrops(withAliases, 'finger', null).map((c) => c['name']), ['Ragi']);
    expect(filterCrops(withAliases, 'CHIKOO', null).map((c) => c['name']), ['Sapota']);
    expect(filterCrops(withAliases, 'eleusine', null).map((c) => c['name']), ['Ragi']);
    expect(filterCrops(withAliases, 'cassava', null).map((c) => c['name']), ['Cassava']);
    expect(filterCrops(_crops, 'grass', 'fruit'), isEmpty);
  });

  test('getAll follows the pages until the total is reached', () async {
    final api = _PagedApi(230);
    final all = await api.getAll('/crops');
    expect(all, hasLength(230));
    expect(api.offsets, [0, 100, 200]);
  });

  testWidgets('category chips show counts and select or clear a category', (tester) async {
    String? selected;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatefulBuilder(
            builder: (context, setState) => CropCategoryChips(
              crops: _crops,
              selected: selected,
              onSelected: (k) => setState(() => selected = k),
            ),
          ),
        ),
      ),
    );
    expect(find.text('All (4)'), findsOneWidget);
    expect(find.text('Fruits (2)'), findsOneWidget);
    expect(find.text('Fodder (1)'), findsOneWidget);
    expect(find.textContaining('Medicinal'), findsNothing); // no crops in it
    expect(categoryName('cereal'), 'Cereals & millets');
    expect(categoryName('plantation'), 'Plantation crops');
    await tester.tap(find.text('Fruits (2)'));
    await tester.pump();
    expect(selected, 'fruit');
    await tester.tap(find.text('All (4)'));
    await tester.pump();
    expect(selected, isNull);
  });
}
