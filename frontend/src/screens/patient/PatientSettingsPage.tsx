import { useState } from 'react';
import { useAuthStore } from '../../stores/authStore';
import { User, Bell, Shield, KeyRound, Globe, ChevronRight } from 'lucide-react';

export default function PatientSettingsPage() {
  const user = useAuthStore((s) => s.user);
  const [activeTab, setActiveTab] = useState<'profile' | 'notifications' | 'security'>('profile');

  // Mock settings state
  const [settings, setSettings] = useState({
    notifications: {
      email: true,
      push: true,
      sms: false,
    },
    language: 'zh-TW',
  });

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
            個人資料
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
            通知設定
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
            帳號安全
          </button>
        </div>

        {/* 內容區塊 */}
        <div className="md:col-span-3">
          <div className="bg-white rounded-2xl shadow-sm border border-surface-200">
            
            {activeTab === 'profile' && (
              <div className="p-6 md:p-8 space-y-6">
                <div>
                  <h2 className="text-lg font-bold text-surface-900 mb-1">個人資料</h2>
                  <p className="text-sm text-surface-500 mb-6">更新您的基本個人資訊，這些資訊將作為問診參考。</p>
                </div>
                
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">真實姓名</label>
                    <input type="text" className="w-full px-4 py-2 border border-surface-200 rounded-xl bg-surface-50" defaultValue={user?.name} disabled />
                    <p className="text-xs text-surface-500 mt-1">如需更改姓名請聯絡櫃檯人員</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">電子信箱</label>
                    <input type="email" className="w-full px-4 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500" defaultValue={user?.email} />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">聯絡電話</label>
                    <input type="tel" className="w-full px-4 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500" placeholder="0912-345-678" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-surface-700 mb-2">慣用語系</label>
                    <div className="relative">
                      <select 
                        className="w-full px-4 py-2 border border-surface-200 rounded-xl appearance-none bg-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                        value={settings.language}
                        onChange={(e) => setSettings({...settings, language: e.target.value})}
                      >
                        <option value="zh-TW">繁體中文</option>
                        <option value="en-US">English</option>
                      </select>
                      <Globe className="absolute right-3 top-2.5 h-5 w-5 text-surface-400 pointer-events-none" />
                    </div>
                  </div>
                </div>

                <div className="pt-4 flex justify-end">
                  <button className="px-6 py-2 bg-primary-600 text-white rounded-xl font-medium hover:bg-primary-700 transition-colors">
                    儲存變更
                  </button>
                </div>
              </div>
            )}

            {activeTab === 'notifications' && (
              <div className="p-6 md:p-8 space-y-6">
                <div>
                  <h2 className="text-lg font-bold text-surface-900 mb-1">推播與通知</h2>
                  <p className="text-sm text-surface-500 mb-6">選擇您希望收到通知的方式與頻道。</p>
                </div>

                <div className="space-y-4">
                  <label className="flex items-center justify-between p-4 border border-surface-200 rounded-xl hover:bg-surface-50 cursor-pointer transition-colors">
                    <div>
                      <p className="font-medium text-surface-900">Email 通知</p>
                      <p className="text-sm text-surface-500">當有新的報告產出或預約提醒時發送 Email</p>
                    </div>
                    <div className="relative inline-block w-12 h-6 rounded-full bg-surface-200">
                      <input type="checkbox" className="sr-only peer" checked={settings.notifications.email} onChange={(e) => setSettings({...settings, notifications: {...settings.notifications, email: e.target.checked}})} />
                      <span className="w-12 h-6 bg-surface-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-surface-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-500 cursor-pointer"></span>
                    </div>
                  </label>

                  <label className="flex items-center justify-between p-4 border border-surface-200 rounded-xl hover:bg-surface-50 cursor-pointer transition-colors">
                    <div>
                      <p className="font-medium text-surface-900">推播通知 (Push Notifications)</p>
                      <p className="text-sm text-surface-500">透過瀏覽器或 App 推播即時通知</p>
                    </div>
                    <div className="relative inline-block w-12 h-6 rounded-full bg-surface-200">
                      <input type="checkbox" className="sr-only peer" checked={settings.notifications.push} onChange={(e) => setSettings({...settings, notifications: {...settings.notifications, push: e.target.checked}})} />
                      <span className="w-12 h-6 bg-surface-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-surface-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-500 cursor-pointer"></span>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {activeTab === 'security' && (
              <div className="p-6 md:p-8 space-y-6">
                <div>
                  <h2 className="text-lg font-bold text-surface-900 mb-1">帳號安全</h2>
                  <p className="text-sm text-surface-500 mb-6">管理您的密碼與登入安全性。</p>
                </div>

                <button className="w-full flex items-center justify-between p-4 border border-surface-200 rounded-xl hover:bg-surface-50 transition-colors text-left">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 bg-surface-100 rounded-full flex items-center justify-center">
                      <KeyRound className="h-5 w-5 text-surface-600" />
                    </div>
                    <div>
                      <p className="font-medium text-surface-900">更改密碼</p>
                      <p className="text-sm text-surface-500">定期更新密碼以保護帳戶安全</p>
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
