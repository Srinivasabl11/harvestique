import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/admin/admin_shell.dart';
import '../features/auth/auth_controller.dart';
import '../features/auth/change_password_screen.dart';
import '../features/auth/login_screen.dart';
import '../features/auth/register_screen.dart';
import '../features/buyer/buyer_shell.dart';
import '../features/shell/farmer_shell.dart';
import '../features/system_status/presentation/system_status_screen.dart';

/// Re-runs the redirect whenever the sign-in state changes.
class _AuthRefresh extends ChangeNotifier {
  _AuthRefresh(Ref ref) {
    ref.listen<AuthState>(authProvider, (_, __) => notifyListeners());
  }
}

String homeFor(String role) => switch (role) {
      'farmer' => FarmerShell.routePath,
      'buyer' => BuyerShell.routePath,
      'admin' => AdminShell.routePath,
      _ => LoginScreen.routePath,
    };

/// Central route table with role routing: each role lands in its own shell and cannot open another role's.
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = _AuthRefresh(ref);
  ref.onDispose(refresh.dispose);
  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: refresh,
    redirect: (context, state) {
      final auth = ref.read(authProvider);
      final loc = state.matchedLocation;
      if (loc == SystemStatusScreen.routePath) return null;
      switch (auth.status) {
        case AuthStatus.unknown:
          return loc == '/splash' ? null : '/splash';
        case AuthStatus.signedOut:
          const open = [LoginScreen.routePath, RegisterScreen.routePath, ChangePasswordScreen.routePath];
          if (loc == ChangePasswordScreen.routePath && state.extra is! String) return LoginScreen.routePath;
          return open.contains(loc) ? null : LoginScreen.routePath;
        case AuthStatus.signedIn:
          final home = homeFor(auth.role);
          return loc.startsWith(home) ? null : home;
      }
    },
    routes: [
      GoRoute(path: '/splash', builder: (context, state) => const _Splash()),
      GoRoute(path: LoginScreen.routePath, builder: (context, state) => const LoginScreen()),
      GoRoute(path: RegisterScreen.routePath, builder: (context, state) => const RegisterScreen()),
      GoRoute(
        path: ChangePasswordScreen.routePath,
        builder: (context, state) => ChangePasswordScreen(phone: state.extra! as String, forced: true),
      ),
      GoRoute(path: FarmerShell.routePath, builder: (context, state) => const FarmerShell()),
      GoRoute(path: BuyerShell.routePath, builder: (context, state) => const BuyerShell()),
      GoRoute(path: AdminShell.routePath, builder: (context, state) => const AdminShell()),
      GoRoute(path: SystemStatusScreen.routePath, builder: (context, state) => const SystemStatusScreen()),
    ],
  );
});

class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) => const Scaffold(body: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading')));
}
