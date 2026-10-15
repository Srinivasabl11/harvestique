import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/core/widgets/brand.dart';
import 'package:harvestique/features/auth/login_screen.dart';
import 'package:harvestique/features/auth/phone.dart';

class NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

void main() {
  testWidgets('login requires phone and password before calling the server', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [tokenStoreProvider.overrideWithValue(NoTokens())],
        child: const MaterialApp(home: LoginScreen()),
      ),
    );
    await tester.tap(find.text('Sign in'));
    await tester.pump();
    expect(find.text('Enter your mobile number'), findsOneWidget);
    expect(find.text('Required'), findsOneWidget); // the password
    expect(find.textContaining('one-time code'), findsNothing); // no SMS step any more
  });

  testWidgets('sign-in shows the seedling brand logo', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [tokenStoreProvider.overrideWithValue(NoTokens())],
        child: const MaterialApp(home: LoginScreen()),
      ),
    );
    expect(find.byType(BrandLogo), findsOneWidget);
    expect(
      find.byWidgetPredicate((w) => w is Image && w.image == const AssetImage(BrandLogo.asset)),
      findsOneWidget,
    );
  });

  group('phone numbers with a country code', () {
    test('Indian mobiles', () {
      expect(validatePhone('+91', '98765 43210'), isNull);
      expect(e164('+91', '98765-43210'), '+919876543210');
      expect(validatePhone('+91', '98765'), contains('10 digits'));
      expect(validatePhone('+91', '1234567890'), contains('starts with 6, 7, 8 or 9'));
      expect(validatePhone('+91', '98765abcde'), 'Use digits only');
      expect(validatePhone('+91', ''), 'Enter your mobile number');
    });
    test('other countries', () {
      expect(validatePhone('+44', '7911123456'), isNull);
      expect(e164('+44', '7911 123456'), '+447911123456');
      expect(validatePhone('+44', '07911123456'), contains('leading 0'));
      expect(validatePhone('+1', '12345'), contains('leading 0'));
    });
  });
}
