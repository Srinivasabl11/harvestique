import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'auth_controller.dart';
import 'login_screen.dart';
import 'otp_screen.dart';
import 'phone.dart';

/// The server's password rule: 8-128 characters with at least one letter and one digit.
String? validateNewPassword(String? v) {
  final s = v ?? '';
  if (s.length < 8) return 'At least 8 characters';
  if (s.length > 128) return 'At most 128 characters';
  if (!s.contains(RegExp('[A-Za-z]')) || !s.contains(RegExp('[0-9]'))) return 'Use letters and numbers';
  return null;
}

/// Forgot password, for farmers and buyers alike: 1) mobile number, 2) the code sent by SMS + a new password.
/// The server answers the same whether or not the number has an account, so this screen never says which.
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  static const routePath = '/forgot-password';

  @override
  ConsumerState<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _numberForm = GlobalKey<FormState>();
  final _resetForm = GlobalKey<FormState>();
  final _phone = TextEditingController();
  final _code = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  String _country = '+91';
  Map<String, dynamic>? _challenge;
  int _resendIn = 0;
  Timer? _timer;
  bool _busy = false;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _timer?.cancel();
    for (final c in [_phone, _code, _password, _confirm]) {
      c.dispose();
    }
    super.dispose();
  }

  void _countdown(int seconds) {
    _timer?.cancel();
    _resendIn = seconds;
    if (seconds <= 0) return;
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || _resendIn <= 0) return t.cancel();
      setState(() => _resendIn -= 1);
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      await action();
    } catch (e) {
      final f = e is AppFailure ? e : mapDioError(e);
      if (mounted) setState(() => _error = f.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sendCode() async {
    if (!_numberForm.currentState!.validate()) return;
    await _run(() async {
      final ch = await ref.read(authProvider.notifier).forgotPassword(e164(_country, _phone.text));
      if (!mounted) return;
      setState(() => _challenge = ch);
      _countdown(ch.intVal('resend_after'));
    });
  }

  Future<void> _resend() async {
    await _run(() async {
      final ch = await ref.read(authProvider.notifier).resend(_challenge!.str('challenge_id'));
      if (!mounted) return;
      setState(() {
        _challenge = ch;
        _code.clear();
        _info = 'A new code was requested. The previous code no longer works.';
      });
      _countdown(ch.intVal('resend_after'));
    });
  }

  Future<void> _reset() async {
    if (!_resetForm.currentState!.validate()) return;
    await _run(() async {
      await ref.read(authProvider.notifier).resetPassword(_challenge!.str('challenge_id'), _code.text.trim(), _password.text);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password changed. Sign in with your new password.')),
      );
      context.go(LoginScreen.routePath);
    });
  }

  @override
  Widget build(BuildContext context) {
    final ch = _challenge;
    final length = ch?.intVal('code_length', 6) ?? 6;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Reset password'),
        leading: BackButton(onPressed: () => context.go(LoginScreen.routePath)),
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          if (_error != null)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: ListTile(leading: const Icon(Icons.error_outline), title: Text(_error!)),
            ),
          if (ch == null)
            Form(
              key: _numberForm,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('Enter the mobile number of your account. We send a one-time code to it.'),
                  const SizedBox(height: 12),
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
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _busy ? null : _sendCode, child: Text(_busy ? 'Sending…' : 'Send code')),
                ],
              ),
            )
          else
            Form(
              key: _resetForm,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(ch.str('message')),
                  if (ch.str('delivery') == 'development_console') ...[const SizedBox(height: 12), DevCodeNotice(challenge: ch)],
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _code,
                    keyboardType: TextInputType.number,
                    maxLength: length,
                    autofillHints: const [AutofillHints.oneTimeCode],
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    decoration: InputDecoration(labelText: '$length-digit code', counterText: ''),
                    validator: (v) => RegExp('^\\d{$length}\$').hasMatch(v ?? '') ? null : 'Enter the $length-digit code',
                  ),
                  FormText(
                      controller: _password,
                      label: 'New password (8+ letters and numbers)',
                      obscure: true,
                      validator: validateNewPassword,),
                  FormText(
                    controller: _confirm,
                    label: 'Confirm new password',
                    obscure: true,
                    validator: (v) => v == _password.text ? null : 'The passwords do not match',
                  ),
                  if (_info != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_info!)),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _busy ? null : _reset, child: Text(_busy ? 'Saving…' : 'Set new password')),
                  TextButton(
                    onPressed: _busy || _resendIn > 0 ? null : _resend,
                    child: Text(_resendIn > 0 ? 'Send a new code in $_resendIn s' : 'Send a new code'),
                  ),
                  Text(
                    'The code expires after ${(ch.intVal('expires_in', 300) / 60).ceil()} minutes. '
                    'After the change, every device is signed out; sign in again with the new password.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
