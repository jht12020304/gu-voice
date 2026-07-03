// =============================================================================
// 選擇主訴頁 — 病患選擇症狀後進入病史填寫
//
// 多語策略：
// - 頁面 UI 字串：`useTranslation('intake').selectComplaint.*`
// - 主訴 name / description / category：由後端 `pick()` 依 Accept-Language
//   回傳已 resolve 的字串，前端直接顯示不再 key map
// - 類別顯示：用 `selectComplaint.categories.*`，若後端 category 不在已知
//   清單則原樣顯示（未來可自 JSONB 直接讀 category_by_lang 以取消此映射）
//
// 主訴複選（2026-06-26）：
// - 可複選多個症狀以協助醫師 narrow down 鑑別診斷。
// - 後端 chief_complaint_id 仍是單一必填 FK → 取「第一個選的」當 primary；
//   其餘選項名稱（+ 補充說明）合併進 chief_complaint_text（後端 String(200)）。
//   LLM / Supervisor / SOAP / 紅旗偵測吃的都是這段文字，故無需 DB migration。
// - 醫療安全：合併文字以「code point」為單位嚴格 <=200，且選取時即用 NAME_BUDGET
//   擋住名稱總長，確保症狀名稱永不被中途截斷（否則醫師端/SOAP/紅旗會漏掉次要主訴）。
//
// 「其他」選項（2026-07-04）：
// - 預設主訴涵蓋不了的狀況走「其他」sentinel（固定 UUID，後端 seed 同步），
//   FK 指向 sentinel、實際主訴內容在 chief_complaint_text（病患自述）。
// - 含「其他」時補充說明轉必填：若併選（如血尿+其他）而自述空白，complaintText
//   只剩既有名稱，「其他」的訊號完全消失（sentinel 非 primary 時連 FK 都不留痕），
//   醫師端/SOAP/紅旗全看不到 → 必填才保證訊號不遺失。
// - 送後端的 complaintText 排除字面「其他」佔位詞，以病患自述為主
//   （否則 AI 開場/SOAP 會出現無資訊量的「其他」）。
// =============================================================================

import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
import { useComplaintStore } from '../../stores/complaintStore';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import type { ChiefComplaint } from '../../types';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

// ── 複選 / 字數上限常量 ──
const MAX_SELECT = 5;        // 最多可選主訴數
const TEXT_MAX = 200;        // == 後端 SessionCreate.chief_complaint_text max_length / models String(200)
const NAME_BUDGET = 160;     // 名稱優先但硬性低於 TEXT_MAX，保留約 40 cp 給「（補充）」，名稱永不被中途切斷

// 「其他」sentinel 主訴 — 與後端 seed（20260704_1000-seed_other_chief_complaint）固定 UUID 同步。
// 選「其他」時補充說明轉必填；送後端的 complaintText 排除字面「其他」，以病患自述為主。
const OTHER_COMPLAINT_ID = '00000000-0000-4000-8000-0000000000ff';

// 以 code point 計數 / 截斷（對齊 Python len()，避免 UTF-16 落單 surrogate 導致 DB insert 失敗）
const cp = (s: string): string[] => Array.from(s);
const clampCp = (s: string, n: number): string => cp(s).slice(0, n).join('');

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
  { id: OTHER_COMPLAINT_ID, name: '其他', nameEn: 'Other', description: '以上皆不符合，請用自己的話描述症狀', category: '其他', isDefault: true, isActive: true, displayOrder: 99, createdAt: '', updatedAt: '' },
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
  // selected 以「選取順序」保存；selected[0] = primary（送後端的單一 FK）
  const [selected, setSelected] = useState<ChiefComplaint[]>([]);
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

  // ── 複選衍生值 ──
  // 分隔符與括號依語系：CJK 用「、」與全形括號，其餘用半形。nameSeparator 帶 inline
  // defaultValue → 即使某語系 intake.json 漏 key 也不會洩漏原始 key 字串。
  const isCJK = !!(
    i18n.resolvedLanguage?.startsWith('zh') || i18n.resolvedLanguage?.startsWith('ja')
  );
  const sep = t('selectComplaint.nameSeparator', { defaultValue: isCJK ? '、' : ', ' });
  const open = isCJK ? '（' : ' (';
  const close = isCJK ? '）' : ')';
  const wrapperLen = cp(open).length + cp(close).length;

  const joinedNames = selected.map((c) => c.name).join(sep);
  // 顯示與儲存共用同一份「已 clamp 名稱」，確保病患確認的 complaintName 與後端
  // 實際存的 complaintText 名稱部分完全一致（避免病患看到完整、醫師看到截斷）。
  const safeNames = clampCp(joinedNames, TEXT_MAX);
  const hasOther = selected.some((c) => c.id === OTHER_COMPLAINT_ID);
  // 送後端文字的名稱部分排除「其他」佔位詞（醫師端要看的是病患自述，不是字面「其他」）
  const namedSelected = selected.filter((c) => c.id !== OTHER_COMPLAINT_ID);
  const safeTextNames = clampCp(namedSelected.map((c) => c.name).join(sep), TEXT_MAX);
  const otherNeedsText = hasOther && customText.trim().length === 0;
  const customMaxLen = Math.max(0, TEXT_MAX - cp(safeTextNames).length - (safeTextNames ? wrapperLen : 0));

  const selIdx = (id: string) => selected.findIndex((x) => x.id === id);

  /** 切換選取；以雙重上限保護：MAX_SELECT 數量上限 + NAME_BUDGET 名稱總長上限。
   *  名稱總長保護是讓「名稱被中途截斷」不可能發生的關鍵（醫療安全）。 */
  function toggleComplaint(c: ChiefComplaint) {
    setSelected((prev) => {
      if (prev.some((x) => x.id === c.id)) {
        return prev.filter((x) => x.id !== c.id); // 取消選取
      }
      if (prev.length >= MAX_SELECT) {
        toast.error(t('selectComplaint.maxReached', { max: MAX_SELECT }));
        return prev;
      }
      const next = [...prev, c];
      // 第一個選項一律允許（避免遇到病態的 200 字 admin 名稱時整頁卡死）；
      // 之後若加入會讓名稱總長超過 NAME_BUDGET 就擋下，名稱因此永遠不需中途切。
      if (prev.length >= 1 && cp(next.map((x) => x.name).join(sep)).length > NAME_BUDGET) {
        toast.error(t('selectComplaint.nameLimitReached'));
        return prev;
      }
      return next;
    });
  }

  /** 組出送後端的 chief_complaint_text：<=200 code points，名稱優先且不被中途切，
   *  只在必要時截斷「補充說明」尾段（code-point 安全）。 */
  function buildComplaintText(names: string, custom: string): string {
    const trimmed = custom.trim();
    if (!trimmed) return clampCp(names, TEXT_MAX);
    if (!names) return clampCp(trimmed, TEXT_MAX); // 只選「其他」：整段即病患自述
    const full = `${names}${open}${trimmed}${close}`;
    if (cp(full).length <= TEXT_MAX) return full;
    const room = TEXT_MAX - cp(names).length - wrapperLen;
    if (room <= 0) return clampCp(names, TEXT_MAX); // 僅在名稱已塞滿上限（病態單一名稱）時
    return `${names}${open}${clampCp(trimmed, room)}${close}`; // 只截補充文字尾段
  }

  const grouped_entries = Object.entries(grouped);

  // groupByCategory 已用 categoryBucket() 正規化過，傳進來的 bucket 可能是 i18n key
  // （urinarySymptoms / pain / ...）或原 category 字串（admin 自訂類別）。
  const localizedCategory = (bucket: string) => {
    // 已是 i18n key → 直接翻譯；否則回傳原字串
    const KNOWN = new Set(['urinarySymptoms', 'pain', 'examinationAbnormalities', 'other']);
    return KNOWN.has(bucket) ? t(`selectComplaint.categories.${bucket}`) : bucket;
  };

  const handleStart = () => {
    if (selected.length === 0) return;
    if (otherNeedsText) {
      toast.error(t('selectComplaint.otherRequired'));
      return; // 防禦：CTA disabled 理論上到不了這裡
    }
    const text = buildComplaintText(safeTextNames, customText); // <=200 cp，名稱不被中途切
    const params = new URLSearchParams({
      complaintId: selected[0].id,   // 單一必填 FK = primary / 第一個選的（可為「其他」sentinel）
      complaintName: safeNames,      // MedicalInfo header + 摘要顯示（含在地化「其他」）；
                                     // 含「其他」時與 text 的名稱部分刻意不相等（text 不含佔位詞）
      complaintText: text,           // AI / Supervisor / SOAP / 紅旗偵測實際吃的內容
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
          <p className="mt-1 text-small text-primary-600 dark:text-primary-300">
            {t('selectComplaint.multiHint')}
            {selected.length > 0 && (
              <span className="ml-2 text-ink-muted dark:text-white/40">
                {t('selectComplaint.selectedCount', { count: selected.length, max: MAX_SELECT })}
              </span>
            )}
          </p>
        </div>
      </div>

      {/* 分類症狀 */}
      <div className="space-y-8">
        {grouped_entries.map(([category, items]) => (
          <div key={category}>
            {/* 分類標題 — 純文字，無圖示 */}
            <h2 className="mb-3 text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">
              {localizedCategory(category)}
            </h2>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {items.map((complaint) => {
                const idx = selIdx(complaint.id);
                const isSelected = idx >= 0;
                // 「其他」卡片以虛線框略作區別（開放式選項，非具體症狀）
                const isOtherCard = complaint.id === OTHER_COMPLAINT_ID;
                return (
                  <button
                    key={complaint.id}
                    aria-pressed={isSelected}
                    className={`relative rounded-card border px-4 py-4 text-left transition-all ${
                      isSelected ? 'pr-12' : ''
                    } ${isOtherCard ? 'border-dashed' : ''} ${
                      isSelected
                        ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500/20 dark:border-primary-400 dark:bg-primary-950 dark:ring-primary-400/20'
                        : 'border-edge bg-white hover:border-edge-hover hover:shadow-card dark:border-dark-border dark:bg-dark-card dark:hover:border-dark-border'
                    }`}
                    onClick={() => toggleComplaint(complaint)}
                  >
                    {isSelected && (
                      <span className="absolute right-2 top-2 flex items-center gap-1">
                        {idx === 0 && (
                          <span className="rounded-full bg-primary-600 px-1.5 py-0.5 text-[10px] font-medium leading-none text-white">
                            {t('selectComplaint.primaryBadge')}
                          </span>
                        )}
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary-600 text-[11px] font-semibold text-white">
                          {idx + 1}
                        </span>
                      </span>
                    )}
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
      {selected.length > 0 && (
        <div className="mt-8 animate-fade-in">
          <label className="mb-1.5 flex items-center justify-between text-small font-medium text-ink-secondary dark:text-white/60">
            <span>
              {hasOther
                ? t('selectComplaint.customLabelRequired')
                : t('selectComplaint.customLabel')}
            </span>
            <span className="text-tiny tabular-nums text-ink-placeholder dark:text-white/30">
              {t('selectComplaint.combinedCounter', {
                count: cp(buildComplaintText(safeTextNames, customText)).length,
                max: TEXT_MAX,
              })}
            </span>
          </label>
          <textarea
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            maxLength={customMaxLen}
            aria-required={hasOther}
            placeholder={
              hasOther
                ? t('selectComplaint.otherPlaceholder')
                : t('selectComplaint.customPlaceholder', { name: safeNames })
            }
            className="input-base min-h-[80px] resize-y"
            rows={3}
          />
          {otherNeedsText && (
            <p className="mt-1 text-tiny text-red-500">{t('selectComplaint.otherRequired')}</p>
          )}
        </div>
      )}

      {/* 底部按鈕 */}
      <div className="sticky bottom-0 mt-8 border-t border-edge bg-surface-secondary/80 py-4 backdrop-blur-sm dark:border-dark-border dark:bg-dark-bg/80">
        <button
          className="btn-primary w-full py-3 text-body"
          disabled={selected.length === 0 || otherNeedsText}
          onClick={handleStart}
        >
          {selected.length > 0
            ? t('selectComplaint.ctaCount', { count: selected.length })
            : t('selectComplaint.cta')}
        </button>
      </div>
    </div>
  );
}
