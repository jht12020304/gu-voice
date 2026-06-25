import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { ArrowLeft, AlertTriangle, Clock, Target, CheckCircle, Lightbulb, User } from 'lucide-react';
import { useCurrentLng } from '../../i18n/paths';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import type { RedFlagAlert, Session } from '../../types';
import * as alertsApi from '../../services/api/alerts';
import * as sessionsApi from '../../services/api/sessions';
import { formatDate } from '../../utils/format';

export default function AlertDetailPage() {
  const { alertId } = useParams();
  const { t } = useTranslation('dashboard');
  const lng = useCurrentLng();
  const [alert, setAlert] = useState<RedFlagAlert | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [actionTaken, setActionTaken] = useState('');
  const [notes, setNotes] = useState('');
  // acknowledge 回應只含 id / acknowledged_*，不回傳 action_taken，
  // 故醫師確認後以本地輸入值保留並顯示已記錄的處置。
  const [recordedActionTaken, setRecordedActionTaken] = useState('');

  useEffect(() => {
    if (!alertId) return;
    const currentAlertId = alertId;

    async function load() {
      setIsLoading(true);
      setError('');
      try {
        const alertData = await alertsApi.getAlert(currentAlertId);
        setAlert(alertData);
        try {
          const sessionData = await sessionsApi.getSession(alertData.sessionId);
          setSession(sessionData);
        } catch {
          setSession(null);
        }
      } catch {
        setError(t('alert.detail.loadError', '無法載入警示詳情'));
      } finally {
        setIsLoading(false);
      }
    }

    load();
  }, [alertId, t]);

  const handleAcknowledge = async () => {
    if (!alert || alert.acknowledgedAt || isSubmitting) return;
    const trimmedAction = actionTaken.trim();
    const trimmedNotes = notes.trim();
    setIsSubmitting(true);
    setError('');
    try {
      const updated = await alertsApi.acknowledgeAlert(alert.id, {
        actionTaken: trimmedAction || undefined,
        acknowledgeNotes: trimmedNotes || undefined,
      });
      // acknowledge 回應為部分欄位（id / acknowledged_*），merge 進現有 alert
      // 以免覆蓋掉 title / severity / triggerReason 等已載入的詳情。
      setAlert((prev) => (prev ? { ...prev, ...updated } : updated));
      setRecordedActionTaken(trimmedAction);
      toast.success(t('alert.detail.acknowledgeSuccess', '已標示為已處理'));
    } catch {
      setError(t('alert.detail.acknowledgeError', '確認警示失敗'));
      toast.error(t('alert.detail.acknowledgeError', '確認警示失敗'));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) return <LoadingSpinner fullPage message={t('alert.detail.loading', '載入警示詳情...')} />;
  if (error && !alert) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!alert) return <ErrorState message={t('alert.detail.notFound', '找不到警示資料')} />;

  const patientName = session?.patient?.name ?? t('alert.detail.unknownPatient', '未知病患');
  const patientPath = session?.patientId
    ? `/${lng}/patients/${session.patientId}`
    : `/${lng}/patients`;
  const llmAnalysis =
    typeof alert.llmAnalysis === 'string'
      ? alert.llmAnalysis
      : alert.llmAnalysis
        ? JSON.stringify(alert.llmAnalysis, null, 2)
        : '';
  const isAcknowledged = !!alert.acknowledgedAt;
  // 已記錄處置：優先本地輸入值，fallback 後端可能回傳的 actionTaken / acknowledgeNotes。
  const displayActionTaken =
    recordedActionTaken ||
    (alert as RedFlagAlert & { actionTaken?: string }).actionTaken ||
    '';

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-10">
      <div className="flex items-center gap-4 mb-4">
        <Link to={`/${lng}/alerts`} className="p-2 -ml-2 rounded-xl text-surface-500 hover:bg-surface-100 transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-surface-900">{t('alert.detail.title', '警示詳情')}</h1>
          <p className="text-sm text-surface-500">Alert ID: {alert.id}</p>
        </div>
      </div>

      <div className="bg-red-50 border border-red-200 rounded-2xl p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0 mt-1">
            <AlertTriangle className="h-6 w-6 text-red-600" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold text-red-900">{alert.title}</h2>
              <span className="px-2.5 py-1 text-xs font-bold bg-red-600 text-white rounded-full">
                {alert.severity.toUpperCase()}
              </span>
              {isAcknowledged ? (
                <span className="px-2.5 py-1 text-xs font-bold bg-green-600 text-white rounded-full">
                  {t('alert.detail.acknowledgedBadge', '已處理')}
                </span>
              ) : null}
            </div>
            <p className="text-red-700 mt-2">{alert.triggerReason}</p>
          </div>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-6">
          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <Target className="h-4 w-4" />
              {t('alert.detail.triggerKeywords', '觸發關鍵字')}
            </h3>
            {alert.triggerKeywords && alert.triggerKeywords.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {alert.triggerKeywords.map((tag) => (
                  <span key={tag} className="px-3 py-1.5 bg-red-100 text-red-800 rounded-lg text-sm font-medium">
                    "{tag}"
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-surface-500 text-sm">{t('alert.detail.noKeywords', '此警示沒有關鍵字資料')}</p>
            )}
          </div>

          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <Lightbulb className="h-4 w-4" />
              {t('alert.detail.llmAnalysis', 'LLM 語意分析')}
            </h3>
            {llmAnalysis ? (
              <pre className="whitespace-pre-wrap break-words text-surface-700 leading-relaxed bg-surface-50 p-4 rounded-xl border border-surface-100">
                {llmAnalysis}
              </pre>
            ) : (
              <p className="text-surface-500 text-sm">{t('alert.detail.noLlmAnalysis', '無額外語意分析內容')}</p>
            )}
          </div>

          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <CheckCircle className="h-4 w-4" />
              {t('alert.detail.suggestedActions', '建議行動')}
            </h3>
            {alert.suggestedActions && alert.suggestedActions.length > 0 ? (
              <ul className="space-y-3">
                {alert.suggestedActions.map((action, idx) => (
                  <li key={action} className="flex gap-3">
                    <div className="w-6 h-6 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center font-bold text-sm shrink-0">
                      {idx + 1}
                    </div>
                    <span className="text-surface-800">{action}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-surface-500 text-sm">{t('alert.detail.noSuggestedActions', '無建議行動資料')}</p>
            )}
          </div>
        </div>

        <div className="md:col-span-1 space-y-6">
          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="font-semibold text-surface-900 mb-4">{t('alert.detail.trackingTitle', '事件追蹤與病患')}</h3>
            <div className="space-y-4">
              <div>
                <p className="text-xs text-surface-400 mb-1 flex items-center gap-1"><User className="h-3.5 w-3.5" /> {t('alert.detail.affectedPatient', '影響病患')}</p>
                <Link to={patientPath} className="font-medium text-primary-600 hover:underline">{patientName}</Link>
              </div>
              <div>
                <p className="text-xs text-surface-400 mb-1 flex items-center gap-1"><Clock className="h-3.5 w-3.5" /> {t('alert.detail.occurredAt', '發生時間')}</p>
                <p className="font-medium text-surface-900 text-sm">{formatDate(alert.createdAt)}</p>
              </div>
              <div>
                <p className="text-xs text-surface-400 mb-1">{t('alert.detail.sessionIdLabel', '對應 Session ID')}</p>
                <Link to={`/${lng}/sessions/${alert.sessionId}`} className="font-mono text-primary-600 hover:underline text-sm truncate block">
                  {alert.sessionId}
                </Link>
              </div>
            </div>

            <hr className="my-5 border-surface-100" />

            {isAcknowledged ? (
              <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                <p className="flex items-center gap-2 text-sm font-semibold text-green-800">
                  <CheckCircle className="h-4 w-4" />
                  {t('alert.detail.acknowledgedHeading', '已標示處理')}
                </p>
                <div className="mt-2">
                  <p className="text-xs font-medium text-green-700">{t('alert.detail.actionTakenLabel', '已採取的處置')}</p>
                  <p className="mt-0.5 whitespace-pre-wrap text-sm text-green-900">
                    {displayActionTaken || t('alert.detail.noActionRecorded', '未記錄處置內容')}
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label htmlFor="action-taken" className="mb-1 block text-xs font-medium text-surface-600">
                    {t('alert.detail.actionTakenLabel', '已採取的處置')}
                  </label>
                  <textarea
                    id="action-taken"
                    rows={3}
                    value={actionTaken}
                    onChange={(e) => setActionTaken(e.target.value)}
                    disabled={isSubmitting}
                    placeholder={t('alert.detail.actionTakenPlaceholder', '例如：已安排立即就醫並通報主治')}
                    className="w-full rounded-xl border border-surface-200 px-3 py-2 text-sm text-surface-900 placeholder:text-surface-400 focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                </div>
                <div>
                  <label htmlFor="ack-notes" className="mb-1 block text-xs font-medium text-surface-600">
                    {t('alert.detail.notesLabel', '備註（選填）')}
                  </label>
                  <textarea
                    id="ack-notes"
                    rows={2}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    disabled={isSubmitting}
                    placeholder={t('alert.detail.notesPlaceholder', '其他補充說明')}
                    className="w-full rounded-xl border border-surface-200 px-3 py-2 text-sm text-surface-900 placeholder:text-surface-400 focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                </div>
                <button
                  className="flex w-full items-center justify-center gap-2 py-2.5 px-4 bg-surface-900 text-white rounded-xl font-medium hover:bg-surface-800 transition-colors shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={handleAcknowledge}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                      {t('alert.detail.acknowledging', '處理中...')}
                    </>
                  ) : (
                    t('alert.detail.acknowledgeButton', '標示為已處理')
                  )}
                </button>
              </div>
            )}
            <Link
              to={`/${lng}/sessions/${alert.sessionId}`}
              className="mt-2 block w-full rounded-xl border border-surface-200 px-4 py-2.5 text-center font-medium text-surface-700 transition-colors hover:bg-surface-50"
            >
              {t('alert.detail.goToSession', '前往場次詳情')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
