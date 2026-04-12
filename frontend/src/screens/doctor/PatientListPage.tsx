// =============================================================================
// 病患列表頁（含搜尋、無限捲動）
// =============================================================================

import { useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePatientListStore } from '../../stores/patientListStore';
import SearchBar from '../../components/form/SearchBar';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import { formatDate } from '../../utils/format';

export default function PatientListPage() {
  const navigate = useNavigate();
  const {
    patients,
    isLoading,
    hasMore,
    searchQuery,
    error,
    fetchPatients,
    fetchMore,
    setSearch,
  } = usePatientListStore();

  const observerRef = useRef<IntersectionObserver>();
  const sentinelRef = useRef<HTMLDivElement>(null);

  // 初始載入
  useEffect(() => {
    fetchPatients(true);
  }, [fetchPatients]);

  // 搜尋變更
  const handleSearch = useCallback(
    (query: string) => {
      setSearch(query);
      fetchPatients(true);
    },
    [setSearch, fetchPatients],
  );

  // 無限捲動
  useEffect(() => {
    if (observerRef.current) observerRef.current.disconnect();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !isLoading) {
          fetchMore();
        }
      },
      { threshold: 0.1 },
    );

    if (sentinelRef.current) {
      observerRef.current.observe(sentinelRef.current);
    }

    return () => observerRef.current?.disconnect();
  }, [hasMore, isLoading, fetchMore]);

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-h1 text-ink-heading dark:text-white">病患列表</h1>
      </div>

      {/* 搜尋列 */}
      <div className="max-w-md">
        <SearchBar
          value={searchQuery}
          onChange={handleSearch}
          placeholder="搜尋病患姓名、病歷號..."
        />
      </div>

      {/* 錯誤狀態 */}
      {error && <ErrorState message={error} onRetry={() => fetchPatients(true)} />}

      {/* 病患列表 */}
      {!error && patients.length === 0 && !isLoading ? (
        <EmptyState title="無病患資料" message="目前尚無符合條件的病患" />
      ) : (
        <div className="card overflow-hidden p-0">
          <table className="w-full">
            <thead>
              <tr className="table-header">
                <th className="px-6 py-3 text-left">病患</th>
                <th className="px-6 py-3 text-left">病歷號</th>
                <th className="px-6 py-3 text-left">性別</th>
                <th className="px-6 py-3 text-left">出生日期</th>
                <th className="px-6 py-3 text-left">建立日期</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody>
              {patients.map((patient) => (
                <tr
                  key={patient.id}
                  className="table-row cursor-pointer"
                  onClick={() => navigate(`/patients/${patient.id}`)}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-primary-50 text-caption font-semibold text-primary-700 dark:bg-primary-950 dark:text-primary-300">
                        {patient.name.charAt(0)}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-body font-medium text-ink-heading dark:text-white">{patient.name}</p>
                        <p className="truncate text-small text-ink-muted">{patient.phone || '-'}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-body font-data text-ink-body">{patient.medicalRecordNumber}</td>
                  <td className="px-6 py-4 text-body text-ink-body">
                    {patient.gender === 'male' ? '男' : patient.gender === 'female' ? '女' : '其他'}
                  </td>
                  <td className="px-6 py-4 text-body text-ink-body font-tnum">
                    {formatDate(patient.dateOfBirth, { year: 'numeric', month: '2-digit', day: '2-digit' })}
                  </td>
                  <td className="px-6 py-4 text-body text-ink-body font-tnum">
                    {formatDate(patient.createdAt, { year: 'numeric', month: '2-digit', day: '2-digit' })}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <svg
                      className="h-4 w-4 text-ink-placeholder"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* 無限捲動哨兵 */}
          <div ref={sentinelRef} className="h-4" />

          {/* 載入中 */}
          {isLoading && (
            <div className="flex justify-center py-4">
              <LoadingSpinner size="sm" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
