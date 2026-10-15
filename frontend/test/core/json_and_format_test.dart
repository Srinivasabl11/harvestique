import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/util/format.dart';
import 'package:harvestique/core/util/json.dart';

void main() {
  group('JsonRead', () {
    final j = <String, dynamic>{
      's': 'text',
      'n': 12.5,
      'ns': '7',
      'i': 3,
      'b': true,
      'o': <String, dynamic>{'x': 1},
      'l': <dynamic>[
        <String, dynamic>{'a': 1},
        'not an object',
      ],
      'nul': null,
    };

    test('reads values safely with fallbacks', () {
      expect(j.str('s'), 'text');
      expect(j.str('missing', 'fb'), 'fb');
      expect(j.str('nul', 'fb'), 'fb');
      expect(j.numVal('n'), 12.5);
      expect(j.numVal('ns'), 7);
      expect(j.numOrNull('s'), isNull);
      expect(j.intVal('i'), 3);
      expect(j.boolVal('b'), isTrue);
      expect(j.boolVal('s'), isFalse);
      expect(j.obj('o').intVal('x'), 1);
      expect(j.obj('s'), isEmpty);
      expect(j.objs('l'), hasLength(1));
      expect(j.objs('missing'), isEmpty);
    });
  });

  group('format', () {
    test('kg groups thousands and keeps one decimal', () {
      expect(kg(2000), '2,000 kg');
      expect(kg(1985.5), '1,985.5 kg');
      expect(kg(null), '—');
    });

    test('dates', () {
      expect(day('2026-10-08'), '8 Oct 2026');
      expect(day('not a date'), 'not a date');
      expect(isoDate(DateTime(2026, 1, 5)), '2026-01-05');
    });

    test('isoWithOffset always includes a UTC offset', () {
      final s = isoWithOffset(DateTime(2026, 10, 9, 6, 30));
      expect(RegExp(r'^2026-10-09T06:30:00[+-]\d\d:\d\d$').hasMatch(s), isTrue);
    });

    test('labels', () {
      expect(label('pest_affected'), 'Pest affected');
      expect(label(''), '');
    });
  });

  test('dateTime uses the local date as well as the local time', () {
    // 18:55 UTC on 13 Oct is 00:25 on 14 Oct in India: the date must move with the time
    final utc = DateTime.utc(2026, 10, 13, 18, 55);
    final local = utc.toLocal();
    final expected =
        '${local.day} ${const ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][local.month - 1]} '
        '${local.year} ${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
    expect(dateTime('2026-10-13T18:55:00Z'), expected);
  });
}
