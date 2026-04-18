// =============================================================================
// 病史資料填寫頁 — 過敏史、目前用藥、過去病史、家族史（簡化版）
// 選擇主訴後、進入問診對話前的資料收集
//
// 多語策略：
// - UI 字串、選項 label：走 `useTranslation('intake').medicalInfo.*`
// - 常數清單（relation / yearsAgo / frequency / commonAllergies / commonConditions）
//   以穩定 key 儲存、送出時用 `optionLabel(key)` 翻成當下語言
// - 送 API 時仍以 t() 結果為字串值（兼容後端舊 schema）；後端完成 intake
//   多語化後可改傳 key
// =============================================================================

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { useLocalizedNavigate } from '../../i18n/paths';
import { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../../i18n';
import * as sessionsApi from '../../services/api/sessions';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

// ── 型別 ──

interface AllergyItem {
  allergen: string;
  hadHospitalization: boolean;
}

interface MedicalHistoryItem {
  condition: string;
  yearsAgo: string; // 存成 key（within1 / oneToFive / ...）
  stillHas: boolean;
}

interface MedicationItem {
  name: string;
  frequency: string; // 存成 key（onceDaily / ...）
}

interface FamilyHistoryItem {
  relation: string; // 存成 key（father / mother / ...）
  condition: string;
}

// ── 常量（以 key 儲存；label 走 t() 翻譯） ──

const YEARS_AGO_KEYS = ['within1', 'oneToFive', 'overFive', 'unsure'] as const;
const FREQUENCY_KEYS = ['onceDaily', 'twiceDaily', 'thriceDaily', 'asNeeded', 'weekly', 'other'] as const;
const FAMILY_RELATION_KEYS = [
  'father', 'mother', 'brother', 'sister',
  'paternalGrandfather', 'paternalGrandmother',
  'maternalGrandfather', 'maternalGrandmother',
] as const;
const COMMON_ALLERGY_KEYS = [
  'penicillin', 'aspirin', 'nsaid', 'sulfa',
  'seafood', 'peanut', 'milk', 'dust', 'pollen',
] as const;
const COMMON_CONDITION_KEYS = [
  'hypertension', 'diabetes', 'heartDisease', 'stroke',
  'kidneyDisease', 'gout', 'bph', 'urinaryStones', 'cancer',
] as const;

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
type Step = 'critical' | 'history';

export default function MedicalInfoPage() {
  const navigate = useLocalizedNavigate();
  const { t, i18n } = useTranslation('intake');
  const [searchParams] = useSearchParams();

  const complaintId = searchParams.get('complaintId') || '';
  const complaintName = searchParams.get('complaintName') || '';
  const complaintText = searchParams.get('complaintText') || '';

  const steps: { key: Step; label: string }[] = [
    { key: 'critical', label: t('medicalInfo.steps.critical') },
    { key: 'history', label: t('medicalInfo.steps.history') },
  ];

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

  const addMedication = () => setMedications([...medications, { name: '', frequency: 'onceDaily' }]);
  const removeMedication = (i: number) => setMedications(medications.filter((_, idx) => idx !== i));
  const updateMedication = (i: number, field: keyof MedicationItem, value: string) =>
    setMedications(medications.map((m, idx) => (idx === i ? { ...m, [field]: value } : m)));

  const addHistory = (name?: string) =>
    setHistory([...history, { condition: name || '', yearsAgo: 'unsure', stillHas: true }]);
  const removeHistory = (i: number) => setHistory(history.filter((_, idx) => idx !== i));
  const updateHistory = (i: number, field: keyof MedicalHistoryItem, value: string | boolean) =>
    setHistory(history.map((h, idx) => (idx === i ? { ...h, [field]: value } : h)));

  const addFamily = () => setFamilyHistory([...familyHistory, { relation: 'father', condition: '' }]);
  const removeFamily = (i: number) => setFamilyHistory(familyHistory.filter((_, idx) => idx !== i));
  const updateFamily = (i: number, field: keyof FamilyHistoryItem, value: string) =>
    setFamilyHistory(familyHistory.map((f, idx) => (idx === i ? { ...f, [field]: value } : f)));

  // ── 驗證 ──
  const trimmedName = patientName.trim();
  const trimmedPhone = phone.trim();
  const nameError = !trimmedName ? t('medicalInfo.patient.nameError') : null;
  const genderError = !gender ? t('medicalInfo.patient.genderError') : null;
  const dobError = !dateOfBirth ? t('medicalInfo.patient.dobError') : null;
  const identityValid = !nameError && !genderError && !dobError;

  const handleNext = () => {
    if (!identityValid) {
      setShowFieldErrors(true);
      return;
    }
    setShowFieldErrors(false);
    setCurrentStep('history');
  };

  // 常用過敏原 / 疾病的 quick-add：translate 後回傳 label 清單
  const commonAllergyLabels = COMMON_ALLERGY_KEYS.map((k) => t(`medicalInfo.commonAllergies.${k}`));
  const commonConditionLabels = COMMON_CONDITION_KEYS.map((k) => t(`medicalInfo.commonConditions.${k}`));

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

    // 以當前 UI 語系建立 session，讓後端 WS 開場白與 session.language 一致。
    // 若 i18n.resolvedLanguage 意外落在支援清單之外，退回 zh-TW。
    const resolved = i18n.resolvedLanguage;
    const sessionLanguage: SupportedLanguage =
      resolved && (SUPPORTED_LANGUAGES as readonly string[]).includes(resolved)
        ? (resolved as SupportedLanguage)
        : 'zh-TW';

    try {
      const session = await sessionsApi.createSession({
        chiefComplaintId: complaintId,
        chiefComplaintText: complaintText || complaintName,
        language: sessionLanguage,
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
                  reaction: item.hadHospitalization ? t('medicalInfo.allergy.hospitalized') : undefined,
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
                  frequency: t(`medicalInfo.frequency.${item.frequency}`),
                })),
          noPastMedicalHistory: noHistory,
          medicalHistory: noHistory
            ? []
            : history
                .filter((item) => item.condition.trim())
                .map((item) => ({
                  condition: item.condition.trim(),
                  yearsAgo: t(`medicalInfo.yearsAgo.${item.yearsAgo}`),
                  stillHas: item.stillHas,
                })),
          familyHistory: familyHistory
            .filter((item) => item.condition.trim())
            .map((item) => ({
              relation: t(`medicalInfo.relations.${item.relation}`),
              condition: item.condition.trim(),
            })),
        },
      });
      navigate(`/conversation/${session.id}`);
    } catch {
      setError(t('medicalInfo.errors.createSession'));
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
          <h1 className="text-h2 font-semibold tracking-tight text-ink-heading dark:text-white">
            {t('medicalInfo.title')}
          </h1>
          <p className="mt-0.5 text-small text-ink-muted dark:text-white/50">
            {t('medicalInfo.complaintLabel', { name: complaintName || t('medicalInfo.complaintUnset') })}
          </p>
        </div>
      </div>

      {/* 進度條 */}
      <div className="mb-6">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-tiny text-ink-muted dark:text-white/40">
            {t('medicalInfo.stepProgress', { current: stepIndex + 1, total: steps.length })}
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
              <h2 className="text-body font-semibold text-ink-heading dark:text-white">
                {t('medicalInfo.patient.title')}
              </h2>
              <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">
                {t('medicalInfo.patient.subtitle')}
              </p>
            </div>
            <div className="px-5 py-4 space-y-4">
              {/* 姓名 */}
              <div>
                <label className="mb-1.5 block text-small font-medium text-ink-secondary dark:text-white/70">
                  {t('medicalInfo.patient.nameLabel')} <span className="text-red-500">{t('medicalInfo.patient.requiredMark')}</span>
                </label>
                <input
                  className="input-base w-full"
                  type="text"
                  maxLength={100}
                  placeholder={t('medicalInfo.patient.namePlaceholder')}
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
                  {t('medicalInfo.patient.genderLabel')} <span className="text-red-500">{t('medicalInfo.patient.requiredMark')}</span>
                </label>
                <div className="flex flex-wrap gap-2">
                  {([
                    { value: 'male', label: t('medicalInfo.patient.genderMale') },
                    { value: 'female', label: t('medicalInfo.patient.genderFemale') },
                    { value: 'other', label: t('medicalInfo.patient.genderOther') },
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
                  {t('medicalInfo.patient.dobLabel')} <span className="text-red-500">{t('medicalInfo.patient.requiredMark')}</span>
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
                  {t('medicalInfo.patient.phoneLabel')} <span className="text-ink-placeholder">{t('medicalInfo.patient.phoneOptional')}</span>
                </label>
                <input
                  className="input-base w-full"
                  type="tel"
                  maxLength={20}
                  placeholder={t('medicalInfo.patient.phonePlaceholder')}
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
                <h2 className="text-body font-semibold text-ink-heading dark:text-white">
                  {t('medicalInfo.allergy.title')}
                </h2>
                <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">
                  {t('medicalInfo.allergy.subtitle')}
                </p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={noAllergies}
                  onChange={(e) => { setNoAllergies(e.target.checked); if (e.target.checked) setAllergies([]); }}
                  className="h-4 w-4 rounded border-edge text-primary-600 focus:ring-primary-500"
                />
                <span className="text-small text-ink-secondary dark:text-white/60">{t('medicalInfo.allergy.noneLabel')}</span>
              </label>
            </div>

            {!noAllergies && (
              <div className="px-5 py-4 space-y-3">
                <div>
                  <p className="mb-2 text-tiny text-ink-muted dark:text-white/40">{t('medicalInfo.allergy.quickAddLabel')}</p>
                  <QuickAddChips
                    items={commonAllergyLabels.filter((a) => !allergies.some((al) => al.allergen === a))}
                    onAdd={(item) => addAllergy(item)}
                  />
                </div>

                {allergies.length > 0 && (
                  <div className="space-y-2 pt-1">
                    {allergies.map((allergy, i) => (
                      <div key={i} className="flex items-center gap-3 rounded-card border border-edge/60 bg-surface-secondary/40 px-4 py-3 dark:border-dark-border dark:bg-dark-surface/40">
                        <input
                          className="input-base flex-1"
                          placeholder={t('medicalInfo.allergy.placeholder')}
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
                          <span className="text-small text-ink-secondary dark:text-white/60">{t('medicalInfo.allergy.hospitalized')}</span>
                        </label>
                        <RemoveButton onClick={() => removeAllergy(i)} />
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={() => addAllergy()} label={t('medicalInfo.allergy.add')} />
              </div>
            )}
          </div>

          {/* 目前用藥 */}
          <div className="rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
            <div className="flex items-center justify-between px-5 py-4 border-b border-edge/60 dark:border-dark-border">
              <div>
                <h2 className="text-body font-semibold text-ink-heading dark:text-white">
                  {t('medicalInfo.medication.title')}
                </h2>
                <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">
                  {t('medicalInfo.medication.subtitle')}
                </p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={noMedications}
                  onChange={(e) => { setNoMedications(e.target.checked); if (e.target.checked) setMedications([]); }}
                  className="h-4 w-4 rounded border-edge text-primary-600 focus:ring-primary-500"
                />
                <span className="text-small text-ink-secondary dark:text-white/60">{t('medicalInfo.medication.noneLabel')}</span>
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
                          placeholder={t('medicalInfo.medication.placeholder')}
                          value={med.name}
                          onChange={(e) => updateMedication(i, 'name', e.target.value)}
                        />
                        <select
                          className="input-base w-32 shrink-0"
                          value={med.frequency}
                          onChange={(e) => updateMedication(i, 'frequency', e.target.value)}
                        >
                          {FREQUENCY_KEYS.map((k) => (
                            <option key={k} value={k}>{t(`medicalInfo.frequency.${k}`)}</option>
                          ))}
                        </select>
                        <RemoveButton onClick={() => removeMedication(i)} />
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={addMedication} label={t('medicalInfo.medication.add')} />
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
                <h2 className="text-body font-semibold text-ink-heading dark:text-white">
                  {t('medicalInfo.history.title')}
                </h2>
                <p className="mt-0.5 text-tiny text-ink-muted dark:text-white/40">
                  {t('medicalInfo.history.subtitle')}
                </p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={noHistory}
                  onChange={(e) => { setNoHistory(e.target.checked); if (e.target.checked) setHistory([]); }}
                  className="h-4 w-4 rounded border-edge text-primary-600 focus:ring-primary-500"
                />
                <span className="text-small text-ink-secondary dark:text-white/60">{t('medicalInfo.history.noneLabel')}</span>
              </label>
            </div>

            {!noHistory && (
              <div className="px-5 py-4 space-y-3">
                <div>
                  <p className="mb-2 text-tiny text-ink-muted dark:text-white/40">{t('medicalInfo.history.quickAddLabel')}</p>
                  <QuickAddChips
                    items={commonConditionLabels.filter((c) => !history.some((h) => h.condition === c))}
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
                              placeholder={t('medicalInfo.history.placeholder')}
                              value={h.condition}
                              onChange={(e) => updateHistory(i, 'condition', e.target.value)}
                            />
                            <div className="flex items-center gap-4 flex-wrap">
                              <div className="flex items-center gap-2">
                                <span className="text-small text-ink-muted dark:text-white/40 whitespace-nowrap">{t('medicalInfo.history.yearsAgoLabel')}</span>
                                <select
                                  className="input-base w-28"
                                  value={h.yearsAgo}
                                  onChange={(e) => updateHistory(i, 'yearsAgo', e.target.value)}
                                >
                                  {YEARS_AGO_KEYS.map((k) => (
                                    <option key={k} value={k}>{t(`medicalInfo.yearsAgo.${k}`)}</option>
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
                                <span className="text-small text-ink-secondary dark:text-white/60 whitespace-nowrap">{t('medicalInfo.history.stillHas')}</span>
                              </label>
                            </div>
                          </div>
                          <RemoveButton onClick={() => removeHistory(i)} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={() => addHistory()} label={t('medicalInfo.history.add')} />
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
                <span className="text-body font-semibold text-ink-heading dark:text-white">{t('medicalInfo.family.title')}</span>
                <span className="rounded-pill bg-surface-tertiary px-2 py-0.5 text-tiny text-ink-placeholder dark:bg-dark-surface dark:text-white/30">
                  {t('medicalInfo.family.optional')}
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
                  {t('medicalInfo.family.hint')}
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
                          {FAMILY_RELATION_KEYS.map((k) => (
                            <option key={k} value={k}>{t(`medicalInfo.relations.${k}`)}</option>
                          ))}
                        </select>
                        <input
                          className="input-base flex-1"
                          placeholder={t('medicalInfo.family.conditionPlaceholder')}
                          value={fh.condition}
                          onChange={(e) => updateFamily(i, 'condition', e.target.value)}
                        />
                        <RemoveButton onClick={() => removeFamily(i)} />
                      </div>
                    ))}
                  </div>
                )}

                <AddButton onClick={addFamily} label={t('medicalInfo.family.add')} />
              </div>
            </div>
          </div>

          {/* 資料摘要 */}
          <div className="rounded-panel border border-edge bg-surface-secondary/60 p-5 dark:border-dark-border dark:bg-dark-surface/40">
            <p className="mb-3 text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">{t('medicalInfo.summary.title')}</p>
            <div className="space-y-2">
              {[
                { label: t('medicalInfo.summary.complaint'), value: complaintName },
                {
                  label: t('medicalInfo.summary.allergy'),
                  value: noAllergies || allergies.length === 0
                    ? t('medicalInfo.summary.noKnownAllergies')
                    : allergies.map((a) => a.allergen).filter(Boolean).join(' / ') || t('medicalInfo.summary.filled'),
                },
                {
                  label: t('medicalInfo.summary.medication'),
                  value: noMedications || medications.length === 0
                    ? t('medicalInfo.summary.noCurrentMedications')
                    : medications.map((m) => m.name).filter(Boolean).join(' / ') || t('medicalInfo.summary.filled'),
                },
                {
                  label: t('medicalInfo.summary.history'),
                  value: noHistory || history.length === 0
                    ? t('medicalInfo.summary.noPastHistory')
                    : history.map((h) => h.condition).filter(Boolean).join(' / ') || t('medicalInfo.summary.filled'),
                },
              ].map(({ label, value }) => (
                <div key={label} className="flex items-start gap-3">
                  <span className="w-16 shrink-0 text-small text-ink-muted dark:text-white/40">{label}</span>
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
            {t('medicalInfo.nav.prev')}
          </button>
        ) : (
          <button className="btn-secondary flex-1 py-3" onClick={() => navigate('/patient/start')}>
            {t('medicalInfo.nav.back')}
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
                {t('medicalInfo.nav.submitting')}
              </span>
            ) : t('medicalInfo.nav.submit')}
          </button>
        ) : (
          <button
            className="btn-primary flex-1 py-3"
            onClick={handleNext}
            disabled={!identityValid}
          >
            {t('medicalInfo.nav.next')}
          </button>
        )}
      </div>
    </div>
  );
}
