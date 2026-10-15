/// Phone numbers with a country code. The server stores and verifies E.164 (+919876543210); these checks give the
/// person the problem before anything is sent. India (+91) is the default.
library;

const countryCodes = <(String, String)>[
  ('+91', 'India +91'),
  ('+977', 'Nepal +977'),
  ('+880', 'Bangladesh +880'),
  ('+94', 'Sri Lanka +94'),
  ('+971', 'UAE +971'),
  ('+1', 'USA / Canada +1'),
  ('+44', 'UK +44'),
];

String _digits(String s) => s.replaceAll(RegExp(r'[\s\-().]'), '');

/// Returns the first problem with the number, or null.
String? validatePhone(String countryCode, String number) {
  final n = _digits(number);
  if (n.isEmpty) return 'Enter your mobile number';
  if (!RegExp(r'^\d+$').hasMatch(n)) return 'Use digits only';
  if (countryCode == '+91') {
    if (n.length != 10) return 'An Indian mobile number has 10 digits';
    if (!RegExp(r'^[6-9]').hasMatch(n)) return 'An Indian mobile number starts with 6, 7, 8 or 9';
    return null;
  }
  final total = countryCode.length - 1 + n.length;
  if (n.startsWith('0') || total < 8 || total > 15) return 'Enter the number without the leading 0';
  return null;
}

/// '+91' + '98765 43210' -> '+919876543210'
String e164(String countryCode, String number) => '$countryCode${_digits(number)}';
