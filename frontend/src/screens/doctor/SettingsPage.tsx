// =============================================================================
// 設定頁面
// =============================================================================

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSettingsStore } from '../../stores/settingsStore';
import { useAuthStore } from '../../stores/authStore';

export default function SettingsPage() {
  const { t } = useTranslation('common');
  const { theme, setTheme, language, setLanguage, notificationsEnabled, setNotificationsEnabled, soundEnabled, setSoundEnabled } = useSettingsStore();
  const user = useAuthStore((s) => s.user);

  // 音訊裝置列表
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([]);
  const { audioInputDevice, setAudioDevice } = useSettingsStore();

  useEffect(() => {
    async function loadDevices() {
      try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        setAudioDevices(devices.filter((d) => d.kind === 'audioinput'));
      } catch {
        // 無麥克風權限
      }
    }
    loadDevices();
  }, []);

  const roleLabel =
    user?.role === 'doctor'
      ? t('roles.doctor')
      : user?.role === 'admin'
      ? t('roles.admin')
      : t('roles.patient');

  return (
    <div className="mx-auto max-w-2xl space-y-8 animate-fade-in">
      <div>
        <h1 className="text-h1 text-ink-heading dark:text-white">{t('doctor.settings.title')}</h1>
        <p className="mt-1 text-body text-ink-secondary">{t('doctor.settings.subtitle')}</p>
      </div>

      {/* 帳號資訊 */}
      <section className="card">
        <h2 className="text-h3 font-semibold text-ink-heading dark:text-white mb-4">{t('doctor.settings.accountInfo')}</h2>
        <div className="space-y-3">
          <div className="flex items-center justify-between py-2 border-b border-edge dark:border-dark-border">
            <span className="text-body text-ink-secondary">{t('doctor.settings.name')}</span>
            <span className="text-body font-medium text-ink-heading dark:text-white">{user?.name || t('common.dash')}</span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-edge dark:border-dark-border">
            <span className="text-body text-ink-secondary">{t('doctor.settings.email')}</span>
            <span className="text-body font-medium text-ink-heading dark:text-white">{user?.email || t('common.dash')}</span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-edge dark:border-dark-border">
            <span className="text-body text-ink-secondary">{t('doctor.settings.role')}</span>
            <span className="badge badge-waiting">
              {roleLabel}
            </span>
          </div>
          {user?.department && (
            <div className="flex items-center justify-between py-2 border-b border-edge dark:border-dark-border">
              <span className="text-body text-ink-secondary">{t('doctor.settings.department')}</span>
              <span className="text-body font-medium text-ink-heading dark:text-white">{user.department}</span>
            </div>
          )}
          <div className="flex items-center justify-between py-2">
            <span className="text-body text-ink-secondary">{t('doctor.settings.phone')}</span>
            <span className="text-body font-medium text-ink-heading dark:text-white">{user?.phone || t('common.notSet')}</span>
          </div>
        </div>
      </section>

      {/* 外觀設定 */}
      <section className="card">
        <h2 className="text-h3 font-semibold text-ink-heading dark:text-white mb-4">{t('doctor.settings.appearance')}</h2>
        <div className="space-y-4">
          {/* 主題 */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-body font-medium text-ink-heading dark:text-white">{t('doctor.settings.themeMode')}</p>
              <p className="text-small text-ink-muted">{t('doctor.settings.themeHint')}</p>
            </div>
            <div className="flex gap-2">
              <button
                className={`rounded-btn px-4 py-2 text-caption font-medium transition-colors ${
                  theme === 'light' ? 'bg-primary-600 text-white' : 'btn-secondary'
                }`}
                onClick={() => setTheme('light')}
              >
                <svg className="mr-1.5 inline h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
                </svg>
                {t('doctor.settings.themeLight')}
              </button>
              <button
                className={`rounded-btn px-4 py-2 text-caption font-medium transition-colors ${
                  theme === 'dark' ? 'bg-primary-600 text-white' : 'btn-secondary'
                }`}
                onClick={() => setTheme('dark')}
              >
                <svg className="mr-1.5 inline h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                </svg>
                {t('doctor.settings.themeDark')}
              </button>
            </div>
          </div>

          {/* 語言 */}
          <div className="flex items-center justify-between border-t border-edge pt-4 dark:border-dark-border">
            <div>
              <p className="text-body font-medium text-ink-heading dark:text-white">{t('doctor.settings.languageLabel')}</p>
              <p className="text-small text-ink-muted">{t('doctor.settings.languageHint')}</p>
            </div>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as 'zh-TW' | 'en-US')}
              className="input-base w-40"
            >
              <option value="zh-TW">{t('language.names.zh-TW')}</option>
              <option value="en-US">{t('language.names.en-US')}</option>
            </select>
          </div>
        </div>
      </section>

      {/* 通知設定 */}
      <section className="card">
        <h2 className="text-h3 font-semibold text-ink-heading dark:text-white mb-4">{t('doctor.settings.notifications')}</h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-body font-medium text-ink-heading dark:text-white">{t('doctor.settings.pushNotifications')}</p>
              <p className="text-small text-ink-muted">{t('doctor.settings.pushHint')}</p>
            </div>
            <ToggleSwitch checked={notificationsEnabled} onChange={setNotificationsEnabled} />
          </div>
          <div className="flex items-center justify-between border-t border-edge pt-4 dark:border-dark-border">
            <div>
              <p className="text-body font-medium text-ink-heading dark:text-white">{t('doctor.settings.soundAlerts')}</p>
              <p className="text-small text-ink-muted">{t('doctor.settings.soundHint')}</p>
            </div>
            <ToggleSwitch checked={soundEnabled} onChange={setSoundEnabled} />
          </div>
        </div>
      </section>

      {/* 音訊設定 */}
      <section className="card">
        <h2 className="text-h3 font-semibold text-ink-heading dark:text-white mb-4">{t('doctor.settings.audio')}</h2>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-body font-medium text-ink-heading dark:text-white">{t('doctor.settings.inputDevice')}</p>
            <p className="text-small text-ink-muted">{t('doctor.settings.inputDeviceHint')}</p>
          </div>
          <select
            value={audioInputDevice}
            onChange={(e) => setAudioDevice(e.target.value)}
            className="input-base w-56"
          >
            <option value="default">{t('common.defaultDevice')}</option>
            {audioDevices.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || t('common.microphoneLabel', { id: d.deviceId.slice(0, 8) })}
              </option>
            ))}
          </select>
        </div>
      </section>

      {/* 系統資訊 */}
      <section className="card">
        <h2 className="text-h3 font-semibold text-ink-heading dark:text-white mb-4">{t('doctor.settings.systemInfo')}</h2>
        <div className="space-y-2 text-body text-ink-muted">
          <div className="flex justify-between">
            <span>{t('doctor.settings.version')}</span>
            <span className="font-data text-ink-heading dark:text-white">0.1.0-alpha</span>
          </div>
          <div className="flex justify-between">
            <span>{t('doctor.settings.apiEndpoint')}</span>
            <span className="font-data text-ink-heading dark:text-white text-small">
              {import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'}
            </span>
          </div>
          <div className="flex justify-between">
            <span>{t('doctor.settings.mockMode')}</span>
            <span className={`font-data ${import.meta.env.VITE_ENABLE_MOCK === 'true' ? 'text-alert-high' : 'text-alert-success'}`}>
              {import.meta.env.VITE_ENABLE_MOCK === 'true' ? t('common.enabled') : t('common.disabled')}
            </span>
          </div>
        </div>
      </section>
    </div>
  );
}

/** Toggle Switch 元件 */
function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
        checked ? 'bg-primary-600' : 'bg-ink-placeholder'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 rounded-full bg-white transition-transform shadow-sm ${
          checked ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );
}
