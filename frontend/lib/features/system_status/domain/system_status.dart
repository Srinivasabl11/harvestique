class ComponentStatus {
  const ComponentStatus({required this.name, required this.status, required this.critical});

  factory ComponentStatus.fromJson(Map<String, dynamic> json) => ComponentStatus(
        name: json['name'] as String,
        status: json['status'] as String,
        critical: json['critical'] as bool,
      );

  final String name;
  final String status;
  final bool critical;
}

class SystemStatus {
  const SystemStatus({required this.status, required this.components});

  factory SystemStatus.fromJson(Map<String, dynamic> json) => SystemStatus(
        status: json['status'] as String,
        components:
            (json['components'] as List<dynamic>).map((e) => ComponentStatus.fromJson(e as Map<String, dynamic>)).toList(),
      );

  final String status;
  final List<ComponentStatus> components;

  bool get isReady => status == 'ready';
}
