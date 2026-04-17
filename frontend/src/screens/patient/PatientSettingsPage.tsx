import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../stores/authStore';
import { User, Bell, Shield, KeyRound, Globe, ChevronRight } from 'lucide-react';
import { useSettingsStore } from '../../stores/settingsStore';

export default function PatientSettingsPage() {
  const { t } = useTranslation('common');
  const user = useAuthStore((s) => s.user);
  const updateProfile = useAuthStore((s) => s.updateProfile);
  const [activeTab, setActiveTab] = useState<'profile' | 'notifications' | 'security'>('profile');
  const {
    language,
    setLanguage,
    notificationsEnabled,
    setNotificationsEnabled,
    soundEnabled,
    setSoundEnabled,
  } = useSettingsStore();

  const [profile, setProfile] = useState({
    email: user?.email || '',
    phone: user?.phone || '',
  });
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState('');

  const handleSaveProfile = async () => {
    setIsSaving(true);
    setMessage('');
    await updateProfile({
      email: profile.email,
      phone: profile.phone,
    });
    setIsSaving(false);
    setMessage(t('patient.settings.savedMessage'));
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* 標題區塊 */}
      <div className="bg-white rounded-2xl shadow-sm border border-surface-200 p-6 md:p-8">
        <div className="flex items-center gap-4">
          <div className="h-16 w-16 bg-primary-100 rounded-full flex items-center justify-center flex-shrink-0">
            <span className="text-2xl font-bold text-primary-700">
              {user?.name?.[0] || 'U'}
            </span>
          </div>
          <div>
            <h1 className="text-2xl font-bold text-surface-900">{user?.name}</h1>
            <p className="text-surface-500">{user?.email}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* 側邊導航 */}
        <div className="md:col-span-1 space-y-2">
          <button
            onClick={() => setActiveTab('profile')}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'profile'
                ? 'bg-primary-50 text-primary-700'
                : 'text-surface-600 hover:bg-surface-50'
            }`}
          >
            <User className="h-5 w-5" />
            {t('patient.settings.tabProfile')}
          </button>
          <button
            onClick={() => setActiveTab('notifications')}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'notifications'
                ? 'bg-primary-50 text-primary-700'
                : 'text-surface-600 hover:bg-surface-50'
            }`}
          >
            <Bell className="h-5 w-5" />
            {t('patient.settings.tabNotifications')}
          </button>
          <button
            onClick={() => setActiveTab('security')}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'security'
                ? 'bg-primary-50 text-primary-700'
                : 'text-surface-600 hover:bg-surface-50'
            }`}
          >
            <Shield className="h-5 w-5" />
            {t('patient.settings.tabSecurity')}
          </button>
        </div>

        {/* 內容區塊 */}
        <div className="md:col-span-3">
          <div className="bg-white rounded-2xl shadow-sm border border-surface-200">

            {activeTab === 'profile' && (
              <div className="p-6 md:p-8 space-y-6">
                <div>
                  <h2 className="text-lg font-bold text-surface-900 mb-1">{t('patient.settings.profileTitle')}</h2>
                  <p className="text-sm text-surface-500 mb-6">{t('patient.settings.profileSubtitle')}</p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">{t('patient.settings.fullName')}</label>
                    <input type="text" className="w-full px-4 py-2 border border-surface-200 rounded-xl bg-surface-50" defaultValue={user?.name} disabled />
                    <p className="text-xs text-surface-500 mt-1">{t('patient.settings.fullNameHint')}</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">{t('patient.settings.emailLabel')}</label>
                    <input type="email" className="w-full px-4 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500" value={profile.email} onChange={(e) => setProfile((prev) => ({ ...prev, email: e.target.value }))} />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">{t('patient.settings.phoneLabel')}</label>
                    <input type="tel" className="w-full px-4 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500" placeholder={t('patient.settings.phonePlaceholder')} value={profile.phone} onChange={(e) => setProfile((prev) => ({ ...prev, phone: e.target.value }))} />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">{t('patient.settings.preferredLanguage')}</label>
                    <div className="relative">
                      <select
                        className="w-full px-4 py-2 border border-surface-200 rounded-xl appearance-none bg-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                        value={language}
                        onChange={(e) => setLanguage(e.target.value as 'zh-TW' | 'en-US')}
                      >
                        <option value="zh-TW">{t('language.names.zh-TW')}</option>
                        <option value="en-US">{t('language.names.en-US')}</option>
                      </select>
                      <Globe className="absolute right-3 top-2.5 h-5 w-5 text-surface-400 pointer-events-none" />
                    </div>
                  </div>
                </div>

                <div className="pt-4 flex justify-end">
                  <button className="px-6 py-2 bg-primary-600 text-white rounded-xl font-medium hover:bg-primary-700 transition-colors disabled:opacity-50" onClick={handleSaveProfile} disabled={isSaving}>
                    {isSaving ? t('saving') : t('patient.settings.saveChanges')}
                  </button>
                </div>
                {message ? <p className="text-sm text-green-600">{message}</p> : null}
              </div>
            )}

            {activeTab === 'notifications' && (
              <div className="p-6 md:p-8 space-y-6">
                <div>
                  <h2 className="text-lg font-bold text-surface-900 mb-1">{t('patient.settings.notificationsTitle')}</h2>
                  <p className="text-sm text-surface-500 mb-6">{t('patient.settings.notificationsSubtitle')}</p>
                </div>

                <div className="space-y-4">
                  <label className="flex items-center justify-between p-4 border border-surface-200 rounded-xl hover:bg-surface-50 cursor-pointer transition-colors">
                    <div>
                      <p className="font-medium text-surface-900">{t('patient.settings.emailNotifications')}</p>
                      <p className="text-sm text-surface-500">{t('patient.settings.emailNotificationsHint')}</p>
                    </div>
                    <div className="relative inline-block w-12 h-6 rounded-full bg-surface-200">
                      <input type="checkbox" className="sr-only peer" checked={notificationsEnabled} onChange={(e) => setNotificationsEnabled(e.target.checked)} />
                      <span className="w-12 h-6 bg-surface-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-surface-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-500 cursor-pointer"></span>
                    </div>
                  </label>

                  <label className="flex items-center justify-between p-4 border border-surface-200 rounded-xl hover:bg-surface-50 cursor-pointer transition-colors">
                    <div>
                      <p className="font-medium text-surface-900">{t('patient.settings.pushNotifications')}</p>
                      <p className="text-sm text-surface-500">{t('patient.settings.pushNotificationsHint')}</p>
                    </div>
                    <div className="relative inline-block w-12 h-6 rounded-full bg-surface-200">
                      <input type="checkbox" className="sr-only peer" checked={soundEnabled} onChange={(e) => setSoundEnabled(e.target.checked)} />
                      <span className="w-12 h-6 bg-surface-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-surface-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-500 cursor-pointer"></span>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {activeTab === 'security' && (
              <div className="p-6 md:p-8 space-y-6">
                <div>
                  <h2 className="text-lg font-bold text-surface-900 mb-1">{t('patient.settings.securityTitle')}</h2>
                  <p className="text-sm text-surface-500 mb-6">{t('patient.settings.securitySubtitle')}</p>
                </div>

                <button className="w-full flex items-center justify-between p-4 border border-surface-200 rounded-xl hover:bg-surface-50 transition-colors text-left">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 bg-surface-100 rounded-full flex items-center justify-center">
                      <KeyRound className="h-5 w-5 text-surface-600" />
                    </div>
                    <div>
                      <p className="font-medium text-surface-900">{t('patient.settings.changePassword')}</p>
                      <p className="text-sm text-surface-500">{t('patient.settings.changePasswordHint')}</p>
                    </div>
                  </div>
                  <ChevronRight className="h-5 w-5 text-surface-400" />
                </button>
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
}
