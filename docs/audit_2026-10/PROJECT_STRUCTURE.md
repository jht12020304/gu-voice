# PROJECT_STRUCTURE — 整理後（2026-10-24）

結構本身沒有搬動任何目錄；本輪只刪死碼、修正配置。以下是現況地圖與主要執行流程，模組層級細節見 [evidence/](evidence/) 各 §1。

```
gu-voice/
├── backend/                 FastAPI + Celery（Python 3.12；Dockerfile 仍 3.11，待對齊）
│   ├── app/
│   │   ├── main.py          lifespan（sentry→firebase→redis 池→dashboard subscriber）、middleware、12 routers、2 WS、/health
│   │   ├── core/            config（Settings，唯一真相）、database（asyncpg + PgBouncer 對策）、security（bcrypt async、JWT）、
│   │   │                    dependencies（get_db/get_redis/get_current_user、BLACKLIST_KEY_PREFIX 唯一定義）、authz、rate_limit、
│   │   │                    middleware（security headers／audit／request id）、language_middleware、session_state（VALID_TRANSITIONS）
│   │   ├── cache/redis_client.py  連線池 + 建池 loop 記錄（pool_for_current_loop）
│   │   ├── models/          14 ORM（sessions 軟刪除、conversations／audit_logs 月分區）
│   │   ├── schemas/         pydantic v2；common.JsonFloatDecimal；ws_message
│   │   ├── routers/         thin routers → services（12 檔，66 REST 路由）
│   │   ├── services/        業務邏輯（session_visibility.session_not_deleted 是軟刪除閘門；report_service 的 PDF 走 thread）
│   │   ├── pipelines/       llm_conversation／supervisor／red_flag_detector／soap_generator／stt／tts（只回 bytes）／patient_context／prompts/shared
│   │   ├── websocket/       conversation_handler（病患 WS，3.4k 行，受 AST 跳閘器保護）、dashboard_handler、connection_manager（publish 走池或短命 client）、auth
│   │   ├── tasks/           Celery app + run_async；report_queue／notification_retry／session_timeout（含軟刪除過濾）／partition_manager／audit_retention／audio_lifecycle
│   │   └── utils/           datetime_utils（utc_now／parse_iso）、pagination（parse_cursor）、language、i18n_messages
│   ├── alembic/             23 版；env.py 以 DATABASE_URL host 判 SSL
│   ├── scripts/start.sh     Railway 入口：migrate → (celery worker+beat in-container) → uvicorn；start_worker/beat.sh + railway-*.toml 是未部署的拆分套件
│   ├── tests/unit/          4,911 tests；根目錄的 test_terminal_path_six_things_matrix.py 與 test_openapi_contract.py（+快照）不可移動
│   └── tests/integration/   13 tests，真 PG（TEST_DATABASE_URL），CI 未跑
├── frontend/                React 18 + Vite 6 + Zustand 5（Node ≥ 22.17）
│   ├── src/main.tsx → App → navigation/RootNavigator（lazy 31 頁；ProtectedRoute／RoleGuard；/:lng/ 前綴）
│   ├── src/i18n/            index.ts（lng 由 URL 決定；10 namespace 預載）、paths.ts、locales/（來源）→ public/locales/（build 鏡像）
│   ├── src/services/        api/*（axios client，camel↔snake）、websocket.ts、audioStream.ts、sentry.ts（DSN 未設時整包被 tree-shake）
│   ├── src/stores/          8 個 Zustand store
│   ├── src/screens/         auth／patient／doctor／admin（ConversationPage 1.5k 行屬語音路徑）
│   ├── src/utils/           date（relativeTime）、format、coalesceRefresh、patientFacingReport、lazyWithRetry
│   ├── scripts/verify/      npm test 跑的 node 測試 + 手動的 smoothness-*.mjs
│   └── tests/e2e/           Playwright 3 spec（mock mode）
├── flutter_app/             Flutter 3.41.3（fvm）+ Riverpod 3 + go_router 17
│   ├── lib/main.dart → app.dart → core/router/app_router.dart（28 路由全 _lngKeyed；StatefulShellRoute 5 branch）
│   ├── lib/core/            config/env（API_BASE／WS_BASE dart-define）、i18n（t()）、theme、router
│   ├── lib/data/api/        dio_client（refresh／retry／登入世代隔離）、parse_page（所有分頁 API 共用）、各資源 API
│   ├── lib/features/        auth／patient（kiosk）／voice（audio_stream_service、ws_manager、tts_playback、conversation_controller autoDispose）／doctor／admin
│   ├── lib/shared/          ui_kit（共用元件）、format、toast、share_bytes、pdf_download*
│   ├── test/ 35 檔 321 tests；integration_test/ 10 檔（需 simulator，不在 CI）；tool/（TestFlight／Vercel／demo 影片／env.production.sh）
│   └── pubspec.yaml         本輪移除 cupertino_icons、path_provider
├── scripts/                 check_translations.py、red_flag_eval.py、refresh_graphify.sh、e2e_realopenai/（driver 5.4k 行；results/ 為 untracked 證據）、tests/（CI）
├── docs/                    README.md 入口；本稽核在 docs/audit_2026-10/
├── .github/workflows/       ci.yml（backend unit + scripts tests／frontend／flutter／e2e-playwright）、i18n_staleness.yml
└── .claude/skills/          7 個專案技能（入庫）
```

## 主要執行流程

1. **病患問診**：Flutter kiosk／React → `POST /sessions`（intake 經 `PromptSafeFreeText` 消毒）→ WS `/ws/sessions/{id}/stream`（首幀 auth）→ `conversation_handler`：音訊 chunk → STT → `llm_conversation`（串流、早句送出）→ 每輪 `red_flag_detector`（規則共現 + 語意）＋背景 `supervisor` → 自動結束／紅旗中止 → 終態六件事（status CAS、SOAP `report_queue.delay`、病患 `session_status`、dashboard publish、醫師通知、`_terminated`）。
2. **SOAP**：Celery `report_queue` → `soap_generator`（`patient_context.build_patient_info` 共用）→ `report_generated` publish → 通知。
3. **醫師端**：REST 清單／詳情（全部經 `session_not_deleted()`，clinician scope 由 `core/authz`）+ WS `/ws/dashboard`（Redis pub/sub 跨 worker；`initial_state`／`queue_updated`／`stats_updated`／`new_red_flag`…）。
4. **背景**：beat 每 5 分鐘 `session_timeout`（60 分鐘閒置 → cancelled，已排除軟刪除）、每月分區／稽核保留／音檔清理。
5. **部署**（手動）：Railway `railway up`（`start.sh` 自動 migrate）、Vercel `vercel --prod` + alias、TestFlight `tool/build_ios_testflight.sh`。

## 模組依賴方向（應維持）
`routers → services → models`；`services` 之間只經 `core/authz`、`session_visibility`、`NotificationService._doctor_targets` 等少數共用點；`websocket/conversation_handler` 依賴 pipelines 與 services，但 pipelines 不得反向依賴 websocket；`tasks/*` 以 `run_async` 隔離自己的 loop，不可取用 API 行程的 Redis 池（`pool_for_current_loop` 會自動回 None）。
