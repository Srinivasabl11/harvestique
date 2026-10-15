import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/theme/app_theme.dart';

void main() {
  // The app crashed on start (debug) because the theme scaled a text theme without font sizes.
  for (final (name, build) in [('light', AppTheme.light), ('dark', AppTheme.dark)]) {
    testWidgets('the $name theme builds and renders text 8% larger than Material', (tester) async {
      final theme = build();
      final body = theme.textTheme.bodyMedium!;
      expect(body.fontSize, closeTo(14 * 1.08, 0.01));
      await tester.pumpWidget(MaterialApp(theme: theme, home: const Scaffold(body: Text('Harvestique'))));
      expect(find.text('Harvestique'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
