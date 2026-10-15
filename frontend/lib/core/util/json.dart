/// Null-safe, cast-safe readers for decoded JSON (the analyzer runs with strict-casts).
extension JsonRead on Map<String, dynamic> {
  String str(String key, [String fallback = '']) {
    final v = this[key];
    if (v == null) return fallback;
    return v is String ? v : v.toString();
  }

  String? strOrNull(String key) {
    final v = this[key];
    return v == null ? null : (v is String ? v : v.toString());
  }

  double numVal(String key, [double fallback = 0]) {
    final v = this[key];
    if (v is num) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? fallback;
    return fallback;
  }

  double? numOrNull(String key) {
    final v = this[key];
    if (v is num) return v.toDouble();
    if (v is String) return double.tryParse(v);
    return null;
  }

  int intVal(String key, [int fallback = 0]) {
    final v = this[key];
    if (v is int) return v;
    if (v is num) return v.toInt();
    if (v is String) return int.tryParse(v) ?? fallback;
    return fallback;
  }

  bool boolVal(String key, [bool fallback = false]) {
    final v = this[key];
    return v is bool ? v : fallback;
  }

  Map<String, dynamic> obj(String key) {
    final v = this[key];
    return v is Map<String, dynamic> ? v : <String, dynamic>{};
  }

  Map<String, dynamic>? objOrNull(String key) {
    final v = this[key];
    return v is Map<String, dynamic> ? v : null;
  }

  List<Map<String, dynamic>> objs(String key) => asObjects(this[key]);

  List<String> strs(String key) {
    final v = this[key];
    return v is List<dynamic> ? v.map((e) => e.toString()).toList() : <String>[];
  }
}

/// Converts a decoded JSON list into a list of objects, skipping anything else.
List<Map<String, dynamic>> asObjects(Object? value) {
  if (value is! List<dynamic>) return <Map<String, dynamic>>[];
  return value.whereType<Map<String, dynamic>>().toList();
}
