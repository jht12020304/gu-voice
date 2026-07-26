import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../shared/widgets/language_bar.dart';
import 'auth_notifier.dart';
import 'password_rules.dart';

// Port of RegisterPage.tsx — patient self-registration (name/email/password/confirm).
class RegisterPage extends ConsumerStatefulWidget {
  const RegisterPage({super.key});

  @override
  ConsumerState<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends ConsumerState<RegisterPage> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  String? _localError;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final err = validateRegistration(
      name: _name.text, email: _email.text, password: _password.text, confirm: _confirm.text);
    if (err != null) {
      setState(() => _localError = err);
      return;
    }
    setState(() => _localError = null);
    try {
      await ref.read(authProvider.notifier).register(_email.text.trim(), _password.text, _name.text.trim());
      // Router redirect lands the new patient on their home.
    } catch (_) {/* error surfaced via provider */}
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final error = _localError ?? auth.error;
    return Scaffold(
      appBar: AppBar(),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(t('auth.register.title'), textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Text(t('auth.register.subtitle'), textAlign: TextAlign.center),
              const SizedBox(height: 24),
              TextField(controller: _name, decoration: InputDecoration(labelText: t('auth.register.nameLabel'))),
              const SizedBox(height: 12),
              TextField(controller: _email, keyboardType: TextInputType.emailAddress, decoration: InputDecoration(labelText: t('auth.register.emailLabel'))),
              const SizedBox(height: 12),
              TextField(controller: _password, obscureText: true, decoration: InputDecoration(labelText: t('auth.register.passwordLabel'), helperText: t('auth.password.hint'))),
              const SizedBox(height: 12),
              TextField(controller: _confirm, obscureText: true, decoration: InputDecoration(labelText: t('auth.register.confirmPasswordLabel'))),
              if (error != null) ...[
                const SizedBox(height: 12),
                Text(error, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 20),
              FilledButton(
                onPressed: auth.isLoading ? null : _submit,
                child: auth.isLoading
                    ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(t('auth.register.submit')),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: () => context.go(prefixLngToPath('/login', currentLng)),
                child: Text(t('auth.register.loginNow')),
              ),
              const SizedBox(height: 24),
              const LanguageBar(),
            ]),
          ),
        ),
      ),
    );
  }
}
