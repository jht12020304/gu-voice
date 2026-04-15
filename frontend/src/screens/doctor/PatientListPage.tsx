// =============================================================================
// 病患列表頁（月整理 + 日期分組）
// =============================================================================

import { addMonths, endOfMonth, format, startOfMonth } from 'date-fns';
import { useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import SearchBar from '../../components/form/SearchBar';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import { usePatientListStore } from '../../stores/patientListStore';
import type { Patient } from '../../types';
import { formatDate, formatMRN } from '../../utils/format';

function formatMonthRange(monthDate: Date): string {
  return `${format(startOfMonth(monthDate), 'yyyy/MM/dd')} - ${format(endOfMonth(monthDate), 'yyyy/MM/dd')}`;
}

function formatGroupHeading(dateKey: string): string {
  return new Intl.DateTimeFormat('zh-TW', {
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  }).format(new Date(`${dateKey}T00:00:00`));
}

function getGenderLabel(gender: Patient['gender']): string {
  if (gender === 'male') return '男';
  if (gender === 'female') return '女';
  return '其他';
}

function groupPatientsByCreatedDate(patients: Patient[]) {
  const groups = patients.reduce<Record<string, Patient[]>>((acc, patient) => {
    const dateKey = format(new Date(patient.createdAt), 'yyyy-MM-dd');
    if (!acc[dateKey]) {
      acc[dateKey] = [];
    }
    acc[dateKey].push(patient);
    return acc;
  }, {});

  return Object.entries(groups)
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([dateKey, items]) => ({
      dateKey,
      label: formatGroupHeading(dateKey),
      items,
    }));
}

function PatientMetricCard({
  title,
  value,
  helper,
  accentClass,
}: {
  title: string;
  value: number;
  helper: string;
  accentClass: string;
}) {
  return (
    <div className={`rounded-panel border border-edge bg-white p-5 shadow-card dark:border-dark-border dark:bg-dark-card ${accentClass}`}>
      <p className="text-small font-semibold text-ink-secondary">{title}</p>
      <p className="mt-4 text-display font-bold text-ink-heading dark:text-white font-tnum">
        {value.toLocaleString('zh-TW')}
      </p>
      <p className="mt-2 text-caption text-ink-muted">{helper}</p>
    </div>
  );
}

export default function PatientListPage() {
  const navigate = useNavigate();
  const {
    patients,
    isLoading,
    hasMore,
    totalCount,
    selectedMonth,
    searchQuery,
    error,
    fetchPatients,
    fetchMore,
    setSearch,
    setSelectedMonth,
  } = usePatientListStore();

  const observerRef = useRef<IntersectionObserver>();
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchPatients(true);
  }, [fetchPatients, selectedMonth]);

  const handleSearch = useCallback(
    (query: string) => {
      setSearch(query);
      fetchPatients(true);
    },
    [setSearch, fetchPatients],
  );

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

  const selectedMonthDate = new Date(`${selectedMonth}-01T00:00:00`);
  const selectedMonthLabel = format(selectedMonthDate, 'yyyy 年 M 月');
  const monthRangeLabel = formatMonthRange(selectedMonthDate);
  const groupedPatients = groupPatientsByCreatedDate(patients);

  const loadedCountHelper = hasMore
    ? `已載入 ${patients.length} / ${totalCount} 位病患`
    : `目前共 ${totalCount} 位病患`;

  return (
    <div className="space-y-6 animate-fade-in">
      <section className="card">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">Patients</p>
            <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">病患列表</h1>
            <p className="mt-2 text-body text-ink-secondary">
              以月份切換檢視病患資料，並依建檔日期整理每日新增病患。
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="rounded-pill bg-surface-tertiary px-3 py-1.5 text-tiny font-semibold text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">
                資料區間 {monthRangeLabel}
              </span>
              {searchQuery ? (
                <span className="rounded-pill bg-primary-50 px-3 py-1.5 text-tiny font-semibold text-primary-700 dark:bg-primary-950/40 dark:text-primary-300">
                  搜尋中：{searchQuery}
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-panel border border-edge bg-white p-1.5 shadow-card dark:border-dark-border dark:bg-dark-card">
            <button
              type="button"
              className="rounded-card p-2 text-ink-secondary transition-colors hover:bg-surface-tertiary hover:text-ink-heading dark:hover:bg-dark-surface dark:hover:text-white"
              onClick={() => setSelectedMonth(format(addMonths(selectedMonthDate, -1), 'yyyy-MM'))}
              aria-label="上一個月"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
            <div className="min-w-[148px] px-3 text-center text-body font-semibold text-ink-heading dark:text-white">
              {selectedMonthLabel}
            </div>
            <button
              type="button"
              className="rounded-card p-2 text-ink-secondary transition-colors hover:bg-surface-tertiary hover:text-ink-heading dark:hover:bg-dark-surface dark:hover:text-white"
              onClick={() => setSelectedMonth(format(addMonths(selectedMonthDate, 1), 'yyyy-MM'))}
              aria-label="下一個月"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5L15.75 12l-7.5 7.5" />
              </svg>
            </button>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-2">
          <PatientMetricCard
            title={`${selectedMonthLabel} 新增病患`}
            value={totalCount}
            helper={searchQuery ? '符合搜尋條件的病患數' : '本月建立的病患總數'}
            accentClass="border-t-4 border-t-[#8F3A6F]"
          />
          <PatientMetricCard
            title="日期分組"
            value={groupedPatients.length}
            helper={loadedCountHelper}
            accentClass="border-t-4 border-t-[#4A7AF7]"
          />
        </div>

        <div className="mt-6 max-w-md">
          <SearchBar
            value={searchQuery}
            onChange={handleSearch}
            placeholder="搜尋病患姓名、病歷號..."
          />
        </div>
      </section>

      {error ? <ErrorState message={error} onRetry={() => fetchPatients(true)} /> : null}

      {!error && patients.length === 0 && !isLoading ? (
        <EmptyState
          title={`${selectedMonthLabel} 無病患資料`}
          message={searchQuery ? '目前沒有符合搜尋條件的病患' : '目前這個月份尚無建立病患資料'}
        />
      ) : null}

      {!error && groupedPatients.length > 0 ? (
        <div className="space-y-5">
          {groupedPatients.map((group) => (
            <section key={group.dateKey} className="card overflow-hidden p-0">
              <div className="flex flex-col gap-2 border-b border-edge bg-surface-tertiary px-6 py-4 dark:border-dark-border dark:bg-dark-surface lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h2 className="text-h3 text-ink-heading dark:text-white">{group.label}</h2>
                  <p className="mt-1 text-small text-ink-muted font-tnum">{group.dateKey}</p>
                </div>
                <span className="rounded-pill bg-white px-3 py-1 text-tiny font-semibold text-ink-secondary shadow-sm dark:bg-dark-card dark:text-dark-text-muted">
                  {group.items.length} 位病患
                </span>
              </div>

              <div className="hidden border-b border-edge px-6 py-3 text-tiny font-semibold uppercase tracking-[0.16em] text-ink-muted dark:border-dark-border md:grid md:grid-cols-[minmax(0,2fr)_1.2fr_0.8fr_1fr_0.8fr_auto] md:gap-4">
                <span>病患</span>
                <span>病歷號</span>
                <span>性別</span>
                <span>出生日期</span>
                <span>建檔時間</span>
                <span />
              </div>

              <div className="divide-y divide-edge dark:divide-dark-border">
                {group.items.map((patient) => (
                  <button
                    key={patient.id}
                    type="button"
                    className="grid w-full grid-cols-1 gap-3 px-6 py-4 text-left transition-colors hover:bg-surface-tertiary/60 dark:hover:bg-dark-surface md:grid-cols-[minmax(0,2fr)_1.2fr_0.8fr_1fr_0.8fr_auto] md:items-center md:gap-4"
                    onClick={() => navigate(`/patients/${patient.id}`)}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-primary-50 text-caption font-semibold text-primary-700 dark:bg-primary-950 dark:text-primary-300">
                        {patient.name.charAt(0)}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-body font-medium text-ink-heading dark:text-white">{patient.name}</p>
                        <p className="truncate text-small text-ink-muted">{patient.phone || '未提供電話'}</p>
                      </div>
                    </div>
                    <div className="text-body font-data text-ink-body">{formatMRN(patient.medicalRecordNumber)}</div>
                    <div className="text-body text-ink-body">{getGenderLabel(patient.gender)}</div>
                    <div className="text-body font-tnum text-ink-body">
                      {formatDate(patient.dateOfBirth, { year: 'numeric', month: '2-digit', day: '2-digit' })}
                    </div>
                    <div className="text-body font-tnum text-ink-body">
                      {formatDate(patient.createdAt, { hour: '2-digit', minute: '2-digit' })}
                    </div>
                    <div className="flex justify-end">
                      <svg
                        className="h-4 w-4 text-ink-placeholder"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                  </button>
                ))}
              </div>
            </section>
          ))}

          <div ref={sentinelRef} className="h-4" />

          {isLoading ? (
            <div className="flex justify-center py-2">
              <LoadingSpinner size="sm" />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
