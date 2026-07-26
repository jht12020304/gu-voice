import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/auth_api.dart';
import '../../shared/widgets/language_action.dart';

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
  // 後端沒設 SENDGRID/SMTP 時為 'onsite'：信不會寄出，要引導找現場醫護／管理員。
  String _delivery = 'onsite';
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
      final r = await AuthApi().forgotPassword(_email.text.trim());
      if (mounted) setState(() { _sent = true; _delivery = r.delivery; _busy = false; });
    } catch (_) {
      if (mounted) setState(() { _error = t('auth.forgot.failed'); _busy = false; });
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
            child: _sent
                ? Column(mainAxisSize: MainAxisSize.min, children: [
                    // onsite 沒有「完成」任何事，不該給信件圖示（與 React 版一致）
                    Icon(
                      _delivery == 'email' ? Icons.mark_email_read : Icons.info_outline,
                      size: 48,
                      color: _delivery == 'email'
                          ? Theme.of(context).colorScheme.primary
                          : Theme.of(context).colorScheme.tertiary,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      t(_delivery == 'email'
                          ? 'auth.forgot.sentTitle'
                          : 'auth.forgot.onsiteTitle'),
                      style: Theme.of(context).textTheme.titleMedium,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _delivery == 'email'
                          ? '${t('auth.forgot.sentPrefix')} ${_email.text.trim()} ${t('auth.forgot.sentSuffix')}'
                          : t('auth.forgot.onsiteBody'),
                      textAlign: TextAlign.center,
                    ),
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
