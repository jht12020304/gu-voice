# Backend codebase audit — gu-voice/backend (branch refactor/codebase-audit-2026-10)

Date: 2026-10-23. Read-only. Nothing in the repo was modified. All paths relative to `backend/` unless prefixed with `../` (repo root). Verified against the working tree (which includes ~256 uncommitted files), not HEAD.

Categories: **A** in use, keep · **B** high-confidence safe to remove (proof given) · **C** suspect, needs stated verification · **D** duplicate/mergeable · **E** performance/architecture.

Verification baseline: `venv/bin/python -m pytest tests -q -p no:cacheprovider` → **4917 passed, 2 skipped, 18.5 s** locally (the 13 extra passes vs. the 4904/3 baseline are `tests/integration/*` which ran because a local Postgres was reachable, plus `test_red_flag_cooccurrence_coverage.py:740/799` which did not skip because `../scripts/e2e_realopenai/results/` exists locally — see §10).

---

## 1. Module map and entry points

### 1a. Subpackages (one line per module; source = module docstring)

| Package / module | Purpose |
|---|---|
| `app/main.py` (377) | FastAPI entry: prod-secret enforcement (`:62-90`), lifespan (sentry → firebase → redis → partition hook → dashboard Redis subscriber, `:94-137`), middleware stack (`:161-199`), exception handlers (`:203`), gated `/metrics` + `/openapi.json` (`:243-258`), 12 routers (`:262-288`), 2 WS routes (`:299-316`), `/health` + `/healthz/deep` (`:319-377`) |
| `app/core/config.py` (521) | pydantic-settings `Settings`; explicit `DATABASE_URL`/`REDIS_URL` win over components; JWT PEM-or-path; `LANGUAGE_MAP` is the locale source |
| `app/core/database.py` | async engine; PgBouncer-safe asyncpg prepared-statement naming (`:41-56`); SSL detection from the real URL host (`:27-40`) |
| `app/core/dependencies.py` | `get_db`, `get_redis`, `get_current_user` (token blacklist check `:86`), `require_role` |
| `app/core/authz.py` | `get_user_role`, clinician scope, `clinician_session_filter` (shared by services) |
| `app/core/security.py` | bcrypt via passlib + `hash_password_async`/`verify_password_async` (`:40-47`), JWT create/verify |
| `app/core/exceptions.py` | `AppException` hierarchy + `register_exception_handlers` (3 handlers, `:321-374`) |
| `app/core/middleware.py` | `SecurityHeadersMiddleware`, `AuditLoggingMiddleware`, `RequestIdMiddleware` |
| `app/core/language_middleware.py` | resolves `?lng` / `X-Language` / `Accept-Language` into `request.state.language` |
| `app/core/rate_limit.py` | Redis sliding-window limiter, 3 policies (login / password-reset / LLM per-user) |
| `app/core/openai_client.py` | `AsyncOpenAI` singleton + tenacity retry + tiktoken budget |
| `app/core/{csrf,net,sentry,metrics,firebase,email_client,session_state}.py` | double-submit CSRF; client-IP; Sentry PII scrub; Prometheus counters; Firebase init; SendGrid/SMTP; `VALID_TRANSITIONS` state machine (single authority for REST + WS) |
| `app/cache/redis_client.py` | async Redis pool `init_redis`/`get_redis`/`close_redis` |
| `app/models/*.py` (14 ORM) | user, patient, session (soft-delete `is_deleted`), conversation (partitioned), soap_report (+revision), red_flag_alert/rule, chief_complaint, notification (+preference), fcm_device, audit_log (partitioned), exam_order, enums |
| `app/schemas/*.py` (16) | pydantic v2 request/response models; `common.JsonFloatDecimal` (Decimal→float invariant); `ws_message.py` canonical WS code payloads |
| `app/routers/*.py` (12) | thin FastAPI routers → services (see §4 for every route) |
| `app/services/*.py` (16) | business logic as static-method classes; `session_visibility.session_not_deleted()` is the soft-delete gate (53 call sites in app/) |
| `app/pipelines/llm_conversation.py` | conversation LLM engine; system prompt builder; §3b risk-factor × intake tri-state |
| `app/pipelines/supervisor.py` | background supervisor model: HPI completeness + `next_focus` guidance |
| `app/pipelines/red_flag_detector.py` | two-layer red-flag detection (rule co-occurrence + semantic LLM), 5 languages |
| `app/pipelines/soap_generator.py` | SOAP report generation (Celery path); now sanitizes patient fields (`:738-747`, working-tree change) |
| `app/pipelines/{stt,tts}_pipeline.py` | OpenAI transcription (+OpenCC s2t) / OpenAI TTS |
| `app/pipelines/patient_context.py` | `build_patient_info` — single source for WS + Celery (CLAUDE.md invariant) |
| `app/pipelines/{conclusion_policy,alert_dedup,next_focus_guard,icd10_validator,icd10_symptom_map}.py` | auto-end policy (pure functions); Redis alert dedup; re-ask guard; ICD-10 validation |
| `app/pipelines/prompts/shared.py` (1784) | ontology constants, `URO_RED_FLAGS` catalogue, `sanitize_for_prompt` (`:1752-1762`, fixed-point `#` strip present in working tree) |
| `app/websocket/conversation_handler.py` (3410) | patient WS: auth → `_validate_session` → greeting → audio/text turns → red flag/supervisor/auto-end → terminal transition + SOAP dispatch |
| `app/websocket/dashboard_handler.py` | doctor dashboard WS; Redis pub/sub cross-worker subscriber; queue/stats/alerts |
| `app/websocket/connection_manager.py` | in-process connection registry + `publish_dashboard_event` |
| `app/websocket/auth.py` | first-frame `auth` handshake for WS |
| `app/tasks/__init__.py` | Celery app (`celery_app`), `run_async`, `worker_process_init` Firebase hook, 4 beat entries |
| `app/tasks/{report_queue,notification_retry,session_timeout,partition_manager,audit_retention,audio_lifecycle}.py` | SOAP generation; APNs→FCM push retry; 60-min stale-session → cancelled (beat 5 min); monthly partitions; 7-year audit retention; audio blob cleanup |
| `app/utils/*.py` | `datetime_utils` (`utc_now`, `parse_iso`), `pagination` (`parse_cursor`), `language` (`resolve_language`), `language_detect`, `localized_field`, `i18n_messages` (1144 lines of UI strings), `complaint_fallback_i18n`, `transcript` |

### 1b. Entry points

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `scripts/start.sh` | A | Railway `railway.toml:22 startCommand`; Dockerfile `:88`; runs `alembic upgrade head` (`:70`) → Celery worker+beat in same container when `RUN_CELERY_IN_API=true` (`:104-126`) → uvicorn (`:141-151`); `wait -n` exits on first child death (`:159`) | — | keep; executable bit present (`-rwxr-xr-x`) |
| `scripts/start_worker.sh`, `scripts/start_beat.sh`, `railway-worker.toml`, `railway-beat.toml` | C | Referenced only by each other (`railway-worker.toml:9`, `railway-beat.toml:9`) and `../docs/railway_celery_runbook.md:33-34,56,80` (the "split out later" runbook). Not referenced by CI, Dockerfile, compose, `start.sh`, or any skill. `../docs/TODO.md:209` still says these files "may need to be added" (stale). Deploy skill `.claude/skills/deploy-production/SKILL.md:75` confirms the separate services do not exist. | Low | Keep as documented split-out path **or** delete all four + runbook together; do not delete half. Fix `docs/TODO.md:209`. |
| `Dockerfile:9,29` `python:3.11-slim` | C | CI pins 3.12 (`../.github/workflows/ci.yml:61`), venv is 3.12.14 — production image is a different minor version than everything tested | Low–Med | Verify prod runs 3.11; align to 3.12 or document |
| `app/tasks/__init__.py:44-51` autodiscover + `:83-104` beat_schedule (4 tasks) | A | `celery -A app.tasks.celery_app` in `start.sh:109,119` | — | keep |
| `alembic/` (23 versions, latest `20261003_1600-notification_paging_indexes.py`, uncommitted) | A | `start.sh:70`; `alembic/env.py:38` uses sync `settings.DATABASE_URL` (psycopg2) | — | see §7 for env.py SSL-detection drift |

### 1c. Request flow (summary)

- REST: `main.py` → router (`require_role`/`get_current_user` from `core/dependencies.py`) → `services/*` static methods (authz via `core/authz.py`, soft-delete via `services/session_visibility.py`) → ORM → pydantic response (`JsonFloatDecimal` for Decimals). Global exception handlers (`core/exceptions.py:321-374`) — routers have no try/except boilerplate left (see §5).
- WS patient: `main.py:299` → `websocket/auth.py` handshake → `conversation_handler.conversation_websocket` (`:491`) → per turn `_handle_audio_chunk` (`:1209`, STT) / `_handle_text_message` (`:1622`, LLM stream + red-flag + supervisor + auto-end) → terminal transition `_update_session_status` (`:3143`) → `report_queue.generate_soap_report.delay` + dashboard publish + doctor notifications (the "six things").
- WS dashboard: `main.py:309` → `dashboard_handler.dashboard_websocket`; cross-worker events via Redis channel (`connection_manager.publish_dashboard_event:329`, subscriber started in lifespan `main.py:116-126`).
- Celery: `report_queue` (SOAP → `soap_generator` → `report_generated` publish + notifications), `notification_retry` (APNs/FCM), beat: `session_timeout` (5 min), `partition_manager` (monthly), `audit_retention` (monthly), `audio_lifecycle` (monthly). REST status changes share the same SOAP trigger via `session_service._after_status_transition` (`:176`).

---

## 2. Unused imports (ruff F401 / F841 — all 50 hits verified)

Proof method: `grep -cw <name> <file>` = 1 means the only occurrence is the import line; for app symbols additionally grepped `tests/`, `../scripts/`, `../docs/`, `../.github` for string/attribute use (`ch.<name>`, `monkeypatch.setattr("app.…")`, `patch("app.…")`). The only string-target patches in the whole suite are `"app.core.sentry.sentry_sdk.set_tag"` (×4) and `"app.cache.redis_client.get_redis"` (×3) — none touch the symbols below.

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `alembic/versions/20260418_1400-…:27 import sqlalchemy as sa` | B | no `sa.` in file | none | optional; editing historical migrations has no value — leave |
| `app/core/email_client.py:15 typing.Any` | B | 1 occurrence | none | remove |
| `app/core/middleware.py:14 typing.Callable` | B | 1 occurrence | none | remove |
| `app/models/audit_log.py:12 sqlalchemy.Text` | B | 1 occurrence | none | remove |
| `app/models/notification_preference.py:11 typing.Optional` | B | 1 occurrence | none | remove |
| `app/pipelines/red_flag_detector.py:12 uuid`, `:13 Optional` | B | no `uuid.`/`Optional` use (`grep -n "uuid\.\|Optional"` → only `:13`) | none | remove |
| `app/pipelines/supervisor.py:26 AIServiceUnavailableException` | B | 1 occurrence in file (raised only in llm_conversation/soap_generator) | none | remove |
| `app/pipelines/supervisor.py:45 get_message as _i18n_get` | B | `grep -c _i18n_get` = 1 | none | remove |
| `app/pipelines/tts_pipeline.py:9 typing.Any` | B | 1 occurrence | none | remove |
| `app/routers/{admin,alerts,audit_logs,patients,sessions}.py:13 AppException` | B | no `except AppException` in those files (`grep -n AppException app/routers/*.py` → only `auth.py:108` uses it); global handlers registered `main.py:203` | none | remove 5 imports |
| `app/routers/auth.py:7 uuid.UUID` | B | 1 occurrence | none | remove |
| `app/routers/auth.py:34 TokenResponse` | B | 1 occurrence; alias `app/schemas/auth.py:168 TokenResponse = LoginResponse` has **no other consumer** (not in `schemas/__init__.py`, not in tests) | none | remove import **and** the alias at `schemas/auth.py:168` |
| `app/services/auth_service.py:29 ValidationException` | B | 1 occurrence | none | remove |
| `app/services/conversation_service.py:15 Session` | B | 1 occurrence | none | remove |
| `app/services/notification_service.py:9 json` | B | `grep -n "json\."` → 0 | none | remove |
| `app/websocket/conversation_handler.py:35 count_critical_risk_factors_for_complaint` | B | 1 occurrence in file; tests import it from `app.pipelines.prompts.shared` (`test_risk_factor_quota_intake_filtered.py:27`, `test_risk_factors.py:19`), never via `ch.` | none | remove |
| `conversation_handler.py:475 coerce_hpi_pct as _coerce_hpi_pct` | **A** | `tests/unit/websocket/test_auto_conclude.py:22` imports `_coerce_hpi_pct` **from conversation_handler** (comment `:472-473` documents the re-export) | — | keep (or move that test import to `conclusion_policy` first) |
| `conversation_handler.py:483 RED_FLAG_SEVERITY_RANK as _RED_FLAG_SEVERITY_RANK` | B | no `ch._RED_FLAG_SEVERITY_RANK` / `RED_FLAG_SEVERITY_RANK` in tests except `alert_dedup` direct import | none | remove |
| `conversation_handler.py:484 SESSION_EMITTED_RED_FLAGS_KEY as _SESSION_EMITTED_RED_FLAGS_KEY` | **A** | `tests/unit/websocket/test_red_flag_dedup.py:25`, `test_e84_red_flag_title_localization.py:25` use `ch._SESSION_EMITTED_RED_FLAGS_KEY` | — | keep |
| `conversation_handler.py:485 alert_dedup_identity as _alert_dedup_identity` | B | tests call `alert_dedup.alert_dedup_identity` directly (`test_red_flag_audit_2026_08.py:1585-1601`) | none | remove |
| `conversation_handler.py:2951 from app.models.patient import Patient` (local) | B | local import, unused in function | none | remove |
| `app/websocket/dashboard_handler.py:320 import json` (local) | B | shadows module-level `import json` at `:13` which is the one used (`:233,:494,:577`) | none | remove local import |
| `tests/unit/core/test_config_env_precedence.py:13-17 os, tempfile, Path, pytest` | B | each 1 occurrence; no fixtures/side effects | none | remove |
| `tests/unit/core/test_rate_limit.py:19 Optional` | B | 1 occurrence | none | remove |
| `tests/unit/middleware/test_i18n_error_handler.py:16 pytest` | B | 1 occurrence | none | remove |
| `tests/unit/pipelines/test_red_flag_rule_layer_w1.py:21 AsyncMock` | B | 1 occurrence | none | remove |
| `tests/unit/services/test_alert_service_authz.py:23 dataclasses.field` | B | 1 occurrence | none | remove |
| `tests/unit/services/test_get_current_user_blacklist.py:20 time`, `:23 Optional` | B | 1 occurrence each | none | remove |
| `tests/unit/services/test_patient_authorization.py:19 Any` | B | 1 occurrence | none | remove |
| `tests/unit/services/test_red_flag_confidence.py:18 AsyncMock` | B | 1 occurrence | none | remove |
| `tests/unit/services/test_red_flag_confidence.py:258 alert = _run(AlertService.create(...))` (F841) | B | result unused; assertions read `db.added` | none | drop the binding, **keep the call** |
| `tests/unit/services/test_refresh_token_rotation.py:29 UserRole` | B | 1 occurrence | none | remove |
| `tests/unit/tasks/test_audio_lifecycle.py:14 Any`, `tests/unit/tasks/test_audit_retention.py:14 Any` | B | 1 occurrence each | none | remove |
| `tests/unit/tasks/test_audit_retention.py:179 call_count = {"n": 0}` (F841) | B | never read | none | remove |
| `tests/unit/tasks/test_audit_retention.py:191 factory = patch_factory(_provide)` (F841) | B | `patch_factory` installs the monkeypatch (side effect) — only the name is dead | none | drop binding, **keep the call** |
| `tests/unit/utils/test_localized_field.py:14 pytest`, `tests/unit/utils/test_resolve_language.py:15 field`, `:18 pytest` | B | 1 occurrence each | none | remove |
| `tests/unit/websocket/test_auth_handshake.py:21 Any` | B | 1 occurrence | none | remove |
| `tests/unit/websocket/test_early_sentence_stream.py:49 result = run_text_turn(...)` (F841) | B | assertions use `cap.messages_of_type` | none | drop binding, keep call |

Net: 46 B, 2 A (`_coerce_hpi_pct`, `_SESSION_EMITTED_RED_FLAGS_KEY`), 0 C. `ruff --fix` would wrongly delete the two A re-exports → fix by hand or add `# noqa: F401` on those two lines.

---

## 3. Dead functions / classes / methods (vulture candidates verified)

Discarded as false positives (no table rows): all FastAPI handlers in `app/main.py`/`app/routers/*` (routes, see §4); pydantic `field_validator`/`model_validator` methods and their `cls`; `model_config`; every schema field (pydantic serializes them); every ORM column / relationship (`creator`, `deleter`, `reviewer`, `acknowledger`, `fcm_devices`, `deleted_at`, …) — DB-mapped; enum members (`SessionStatus`, `DevicePlatform.IOS/ANDROID/WEB`, `Gender`, `AuditAction.READ/EXPORT`, …) — stored DB values; middleware `dispatch`; `register_exception_handlers` targets (`exceptions.py:321,342,374` registered at `main.py:203`); Celery task bodies (`check_session_timeouts`, `ensure_monthly_partitions`, `cleanup_old_audit_partitions`, `cleanup_old_audio_files` — all in `beat_schedule` `tasks/__init__.py:83-104`), `_init_worker` (signal-connected `:75`), `report_queue.py:26 on_failure` (Celery `Task` hook); attribute writes flagged "unused attribute" (`read_at`, `reviewed_at`, `deleted_at`, `alert_session`, `patient_facing_localized`) are ORM/pydantic assignments; `next_focus_guard.py:205 matched_fields` is a `NamedTuple` field built positionally (`FocusVerdict((), ())` `:216`).

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `app/core/config.py:92 DATABASE_URL` (property) | A | `alembic/env.py:38 _sync_url = settings.DATABASE_URL`; `tests/unit/core/test_config_env_precedence.py:63-121` | — | keep |
| `config.py:53-55 APP_HOST / APP_PORT / APP_WORKERS` | B | zero readers in app/tests/scripts/CI; `start.sh:48-49` reads shell `PORT`/`WORKERS`, not these; the 23 dynamic `getattr(settings, "…")` sites in app/ name other keys; only `docs/archive/*` mention them | none | remove fields + `.env.example:14-16` |
| `config.py:324 RED_FLAG_SEMANTIC_ONLY_THRESHOLD` | B | no reader anywhere in app/tests/scripts (`grep -rnw`); only `.env.example:139` + `docs/archive/i18n_plan.md:258`; not in any `getattr(settings,…)` | none | remove field + `.env.example:139`; or implement TODO-M8 — today it is a no-op env var |
| `config.py:467-480 parse_cors_origins / parse_disabled_languages` | A | `@field_validator` | — | keep |
| `config.py:493 ACTIVE_LANGUAGES` | A | `tests/unit/utils/test_i18n_messages.py:132`, `test_i18n_message_locale_parity.py:6`, `test_admin_toggle_self_i18n.py:64,90`; no app reader (app uses `SUPPORTED_LANGUAGES`) | — | keep (test contract) |
| `app/core/exceptions.py:272 InternalErrorException` | B | never raised/imported; only mentioned in a docstring `:249`; no test | none | remove class + docstring mention |
| `app/core/openai_client.py:59 reset_openai_client` | B | zero callers in app/tests; docstring says "for tests/app shutdown" but `main.py` lifespan never calls it (`:131-137`) | none | remove, **or** wire into lifespan shutdown (would be the more correct outcome: the singleton `AsyncOpenAI` is never closed) |
| `app/models/enums.py:177 SupportedLanguage` | A (and D) | no runtime import, but `../scripts/tests/test_locale_lists_in_sync.py:29` regex-parses the enum source and CI runs `python -m pytest scripts/tests` (`ci.yml:82`); duplicates `settings.LANGUAGE_MAP` keys (enum docstring `:184` says config is the source) | Med if removed blindly | keep until that repo-check test is re-pointed at `LANGUAGE_MAP`; then remove enum + test together |
| `app/pipelines/llm_conversation.py:545 risk_factor_intake_field` | C | no production caller; used only by `tests/unit/pipelines/test_intake_risk_coverage.py:49,169` | low | test-only helper — either move into that test or keep; decide with pipeline owner |
| `app/pipelines/tts_pipeline.py:112 synthesize_to_url` | B | zero callers in app/tests/scripts; only `docs/archive/production_readiness_audit_2026-06-14.md:339`; WS path uses `synthesize` streaming | none | remove (Supabase upload of TTS audio contradicts `docs/session_data_inventory.md:304` "audio not retained") |
| `app/services/alert_service.py:690 delete_rule_entry` | B | router calls `alert_service.delete_rule` directly (`routers/alerts.py:229`); the sibling wrappers `list_rules/create_rule_entry/update_rule_entry` (`:678-688`) ARE used (`routers/alerts.py:86,109,210`) | none | remove the one wrapper |
| `app/services/audio_service.py:22 AudioService` (+ `upload_audio`, `get_audio_url`) | A (policy) | no runtime caller; but `../docs/session_data_inventory.md:304` records a product decision to keep it as reserved facility, `app/tasks/audio_lifecycle.py:29,148` documents its path format, and `tests/unit/services/test_audio_service_config.py:21` imports the module | — | keep; revisit only if the product decision changes |
| `app/services/complaint_service.py:103 get_active_list` | B | zero callers (router uses other methods); no test | none | remove |
| `app/websocket/connection_manager.py:442 broadcast_report_generated` | B | zero callers; `tasks/report_queue.py:599` publishes `"report_generated"` directly | none | remove |
| `connection_manager.py:503 get_session_connection`, `:507 is_session_connected`, `:511 active_session_count` | B | zero callers in app/tests (`grep -rnw`) | none | remove |
| `connection_manager.py:490` docstring mentions `stt_partial` | C | message type never emitted by server nor handled by either client | none | drop from docstring |
| `conversation_handler.py:474-485` aliased re-imports | mixed | see §2: keep `_coerce_hpi_pct`, `_SESSION_EMITTED_RED_FLAGS_KEY`; remove `_RED_FLAG_SEVERITY_RANK`, `_alert_dedup_identity` | — | — |
| `conversation_handler.py:35`, `dashboard_handler.py:320`, `notification_service.py:9` | B | see §2 | — | — |
| `app/services/session_service.py:398` re-import of `VALID_TRANSITIONS, is_valid_transition` | A | used inside the module (`:427,:623-624,:757-758`) and `tests/unit/tasks/test_session_timeout.py:259` monkeypatches `ss_mod.is_valid_transition` | — | keep |
| `app/schemas/auth.py:168 TokenResponse = LoginResponse` | B | only consumer is the unused import in `routers/auth.py:34` | none | remove with §2 item |

---

## 4. API endpoint inventory and callers

Search scope for every row: `../frontend/src/**/*.ts(x)`, `../flutter_app/lib/**/*.dart`, `../scripts/e2e_realopenai/driver.py`, `../scripts/*.py`, `scripts/*`, `../docs/**/*.md` (excl. `docs/archive`), `../.github/workflows/*.yml`, `../docker-compose.yml`, `railway*.toml`, `Dockerfile`. React base = `client.ts:126` (`…/api/v1`); Flutter base = `API_BASE` dart-define (includes `/api/v1`). "Flutter-only"/"React-only" = other client has no call. Totals: 66 HTTP routes (64 router + 2 ops-gated) + 2 health + 2 WS. **17 routes have no caller anywhere (C)**; all share the pattern "React `services/api/*.ts` wrapper exists but no page calls it".

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| **main.py** | | | | |
| GET `/metrics` `main.py:243` (ops token) | A | `../docs/ops_endpoint_exposure.md:31,68`; `../docs/railway_region_move.md:212` | — | keep |
| GET `/openapi.json` `main.py:253` (ops token, non-dev) | A | `../docs/deployment_guide.md:44-50`, `../docs/AGENTS.md:45-52` (deploy verification) | — | keep |
| WS `/api/v1/ws/sessions/{id}/stream` `main.py:299` | A | `frontend/src/services/websocket.ts`; `flutter_app/lib/features/voice/services/ws_manager.dart`; `driver.py:8,47` | — | keep |
| WS `/api/v1/ws/dashboard` `main.py:309` | A | `frontend/src/components/DoctorAlertPoller.tsx`; `flutter …/doctor/state/alerts_controller.dart` | — | keep |
| GET `/api/v1/health` `main.py:319` | A | `railway.toml:16`, `Dockerfile:82`, `docker-compose.yml:72` | — | keep |
| GET `/api/v1/healthz/deep` `main.py:357` | A | `../docs/deployment_guide.md:41`, `../docs/AGENTS.md:42`, `../docs/supabase_connection_guide.md:83` | — | keep |
| **auth.py** `/api/v1/auth` | | | | |
| POST `/login` `:112`, `/register` `:154`, `/refresh` `:205`, `/logout` `:270`, `/change-password` `:318`, `/forgot-password` `:344`, `/reset-password` `:380`, GET `/me` `:413`, PUT `/me` `:427` | A | React `services/api/auth.ts:14-84`, `client.ts:241`; Flutter `data/api/auth_api.dart:16-86`, `dio_client.dart:179`; `driver.py:806` (register) | — | keep (vulture FP on `get_me`/`update_me`) |
| **patients.py** `/api/v1/patients` | | | | |
| POST `` `:28 create_patient` | C | only `frontend patients.ts:25 createPatient` — export has **zero callers** in `frontend/src`; Flutter none; docs none | med | verify patients are only created via `POST /sessions` patientInfo; if so route + client fn are dead |
| GET `` `:48`, GET `/{id}` `:91`, DELETE `/{id}` `:139`, GET `/{id}/sessions` `:162` | A | React `patients.ts:13,19,37,45`; Flutter `patients_api.dart:13,24,28,31` | — | keep |
| PUT `/{id}` `:114 update_patient` | C | `frontend patients.ts:31 updatePatient` zero callers; Flutter none | med | same as create_patient |
| **sessions.py** `/api/v1/sessions` | | | | |
| POST `` `:34`, GET `` `:81`, GET `/{id}` `:119`, PUT `/{id}/status` `:172`, POST `/{id}/end-for-language-switch` `:198`, GET `/{id}/conversations` `:226`, POST `/{id}/reconnect` `:249`, POST `/{id}/assign` `:295` | A | React `sessions.ts:13-94`; Flutter `sessions_api.dart:24-160`; `driver.py:828` | — | keep |
| GET `/doctors` `:67` | A (Flutter-only) | `sessions_api.dart:29`; `../docs/consultation_flow.md:66` | — | keep |
| DELETE `/{id}` `:138 delete_session` (admin) | A (Flutter-only) | `sessions_api.dart:122`; CLAUDE.md soft-delete rule | — | keep |
| **exam_orders.py** `/api/v1/sessions/{id}/exam-orders` POST `:23`, GET `/latest` `:52` | A (Flutter-only) | `exam_orders_api.dart:12,26` → `quick_orders_page.dart:146` | — | keep |
| **complaints.py** `/api/v1/complaints` GET `` `:30`, POST `` `:77`, PUT `/{id}` `:140`, DELETE `/{id}` `:167` | A | React `complaints.ts:18-42`; Flutter `complaints_api.dart:14-33` | — | keep |
| PUT `/reorder` `:100` | A (React-only) | `complaints.ts:47` has page callers | — | keep |
| GET `/{id}` `:119 get_complaint` | C | `complaints.ts:24 getComplaint` zero callers; Flutter none | low | remove with client fn after e2e check |
| **reports.py** GET `/api/v1/reports` `:31`, GET `/{id}` `:69`, POST `/api/v1/sessions/{id}/reports/generate` `:90`, PUT `/{id}/review` `:134`, GET `/{id}/pdf` `:198` | A | React `reports.ts:14-59`; Flutter `reports_api.dart:30-84`; `../docs/session_data_inventory.md:283` | — | keep |
| GET `/api/v1/reports/{id}/revisions` `:164 list_report_revisions` | C | **no caller** in React/Flutter/scripts/CI/tests; only `../docs/session_data_inventory.md:282` lists it | med | keep as documented audit API or remove with service method; add a test if kept |
| **alerts.py** `/api/v1/alerts` GET `` `:33`, GET `/unacknowledged/count` `:116`, GET `/{id}` `:152`, POST `/{id}/acknowledge` `:170` | A | React `alerts.ts:24-45`; Flutter `alerts_api.dart:13-48` | — | keep |
| POST `/acknowledge-all` `:131` | A (Flutter-only) | `alerts_api.dart:29` (2 callers) | — | keep |
| GET `/rules` `:69`, POST `/rules` `:96`, PUT `/rules/{id}` `:196`, DELETE `/rules/{id}` `:217` | C | React `admin.ts:80-98` (`getRedFlagRules/createRedFlagRule/updateRedFlagRule/deleteRedFlagRule`) — **all four exports have zero callers**; Flutter none; docs none | med | rule-management UI unwired on both clients; decide keep-for-ops vs remove router+service(`alert_service.py:491-690`)+client |
| **dashboard.py** `/api/v1/dashboard` GET `/monthly-summary` `:75` | A | React `dashboard.ts:30`; Flutter `dashboard_api.dart:60` | — | keep |
| GET `/calendar` `:33` | A (Flutter-only) | `sessions_api.dart:111` → `session_calendar_view.dart:255` | — | keep |
| GET `/stats` `:43`, GET `/queue` `:96`, GET `/recent-alerts` `:117`, GET `/recent-sessions` `:138` | C | React `dashboard.ts:18,24,38,44` exports zero callers; Flutter none; both dashboards consume WS `initial_state`/`stats_updated`/`queue_updated` instead; `/queue` has no LIMIT (`dashboard_service.py:393-402`, §9) and `../docs/perf_audit_2026-08-22.md:364` already called it dead | low | remove the four routes + service methods + React wrappers (`test_dashboard_month_key.py` covers month logic only) |
| **research.py** GET `/api/v1/research/analytics` `:28` | A | React `research.ts:15`; Flutter `research_api.dart:10` | — | keep |
| **notifications.py** `/api/v1/notifications` GET `` `:32`, PUT `/read-all` `:57`, GET `/unread-count` `:74`, PUT `/{id}/read` `:170` | A | React `notifications.ts:23-40`; Flutter `notifications_api.dart:25-42` | — | keep |
| POST `/fcm-token` `:130`, DELETE `/fcm-token/{token}` `:152` | A (Flutter-only) | `notifications_api.dart:55,67` (`push_backend.dart`); React `registerFcmToken/deleteFcmToken` zero callers | — | keep; React wrappers are dead client code |
| GET `/preferences` `:94`, PUT `/preferences` `:111` | C | React `notifications.ts:48,56` zero callers; Flutter none; migration `20260614_1030` + model exist | med | preferences UI never wired; keep only if planned |
| **admin.py** `/api/v1/admin` GET/POST `/users` `:39,:65`, PUT `/users/{id}` `:84`, PUT `/users/{id}/toggle-active` `:105`, POST `/users/{id}/reset-password` `:124`, GET `/system/health` `:153` | A | React `admin.ts:21-125`; Flutter `admin_api.dart:12-53`; `tests/unit/services/test_admin_service.py` | — | keep |
| **audit_logs.py** `/api/v1/audit-logs` GET `` `:32` | A | React `admin.ts:104`; Flutter `admin_api.dart:61` | — | keep |
| GET `/{log_id}` `:75 get_audit_log` | C | no caller in React/Flutter/scripts/docs/tests | low | remove candidate |

WebSocket message types:

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Inbound handled: `ping` (`conversation_handler.py:764`, `dashboard_handler.py:111`), `control/end_session` `:777-780`, `control/pause_recording` `:846`, `control/resume_recording` `:851`, `audio_chunk` `:869`, `text_message` `:896`, first-frame `auth` (`websocket/auth.py:7`), unknown → `errors.ws.unknown_message_type` `:940-949` | A | each sent by `frontend/src/services/websocket.ts` / `ConversationPage.tsx` / `hooks/useAudioStream.ts` and `flutter …/conversation_controller.dart` / `ws_manager.dart` | — | keep; no inbound type lacks a client sender |
| Outbound emitted: `pong`, `connection_ack` `:565`, `session_status` `:662,817,1569,1593,2450,2796`, `resume_failed` `:674`, `stt_final` `:1398`, `ai_response_start/chunk/end` `:1036-2501`, `supervisor_guidance` `:1473`, `supervisor_degraded` `:1498`, `red_flag_alert` `:2336`, `error` (many), dashboard `initial_state` `dash:100`, `session_status_changed` (`conv:628…`, `session_service.py:251`, `session_timeout.py:194`), `new_red_flag` `:2355`, `queue_updated` `connection_manager.py:395`, `stats_updated` `:412`, `session_created` `:431`, `report_generated` `report_queue.py:599`, `red_flag_acknowledged` `connection_manager.py:467` | A | all declared in `frontend/src/types/websocket.ts` and handled in Flutter controllers (Flutter ignores `pong`, harmless) | — | keep; no emitted type lacks a consumer |
| `stt_partial` (docstring only, `connection_manager.py:490`) | C | never emitted, never handled | none | delete mention |

Side note: `frontend/src/services/api/client.ts` exports `snakeToCamel`/`camelToSnake` with no external callers (frontend, out of scope).

---

## 5. Duplicate / mergeable logic (D)

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Keyset-cursor predicate (`parse_cursor` → anchor row → `(col < v) \| (col == v & id < id)`) | D | canonical but private: `session_service.py:374-392 _apply_cursor_keyset` (used `:529`). Verbatim copies: `report_service.py:373-385`, `alert_service.py:167-179` and `:530-540`, `notification_service.py:380-391` (inline `UUID(cursor)` `:382-385`), `admin_service.py:66-79` (inline parse `:69` catches only `ValueError`, unlike `utils/pagination.py:22`), `patient_service.py:320-334`. Distinct by design: `complaint_service.py:297-310` (display_order), `session_service.py:867-876` (sequence_number), `audit_log_service.py:116-121` (BIGINT id) | Med — the tie-break fix noted in `_apply_cursor_keyset` docstring landed in one place only | move `_apply_cursor_keyset` into `app/utils/pagination.py` (parametrize id column; it hard-codes `Session.id` `:388/:392`); route 6 copies through it; replace inline `UUID(cursor)` with `parse_cursor` |
| `has_more`/`next_cursor` trailer (11 copies) | D | `patient_service.py:349-367,529-547`; `admin_service.py:90-101`; `audit_log_service.py:126-153`; `notification_service.py:403-422`; `complaint_service.py:318-332`; `report_service.py:391-424`; `alert_service.py:185-208,544-558`; `session_service.py:536-557,881-896` | low | `page_slice(rows, limit)` in `utils/pagination.py`; low priority |
| `BLACKLIST_KEY_PREFIX` defined twice | D | `core/dependencies.py:33` and `services/auth_service.py:46`, both `"gu:token_blacklist:"`; comment `dependencies.py:32` admits manual sync; writer `auth_service.py:361`, reader `dependencies.py:86` | **Med** — drift silently un-revokes logged-out tokens | keep one (reader side) and import it |
| Redis prefix hard-coded `"gu:"` vs `settings.REDIS_KEY_PREFIX` | D | only the supervisor-guidance key uses the setting (`conversation_handler.py:1721,2072`; `supervisor.py:362`; rationale comment `:1716-1718`). Hard-coded `gu:` at `conversation_handler.py:53-54`, `dashboard_handler.py:32`, `connection_manager.py:23`, `core/rate_limit.py:36-42` (7 prefixes), `core/dependencies.py:33`, `pipelines/alert_dedup.py:21`, `notification_service.py:496,799`, `auth_service.py:46,51,55`, `dashboard_service.py:51,237`. Setting at `config.py:123`; compose sets `gu_dev:` (`docker-compose.yml:56`), e2e README says `REDIS_KEY_PREFIX=gu:` is "required" | Med — the setting is a no-op for ~95 % of keys; shared Redis across envs would collide | either one `redis_key(*parts)` helper everywhere or drop the setting + its 3 users; half-adopted is the worst state |
| Unread-notification cache key literal ×2 | D | `notification_service.py:496` and `:799` | low | one constant |
| Dashboard stats cache key shape | C | `dashboard_handler.py:32 "gu:dashboard:stats:{doctor_id}"` (read `:490`, write `:575`) vs `dashboard_service.py:237 "gu:dashboard:stats:{scope_key}:{day}"` + glob invalidation `:51,:70` — same namespace, different shapes | Med if handler key is never invalidated correctly | verify producer/consumer; share one constant |
| Active-clinician fan-out query | D | identical `select(User.id).where(role in (DOCTOR, ADMIN), is_active)` at `conversation_handler.py:3091-3100` and `notification_service.py:329-340 _doctor_targets` (handler comment `:3088` points at the service copy). `session_service.py:44-57 _selectable_doctor_filter` is different by design (assignable ≠ notify) | Med — same bug class as CLAUDE.md "admin silently stops receiving red-flag push" | call `NotificationService._doctor_targets` from the handler, or lift into `core/authz.py` |
| Per-resource authorization orchestration ×3 | D (C on exception type) | `session_service.py:288-345`, `report_service.py:117-173`, `patient_service.py:41-83`; shared chain already in `core/authz.py`; duplicated patient-owner lookup `session_service.py:324` / `report_service.py:164`; deliberate differences: report raises `NotFoundException` (`report_service.py:131-132`) and applies `session_not_deleted()` before admin early-return (`:140-150`, CLAUDE.md) | low–med | extract `patient_owned_by()` into `authz.py`; do **not** merge the three wholesale |
| Trivial wrappers `alert_service.py:76-78 _doctor_scope_id`, `auth_service.py:62-68 _is_admin`; `get_user_role as _get_user_role` aliases in 4 services (`alert_service.py:18`, `report_service.py:24`, `patient_service.py:19`, `session_service.py:21`) | D | one-line delegations to `core/authz.py` | low | delete wrappers/aliases, call authz directly |
| `_extract_client_ip` ×2 | D | `routers/auth.py:143-151`, `core/middleware.py:256-260` — both delegate to `core/net.get_client_ip` | low | import `get_client_ip` directly |
| UUID coercion ×4 | D | `utils/pagination.py:7-23 parse_cursor` (canonical), `core/middleware.py:219-227 _coerce_uuid`, `notification_service.py:382-385`, `admin_service.py:69`, `auth_service.py:507` | low | one `coerce_uuid` in utils |
| Health probes ×2 | D | `main.py:330-356 _deep_check_db/_deep_check_redis` vs `admin_service.py:357-388 _probe_db/_probe_redis` (same 2.0 s timeout, same `SELECT 1`/`ping`, same `"fail: …"` protocol; admin adds `_probe_openai` `:390-403`) | low–med — Railway healthcheck and admin health can drift | `main.py` reuses admin_service probes |
| `_broadcast_dashboard_queue_and_stats` wrappers | C | `conversation_handler.py:1512-1533` vs `tasks/session_timeout.py:212-240` (Celery builds its own `aioredis.from_url` per call `:226-230`, documented) | low | leave until the Celery loop-binding issue (§9 #18) is addressed |
| `SessionCreate._validate_language` vs `SessionEndForLanguageSwitch._validate_to_language` | D | `schemas/session.py:132-142` and `:162-169` identical bodies | low | one module-level validator fn |
| `i18n_messages._resolve_lang` vs `utils/language.resolve_language` | C | `i18n_messages.py:1076-1088` ignores `MULTILANG_DISABLED_LANGUAGES`; `localized_field.py:51` same; may be intentional (error copy should still localize) | low | confirm intent |
| `exceptions._resolve_request_language` vs `language_middleware.get_request_language` | C | `exceptions.py:297-305` ignores `?lng`/`X-Language` that `language_middleware.py:49-68` already resolved → 4xx body language can differ from 200 | med (UX) | start from `request.state.language` |
| `enums.SupportedLanguage` vs `settings.LANGUAGE_MAP` | D | see §3 | low | drop enum after re-pointing `scripts/tests/test_locale_lists_in_sync.py` |
| CJK predicate ×2 | C | `utils/language_detect.py:29-37` (4 ranges) vs `red_flag_detector.py:291-301` (5 ranges incl. Hangul) — different coverage | low | leave |
| `datetime.now(timezone.utc)` direct calls vs `utc_now()` | D (cosmetic) | `conversation_handler.py:266,275,294,770,1085,1681,1789`; `dashboard_handler.py:116,331`; `connection_manager.py:499`; `main.py:325`; `core/security.py:66` | low | use `utc_now()` (lets tests freeze one fn) |
| Date/ISO parsing | A (already consolidated) | `utils/datetime_utils.py:36-61 parse_iso` used by all list filters (`session_service.py:1153`, `patient_service.py:570,631`, `report_service.py:298`, `alert_service.py:119`, `audit_log_service.py:212`); `dashboard_service._parse_day_range/_parse_month_range` are different formats by design; `datetime.utcnow()` count = 0; one residual tz-normalize at `report_service.py:112-113` | — | optional `ensure_utc()` helper |
| Router error-handling boilerplate | A (already removed) | no `except AppException`/`except Exception → 500` blocks remain in `app/routers/*` except intentional `auth.py:106-109,193-196`; only residue is the 5 unused imports (§2) | — | — |
| Session-visibility filter | A (already consolidated) | zero inline `Session.is_deleted` predicates outside `session_visibility.py` (only the writer `session_service.py:1289-1294`); `Patient.is_deleted.is_(False)` inline ×3 (`patient_service.py:315,357,390`) is a different table with no helper | low | optional `patient_not_deleted()` |

---

## 6. Dependencies (requirements.txt / requirements-dev.txt)

| Package | Category | Evidence (import or runtime need) | Risk | Recommendation |
|---|---|---|---|---|
| fastapi | A | 31 files | — | — |
| uvicorn[standard] | A | no import; `start.sh:141`, `CLAUDE.md` dev command | — | — |
| websockets | C | no import; `uvicorn[standard]` already pulls `websockets`; explicit pin only forces a version | none | keep pin or drop — cosmetic |
| pydantic, pydantic-settings | A | 22 files / `config.py:17` | — | — |
| email-validator | A | no import; required by `EmailStr` (`schemas/auth.py:7`) | — | — |
| sqlalchemy[asyncio], greenlet | A | 86 files; greenlet required by SA async | — | — |
| asyncpg | A | no import; driver selected by URL `postgresql+asyncpg://` (`config.py:29-37`, `database.py`) | — | — |
| psycopg2-binary | A | no import; alembic sync URL `alembic/env.py:38` (+ comment `requirements.txt:19-21`) | — | — |
| alembic | A | `start.sh:70`; 26 files | — | — |
| PyJWT | A | 5 files (`core/security.py`, `websocket/auth.py`, `tasks/notification_retry.py`) | — | — |
| passlib[bcrypt], bcrypt | A | `core/security.py:14,19`; bcrypt is the passlib backend | — | — |
| cryptography | A | no direct import; PyJWT RS256 (`config.py:167 JWT_ALGORITHM="RS256"`) needs it | — | — |
| httpx | A | `tasks/notification_retry.py:10`, `core/email_client.py:82`; also openai/supabase dep | — | — |
| h2 | A | `notification_retry.py:113 httpx.AsyncClient(http2=True)` (APNs requires HTTP/2) | — | — |
| openai, tiktoken, tenacity | A | `core/openai_client.py:15-17` | — | — |
| opencc-python-reimplemented | A | `pipelines/stt_pipeline.py:20` | — | — |
| weasyprint | A | `services/report_service.py:740` (lazy import); Dockerfile system libs `:36-53` | — | — |
| redis[hiredis] | A | 14 files | — | — |
| celery[redis] | A | `tasks/__init__.py:12-14`; CLI in `start.sh` | — | — |
| sentry-sdk[fastapi] | A | `core/sentry.py:14`, `core/exceptions.py:9` | — | — |
| firebase-admin | A | `core/firebase.py:17`, `tasks/notification_retry.py:9` | — | — |
| supabase | A | `pipelines/tts_pipeline.py:11`, `tasks/audio_lifecycle.py:193`, `services/audio_service.py` | — | note: the only runtime user left is `audio_lifecycle` cleanup + the §3 B/A items; if `synthesize_to_url` and `AudioService` go, only `audio_lifecycle.py:193` remains |
| python-dotenv | A | no import; pydantic-settings `env_file=".env"` (`config.py:44`) uses it | — | — |
| python-dateutil | C | no import anywhere in app/tests/alembic/scripts; `requirements.txt:63` says "transitive pin (celery/storage3)" | none | keep as deliberate pin, or drop (pip resolves it anyway) |
| prometheus-fastapi-instrumentator, prometheus-client | A | `main.py:17-18`, `core/metrics.py:28` | — | — |
| pytest, pytest-asyncio (dev) | A | 99 files; `@pytest.mark.asyncio` markers (CI comment `ci.yml:71-74`) | — | — |

No package is unused at runtime. Two are pure version pins (`websockets`, `python-dateutil`).

---

## 7. Config / env drift

Mechanical comparison (script over `config.py` field names + `validation_alias` vs `.env.example` active **and** commented keys): **no key missing in either direction**. Remaining drift is semantic:

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `APP_HOST`, `APP_PORT`, `APP_WORKERS` (`config.py:53-55`, `.env.example:14-16`) | B | never read; `start.sh:48-49` uses `PORT`/`WORKERS` (shell-only) | none | remove from both; document `PORT`/`WORKERS`/`RUN_CELERY_IN_API`/`CELERY_CONCURRENCY`/`CELERY_BEAT_SCHEDULE` as shell-level vars (they are not `Settings` fields; only `start.sh:47-50,104-105,121` read them) |
| `RED_FLAG_SEMANTIC_ONLY_THRESHOLD` (`config.py:324`, `.env.example:139`) | B | no reader (§3) | none | remove or implement |
| `APP_DEBUG` in `../docker-compose.yml:52` | C | not a `Settings` field; `extra="ignore"` (`config.py:47`) silently drops it | none | delete from compose or add the field |
| `APP_LOG_LEVEL` in `../docs/system_overview.md:295` | C | no such field (only `LOG_LEVEL`, `config.py:57`) | doc drift | fix doc |
| `alembic/env.py:37` `_use_ssl = "supabase" in settings.DB_HOST` | C | when the DB is injected as a full `DATABASE_URL` (Railway/Supabase, the production norm), `DB_HOST` stays `"localhost"` → `sslmode=require` is **not** set for migrations; `app/core/database.py:27-40` fixed exactly this for the runtime engine but env.py still uses the old check | Med — works today only if the pooler accepts non-SSL or the URL carries `?sslmode=` (not verifiable offline) | parse host from `settings.DATABASE_URL` like `database.py:32-36`; verify by running `alembic current` against prod URL with `PGSSLMODE` unset |
| `REDIS_KEY_PREFIX` half-adopted | D | see §5 | med | — |
| `Dockerfile:9,29 python:3.11-slim` vs CI/venv 3.12 | C | see §1b | low | align |
| `railway-worker.toml`, `railway-beat.toml`, `start_worker.sh`, `start_beat.sh` | C | referenced only by `../docs/railway_celery_runbook.md:33-34,56,80`; `../docs/TODO.md:209` says they "may need to be created" (stale — they exist) | low | keep as split-out kit **with** the runbook, or delete all together; fix TODO.md |
| `.env.example:30 # DOCS_ENABLED=`, `:80 # JWT_SECRET_KEY=` commented defaults | A | match `config.py:79,168` | — | — |
| JWT alias names `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` / `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (`config.py:178-190`) | A | documented in `.env.example:91-94` | — | — |
| CI env (`ci.yml:44-52`) vs compose (`docker-compose.yml:50-65`) | A | both set only what `Settings` needs; CI relies on defaults for everything else | — | — |

---

## 8. Size / complexity hot spots (E)

Top 15 files by LOC in `app/` (total 35,130): `websocket/conversation_handler.py` 3410 · `pipelines/red_flag_detector.py` 2508 · `pipelines/prompts/shared.py` 1784 · `pipelines/soap_generator.py` 1574 · `services/report_service.py` 1336 · `services/session_service.py` 1320 · `pipelines/llm_conversation.py` 1208 · `utils/i18n_messages.py` 1144 · `services/notification_service.py` 802 · `services/research_service.py` 752 · `services/dashboard_service.py` 701 · `services/alert_service.py` 691 · `services/patient_service.py` 633 · `tasks/report_queue.py` 624 · `websocket/dashboard_handler.py` 590.

Longest functions (AST; nesting = max depth of if/for/while/try/with):

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `conversation_handler.py:1622 _handle_text_message` | E | **1202 lines**, nesting 6; contains the EM-1 `return` invariant (CLAUDE.md) and the auto-end/hard-cap/red-flag abort branches | high change-risk | identify only; any split must keep the AST tripwire (`tests/unit/test_terminal_path_six_things_matrix.py`) green |
| `conversation_handler.py:491 conversation_websocket` | E | 509 lines, nesting 6 | high | — |
| `conversation_handler.py:1209 _handle_audio_chunk` 234 · `:2160 _persist_and_emit_alert` 218 (nest 4) · `:3143 _update_session_status` 208 (nest 4) · `:1003 _send_initial_greeting` 114 · `:3029 _notify_doctors_red_flag` 112 · `:2379 _finalize_red_flag_abort` 105 | E | 38 functions in 3410 lines → avg 90 lines | — | — |
| `session_service.py:929 create_session` 155 (nest 3) · `:599 update_status_static` 130 · `:731 end_for_language_switch` 110 · `:176 _after_status_transition` 110 · `:467 get_list` 95 · `:1095 list_sessions` 64 | E | `_after_status_transition` is the REST terminal fan-out entry (CLAUDE.md) | — | — |
| `llm_conversation.py:812 build_system_prompt` 207 · `:1035 format_messages` 100 (nest 4) · `:1136 generate_response` 73 · `:680 split_risk_factors_by_intake` 44 (**nest 5**) | E | — | — | — |
| `red_flag_detector.py:1862 _rule_based_detect` 182 (**nest 5**) · `:2045 _semantic_detect` 176 · `:2222 detect` 145 · `:2413 _merge_and_deduplicate` 96 · `:971 _clause_before` 67 (nest 4) · `:1417 _cooccurrence_matches` 62 (**nest 5**) | E | rule layer is clinically policy-locked (CLAUDE.md RF-3/4/5) | — | — |
| `report_service.py:457 generate_report` 185 · `:264 list_reports` 165 · `:1179 _build_report_html` 135 · `:179 _snapshot_revision` 70 (nest 4) | E | — | — | — |
| `utils/i18n_messages.py` 1144 lines of dict literals | E | data-as-code; `test_i18n_message_locale_parity.py` enforces parity | low | — |

---

## 9. Performance review (E)

### 9a. `../docs/perf_audit_2026-08-22.md` remaining items → current status

| Doc item | Status | Evidence |
|---|---|---|
| §4a LLM reply not streamed | **Fixed** (F07) | `conversation_handler.py:1863 early_sender = asyncio.create_task(_send_ready_sentences())` |
| §4a sentence split only CJK punctuation | **Fixed** | `:59 _SENTENCE_BOUNDARY_CHARS = "。！？!?\n"` + Latin period lookahead `:313-315` |
| §4c handshake runs 7 sequential scans before greeting | **Fixed** | `:641 _spawn_background(_broadcast_dashboard_queue_and_stats(None, redis))`; queue count → 1 SQL `dashboard_handler.py:354-360` |
| §4c notifications sorted on unindexed `created_at` + 2 COUNTs | **Fixed** | `alembic/versions/20261003_1600-notification_paging_indexes.py:13-16`; counts merged `notification_service.py:404-408` |
| §4c month summary loads whole-month ORM | **Fixed** | SQL GROUP BY `dashboard_service.py:551-560` |
| §4c status change runs 7 queries | **Partial** | queue → 1 SQL; stats still use non-sargable `func.date(created_at) == today` (`dashboard_handler.py:521,529,538`) |
| §4c `GET /sessions/{id}/conversations` loads transcript twice | **Fixed** | `session_service.py:858 get_by_id(..., with_conversations=False)` |
| §4 Redis still in California | unverified (deployment) | `perf_audit:297` — C |
| §5 dismissal "`/dashboard/queue` has no LIMIT — dead code" | dismissal **wrong**: route still mounted `routers/dashboard.py:97` (but no client caller, §4) | remove route (§4) |
| §5 Celery `.delay()` blocks event loop | still true | no user-visible evidence |
| F10 "bcrypt moved off loop" | **Partial** | `security.py:42,47` wrappers exist; `admin_service.py:128,293` still call sync `hash_password` in `async def` |

### 9b. Current-code findings

| Item (file:line / symbol) | Category | Evidence (why) | Risk | Recommendation (how to measure) |
|---|---|---|---|---|
| `tasks/session_timeout.py:105-113` stale-session query has **no `session_not_deleted()`** | **A** (CLAUDE.md soft-delete invariant) | `select(Session.id, Session.updated_at).where(status==IN_PROGRESS …)` — a soft-deleted in-progress session is timed out, CAS-updated `:128`, then fanned out (`:205 session_status_changed`, `:212 queue/stats`) → deleted session re-appears as a `cancelled` dashboard event | Med | add filter at `:105`; pin in `tests/integration/test_soft_deleted_session_invisible_pg.py` (CLAUDE.md rule) |
| `services/alert_service.py:398` `select(Session).where(id==…)` in create-alert push path | A/C | no visibility filter; reads `doctor_id` of a possibly deleted session for push | low (alerts originate from live WS) | verify a deleted session cannot hold an open WS; else add filter |
| `services/session_service.py:418` status re-read on CAS miss | A/C | error path; 409 details reveal `current_status` of a deleted session | low | add filter or accept |
| `tasks/report_queue.py:206-208` `select(Session)…` in report-ready notify helper | A/C | no filter; caller already fails out at `:291` for deleted sessions | low | confirm reachability only after `:285` guard |
| `notification_service.py:194-215`, `:259-270` fan-out: per target `select(User.preferred_language)` + `create()` flush (`:86`) | E | N+1 = 2×(active doctors+admins) round-trips per report-ready/failed event; comment `:195-198` accepts N≈10 | low today | count SQL statements per event (SA event counter, like `tests/integration/test_smoothness_queries_pg.py`) |
| `conversation_handler.py:3090-3124 _notify_doctors_red_flag` | E | same N+1 shape, on the critical red-flag path inside the WS turn | low–med (adds N flushes before patient abort message) | time with N=50 synthetic users |
| `dashboard_service.py:393-402 get_queue` (`GET /dashboard/queue`) | E | no `.limit(`; WS twin caps at 50 (`dashboard_handler.py:371`); no caller (§4) | med if ever called | remove route; else EXPLAIN ANALYZE at 1k waiting |
| `research_service.py:257-269` population then Q2–Q6 `WHERE session_id IN (<python list>)` (`:296,:312,:327,:374`) | E | no date filter → whole `sessions` table; Q4 pulls `SOAPReport.subjective` JSONB for all reports (`:325`); no LIMIT | med — `/research/analytics` scales linearly with history | EXPLAIN ANALYZE Q2/Q4 at 10k sessions; P95 vs row count |
| `report_service.py:740-744` WeasyPrint `write_pdf()` inside `async def export_pdf` (awaited from `routers/reports.py:212`) | E | CPU-bound sync render (100s ms–s) blocks the event loop that also serves every kiosk WS | **High** (shared API worker) | `loop.slow_callback_duration` log / py-spy during PDF export; wrap in `asyncio.to_thread` |
| `admin_service.py:128`, `:293` sync `hash_password()` in async | E | bcrypt cost 12 ≈ 200–400 ms blocking; `hash_password_async` already exists | med (admin-only) | same slow-callback log; switch to async wrapper |
| `connection_manager.py:329-345 publish_dashboard_event` creates `aioredis.from_url(...)` **per publish** | E | new TCP+AUTH per event; several events per WS turn; Redis is cross-region per perf doc | med | Redis `total_connections_received` during one consultation |
| `conversation_handler.py:3370`, `:3399-3404` history as one JSON blob rewritten each turn | E | O(n) per turn, grows with transcript | low (KBs) | log payload size/turn |
| `conversation_handler.py:1046-1050` greeting TTS sequential per sentence | E | first sentence fast; total = Σ TTS | low | existing stage-timing logs |
| `dashboard_handler.py:521,529,538`, `dashboard_service.py:551,565` `func.date(created_at) == today` | E | non-sargable + no index on `sessions.created_at`/`red_flag_alerts.created_at` → full scan per stats broadcast (fires on every status change, `:641`) | med, grows with table | EXPLAIN `sessions_today_stmt`; rewrite as range once index exists |
| `complaint_service.py:245-252` reorder = one UPDATE per item | E | admin-only, N≈30 | low | ignore |
| `tasks/audio_lifecycle.py:91-110`, `tasks/session_timeout.py:124-146` per-row UPDATE+commit | E | bounded batches in Celery | low | n/a |
| `tasks/__init__.py:63-71 run_async` → `asyncio.run` per task body ⇒ new loop + new engine/pool per invocation (`session_timeout.py:214-217` comment confirms) | E | connection churn to Supabase pooler on every SOAP/timeout/retry task | low–med | `pg_stat_activity` connection count per worker over 10 tasks |
| `red_flag_detector.py:1708` loads all active rules per detector instance (per WS connection `conversation_handler.py:582`) | E | one small query per consultation, cached | low | n/a |
| Lazy loads | A | all relationships default `lazy="select"`; 21 `selectinload` sites (`session_service.py:584-589`, `report_service.py:336-341`, `report_queue.py:287-291`); no un-eager traversal found; `tests/unit/schemas/test_report_session_context.py` guards it | — | keep guard |
| OpenAI client | A | singleton `core/openai_client.py:48-56`; all 6 pipelines use `get_openai_client()` | — | — |
| Redis in loops | A | only `auth_service.py:112-114` (logout-all `scan_iter`+`delete`) and `alert_dedup.py:77,105-106` (3 ops/alert) | — | — |
| Blocking I/O in async | A | `audio_lifecycle.py:222` and `red_flag_detector.py:2258` use `asyncio.to_thread`; no `time.sleep`/`requests`/`open(` in app/ | — | — |
| `cache/redis_client.py:32 await _redis_pool.close()` | E (minor) | `DeprecationWarning: use aclose()` (redis ≥5.0.1) seen in test run | none | `aclose()` |

### 9c. Index coverage vs. query predicates

Indexes present (alembic + models): `users(email)`; `sessions(doctor_id)`, `(patient_id)`, `(is_deleted)` (`20260823_1800:54`); `conversations(session_id)` (partitioned by `created_at`, `20260417_0910:80`); `red_flag_alerts(session_id)`, `(canonical_id)` (`20260418_1700:82`); `soap_reports(session_id)` unique; `soap_report_revisions(report_id)`; `notifications(user_id)`, `(user_id, created_at, id)`, partial `(user_id) WHERE is_read=false` (`20261003_1600:13-16`); `audit_logs(user_id)`, `(language)` (partitioned by `created_at`); `patients(user_id)`, `(medical_record_number)`, `(is_deleted)`; `fcm_devices(user_id)`; `notification_preferences(user_id)`; `exam_orders(session_id, created_at)`.

| Predicate | Index? | Evidence | Category / Risk | Measure |
|---|---|---|---|---|
| `sessions.status` (+ `ORDER BY created_at`) — queue `dashboard_handler.py:357,366-370`, `dashboard_service.py:396-398`, list `session_service.py:511` | **none** | only `doctor_id/patient_id/is_deleted` | E / med — recomputed on every status change | EXPLAIN ANALYZE at 10k rows; candidate `(status, created_at)` |
| `sessions.created_at` range / order — list default, calendar `dashboard_service.py:533`, month `:555-556`, recent `:490` | **none** | — | E / med | same |
| `sessions(status, updated_at)` — timeout `session_timeout.py:106-107` | none | — | E / low (every 5 min) | EXPLAIN |
| `red_flag_alerts.acknowledged_by IS NULL` + `ORDER BY created_at DESC` — `alert_service.py:155-162`, `dashboard_handler.py:433-436,544-546`, `dashboard_service.py:450-452` | **none** (only `session_id`, `canonical_id`) | pending count on every stats broadcast | E / med | partial index `WHERE acknowledged_by IS NULL` |
| `red_flag_alerts.severity`, `.created_at` filters (`alert_service.py:144-151`) | none | — | E / low | EXPLAIN |
| `soap_reports.status/review_status/reviewed_by` + `ORDER BY created_at DESC` (`report_service.py:342,352-357`) | none (only unique `session_id`) | doctor landing page | E / low–med | EXPLAIN at 10k reports |
| `conversations(session_id, sequence_number)` (`session_service.py:861-863`) | `session_id` only | few rows/session | A | — |
| `notifications` paging/unread | covered | `20261003_1600` | A | — |
| `audit_logs` `ORDER BY created_at DESC` + `action/resource_type/ip_address` (`audit_log_service.py:97-109`) | partition pruning only with a range; no index on `action` | admin | E / low | EXPLAIN |

---

## 10. Tests

Inventory (158 files): `tests/integration` 4 files / 11 tests (gated by `requires_db` skipif at module level, `tests/integration/conftest.py:65-71`) · `tests/unit` root 3 (incl. the AST tripwire `test_terminal_path_six_things_matrix.py` — **must stay at `tests/unit/` root**, CLAUDE.md) · `unit/alembic` 2 · `unit/core` 14 · `unit/middleware` 1 · `unit/models` 1 · `unit/pipelines` 42 · `unit/routers` 6 · `unit/schemas` 5 · `unit/services` 32 · `unit/tasks` 10 · `unit/utils` 8 · `unit/websocket` 30. No `pytest.ini`/`pyproject` — defaults.

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Skip 1: `tests/unit/test_terminal_path_six_things_matrix.py:674` | A | the Celery cross-process cell has `exercise=None`; documented by `test_skipped_cells_are_documented` | — | keep |
| Skip 2: `tests/unit/pipelines/test_red_flag_audit_2026_08.py:1797` ('意識不清' protected on MUST_FIRE side, no single-axis false-positive corpus) | A | clinical policy (CLAUDE.md RF-3/4, `REMOVED_LITERAL_JUSTIFICATION`) | — | keep |
| Skip 3 (CI only): `tests/unit/pipelines/test_red_flag_cooccurrence_coverage.py:740,799` need `../scripts/e2e_realopenai/results/*.json` (gitignored, `scripts/e2e_realopenai/.gitignore:1`) | C | anti-plagiarism check vs real transcripts; silently skipped in every CI run, runs only on a dev box that has results | low | document, or vendor a small fixture so CI exercises it |
| `tests/integration/*` never run in CI | **C (high value)** | `ci.yml:79` runs `pytest tests/unit` only, although Postgres+Redis services are provisioned (`ci.yml:20-42`); `test_soft_deleted_session_invisible_pg.py` — the CLAUDE.md soft-delete tripwire — therefore only runs on dev machines | med | add a CI step `pytest tests/integration` with `TEST_DATABASE_URL` + `alembic upgrade head`; verify locally first |
| Date-named: `test_red_flag_audit_2026_08.py` (2054 lines, 57 tests), `test_report_queue_audit_2026_08.py` (672 lines, 21 tests) | A | regression tables for the 2026-08-20 audit; the former holds `KEPT_LITERALS`/`REMOVED_LITERAL_JUSTIFICATION` referenced by CLAUDE.md | — | keep names (CLAUDE.md cites them) |
| Pairs that look duplicated but are complementary: `test_end_for_language_switch.py` (happy/idempotent/audit) vs `_guard.py` (authz/state machine, docstring `:2-4` says so); `test_red_flag_negation.py` / `_guard_e11.py` / `_false_friends.py` (base / 5-lang critical window / guard-induced misses); `test_intake_risk_coverage.py` vs `_multilingual.py`; `test_report_pdf_content.py` vs `_escaping.py`; `test_e84_red_flag_reason_localization.py` vs `_title_localization.py` | A | docstrings state distinct scopes | — | no merge |
| `tests/unit/pipelines/test_red_flag_detector_shared.py` (76 lines, "Phase 3 migration to shared.URO_RED_FLAGS") | C | migration-era guard; overlap with `test_shared_prompts.py` not verified | low | verify overlap before removing |
| Tests that would break if a **B** item were removed | — | none: every B symbol in §2/§3 was grepped in `tests/` (incl. `ch.<name>` and string targets). Tests that pin **A** items: `test_auto_conclude.py:22` (`_coerce_hpi_pct`), `test_red_flag_dedup.py:25` + `test_e84_red_flag_title_localization.py:25` (`_SESSION_EMITTED_RED_FLAGS_KEY`), `test_audio_service_config.py:21` (`audio_service`), `../scripts/tests/test_locale_lists_in_sync.py:29` (`SupportedLanguage`), `test_intake_risk_coverage.py:49` (`risk_factor_intake_field`, C) | — | — |
| Deprecation warnings in run: `redis_client.py:32 close()`; weasyprint `instantiateVariableFont` (library) | E | 6 warnings total | none | `aclose()`; library upgrade later |

---

## 11. Security notes relevant to cleanup

Scans over `app/`: `print(` = 0; `breakpoint()/pdb` = 0; hard-coded secret-looking literals = 0; `noqa` = 53; TODO/FIXME/XXX/HACK markers = 55 lines in 26 files (`red_flag_detector.py` 11, `core/metrics.py` 5, `prompts/shared.py` 3, `core/config.py` 3, 2 each in `utils/language.py`, `utils/i18n_messages.py`, `services/alert_service.py`, `models/red_flag_rule.py`, `models/red_flag_alert.py`, `models/enums.py`, `core/sentry.py`, 1 each in 15 others). The single `XXX` (`core/metrics.py:18`) is a placeholder in prose, not a marker.

| Item (file:line / symbol) | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| TODO markers | A | all 54 real markers are cross-references to closed ticket IDs (TODO-E6, TODO-M8, TODO-O2 …) explaining *why* code exists, not dead/temporary code. Only two describe pending work: `report_service.py:1191` (PDF content not translated, labels only) and `utils/language.py:23` (consent_records gate) | none | leave; optionally rename to plain "see docs/…" refs |
| `main.py:50-59 _DEV_DEFAULT_SECRETS` | A | public dev defaults, rejected at production start `:62-90`; pinned by `tests/unit/services/test_startup_secret_enforcement.py` | — | keep |
| `docker-compose.yml:63 JWT_SECRET_KEY`, `ci.yml:49` | A | dev/CI placeholders | — | — |
| `../scripts/e2e_realopenai/local.env` is **git-tracked** and contains non-empty `JWT_SECRET_KEY` (43 chars), `DB_PASSWORD` (8), `DATABASE_URL` → `@localhost:55432` | C | README `:16` documents it as local overrides; values point at localhost; CLAUDE.md "Never commit `.env*`" pattern does not match `local.env` | low (local-only values) unless any value was ever reused in prod | confirm the JWT secret is not the production one; consider renaming to `local.env.example` + gitignore |
| Ops endpoints `/metrics`, `/openapi.json` | A | token-gated with `secrets.compare_digest`, fail-closed in prod (`main.py:206-235`), 404 on unauthorized; `tests/unit/test_ops_endpoint_exposure.py` | — | keep |
| `settings.docs_exposed` / `metrics_open_without_token` (`config.py:508-518`) | A | dev-only relaxations keyed on `APP_ENV` | — | — |
| Dockerfile non-root `appuser` (`:61-75`), `tini` | A | — | — | — |
| Working-tree (uncommitted) security fixes present: `soap_generator.py:738-747` sanitizes patient fields; `prompts/shared.py:1752-1762` `_LEADING_HEADING_MARKS = ^[#＃\s]+` with fixed-point assert | A | CLAUDE.md lists these as "in progress, not committed" — they are in the working tree now | — | do not touch during cleanup; commit via the pipeline owner's flow (`e2e-real-openai` skill) |
| `tasks/session_timeout.py:105` missing `session_not_deleted()` | A-invariant breach | see §9b row 1 | med | fix + register in integration test |
| `core/dependencies.py:33` / `auth_service.py:46` duplicated blacklist prefix | D | see §5 | med | single constant |

---

## Summary counts

Each table row counted once (rows with mixed labels counted under their primary label).

| Category | Count | Where |
|---|---|---|
| A (keep, confirmed in use / policy) | ~90 | §2: 2 · §3: 8 · §4: ~55 route/WS rows · §5: 5 · §6: 27 · §7: 3 · §10: 5 · §11: 8 |
| B (safe to remove, proof given) | **62** | §2: 46 (26 app + 20 test) · §3: 13 (`APP_HOST/PORT/WORKERS`, `RED_FLAG_SEMANTIC_ONLY_THRESHOLD`, `InternalErrorException`, `reset_openai_client`, `synthesize_to_url`, `delete_rule_entry`, `get_active_list`, `broadcast_report_generated`, `get_session_connection`, `is_session_connected`, `active_session_count`, `TokenResponse` alias, 2 aliased re-imports) · §7: 2 (same config fields) |
| C (needs verification) | **36** | §1: 2 · §3: 3 · §4: 17 uncalled routes + 1 docstring · §5: 6 · §6: 2 · §7: 6 · §10: 3 · §11: 1 |
| D (duplicate/mergeable) | **15** | §5 |
| E (performance/architecture) | **38** | §8: 8 · §9b: 17 · §9c: 7 · §10: 1 · plus §1b Dockerfile version |

## Top 10 highest-value, lowest-risk actions

1. **Fix the soft-delete invariant breach** in `app/tasks/session_timeout.py:105` (add `session_not_deleted()`) and register the path in `tests/integration/test_soft_deleted_session_invisible_pg.py` — category A rule from CLAUDE.md, 1-line change.
2. **Run `tests/integration` in CI** (`ci.yml:79` only runs `tests/unit`; Postgres/Redis services are already provisioned) so the soft-delete tripwire actually gates merges.
3. **Remove the 46 ruff B hits by hand** (§2) — but add `# noqa: F401` to `conversation_handler.py:475` and `:484` first; a blind `ruff --fix` would break `test_auto_conclude.py` and `test_red_flag_dedup.py`.
4. **Single `BLACKLIST_KEY_PREFIX`** (`core/dependencies.py:33` ← `auth_service.py:46`): drift here silently un-revokes logged-out tokens.
5. **Move WeasyPrint `write_pdf()` off the event loop** (`report_service.py:740-744` → `asyncio.to_thread`) and use the existing `hash_password_async` in `admin_service.py:128,293` — highest perf payoff per line changed.
6. **Delete the 13 dead symbols in §3** (`InternalErrorException`, `reset_openai_client` or wire it into lifespan, `synthesize_to_url`, `delete_rule_entry`, `get_active_list`, 4 `connection_manager` helpers, `TokenResponse` alias, `APP_HOST/PORT/WORKERS`, `RED_FLAG_SEMANTIC_ONLY_THRESHOLD` + their `.env.example` lines).
7. **Decide the 17 uncalled routes** (§4): the four `/dashboard/{stats,queue,recent-alerts,recent-sessions}` are the clearest removals (superseded by WS `initial_state`; `/queue` is unbounded). Alert-rule CRUD, notification preferences, patient create/update, report revisions, audit-log detail need a product decision (ops/external use?).
8. **Share `_doctor_targets`** between `conversation_handler.py:3091` and `notification_service.py:329` — the "admin stops getting red-flag push" bug class from CLAUDE.md lives in exactly this duplication.
9. **Add indexes** for `sessions(status, created_at)` and partial `red_flag_alerts(acknowledged_by IS NULL)` after `EXPLAIN ANALYZE` confirms (§9c) — both predicates run on every status-change broadcast.
10. **Fix `alembic/env.py:37` SSL detection** to parse the host from `settings.DATABASE_URL` as `core/database.py:32-36` already does, and resolve the worker/beat kit question (keep `railway-*.toml` + `start_*.sh` + runbook together, or delete all; fix `docs/TODO.md:209`).

Do-not-touch list during cleanup (category A by CLAUDE.md): `tests/unit/test_terminal_path_six_things_matrix.py` location; `pipelines/patient_context.build_patient_info`; `prompts/shared.sanitize_for_prompt` and its working-tree fix; `soap_generator.py:738-747` working-tree sanitization; `_after_status_transition` as the only REST SOAP trigger; the EM-1 `return` in `_handle_text_message`; `KEPT_LITERALS`/`REMOVED_LITERAL_JUSTIFICATION` in `test_red_flag_audit_2026_08.py`; `JsonFloatDecimal` on Decimal response fields; every `session_not_deleted()` call site (53).
