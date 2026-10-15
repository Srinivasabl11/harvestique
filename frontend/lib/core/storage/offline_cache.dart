import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Basic offline cache: the last successful response of selected reads, with the time it was saved.
/// Shown only with a visible "offline, saved at ..." banner; never presented as live data.
class OfflineCache {
  static const _prefix = 'cache:';

  Future<void> put(String key, Object? json) async {
    final prefs = await SharedPreferences.getInstance();
    final entry = jsonEncode({'saved_at': DateTime.now().toIso8601String(), 'data': json});
    await prefs.setString('$_prefix$key', entry);
  }

  Future<CachedEntry?> get(String key) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('$_prefix$key');
    if (raw == null) return null;
    final decoded = jsonDecode(raw);
    if (decoded is! Map<String, dynamic>) return null;
    final saved = DateTime.tryParse('${decoded['saved_at']}');
    return saved == null ? null : CachedEntry(decoded['data'], saved);
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    for (final k in prefs.getKeys().where((k) => k.startsWith(_prefix)).toList()) {
      await prefs.remove(k);
    }
  }
}

class CachedEntry {
  const CachedEntry(this.data, this.savedAt);

  final Object? data;
  final DateTime savedAt;
}

final offlineCacheProvider = Provider<OfflineCache>((ref) => OfflineCache());
