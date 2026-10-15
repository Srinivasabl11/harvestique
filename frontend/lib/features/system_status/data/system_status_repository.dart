import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../domain/system_status.dart';

/// Abstract contract so widgets/tests depend on the interface, not on Dio.
abstract interface class SystemStatusRepository {
  Future<SystemStatus> fetchReadiness();
}

class HttpSystemStatusRepository implements SystemStatusRepository {
  HttpSystemStatusRepository(this._dio);

  final Dio _dio;

  @override
  Future<SystemStatus> fetchReadiness() async {
    try {
      final res = await _dio.get<Map<String, dynamic>>('/health/ready');
      return SystemStatus.fromJson(res.data!);
    } catch (e) {
      throw mapDioError(e);
    }
  }
}

final systemStatusRepositoryProvider = Provider<SystemStatusRepository>(
  (ref) => HttpSystemStatusRepository(ref.watch(dioProvider)),
);

final systemStatusProvider = FutureProvider.autoDispose<SystemStatus>(
  (ref) => ref.watch(systemStatusRepositoryProvider).fetchReadiness(),
);
