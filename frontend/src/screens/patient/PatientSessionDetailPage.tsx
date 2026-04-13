import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, FileText, Calendar, Activity, CheckCircle2 } from 'lucide-react';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import type { Session, SOAPReport } from '../../types';
import * as sessionsApi from '../../services/api/sessions';
import * as reportsApi from '../../services/api/reports';
import { formatDate, formatDuration } from '../../utils/format';

export default function PatientSessionDetailPage() {
  const { sessionId } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [report, setReport] = useState<SOAPReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    const currentSessionId = sessionId;

    async function load() {
      setIsLoading(true);
      setError('');
      try {
        const sessionData = await sessionsApi.getSession(currentSessionId);
        setSession(sessionData);
        try {
          const reportData = await reportsApi.getReportBySession(currentSessionId);
          setReport(reportData);
        } catch {
          setReport(null);
        }
      } catch {
        setError('無法載入問診紀錄');
      } finally {
        setIsLoading(false);
      }
    }

    load();
  }, [sessionId]);

  if (isLoading) return <LoadingSpinner fullPage message="載入問診紀錄..." />;
  if (error || !session) return <ErrorState message={error || '找不到問診紀錄'} />;

  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-20">
      <div className="flex items-center gap-4">
        <Link 
          to="/patient/history" 
          className="p-2 -ml-2 rounded-xl text-surface-500 hover:bg-surface-100 transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-surface-900">問診紀錄詳情</h1>
          <p className="text-sm text-surface-500">紀錄 ID: {session.id}</p>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-surface-200 shadow-sm overflow-hidden">
        <div className="bg-primary-50 p-6 border-b border-primary-100 flex justify-between items-start">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-2.5 py-1 text-xs font-medium bg-green-100 text-green-700 rounded-full flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5" />
                已完成
              </span>
              <span className="text-sm text-surface-500 flex items-center gap-1">
                <Calendar className="h-4 w-4" />
                {formatDate(session.createdAt)}
              </span>
            </div>
            <h2 className="text-xl font-bold text-primary-900 flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary-600" />
              主訴：{session.chiefComplaintText || session.chiefComplaint?.name || '未填寫'}
            </h2>
          </div>
        </div>

        <div className="p-6 space-y-8">
          {/* Summary Section */}
          <section>
            <h3 className="text-sm font-semibold text-surface-900 uppercase tracking-wider mb-3">醫師總結</h3>
            <div className="p-4 bg-surface-50 rounded-xl text-surface-700 leading-relaxed border border-surface-100">
              {report?.summary || '目前尚無已產生的摘要內容。'}
            </div>
          </section>

          {/* Details Section */}
          <section>
            <h3 className="text-sm font-semibold text-surface-900 uppercase tracking-wider mb-3 flex items-center gap-2">
              <FileText className="h-4 w-4 text-surface-400" />
              醫囑建議
            </h3>
            <div className="p-4 bg-white border border-surface-200 shadow-sm rounded-xl text-surface-800 leading-relaxed indent-4">
              {report?.plan?.patientEducation?.join('；') || report?.reviewNotes || '目前尚無可顯示的醫囑建議。'}
            </div>
          </section>

          {/* Meta Info */}
          <section className="grid grid-cols-2 pt-6 border-t border-surface-200 gap-4">
            <div>
              <p className="text-xs text-surface-500 mb-1">主治醫師</p>
              <p className="font-medium text-surface-900">{session.doctorId || '未指派'}</p>
            </div>
            <div>
              <p className="text-xs text-surface-500 mb-1">對話時長</p>
              <p className="font-medium text-surface-900">{session.durationSeconds ? formatDuration(session.durationSeconds) : '-'}</p>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
