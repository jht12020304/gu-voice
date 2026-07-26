import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../shared/widgets/language_bar.dart';
import 'auth_notifier.dart';

// Port of frontend/src/screens/auth/LoginPage.tsx (keys from the `common.login.*` set).
class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  String? _localError;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    final password = _password.text;
    if (email.isEmpty) {
      setState(() => _localError = t('common.login.emailRequired'));
      return;
    }
    if (password.isEmpty) {
      setState(() => _localError = t('common.login.passwordRequired'));
      return;
    }
    setState(() => _localError = null);
    try {
      await ref.read(authProvider.notifier).login(email, password);
      // Router redirect navigates to the role home on success.
    } catch (_) {
      // error surfaced via authProvider.error below
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final error = _localError ?? auth.error;

    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  t('common.appTitle'),
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                Text(t('common.login.prompt'), textAlign: TextAlign.center),
                const SizedBox(height: 32),
                TextField(
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  decoration: InputDecoration(labelText: t('common.login.emailLabel')),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _password,
                  obscureText: true,
                  autofillHints: const [AutofillHints.password],
                  onSubmitted: (_) => _submit(),
                  decoration: InputDecoration(
                    labelText: t('common.login.passwordLabel'),
                    hintText: t('common.login.passwordPlaceholder'),
                  ),
                ),
                if (error != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    error,
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ],
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: auth.isLoading ? null : _submit,
                  child: auth.isLoading
                      ? const SizedBox(
                          height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(t('common.login.submit')),
                ),
                const SizedBox(height: 8),
                Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  TextButton(
                    onPressed: () => context.go(prefixLngToPath('/forgot-password', currentLng)),
                    child: Text(t('common.login.forgotPassword')),
                  ),
                  TextButton(
                    onPressed: () => context.go(prefixLngToPath('/register', currentLng)),
                    child: Text(t('auth.register.title')),
                  ),
                ]),
                const SizedBox(height: 24),
                const LanguageBar(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
