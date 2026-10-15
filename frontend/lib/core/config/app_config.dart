/// Build-time configuration via --dart-define.
///
/// Android emulator reaches the Windows host at 10.0.2.2.
/// Physical phone on the same Wi-Fi: use the PC's LAN IP, e.g.
///   flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000/api/v1
class AppConfig {
  const AppConfig._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000/api/v1',
  );

  static const Duration connectTimeout = Duration(seconds: 10);
  static const Duration receiveTimeout = Duration(seconds: 20);

  /// Assistant questions may wait for a local AI model (slow on CPU-only servers).
  static const Duration assistantTimeout = Duration(seconds: 120);

  /// A crop photo may be checked by a local vision model, which can take a minute or more on a CPU.
  static const Duration photoCheckTimeout = Duration(seconds: 180);
}
