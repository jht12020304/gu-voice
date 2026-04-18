// =============================================================================
// SOAP 報告區塊卡片 — 結構化醫學報告渲染
// 設計語言：Stripe 精準 × 醫療級可讀性 × 最小色彩原則
// =============================================================================

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type {
  SOAPSubjective,
  SOAPObjective,
  SOAPAssessment,
  SOAPPlan,
  LabResult,
  DifferentialDiagnosis,
  RecommendedTest,
  Treatment,
} from '../../types';

// ── AI 原始輸出正規化（處理型別不一致）─────────────────────
function toStrArr(v: unknown): string[] {
  if (!v) return [];
  if (Array.isArray(v)) return (v as unknown[]).map(String).filter(Boolean);
  if (typeof v === 'string') return v.trim() ? [v] : [];
  return [];
}

function normalizeSubjective(raw: Record<string, unknown>): SOAPSubjective {
  const hpiRaw = (raw.hpi ?? {}) as Record<string, unknown>;
  return {
    chiefComplaint: String(raw.chiefComplaint ?? raw.chief_complaint ?? ''),
    hpi: {
      onset:              String(hpiRaw.onset ?? ''),
      location:           String(hpiRaw.location ?? ''),
      duration:           String(hpiRaw.duration ?? ''),
      characteristics:    String(hpiRaw.characteristics ?? ''),
      severity:           String(hpiRaw.severity ?? ''),
      aggravatingFactors: toStrArr(hpiRaw.aggravatingFactors ?? hpiRaw.aggravating_factors),
      relievingFactors:   toStrArr(hpiRaw.relievingFactors ?? hpiRaw.relieving_factors),
      associatedSymptoms: toStrArr(hpiRaw.associatedSymptoms ?? hpiRaw.associated_symptoms),
      timing:             String(hpiRaw.timing ?? ''),
      context:            String(hpiRaw.context ?? ''),
    },
    pastMedicalHistory: (() => {
      const pmh = raw.pastMedicalHistory ?? raw.past_medical_history;
      if (pmh && typeof pmh === 'object' && !Array.isArray(pmh)) {
        const p = pmh as Record<string, unknown>;
        return { conditions: toStrArr(p.conditions), surgeries: toStrArr(p.surgeries), hospitalizations: toStrArr(p.hospitalizations) };
      }
      return { conditions: toStrArr(pmh), surgeries: [], hospitalizations: [] };
    })(),
    medicationHistory: (() => {
      const mh = raw.medicationHistory ?? raw.medication_history ?? raw.medications;
      if (mh && typeof mh === 'object' && !Array.isArray(mh)) {
        const m = mh as Record<string, unknown>;
        return { current: toStrArr(m.current), past: toStrArr(m.past), otc: toStrArr(m.otc) };
      }
      return { current: toStrArr(mh), past: [], otc: [] };
    })(),
    systemReview: (() => {
      const sr = raw.systemReview ?? raw.system_review ?? raw.reviewOfSystems ?? raw.review_of_systems;
      if (sr && typeof sr === 'object' && !Array.isArray(sr)) return sr as Record<string, string>;
      return {};
    })(),
    socialHistory: (() => {
      const sh = raw.socialHistory ?? raw.social_history;
      if (sh && typeof sh === 'object' && !Array.isArray(sh)) return sh as Record<string, string>;
      return {};
    })(),
  };
}

function normalizeObjective(raw: Record<string, unknown>): SOAPObjective {
  const vs = raw.vitalSigns;
  const pe = raw.physicalExam;
  return {
    // Only pass vitalSigns if it's a proper object (not a placeholder string)
    vitalSigns: (vs && typeof vs === 'object' && !Array.isArray(vs))
      ? vs as SOAPObjective['vitalSigns']
      : undefined,
    // Only pass physicalExam if it's a proper object
    physicalExam: (pe && typeof pe === 'object' && !Array.isArray(pe))
      ? pe as Record<string, string>
      : undefined,
    labResults: Array.isArray(raw.labResults) ? raw.labResults as LabResult[] : undefined,
  };
}

function normalizeAssessment(raw: Record<string, unknown>): SOAPAssessment {
  const dxRaw = Array.isArray(raw.differentialDiagnoses) ? raw.differentialDiagnoses : [];
  return {
    clinicalImpression: String(raw.clinicalImpression ?? ''),
    differentialDiagnoses: (dxRaw as Record<string, unknown>[]).map((dx) => ({
      diagnosis: String(dx.diagnosis ?? ''),
      icd10:     String(dx.icd10 ?? ''),
      // AI returns 'likelihood' (high/moderate/low); frontend uses 'probability' (high/medium/low)
      probability: (() => {
        const raw_p = String(dx.probability ?? dx.likelihood ?? 'low');
        return (raw_p === 'moderate' ? 'medium' : raw_p) as DifferentialDiagnosis['probability'];
      })(),
      reasoning: String(dx.reasoning ?? ''),
    })),
  };
}

function normalizePlan(raw: Record<string, unknown>): SOAPPlan {
  const testsRaw = Array.isArray(raw.recommendedTests) ? raw.recommendedTests : [];
  const txRaw = Array.isArray(raw.treatments) ? raw.treatments : [];
  const fuRaw = raw.followUp;

  return {
    recommendedTests: (testsRaw as Record<string, unknown>[]).map((t) => ({
      testName:        String(t.testName ?? t.test_name ?? t),
      rationale:       String(t.rationale ?? ''),
      urgency:         (String(t.urgency ?? 'routine')) as RecommendedTest['urgency'],
      clinicalReasoning: t.clinicalReasoning ? String(t.clinicalReasoning) : undefined,
    })),
    treatments: (txRaw as unknown[]).map((t): Treatment => {
      if (typeof t === 'string') return { type: '其他', name: t, instruction: '' };
      const tx = t as Record<string, unknown>;
      return { type: String(tx.type ?? ''), name: String(tx.name ?? ''), instruction: String(tx.instruction ?? ''), note: tx.note ? String(tx.note) : undefined };
    }),
    followUp: (() => {
      if (fuRaw && typeof fuRaw === 'object' && !Array.isArray(fuRaw)) {
        const f = fuRaw as Record<string, unknown>;
        return { interval: String(f.interval ?? ''), reason: String(f.reason ?? ''), additionalNotes: f.additionalNotes ? String(f.additionalNotes) : undefined };
      }
      return { interval: String(fuRaw ?? ''), reason: '' };
    })(),
    referrals:        toStrArr(raw.referrals),
    patientEducation: toStrArr(raw.patientEducation ?? raw.patient_education),
    diagnosticReasoning: raw.diagnosticReasoning ? String(raw.diagnosticReasoning) : undefined,
  };
}

interface SOAPCardProps {
  section: 'subjective' | 'objective' | 'assessment' | 'plan';
  content: Record<string, unknown> | null | undefined;
}

// i18n t() 型別快捷：SOAPCard 永遠用 'soap' namespace
type SoapT = TFunction<'soap'>;

const sectionMeta: Record<string, {
  letter: string;
  accent: string;
  badge: string;
}> = {
  subjective: {
    letter: 'S',
    accent: 'bg-indigo-400 dark:bg-indigo-500',
    badge: 'bg-indigo-50 text-indigo-600 ring-1 ring-indigo-500/15 dark:bg-indigo-500/10 dark:text-indigo-400 dark:ring-indigo-400/20',
  },
  objective: {
    letter: 'O',
    accent: 'bg-teal-400 dark:bg-teal-500',
    badge: 'bg-teal-50 text-teal-600 ring-1 ring-teal-500/15 dark:bg-teal-500/10 dark:text-teal-400 dark:ring-teal-400/20',
  },
  assessment: {
    letter: 'A',
    accent: 'bg-amber-400 dark:bg-amber-500',
    badge: 'bg-amber-50 text-amber-700 ring-1 ring-amber-500/15 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-400/20',
  },
  plan: {
    letter: 'P',
    accent: 'bg-violet-400 dark:bg-violet-500',
    badge: 'bg-violet-50 text-violet-600 ring-1 ring-violet-500/15 dark:bg-violet-500/10 dark:text-violet-400 dark:ring-violet-400/20',
  },
};

// ── 共用小元件 ────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="mb-1.5 text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/50">
      {children}
    </h4>
  );
}

function SubLabel({ children }: { children: React.ReactNode }) {
  return <span className="text-small font-medium text-ink-placeholder dark:text-white/40">{children}</span>;
}

function FieldGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-5 gap-y-2 sm:grid-cols-3">{children}</div>;
}

function FieldItem({ label, value }: { label: string; value: React.ReactNode }) {
  if (!value || value === '-' || (typeof value === 'string' && !value.trim())) return null;
  return (
    <div>
      <SubLabel>{label}</SubLabel>
      <p className="mt-0.5 text-body-lg text-ink-body dark:text-white/85">{value}</p>
    </div>
  );
}

function TagList({ items, noneLabel }: { items: string[]; noneLabel: string }) {
  // 注意：AI 輸出的中文字面值「無」是資料側慣例，不屬於 UI label
  const filtered = items.filter((s) => s && s !== '無');
  if (filtered.length === 0) return <span className="text-body text-ink-placeholder">{noneLabel}</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {filtered.map((item, i) => (
        <span
          key={i}
          className="rounded-pill border border-edge bg-white px-2 py-0.5 text-body text-ink-body dark:border-dark-border dark:bg-dark-card dark:text-white/75"
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function Divider() {
  return <div className="border-t border-edge/60 dark:border-dark-border" />;
}

function Callout({ children, border = 'border-l-edge-hover dark:border-l-dark-border' }: {
  children: React.ReactNode;
  border?: string;
}) {
  return (
    <div className={`rounded-card bg-surface-secondary/60 border-l-2 px-3.5 py-2.5 dark:bg-dark-surface/60 ${border}`}>
      {children}
    </div>
  );
}

// 將動態 key（systemReview / socialHistory / physicalExam）解析為顯示標籤：
// 先查 i18n fieldLabels.*，若該 key 未納入則回退為原始 key（常見於 API 新增欄位）
function resolveFieldLabel(t: SoapT, key: string): string {
  const translated = t(`fieldLabels.${key}`, { defaultValue: key });
  return translated;
}

// ── S 主觀 ────────────────────────────────────────────────

function SubjectiveContent({ data, t }: { data: SOAPSubjective; t: SoapT }) {
  const { chiefComplaint, hpi, pastMedicalHistory: pmh, medicationHistory: meds, systemReview, socialHistory } = data;
  const noneLabel = t('common.none');
  return (
    <div className="space-y-3.5">
      <Callout border="border-l-indigo-300 dark:border-l-indigo-600">
        <SubLabel>{t('subjective.chiefComplaint')}</SubLabel>
        <p className="mt-0.5 text-h3 font-medium text-ink-heading dark:text-white">{chiefComplaint}</p>
      </Callout>

      {hpi && (
        <div>
          <SectionLabel>{t('subjective.hpi.title')}</SectionLabel>
          <FieldGrid>
            <FieldItem label={t('subjective.hpi.onset')} value={hpi.onset} />
            <FieldItem label={t('subjective.hpi.location')} value={hpi.location} />
            <FieldItem label={t('subjective.hpi.duration')} value={hpi.duration} />
            <FieldItem label={t('subjective.hpi.severity')} value={hpi.severity} />
            <FieldItem label={t('subjective.hpi.timing')} value={hpi.timing} />
            <FieldItem label={t('subjective.hpi.context')} value={hpi.context} />
          </FieldGrid>
          {hpi.characteristics && (
            <div className="mt-2">
              <SubLabel>{t('subjective.hpi.characteristics')}</SubLabel>
              <p className="mt-0.5 text-body-lg text-ink-body dark:text-white/85">{hpi.characteristics}</p>
            </div>
          )}
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div>
              <SubLabel>{t('subjective.hpi.aggravatingFactors')}</SubLabel>
              <div className="mt-1"><TagList items={hpi.aggravatingFactors ?? []} noneLabel={noneLabel} /></div>
            </div>
            <div>
              <SubLabel>{t('subjective.hpi.relievingFactors')}</SubLabel>
              <div className="mt-1"><TagList items={hpi.relievingFactors ?? []} noneLabel={noneLabel} /></div>
            </div>
            <div>
              <SubLabel>{t('subjective.hpi.associatedSymptoms')}</SubLabel>
              <div className="mt-1"><TagList items={hpi.associatedSymptoms ?? []} noneLabel={noneLabel} /></div>
            </div>
          </div>
        </div>
      )}

      <Divider />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {pmh && (
          <div>
            <SectionLabel>{t('subjective.pastMedicalHistory.title')}</SectionLabel>
            <div className="space-y-1.5">
              <div><SubLabel>{t('subjective.pastMedicalHistory.conditions')}</SubLabel><div className="mt-0.5"><TagList items={pmh.conditions ?? []} noneLabel={noneLabel} /></div></div>
              <div><SubLabel>{t('subjective.pastMedicalHistory.surgeries')}</SubLabel><div className="mt-0.5"><TagList items={pmh.surgeries ?? []} noneLabel={noneLabel} /></div></div>
              <div><SubLabel>{t('subjective.pastMedicalHistory.hospitalizations')}</SubLabel><div className="mt-0.5"><TagList items={pmh.hospitalizations ?? []} noneLabel={noneLabel} /></div></div>
            </div>
          </div>
        )}
        {meds && (
          <div>
            <SectionLabel>{t('subjective.medicationHistory.title')}</SectionLabel>
            <div className="space-y-1.5">
              <div><SubLabel>{t('subjective.medicationHistory.current')}</SubLabel><div className="mt-0.5"><TagList items={meds.current ?? []} noneLabel={noneLabel} /></div></div>
              {(meds.past?.length ?? 0) > 0 && <div><SubLabel>{t('subjective.medicationHistory.past')}</SubLabel><div className="mt-0.5"><TagList items={meds.past} noneLabel={noneLabel} /></div></div>}
              {(meds.otc?.length ?? 0) > 0 && <div><SubLabel>{t('subjective.medicationHistory.otc')}</SubLabel><div className="mt-0.5"><TagList items={meds.otc} noneLabel={noneLabel} /></div></div>}
            </div>
          </div>
        )}
      </div>

      {(systemReview || socialHistory) && (
        <>
          <Divider />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {systemReview && Object.keys(systemReview).length > 0 && (
              <div>
                <SectionLabel>{t('subjective.systemReview.title')}</SectionLabel>
                <FieldGrid>
                  {Object.entries(systemReview).map(([key, val]) => (
                    <FieldItem key={key} label={resolveFieldLabel(t, key)} value={val} />
                  ))}
                </FieldGrid>
              </div>
            )}
            {socialHistory && Object.keys(socialHistory).length > 0 && (
              <div>
                <SectionLabel>{t('subjective.socialHistory.title')}</SectionLabel>
                <FieldGrid>
                  {Object.entries(socialHistory).map(([key, val]) => (
                    <FieldItem key={key} label={resolveFieldLabel(t, key)} value={val} />
                  ))}
                </FieldGrid>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── O 客觀 ────────────────────────────────────────────────

const VITAL_KEYS = ['bloodPressure', 'heartRate', 'respiratoryRate', 'temperature', 'spo2'] as const;

function ObjectiveContent({ data, t }: { data: SOAPObjective; t: SoapT }) {
  const { vitalSigns, physicalExam, labResults } = data;
  return (
    <div className="space-y-3.5">
      {vitalSigns && (
        <div>
          <SectionLabel>{t('objective.vitalSigns.title')}</SectionLabel>
          <div className="grid grid-cols-3 gap-2 lg:grid-cols-5">
            {Object.entries(vitalSigns).map(([key, val]) => {
              if (val === undefined || val === null) return null;
              const isKnown = (VITAL_KEYS as readonly string[]).includes(key);
              const label = isKnown ? t(`objective.vitalSigns.labels.${key}`) : key;
              const unit  = isKnown ? t(`objective.vitalSigns.units.${key}`)  : '';
              return (
                <div
                  key={key}
                  className="rounded-card border border-edge bg-white px-2.5 py-2 text-center dark:border-dark-border dark:bg-dark-card"
                >
                  <p className="text-small font-medium text-ink-placeholder dark:text-white/40">{label}</p>
                  <p className="text-h3 font-semibold font-tnum text-ink-heading dark:text-white">{val}</p>
                  <p className="text-small text-ink-placeholder dark:text-white/30">{unit}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {physicalExam && Object.keys(physicalExam).length > 0 && (
        <div>
          <SectionLabel>{t('objective.physicalExam.title')}</SectionLabel>
          <div className="overflow-hidden rounded-card border border-edge dark:border-dark-border">
            {Object.entries(physicalExam).map(([key, val], i) => (
              <div
                key={key}
                className={`flex items-start gap-3 px-3.5 py-2 ${i > 0 ? 'border-t border-edge/60 dark:border-dark-border' : ''}`}
              >
                <span className="w-20 shrink-0 text-body font-medium text-ink-muted dark:text-white/50">{resolveFieldLabel(t, key)}</span>
                <span className="text-body-lg text-ink-body dark:text-white/85">{val}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {labResults && labResults.length > 0 && (
        <div>
          <SectionLabel>{t('objective.labResults.title')}</SectionLabel>
          <div className="overflow-hidden rounded-card border border-edge dark:border-dark-border">
            <table className="w-full">
              <thead>
                <tr className="bg-surface-secondary dark:bg-dark-surface">
                  <th className="px-3.5 py-2 text-left text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">{t('objective.labResults.columns.test')}</th>
                  <th className="px-3.5 py-2 text-left text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">{t('objective.labResults.columns.result')}</th>
                  <th className="px-3.5 py-2 text-left text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">{t('objective.labResults.columns.reference')}</th>
                  <th className="px-3.5 py-2 text-center text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">{t('objective.labResults.columns.status')}</th>
                </tr>
              </thead>
              <tbody>
                {(labResults as LabResult[]).map((lab, i) => (
                  <tr key={i} className="border-t border-edge/60 dark:border-dark-border">
                    <td className="px-3.5 py-2 text-body-lg font-medium text-ink-heading dark:text-white">{lab.testName}</td>
                    <td className={`px-3.5 py-2 font-data text-body-lg ${lab.isAbnormal ? 'font-semibold text-red-600 dark:text-red-400' : 'text-ink-body dark:text-white/80'}`}>
                      {lab.result}
                    </td>
                    <td className="px-3.5 py-2 font-data text-body text-ink-placeholder dark:text-white/40">{lab.referenceRange}</td>
                    <td className="px-3.5 py-2 text-center">
                      {lab.isAbnormal ? (
                        <span className="inline-flex items-center gap-1 rounded-pill bg-red-50 px-2 py-0.5 text-small font-semibold text-red-600 ring-1 ring-red-500/15 dark:bg-red-500/10 dark:text-red-400 dark:ring-red-400/20">
                          <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                          {t('common.abnormal')}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-pill bg-surface-tertiary px-2 py-0.5 text-small font-medium text-ink-muted dark:bg-dark-border dark:text-white/50">
                          {t('common.normal')}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── A 評估 ────────────────────────────────────────────────

const probConfig: Record<string, { dot: string; text: string; bg: string }> = {
  high:   { dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 ring-1 ring-red-500/15 dark:bg-red-500/10 dark:ring-red-400/20' },
  medium: { dot: 'bg-amber-500', text: 'text-amber-700 dark:text-amber-400', bg: 'bg-amber-50 ring-1 ring-amber-500/15 dark:bg-amber-500/10 dark:ring-amber-400/20' },
  low:    { dot: 'bg-slate-400', text: 'text-ink-muted dark:text-white/50', bg: 'bg-surface-tertiary ring-1 ring-edge dark:bg-dark-border dark:ring-dark-border' },
};

function AssessmentContent({ data, t }: { data: SOAPAssessment; t: SoapT }) {
  const { differentialDiagnoses, clinicalImpression } = data;
  return (
    <div className="space-y-3.5">
      {clinicalImpression && (
        <Callout border="border-l-amber-300 dark:border-l-amber-600">
          <SubLabel>{t('assessment.clinicalImpression')}</SubLabel>
          <p className="mt-0.5 text-body-lg font-medium text-ink-heading dark:text-white">{clinicalImpression}</p>
        </Callout>
      )}

      {differentialDiagnoses && differentialDiagnoses.length > 0 && (
        <div>
          <SectionLabel>{t('assessment.differentialDiagnoses.title')}</SectionLabel>
          <div className="space-y-2">
            {(differentialDiagnoses as DifferentialDiagnosis[]).map((dx, i) => {
              const p = probConfig[dx.probability] || probConfig.low;
              const probLabel = t(`assessment.probability.${dx.probability}`, { defaultValue: dx.probability });
              return (
                <div key={i} className="rounded-card border border-edge px-3.5 py-2.5 dark:border-dark-border">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-tertiary font-data text-body font-semibold text-ink-muted dark:bg-dark-border dark:text-white/50">
                        {i + 1}
                      </span>
                      <div>
                        <p className="text-body-lg font-semibold text-ink-heading dark:text-white">{dx.diagnosis}</p>
                        <span className="font-data text-body text-ink-placeholder">{dx.icd10}</span>
                      </div>
                    </div>
                    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-pill px-2 py-0.5 text-small font-semibold ${p.bg} ${p.text}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${p.dot}`} />
                      {probLabel}
                    </span>
                  </div>
                  {dx.reasoning && (
                    <p className="mt-1.5 ml-8.5 text-body leading-relaxed text-ink-secondary dark:text-white/60">{dx.reasoning}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── P 計畫 ────────────────────────────────────────────────

const urgConfig: Record<string, { cls: string }> = {
  urgent:   { cls: 'bg-red-50 text-red-600 ring-1 ring-red-500/15 dark:bg-red-500/10 dark:text-red-400 dark:ring-red-400/20' },
  routine:  { cls: 'bg-surface-tertiary text-ink-muted ring-1 ring-edge dark:bg-dark-border dark:text-white/50 dark:ring-dark-border' },
  elective: { cls: 'bg-surface-tertiary text-ink-placeholder ring-1 ring-edge dark:bg-dark-border dark:text-white/40 dark:ring-dark-border' },
};

function PlanContent({ data, t }: { data: SOAPPlan; t: SoapT }) {
  const { recommendedTests, treatments, followUp, referrals, patientEducation, diagnosticReasoning } = data;
  const [expandedTests, setExpandedTests] = useState<Record<number, boolean>>({});
  const toggleTest = (i: number) => setExpandedTests((prev) => ({ ...prev, [i]: !prev[i] }));
  const noneLabel = t('common.none');

  return (
    <div className="space-y-3.5">
      {diagnosticReasoning && (
        <Callout border="border-l-violet-300 dark:border-l-violet-600">
          <div className="flex items-start gap-2">
            <svg className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted dark:text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <div>
              <p className="text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/50 mb-0.5">{t('plan.diagnosticReasoning')}</p>
              <p className="text-body-lg leading-relaxed text-ink-body dark:text-white/80">{diagnosticReasoning}</p>
            </div>
          </div>
        </Callout>
      )}

      {recommendedTests && recommendedTests.length > 0 && (
        <div>
          <SectionLabel>{t('plan.recommendedTests.title')}</SectionLabel>
          <div className="space-y-1.5">
            {(recommendedTests as RecommendedTest[]).map((test, i) => {
              const u = urgConfig[test.urgency] || urgConfig.routine;
              const urgencyLabel = t(`plan.urgency.${test.urgency}`, { defaultValue: test.urgency });
              const isExpanded = expandedTests[i];
              const hasReasoning = !!test.clinicalReasoning;
              return (
                <div key={i} className="overflow-hidden rounded-card border border-edge dark:border-dark-border">
                  <div
                    className={`flex items-center gap-2.5 px-3.5 py-2.5 ${hasReasoning ? 'cursor-pointer hover:bg-surface-secondary/40 dark:hover:bg-dark-surface/40 transition-colors' : ''}`}
                    onClick={() => hasReasoning && toggleTest(i)}
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-tertiary font-data text-body font-semibold text-ink-muted dark:bg-dark-border dark:text-white/50">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="text-body-lg font-semibold text-ink-heading dark:text-white">{test.testName}</p>
                        <span className={`rounded-pill px-2 py-0.5 text-small font-semibold ${u.cls}`}>{urgencyLabel}</span>
                      </div>
                      {test.rationale && (
                        <p className="text-body text-ink-secondary dark:text-white/60">{test.rationale}</p>
                      )}
                    </div>
                    {hasReasoning && (
                      <svg
                        className={`h-4 w-4 shrink-0 text-ink-placeholder transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                        fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                      </svg>
                    )}
                  </div>
                  {isExpanded && test.clinicalReasoning && (
                    <div className="border-t border-edge/60 bg-surface-secondary/30 px-3.5 py-2.5 dark:border-dark-border dark:bg-dark-surface/30">
                      <p className="text-body leading-relaxed text-ink-secondary dark:text-white/65">{test.clinicalReasoning}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {treatments && treatments.length > 0 && (
        <div>
          <SectionLabel>{t('plan.treatments.title')}</SectionLabel>
          <div className="space-y-1.5">
            {(treatments as Treatment[]).map((tx, i) => (
              <div key={i} className="flex items-start gap-2.5 rounded-card border border-edge px-3.5 py-2.5 dark:border-dark-border">
                <span className="mt-0.5 rounded-pill border border-edge bg-surface-tertiary px-2 py-0.5 text-small font-semibold text-ink-secondary dark:border-dark-border dark:bg-dark-border dark:text-white/60">
                  {tx.type}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-body-lg font-semibold text-ink-heading dark:text-white">{tx.name}</p>
                  <p className="text-body text-ink-secondary dark:text-white/60">{tx.instruction}</p>
                  {tx.note && <p className="mt-0.5 text-body italic text-ink-placeholder">{tx.note}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {followUp && (
        <div>
          <SectionLabel>{t('plan.followUp.title')}</SectionLabel>
          <div className="rounded-card border border-edge px-3.5 py-2.5 dark:border-dark-border">
            <FieldGrid>
              <FieldItem label={t('plan.followUp.interval')} value={followUp.interval} />
              <FieldItem label={t('plan.followUp.reason')} value={followUp.reason} />
            </FieldGrid>
            {followUp.additionalNotes && (
              <p className="mt-1.5 text-body italic text-ink-muted dark:text-white/50">{followUp.additionalNotes}</p>
            )}
          </div>
        </div>
      )}

      {referrals && referrals.length > 0 && (
        <div>
          <SectionLabel>{t('plan.referrals.title')}</SectionLabel>
          <TagList items={referrals} noneLabel={noneLabel} />
        </div>
      )}

      {patientEducation && patientEducation.length > 0 && (
        <div>
          <SectionLabel>{t('plan.patientEducation.title')}</SectionLabel>
          <ul className="space-y-1">
            {patientEducation.map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-body-lg text-ink-body dark:text-white/85">
                <svg className="mt-0.5 h-4 w-4 shrink-0 text-ink-placeholder dark:text-white/30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── 主元件 ────────────────────────────────────────────────

export default function SOAPCard({ section, content }: SOAPCardProps) {
  const { t } = useTranslation('soap');
  const meta = sectionMeta[section];
  const [collapsed, setCollapsed] = useState(false);

  const renderContent = () => {
    if (!content) return <p className="py-2 text-center text-body-lg text-ink-placeholder">{t('common.empty')}</p>;
    switch (section) {
      case 'subjective':  return <SubjectiveContent data={normalizeSubjective(content)} t={t} />;
      case 'objective':   return <ObjectiveContent data={normalizeObjective(content)} t={t} />;
      case 'assessment':  return <AssessmentContent data={normalizeAssessment(content)} t={t} />;
      case 'plan':        return <PlanContent data={normalizePlan(content)} t={t} />;
      default:            return null;
    }
  };

  return (
    <div className="overflow-hidden rounded-card border border-edge bg-white shadow-card transition-shadow duration-200 hover:shadow-card-hover dark:border-dark-border dark:bg-dark-card">
      <div className={`h-[3px] ${meta.accent}`} />

      <button
        type="button"
        className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-surface-secondary/40 dark:hover:bg-dark-surface/40"
        onClick={() => setCollapsed((prev) => !prev)}
      >
        <span className={`flex h-7 w-7 items-center justify-center rounded-lg font-mono text-body font-bold ${meta.badge}`}>
          {meta.letter}
        </span>
        <h3 className="flex-1 text-h3 font-semibold tracking-tight text-ink-heading dark:text-white">
          {t(`section.${section}.title`)}
          <span className="ml-1.5 text-caption font-normal tracking-normal text-ink-placeholder dark:text-white/35">
            {t(`section.${section}.subtitle`)}
          </span>
        </h3>
        <svg
          className={`h-5 w-5 shrink-0 text-ink-placeholder transition-transform duration-200 ${collapsed ? '-rotate-90' : 'rotate-0'}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <div
        className={`border-t border-edge/60 dark:border-dark-border transition-all duration-200 ease-in-out ${
          collapsed ? 'max-h-0 overflow-hidden border-t-0 opacity-0' : 'max-h-[2000px] opacity-100'
        }`}
      >
        <div className="px-4 py-3.5">
          {renderContent()}
        </div>
      </div>
    </div>
  );
}
