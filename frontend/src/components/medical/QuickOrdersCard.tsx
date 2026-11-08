// =============================================================================
// 快速開單 — 從 AI 建議檢查勾選後送出（行為對齊 Flutter quick_orders_page.dart）
// - 預設勾選＝上一張單的項目（沒開過就全不勾）；空單送出合法＝「看過了，這次不開檢查」
// - 上一張單裡已不在 AI 清單的項目照樣列出（標「先前開立」），避免報告重生後勾選紀錄消失
// =============================================================================

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import type { SOAPReport } from '../../types';
import * as sessionsApi from '../../services/api/sessions';
import type { ExamOrder, ExamOrderItem } from '../../services/api/sessions';
import { formatDate } from '../../utils/format';
import { URGENCY_CLASS } from './urgency';

function nonEmpty(v: unknown): string | undefined {
  const s = typeof v === 'string' ? v.trim() : '';
  return s || undefined;
}

/** AI 建議在前（維持報告順序），上一張單多出來的接在後面。 */
function buildCandidates(report: SOAPReport, latest: ExamOrder | null): { items: ExamOrderItem[]; aiNames: Set<string> } {
  const raw = (report.plan?.recommendedTests ?? []) as unknown as Array<Record<string, unknown>>;
  const items: ExamOrderItem[] = [];
  const seen = new Set<string>();
  for (const r of raw) {
    const testName = nonEmpty(r?.testName ?? r?.test_name);
    if (!testName || seen.has(testName)) continue;
    seen.add(testName);
    items.push({ testName, urgency: nonEmpty(r.urgency), rationale: nonEmpty(r.rationale) });
  }
  const aiNames = new Set(seen);
  for (const item of latest?.items ?? []) {
    if (!seen.has(item.testName)) {
      seen.add(item.testName);
      items.push(item);
    }
  }
  return { items, aiNames };
}

export default function QuickOrdersCard({ sessionId, report }: { sessionId: string; report: SOAPReport }) {
  const { t } = useTranslation('soap');
  const [latest, setLatest] = useState<ExamOrder | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (import.meta.env.VITE_ENABLE_MOCK === 'true') {
      setLoaded(true);
      return;
    }
    let alive = true;
    setLoaded(false);
    setLoadFailed(false);
    sessionsApi
      .getLatestExamOrder(sessionId)
      .then((order) => {
        if (!alive) return;
        setLatest(order);
        setSelected(new Set(order?.items.map((i) => i.testName) ?? []));
        setNote(order?.note ?? '');
      })
      .catch(() => alive && setLoadFailed(true))
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [sessionId]);

  const { items, aiNames } = useMemo(() => buildCandidates(report, latest), [report, latest]);
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.testName));

  const toggle = (name: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const submit = async () => {
    setSubmitting(true);
    try {
      const saved = await sessionsApi.submitExamOrder(sessionId, {
        items: items.filter((i) => selected.has(i.testName)),
        note: note.trim() || undefined,
        reportId: report.id,
      });
      setLatest(saved);
      toast.success(t('quickOrders.submitted'));
    } catch {
      toast.error(t('quickOrders.submitError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="card" aria-labelledby="quick-orders-title">
      <div className="flex items-center justify-between gap-2">
        <h2 id="quick-orders-title" className="text-h3 text-ink-heading dark:text-white">{t('quickOrders.title')}</h2>
        {items.length > 0 ? (
          <button
            type="button"
            className="text-small font-medium text-primary-600 hover:text-primary-700 disabled:opacity-50 dark:text-primary-400"
            disabled={submitting || !loaded}
            onClick={() => setSelected(allSelected ? new Set() : new Set(items.map((i) => i.testName)))}
          >
            {allSelected ? t('quickOrders.clearAll') : t('quickOrders.selectAll')}
          </button>
        ) : null}
      </div>

      {report.status === 'generating' ? (
        <p className="mt-2 text-small text-ink-muted">{t('quickOrders.reportGenerating')}</p>
      ) : null}
      {loadFailed ? (
        <p className="mt-2 text-small text-amber-700 dark:text-amber-400">{t('quickOrders.loadError')}</p>
      ) : null}

      <p className="mt-3 text-small font-semibold uppercase tracking-[0.14em] text-ink-muted">{t('quickOrders.testsTitle')}</p>
      {items.length === 0 ? (
        <p className="mt-2 text-body text-ink-muted">{t('quickOrders.noTests')}</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {items.map((item) => (
            <li key={item.testName}>
              <label className="flex cursor-pointer items-start gap-3 rounded-card border border-edge px-3 py-2.5 transition-colors hover:bg-surface-secondary/50 has-[:checked]:border-primary-300 has-[:checked]:bg-primary-50/50 dark:border-dark-border dark:hover:bg-dark-surface/50 dark:has-[:checked]:border-primary-700 dark:has-[:checked]:bg-primary-950/20">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0 accent-primary-600"
                  checked={selected.has(item.testName)}
                  disabled={submitting || !loaded}
                  onChange={() => toggle(item.testName)}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-body font-semibold text-ink-heading dark:text-white">{item.testName}</span>
                    {item.urgency ? (
                      <span className={`rounded-pill px-2 py-0.5 text-tiny font-semibold ${URGENCY_CLASS[item.urgency] ?? URGENCY_CLASS.routine}`}>
                        {t(`plan.urgency.${item.urgency}`, { defaultValue: item.urgency })}
                      </span>
                    ) : null}
                    {!aiNames.has(item.testName) ? (
                      <span className="rounded-pill bg-surface-tertiary px-2 py-0.5 text-tiny font-semibold text-ink-muted dark:bg-dark-border dark:text-white/50">
                        {t('quickOrders.previouslyOrdered')}
                      </span>
                    ) : null}
                  </span>
                  {item.rationale ? (
                    <span className="mt-0.5 block text-small text-ink-secondary dark:text-white/60">{item.rationale}</span>
                  ) : null}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <label className="mt-4 block">
        <span className="text-small font-semibold uppercase tracking-[0.14em] text-ink-muted">{t('quickOrders.noteTitle')}</span>
        <textarea
          className="input-base mt-2 min-h-[72px] resize-y"
          rows={3}
          maxLength={2000}
          value={note}
          disabled={submitting || !loaded}
          placeholder={t('quickOrders.noteHint')}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>

      {selected.size === 0 ? (
        <p className="mt-3 text-small text-ink-muted">{t('quickOrders.emptySelectionHint')}</p>
      ) : null}
      <button
        type="button"
        className="btn-primary mt-3 w-full disabled:cursor-not-allowed disabled:opacity-50"
        disabled={submitting || !loaded}
        onClick={submit}
      >
        {submitting ? t('quickOrders.submitting') : t('quickOrders.submit')}
      </button>
      {latest ? (
        <p className="mt-2 text-small text-ink-muted">
          {t('quickOrders.lastOrdered', { time: formatDate(latest.createdAt, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) })}
        </p>
      ) : null}
    </section>
  );
}
