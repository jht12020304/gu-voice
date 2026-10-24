# Backend round-2 measurements (2026-10-24, local macOS, Postgres 16 in Docker)

## B46 PDF render in a recycling process pool (vs thread, vs original sync)
Single uvicorn worker on :18000, same report rendered repeatedly.

| metric | original (sync in loop) | thread + lock | process pool (max_workers=1, spawn, recycle every 20) |
|---|---|---|---|
| API process RSS after first PDF | 719 MB | 719 MB | **167 MB** |
| API process RSS after 25 PDFs | 737 MB | ~740 MB | **168 MB** (render memory lives in the child: 657 MB, recycled) |
| /health latency while a PDF renders | 956 ms | 1.6–142 ms | **1.3–1.8 ms** |
| PDF #1 | 1.27 s | 1.24 s | 1.70 s (+0.5 s child spawn + import) |
| PDF #2–#4 | 1.25–1.30 s | 1.24–1.52 s | 1.17–1.21 s |

## B30 notification fan-out language lookup
Statement count pinned by `tests/unit/services/test_notification_fanout_language_query.py`: N targets → 1 `preferred_language` query (was N). Not timed against a live DB (local RTT ≈ 0.1 ms would not show it); the saving is N−1 round trips per SOAP-ready/failed event.

## B33 / B34 dashboard hot-path indexes (EXPLAIN ANALYZE, script evidence/explain_b33.py)
Synthetic data: 100,000 sessions (2 % waiting/in_progress, like production history), 10,000 alerts (33 % unacknowledged).

| statement | before | after `audit_20261024_idx` | plan after |
|---|---|---|---|
| queue: `status IN (...) ORDER BY created_at LIMIT 50` | 5.65 ms Seq Scan | **1.08 ms** | Bitmap Index Scan `ix_sessions_status_created_at` |
| sessions today, range predicate (B34 form) | 4.72 ms Seq Scan | **1.05 ms** | Index Scan `ix_sessions_status_created_at` |
| sessions today, old `date(created_at) = :d` form | 6.62 ms Seq Scan | 6.63 ms Seq Scan | index unusable → B34 rewrite is required for the gain |
| pending alerts `acknowledged_by IS NULL` (33 % pending) | 13.08 ms Hash Join | 13.08 ms (planner keeps seq scan) | — |
| pending alerts at 3.3k alerts / low pending share (earlier run) | 0.20 ms | **0.05 ms** | Index Scan `ix_red_flag_alerts_pending_created` |

Conclusion: the composite sessions index + sargable predicate is a 4–5× win at 100k rows; the partial alert index only pays when the unacknowledged share is small (the normal state; the audit noted a one-off 128-row backlog). Neither regressed anything. Both indexes are CONCURRENTLY and self-healing (R17 drill: an INVALID leftover was dropped and recreated; a second `upgrade head` is a no-op).

## R17 self-healing migration drill
downgrade → create index manually → `UPDATE pg_index SET indisvalid=false` → `alembic upgrade head` ⇒ all four indexes `valid=true`; re-running upgrade: no-op.
