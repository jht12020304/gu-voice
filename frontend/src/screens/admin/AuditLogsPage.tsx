import { useState } from 'react';
import { Search, Filter, Download } from 'lucide-react';

export default function AuditLogsPage() {
  const [searchTerm, setSearchTerm] = useState('');

  // Mock data
  const logs = [
    { id: 101, action: 'SESSION_START', user: '王小明 (病患)', resource: 'Session', resourceId: 'sess-1234', ip: '192.168.1.10', time: '2026-04-12 14:30:12' },
    { id: 102, action: 'SESSION_END', user: '王小明 (病患)', resource: 'Session', resourceId: 'sess-1234', ip: '192.168.1.10', time: '2026-04-12 14:38:45' },
    { id: 103, action: 'CREATE', user: 'System Worker', resource: 'SOAPReport', resourceId: 'rep-5566', ip: 'internal', time: '2026-04-12 14:39:02' },
    { id: 104, action: 'REVIEW', user: '陳醫師 (醫師)', resource: 'SOAPReport', resourceId: 'rep-5566', ip: '10.0.0.5', time: '2026-04-12 15:10:20' },
    { id: 105, action: 'LOGIN', user: 'Admin (系統管理員)', resource: 'Auth', resourceId: '-', ip: '10.0.0.1', time: '2026-04-12 15:55:00' },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">稽核日誌 (Audit Logs)</h1>
          <p className="text-surface-500 text-sm mt-1">檢視系統操作紀錄，符合醫療資訊規範。</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-white border border-surface-200 text-surface-700 rounded-xl hover:bg-surface-50 transition-colors shadow-sm font-medium">
          <Download className="h-4 w-4" />
          匯出 CSV
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
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-surface-200 text-surface-700 rounded-xl hover:bg-surface-50 transition-colors">
            <Filter className="h-4 w-4" />
            過濾條件
          </button>
        </div>

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
              {logs.map((log) => (
                <tr key={log.id} className="hover:bg-surface-50 transition-colors text-sm">
                  <td className="py-4 px-6 text-surface-500 font-mono text-xs">{log.time}</td>
                  <td className="py-4 px-6">
                    <span className="font-semibold text-primary-700">{log.action}</span>
                  </td>
                  <td className="py-4 px-6 font-medium text-surface-900">{log.user}</td>
                  <td className="py-4 px-6 text-surface-600">{log.resource}</td>
                  <td className="py-4 px-6 text-surface-500 font-mono text-xs">{log.resourceId}</td>
                  <td className="py-4 px-6 text-surface-400 font-mono text-xs">{log.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
