# gu-voice repository-level audit (read-only) — 2026-10-23

Scope: everything outside `backend/app`, `frontend/src`, `flutter_app/lib` internals, plus characterization of the uncommitted WIP. Branch `refactor/codebase-audit-2026-10` @ `e41cc9e` (HEAD unchanged); WIP snapshot tag `wip-snapshot-2026-10-23` = `e54956e`. Nothing in the repo or parent dir was modified. No tests were run (would write `__pycache__`/`.pytest_cache` into the tree).

Categories: **A** keep · **B** safe to remove (proof given) · **C** suspect/verify · **D** duplicate/mergeable · **E** improvement.

---

## 1. WIP characterization

### 1.0 Shape

| Metric | Value | Evidence |
|---|---|---|
| `git status --short` | 223 ` M`, 4 ` D` (3 unstaged + `D ` staged `frontend/vite.config.d.ts`), 29 `??` | `git status --short \| awk '{print $1}' \| uniq -c` |
| `git diff HEAD wip-snapshot-2026-10-23 --stat` | 255 files, +6674 / −3508 (includes untracked) | stat tail line |
| Last-mtime of WIP files | 61 → 2026-10-03 · 181 → 2026-10-10 · 4 → 2026-09-09 (demo-video tooling) · 1 → 2026-08-20 (`vite.config.d.ts`) · 1 → 10-22 (`ios/Podfile.lock`) · 5 → 10-23 (`frontend/public/locales/*/common.json`, rebuilt mirror) | `stat -f %Sm` over status list |
| Docs mentioning the 10-10 session | **none** — `grep -rn "2026-10-1" docs CLAUDE.md .claude backend/app frontend/src flutter_app/lib` → 0 hits | — |
| Stash | empty | `git stash list` |

Because 181 files were re-touched on 10-10, mtime alone cannot cleanly separate theme (a)/(b) from (c) for files edited in both sessions; the split below uses diff content + F/M-id comments (`git diff … \| grep -oE '\b(F0[1-9]\|F1[0-2]\|M[1-3])\b'` → all 12 F-ids and M1–M3 appear as code comments).

### 1.1 Themes

#### (a) 2026-10-03 「整體流暢度修正 F01–F12」 (iOS + React + backend)

- **Files (~70)**: backend `alembic/versions/20261003_1600-notification_paging_indexes.py` (new, 22 L), `app/models/notification.py` (+`__table_args__` two indexes, :20-23), `app/routers/dashboard.py` (+`GET /dashboard/calendar`, :33-40), `app/schemas/dashboard.py` (+`CalendarDaySummary`, :110-118), `app/services/dashboard_service.py` (104 L: SQL month aggregation, `invalidate_stats_cache`), `app/services/notification_service.py`, `app/websocket/conversation_handler.py` (F07 early-sentence stream, Latin punctuation split; F10 one-round-trip queue/stats; request-scoped session closed after snapshot), `app/websocket/dashboard_handler.py` (70 L). React: `stores/reportStore.ts` (F02), `stores/notificationStore.ts` + `screens/doctor/NotificationPage.tsx` (F03/F05), `navigation/RootNavigator.tsx` + `components/layout/MainLayout.tsx` (F04/F11 shared dashboard socket), `utils/coalesceRefresh.ts` (new, F05), `stores/authStore.ts` + `services/api/client.ts` (F06 503/timeout keeps login), `services/audioStream.ts` + `hooks/useAudioStream.ts` + `screens/patient/ConversationPage.tsx` (F08 waveform throttle), `index.css:427-432` (F12 `content-visibility`, carries a `ponytail:` ceiling comment), `i18n/index.ts:62` (`load: 'currentOnly'`), `components/DoctorAlertPoller.tsx`, `Header.tsx`, `Sidebar.tsx`. Flutter: `core/router/app_router.dart` (F01 StatefulShellRoute), `data/api/reports_api.dart` + `features/doctor/screens/report_list_page.dart` (F02), `features/doctor/state/sessions_list_controller.dart` (F05), `data/api/sessions_api.dart` + `screens/session_calendar_view.dart` (F09, 482 L), `patient_list_page.dart`/`alert_list_page.dart` (F12 builders), `features/voice/services/audio_stream_service.dart`, `ios/Podfile` (platform 15 + pod deployment-target floor, :1,:41-46).
- **New tests**: backend `tests/unit/websocket/test_early_sentence_stream.py` (98 L), `tests/integration/test_smoothness_queries_pg.py` (134 L, real PG), `tests/unit/services/test_dashboard_month_key.py` (+49); Flutter `test/smoothness_regression_test.dart` (341 L), `test/conversation_page_ux_test.dart` (+76); React `scripts/verify/smoothness-state.test.mjs` (75 L, run by `npm test`), `scripts/verify/smoothness-browser.mjs` (151 L) and `smoothness-performance.mjs` (95 L) — the latter two need a preview server and are **manual only** (`docs/perf_audit_2026-08-22.md:75-84`).
- **TODO.md marks done?** Yes: `docs/TODO.md:4-6` (WIP) "F01–F12 已完成程式修正與本機回歸 … production 未變更". Authoritative write-up: `docs/perf_audit_2026-08-22.md:30-104` (WIP).
- **Risk**: Changes DB schema and API. Migration `smoothness_20261003` (`down_revision = "a1b2c3d4e5f6"` = `20260909_0100-add_exam_orders.py:15`, so the chain is linear, no second head) creates two indexes with `postgresql_concurrently=True` inside `autocommit_block()` — **additive, online-safe**; downgrade symmetric. Note `scripts/start.sh:66-82` runs `alembic upgrade head` on every container boot with retries; CONCURRENTLY + a failed attempt can leave an `INVALID` index that a retry will then fail on (`relation already exists`) — **C**: verify on staging that a retried boot is idempotent (perf_audit:15 says the index "已存在" on staging, so it has run at least once). API additions are additive (`/dashboard/calendar`, `review_counts` in report list). iOS calendar depends on `/dashboard/calendar` → **backend must deploy before the iOS build** (`docs/perf_audit_2026-08-22.md:101`).

#### (b) 2026-10-03 iOS maintainability M1–M3

- **Files**: `flutter_app/lib/data/api/dio_client.dart` (111 L, refresh/retry split, login-generation isolation), `data/api/token_store.dart` (46 L, ordered Keychain writes), `features/doctor/services/dashboard_ws.dart` (provider keyed by account/role), `features/auth/auth_notifier.dart`, `features/doctor/state/notifications_controller.dart` (request sequence numbers), `data/api/notifications_api.dart`, `features/doctor/state/alerts_controller.dart`.
- **New tests**: `test/api_auth_recovery_test.dart` (227 L), `test/doctor_session_lifecycle_test.dart` (171 L), `test/notifications_ws_refresh_test.dart` (+75), `test/support/api_stub.dart`.
- **TODO.md marks done?** Yes: `docs/TODO.md:10-21` `[x] M1/M2/M3 …（2026-10-03，本機未提交）`, "308 項全數通過" (:23).
- **Risk**: client-only, no API/DB change. Self-contained.

#### (c) 2026-10-10 orchestrated code-quality refactor (backend 18 / frontend 17 findings)

- **Backend files (~45)**: `app/tasks/__init__.py:53-71` new `run_async(factory)` replacing six copies of `try: loop.run_until_complete … except Exception: asyncio.run` (business exceptions used to re-run the task body: double push / double FAILED) in `audio_lifecycle.py`, `audit_retention.py`, `notification_retry.py`, `partition_manager.py`, `report_queue.py`, `session_timeout.py`; `app/tasks/report_queue.py` (`_update_report_status` → bool so only the first marker announces failure, :610-624; `notify_report_ready` committed **before** `report_generated` publish; soft-deleted sessions skipped :291); `app/tasks/session_timeout.py:101-113` (idle = no `Conversation` after threshold); `app/services/session_service.py` (−381/+… : `_execute_status_cas` compare-and-set on `UPDATE sessions WHERE status=<prev>` :401-432, used by `update_status_static` and language-switch cancel; `scope_filter` unifies data+count query for clinician/patient :478-485; `get_by_id(with_conversations=)`; `assign_doctor` validates target is a selectable clinician :913-922; `_parse_cursor`/`_parse_date_filter` removed in favour of `app/utils/pagination.parse_cursor` (new) and `datetime_utils.parse_iso`); `app/services/report_service.py:463-497` (row-level authz on generate/regenerate via `SessionService.get_session`, `review_counts` group-by); `app/core/dependencies.py` (dead `PaginationParams` removed); `app/cache/redis_client.py` (dead `cache_get/set/delete/exists` removed); `app/services/conversation_service.py` (dead `get_by_session` removed); `app/schemas/__init__.py` (dead `GenerateReportResponse`/`ReviewReportResponse` exports removed); `app/pipelines/prompts/shared.py` (+`CORE_HPI_PRIORITY_RULE` shared by conversation+supervisor); `app/core/config.py:248` (+`OPENAI_TEMPERATURE_SUPERVISOR`); `requirements.txt` drops `python-multipart`, `aiohttp`, `orjson`, `pytz`, `jinja2`, pins `prometheus-client==0.26.0`.
  - Dead-code proof (working tree, `grep -rn` over `backend/app frontend/src flutter_app/lib`): `PaginationParams` 0, `cache_get/set/delete/exists` 0, `get_by_session` 0, `GenerateReportResponse`/`ReviewReportResponse` 0, `_parse_date_filter` 0, `useLocalizedTo` 0, `useWebSocket(` 0. Dropped requirements: `multipart`/`UploadFile`/`Form(` 0, `aiohttp` 0, `orjson` 0, `pytz` 0, `jinja2`/`Template(` 0 across `backend/app backend/alembic backend/scripts backend/tests`. WeasyPrint stays (`requirements.txt:43`, used `report_service.py:717`).
- **Backend new tests**: `tests/unit/tasks/test_run_async.py` (30), `tests/unit/utils/test_pagination.py` (17), `tests/unit/routers/test_session_reconnect.py` (45); large additions to `test_prompt_injection_sanitization.py` (+108), `test_session_authorization.py` (+61), `test_supervisor_prompt.py` (+53), `test_guidance_key_prefix_and_history_summary.py` (+51), `test_rest_status_side_effects.py` (+48), `test_auth_cookies.py` (+46), `test_report_queue_audit_2026_08.py` (+43), `test_report_generate_regenerate.py` (+30).
- **Frontend files (~35)**: `services/websocket.ts:94,121-134,231-242,341-375` (`generation` counter; old socket handlers nulled before `close()` → fixes double live socket; transient refresh failure now reconnects with backoff instead of logging out), `hooks/useWebSocket.ts` (split `useDashboardConnection` (MainLayout-owned) / `useDashboardWebSocket` (listeners only); generic `useWebSocket` removed; `refreshOrReject` helper), new `components/common/ThemeToggle.tsx`, `hooks/useClickOutside.ts`, `hooks/useInfiniteScroll.ts`; `i18n/paths.ts` (dead `useLocalizedTo` removed); `types/index.ts` (`User.role: UserRole`; `SOAPReport` gains `patientName/chiefComplaintText/sessionStatus/sessionRedFlag`); `package.json` (`@sentry/react` moved devDependencies → dependencies — a real prod-bundle fix; `@types/uuid` removed; `engines.node >=22.17.0`; new `test` script); `Dockerfile:6` node 20→22; many screens for timezone/URL-language/dead exports.
- **Frontend new tests**: `services/__tests__/wsStaleSocketClose.test.mts` (105), `wsAuthRecoveryGuard.test.mts` (+26), `stores/__tests__/normalizeSupervisorGuidance.test.mts` (+15).
- **Flutter 10-10 files (~50)**: new `data/api/parse_page.dart` (cursor-page parser, 7 call sites), `shared/toast.dart` (34 call sites), `shared/share_bytes.dart` (replaces two files, see 1.2), `shared/widgets/ui_kit.dart` (+62), `shared/format.dart`, pages (`report_list_page.dart` −259/+…, `user_management_page.dart`, `quick_orders_page.dart`, `research_analytics_page.dart`, `conversation_page.dart` −203/+…), `features/doctor/research/stats.dart` (−36 dead), tests `doctor_alert_watcher_test.dart` (new 71), `patient_facing_summary_test.dart` (+36), `research_stats_test.dart` (−16).
- **TODO.md marks done?** **No.** No doc, TODO entry, or perf_audit line mentions 2026-10-10 or the 18/17 findings. The only trace is in code comments. → **C/E**: write the finding list into `docs/TODO.md` (or a `docs/code_quality_2026-10-10.md`) before committing, otherwise the authz/CAS semantics changes are undiscoverable.
- **Risk**: behaviour changes that are *not* purely refactor: (1) `PUT /sessions/{id}/status` now **rejects** with 409-style `InvalidStatusTransitionException` when another process moved the row first (previously silently overwrote) — clients must tolerate; (2) report generate/regenerate now **403s** for clinicians outside the session scope; (3) `assign_doctor` now **404s** on non-clinician ids; (4) session-timeout no longer cancels sessions with recent conversations; (5) `requirements.txt` slimmed — production Dockerfile installs from it (`backend/Dockerfile:21-24`), grep proves no first-party use, but transitive needs are unverified offline (**C**: `pip check` in a fresh venv / staging boot). (6) React `useDashboardWebSocket` no longer connects — any page still relying on it to open the socket outside `MainLayout` would silently get no events (**C**: confirm `useDashboardConnection` is mounted on every authenticated layout; 3 references exist).

#### (d) Scope decision: "maintain both iOS and React" (docs / CLAUDE.md / skills)

- **Files**: `CLAUDE.md` (:3,:16-23,:34-38,:47,:53,:66,:78), `docs/README.md:11-30` (new 維護範圍 section), `docs/AGENTS.md:3-8` (+ fixes 9 absolute `/Users/chun/Desktop/GU_0410/...` links → relative, :83-89,:129,:142-143), `docs/app_architecture.md:3-9`, `docs/deployment_guide.md:122-128`, `docs/flutter_web_cutover.md:3-5`, `docs/system_overview.md:115-116`, `docs/ios_release_settings.md` (new §0 staging table :31-54, Xcode 27, §7 retitled "最近一次已確認"), `docs/TODO.md` (:443, :745-747, :954-956, :1004-1008 corrections), `docs/full_setup_guide.md:11-18` (absolute paths → `<repo>`), `docs/research_analytics.md:137` (removed `scratchpad/seed_research_e2e.py` ref — that file never existed in repo), `docs/runbook/add_new_language.md:190` (dead `useWsMessageRenderer.ts` → `ConversationPage.tsx`), `docs/runbook/i18n_rollout.md:107,:221` (dead `docs/clinical/…`, `docs/専案開発進度.md` refs removed), `docs/supabase_connection_guide.md:43`, `.claude/skills/i18n-language-consistency/SKILL.md:27-45,:59,:63`, `.claude/skills/ios-testflight/SKILL.md:14,:38,:172,:188`, `flutter_app/README.md`, `flutter_app/pubspec.yaml:93`.
- **Risk**: docs only. Self-contained; these fix 14 previously-broken absolute links (section 5).

#### (e) CI workflow changes

- `.github/workflows/ci.yml`: `permissions: contents: read` (:9-10); backend installs `requirements-dev.txt` (:69-75); drops `--ignore=tests/unit/api` (dir does not exist — `ls backend/tests/unit/api` → ENOENT); adds `python -m pytest scripts/tests -q` step (:80-81) at repo root; Node 20→22 (:105-107,:199-201); adds `npm test` (:120-122); `npm run build` with env placeholders (:124-130); Flutter DST calendar run with `TZ=America/New_York` (:174-178); **e2e-playwright enabled** (:183-218; was `if: false` stub).
- `.github/workflows/i18n_staleness.yml`: path triggers widened to Flutter locales/lib (:13-16); matrix `web`/`ios` with `--locales-dir`/`--mirrors` (:31-45); Node 22.
- Consistency with `backend/requirements-dev.txt` (`-r requirements.txt`, `pytest==9.1.1`, `pytest-asyncio==1.4.0`): matches local venv (`pip list` → pytest 9.1.1, pytest-asyncio 1.4.0). ✔
- **E**: `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` placeholders in `ci.yml:128-129` are now dead — `frontend/vite.config.ts:7-9` (WIP) no longer requires them and `frontend/src/vite-env.d.ts:6` says they are unread ("L-24 死設定").

#### (f) Demo video tooling (mtime 2026-09-09, predates branch; never committed)

- `flutter_app/integration_test/demo_walkthrough_test.dart:371-399` (+9 `markStage()` calls), `flutter_app/tool/make_demo_video.sh` (+125: `--stages`, embedded Python resolver), `tool/record_demo.sh` (+48: parses `DEMO_MARK_STAGE` → `stages.tsv`), `tool/demo_captions.example.json` (captions keyed by `stage`). Documented in `flutter_app/README.md` §介紹影片 and `docs/README.md:56`. Self-contained; 4 files; no tests (shell + integration test, not in CI).

#### (g) requirements-dev.txt / pytest-asyncio — folded into (e); file is new (3 L).

#### (h) Everything else

| Item | Files | Note |
|---|---|---|
| Staging/env tooling | `flutter_app/tool/env.production.sh` (new, 6 L: `PROD_API_BASE`/`PROD_WS_BASE`), `tool/build_ios_testflight.sh:42-46,:67-75` (sources it; banner shows custom targets), `tool/build_vercel_output.sh:5-10`, `scripts/tests/test_ios_build_banner.py` (new, 28 L, runs the banner via `bash -c`) | Self-contained |
| i18n checker per client | `scripts/check_translations.py` (`DEFAULT_MIRROR_DIRS` drops `flutter_app/assets/locales` :57-58; `--locales-dir`), `scripts/tests/test_check_translations.py` (+28), `scripts/tests/test_locale_lists_in_sync.py` (new, 42 L: regex-pins backend/web/flutter locale lists) | pairs with (d)/(e) |
| E2E tooling de-hardcoding | `scripts/e2e_realopenai/{README.md,compose.override.yml,driver.py:40-47,start_backend.sh,red_flag_eval.py}` replace `/Users/chun/Desktop/GU_0410` with relative paths; `driver.py:851-855,1834-1843` dontknow analyzer fix; `scripts/tests/test_e2e_dontknow_analysis.py` (new, 65 L) | Self-contained |
| Locale text | `frontend/src/i18n/locales/*/common.json` (+`navigation` key for mobile nav), `frontend/public/locales/*/common.json` (mirror, mtime 10-23) | Must be committed together (CLAUDE.md:74) |
| Misc | `.gitignore:102-103` (+`frontend/vite.config.d.ts`) with staged `D frontend/vite.config.d.ts`; `frontend/.env.example:37-38` (+`VITE_MOCK_ROLE`); `flutter_app/ios/Podfile.lock` (2 L, 10-22); `flutter_app/tool/voice_encode_benchmark.dart` (new, 31 L, host-only AOT benchmark, referenced `perf_audit:59`); `backend/.env.example` fully regenerated (274 L: "本檔由 config.py 產生", drops Google STT/TTS, Celery, WS sections no longer in `Settings`) | — |

### 1.2 The three deletions

| Deleted | Why | Replacement proof | Cat |
|---|---|---|---|
| `flutter_app/lib/shared/pdf_share.dart` | merged into `shared/share_bytes.dart` (git shows rename, 8 L changed) | `soap_report_page.dart:11` and `research_analytics_page.dart:12` import `share_bytes.dart`; `shareBytes` 3 call sites; 0 references to `pdf_share` remain | B (already done) |
| `flutter_app/lib/shared/png_share.dart` (19 L) | same (PNG + PDF now one `shareBytes(bytes, name, mime)`) | 0 references to `png_share` | B |
| `scripts/verify_multilang_migration.sh` (207 L) | one-off upgrade→downgrade→upgrade round-trip for migration `c3d4e5f6a7b8` (2026-06 era) | `git grep -n verify_multilang_migration HEAD` → only the file itself; no doc/skill/CI reference at HEAD or in WIP | B |

### 1.3 Commit recommendation

Split is feasible for the leaf themes; the code core is entangled. Suggested order (each `git add` list is verified to be theme-pure by diff content):

1. **`chore(demo): stage-anchored captions for demo video`** — `flutter_app/integration_test/demo_walkthrough_test.dart flutter_app/tool/make_demo_video.sh flutter_app/tool/record_demo.sh flutter_app/tool/demo_captions.example.json`
2. **`docs: maintain both iOS and React; staging §0; fix absolute links`** — `CLAUDE.md docs/README.md docs/AGENTS.md docs/app_architecture.md docs/deployment_guide.md docs/flutter_web_cutover.md docs/system_overview.md docs/ios_release_settings.md docs/full_setup_guide.md docs/research_analytics.md docs/runbook/add_new_language.md docs/runbook/i18n_rollout.md docs/supabase_connection_guide.md .claude/skills/i18n-language-consistency/SKILL.md .claude/skills/ios-testflight/SKILL.md flutter_app/README.md flutter_app/pubspec.yaml`
3. **`ci: Node 22, requirements-dev, scripts/tests, enable e2e-playwright, i18n matrix`** — `.github/workflows/ci.yml .github/workflows/i18n_staleness.yml backend/requirements-dev.txt frontend/Dockerfile frontend/package.json frontend/package-lock.json .gitignore frontend/vite.config.d.ts` (the staged deletion) + `frontend/vite.config.ts frontend/.env.example`
4. **`tooling: per-client i18n check, e2e path de-hardcoding, staging build env`** — `scripts/check_translations.py scripts/tests/ scripts/e2e_realopenai/ scripts/red_flag_eval.py scripts/verify_multilang_migration.sh flutter_app/tool/env.production.sh flutter_app/tool/build_ios_testflight.sh flutter_app/tool/build_vercel_output.sh flutter_app/tool/voice_encode_benchmark.dart`
5. **`feat(db): notification paging indexes + /dashboard/calendar`** — `backend/alembic/versions/20261003_1600-notification_paging_indexes.py backend/app/models/notification.py backend/app/routers/dashboard.py backend/app/schemas/dashboard.py backend/tests/integration/test_smoothness_queries_pg.py backend/tests/unit/services/test_dashboard_month_key.py` (note: `dashboard_service.py` also carries 10-10 edits — include it here or in 6; it is the only backend service file needed by the router)
6. **`refactor+perf: F01–F12, M1–M3, 2026-10-10 code-quality pass`** — everything remaining under `backend/ frontend/src frontend/scripts/verify frontend/public/locales flutter_app/lib flutter_app/test flutter_app/ios docs/TODO.md docs/perf_audit_2026-08-22.md backend/.env.example`. Files that mix themes and block a finer a/b/c split without `git add -p`: `backend/app/services/session_service.py`, `app/websocket/conversation_handler.py`, `app/tasks/report_queue.py`, `frontend/src/screens/doctor/{ReportListPage,NotificationPage}.tsx`, `frontend/src/stores/{authStore,notificationStore,reportStore}.ts`, `frontend/src/hooks/useWebSocket.ts`, `flutter_app/lib/features/doctor/screens/{report_list_page,alert_list_page,patient_list_page,session_calendar_view}.dart`, `flutter_app/lib/data/api/{dio_client,sessions_api}.dart`, `docs/TODO.md`, `docs/perf_audit_2026-08-22.md`.

Before step 6: (i) run the three suites once more — the "4,879 passed / 317 / 14 files" numbers in `perf_audit:65-73` are from 10-03, before the 10-10 refactor (**C**); (ii) add a TODO.md entry for the 10-10 findings; (iii) `git update-index --chmod=+x` check is not needed (no `start.sh` change). If time is short, steps 1–4 as four commits + step 5+6 as one `wip:` commit is still a large improvement over a single blob.

---

## 2. Tracked files that should not be tracked / secrets hygiene

`git ls-files | grep -Ei '\.env|\.log$|results/.*\.json|tsbuildinfo|\.DS_Store|\.pem|\.p8|\.p12|\.key|secret|token|credential'` → 11 hits; 8 are legitimate source/test files containing the word "token". Relevant:

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `frontend/.env.production` (tracked since `a19f9d2` 2026-04-12, last change `587ce0b` 2026-06-25) | **C → remove from index** | Keys: `VITE_API_BASE_URL, VITE_WS_BASE_URL, VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_APP_ENV, VITE_ENABLE_MOCK, VITE_MOCK_ROLE`. Matches ignore rule `frontend/.gitignore:60 (.env*)` per `git check-ignore --no-index` — i.e. tracked despite the pattern. Rule "Never commit `.env*`" `CLAUDE.md:100`. Supabase vars are dead config (`frontend/src/vite-env.d.ts:6`, `vite.config.ts:7-9` WIP). | Anon key is public-by-design but the project ref is in a public repo; the file also silently defines the production API URL for every `vite build` (Vercel) — removing it moves that into Vercel env (`deployment_guide.md` has an env section). History cannot be scrubbed without rewrite. | `git rm --cached frontend/.env.production`, set `VITE_API_BASE_URL`/`VITE_WS_BASE_URL`/`VITE_APP_ENV` in Vercel project env (confirm present first), drop the Supabase keys entirely; document in `deployment_guide.md`. Rotate the anon key if RLS review wants it. |
| `scripts/e2e_realopenai/local.env` (tracked) | **A (with caveat)** | Required by runbook `scripts/e2e_realopenai/README.md:16` and `run_scenario.sh:14-16`, `start_backend.sh:22-24`. Keys: local docker `DATABASE_URL/DB_*`, `REDIS_URL`, `REDIS_KEY_PREFIX`, `APP_ENV`, `LOG_LEVEL`, `JWT_ALGORITHM=HS256`, `JWT_SECRET_KEY` (comment :20-22: "純本機測試密鑰，非生產設定"). Not matched by any ignore rule (root `.gitignore:21` is `backend/.env` only). | Low: dev-only values, identical in spirit to `docker-compose.yml:62-63`. | Keep. Optionally rename to `local.env.example` + copy step to avoid the `.env` smell; not required. |
| `frontend/.env.local`, `flutter_app/.env.local` | A (ignored) | `frontend/.gitignore:60`, `flutter_app/.gitignore:54` (`.env*`); files exist on disk (1276 B each), not in index. ✔ | — | — |
| `backend/.env` | A (ignored) | `.gitignore:21 backend/.env`; exists (1034 B), not in index. ✔ `docker-compose.yml:44-48` requires it to exist. | — | — |
| `frontend/tsconfig.node.tsbuildinfo`, `frontend/tsconfig.tsbuildinfo` | A (ignored) | `frontend/.gitignore:45 *.tsbuildinfo`; on disk 48K/8K, not tracked. ✔ | — | — |
| `frontend/vite.config.d.ts` | B (already staged `D`) | emitted by `tsc -b` (`.gitignore:102-103` WIP) | none | commit the deletion with theme 3 |
| `backend/.env.example`, `frontend/.env.example`, `frontend/.env.local.example` | A | templates, placeholders only | — | — |
| `.log`, `results/*.json`, `.DS_Store`, `.pem/.p8/.p12` | none tracked ✔ | `scripts/e2e_realopenai/.gitignore:1-2`, root `.gitignore:62-63` | — | — |

---

## 3. Untracked / ignored junk on disk

All sizes from `du -sh`. "Documented as needed" = referenced by a doc/skill as an artifact to keep.

### Safe to delete now (regenerable, nothing documents them as needed)

| Path | Size | Regenerated by | Doc reference | Cat |
|---|---|---|---|---|
| `flutter_app/build/` (incl. `flutter_driver_commands_0.log` 147 MB) | **2.6 GB** | `fvm flutter build/run/test` | none (`.gitignore` only) | B |
| `flutter_app/.dart_tool/` | **2.8 GB** | `fvm flutter pub get` | none | B (re-fetch ~minutes) |
| `graphify-out/`, `backend/graphify-out/`, `frontend/graphify-out/`, `flutter_app/graphify-out/`, `docs/graphify-out/` | 64 + 52 + 3.6 + 17 + 6.2 ≈ **143 MB** | `./scripts/refresh_graphify.sh` (AST only) + `/graphify docs`; `AGENTS.md:1-12`, `CLAUDE.md:29` "可重建" | `AGENTS.md` says to **use** them when present — deleting disables graphify queries until rebuilt (`docs/graphify-out/` needs a Gemini/Codex semantic pass, `refresh_graphify.sh:10-13`) | B for the four code graphs; **C** for `docs/graphify-out/` (needs API key to rebuild; also contains three `.graphify_before_*.json` snapshots 0.5 MB each that are one-off diagnostics) |
| `frontend/dist/` | 2.4 MB | `npm run build` | — | B |
| `frontend/playwright-report/`, `frontend/test-results/` | 524 K / 292 K | `npm run test:e2e` | — | B |
| `frontend/tsconfig.node.tsbuildinfo`, `frontend/tsconfig.tsbuildinfo` | 48 K / 8 K | `tsc -b` | — | B |
| `scripts/e2e_realopenai/uvicorn.log`, `celery_worker.log` | 452 K / 108 K | next `start_backend.sh` / celery run | README names them as *where logs go*, not as evidence | B |
| `.DS_Store` ×5 (`./`, `frontend/`, `backend/`, `docs/`, `flutter_app/`) | 8 K each | Finder | — | B |
| `__pycache__` / `.pytest_cache` (32 dirs; root `.pytest_cache` + `backend/.pytest_cache` 716 K) | 7.9 MB | pytest / import | — | B |
| `.ruff_cache/` (root) | 48 K | ruff | absent from `git status` (ruff self-ignores via its own `.gitignore`) | B |

### Keep (cache that speeds up dev, or evidence)

| Path | Size | Why keep | Cat |
|---|---|---|---|
| `scripts/e2e_realopenai/results/*.json` (21 files, ignored via `scripts/e2e_realopenai/.gitignore:1`) | 1.0 MB | Cited as evidence: `docs/TODO.md:117,120,179,1637,1643`, `.claude/skills/e2e-real-openai/SKILL.md:25,53,74`, `docs/perf_audit_2026-08-22.md:72,97`. Not tracked, so this disk copy is the only copy. | A |
| `backend/venv/` | 379 MB | dev venv; `CLAUDE.md:35` uses `venv/bin/pytest` | A |
| `frontend/node_modules/` | 255 MB | `npm ci` | A |

Total reclaimable now: ≈ 5.5 GB (of the 6.3 GB working tree; `.git` is 22 MB).

---

## 4. `scripts/`

Tracked: 13 files (`git ls-files scripts`), + 3 new untracked tests. CI runs `python -m pytest scripts/tests -q` (`ci.yml:80-81`, WIP) and `i18n_staleness.yml:57-62` runs `check_translations.py`.

| File | Lines | Referenced by | Cat | Note |
|---|---|---|---|---|
| `check_translations.py` | 938 | `CLAUDE.md:38`, `docs/README.md:26-27`, `i18n_staleness.yml`, `.claude/skills/i18n-language-consistency`, `flutter_app/README.md`, `frontend/i18next-parser.config.js`, `frontend/scripts/i18n-extract-check.mjs`, `scripts/tests/test_check_translations.py` | A | WIP adds `--locales-dir`; Flutter dir no longer a "mirror" |
| `red_flag_eval.py` | 171 | `docs/TODO.md` only | A | manual real-OpenAI regression; `cd backend && venv/bin/python ../scripts/red_flag_eval.py` (:11) |
| `normalize_graphify_labels.py` | 59 | `scripts/refresh_graphify.sh:24` | A | graphify helper |
| `refresh_graphify.sh` | 28 | `AGENTS.md:12`, `docs/graphify_codex.md:36-44` | A | hard-fails if `docs/graphify-out/graph.json` missing (:10-13) |
| `e2e_realopenai/driver.py` | 5397 | `.claude/skills/{e2e-real-openai,voice-pipeline-invariants}`, 9 backend unit tests import its corpora (`backend/tests/unit/pipelines/patient_facing_corpus.py` etc.), `docs/app_architecture.md`, `docs/TODO.md`, `scripts/tests/test_e2e_dontknow_analysis.py` | A | **E**: 5.4 kLOC single file imported by unit tests via `importlib` path hacks — candidate to split personas/analyzers into a package; not a removal |
| `e2e_realopenai/run_scenario.sh` | 23 | README, skill | A | |
| `e2e_realopenai/start_backend.sh` | 28 | README, skill, `run_scenario.sh` | A | WIP de-hardcodes paths |
| `e2e_realopenai/compose.override.yml` | 12 | README, skill | A | |
| `e2e_realopenai/local.env` | 24 | README:16, `run_scenario.sh`, `start_backend.sh` | A | see §2 |
| `e2e_realopenai/README.md` | 655 | `.claude/skills/e2e-real-openai`, `voice-pipeline-invariants`, `docs/TODO.md`, `CLAUDE.md:26` | A | **E**: `:24` still points `E2E=` at a dead `/private/tmp/claude-501/-Users-chun-Desktop-GU-0410/…/scratchpad/e2e` path and `:7-8` cites 2026-06 branches/SHAs — stale runbook lines |
| `e2e_realopenai/.gitignore` | 2 | — | A | ignores `results/`, `*.log` |
| `e2e_realopenai/results/` (dir) | — | see §3 | A (local only) | |
| `tests/__init__.py`, `tests/test_check_translations.py` (361) | | `ci.yml:80-81`, `i18n_staleness` indirectly | A | run by CI |
| `tests/test_e2e_dontknow_analysis.py`, `test_ios_build_banner.py`, `test_locale_lists_in_sync.py` (new) | 65/28/42 | `ci.yml:80-81`, `docs/perf_audit_2026-08-22.md:73` ("20 通過") | A | `test_ios_build_banner.py` shells out to `bash` and reads `flutter_app/tool/build_ios_testflight.sh` by relative path — fine on ubuntu-latest |
| `verify_multilang_migration.sh` (deleted in WIP) | 207 | **none** (`git grep HEAD` → only self) | B | deletion is safe; see §1.2 |

Scripts referenced by docs that do not exist: `scratchpad/seed_research_e2e.py` (`docs/research_analytics.md:137` at HEAD; WIP already removes the mention). No other dangling script refs found (backtick-path scan over docs/skills → 0 missing).

---

## 5. `docs/`

### 5.1 Inventory (47 tracked files; `docs/README.md` index = "Idx")

| File | Purpose (1 line) | Idx | Cat |
|---|---|---|---|
| `README.md` | entry point / scope decision / index | — | A |
| `AGENTS.md` | deployment detail guide for agents (manual deploy flow) | ✔ :41 | A (name clashes with root `AGENTS.md`, see 5.3) |
| `TODO.md` (2388 L, 192 KB) | living backlog + lessons | ✔ :52 | A; **E**: largest doc in repo, 109 TODO/FIXME tokens, sections §R/§V/§W/§U mixed with 2026-04 items — candidate to move closed 2026-04…06 sections to `archive/` |
| `app_architecture.md` | authoritative architecture + pipeline invariants | ✔ :36 | A |
| `system_overview.md` | onboarding overview | ✔ :36 | A with stale lines (5.4) |
| `consultation_flow.md` | end-to-end flow | ✔ :38 | A |
| `session_data_inventory.md` | per-session data landing incl. soft delete | ✔ :39 | A |
| `research_analytics.md` | /research feature doc | ✔ :40 | A |
| `deployment_guide.md` (616 L) | manual deploy + env + iOS ops | ✔ :41-43 | A |
| `ios_release_settings.md` | TestFlight values (single source) | ✔ :43 | A |
| `push_troubleshooting.md` | push runbook | ✔ :44 | A |
| `supabase_connection_guide.md` | DB connection/incident runbook | ✔ :45 | A |
| `railway_celery_runbook.md` | how to split worker/beat into separate Railway services | ✔ :46 | A/**C**: describes a topology that is *not* deployed (`backend/scripts/start.sh:91-103` runs worker+beat inside the API container, `RUN_CELERY_IN_API=true`); README row "Celery worker/beat 建置" reads as current. Retitle "(optional split, not deployed)" or move to archive with the two toml files (§6) |
| `full_setup_guide.md` | local setup | ✔ :47 | A; **E**: `:10` says frontend port 3000 while `README.md:7` says dev port 5175 (`docker-compose.yml:60` whitelists both) |
| `graphify_codex.md` | Codex MCP + graphify setup | ✔ :48 | A |
| `ops_endpoint_exposure.md` | /metrics, /docs locking | ✔ :53 | A |
| `railway_region_move.md` | region migration runbook | ✔ :54 | A |
| `perf_audit_2026-08-22.md` (375 L) | perf/smoothness single source (now 10-03 + 08-22) | ✔ :55 | A; **E**: filename carries the 08-22 date but is the 10-03 authority — rename to `perf_audit.md` (update 6 inbound links) |
| `flutter_web_cutover.md` | historical Flutter Web promotion runbook | ✔ :57 | A (marked historical in WIP) |
| `DESIGN.md` | Linear-inspired design-system reference | ✔ :51 | **D**: byte-identical to `design_references/linear_app_design.md` (md5 `7cecf093…` both) |
| `design_references/linear_app_design.md` | same content | ✔ :51 (dir) | D (keep one) |
| `design_references/posthog_design.md` | PostHog reference | ✔ :51 (dir) | A |
| `runbook/add_new_language.md`, `runbook/i18n_rollout.md` | i18n runbooks | ✔ :49 | A |
| `observability/red_flag_coverage_alert.md`, `sentry_lang_alerting.md`, `grafana_i18n_overview.json` | alert/dashboard defs | ✔ :50 (dir) | A |
| `supabase_rls_policies.sql` (337 L) | RLS policies | **✘ not indexed** (only `TODO.md:375`) | **C**: is it applied to `gu-voice-prod`? No doc says; add a README row or move to `backend/` / archive |
| `archive/README.md` + 14 archived md + `spec_2026-04/` (6 files, 21 kLOC) | historical | ✔ :59-61 | A (explicitly "勿當現行讀") |

Untracked in docs: `docs/.DS_Store` (junk), `docs/graphify-out/` (§3).

### 5.2 Relative-link check

Scanned 58 files (`docs/**/*.md`, `CLAUDE.md`, `AGENTS.md`, `flutter_app/README.md`, `scripts/e2e_realopenai/README.md`, `.claude/skills/*/SKILL.md`): 221 relative links, **31 broken — all inside `docs/archive/`**, 0 broken in current docs/skills/CLAUDE.md (the WIP fixed 14 absolute-path links in `docs/AGENTS.md` and `full_setup_guide.md`).

| File:line | Broken target | Cat |
|---|---|---|
| `docs/archive/sidebar_structure_issue_audit.md:133-416` (25 links) | `/Users/chun/Desktop/GU_0410/frontend/...`, `.../backend/...` absolute paths to a machine path that no longer exists | E (archive; leave or bulk-replace prefix with `../../`) |
| `docs/archive/e2e_realopenai_audit_2026-06-28.md:12` | `./app_architecture.md`, `./TODO.md` (now one level up) | E |
| `docs/archive/專案開發進度.md:16` | `./TODO.md` | E |
| `docs/archive/system_issues_and_risks.md:8` | `./system_overview.md`, `./deployment_guide.md` | E |
| `docs/archive/spec_2026-04/api_spec.md:2444` | `research_analytics.md` | E |

### 5.3 Duplicates

| Pair | Finding | Cat |
|---|---|---|
| `docs/DESIGN.md` ↔ `docs/design_references/linear_app_design.md` | **byte-identical** (`cmp` OK) | D — delete one, keep README link to the survivor |
| `docs/DESIGN.md` ↔ `frontend/DESIGN.md` | different: frontend copy is 1200 L project-specific "Stripe 60% + Intercom 25% + Sentry 15%"; **no doc, skill or README links `frontend/DESIGN.md`** (`grep` over CLAUDE.md/AGENTS.md/docs/.claude → 0) | C — either index it from `docs/README.md` (it is the *actual* app design system; `design-taste-frontend` skill does not cite it) or archive |
| `docs/AGENTS.md` (143 L, deployment guide) ↔ root `AGENTS.md` (12 L, graphify rules for Codex) | different purpose, same filename; `CLAUDE.md:24` calls docs one "部署細節指南" | E — rename `docs/AGENTS.md` → `docs/deployment_agents_guide.md` or fold into `deployment_guide.md` (which already holds the same two-step flow) |
| `docs/graphify_codex.md` ↔ `.codex/skills/graphify/SKILL.md` (41 KB vendored upstream skill + 8 reference files) | different: project note vs vendored tool docs | A; **C**: vendored `.codex/skills/graphify/` (12 files, 112 KB) is a copy of the installed graphify skill (`.graphify_version` 6 B) — will drift from the uv-installed version; consider removing from git if the hook/MCP works from the global install |

### 5.4 Stale statements (E — doc fixes)

| File:line | Statement | Contradicted by |
|---|---|---|
| `docs/system_overview.md:385` | "`main` branch 直接部署到正式環境（Vercel + Railway 自動觸發）" | `CLAUDE.md:43`, `docs/README.md:4`, `docs/AGENTS.md:11-19`, and `system_overview.md:121` itself ("部署是手動的") |
| `docs/system_overview.md:102` | "Python 3.11" | matches `backend/Dockerfile:9,29` (`python:3.11-slim`) but **CI tests on 3.12** (`ci.yml:61`) and `full_setup_guide.md:15` says "3.12+". Real drift is CI↔Dockerfile, not just the doc (see §7) |
| `docs/system_overview.md:121` | "`e2e-playwright` 佔位" | WIP `ci.yml:183-218` enables the job |
| `docs/full_setup_guide.md:10` | frontend `http://localhost:3000` | `docs/README.md:7` "前端 dev port = 5175" |
| `CLAUDE.md:27` | "`supabase/` → 本機 supabase CLI 設定（untracked）" | directory does not exist on disk (`ls -d supabase` → ENOENT) |
| `scripts/e2e_realopenai/README.md:24` | `E2E=/private/tmp/claude-501/-Users-chun-Desktop-GU-0410/…` | dead scratchpad path from a 2026-06 session |
| `docs/railway_celery_runbook.md` (whole) | separate worker/beat services | `backend/scripts/start.sh:91-103` single-container; `railway.toml:28-32` |

---

## 6. Config duplication / conflict

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `backend/railway-worker.toml`, `railway-beat.toml`, `backend/scripts/start_worker.sh`, `start_beat.sh` | **C** | Referenced only by `docs/railway_celery_runbook.md:33-34,56,80` and `docs/TODO.md:209`; not by `deployment_guide.md`, `deploy-production` skill, `railway.toml`, or `Dockerfile`. `start.sh:91-96` states Railway has **no** worker/beat service; `railway.toml:28-32` pins `numReplicas=1` for that reason. Railway reads only `railway.toml` (filename fixed) — the other two tomls are never auto-applied. | None at runtime (dead unless someone follows the runbook). | Keep as the documented escape hatch **or** move all four + runbook to `docs/archive/`. Do not delete silently: `start.sh:95` tells readers to "依 docs/railway_celery_runbook.md 拆". |
| `docker-compose.yml` vs `backend/.env.example` vs `config.py` | A / E | `REDIS_KEY_PREFIX`: compose `gu_dev:` (:56), `.env.example` `gu_prod:` (:344), `config.py:123` `gu:`, `local.env` insists `gu:` with the comment that `conversation_handler` hard-codes `gu:`. Current code: `conversation_handler.py:53-54` still hard-codes `gu:session:{id}:context/state` while guidance key uses `settings.REDIS_KEY_PREFIX` (:1721, :2072; comment :1716-1717 says the hard-coded guidance read was fixed). | Context/state keys ignore the prefix → multi-env on one Redis would collide for those two keys only; functional otherwise. | E: make `_SESSION_CONTEXT_KEY/_SESSION_STATE_KEY` use the prefix, then drop the "必須是 gu:" note in `local.env:7-9`. |
| `DB_POOL_SIZE/DB_MAX_OVERFLOW` | A | `.env.example:321-322` = 5/5 (Supabase pooler) vs `config.py:89-90` = 10/20 default; documented intentionally (`.env.example:320`). | — | — |
| `WORKERS` vs `APP_WORKERS` | E | `start.sh:49` reads `WORKERS`; `config.py:55` and `.env.example:277` define `APP_WORKERS`. Two names, one concept. | Setting `APP_WORKERS` on Railway changes nothing. | Make `start.sh` read `${APP_WORKERS:-${WORKERS:-4}}` or document. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | A | `.env.example:374` 15 = `config.py:178-179` default 15 ✔ (HEAD `.env.example` said 30) | — | — |
| `frontend/vercel.json` | A / E | CSP `connect-src` still allows `https://*.supabase.co wss://*.supabase.co` (:40) although the SPA no longer talks to Supabase (`vite-env.d.ts:6`). `regions: ["hkg1"]` fine. | Over-broad CSP only. | Trim Supabase origins. |
| `frontend/nginx.conf` + `frontend/Dockerfile` | A | used only by `docker-compose.yml:72-80` (local full stack); Vercel ignores both. Dockerfile ARG defaults point at `localhost:8000` (:24-26). | — | — |
| `.github/workflows/ci.yml` vs `CLAUDE.md:34-36` / `docs/README.md:17-19` | A | CLAUDE lists `npm run lint/type-check/test/test:e2e/build`, `venv/bin/pytest tests/`, `fvm flutter analyze/test`; CI runs lint, type-check, test, build, e2e, `pytest tests/unit`, `pytest scripts/tests`, `flutter analyze/test`. Consistent. `check_translations.py` runs in `i18n_staleness.yml` (PR path-filtered), not in `ci.yml` — matches README. | — | — |
| **CI Python 3.12 vs prod Python 3.11** | **C** | `ci.yml:61` `python-version: "3.12"`; `backend/Dockerfile:9,29` `python:3.11-slim`; `ops_endpoint_exposure.md:22` observed `3.11.16` in prod. `check_translations.py:27` "Python 3.12 標準庫". | Tests pass on a Python the image never runs; 3.12-only syntax would ship untested. | Align: bump Dockerfile to 3.12-slim (then fix `system_overview.md:102`) or set CI to 3.11. |
| `.codex/` (12 files, tracked) | A | `docs/graphify_codex.md:7-10` documents it; `hooks.json` = one `PreToolUse` Bash hook → `graphify hook-check`; `config.toml` starts `graphify-mcp graphify-out/graph.json` with `cwd=".."`. | Hook fails if `graphify` not on PATH (doc :22-23 says so). | Keep `config.toml`/`hooks.json`; see 5.3 on the vendored skill copy. |
| `.claude/skills/` (7 skills, 2063 L md) | A | tracked by design `CLAUDE.md:28,60-70` | — | — |
| root `AGENTS.md` | A | graphify rules; `docs/graphify_codex.md:9` | — | — |
| `supabase/` | — | does not exist; `.gitignore` has no rule for it; `CLAUDE.md:27` mentions it | — | doc fix (5.4) |

---

## 7. CI

**`ci.yml` (WIP) — 4 jobs, trigger PR + push main, `permissions: contents: read`:**

| Job | Steps | Notes |
|---|---|---|
| `backend-tests` | Postgres 15 + Redis 7 services; Python 3.12; `pip install -r requirements-dev.txt`; `pytest tests/unit -q --junitxml`; `python -m pytest scripts/tests -q` (repo root); upload junit | `--ignore=tests/unit/api` dropped (dir absent). `scripts/tests` step needs only pytest (installed above). Env uses HS256 + placeholders (`ci.yml:44-52`). |
| `frontend-checks` | Node 22; `npm ci`; lint; type-check; **`npm test`** (node `--experimental-strip-types --test`, 15 test files); build with `VITE_*` placeholders | Supabase placeholders now unnecessary (§1 e). `engines.node>=22.17` enforced only by npm warning. |
| `flutter-checks` | `subosito/flutter-action@v2` 3.41.3; `pub get`; `flutter analyze`; `flutter test`; `flutter test --no-pub test/session_calendar_test.dart` with `TZ=America/New_York` | Uses bare `flutter` (correct in CI; `fvm` is a local concern, `CLAUDE.md:80`). |
| `e2e-playwright` | Node 22; `npm ci`; `npx playwright install --with-deps --only-shell chromium`; `npm run test:e2e`; upload report on failure | **Now real**: `frontend/playwright.config.ts:13` `testDir ./tests/e2e`, `:41-45` `webServer` with `VITE_ENABLE_MOCK=true VITE_MOCK_ROLE=patient`; 3 specs (`i18n_en_no_cjk`, `multiselect_complaint`, `other_complaint`). `system_overview.md:121` "佔位" is stale. **C**: first green run on GitHub not yet observed (nothing committed). |

**`i18n_staleness.yml`:** PR-only, path-filtered; job `translation-coverage (web|ios)` matrix (Python 3.12, `check_translations.py --locales-dir … --mirrors …`, JSON artifact per client, PR comment upsert with per-client marker, fail on threshold) + `extract-keys-check` (Node 22, `npm run i18n:extract:check`). ios matrix passes `--mirrors ""` (coverage only) — consistent with `DEFAULT_MIRROR_DIRS` change.

**Local baseline vs CI:** same commands; local backend run is `venv/bin/pytest tests/` (includes integration/e2e dirs) vs CI `tests/unit` only — expected (`docs/README.md:19`). `test_smoothness_queries_pg.py` (real PG) is therefore **not** run in CI even though a Postgres service is provisioned — **E**: add `pytest tests/integration -q` guarded by the service env.

---

## 8. Size / hygiene metrics

| Metric | Value |
|---|---|
| `git count-objects -vH` | loose 2193 objects / 16.74 MiB; pack 4317 objects / 4.34 MiB; `.git` = 22 MB |
| Tracked files | 926 (backend 324, flutter_app 281, frontend 233, docs 47, scripts 14, .codex 12, .claude 7, .github 2, root 4) |
| Working tree on disk | 6.3 GB (≈ 5.4 GB is `flutter_app/build` + `.dart_tool`) |
| Largest tracked (du -k) | `flutter_app/assets/images/urosense_mascot.png` 1252K, `frontend/public/logo.png` 1056K, `…/Icon-App-1024x1024@1x.png` 880K, `LaunchImage@3x.png` 280K, `scripts/e2e_realopenai/driver.py` 256K, `frontend/package-lock.json` 240K, `docs/TODO.md` 192K, `backend/app/websocket/conversation_handler.py` 156K, `backend/app/pipelines/red_flag_detector.py` 148K, `docs/archive/spec_2026-04/{backend,infrastructure}_spec.md` 144K each |
| LOC (tracked) code / md / json | backend 78,002 / 0 / 0 · frontend 22,354 / 1,200 / 21,848 · flutter_app 28,916 / 217 / 8,029 · docs 0 / 34,059 / 108 · scripts 7,017 / 655 / 0 · .claude 0 / 2,063 / 0 · .github 424 / 0 / 0 |
| TODO/FIXME tokens | docs md: 109 · backend .py: 78 · flutter .dart: 43 · frontend .ts/.tsx: 7 |
| `.env.production` first commit | `a19f9d2` 2026-04-12 (initial commit) |

**E**: `frontend/public/logo.png` (1 MB) and the 1.2 MB mascot PNG are the two biggest blobs; worth an optipng/WebP pass if bundle size matters (perf_audit:162 says bundle size is not a current concern).

---

## 9. Parent directory `/Users/chun/Desktop/GitHub專案/chatgu` (not a git repo; names/sizes only; **nothing opened or touched; user decision**)

| Entry | Size | Note |
|---|---|---|
| `gu-voice/` | 6.3 GB | the repo |
| `gu-voice-main.zip` | 3.4 MB, dated 2026-08-17 09:22 | same timestamp as the 08-17 import of most docs (`docs/archive/*` mtime 08-17 09:25) — almost certainly an old GitHub export of the repo; redundant with git history |
| `a7ce22c1-745c-44ff-8c9a-475615352b20.png` | 1.2 MB, 2026-08-25 | screenshot |
| `login-new.png` | 24 K, 2026-08-23 | screenshot (login-page redesign, cf. `docs/README.md:52` §W) |
| `.playwright-mcp/` | 2.1 MB, 207 entries, last 2026-09-09 | Playwright MCP session artifacts (`.gitignore:98-99` ignores the same name inside the repo) |
| `開發文件/` | 20 K, 1 entry `0_部署ios` | user notes |
| `firebase-secrets/` | 12 K, 3 files (`*.p8`, `*-Info.plist`, `gu-voice-*-fbsvc-*.json`), mode `drwx------` | **DO NOT OPEN** — APNs key + Firebase service account; `.gitignore:61-63` explicitly says they live here "防手滑複製進來" |
| `.claude/` | empty dir | — |
| `.DS_Store` | 8 K | Finder |

All: user decision; not touched.

---

## Summary counts

| Category | Count | Items |
|---|---|---|
| **A keep** | ~40 | all current docs, scripts (12), skills, `.codex` config, `local.env`, `results/`, venv/node_modules, CI jobs |
| **B safe to remove** | 15 | 3 WIP deletions (`pdf_share`, `png_share`, `verify_multilang_migration.sh`), staged `vite.config.d.ts`, on-disk junk: `flutter_app/build`, `.dart_tool`, 4 code `graphify-out/`, `frontend/dist`, `playwright-report`, `test-results`, 2 tsbuildinfo, 2 e2e logs, 5 `.DS_Store`, pycache/pytest/ruff caches |
| **C verify** | 12 | `frontend/.env.production` removal path, CI 3.12 vs Docker 3.11, requirements.txt transitive check, CONCURRENTLY retry idempotence, 10-10 refactor undocumented + tests not re-run after 10-10, `useDashboardConnection` mount coverage, `docs/graphify-out/` rebuild cost, `railway_celery_runbook` + 2 tomls + 2 scripts topology, `supabase_rls_policies.sql` applied?, `frontend/DESIGN.md` unreferenced, vendored `.codex/skills/graphify`, e2e-playwright first green run |
| **D duplicate** | 2 | `docs/DESIGN.md` == `design_references/linear_app_design.md`; `docs/AGENTS.md` name clash with root `AGENTS.md` |
| **E improvement** | 14 | 7 stale doc statements (5.4), 31 archive links, CI Supabase placeholders, integration tests not in CI, `WORKERS`/`APP_WORKERS`, Redis key prefix hard-code, vercel CSP Supabase origins, `perf_audit` filename, TODO.md size, `driver.py` 5.4 kLOC, PNG sizes |

## Top 10 highest-value, lowest-risk actions

1. **Commit the WIP as 5–6 commits** per §1.3 (demo tooling → docs → CI → tooling → DB/API → code), after re-running the three suites; tag `wip-snapshot-2026-10-23` already protects the tree.
2. **Write the 2026-10-10 refactor findings into `docs/TODO.md`** (CAS on status, report authz, assign_doctor validation, timeout semantics, requirements slimming) — currently zero documentation.
3. `git rm --cached frontend/.env.production` after confirming Vercel env has `VITE_API_BASE_URL`/`VITE_WS_BASE_URL`/`VITE_APP_ENV`; drop dead Supabase vars; update `deployment_guide.md`.
4. Delete `flutter_app/build/` and `flutter_app/.dart_tool/` (5.4 GB) and the four code `graphify-out/` dirs; keep `docs/graphify-out/` until a rebuild is convenient.
5. Align Python: Dockerfile `3.11-slim` → `3.12-slim` (or CI → 3.11); then fix `system_overview.md:102`.
6. Fix `docs/system_overview.md:385` (auto-deploy claim) and `:121` (e2e 佔位); fix `full_setup_guide.md:10` port; remove `supabase/` line from `CLAUDE.md:27`.
7. Delete one of `docs/DESIGN.md` / `docs/design_references/linear_app_design.md` (identical) and decide whether `frontend/DESIGN.md` is indexed or archived.
8. Remove the now-dead `VITE_SUPABASE_*` placeholders from `ci.yml:128-129` and the Supabase origins from `vercel.json:40` CSP.
9. Retitle or archive `docs/railway_celery_runbook.md` + `railway-worker.toml`/`railway-beat.toml`/`start_worker.sh`/`start_beat.sh` as "optional split (not deployed)".
10. Add `pytest tests/integration -q` to `backend-tests` (Postgres service already provisioned) so `test_smoothness_queries_pg.py` runs in CI.
