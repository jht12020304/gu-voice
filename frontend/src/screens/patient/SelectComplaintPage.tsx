// =============================================================================
// 選擇主訴頁 — 病患選擇症狀後進入病史填寫
// =============================================================================

import { useEffect, useState } from 'react';
import { useLocalizedNavigate } from '../../i18n/paths';
import { useComplaintStore } from '../../stores/complaintStore';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import type { ChiefComplaint } from '../../types';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

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

function groupByCategory(complaints: ChiefComplaint[]): Record<string, ChiefComplaint[]> {
  return complaints.reduce<Record<string, ChiefComplaint[]>>((acc, c) => {
    if (!acc[c.category]) acc[c.category] = [];
    acc[c.category].push(c);
    return acc;
  }, {});
}

export default function SelectComplaintPage() {
  const navigate = useLocalizedNavigate();
  const { complaints, isLoading: storeLoading, fetchComplaints } = useComplaintStore();
  const [selected, setSelected] = useState<ChiefComplaint | null>(null);
  const [customText, setCustomText] = useState('');

  const displayComplaints = IS_MOCK ? mockComplaints : complaints;
  const isLoading = IS_MOCK ? false : storeLoading;

  useEffect(() => {
    if (!IS_MOCK) {
      fetchComplaints();
    }
  }, [fetchComplaints]);

  const grouped = groupByCategory(displayComplaints);

  const handleStart = () => {
    if (!selected) return;
    const params = new URLSearchParams({
      complaintId: selected.id,
      complaintName: selected.name,
      complaintText: customText || selected.name,
    });
    navigate(`/patient/medical-info?${params.toString()}`);
  };

  if (isLoading) return <LoadingSpinner fullPage message="載入症狀列表..." />;

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
          <h1 className="text-h2 font-semibold tracking-tight text-ink-heading dark:text-white">選擇您的症狀</h1>
          <p className="mt-0.5 text-body text-ink-muted dark:text-white/50">請選擇最符合您目前狀況的主訴</p>
        </div>
      </div>

      {/* 分類症狀 */}
      <div className="space-y-8">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            {/* 分類標題 — 純文字，無圖示 */}
            <h2 className="mb-3 text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">
              {category}
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
            補充說明（選填）
          </label>
          <textarea
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            placeholder={`請簡述您的「${selected.name}」症狀，例如：持續多久、嚴重程度…`}
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
          下一步：填寫病史
        </button>
      </div>
    </div>
  );
}
