import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/env.dart';
import '../../../core/i18n/loc.dart';
import '../../../shared/widgets/language_bar.dart';
import '../../auth/auth_notifier.dart';
import '../../voice/state/settings_notifier.dart';

/// Doctor/admin settings. `/settings` used to render `PatientSettingsPage`, so a doctor
/// got the patient's profile/notification/security tabs and none of the things the
/// `common.doctor.settings.*` translations already promised — theme mode and the sound
/// alert toggle in particular (TODO §G medium).
///
/// Every string here was already in all five locale files; only the page was missing.
///
/// Preferences are in-memory (as in the React version). Persisting them needs a real
/// user-preferences endpoint, which the backend does not have.
class DoctorSettingsPage extends ConsumerWidget {
  const DoctorSettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider.select((s) => s.user));
    final settings = ref.watch(settingsProvider);
    final notifier = ref.read(settingsProvider.notifier);
    final text = Theme.of(context).textTheme;

    Widget section(String title, List<Widget> children) => Card(
          margin: const EdgeInsets.only(bottom: 16),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: text.titleMedium),
                const SizedBox(height: 12),
                ...children,
              ],
            ),
          ),
        );

    Widget row(String label, String? value) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(label, style: text.bodyMedium),
              Flexible(
                child: Text(
                  value == null || value.isEmpty ? '—' : value,
                  style: text.bodyMedium,
                  textAlign: TextAlign.end,
                ),
              ),
            ],
          ),
        );

    return Scaffold(
      appBar: AppBar(title: Text(t('common.doctor.settings.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t('common.doctor.settings.subtitle'), style: text.bodySmall),
          const SizedBox(height: 16),
          section(t('common.doctor.settings.accountInfo'), [
            row(t('common.doctor.settings.name'), user?.name),
            row(t('common.doctor.settings.email'), user?.email),
            row(t('common.doctor.settings.role'), user?.role),
            row(t('common.doctor.settings.department'), user?.department),
            row(t('common.doctor.settings.phone'), user?.phone),
          ]),
          section(t('common.doctor.settings.appearance'), [
            Text(t('common.doctor.settings.themeHint'), style: text.bodySmall),
            const SizedBox(height: 8),
            SegmentedButton<ThemeMode>(
              segments: [
                ButtonSegment(
                  value: ThemeMode.system,
                  label: Text(t('common.doctor.settings.themeMode')),
                ),
                ButtonSegment(
                  value: ThemeMode.light,
                  label: Text(t('common.doctor.settings.themeLight')),
                ),
                ButtonSegment(
                  value: ThemeMode.dark,
                  label: Text(t('common.doctor.settings.themeDark')),
                ),
              ],
              selected: {settings.themeMode},
              onSelectionChanged: (v) => notifier.setThemeMode(v.first),
            ),
            const SizedBox(height: 16),
            Text(t('common.doctor.settings.languageLabel'), style: text.bodyMedium),
            Text(t('common.doctor.settings.languageHint'), style: text.bodySmall),
            const SizedBox(height: 8),
            // Same authority as everywhere else: switching navigates to the URL under the
            // new lng. Doctors previously only had zh/en chips on the patient page.
            const LanguageBar(),
          ]),
          section(t('common.doctor.settings.notifications'), [
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(t('common.doctor.settings.soundAlerts')),
              subtitle: Text(t('common.doctor.settings.soundHint')),
              value: settings.soundAlerts,
              onChanged: (_) => notifier.toggleSoundAlerts(),
            ),
          ]),
          section(t('common.doctor.settings.systemInfo'), [
            row(t('common.doctor.settings.apiEndpoint'), Env.apiBase),
          ]),
        ],
      ),
    );
  }
}
