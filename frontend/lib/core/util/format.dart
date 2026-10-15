/// Display helpers. Numbers are shown as returned by the server; nothing is rounded into a different claim.
String kg(num? value) {
  if (value == null) return '—';
  final v = value.toDouble();
  final whole = v == v.roundToDouble();
  final text = whole ? v.toStringAsFixed(0) : v.toStringAsFixed(1);
  return '${_group(text)} kg';
}

String number(num? value, {int decimals = 1}) {
  if (value == null) return '—';
  final v = value.toDouble();
  return v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(decimals);
}

/// 1234.5 -> "₹1,234.50"; whole amounts drop the paise ("₹1,200").
String rupees(num? value) {
  if (value == null) return '—';
  final v = value.toDouble();
  return '₹${_group(v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(2))}';
}

String _group(String text) {
  final parts = text.split('.');
  final digits = parts[0];
  final neg = digits.startsWith('-');
  final d = neg ? digits.substring(1) : digits;
  final buf = StringBuffer();
  for (var i = 0; i < d.length; i++) {
    if (i > 0 && (d.length - i) % 3 == 0) buf.write(',');
    buf.write(d[i]);
  }
  return '${neg ? '-' : ''}$buf${parts.length > 1 ? '.${parts[1]}' : ''}';
}

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "2026-10-08" or an ISO timestamp -> "8 Oct 2026". Unparseable input is returned unchanged.
String day(String? iso) {
  if (iso == null || iso.isEmpty) return '—';
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  final local = iso.length > 10 ? d.toLocal() : d;
  return '${local.day} ${_months[local.month - 1]} ${local.year}';
}

String dateTime(String? iso) {
  if (iso == null || iso.isEmpty) return '—';
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  final l = d.toLocal();
  final hh = l.hour.toString().padLeft(2, '0');
  final mm = l.minute.toString().padLeft(2, '0');
  // date and time both in the phone's time zone (the UTC date is a day early between midnight and 05:30 IST)
  return '${l.day} ${_months[l.month - 1]} ${l.year} $hh:$mm';
}

String isoDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// A local date and time as an ISO-8601 string with the device's UTC offset (the API requires an offset).
String isoWithOffset(DateTime local) {
  final o = local.timeZoneOffset;
  final sign = o.isNegative ? '-' : '+';
  final h = o.inHours.abs().toString().padLeft(2, '0');
  final m = (o.inMinutes.abs() % 60).toString().padLeft(2, '0');
  final base = '${isoDate(local)}T${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}:00';
  return '$base$sign$h:$m';
}

/// "pest_affected" -> "Pest affected"
String label(String raw) {
  if (raw.isEmpty) return raw;
  final s = raw.replaceAll('_', ' ');
  return s[0].toUpperCase() + s.substring(1);
}
