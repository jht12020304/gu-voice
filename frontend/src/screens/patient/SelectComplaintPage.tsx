// =============================================================================
// 選擇主訴頁 — 病患選擇症狀後進入病史填寫
//
// 多語策略：
// - 頁面 UI 字串：`useTranslation('intake').selectComplaint.*`
// - 主訴 name / description / category：由後端 `pick()` 依 Accept-Language
//   回傳已 resolve 的字串，前端直接顯示不再 key map
// - 類別顯示：用 `selectComplaint.categories.*`，若後端 category 不在已知
//   清單則原樣顯示（未來可自 JSONB 直接讀 category_by_lang 以取消此映射）
// =============================================================================

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
import { useComplaintStore } from '../../stores/complaintStore';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import type { ChiefComplaint } from '../../types';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

// Mock 僅供本機開發；name/nameEn/description 均以 zh-TW 起步，
// 切英文時仍看到中文屬可接受的已知限制（真實環境走 API 的多語 resolver）。
const mockComplaints: ChiefComplaint[] = [
  { id: 'cc1', name: '血尿', nameEn: 'Hematuria', description: '尿液中帶血或呈紅色', category: '排尿症狀', isDefault: true, isActive: true, displayOrder: 1, createdAt: '', updatedAt: '' },
  { id: 'cc2', name: '頻尿', nameEn: 'Frequent Urination', description: '排尿次數異常增多', category: '排尿症狀', isDefault: true, isActive: true, displayOrder: 2, createdAt: '', updatedAt: '' },
  { id: 'cc3', name: '排尿疼痛', nameEn: 'Dysuria', description: '排尿時感到疼痛或灼熱', category: '排尿症狀', isDefault: true, isActive: true, displayOrder: 3, createdAt: '', updatedAt: '' },
  { id: 'cc4', name: '尿失禁', nameEn: 'Urinary Incontinence', description: '無法控制排尿', category: '排尿症狀', isDefault: false, isActive: true, displayOrder: 4, createdAt: '', updatedAt: '' },
  { id: 'cc5', name: '腰痛', nameEn: 'Flank Pain', description: '側腰部或後腰疼痛', category: '疼痛', isDefault: true, isActive: true, displayOrder: 5, createdAt: '', updatedAt: '' },
  { id: 'cc6', name: '下腹痛', nameEn: 'Lower Abdominal Pain', description: '下腹部疼痛或不適', category: '疼痛', isDefault: false, isActive: true, displayOrder: 6, createdAt: '', updatedAt: '' },
  { id: 'cc7', name: '陰囊腫脹', nameEn: 'Scrotal Swelling', description: '陰囊腫大或有硬塊', category: '其他', isDefault: false, isActive: true, displayOrder: 7, createdAt: '', updatedAt: '' },
  { id: 'cc8', name: '勃起功能障礙', nameEn: 'Erectile Dysfunction', description: '勃起困難或無法維持', category: '其他', isDefault: false, isActive: true, displayOrder: 8, createdAt: '', updatedAt: '' },
  { id: 'cc9', name: 'PSA 異常', nameEn: 'Elevated PSA', description: 'PSA 指數偏高需追蹤', category: '檢查異常', isDefault: false, isActive: true, displayOrder: 9, createdAt: '', updatedAt: '' },
  { id: 'cc10', name: '尿液檢查異常', nameEn: 'Abnormal Urinalysis', description: '尿液常規檢查發現異常', category: '檢查異常', isDefault: false, isActive: true, displayOrder: 10, createdAt: '', updatedAt: '' },
];

// 任一語言 → intake.selectComplaint.categories.* 的 key 映射。
// 後端已用 Accept-Language 回傳 localized category，但舊記錄可能未 backfill
// `category_by_lang` → fallback 成 zh-TW；本表同時收錄 5 國語言對應 key，
// 讓「已翻譯」與「未翻譯」的 category 都落在同一個 i18n bucket，避免出現兩組同名 section。
const CATEGORY_I18N_KEY: Record<string, string> = {
  // zh-TW（legacy fallback）
  '排尿症狀': 'urinarySymptoms',
  '排尿': 'urinarySymptoms',  // admin 變體
  '疼痛': 'pain',
  '疼痛症狀': 'pain',  // admin 變體：與 seed「疼痛」合併 section
  '檢查異常': 'examinationAbnormalities',
  '其他': 'other',
  // en-US
  'Urinary symptoms': 'urinarySymptoms',
  'Pain': 'pain',
  'Abnormal findings': 'examinationAbnormalities',
  'Other': 'other',
  // ja-JP（'疼痛' 與 zh-TW 同字，上方已涵蓋）
  '排尿症状': 'urinarySymptoms',
  '検査異常': 'examinationAbnormalities',
  'その他': 'other',
  // ko-KR
  '배뇨 증상': 'urinarySymptoms',
  '통증': 'pain',
  '검사 이상': 'examinationAbnormalities',
  '기타': 'other',
  // vi-VN
  'Triệu chứng tiết niệu': 'urinarySymptoms',
  'Đau': 'pain',
  'Kết quả xét nghiệm bất thường': 'examinationAbnormalities',
  'Khác': 'other',
};

/** 將 backend 回傳的 category 字串正規化為穩定 bucket key；
 *  找不到對應時以原字串當 key（保留 admin 自訂 category 的分組能力）。 */
function categoryBucket(raw: string): string {
  return CATEGORY_I18N_KEY[raw] ?? raw;
}

function groupByCategory(complaints: ChiefComplaint[]): Record<string, ChiefComplaint[]> {
  return complaints.reduce<Record<string, ChiefComplaint[]>>((acc, c) => {
    const bucket = categoryBucket(c.category);
    if (!acc[bucket]) acc[bucket] = [];
    acc[bucket].push(c);
    return acc;
  }, {});
}

export default function SelectComplaintPage() {
  const navigate = useLocalizedNavigate();
  const { t, i18n } = useTranslation('intake');
  const { complaints, isLoading: storeLoading, fetchComplaints } = useComplaintStore();
  const [selected, setSelected] = useState<ChiefComplaint | null>(null);
  const [customText, setCustomText] = useState('');

  const displayComplaints = IS_MOCK ? mockComplaints : complaints;
  const isLoading = IS_MOCK ? false : storeLoading;

  // 語言變更時 refetch — 後端依 Accept-Language 回傳 localized name/description/category
  useEffect(() => {
    if (!IS_MOCK) {
      fetchComplaints();
    }
  }, [fetchComplaints, i18n.resolvedLanguage]);

  const grouped = useMemo(() => groupByCategory(displayComplaints), [displayComplaints]);

  // groupByCategory 已用 categoryBucket() 正規化過，傳進來的 bucket 可能是 i18n key
  // （urinarySymptoms / pain / ...）或原 category 字串（admin 自訂類別）。
  const localizedCategory = (bucket: string) => {
    // 已是 i18n key → 直接翻譯；否則回傳原字串
    const KNOWN = new Set(['urinarySymptoms', 'pain', 'examinationAbnormalities', 'other']);
    return KNOWN.has(bucket) ? t(`selectComplaint.categories.${bucket}`) : bucket;
  };

  const handleStart = () => {
    if (!selected) return;
    const params = new URLSearchParams({
      complaintId: selected.id,
      complaintName: selected.name,
      complaintText: customText || selected.name,
    });
    navigate(`/patient/medical-info?${params.toString()}`);
  };

  if (isLoading) return <LoadingSpinner fullPage message={t('selectComplaint.loading')} />;

  return (
    <div className="mx-auto max-w-3xl px-6 py-8 animate-fade-in">

      {/* Header */}
      <div className="mb-8 flex items-center gap-3">
        <button
          className="rounded-card p-1.5 text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary transition-colors"
          onClick={() => navigate('/patient')}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div>
          <h1 className="text-h2 font-semibold tracking-tight text-ink-heading dark:text-white">
            {t('selectComplaint.title')}
          </h1>
          <p className="mt-0.5 text-body text-ink-muted dark:text-white/50">
            {t('selectComplaint.subtitle')}
          </p>
        </div>
      </div>

      {/* 分類症狀 */}
      <div className="space-y-8">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            {/* 分類標題 — 純文字，無圖示 */}
            <h2 className="mb-3 text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">
              {localizedCategory(category)}
            </h2>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {items.map((complaint) => {
                const isSelected = selected?.id === complaint.id;
                return (
                  <button
                    key={complaint.id}
                    className={`rounded-card border px-4 py-4 text-left transition-all ${
                      isSelected
                        ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500/20 dark:border-primary-400 dark:bg-primary-950 dark:ring-primary-400/20'
                        : 'border-edge bg-white hover:border-edge-hover hover:shadow-card dark:border-dark-border dark:bg-dark-card dark:hover:border-dark-border'
                    }`}
                    onClick={() => setSelected(complaint)}
                  >
                    <p className={`text-body font-semibold leading-snug ${
                      isSelected ? 'text-primary-700 dark:text-primary-300' : 'text-ink-heading dark:text-white'
                    }`}>
                      {complaint.name}
                    </p>
                    {complaint.nameEn && (
                      <p className="mt-0.5 text-tiny text-ink-placeholder dark:text-white/30">
                        {complaint.nameEn}
                      </p>
                    )}
                    {complaint.description && (
                      <p className={`mt-2 text-small leading-snug ${
                        isSelected ? 'text-primary-600/70 dark:text-primary-400/60' : 'text-ink-muted dark:text-white/40'
                      }`}>
                        {complaint.description}
                      </p>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 補充說明 */}
      {selected && (
        <div className="mt-8 animate-fade-in">
          <label className="mb-1.5 block text-small font-medium text-ink-secondary dark:text-white/60">
            {t('selectComplaint.customLabel')}
          </label>
          <textarea
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            placeholder={t('selectComplaint.customPlaceholder', { name: selected.name })}
            className="input-base min-h-[80px] resize-y"
            rows={3}
          />
        </div>
      )}

      {/* 底部按鈕 */}
      <div className="sticky bottom-0 mt-8 border-t border-edge bg-surface-secondary/80 py-4 backdrop-blur-sm dark:border-dark-border dark:bg-dark-bg/80">
        <button
          className="btn-primary w-full py-3 text-body"
          disabled={!selected}
          onClick={handleStart}
        >
          {t('selectComplaint.cta')}
        </button>
      </div>
    </div>
  );
}
