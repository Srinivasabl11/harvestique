import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/widgets/common.dart';
import 'auth_controller.dart';
import 'change_password_screen.dart';
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
    final phone = e164(_country, _phone.text);
    var mustChange = false;
    await runAction(context, () async {
      try {
        await ref.read(authProvider.notifier).login(phone, _password.text);
        // signed in: the router moves on to the home screen
      } catch (e) {
        final f = e is AppFailure ? e : mapDioError(e);
        if (f.code != 'password_change_required') throw f;
        mustChange = true; // an admin reset the password: the temporary one must be replaced first
      }
    });
    if (!mounted) return;
    setState(() => _busy = false);
    if (mustChange) context.go(ChangePasswordScreen.routePath, extra: phone);
  }

  Future<void> _forgot() => showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Forgot your password?'),
          content: const Text(
            'Ask the Harvestique team to reset it. They will check that it is really you and give you a '
            'temporary password. Sign in with it and you will be asked to choose a new password.',
          ),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
        ),
      );

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
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Signing in…' : 'Sign in')),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: _forgot,
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
