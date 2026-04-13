import { useEffect, useState } from 'react';
import { Activity, Server, Database, Globe, Clock, RefreshCw } from 'lucide-react';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import * as adminApi from '../../services/api/admin';

export default function SystemHealthPage() {
  const [health, setHealth] = useState<adminApi.SystemHealthResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  const loadHealth = async () => {
    setIsLoading(true);
    setError('');
    try {
      const response = await adminApi.getSystemHealth();
      setHealth(response);
    } catch {
      setError('無法載入系統狀態');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadHealth();
  }, []);

  if (isLoading) return <LoadingSpinner fullPage message="載入系統健康狀態..." />;
  if (error || !health) return <ErrorState message={error || '無法取得系統健康狀態'} onRetry={loadHealth} />;

  const metrics = [
    { label: 'API 伺服器狀態', value: health.status, color: 'text-green-600', icon: Server },
    { label: '資料庫', value: health.database || 'unknown', color: 'text-green-600', icon: Database },
    { label: 'Redis', value: health.redis || 'unknown', color: 'text-primary-600', icon: Activity },
    { label: '版本', value: health.version || 'unknown', color: 'text-surface-900', icon: Globe },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">系統健康監控</h1>
          <p className="text-surface-500 text-sm mt-1">監控後端核心服務與基礎設施狀態。</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-white border border-surface-200 text-surface-700 rounded-xl hover:bg-surface-50 transition-colors shadow-sm font-medium" onClick={loadHealth}>
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
                  <p className="text-sm font-medium text-surface-900">後端狀態回報</p>
                  <p className="text-xs text-surface-500">{health.status}</p>
                </div>
             </div>
             <div className="flex gap-3">
                <Clock className="h-5 w-5 text-primary-500 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-primary-900">最後健康檢查時間</p>
                  <p className="text-xs text-primary-600">{health.timestamp || '未提供'}</p>
                </div>
             </div>
           </div>
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-surface-200 p-6">
           <h3 className="text-lg font-bold text-surface-900 mb-4">AI 服務配額狀態</h3>
           <div className="space-y-4">
             <div>
               <div className="flex justify-between text-sm mb-1">
                 <span className="font-medium text-surface-700">資料庫</span>
                 <span className="text-surface-500">{health.database || 'unknown'}</span>
               </div>
               <div className="w-full bg-surface-100 rounded-full h-2">
                 <div className="bg-green-500 h-2 rounded-full" style={{ width: health.database === 'ok' ? '100%' : '40%' }}></div>
               </div>
             </div>
             <div>
               <div className="flex justify-between text-sm mb-1">
                 <span className="font-medium text-surface-700">Redis</span>
                 <span className="text-surface-500">{health.redis || 'unknown'}</span>
               </div>
               <div className="w-full bg-surface-100 rounded-full h-2">
                 <div className="bg-amber-500 h-2 rounded-full" style={{ width: health.redis === 'ok' ? '100%' : '40%' }}></div>
               </div>
             </div>
           </div>
        </div>
      </div>
    </div>
  );
}
