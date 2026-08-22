import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/auth_api.dart';
import '../auth/auth_notifier.dart';

// Port of PatientSettingsPage.tsx — profile / notifications / security tabs.
// The language select is zh-TW/en-US only; per the Dart port note it drives the app's
// single language authority (the URL/route lng) directly rather than a drifting side-store.
class PatientSettingsPage extends ConsumerStatefulWidget {
  const PatientSettingsPage({super.key});

  @override
  ConsumerState<PatientSettingsPage> createState() => _PatientSettingsPageState();
}

class _PatientSettingsPageState extends ConsumerState<PatientSettingsPage> {
  final _emailCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  bool _emailNotif = true;
  bool _pushNotif = false;
  bool _saving = false;
  String? _saveMsg;
  bool _saveOk = false;
  bool _seeded = false;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _phoneCtrl.dispose();
    super.dispose();
  }

  Future<void> _saveProfile() async {
    setState(() { _saving = true; _saveMsg = null; });
    try {
      // email 是登入身分：後端 UpdateProfileRequest 本來就不收 email（會被
      // pydantic 靜默丟棄），舊版卻照送＋報成功＝假儲存（2026-08-23 稽核）。
      // 改 email 需要驗證流程，этот頁只存電話。
      await ref.read(authProvider.notifier).updateProfile({
        'phone': _phoneCtrl.text.trim(),
      });
      setState(() { _saveOk = true; _saveMsg = t('common.patient.settings.savedMessage'); });
    } catch (_) {
      setState(() { _saveOk = false; _saveMsg = t('common.patient.settings.saveFailedMessage'); });
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authProvider).user;
    if (!_seeded && user != null) {
      _emailCtrl.text = user.email;
      _phoneCtrl.text = user.phone ?? '';
      _seeded = true;
    }

    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: Text(user?.name ?? ''),
          bottom: TabBar(tabs: [
            Tab(text: t('common.patient.settings.tabProfile')),
            Tab(text: t('common.patient.settings.tabNotifications')),
            Tab(text: t('common.patient.settings.tabSecurity')),
          ]),
        ),
        body: TabBarView(children: [_profileTab(), _notificationsTab(), _securityTab()]),
      ),
    );
  }

  Widget _profileTab() {
    final theme = Theme.of(context);
    final user = ref.watch(authProvider).user;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(t('common.patient.settings.profileTitle'), style: theme.textTheme.titleMedium),
        const SizedBox(height: 16),
        TextField(
          enabled: false,
          controller: TextEditingController(text: user?.name ?? ''),
          decoration: InputDecoration(
            labelText: t('common.patient.settings.fullName'),
            helperText: t('common.patient.settings.fullNameHint'),
          ),
        ),
        const SizedBox(height: 12),
        // 唯讀：與姓名同理（登入身分不在此頁修改）。
        TextField(
          controller: _emailCtrl,
          enabled: false,
          decoration: InputDecoration(labelText: t('common.patient.settings.emailLabel')),
        ),
        const SizedBox(height: 12),
        TextField(controller: _phoneCtrl, decoration: InputDecoration(labelText: t('common.patient.settings.phoneLabel'))),
        const SizedBox(height: 16),
        Text(t('common.patient.settings.preferredLanguage'), style: theme.textTheme.bodyMedium),
        const SizedBox(height: 8),
        // All supported languages, not just zh/en — the app ships 5 and a patient whose
        // language is ja/ko/vi could not pick it here. Switching drives the URL language
        // authority; the whole URI is preserved so query params survive.
        Wrap(spacing: 8, children: [
          for (final lng in supportedLanguages)
            ChoiceChip(
              selected: currentLng == lng,
              label: Text(
                t('common.language.names.$lng') +
                    (betaLanguages.contains(lng) ? ' ${t('common.language.betaTag')}' : ''),
              ),
              onSelected: (_) {
                final uri = GoRouterState.of(context).uri;
                context.go(uri.replace(path: prefixLngToPath(uri.path, lng)).toString());
              },
            ),
        ]),
        const SizedBox(height: 20),
        FilledButton(
          onPressed: _saving ? null : _saveProfile,
          child: _saving
              ? Text(t('common.saving'))
              : Text(t('common.patient.settings.saveChanges')),
        ),
        if (_saveMsg != null) ...[
          const SizedBox(height: 12),
          Text(_saveMsg!,
              style: TextStyle(color: _saveOk ? theme.colorScheme.primary : theme.colorScheme.error)),
        ],
      ],
    );
  }

  Widget _notificationsTab() {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(t('common.patient.settings.notificationsTitle'), style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        SwitchListTile(
          value: _emailNotif,
          onChanged: (v) => setState(() => _emailNotif = v),
          title: Text(t('common.patient.settings.emailNotifications')),
          subtitle: Text(t('common.patient.settings.emailNotificationsHint')),
        ),
        SwitchListTile(
          value: _pushNotif,
          onChanged: (v) => setState(() => _pushNotif = v),
          title: Text(t('common.patient.settings.pushNotifications')),
          subtitle: Text(t('common.patient.settings.pushNotificationsHint')),
        ),
      ],
    );
    // ponytail: toggles are ephemeral (no persistence/API) — wire to shared_preferences
    // when a real notification backend exists; the web version only writes localStorage too.
  }

  Widget _securityTab() {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(t('common.patient.settings.securityTitle'), style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        ListTile(
          leading: const Icon(Icons.key),
          title: Text(t('common.patient.settings.changePassword')),
          subtitle: Text(t('common.patient.settings.changePasswordHint')),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => showDialog(context: context, builder: (_) => const _ChangePasswordDialog()),
        ),
      ],
    );
  }
}

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog();

  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _current = TextEditingController();
  final _new = TextEditingController();
  final _confirm = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _current.dispose();
    _new.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    // The web modal validates only: required / minLength 8 / mismatch.
    if (_current.text.isEmpty || _new.text.isEmpty || _confirm.text.isEmpty) {
      setState(() => _error = t('common.patient.settings.passwordRequired'));
      return;
    }
    if (_new.text.length < 8) {
      setState(() => _error = t('common.patient.settings.passwordTooShort'));
      return;
    }
    if (_new.text != _confirm.text) {
      setState(() => _error = t('common.patient.settings.passwordMismatch'));
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      await AuthApi().changePassword(_current.text, _new.text);
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(t('common.patient.settings.passwordChanged'))),
      );
    } catch (_) {
      setState(() { _busy = false; _error = t('common.patient.settings.passwordChangeFailed'); });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(t('common.patient.settings.changePassword')),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(controller: _current, obscureText: true, decoration: InputDecoration(labelText: t('common.patient.settings.currentPassword'))),
          const SizedBox(height: 8),
          TextField(controller: _new, obscureText: true, decoration: InputDecoration(labelText: t('common.patient.settings.newPassword'), helperText: t('common.patient.settings.passwordHint'))),
          const SizedBox(height: 8),
          TextField(controller: _confirm, obscureText: true, decoration: InputDecoration(labelText: t('common.patient.settings.confirmPassword'))),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ],
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.of(context).pop(), child: Text(t('common.cancel'))),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? t('common.saving') : t('common.patient.settings.changePassword')),
        ),
      ],
    );
  }
}
