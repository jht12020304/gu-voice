import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/auth_api.dart';
import 'password_rules.dart';
import '../../shared/widgets/language_action.dart';

// Port of ResetPasswordPage.tsx — set a new password via the emailed reset token
// (deep-linked as /:lng/reset-password?token=...).
class ResetPasswordPage extends StatefulWidget {
  const ResetPasswordPage({super.key, required this.token});
  final String token;

  @override
  State<ResetPasswordPage> createState() => _ResetPasswordPageState();
}

class _ResetPasswordPageState extends State<ResetPasswordPage> {
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  bool _done = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (widget.token.isEmpty) {
      setState(() => _error = t('auth.reset.invalidToken'));
      return;
    }
    final err = validatePassword(_password.text, _confirm.text);
    if (err != null) {
      setState(() => _error = err);
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      await AuthApi().resetPassword(widget.token, _password.text);
      if (mounted) setState(() { _done = true; _busy = false; });
    } catch (_) {
      if (mounted) setState(() { _error = t('auth.reset.failed'); _busy = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(actions: const [LanguageAction()]),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: _done
                ? Column(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.check_circle, size: 48, color: Theme.of(context).colorScheme.primary),
                    const SizedBox(height: 12),
                    Text(t('auth.reset.doneTitle'), style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Text(t('auth.reset.doneMessage'), textAlign: TextAlign.center),
                    const SizedBox(height: 20),
                    FilledButton(onPressed: () => context.go(prefixLngToPath('/login', currentLng)), child: Text(t('auth.backToLogin'))),
                  ])
                : Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Text(t('auth.reset.title'), textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    Text(t('auth.reset.subtitle'), textAlign: TextAlign.center),
                    const SizedBox(height: 24),
                    TextField(controller: _password, obscureText: true, decoration: InputDecoration(labelText: t('auth.reset.newPasswordLabel'), helperText: t('auth.password.hint'))),
                    const SizedBox(height: 12),
                    TextField(controller: _confirm, obscureText: true, decoration: InputDecoration(labelText: t('auth.reset.confirmPasswordLabel'))),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ],
                    const SizedBox(height: 20),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: _busy
                          ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                          : Text(t('auth.reset.submit')),
                    ),
                    const SizedBox(height: 12),
                    TextButton(onPressed: () => context.go(prefixLngToPath('/login', currentLng)), child: Text(t('auth.backToLogin'))),
                  ]),
          ),
        ),
      ),
    );
  }
}
