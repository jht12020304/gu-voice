// =============================================================================
// 病史資料填寫頁 — 過敏史、目前用藥、過去病史、家族史（簡化版）
// 選擇主訴後、進入問診對話前的資料收集
// =============================================================================

import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import * as sessionsApi from '../../services/api/sessions';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

// ── 型別 ──

interface AllergyItem {
  allergen: string;
  hadHospitalization: boolean;
}

interface MedicalHistoryItem {
  condition: string;
  yearsAgo: string;
  stillHas: boolean;
}

interface MedicationItem {
  name: string;
  frequency: string;
}

interface FamilyHistoryItem {
  relation: string;
  condition: string;
}

// ── 常量 ──

const yearsAgoOptions = ['1年內', '1–5年', '5年以上', '不確定'];
const frequencyOptions = ['每日一次', '每日兩次', '每日三次', '需要時服用', '每週一次', '其他'];
const familyRelations = ['父親', '母親', '兄弟', '姊妹', '祖父', '祖母', '外祖父', '外祖母'];

const commonAllergies = ['盤尼西林', 'Aspirin', 'NSAID', 'Sulfa 類', '海鮮', '花生', '牛奶', '塵蟎', '花粉'];
const commonConditions = ['高血壓', '糖尿病', '心臟病', '中風', '腎臟病', '痛風', '攝護腺肥大', '泌尿道結石', '癌症'];

// ── 步驟 ──

type Step = 'critical' | 'history';

const steps: { key: Step; label: string }[] = [
  { key: 'critical', label: '過敏 & 用藥' },
  { key: 'history', label: '病史（選填）' },
];

// ── 輔助元件 ──

function QuickAddChips({ items, onAdd }: { items: string[]; onAdd: (item: string) => void }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <button
          key={item}
          type="button"
          className="rounded-pill bg-surface-tertiary px-3 py-1 text-small text-ink-secondary transition-colors hover:bg-surface-secondary hover:text-ink-heading dark:bg-dark-surface dark:text-white/50 dark:hover:bg-dark-hover dark:hover:text-white/80"
          onClick={() => onAdd(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}

function AddButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      className="mt-3 flex items-center gap-1.5 text-small font-medium text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300"
      onClick={onClick}
    >
      <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
      </svg>
      {label}
    </button>
  );
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="rounded-card p-1 text-ink-placeholder hover:text-red-500 transition-colors"
      onClick={onClick}
    >
      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  );
}

// ── 主元件 ──

type Gender = 'male' | 'female' | 'other';

export default function MedicalInfoPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const complaintId = searchParams.get('complaintId') || '';
  const complaintName = searchParams.get('complaintName') || '';
  const complaintText = searchParams.get('complaintText') || '';

  const [currentStep, setCurrentStep] = useState<Step>('critical');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [familyOpen, setFamilyOpen] = useState(false);
  const [showFieldErrors, setShowFieldErrors] = useState(false);

  // ── 基本資料 ──
  const [patientName, setPatientName] = useState('');
  const [gender, setGender] = useState<Gender | ''>('');
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [phone, setPhone] = useState('');

  // ── 資料狀態 ──
  const [allergies, setAllergies] = useState<AllergyItem[]>([]);
  const [noAllergies, setNoAllergies] = useState(false);
  const [medications, setMedications] = useState<MedicationItem[]>([]);
  const [noMedications, setNoMedications] = useState(false);
  const [history, setHistory] = useState<MedicalHistoryItem[]>([]);
  const [noHistory, setNoHistory] = useState(false);
  const [familyHistory, setFamilyHistory] = useState<FamilyHistoryItem[]>([]);

  const stepIndex = steps.findIndex((s) => s.key === currentStep);

  // ── Helpers ──
  const addAllergy = (name?: string) =>
    setAllergies([...allergies, { allergen: name || '', hadHospitalization: false }]);
  const removeAllergy = (i: number) => setAllergies(allergies.filter((_, idx) => idx !== i));
  const updateAllergy = (i: number, field: keyof AllergyItem, value: string | boolean) =>
    setAllergies(allergies.map((a, idx) => (idx === i ? { ...a, [field]: value } : a)));

  const addMedication = () => setMedications([...medications, { name: '', frequency: '每日一次' }]);
  const removeMedication = (i: number) => setMedications(medications.filter((_, idx) => idx !== i));
  const updateMedication = (i: number, field: keyof MedicationItem, value: string) =>
    setMedications(medications.map((m, idx) => (idx === i ? { ...m, [field]: value } : m)));

  const addHistory = (name?: string) =>
    setHistory([...history, { condition: name || '', yearsAgo: '不確定', stillHas: true }]);
  const removeHistory = (i: number) => setHistory(history.filter((_, idx) => idx !== i));
  const updateHistory = (i: number, field: keyof MedicalHistoryItem, value: string | boolean) =>
    setHistory(history.map((h, idx) => (idx === i ? { ...h, [field]: value } : h)));

  const addFamily = () => setFamilyHistory([...familyHistory, { relation: '父親', condition: '' }]);
  const removeFamily = (i: number) => setFamilyHistory(familyHistory.filter((_, idx) => idx !== i));
  const updateFamily = (i: number, field: keyof FamilyHistoryItem, value: string) =>
    setFamilyHistory(familyHistory.map((f, idx) => (idx === i ? { ...f, [field]: value } : f)));

  // ── 驗證 ──
  const trimmedName = patientName.trim();
  const trimmedPhone = phone.trim();
  const nameError = !trimmedName ? '請輸入姓名' : null;
  const genderError = !gender ? '請選擇性別' : null;
  const dobError = !dateOfBirth ? '請選擇出生日期' : null;
  const identityValid = !nameError && !genderError && !dobError;

  const handleNext = () => {
    if (!identityValid) {
      setShowFieldErrors(true);
      return;
    }
    setShowFieldErrors(false);
    setCurrentStep('history');
  };

  // ── 送出 ──
  const handleSubmit = async () => {
    if (!identityValid) {
      setShowFieldErrors(true);
      setCurrentStep('critical');
      return;
    }
    setIsCreating(true);
    setError(null);

    if (IS_MOCK) {
      setTimeout(() => navigate('/conversation/mock-new-session'), 600);
      return;
    }

    try {
      const session = await sessionsApi.createSession({
        chiefComplaintId: complaintId,
        chiefComplaintText: complaintText || complaintName,
        language: 'zh-TW',
        patientInfo: {
          name: trimmedName,
          gender: gender as Gender,
          dateOfBirth,
          phone: trimmedPhone ? trimmedPhone : null,
        },
        intake: {
          noKnownAllergies: noAllergies,
          allergies: noAllergies
            ? []
            : allergies
                .filter((item) => item.allergen.trim())
                .map((item) => ({
                  allergen: item.allergen.trim(),
                  reaction: item.hadHospitalization ? '曾就醫或急診' : undefined,
                  severity: item.hadHospitalization ? 'severe' : undefined,
                  hadHospitalization: item.hadHospitalization,
                })),
          noCurrentMedications: noMedications,
          currentMedications: noMedications
            ? []
            : medications
                .filter((item) => item.name.trim())
                .map((item) => ({
                  name: item.name.trim(),
                  frequency: item.frequency,
                })),
          noPastMedicalHistory: noHistory,
          medicalHistory: noHistory
            ? []
            : history
                .filter((item) => item.condition.trim())
                .map((item) => ({
                  condition: item.condition.trim(),
                  yearsAgo: item.yearsAgo,
                  stillHas: item.stillHas,
                })),
          familyHistory: familyHistory
            .filter((item) => item.condition.trim())
            .map((item) => ({
              relation: item.relation,
              condition: item.condition.trim(),
            })),
        },
      });
      navigate(`/conversation/${session.id}`);
    } catch {
      setError('建立問診失敗，請稍後再試');
      setIsCreating(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl px-6 py-8 animate-fade-in">

      {/* Header */}
      <div className="mb-6 flex items-center gap-3">
        <button
          className="rounded-card p-1.5 text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary transition-colors"
          onClick={() => navigate('/patient/start')}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="flex-1">
          <h1 className="text-h2 font-semibold tracking-tight text-ink-heading dark:text-white">填寫病史資料</h1>
          <p className="mt-0.5 text-small text-ink-muted dark:text-white/50">主訴：{complaintName || '未選擇'}</p>
        </div>
      </div>

      {/* 進度條 */}
      <div className="mb-6">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-tiny text-ink-muted dark:text-white/40">
            步驟 {stepIndex + 1} / {steps.length}
          </p>
          <p className="text-small font-medium text-ink-secondary dark:text-white/60">
            {steps[stepIndex].label}
          </p>
        </div>
        <div className="h-[3px] overflow-hidden rounded-full bg-surface-tertiary dark:bg-dark-surface">
          <div
            className="h-full rounded-full bg-primary-500 transition-all duration-300"
            style={{ width: `${((stepIndex + 1) / steps.length) * 100}%` }}
          />
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════
          Step 1: 過敏史 + 目前用藥
         ════════════════════════════════════════════════════════════ */}
      {currentStep === 'critical' && (
        <div className="space-y-4 animate-fade-in">

          {/* 基本資料 */}
          <div className="rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
            <div className="px-5 py-4 border-b border-edge/60 dark:border-dark-border">
              <h2 className="text-body font-semibold text-ink-heading dark:text-white">病患資料</h2>
              <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">本次問診的基本資料</p>
            </div>
            <div className="px-5 py-4 space-y-4">
              {/* 姓名 */}
              <div>
                <label className="mb-1.5 block text-small font-medium text-ink-secondary dark:text-white/70">
                  姓名 <span className="text-red-500">*</span>
                </label>
                <input
                  className="input-base w-full"
                  type="text"
                  maxLength={100}
                  placeholder="請輸入姓名"
                  value={patientName}
                  onChange={(e) => setPatientName(e.target.value)}
                />
                {showFieldErrors && nameError && (
                  <p className="mt-1 text-tiny text-red-500">{nameError}</p>
                )}
              </div>

              {/* 性別 */}
              <div>
                <label className="mb-1.5 block text-small font-medium text-ink-secondary dark:text-white/70">
                  性別 <span className="text-red-500">*</span>
                </label>
                <div className="flex flex-wrap gap-2">
                  {([
                    { value: 'male', label: '男' },
                    { value: 'female', label: '女' },
                    { value: 'other', label: '其他' },
                  ] as { value: Gender; label: string }[]).map((opt) => (
                    <label
                      key={opt.value}
                      className={`flex cursor-pointer items-center gap-2 rounded-pill border px-4 py-2 text-small transition-colors ${
                        gender === opt.value
                          ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-950 dark:text-primary-300'
                          : 'border-edge bg-surface-secondary/40 text-ink-secondary hover:bg-surface-tertiary dark:border-dark-border dark:bg-dark-surface/40 dark:text-white/60'
                      }`}
                    >
                      <input
                        type="radio"
                        name="gender"
                        value={opt.value}
                        checked={gender === opt.value}
                        onChange={() => setGender(opt.value)}
                        className="sr-only"
                      />
                      {opt.label}
                    </label>
                  ))}
                </div>
                {showFieldErrors && genderError && (
                  <p className="mt-1 text-tiny text-red-500">{genderError}</p>
                )}
              </div>

              {/* 出生日期 */}
              <div>
                <label className="mb-1.5 block text-small font-medium text-ink-secondary dark:text-white/70">
                  出生日期 <span className="text-red-500">*</span>
                </label>
                <input
                  className="input-base w-full"
                  type="date"
                  value={dateOfBirth}
                  onChange={(e) => setDateOfBirth(e.target.value)}
                />
                {showFieldErrors && dobError && (
                  <p className="mt-1 text-tiny text-red-500">{dobError}</p>
                )}
              </div>

              {/* 電話 */}
              <div>
                <label className="mb-1.5 block text-small font-medium text-ink-secondary dark:text-white/70">
                  電話 <span className="text-ink-placeholder">（選填）</span>
                </label>
                <input
                  className="input-base w-full"
                  type="tel"
                  maxLength={20}
                  placeholder="例：0912-345-678"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </div>
            </div>
          </div>

          {/* 過敏史 */}
          <div className="rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
            <div className="flex items-center justify-between px-5 py-4 border-b border-edge/60 dark:border-dark-border">
              <div>
                <h2 className="text-body font-semibold text-ink-heading dark:text-white">過敏史</h2>
                <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">藥物、食物或環境過敏</p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={noAllergies}
                  onChange={(e) => { setNoAllergies(e.target.checked); if (e.target.checked) setAllergies([]); }}
                  className="h-4 w-4 rounded border-edge text-primary-600 focus:ring-primary-500"
                />
                <span className="text-small text-ink-secondary dark:text-white/60">無過敏</span>
              </label>
            </div>

            {!noAllergies && (
              <div className="px-5 py-4 space-y-3">
                <div>
                  <p className="mb-2 text-tiny text-ink-muted dark:text-white/40">快速加入常見過敏原</p>
                  <QuickAddChips
                    items={commonAllergies.filter((a) => !allergies.some((al) => al.allergen === a))}
                    onAdd={(item) => addAllergy(item)}
                  />
                </div>

                {allergies.length > 0 && (
                  <div className="space-y-2 pt-1">
                    {allergies.map((allergy, i) => (
                      <div key={i} className="flex items-center gap-3 rounded-card border border-edge/60 bg-surface-secondary/40 px-4 py-3 dark:border-dark-border dark:bg-dark-surface/40">
                        <input
                          className="input-base flex-1"
                          placeholder="過敏原名稱"
                          value={allergy.allergen}
                          onChange={(e) => updateAllergy(i, 'allergen', e.target.value)}
                        />
                        <label className="flex shrink-0 items-center gap-1.5 cursor-pointer whitespace-nowrap">
                          <input
                            type="checkbox"
                            checked={allergy.hadHospitalization}
                            onChange={(e) => updateAllergy(i, 'hadHospitalization', e.target.checked)}
                            className="h-4 w-4 rounded border-edge text-red-500 focus:ring-red-400"
                          />
                          <span className="text-small text-ink-secondary dark:text-white/60">曾就醫或送急診</span>
                        </label>
                        <RemoveButton onClick={() => removeAllergy(i)} />
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={() => addAllergy()} label="新增過敏原" />
              </div>
            )}
          </div>

          {/* 目前用藥 */}
          <div className="rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
            <div className="flex items-center justify-between px-5 py-4 border-b border-edge/60 dark:border-dark-border">
              <div>
                <h2 className="text-body font-semibold text-ink-heading dark:text-white">目前用藥</h2>
                <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">目前正在服用的藥物，不需填寫劑量</p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={noMedications}
                  onChange={(e) => { setNoMedications(e.target.checked); if (e.target.checked) setMedications([]); }}
                  className="h-4 w-4 rounded border-edge text-primary-600 focus:ring-primary-500"
                />
                <span className="text-small text-ink-secondary dark:text-white/60">目前未服藥</span>
              </label>
            </div>

            {!noMedications && (
              <div className="px-5 py-4 space-y-3">
                {medications.length > 0 && (
                  <div className="space-y-2">
                    {medications.map((med, i) => (
                      <div key={i} className="flex items-center gap-3 rounded-card border border-edge/60 bg-surface-secondary/40 px-4 py-3 dark:border-dark-border dark:bg-dark-surface/40">
                        <input
                          className="input-base flex-1"
                          placeholder="藥物名稱（例：血壓藥、胃藥）"
                          value={med.name}
                          onChange={(e) => updateMedication(i, 'name', e.target.value)}
                        />
                        <select
                          className="input-base w-32 shrink-0"
                          value={med.frequency}
                          onChange={(e) => updateMedication(i, 'frequency', e.target.value)}
                        >
                          {frequencyOptions.map((f) => (
                            <option key={f} value={f}>{f}</option>
                          ))}
                        </select>
                        <RemoveButton onClick={() => removeMedication(i)} />
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={addMedication} label="新增藥物" />
              </div>
            )}
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════
          Step 2: 過去病史 + 家族史（選填）+ 確認送出
         ════════════════════════════════════════════════════════════ */}
      {currentStep === 'history' && (
        <div className="space-y-4 animate-fade-in">

          {/* 過去病史 */}
          <div className="rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
            <div className="flex items-center justify-between px-5 py-4 border-b border-edge/60 dark:border-dark-border">
              <div>
                <h2 className="text-body font-semibold text-ink-heading dark:text-white">過去病史</h2>
                <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">曾診斷過的疾病，可略過此步驟</p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={noHistory}
                  onChange={(e) => { setNoHistory(e.target.checked); if (e.target.checked) setHistory([]); }}
                  className="h-4 w-4 rounded border-edge text-primary-600 focus:ring-primary-500"
                />
                <span className="text-small text-ink-secondary dark:text-white/60">無重大病史</span>
              </label>
            </div>

            {!noHistory && (
              <div className="px-5 py-4 space-y-3">
                <div>
                  <p className="mb-2 text-tiny text-ink-muted dark:text-white/40">快速加入常見疾病</p>
                  <QuickAddChips
                    items={commonConditions.filter((c) => !history.some((h) => h.condition === c))}
                    onAdd={(item) => addHistory(item)}
                  />
                </div>

                {history.length > 0 && (
                  <div className="space-y-2 pt-1">
                    {history.map((h, i) => (
                      <div key={i} className="rounded-card border border-edge/60 bg-surface-secondary/40 px-4 py-3 dark:border-dark-border dark:bg-dark-surface/40">
                        <div className="flex items-start gap-3">
                          <div className="flex flex-1 flex-col gap-2">
                            <input
                              className="input-base"
                              placeholder="疾病名稱（例：高血壓）"
                              value={h.condition}
                              onChange={(e) => updateHistory(i, 'condition', e.target.value)}
                            />
                            <div className="flex items-center gap-4 flex-wrap">
                              <div className="flex items-center gap-2">
                                <span className="text-small text-ink-muted dark:text-white/40 whitespace-nowrap">大概幾年前</span>
                                <select
                                  className="input-base w-28"
                                  value={h.yearsAgo}
                                  onChange={(e) => updateHistory(i, 'yearsAgo', e.target.value)}
                                >
                                  {yearsAgoOptions.map((y) => (
                                    <option key={y} value={y}>{y}</option>
                                  ))}
                                </select>
                              </div>
                              <label className="flex items-center gap-1.5 cursor-pointer">
                                <input
                                  type="checkbox"
                                  checked={h.stillHas}
                                  onChange={(e) => updateHistory(i, 'stillHas', e.target.checked)}
                                  className="h-4 w-4 rounded border-edge text-primary-600 focus:ring-primary-500"
                                />
                                <span className="text-small text-ink-secondary dark:text-white/60 whitespace-nowrap">目前還有</span>
                              </label>
                            </div>
                          </div>
                          <RemoveButton onClick={() => removeHistory(i)} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={() => addHistory()} label="新增病史" />
              </div>
            )}
          </div>

          {/* 家族史（可摺疊） */}
          <div className="rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
            <button
              type="button"
              className="flex w-full items-center justify-between px-5 py-4 text-left"
              onClick={() => setFamilyOpen((v) => !v)}
            >
              <div className="flex items-center gap-2.5">
                <span className="text-body font-semibold text-ink-heading dark:text-white">家族病史</span>
                <span className="rounded-pill bg-surface-tertiary px-2 py-0.5 text-tiny text-ink-placeholder dark:bg-dark-surface dark:text-white/30">
                  選填
                </span>
              </div>
              <svg
                className={`h-4 w-4 text-ink-placeholder transition-transform duration-200 ${familyOpen ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            <div className={`transition-all duration-200 ease-in-out overflow-hidden ${familyOpen ? 'max-h-[1000px] opacity-100' : 'max-h-0 opacity-0'}`}>
              <div className="border-t border-edge/60 px-5 py-4 dark:border-dark-border">
                <p className="mb-3 text-small text-ink-muted dark:text-white/40">
                  直系親屬中有無遺傳性疾病？如不清楚可略過。
                </p>

                {familyHistory.length > 0 && (
                  <div className="mb-3 space-y-2">
                    {familyHistory.map((fh, i) => (
                      <div key={i} className="flex items-center gap-3 rounded-card border border-edge/60 bg-surface-secondary/40 px-4 py-3 dark:border-dark-border dark:bg-dark-surface/40">
                        <select
                          className="input-base w-24 shrink-0"
                          value={fh.relation}
                          onChange={(e) => updateFamily(i, 'relation', e.target.value)}
                        >
                          {familyRelations.map((r) => (
                            <option key={r} value={r}>{r}</option>
                          ))}
                        </select>
                        <input
                          className="input-base flex-1"
                          placeholder="疾病（例：糖尿病）"
                          value={fh.condition}
                          onChange={(e) => updateFamily(i, 'condition', e.target.value)}
                        />
                        <RemoveButton onClick={() => removeFamily(i)} />
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={addFamily} label="新增家族病史" />
              </div>
            </div>
          </div>

          {/* 資料摘要 */}
          <div className="rounded-panel border border-edge bg-surface-secondary/60 p-5 dark:border-dark-border dark:bg-dark-surface/40">
            <p className="mb-3 text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">確認送出的資料</p>
            <div className="space-y-2">
              {[
                { label: '主訴', value: complaintName },
                {
                  label: '過敏',
                  value: noAllergies || allergies.length === 0
                    ? '無已知過敏'
                    : allergies.map((a) => a.allergen).filter(Boolean).join('、') || '已填寫',
                },
                {
                  label: '用藥',
                  value: noMedications || medications.length === 0
                    ? '目前未服藥'
                    : medications.map((m) => m.name).filter(Boolean).join('、') || '已填寫',
                },
                {
                  label: '病史',
                  value: noHistory || history.length === 0
                    ? '無重大病史'
                    : history.map((h) => h.condition).filter(Boolean).join('、') || '已填寫',
                },
              ].map(({ label, value }) => (
                <div key={label} className="flex items-start gap-3">
                  <span className="w-10 shrink-0 text-small text-ink-muted dark:text-white/40">{label}</span>
                  <span className="text-small text-ink-body dark:text-white/70">{value}</span>
                </div>
              ))}
            </div>
          </div>

          {error && (
            <div className="rounded-card border border-alert-critical-border bg-alert-critical-bg px-4 py-3 text-body text-alert-critical-text">
              {error}
            </div>
          )}
        </div>
      )}

      {/* ── 底部導航 ── */}
      <div className="sticky bottom-0 mt-6 flex gap-3 border-t border-edge bg-surface-secondary/80 py-4 backdrop-blur-sm dark:border-dark-border dark:bg-dark-bg/80">
        {stepIndex > 0 ? (
          <button className="btn-secondary flex-1 py-3" onClick={() => setCurrentStep('critical')}>
            上一步
          </button>
        ) : (
          <button className="btn-secondary flex-1 py-3" onClick={() => navigate('/patient/start')}>
            返回
          </button>
        )}

        {currentStep === 'history' ? (
          <button
            className="btn-primary flex-1 py-3"
            onClick={handleSubmit}
            disabled={isCreating}
          >
            {isCreating ? (
              <span className="flex items-center justify-center gap-2">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                建立問診中…
              </span>
            ) : '開始 AI 問診'}
          </button>
        ) : (
          <button
            className="btn-primary flex-1 py-3"
            onClick={handleNext}
            disabled={!identityValid}
          >
            下一步
          </button>
        )}
      </div>
    </div>
  );
}
