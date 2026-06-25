import { useEffect, useMemo, useState } from 'react';
import { Search, Filter, Download, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import * as adminApi from '../../services/api/admin';
import type { AuditLog } from '../../types';
import type { AuditLogListParams } from '../../types/api';

interface FilterState {
  action: string;
  userId: string;
  startDate: string;
  endDate: string;
}

const EMPTY_FILTERS: FilterState = { action: '', userId: '', startDate: '', endDate: '' };

export default function AuditLogsPage() {
  const { t } = useTranslation();
  const [searchTerm, setSearchTerm] = useState('');
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  // 已套用至 API 的篩選條件
  const [appliedFilters, setAppliedFilters] = useState<FilterState>(EMPTY_FILTERS);
  // 表單暫存的篩選條件（按下「套用」後才生效）
  const [draftFilters, setDraftFilters] = useState<FilterState>(EMPTY_FILTERS);

  const loadLogs = async (filters: FilterState = appliedFilters) => {
    setIsLoading(true);
    setError('');
    try {
      const params: AuditLogListParams = { limit: 100 };
      if (filters.action.trim()) params.action = filters.action.trim();
      if (filters.userId.trim()) params.userId = filters.userId.trim();
      if (filters.startDate) params.startDate = filters.startDate;
      if (filters.endDate) params.endDate = filters.endDate;
      const response = await adminApi.getAuditLogs(params);
      setLogs(response.data);
    } catch {
      setError(t('admin:audit.loadFailed', '無法載入稽核日誌'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadLogs(EMPTY_FILTERS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasActiveFilters = useMemo(
    () => Boolean(appliedFilters.action || appliedFilters.userId || appliedFilters.startDate || appliedFilters.endDate),
    [appliedFilters],
  );

  const openFilters = () => {
    setDraftFilters(appliedFilters);
    setShowFilters((prev) => !prev);
  };

  const applyFilters = () => {
    setAppliedFilters(draftFilters);
    setShowFilters(false);
    loadLogs(draftFilters);
  };

  const clearFilters = () => {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setShowFilters(false);
    loadLogs(EMPTY_FILTERS);
  };

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
        log.userId,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword)),
    );
  }, [logs, searchTerm]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">{t('admin:audit.title', '稽核日誌 (Audit Logs)')}</h1>
          <p className="text-surface-500 text-sm mt-1">{t('admin:audit.subtitle', '檢視系統操作紀錄，符合醫療資訊規範。')}</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-white border border-surface-200 text-surface-700 rounded-xl hover:bg-surface-50 transition-colors shadow-sm font-medium" onClick={() => loadLogs()}>
          <Download className="h-4 w-4" />
          {t('admin:audit.refresh', '重新整理')}
        </button>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-surface-200 overflow-hidden">
        <div className="p-4 border-b border-surface-200 bg-surface-50 flex gap-4">
          <div className="relative max-w-md flex-1">
            <Search className="absolute left-3 top-2.5 h-5 w-5 text-surface-400" />
            <input
              type="text"
              placeholder={t('admin:audit.searchPlaceholder', '搜尋使用者、資源 ID...')}
              className="w-full pl-10 pr-4 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <button
            className={`flex items-center gap-2 px-4 py-2 rounded-xl border transition-colors ${
              hasActiveFilters
                ? 'bg-primary-50 border-primary-200 text-primary-700'
                : 'bg-white border-surface-200 text-surface-700 hover:bg-surface-50'
            }`}
            onClick={openFilters}
          >
            <Filter className="h-4 w-4" />
            {t('admin:audit.filter', '篩選')}
            {hasActiveFilters && (
              <span className="ml-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-primary-600 px-1.5 text-xs font-semibold text-white">
                {[appliedFilters.action, appliedFilters.userId, appliedFilters.startDate, appliedFilters.endDate].filter(Boolean).length}
              </span>
            )}
          </button>
        </div>

        {showFilters && (
          <div className="p-4 border-b border-surface-200 bg-white">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-surface-700">{t('admin:audit.filterAction', '動作')}</label>
                <input
                  type="text"
                  placeholder={t('admin:audit.filterActionPlaceholder', '例如：login、update')}
                  className="w-full px-3 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
                  value={draftFilters.action}
                  onChange={(e) => setDraftFilters((prev) => ({ ...prev, action: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-surface-700">{t('admin:audit.filterUser', '使用者 ID')}</label>
                <input
                  type="text"
                  placeholder={t('admin:audit.filterUserPlaceholder', '使用者 ID')}
                  className="w-full px-3 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
                  value={draftFilters.userId}
                  onChange={(e) => setDraftFilters((prev) => ({ ...prev, userId: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-surface-700">{t('admin:audit.filterStartDate', '起始日期')}</label>
                <input
                  type="date"
                  className="w-full px-3 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
                  value={draftFilters.startDate}
                  onChange={(e) => setDraftFilters((prev) => ({ ...prev, startDate: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-surface-700">{t('admin:audit.filterEndDate', '結束日期')}</label>
                <input
                  type="date"
                  className="w-full px-3 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
                  value={draftFilters.endDate}
                  onChange={(e) => setDraftFilters((prev) => ({ ...prev, endDate: e.target.value }))}
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                className="flex items-center gap-1.5 px-4 py-2 text-surface-600 hover:text-surface-900 rounded-xl hover:bg-surface-50 transition-colors text-sm font-medium"
                onClick={clearFilters}
              >
                <X className="h-4 w-4" />
                {t('admin:audit.filterClear', '清除')}
              </button>
              <button
                className="px-4 py-2 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors text-sm font-medium"
                onClick={applyFilters}
              >
                {t('admin:audit.filterApply', '套用篩選')}
              </button>
            </div>
          </div>
        )}

        {error ? <ErrorState message={error} onRetry={() => loadLogs()} /> : null}

        {isLoading ? (
          <LoadingSpinner fullPage />
        ) : filteredLogs.length === 0 ? (
          <EmptyState title={t('admin:audit.emptyTitle', '無稽核日誌')} message={t('admin:audit.emptyMessage', '目前沒有符合條件的操作紀錄')} />
        ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-50 text-surface-500 text-sm border-b border-surface-200">
                <th className="py-3 px-6 font-medium">{t('admin:audit.colTime', '時間')}</th>
                <th className="py-3 px-6 font-medium">{t('admin:audit.colAction', '動作')}</th>
                <th className="py-3 px-6 font-medium">{t('admin:audit.colUser', '使用者')}</th>
                <th className="py-3 px-6 font-medium">{t('admin:audit.colResourceType', '資源類型')}</th>
                <th className="py-3 px-6 font-medium">{t('admin:audit.colResourceId', '資源 ID')}</th>
                <th className="py-3 px-6 font-medium">{t('admin:audit.colIp', 'IP Address')}</th>
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
