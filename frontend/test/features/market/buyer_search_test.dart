import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/features/buyer/search_screen.dart';

void main() {
  test('harvest search and new demand explain what is missing instead of doing nothing', () {
    expect(validateHarvestSearch(cropId: null, quantity: '100'), 'Choose a crop.');
    expect(validateHarvestSearch(cropId: 'c1', quantity: ''), contains('quantity'));
    expect(validateHarvestSearch(cropId: 'c1', quantity: '-5'), contains('above 0'));
    expect(validateHarvestSearch(cropId: 'c1', quantity: 'abc'), isNotNull);
    expect(validateHarvestSearch(cropId: 'c1', quantity: '99999999'), 'That quantity is too large.');
    expect(validateHarvestSearch(cropId: 'c1', quantity: ' 250 '), isNull);
  });
}
