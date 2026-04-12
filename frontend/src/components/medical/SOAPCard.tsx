// =============================================================================
// SOAP 報告區塊卡片 — 結構化醫學報告渲染
// 設計語言：Stripe 精準 × 醫療級可讀性 × 最小色彩原則
// =============================================================================

import { useState } from 'react';
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

interface SOAPCardProps {
  section: 'subjective' | 'objective' | 'assessment' | 'plan';
  content: Record<string, unknown> | null | undefined;
}

const sectionMeta: Record<string, {
  letter: string;
  title: string;
  subtitle: string;
  accent: string;
  badge: string;
}> = {
  subjective: {
    letter: 'S',
    title: '主觀',
    subtitle: 'Subjective',
    accent: 'bg-indigo-400 dark:bg-indigo-500',
    badge: 'bg-indigo-50 text-indigo-600 ring-1 ring-indigo-500/15 dark:bg-indigo-500/10 dark:text-indigo-400 dark:ring-indigo-400/20',
  },
  objective: {
    letter: 'O',
    title: '客觀',
    subtitle: 'Objective',
    accent: 'bg-teal-400 dark:bg-teal-500',
    badge: 'bg-teal-50 text-teal-600 ring-1 ring-teal-500/15 dark:bg-teal-500/10 dark:text-teal-400 dark:ring-teal-400/20',
  },
  assessment: {
    letter: 'A',
    title: '評估',
    subtitle: 'Assessment',
    accent: 'bg-amber-400 dark:bg-amber-500',
    badge: 'bg-amber-50 text-amber-700 ring-1 ring-amber-500/15 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-400/20',
  },
  plan: {
    letter: 'P',
    title: '計畫',
    subtitle: 'Plan',
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

function TagList({ items }: { items: string[] }) {
  const filtered = items.filter((s) => s && s !== '無');
  if (filtered.length === 0) return <span className="text-body text-ink-placeholder">無</span>;
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

// ── S 主觀 ────────────────────────────────────────────────

function SubjectiveContent({ data }: { data: SOAPSubjective }) {
  const { chiefComplaint, hpi, pastMedicalHistory: pmh, medicationHistory: meds, systemReview, socialHistory } = data;
  return (
    <div className="space-y-3.5">
      <Callout border="border-l-indigo-300 dark:border-l-indigo-600">
        <SubLabel>主訴 Chief Complaint</SubLabel>
        <p className="mt-0.5 text-h3 font-medium text-ink-heading dark:text-white">{chiefComplaint}</p>
      </Callout>

      {hpi && (
        <div>
          <SectionLabel>現病史 HPI</SectionLabel>
          <FieldGrid>
            <FieldItem label="發病時間" value={hpi.onset} />
            <FieldItem label="部位" value={hpi.location} />
            <FieldItem label="持續時間" value={hpi.duration} />
            <FieldItem label="嚴重度" value={hpi.severity} />
            <FieldItem label="發作頻率" value={hpi.timing} />
            <FieldItem label="情境" value={hpi.context} />
          </FieldGrid>
          {hpi.characteristics && (
            <div className="mt-2">
              <SubLabel>特徵描述</SubLabel>
              <p className="mt-0.5 text-body-lg text-ink-body dark:text-white/85">{hpi.characteristics}</p>
            </div>
          )}
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div>
              <SubLabel>加重因素</SubLabel>
              <div className="mt-1"><TagList items={hpi.aggravatingFactors ?? []} /></div>
            </div>
            <div>
              <SubLabel>緩解因素</SubLabel>
              <div className="mt-1"><TagList items={hpi.relievingFactors ?? []} /></div>
            </div>
            <div>
              <SubLabel>伴隨症狀</SubLabel>
              <div className="mt-1"><TagList items={hpi.associatedSymptoms ?? []} /></div>
            </div>
          </div>
        </div>
      )}

      <Divider />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {pmh && (
          <div>
            <SectionLabel>過去病史</SectionLabel>
            <div className="space-y-1.5">
              <div><SubLabel>疾病</SubLabel><div className="mt-0.5"><TagList items={pmh.conditions ?? []} /></div></div>
              <div><SubLabel>手術史</SubLabel><div className="mt-0.5"><TagList items={pmh.surgeries ?? []} /></div></div>
              <div><SubLabel>住院史</SubLabel><div className="mt-0.5"><TagList items={pmh.hospitalizations ?? []} /></div></div>
            </div>
          </div>
        )}
        {meds && (
          <div>
            <SectionLabel>用藥史</SectionLabel>
            <div className="space-y-1.5">
              <div><SubLabel>目前用藥</SubLabel><div className="mt-0.5"><TagList items={meds.current ?? []} /></div></div>
              {(meds.past?.length ?? 0) > 0 && <div><SubLabel>過去用藥</SubLabel><div className="mt-0.5"><TagList items={meds.past} /></div></div>}
              {(meds.otc?.length ?? 0) > 0 && <div><SubLabel>非處方藥</SubLabel><div className="mt-0.5"><TagList items={meds.otc} /></div></div>}
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
                <SectionLabel>系統回顧</SectionLabel>
                <FieldGrid>
                  {Object.entries(systemReview).map(([key, val]) => (
                    <FieldItem key={key} label={fieldLabels[key] || key} value={val} />
                  ))}
                </FieldGrid>
              </div>
            )}
            {socialHistory && Object.keys(socialHistory).length > 0 && (
              <div>
                <SectionLabel>社會史</SectionLabel>
                <FieldGrid>
                  {Object.entries(socialHistory).map(([key, val]) => (
                    <FieldItem key={key} label={fieldLabels[key] || key} value={val} />
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

const vitalLabels: Record<string, string> = {
  bloodPressure: '血壓', heartRate: '心率', respiratoryRate: '呼吸速率', temperature: '體溫', spo2: '血氧',
};
const vitalUnits: Record<string, string> = {
  bloodPressure: 'mmHg', heartRate: 'bpm', respiratoryRate: '次/分', temperature: '°C', spo2: '%',
};

function ObjectiveContent({ data }: { data: SOAPObjective }) {
  const { vitalSigns, physicalExam, labResults } = data;
  return (
    <div className="space-y-3.5">
      {vitalSigns && (
        <div>
          <SectionLabel>生命徵象</SectionLabel>
          <div className="grid grid-cols-3 gap-2 lg:grid-cols-5">
            {Object.entries(vitalSigns).map(([key, val]) => {
              if (val === undefined || val === null) return null;
              return (
                <div
                  key={key}
                  className="rounded-card border border-edge bg-white px-2.5 py-2 text-center dark:border-dark-border dark:bg-dark-card"
                >
                  <p className="text-small font-medium text-ink-placeholder dark:text-white/40">{vitalLabels[key] || key}</p>
                  <p className="text-h3 font-semibold font-tnum text-ink-heading dark:text-white">{val}</p>
                  <p className="text-small text-ink-placeholder dark:text-white/30">{vitalUnits[key] || ''}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {physicalExam && Object.keys(physicalExam).length > 0 && (
        <div>
          <SectionLabel>理學檢查</SectionLabel>
          <div className="overflow-hidden rounded-card border border-edge dark:border-dark-border">
            {Object.entries(physicalExam).map(([key, val], i) => (
              <div
                key={key}
                className={`flex items-start gap-3 px-3.5 py-2 ${i > 0 ? 'border-t border-edge/60 dark:border-dark-border' : ''}`}
              >
                <span className="w-20 shrink-0 text-body font-medium text-ink-muted dark:text-white/50">{fieldLabels[key] || key}</span>
                <span className="text-body-lg text-ink-body dark:text-white/85">{val}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {labResults && labResults.length > 0 && (
        <div>
          <SectionLabel>實驗室檢查</SectionLabel>
          <div className="overflow-hidden rounded-card border border-edge dark:border-dark-border">
            <table className="w-full">
              <thead>
                <tr className="bg-surface-secondary dark:bg-dark-surface">
                  <th className="px-3.5 py-2 text-left text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">項目</th>
                  <th className="px-3.5 py-2 text-left text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">結果</th>
                  <th className="px-3.5 py-2 text-left text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">參考</th>
                  <th className="px-3.5 py-2 text-center text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/40">狀態</th>
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
                          異常
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-pill bg-surface-tertiary px-2 py-0.5 text-small font-medium text-ink-muted dark:bg-dark-border dark:text-white/50">
                          正常
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

const probConfig: Record<string, { label: string; dot: string; text: string; bg: string }> = {
  high:   { label: '高', dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 ring-1 ring-red-500/15 dark:bg-red-500/10 dark:ring-red-400/20' },
  medium: { label: '中', dot: 'bg-amber-500', text: 'text-amber-700 dark:text-amber-400', bg: 'bg-amber-50 ring-1 ring-amber-500/15 dark:bg-amber-500/10 dark:ring-amber-400/20' },
  low:    { label: '低', dot: 'bg-slate-400', text: 'text-ink-muted dark:text-white/50', bg: 'bg-surface-tertiary ring-1 ring-edge dark:bg-dark-border dark:ring-dark-border' },
};

function AssessmentContent({ data }: { data: SOAPAssessment }) {
  const { differentialDiagnoses, clinicalImpression } = data;
  return (
    <div className="space-y-3.5">
      {clinicalImpression && (
        <Callout border="border-l-amber-300 dark:border-l-amber-600">
          <SubLabel>臨床印象</SubLabel>
          <p className="mt-0.5 text-body-lg font-medium text-ink-heading dark:text-white">{clinicalImpression}</p>
        </Callout>
      )}

      {differentialDiagnoses && differentialDiagnoses.length > 0 && (
        <div>
          <SectionLabel>鑑別診斷</SectionLabel>
          <div className="space-y-2">
            {(differentialDiagnoses as DifferentialDiagnosis[]).map((dx, i) => {
              const p = probConfig[dx.probability] || probConfig.low;
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
                      {p.label}
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

const urgConfig: Record<string, { label: string; cls: string }> = {
  urgent:   { label: '急', cls: 'bg-red-50 text-red-600 ring-1 ring-red-500/15 dark:bg-red-500/10 dark:text-red-400 dark:ring-red-400/20' },
  routine:  { label: '常規', cls: 'bg-surface-tertiary text-ink-muted ring-1 ring-edge dark:bg-dark-border dark:text-white/50 dark:ring-dark-border' },
  elective: { label: '擇期', cls: 'bg-surface-tertiary text-ink-placeholder ring-1 ring-edge dark:bg-dark-border dark:text-white/40 dark:ring-dark-border' },
};

function PlanContent({ data }: { data: SOAPPlan }) {
  const { recommendedTests, treatments, followUp, referrals, patientEducation, diagnosticReasoning } = data;
  const [expandedTests, setExpandedTests] = useState<Record<number, boolean>>({});
  const toggleTest = (i: number) => setExpandedTests((prev) => ({ ...prev, [i]: !prev[i] }));

  return (
    <div className="space-y-3.5">
      {diagnosticReasoning && (
        <Callout border="border-l-violet-300 dark:border-l-violet-600">
          <div className="flex items-start gap-2">
            <svg className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted dark:text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <div>
              <p className="text-small font-semibold uppercase tracking-wider text-ink-muted dark:text-white/50 mb-0.5">臨床推理</p>
              <p className="text-body-lg leading-relaxed text-ink-body dark:text-white/80">{diagnosticReasoning}</p>
            </div>
          </div>
        </Callout>
      )}

      {recommendedTests && recommendedTests.length > 0 && (
        <div>
          <SectionLabel>建議檢查</SectionLabel>
          <div className="space-y-1.5">
            {(recommendedTests as RecommendedTest[]).map((test, i) => {
              const u = urgConfig[test.urgency] || urgConfig.routine;
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
                        <span className={`rounded-pill px-2 py-0.5 text-small font-semibold ${u.cls}`}>{u.label}</span>
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
          <SectionLabel>治療處置</SectionLabel>
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
          <SectionLabel>追蹤計畫</SectionLabel>
          <div className="rounded-card border border-edge px-3.5 py-2.5 dark:border-dark-border">
            <FieldGrid>
              <FieldItem label="回診時間" value={followUp.interval} />
              <FieldItem label="追蹤原因" value={followUp.reason} />
            </FieldGrid>
            {followUp.additionalNotes && (
              <p className="mt-1.5 text-body italic text-ink-muted dark:text-white/50">{followUp.additionalNotes}</p>
            )}
          </div>
        </div>
      )}

      {referrals && referrals.length > 0 && (
        <div>
          <SectionLabel>轉介</SectionLabel>
          <TagList items={referrals} />
        </div>
      )}

      {patientEducation && patientEducation.length > 0 && (
        <div>
          <SectionLabel>衛教指導</SectionLabel>
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

// ── 欄位標籤 ────────────────────────────────────────────────

const fieldLabels: Record<string, string> = {
  general: '一般狀態', urological: '泌尿系統',
  smoking: '吸菸', alcohol: '飲酒', occupation: '職業',
  abdomen: '腹部', costovertebral: '肋脊角', genitourinary: '泌尿生殖',
};

// ── 主元件 ────────────────────────────────────────────────

export default function SOAPCard({ section, content }: SOAPCardProps) {
  const meta = sectionMeta[section];
  const [collapsed, setCollapsed] = useState(false);

  const renderContent = () => {
    if (!content) return <p className="py-2 text-center text-body-lg text-ink-placeholder">尚無資料</p>;
    switch (section) {
      case 'subjective':  return <SubjectiveContent data={content as unknown as SOAPSubjective} />;
      case 'objective':   return <ObjectiveContent data={content as unknown as SOAPObjective} />;
      case 'assessment':  return <AssessmentContent data={content as unknown as SOAPAssessment} />;
      case 'plan':        return <PlanContent data={content as unknown as SOAPPlan} />;
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
          {meta.title}
          <span className="ml-1.5 text-caption font-normal tracking-normal text-ink-placeholder dark:text-white/35">
            {meta.subtitle}
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
