import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/auth_api.dart';

// Port of ForgotPasswordPage.tsx — request a reset link (uniform response).
class ForgotPasswordPage extends StatefulWidget {
  const ForgotPasswordPage({super.key});

  @override
  State<ForgotPasswordPage> createState() => _ForgotPasswordPageState();
}

class _ForgotPasswordPageState extends State<ForgotPasswordPage> {
  final _email = TextEditingController();
  bool _busy = false;
  bool _sent = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_email.text.trim().isEmpty) {
      setState(() => _error = t('auth.email.required'));
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      await AuthApi().forgotPassword(_email.text.trim());
      if (mounted) setState(() { _sent = true; _busy = false; });
    } catch (_) {
      if (mounted) setState(() { _error = t('auth.forgot.failed'); _busy = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: _sent
                ? Column(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.mark_email_read, size: 48, color: Theme.of(context).colorScheme.primary),
                    const SizedBox(height: 12),
                    Text(t('auth.forgot.sentTitle'), style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Text('${t('auth.forgot.sentPrefix')} ${_email.text.trim()} ${t('auth.forgot.sentSuffix')}', textAlign: TextAlign.center),
                    const SizedBox(height: 20),
                    FilledButton(onPressed: () => context.go(prefixLngToPath('/login', currentLng)), child: Text(t('auth.backToLogin'))),
                  ])
                : Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Text(t('auth.forgot.title'), textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    Text(t('auth.forgot.subtitle'), textAlign: TextAlign.center),
                    const SizedBox(height: 24),
                    TextField(controller: _email, keyboardType: TextInputType.emailAddress, decoration: InputDecoration(labelText: t('auth.forgot.emailLabel'))),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ],
                    const SizedBox(height: 20),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: _busy
                          ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                          : Text(t('auth.forgot.submit')),
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
