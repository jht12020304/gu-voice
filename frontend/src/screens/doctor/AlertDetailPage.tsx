import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, AlertTriangle, Clock, Target, CheckCircle, Lightbulb, User } from 'lucide-react';

export default function AlertDetailPage() {
  const { alertId } = useParams();

  // Mock Alert details
  const mockAlert = {
    id: alertId,
    title: '偵測到潛在敗血症跡象 (Sepsis Sign)',
    patientName: '王小明',
    sessionId: 'sess-1234',
    severity: 'CRITICAL',
    timestamp: '2026-04-12 15:45:22',
    triggerReason: '系統經語意分析偵測到持續高燒、意識模糊與心跳加速的組合描述。',
    matchedKeywords: ['高燒不退', '頭暈', '想吐', '心跳很快'],
    llmAnalysis: '語音轉錄內容顯示患者提到「昨天開始就一直發燒到39度，而且一直覺得很喘、心臟跳得很大力」。這些關鍵字綜合評估符合敗血症或嚴重心因性問題之初期表徵，建議立刻終止例行問診並導向急診。',
    suggestedActions: [
      '立即撥打電話聯絡患者家屬',
      '建議患者立即前往最近急診室',
      '安排醫療人員緊急介入對話'
    ]
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-10">
      <div className="flex items-center gap-4 mb-4">
        <Link to="/alerts" className="p-2 -ml-2 rounded-xl text-surface-500 hover:bg-surface-100 transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-surface-900">警示詳情</h1>
          <p className="text-sm text-surface-500">Alert ID: {mockAlert.id}</p>
        </div>
      </div>

      {/* Hero Alert Banner */}
      <div className="bg-red-50 border border-red-200 rounded-2xl p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0 mt-1">
            <AlertTriangle className="h-6 w-6 text-red-600" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold text-red-900">{mockAlert.title}</h2>
              <span className="px-2.5 py-1 text-xs font-bold bg-red-600 text-white rounded-full">
                {mockAlert.severity}
              </span>
            </div>
            <p className="text-red-700 mt-2">{mockAlert.triggerReason}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* 左側詳細資訊 */}
        <div className="md:col-span-2 space-y-6">
          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <Target className="h-4 w-4" />
              觸發關鍵字
            </h3>
            <div className="flex flex-wrap gap-2">
              {mockAlert.matchedKeywords.map((tag, idx) => (
                <span key={idx} className="px-3 py-1.5 bg-red-100 text-red-800 rounded-lg text-sm font-medium">
                  "{tag}"
                </span>
              ))}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <Lightbulb className="h-4 w-4" />
              LLM 語意分析
            </h3>
            <p className="text-surface-700 leading-relaxed bg-surface-50 p-4 rounded-xl border border-surface-100">
              {mockAlert.llmAnalysis}
            </p>
          </div>

          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <CheckCircle className="h-4 w-4" />
              建議行動
            </h3>
            <ul className="space-y-3">
              {mockAlert.suggestedActions.map((action, idx) => (
                <li key={idx} className="flex gap-3">
                  <div className="w-6 h-6 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center font-bold text-sm shrink-0">
                    {idx + 1}
                  </div>
                  <span className="text-surface-800">{action}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* 右側 Meta Card */}
        <div className="md:col-span-1 space-y-6">
          <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-6">
            <h3 className="font-semibold text-surface-900 mb-4">事件追蹤與病患</h3>
            <div className="space-y-4">
              <div>
                <p className="text-xs text-surface-400 mb-1 flex items-center gap-1"><User className="h-3.5 w-3.5" /> 影響病患</p>
                <Link to="/patients" className="font-medium text-primary-600 hover:underline">{mockAlert.patientName}</Link>
              </div>
              <div>
                <p className="text-xs text-surface-400 mb-1 flex items-center gap-1"><Clock className="h-3.5 w-3.5" /> 發生時間</p>
                <p className="font-medium text-surface-900 text-sm">{mockAlert.timestamp}</p>
              </div>
              <div>
                <p className="text-xs text-surface-400 mb-1">對應 Session ID</p>
                <Link to={`/sessions/${mockAlert.sessionId}`} className="font-mono text-primary-600 hover:underline text-sm truncate block">
                  {mockAlert.sessionId}
                </Link>
              </div>
            </div>

            <hr className="my-5 border-surface-100" />
            
            <button className="w-full py-2.5 px-4 bg-surface-900 text-white rounded-xl font-medium hover:bg-surface-800 transition-colors shadow-sm">
              標示為已處理
            </button>
            <button className="w-full py-2.5 px-4 mt-2 bg-white border border-surface-200 text-surface-700 rounded-xl font-medium hover:bg-surface-50 transition-colors">
              誤報忽略
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
