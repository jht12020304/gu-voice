import { useEffect, useMemo, useState } from 'react';
import { Search, Filter, Download } from 'lucide-react';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import * as adminApi from '../../services/api/admin';
import type { AuditLog } from '../../types';

export default function AuditLogsPage() {
  const [searchTerm, setSearchTerm] = useState('');
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  const loadLogs = async () => {
    setIsLoading(true);
    setError('');
    try {
      const response = await adminApi.getAuditLogs({ limit: 100 });
      setLogs(response.data);
    } catch {
      setError('無法載入稽核日誌');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, []);

  const filteredLogs = useMemo(() => {
    if (!searchTerm.trim()) return logs;
    const keyword = searchTerm.trim().toLowerCase();
    return logs.filter((log) =>
      [
        String(log.id),
        log.action,
        log.resourceType,
        log.resourceId,
        log.ipAddress,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword)),
    );
  }, [logs, searchTerm]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">稽核日誌 (Audit Logs)</h1>
          <p className="text-surface-500 text-sm mt-1">檢視系統操作紀錄，符合醫療資訊規範。</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-white border border-surface-200 text-surface-700 rounded-xl hover:bg-surface-50 transition-colors shadow-sm font-medium" onClick={loadLogs}>
          <Download className="h-4 w-4" />
          重新整理
        </button>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-surface-200 overflow-hidden">
        <div className="p-4 border-b border-surface-200 bg-surface-50 flex gap-4">
          <div className="relative max-w-md flex-1">
            <Search className="absolute left-3 top-2.5 h-5 w-5 text-surface-400" />
            <input
              type="text"
              placeholder="搜尋使用者、資源 ID..."
              className="w-full pl-10 pr-4 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-surface-200 text-surface-700 rounded-xl hover:bg-surface-50 transition-colors" disabled>
            <Filter className="h-4 w-4" />
            關鍵字篩選
          </button>
        </div>

        {error ? <ErrorState message={error} onRetry={loadLogs} /> : null}

        {isLoading ? (
          <LoadingSpinner fullPage />
        ) : filteredLogs.length === 0 ? (
          <EmptyState title="無稽核日誌" message="目前沒有符合條件的操作紀錄" />
        ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-50 text-surface-500 text-sm border-b border-surface-200">
                <th className="py-3 px-6 font-medium">時間</th>
                <th className="py-3 px-6 font-medium">動作</th>
                <th className="py-3 px-6 font-medium">使用者</th>
                <th className="py-3 px-6 font-medium">資源類型</th>
                <th className="py-3 px-6 font-medium">資源 ID</th>
                <th className="py-3 px-6 font-medium">IP Address</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-100">
              {filteredLogs.map((log) => (
                <tr key={log.id} className="hover:bg-surface-50 transition-colors text-sm">
                  <td className="py-4 px-6 text-surface-500 font-mono text-xs">{log.createdAt}</td>
                  <td className="py-4 px-6">
                    <span className="font-semibold text-primary-700">{log.action}</span>
                  </td>
                  <td className="py-4 px-6 font-medium text-surface-900">{log.userId || '-'}</td>
                  <td className="py-4 px-6 text-surface-600">{log.resourceType}</td>
                  <td className="py-4 px-6 text-surface-500 font-mono text-xs">{log.resourceId || '-'}</td>
                  <td className="py-4 px-6 text-surface-400 font-mono text-xs">{log.ipAddress || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
      </div>
    </div>
  );
}
