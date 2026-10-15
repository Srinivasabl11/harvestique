import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/widgets/common.dart';
import 'auth_controller.dart';
import 'login_screen.dart';

/// The server's password rule: 8-128 characters with at least one letter and one digit (it also refuses
/// well-known passwords and says so).
String? validateNewPassword(String? v) {
  final s = v ?? '';
  if (s.length < 8) return 'At least 8 characters';
  if (s.length > 128) return 'At most 128 characters';
  if (!s.contains(RegExp('[A-Za-z]')) || !s.contains(RegExp('[0-9]'))) return 'Use letters and numbers';
  return null;
}

/// Set a new password. Two ways in:
/// * [forced]: sign-in was refused with `password_change_required` because an admin gave this person a temporary
///   password. They type it here with their own new password and are then signed in.
/// * from the account menu while signed in: the current password and a new one.
/// Either way the server signs out every other device.
class ChangePasswordScreen extends ConsumerStatefulWidget {
  const ChangePasswordScreen({super.key, required this.phone, this.forced = false});

  static const routePath = '/change-password';

  final String phone;
  final bool forced;

  @override
  ConsumerState<ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends ConsumerState<ChangePasswordScreen> {
  final _form = GlobalKey<FormState>();
  final _current = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_current, _password, _confirm]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).changePassword(widget.phone, _current.text, _password.text);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password changed. Any other phone signed in to this account was signed out.')),
      );
      // forced flow: signing in moves the router to the home screen; from the menu: back to where we were
      if (!widget.forced) Navigator.of(context).maybePop();
    } catch (e) {
      final f = e is AppFailure ? e : mapDioError(e);
      if (mounted) setState(() => _error = f.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Set a new password'),
        leading: widget.forced ? BackButton(onPressed: () => context.go(LoginScreen.routePath)) : null,
      ),
      body: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            if (widget.forced)
              const Text(
                'The Harvestique team gave you a temporary password. Enter it below and choose your own new '
                'password to continue.',
              ),
            const SizedBox(height: 8),
            Text('Mobile number: ${widget.phone}', style: Theme.of(context).textTheme.titleMedium),
            if (_error != null)
              Card(
                color: Theme.of(context).colorScheme.errorContainer,
                child: ListTile(leading: const Icon(Icons.error_outline), title: Text(_error!)),
              ),
            FormText(
              controller: _current,
              label: widget.forced ? 'Temporary password' : 'Current password',
              obscure: true,
              validator: requiredText,
            ),
            FormText(
              controller: _password,
              label: 'New password (8+ letters and numbers)',
              obscure: true,
              validator: validateNewPassword,
            ),
            FormText(
              controller: _confirm,
              label: 'Confirm new password',
              obscure: true,
              validator: (v) => v == _password.text ? null : 'The passwords do not match',
            ),
            const SizedBox(height: 16),
            FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'Saving…' : 'Save new password')),
            const SizedBox(height: 8),
            Text(
              'After the change, any other phone signed in to this account is signed out.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
