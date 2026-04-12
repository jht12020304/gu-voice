// =============================================================================
// SOAP 報告列表頁
// =============================================================================

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import type { SOAPReport } from '../../types';
import { formatDate } from '../../utils/format';
import { useReportStore } from '../../stores/reportStore';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockReports: Array<SOAPReport & { patientName: string }> = [
  { id: 'rpt-001', sessionId: 's1', status: 'generated', reviewStatus: 'pending', summary: '45歲男性因肉眼血尿持續三天就診', aiConfidenceScore: 0.87, icd10Codes: ['R31.0', 'R30.0'], generatedAt: '2026-04-10T14:00:00Z', createdAt: '2026-04-10T14:00:00Z', updatedAt: '2026-04-10T14:00:00Z', patientName: '陳小明' },
  { id: 'rpt-002', sessionId: 'rs1', status: 'generated', reviewStatus: 'approved', summary: '60歲女性攝護腺症狀，PSA偏高需追蹤', aiConfidenceScore: 0.91, icd10Codes: ['R97.20'], reviewedBy: 'mock-doctor-001', reviewedAt: '2026-04-10T12:00:00Z', generatedAt: '2026-04-10T11:35:00Z', createdAt: '2026-04-10T11:35:00Z', updatedAt: '2026-04-10T12:00:00Z', patientName: '黃美芳' },
  { id: 'rpt-003', sessionId: 'rs2', status: 'generated', reviewStatus: 'approved', summary: '43歲男性反覆泌尿道感染，建議影像學檢查', aiConfidenceScore: 0.84, icd10Codes: ['N39.0'], reviewedBy: 'mock-doctor-001', reviewedAt: '2026-04-10T11:00:00Z', generatedAt: '2026-04-10T10:50:00Z', createdAt: '2026-04-10T10:50:00Z', updatedAt: '2026-04-10T11:00:00Z', patientName: '吳建宏' },
  { id: 'rpt-004', sessionId: 'rs4', status: 'generated', reviewStatus: 'revision_needed', summary: '50歲男性勃起功能障礙，發現潛在心血管風險', aiConfidenceScore: 0.78, icd10Codes: ['N52.9'], reviewNotes: '需補充心血管評估', generatedAt: '2026-04-10T09:20:00Z', createdAt: '2026-04-10T09:20:00Z', updatedAt: '2026-04-10T09:30:00Z', patientName: '周志豪' },
];

const REVIEW_TABS = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待審閱' },
  { key: 'approved', label: '已核准' },
  { key: 'revision_needed', label: '需修改' },
];

export default function ReportListPage() {
  const navigate = useNavigate();
  const { reports, isLoading: storeLoading, fetchReports } = useReportStore();
  const [reviewFilter, setReviewFilter] = useState('');
  const [mockFiltered, setMockFiltered] = useState(mockReports);
  const isLoading = IS_MOCK ? false : storeLoading;

  useEffect(() => {
    if (IS_MOCK) {
      const filtered = reviewFilter
        ? mockReports.filter((r) => r.reviewStatus === reviewFilter)
        : mockReports;
      setMockFiltered(filtered);
      return;
    }
    fetchReports({ reviewStatus: reviewFilter || undefined });
  }, [reviewFilter, fetchReports]);

  const displayReports = IS_MOCK ? mockFiltered : reports;

  const reviewStatusLabel = (status: string) => {
    switch (status) {
      case 'approved': return '已核准';
      case 'revision_needed': return '需修改';
      default: return '待審閱';
    }
  };

  const reviewStatusBadge = (status: string) => {
    switch (status) {
      case 'approved': return 'badge-completed';
      case 'revision_needed': return 'badge-red-flag';
      default: return 'badge-waiting';
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <h1 className="text-h1 text-ink-heading dark:text-white">SOAP 報告</h1>

      {/* 篩選 */}
      <div className="flex gap-2">
        {REVIEW_TABS.map((tab) => (
          <button
            key={tab.key}
            className={`rounded-btn px-4 py-2 text-body font-medium transition-colors ${
              reviewFilter === tab.key
                ? 'bg-primary-600 text-white'
                : 'btn-secondary'
            }`}
            onClick={() => setReviewFilter(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 列表 */}
      {isLoading ? (
        <LoadingSpinner fullPage />
      ) : displayReports.length === 0 ? (
        <EmptyState title="無報告" message="目前沒有符合條件的 SOAP 報告" />
      ) : (
        <div className="space-y-3">
          {displayReports.map((report) => {
            const patientName = IS_MOCK ? (report as typeof mockReports[0]).patientName : report.sessionId;
            return (
              <div
                key={report.id}
                className="card card-interactive"
                onClick={() => navigate(`/reports/${report.sessionId}`)}
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-body font-medium text-ink-heading dark:text-white">
                        {patientName}
                      </h3>
                      <span className={`badge ${reviewStatusBadge(report.reviewStatus)}`}>
                        {reviewStatusLabel(report.reviewStatus)}
                      </span>
                    </div>
                    {report.summary && (
                      <p className="mt-1 text-small text-ink-muted line-clamp-2">{report.summary}</p>
                    )}
                    <div className="mt-2 flex items-center gap-3">
                      {report.icd10Codes && report.icd10Codes.length > 0 && (
                        <div className="flex gap-1">
                          {report.icd10Codes.slice(0, 3).map((code) => (
                            <span key={code} className="rounded-pill bg-primary-50 px-2 py-0.5 text-tiny font-data text-primary-600 dark:bg-primary-950 dark:text-primary-400">
                              {code}
                            </span>
                          ))}
                        </div>
                      )}
                      {report.aiConfidenceScore !== undefined && (
                        <span className="text-tiny text-ink-muted font-tnum">
                          AI 信心: {Math.round(report.aiConfidenceScore * 100)}%
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="ml-4 flex flex-shrink-0 flex-col items-end gap-1">
                    <span className="text-tiny text-ink-muted font-tnum">
                      {formatDate(report.generatedAt, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </span>
                    <svg className="h-4 w-4 text-ink-placeholder" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
