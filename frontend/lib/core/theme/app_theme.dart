import 'package:flutter/material.dart';

/// Farmer-friendly theme: crop green, high contrast, larger text and generous touch targets (>= 48 dp).
class AppTheme {
  const AppTheme._();

  static const Color _seed = Color(0xFF2E7D32); // crop green

  static ThemeData light() => _build(Brightness.light);

  static ThemeData dark() => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(seedColor: _seed, brightness: brightness);
    final base = ThemeData(colorScheme: scheme, useMaterial3: true, brightness: brightness);
    return base.copyWith(
      materialTapTargetSize: MaterialTapTargetSize.padded,
      visualDensity: VisualDensity.standard,
      // ThemeData's text theme carries no font sizes in current Flutter; add Material's standard sizes first,
      // otherwise scaling fails an assertion (red screen at start in debug builds).
      textTheme: Typography.englishLike2021.merge(base.textTheme).apply(fontSizeFactor: 1.08),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(minimumSize: const Size(64, 52), textStyle: const TextStyle(fontSize: 16)),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
      ),
      inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
      listTileTheme: const ListTileThemeData(minVerticalPadding: 10),
    );
  }
}

/// Colours for data-provenance and risk indicators (always paired with text, never colour alone).
class Signal {
  const Signal._();

  static const measured = Color(0xFF2E7D32);
  static const estimate = Color(0xFFB26A00);
  static const assumption = Color(0xFF616161);
  static const simulated = Color(0xFF6A1B9A);
  static const userEntered = Color(0xFF1565C0);
  static const low = Color(0xFF2E7D32);
  static const medium = Color(0xFFB26A00);
  static const high = Color(0xFFC62828);
}
