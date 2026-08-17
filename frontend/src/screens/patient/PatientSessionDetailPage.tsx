import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, FileText, Calendar, Activity, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useCurrentLng } from '../../i18n/paths';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import type { Session, SOAPReport } from '../../types';
import * as sessionsApi from '../../services/api/sessions';
import * as reportsApi from '../../services/api/reports';
import { formatDate, formatDuration } from '../../utils/format';

export default function PatientSessionDetailPage() {
  const { sessionId } = useParams();
  const lng = useCurrentLng();
  const { t } = useTranslation('session');
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
        setError(t('patientDetail.loadError'));
      } finally {
        setIsLoading(false);
      }
    }

    load();
  }, [sessionId, t]);

  if (isLoading) return <LoadingSpinner fullPage message={t('patientDetail.loading')} />;
  if (error || !session) return <ErrorState message={error || t('patientDetail.notFound')} />;

  const chiefComplaintValue =
    session.chiefComplaintText || session.chiefComplaint?.name || t('patientDetail.chiefComplaintEmpty');

  // 病患衛教（SOAP plan.patientEducation）——這是本頁唯一允許呈現給病患的「建議」。
  //
  // 型別上是 string[]，但實際來源是 LLM 產出 + 後端出口過濾，執行期可能是
  // undefined / null / 空陣列 / 單一字串 / 含空字串或 null 的陣列。舊寫法
  // `report?.plan?.patientEducation?.join('；')` 在「被換成字串」時會直接
  // TypeError（字串沒有 .join）把整頁炸掉，在「['', '']」時則印出一個孤零零的
  // 分隔符號。這裡一律正規化成「非空字串陣列」再渲染，任何非預期形狀都退回
  // adviceEmpty，不會壞畫面。
  const patientEducation: string[] = (() => {
    const raw: unknown = report?.plan?.patientEducation;
    const items = Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : [];
    return items
      .filter((x): x is string => typeof x === 'string')
      .map((x) => x.trim())
      .filter((x) => x.length > 0);
  })();

  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-20">
      <div className="flex items-center gap-4">
        <Link
          to={`/${lng}/patient/history`}
          className="p-2 -ml-2 rounded-xl text-surface-500 hover:bg-surface-100 transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-surface-900">{t('patientDetail.title')}</h1>
          <p className="text-sm text-surface-500">{t('patientDetail.recordId', { id: session.id })}</p>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-surface-200 shadow-sm overflow-hidden">
        <div className="bg-primary-50 p-6 border-b border-primary-100 flex justify-between items-start">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-2.5 py-1 text-xs font-medium bg-green-100 text-green-700 rounded-full flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {t('patientDetail.statusCompleted')}
              </span>
              <span className="text-sm text-surface-500 flex items-center gap-1">
                <Calendar className="h-4 w-4" />
                {formatDate(session.createdAt)}
              </span>
            </div>
            <h2 className="text-xl font-bold text-primary-900 flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary-600" />
              {t('patientDetail.chiefComplaint', { value: chiefComplaintValue })}
            </h2>
          </div>
        </div>

        <div className="p-6 space-y-8">
          {/* Summary Section */}
          <section>
            <h3 className="text-sm font-semibold text-surface-900 uppercase tracking-wider mb-3">{t('patientDetail.summaryHeading')}</h3>
            <div className="p-4 bg-surface-50 rounded-xl text-surface-700 leading-relaxed border border-surface-100">
              {report?.summary || t('patientDetail.summaryEmpty')}
            </div>
          </section>

          {/* Details Section */}
          <section>
            <h3 className="text-sm font-semibold text-surface-900 uppercase tracking-wider mb-3 flex items-center gap-2">
              <FileText className="h-4 w-4 text-surface-400" />
              {t('patientDetail.adviceHeading')}
            </h3>
            {/* 沒有衛教內容時**不可**退回 report.reviewNotes——那是醫師的審閱備註
                （醫師向自由文字），退回去等於把醫師的內部註記直接顯示給病患。
                後端這輪對 patientEducation 加了出口過濾，過濾後常態就是空陣列，
                舊的 `|| report?.reviewNotes` 會讓這個洩漏從邊角情境變成常態。 */}
            <div className="p-4 bg-white border border-surface-200 shadow-sm rounded-xl text-surface-800 leading-relaxed">
              {patientEducation.length > 0 ? (
                <ul className="list-disc pl-5 space-y-1">
                  {patientEducation.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="indent-4">{t('patientDetail.adviceEmpty')}</p>
              )}
            </div>
          </section>

          {/* Meta Info */}
          <section className="grid grid-cols-2 pt-6 border-t border-surface-200 gap-4">
            <div>
              <p className="text-xs text-surface-500 mb-1">{t('patientDetail.doctorLabel')}</p>
              <p className="font-medium text-surface-900">{session.doctorId || t('patientDetail.doctorUnassigned')}</p>
            </div>
            <div>
              <p className="text-xs text-surface-500 mb-1">{t('patientDetail.durationLabel')}</p>
              <p className="font-medium text-surface-900">{session.durationSeconds ? formatDuration(session.durationSeconds) : t('patientDetail.durationEmpty')}</p>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
