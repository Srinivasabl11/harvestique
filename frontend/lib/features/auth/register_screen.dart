import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/widgets/common.dart';
import 'auth_controller.dart';
import 'change_password_screen.dart';
import 'login_screen.dart';
import 'phone.dart';

/// Public sign-up is for farmers and buyers only (admins are created by operators).
class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  static const routePath = '/register';

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  final _district = TextEditingController();
  final _business = TextEditingController();
  String _role = 'farmer';
  String _language = 'en';
  String _buyerType = 'retailer';
  String _country = '+91';
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [_name, _phone, _password, _district, _business]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    final district = _district.text.trim();
    final profile = _role == 'farmer'
        ? <String, dynamic>{'preferred_language': _language, if (district.isNotEmpty) 'district': district}
        : <String, dynamic>{
            'business_name': _business.text.trim(),
            'buyer_type': _buyerType,
            if (district.isNotEmpty) 'district': district,
          };
    String? waiting;
    await runAction(context, () async {
      waiting = await ref.read(authProvider.notifier).register({
        'role': _role,
        'full_name': _name.text.trim(),
        'phone': e164(_country, _phone.text),
        'password': _password.text,
        'profile': profile,
      });
    });
    if (!mounted) return;
    setState(() => _busy = false);
    final message = waiting;
    if (message == null) return; // signed in (open sign-up), or the request failed and was reported
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Account request received'),
        content: Text(message),
        actions: [FilledButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
      ),
    );
    if (mounted) context.go(LoginScreen.routePath);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Create account'), leading: BackButton(onPressed: () => context.go('/login'))),
      body: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'farmer', label: Text('Farmer'), icon: Icon(Icons.agriculture)),
                ButtonSegment(value: 'buyer', label: Text('Buyer'), icon: Icon(Icons.storefront)),
              ],
              selected: {_role},
              onSelectionChanged: (s) => setState(() => _role = s.first),
            ),
            const SizedBox(height: 12),
            FormText(controller: _name, label: 'Full name', validator: requiredText),
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
            FormText(controller: _password, label: 'Password (8+ letters and numbers)', obscure: true, validator: validateNewPassword),
            FormText(controller: _district, label: 'District (optional)'),
            if (_role == 'farmer')
              DropdownButtonFormField<String>(
                initialValue: _language,
                decoration: const InputDecoration(labelText: 'Assistant and voice language'),
                items: const [
                  DropdownMenuItem(value: 'en', child: Text('English')),
                  DropdownMenuItem(value: 'kn', child: Text('ಕನ್ನಡ (Kannada)')),
                ],
                onChanged: (v) => setState(() => _language = v ?? 'en'),
              )
            else ...[
              FormText(controller: _business, label: 'Business name', validator: requiredText),
              DropdownButtonFormField<String>(
                initialValue: _buyerType,
                decoration: const InputDecoration(labelText: 'Business type'),
                items: const [
                  DropdownMenuItem(value: 'retailer', child: Text('Retailer')),
                  DropdownMenuItem(value: 'wholesaler', child: Text('Wholesaler')),
                  DropdownMenuItem(value: 'processor', child: Text('Processor')),
                  DropdownMenuItem(value: 'restaurant', child: Text('Restaurant')),
                  DropdownMenuItem(value: 'other', child: Text('Other')),
                ],
                onChanged: (v) => setState(() => _buyerType = v ?? 'other'),
              ),
            ],
            const SizedBox(height: 16),
            const Text(
              'The Harvestique team checks each new account before it can be used. You can sign in with this '
              'number and password once it is approved.',
              style: TextStyle(fontSize: 12),
            ),
            const SizedBox(height: 8),
            FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Creating account…' : 'Create account')),
          ],
        ),
      ),
    );
  }
}
