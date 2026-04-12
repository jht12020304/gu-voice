import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, FileText, Calendar, Activity, CheckCircle2 } from 'lucide-react';

export default function PatientSessionDetailPage() {
  const { sessionId } = useParams();

  // Mock data for the session detail
  const mockSession = {
    id: sessionId,
    date: '2026-04-12 14:30',
    status: 'COMPLETED',
    chiefComplaint: '血尿 (Bloody Urine)',
    duration: '08:45',
    doctor: '陳醫師',
    notes: '患者主訴近期排尿時帶有輕微血絲，無明顯痛感。已安排進一步超音波檢查並提醒多喝水。目前不建議劇烈運動。',
    summary: '初步排除結石可能，待驗尿與超音波結果。'
  };

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
          <p className="text-sm text-surface-500">紀錄 ID: {mockSession.id?.split('-')[0]}</p>
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
                {mockSession.date}
              </span>
            </div>
            <h2 className="text-xl font-bold text-primary-900 flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary-600" />
              主訴：{mockSession.chiefComplaint}
            </h2>
          </div>
        </div>

        <div className="p-6 space-y-8">
          {/* Summary Section */}
          <section>
            <h3 className="text-sm font-semibold text-surface-900 uppercase tracking-wider mb-3">醫師總結</h3>
            <div className="p-4 bg-surface-50 rounded-xl text-surface-700 leading-relaxed border border-surface-100">
              {mockSession.summary}
            </div>
          </section>

          {/* Details Section */}
          <section>
            <h3 className="text-sm font-semibold text-surface-900 uppercase tracking-wider mb-3 flex items-center gap-2">
              <FileText className="h-4 w-4 text-surface-400" />
              醫囑建議
            </h3>
            <div className="p-4 bg-white border border-surface-200 shadow-sm rounded-xl text-surface-800 leading-relaxed indent-4">
              {mockSession.notes}
            </div>
          </section>

          {/* Meta Info */}
          <section className="grid grid-cols-2 pt-6 border-t border-surface-200 gap-4">
            <div>
              <p className="text-xs text-surface-500 mb-1">主治醫師</p>
              <p className="font-medium text-surface-900">{mockSession.doctor}</p>
            </div>
            <div>
              <p className="text-xs text-surface-500 mb-1">對話時長</p>
              <p className="font-medium text-surface-900">{mockSession.duration}</p>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
