import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/widgets/common.dart';
import 'auth_controller.dart';
import 'forgot_password_screen.dart';
import 'otp_screen.dart';
import 'phone.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  static const routePath = '/login';

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _form = GlobalKey<FormState>();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  String _country = '+91';
  bool _busy = false;

  @override
  void dispose() {
    _phone.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    Map<String, dynamic>? challenge;
    await runAction(context, () async {
      challenge = await ref.read(authProvider.notifier).login(e164(_country, _phone.text), _password.text);
    });
    if (!mounted) return;
    setState(() => _busy = false);
    if (challenge != null) context.go(OtpScreen.routePath, extra: challenge);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Form(
              key: _form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.agriculture, size: 64),
                  const SizedBox(height: 8),
                  Text('Harvestique', textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 24),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 120,
                        child: DropdownButtonFormField<String>(
                          initialValue: _country,
                          isExpanded: true,
                          decoration: const InputDecoration(labelText: 'Country'),
                          items: [for (final (code, _) in countryCodes) DropdownMenuItem(value: code, child: Text(code))],
                          onChanged: (v) => setState(() => _country = v ?? '+91'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: FormText(
                          controller: _phone,
                          label: 'Mobile number',
                          keyboard: TextInputType.phone,
                          validator: (v) => validatePhone(_country, v ?? ''),
                        ),
                      ),
                    ],
                  ),
                  FormText(controller: _password, label: 'Password', obscure: true, validator: requiredText),
                  const Text('After your password we send a one-time code to your phone.', style: TextStyle(fontSize: 12)),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Signing in…' : 'Sign in')),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: () => context.go(ForgotPasswordScreen.routePath),
                      child: const Text('Forgot password?'),
                    ),
                  ),
                  TextButton(onPressed: () => context.go('/register'), child: const Text('New here? Create an account')),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
