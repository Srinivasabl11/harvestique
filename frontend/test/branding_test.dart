import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/widgets/brand.dart';
import 'package:harvestique/features/home/quotes/quote_hero.dart';

/// The seedling photo is the only brand image: launcher icons, splash, sign-in and Home all use it, and the old
/// Karnataka flag/map branding is gone. (Kannada quotes and Karnataka data are content, not branding, and stay.)
void main() {
  const res = 'android/app/src/main/res';
  String read(String path) => File(path).readAsStringSync();

  test('brand assets exist and are declared', () {
    final pubspec = read('pubspec.yaml');
    for (final asset in [HarvestiqueQuoteHero.asset, BrandLogo.asset]) {
      expect(File(asset).existsSync(), isTrue, reason: asset);
      expect(pubspec, contains('- $asset'));
    }
    expect(File('branding/seedling_source.png').existsSync(), isTrue);
  });

  test('no old flag or map branding is left', () {
    expect(read('pubspec.yaml'), isNot(contains('karnataka_hero')));
    expect(File('assets/images/karnataka_hero.png').existsSync(), isFalse);
    expect(File('branding/karnataka_flag_source.png').existsSync(), isFalse);
    expect(File('$res/drawable/ic_launcher_background.xml').existsSync(), isFalse);
    expect(read('$res/values/ic_launcher_colors.xml'), isNot(contains('flag')));
  });

  test('launcher icons exist for every density, legacy and adaptive', () {
    for (final d in ['mdpi', 'hdpi', 'xhdpi', 'xxhdpi', 'xxxhdpi']) {
      for (final f in ['ic_launcher.png', 'ic_launcher_round.png', 'ic_launcher_foreground.png']) {
        expect(File('$res/mipmap-$d/$f').existsSync(), isTrue, reason: '$d/$f');
      }
    }
    for (final f in ['ic_launcher.xml', 'ic_launcher_round.xml']) {
      final xml = read('$res/mipmap-anydpi-v26/$f');
      expect(xml, contains('@mipmap/ic_launcher_foreground'));
      expect(xml, contains('@color/ic_launcher_background'));
      expect(xml, contains('@drawable/ic_launcher_monochrome'));
    }
    expect(File('$res/drawable/ic_launcher_monochrome.xml').existsSync(), isTrue);
  });

  test('the launch screen shows the seedling', () {
    expect(File('$res/drawable-xxhdpi/splash_seedling.png').existsSync(), isTrue);
    for (final f in ['drawable/launch_background.xml', 'drawable-v21/launch_background.xml']) {
      expect(read('$res/$f'), contains('@drawable/splash_seedling'), reason: f);
    }
  });
}
