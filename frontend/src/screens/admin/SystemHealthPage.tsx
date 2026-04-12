import { Activity, Server, Database, Globe, Clock, RefreshCw } from 'lucide-react';

export default function SystemHealthPage() {
  // Mock Data
  const metrics = [
    { label: 'API 伺服器狀態', value: '正常', color: 'text-green-600', icon: Server },
    { label: 'Supabase 資料庫', value: '連線中', color: 'text-green-600', icon: Database },
    { label: 'Redis 訊息佇列', value: '延遲 12ms', color: 'text-primary-600', icon: Activity },
    { label: '活躍 WebSocket 連線', value: '24', color: 'text-surface-900', icon: Globe },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">系統健康監控</h1>
          <p className="text-surface-500 text-sm mt-1">監控後端核心服務與基礎設施狀態。</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-white border border-surface-200 text-surface-700 rounded-xl hover:bg-surface-50 transition-colors shadow-sm font-medium">
          <RefreshCw className="h-4 w-4" />
          重新整理
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((m, idx) => {
          const Icon = m.icon;
          return (
            <div key={idx} className="bg-white p-6 rounded-2xl shadow-sm border border-surface-200">
              <div className="flex items-center gap-3 mb-3">
                <div className="p-2 bg-surface-100 rounded-lg text-surface-600">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="text-sm font-medium text-surface-500">{m.label}</h3>
              </div>
              <p className={`text-2xl font-bold ${m.color}`}>{m.value}</p>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-4">
        <div className="bg-white rounded-2xl shadow-sm border border-surface-200 p-6">
           <h3 className="text-lg font-bold text-surface-900 mb-4">最近系統事件</h3>
           <div className="space-y-4">
             <div className="flex gap-3">
                <Clock className="h-5 w-5 text-surface-400 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-surface-900">Redis Cache 清理完成</p>
                  <p className="text-xs text-surface-500">2026-04-12 10:00:00</p>
                </div>
             </div>
             <div className="flex gap-3">
                <Clock className="h-5 w-5 text-primary-500 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-primary-900">Supabase Schema 遷移完成 (c98fa7840c8c)</p>
                  <p className="text-xs text-primary-600">2026-04-12 03:10:38</p>
                </div>
             </div>
           </div>
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-surface-200 p-6">
           <h3 className="text-lg font-bold text-surface-900 mb-4">AI 服務配額狀態</h3>
           <div className="space-y-4">
             <div>
               <div className="flex justify-between text-sm mb-1">
                 <span className="font-medium text-surface-700">OpenAI API (Whisper)</span>
                 <span className="text-surface-500">正常 (無耗盡風險)</span>
               </div>
               <div className="w-full bg-surface-100 rounded-full h-2">
                 <div className="bg-green-500 h-2 rounded-full" style={{ width: '15%' }}></div>
               </div>
             </div>
             <div>
               <div className="flex justify-between text-sm mb-1">
                 <span className="font-medium text-surface-700">Gemini LLM (SOAP 生成)</span>
                 <span className="text-surface-500">高負載 (250/300 RPM)</span>
               </div>
               <div className="w-full bg-surface-100 rounded-full h-2">
                 <div className="bg-amber-500 h-2 rounded-full" style={{ width: '83%' }}></div>
               </div>
             </div>
           </div>
        </div>
      </div>
    </div>
  );
}
