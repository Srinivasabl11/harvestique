import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/json.dart';
import 'auth_controller.dart';
import 'login_screen.dart';

/// Step 2 of sign-up and sign-in: the one-time code sent by SMS. Signing in happens only after the server accepts
/// the code. On a development server (no SMS provider) the server returns the code instead; it is shown in a
/// clearly marked box and never described as an SMS.
class OtpScreen extends ConsumerStatefulWidget {
  const OtpScreen({super.key, required this.challenge});

  static const routePath = '/verify';

  /// The server's challenge (POST /auth/register or /auth/login).
  final Map<String, dynamic> challenge;

  @override
  ConsumerState<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends ConsumerState<OtpScreen> {
  final _code = TextEditingController();
  late Map<String, dynamic> _challenge = widget.challenge;
  late int _resendIn = _challenge.intVal('resend_after');
  Timer? _timer;
  String? _error;
  String? _info;
  bool _busy = false;

  String get _purpose => _challenge.str('purpose', 'login');
  int get _length => _challenge.intVal('code_length', 6);

  @override
  void initState() {
    super.initState();
    _tick();
  }

  void _tick() {
    _timer?.cancel();
    if (_resendIn <= 0) return;
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      if (_resendIn <= 0) return t.cancel();
      setState(() => _resendIn -= 1);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _code.dispose();
    super.dispose();
  }

  Future<void> _verify() async {
    final code = _code.text.trim();
    if (!RegExp('^\\d{$_length}\$').hasMatch(code)) {
      setState(() => _error = 'Enter the $_length-digit code.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      await ref.read(authProvider.notifier).verify(_purpose, _challenge.str('challenge_id'), code);
      // signed in: the router leaves this screen for the home screen
    } catch (e) {
      final f = e is AppFailure ? e : mapDioError(e);
      if (mounted) {
        setState(() {
          _error = f.message;
          _busy = false;
        });
      }
    }
  }

  Future<void> _resend() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final next = await ref.read(authProvider.notifier).resend(_challenge.str('challenge_id'));
      if (!mounted) return;
      setState(() {
        _challenge = next;
        _resendIn = next.intVal('resend_after');
        _info = 'A new code was requested. The previous code no longer works.';
        _busy = false;
        _code.clear();
      });
      _tick();
    } catch (e) {
      final f = e is AppFailure ? e : mapDioError(e);
      if (mounted) {
        setState(() {
          _error = f.message;
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final dev = _challenge.str('delivery') == 'development_console';
    return Scaffold(
      appBar: AppBar(
        title: Text(_purpose == 'register' ? 'Verify your number' : 'Enter your code'),
        leading: BackButton(onPressed: () => context.go(LoginScreen.routePath)),
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text(_challenge.str('message'), style: Theme.of(context).textTheme.bodyLarge),
          const SizedBox(height: 8),
          Text('Number: ${_challenge.str('phone_hint')}', style: Theme.of(context).textTheme.titleMedium),
          if (dev) ...[const SizedBox(height: 12), DevCodeNotice(challenge: _challenge)],
          const SizedBox(height: 16),
          TextField(
            controller: _code,
            autofocus: true,
            keyboardType: TextInputType.number,
            maxLength: _length,
            autofillHints: const [AutofillHints.oneTimeCode],
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 28, letterSpacing: 8),
            decoration: InputDecoration(labelText: '$_length-digit code', counterText: ''),
            onChanged: (v) {
              if (_error != null) setState(() => _error = null);
              if (v.length == _length && !_busy) _verify();
            },
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_error!, style: TextStyle(color: scheme.error)),
            ),
          if (_info != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_info!)),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy ? null : _verify,
            child: Text(_busy ? 'Checking…' : (_purpose == 'register' ? 'Verify and create account' : 'Verify and sign in')),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _busy || _resendIn > 0 ? null : _resend,
            child: Text(_resendIn > 0 ? 'Send a new code in $_resendIn s' : 'Send a new code'),
          ),
          Text(
            'The code expires after ${(_challenge.intVal('expires_in', 300) / 60).ceil()} minutes. '
            '${_challenge.intVal('attempts_left', 5)} attempts left. Never share this code with anyone.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

/// Development servers only: the server has no SMS provider and returned the code. Never shown as an SMS.
class DevCodeNotice extends StatelessWidget {
  const DevCodeNotice({super.key, required this.challenge});

  final Map<String, dynamic> challenge;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      color: scheme.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'DEVELOPMENT MODE – not sent by SMS',
              style: TextStyle(fontWeight: FontWeight.bold, color: scheme.onTertiaryContainer),
            ),
            const SizedBox(height: 4),
            Text(
              challenge.strOrNull('dev_code') == null
                  ? 'This development server has no SMS provider and returned no code for this request.'
                  : 'This server has no SMS provider, so it returned the code: ${challenge.str('dev_code')}',
              style: TextStyle(color: scheme.onTertiaryContainer),
            ),
          ],
        ),
      ),
    );
  }
}
