# Frontend audit — gu-voice/frontend (branch `refactor/codebase-audit-2026-10`, 2026-10-23)

Read-only audit. Nothing in the repo was modified. All paths below are relative to `frontend/` unless prefixed with `../`.
Baseline reconfirmed: `npm test` → 15/15 pass (269 ms); `diff -rq src/i18n/locales public/locales` → identical; `python3 ../scripts/check_translations.py` → `Result: OK` (50 mirror files in sync); `npm run i18n:extract:check` → PASS.
Working tree: 256 changed paths, `frontend/src` diff = 51 files / +808 −689 (untouched).

Categories: **A** in use · **B** safe to remove (proof given) · **C** suspect, needs verification · **D** duplicate/mergeable · **E** perf/architecture opportunity.

---

## 1. Module map

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `src/main.tsx` (entry) | A | `initSentry()` then `<StrictMode><Suspense><App/>` (`main.tsx:11,36-42`); imports `./i18n` side-effect (`:9`) | – | – |
| `src/App.tsx` | A | hydrates auth (`App.tsx:15-17`), toggles `dark` class from `settingsStore.theme` (`:20-22`), mounts `RootNavigator` + `Toaster` | – | – |
| `src/navigation/RootNavigator.tsx` | A | all 31 screens + 2 layouts via `lazyWithRetry` (`:17-56`); guards `ProtectedRoute` (`:59-84`), `RoleGuard` (`:87-97`), `RoleRedirect`, `RootRedirect`; `KioskIdleGuard` mounted once (`:132`) | – | – |
| `src/components/` | A | `chat/ChatBubble`, `common/{EmptyState,ErrorState,LanguageSwitcher,LoadingSpinner,Modal,ThemeToggle}`, `dashboard/AlertItem`, `form/SearchBar`, `layout/{Header,LanguageLayout,MainLayout,PatientLayout,Sidebar}`, `medical/{SeverityBadge,SOAPCard,StatusBadge,TranscriptPanel}`, `DoctorAlertPoller`, `KioskIdleGuard` — every file has ≥1 importer (importer graph, §3) | – | – |
| `src/hooks/` | A | `useAudioStream` (←ConversationPage), `useClickOutside` (←Header, PatientLayout), `useInfiniteScroll` (←Alert/Notification/Patient/ReportList), `useRedFlagAlerts` (←AlertListPage), `useWebSocket` (3 hooks: `useConversationWebSocket`, `useDashboardConnection` ←MainLayout, `useDashboardWebSocket` ←6 consumers) | – | – |
| `src/i18n/` | A | `index.ts` (i18next + HttpBackend + LanguageDetector, 10 namespaces preloaded `:34-45`), `paths.ts` (URL-lng helpers, 29 importers), `locales/{zh-TW,en-US,ja-JP,ko-KR,vi-VN}/{10 ns}.json` | – | see §7/§9 |
| `src/screens/` | A | admin 4, auth 4, doctor 13 + `research/charts.tsx`, patient 9 — each imported exactly once by `RootNavigator.tsx` | – | – |
| `src/services/` | A | `api/{client,admin,alerts,auth,complaints,dashboard,notifications,patients,reports,research,sessions}.ts`; `websocket.ts` (`WebSocketManager`, singletons `conversationWS`/`dashboardWS` `:439-442`); `audioStream.ts` (mic/VAD/ScriptProcessor); `pcmRingBuffer.ts`, `wavEncoder.ts`; `sentry.ts` | – | – |
| `src/stores/` (Zustand 5) | A | 8 stores, see store table below | – | – |
| `src/types/` | A | `index.ts` (domain models, 37 importers), `api.ts` (request/response DTOs, 17), `enums.ts` (10), `websocket.ts` (3) | – | §2 for dead members |
| `src/utils/` | A/B | `coalesceRefresh` (5), `date` (2), `format` (16), `lazyWithRetry` (1), `patientFacingReport` (3), **`validation` (0 importers)** | – | §3 |

**Route table** (`RootNavigator.tsx:134-186`; all under `/:lng` → `LanguageLayout`):

| Path | Screen | Guard |
|---|---|---|
| `/` , `/*` (non-lng) | `RootRedirect` → `/${detectInitialLanguage()}…` | none |
| `/:lng/login`, `register`, `forgot-password`, `reset-password` | `LoginPage`, `RegisterPage`, `ForgotPasswordPage`, `ResetPasswordPage` | public |
| `/:lng/patient`, `patient/start`, `patient/medical-info`, `patient/history`, `patient/history/:sessionId`, `patient/settings`, `patient/session/:sessionId/complete`, `patient/session/:sessionId/thank-you` | `PatientHomePage`, `SelectComplaintPage`, `MedicalInfoPage`, `PatientHistoryPage`, `PatientSessionDetailPage`, `PatientSettingsPage`, `SessionCompletePage`, `SessionThankYouPage` | `ProtectedRoute` → `RoleGuard[patient,doctor,admin]` → `PatientLayout` |
| `/:lng/conversation/:sessionId` | `ConversationPage` (full-screen, no layout) | `ProtectedRoute` only (any role) |
| `/:lng/dashboard`, `research`, `patients`, `patients/:patientId`, `sessions`, `sessions/:sessionId`, `reports`, `reports/:sessionId`, `alerts`, `alerts/:alertId`, `notifications`, `settings` | `DashboardPage`, `ResearchAnalyticsPage`, `PatientListPage`, `PatientDetailPage`, `SessionListPage`, `SessionDetailPage`, `ReportListPage`, `SOAPReportPage`, `AlertListPage`, `AlertDetailPage`, `NotificationPage`, `SettingsPage` | `ProtectedRoute` → `RoleGuard[doctor,admin]` → `MainLayout` |
| `/:lng/admin/users`, `admin/complaints`, `admin/health`, `admin/audit-logs` | `UserManagementPage`, `ComplaintManagementPage`, `SystemHealthPage`, `AuditLogsPage` | …→ `RoleGuard[admin]` |
| `/:lng` (index), `/:lng/*` | `RoleRedirect` (patient→`/patient`, else `/dashboard`) | `ProtectedRoute` |

**Stores** (file:line = state interface):

| Store | State shape | Consumers |
|---|---|---|
| `authStore.ts:18` | `recoveryRequired, user, accessToken, isAuthenticated, isLoading, error` + login/logout/hydrateFromStorage/refreshSession; **mock branch** `:152-191` | 22 files (App, guards, layouts, client.ts, other stores, verify tests) |
| `settingsStore.ts:19` (persist `gu-settings`) | `theme, language, audioInputDevice, notificationsEnabled, soundEnabled, ttsMuted, ttsSpeed`; `setLanguage` calls `i18n.changeLanguage` (`:62-66`); global `languageChanged` listener (`:82-89`) | App, DoctorAlertPoller, LanguageSwitcher, ThemeToggle, SettingsPage, ConversationPage, PatientSettingsPage |
| `conversationStore.ts:48` | `currentSession, conversations[], isRecording, isAIResponding, sttProcessing, userPaused, sttPartialText, aiStreamingText, recordingDuration, audioLevel, waveformData, activeRedFlags, supervisorGuidance, missingHpi, supervisorDegraded, error` | ConversationPage, useAudioStream, KioskIdleGuard, LanguageSwitcher, 4 unit tests |
| `alertStore.ts:24` | `alerts, unacknowledgedCount, totalCount, allTotalCount, isLoading, cursor, hasMore, filter, error`; mock `:16-22,62-77,166-169` | DoctorAlertPoller, Sidebar, useRedFlagAlerts, AlertListPage |
| `notificationStore.ts:11` | `notifications, unreadCount, loaded, isLoading, cursor, hasMore, error` | DoctorAlertPoller, Header, NotificationPage |
| `patientListStore.ts:24` | `patients, selectedPatient, isLoading, cursor, hasMore, totalCount, searchQuery, selectedMonth, error`; mock `:13-22,67-84` | PatientListPage |
| `reportStore.ts:107` | `reviewCounts, reports, selectedReport, conversations, isLoading, isLoadingConversations, cursor, hasMore, error`; mock `:20-105,208-217,232-235` | ReportListPage, SOAPReportPage, SessionDetailPage, SessionCompletePage |
| `complaintStore.ts:23` | `complaints, groupedComplaints, isLoading, error` | SelectComplaintPage |

**Services**: `api/client.ts` — axios instance, camel/snake transforms (`:66-70`), auth-epoch + single-flight `refreshAccessToken` (`:224`), `isAuthRejected` (`:108`). `websocket.ts` — reconnect with backoff (`:331`), ping interval (`:394`), auth-failure handler + `_auth_exhausted`, stale-socket handler detach (`:232-239`). `audioStream.ts` — getUserMedia (`:155`), `createScriptProcessor` (`:195`, deprecated API, noted in code), duration interval, rAF meter, full teardown `:507-553`. `sentry.ts` — DSN-gated init with PII redaction.

---

## 2. Unused exports (ts-prune, 58 items verified)

Verification method for every item: grep of the symbol across `src/`, `scripts/`, `tests/`, `index.html`; all API modules are imported as namespaces (`import * as xApi`) — grep `(Api|api)\[` returns nothing, so no computed-member access exists; no `t()` or string-keyed lookup involves these names; e2e specs/`scripts/verify/*.mjs` do not reference them.

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `i18n/index.ts:27 BETA_LANGUAGES` | B | only its definition in code; sole other mention `../docs/archive/修改.md:78`; `language.betaTag` i18n key also unreferenced (§7) | none | delete (or wire the "(beta)" tag into `LanguageSwitcher` if product wants it) |
| `i18n/paths.ts:63 extractLngFromPath` | B | definition only; `LanguageLayout` reads `useParams` instead | none | delete |
| `services/sentry.ts:66 _redact` | B | comment says "供測試 import" but no test imports it (grep `_redact` → only `docs/TODO.md:288`, `docs/archive/...`) | none | delete, or add the test it promises |
| `types/enums.ts:99 sessionStatusDisplay`, `:107 alertSeverityDisplay` | B + D | definition only; hard-coded zh-TW labels superseded by i18n `StatusBadge.tsx:15-45` / `SeverityBadge.tsx:16-36` | none | delete |
| `types/index.ts:149 Conversation`, `:181 SOAPReport`, `:330 RedFlagRule`, `:347 Notification`, `:360 AuditLog`, `:385 PaginatedResponse` | A (ts-prune false positive) | imported via `'../types'` in stores/services (e.g. `conversationStore.ts:6`, `reportStore.ts:6`, `admin.ts:6`, `notifications.ts:6`) | – | keep (`RedFlagRule` becomes B if the rules API below is removed) |
| `types/index.ts:373 FCMDevice`, `:396 ErrorResponse` | B | type-only, zero references; not referenced by docs for the web client | none | delete |
| `types/websocket.ts` 17 items: `AudioChunkPayload:17`, `ControlPayload:30`, `PingPayload:34`, `ClientMessageType:38`, `ConnectionAckPayload:44`, `WSErrorPayload:130`, `PongPayload:151`, `ServerMessageType:155`, `SessionCreatedPayload:173`, `SessionStatusChangedPayload:180`, `NewRedFlagPayload:187`, `RedFlagAcknowledgedPayload:196`, `ReportGeneratedPayload:201`, `QueueUpdatedPayload:208`, `StatsUpdatedPayload:220`, `InitialStatePayload:234`, `DashboardEventType:262` | C | zero references; handlers use inline casts instead (`DoctorAlertPoller.tsx:64 payload as { alertId?: string }`, `useWebSocket.ts:51`). They are the only written WS contract on the web side; `types/websocket.ts:112,127` carry TODO-E2 contract notes | removing loses contract docs; keeping = drift risk | either type the `on()` handlers with them (preferred, e.g. `on<NewRedFlagPayload>('new_red_flag', …)`) or delete the dashboard subset |
| `utils/date.ts:10 parseISO`, `:17 isToday`, `:30 isThisWeek`, `:79 toDateString`, `:87 toTimeString` | B | definition only; only `relativeTime` (`:49`) is imported (`ChatBubble.tsx`, `AlertItem.tsx`) | none | delete 5 fns; see §6 for `relativeTime` vs `formatRelative` |
| `utils/format.ts:81 truncateText`, `:94 formatWaitingTime`, `:139 formatRelative` | B | definition only; `formatRelative` mentioned in `docs/` twice (prose) | none | delete; `formatRelative` duplicates `date.ts:relativeTime` (D) |
| `utils/validation.ts:8 validateEmail`, `:19 validatePassword`, `:31 validatePhone`, `:41 validateRequired`, `:49 validateConfirmPassword` | B (whole file) | file has **0 importers**; screens re-implement with i18n (`RegisterPage.tsx:30-35`, `ResetPasswordPage.tsx:27-32`, `ForgotPasswordPage.tsx:22-26`) and only mention it in comments; messages are hard-coded zh (`validation.ts:11,22-24,34`) | none | delete file; then dedupe the password rule into one helper (D) |
| `services/api/admin.ts:74 getRedFlagRules`, `:84 createRedFlagRule`, `:89 updateRedFlagRule`, `:97 deleteRedFlagRule` | B | `adminApi.` call sites = createUser, getAuditLogs, getSystemHealth, getUsers, resetUserPassword, toggleUserActive, updateUser only; no rules UI/route | none | delete + `RedFlagRule` type + `RULES_BASE` |
| `services/api/complaints.ts:23 getComplaint` | B | `complaintsApi.` call sites: create/delete/getComplaints/reorder/update | none | delete |
| `services/api/dashboard.ts:17 getDashboardStats`, `:23 getDashboardQueue`, `:37 getRecentAlerts`, `:43 getRecentSessions` | B | only `dashboardApi.getMonthlySummary` is called (`DashboardPage.tsx:339`); CLAUDE.md forbids using `/dashboard/*` day stats for date grouping (UTC bucketing) | none | delete 4 fns + `DashboardStatsResponse/DashboardQueueResponse/QueueItem/RecentAlertItem/RecentAlertsResponse/RecentSessionItem/RecentSessionsResponse` (`types/api.ts:170-225`) which become dead |
| `services/api/notifications.ts:47 getNotificationPreferences`, `:53 updateNotificationPreferences`, `:63 registerFcmToken`, `:71 deleteFcmToken` | B | `notificationsApi.` call sites: getNotifications, getUnreadCount, markAllAsRead, markAsRead; web has no FCM; settings toggles are local (`settingsStore.ts:23-24`) | none | delete + `NotificationPreference/NotificationPreferenceUpdate/FcmTokenCreateRequest/FcmTokenResponse` (`types/api.ts:286-324`) + `FCMDevice` |
| `services/api/patients.ts:24 createPatient`, `:30 updatePatient` | B | `patientsApi.` call sites: deletePatient, getPatient, getPatients, getPatientSessions | none | delete + `PatientCreateRequest/PatientUpdateRequest` (`types/api.ts:42-71`) |

Public-contract note: none of the exported types are consumed outside `frontend/src`; `docs/` references are prose only (`docs/archive/修改.md:78` for `BETA_LANGUAGES`). Removing them changes no contract.

---

## 3. Unused files and alias health

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `src/utils/validation.ts` | B | importer graph (scratchpad `importers.mjs`, resolves `./`, `../`, and all 9 aliases): 0 importers; every other non-entry, non-test file has ≥1 importer | none | delete |
| Zero-importer list (expected) | A | `main.tsx` (entry), `vite-env.d.ts` (ambient), 12 `__tests__/*.test.mts` (run by `npm test` glob) | – | – |
| tsconfig/vite aliases `@/*, @components/*, @hooks/*, @pages/*, @stores/*, @utils/*, @types/*, @services/*, @assets/*` (`tsconfig.json:30-40`, `vite.config.ts:83-93`) | B/C | **no alias is used anywhere in `src/`** (grep `from '@(/\|components\|…)'` → 0); every import is relative. `@pages/*` → `src/pages` and `@assets/*` → `src/assets` **do not exist**. vite and tsconfig lists match each other exactly | `@types/*` shadows the npm `@types/...` scope name — a future `import x from '@types/foo'` resolves to `src/types/foo` | delete all 9 aliases from both configs (or keep only `@/*` and adopt it); at minimum drop `@pages`, `@assets`, `@types` |
| `tsconfig.json:42 "include": ["src", "vite-env.d.ts"]` | C | `frontend/vite-env.d.ts` does not exist (file lives at `src/vite-env.d.ts`, already covered by `"src"`) | none | drop the stale entry |
| `src/vite-env.d.ts` env typing | C | declares 7 vars; code reads `VITE_KIOSK_IDLE_TIMEOUT_MS` (`KioskIdleGuard.tsx:19`) and `VITE_MOCK_ROLE` (`authStore.ts:154`) which are **not declared** | type-safety gap only | add the two declarations |

---

## 4. Mock mode (`VITE_ENABLE_MOCK`)

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Mock gating spread over 17 files, ≈560 gated LOC | A (e2e dependency) + E | brace-matched count (scratchpad `mockloc.mjs`): `reportStore` 90, `ReportListPage` 70, `PatientHistoryPage` 64, `DashboardPage` 52, `authStore` 40, `PatientHomePage` 37, `SessionCompletePage` 36, `SOAPReportPage` 31, `patientListStore` 28, `SelectComplaintPage` 28, `alertStore` 27, `UserManagementPage` 20, `ConversationPage` 19, `SessionListPage` 14, `MedicalInfoPage` 4, `client.ts` 3 | mock branches inside screens = screen logic diverges from real path; each new screen re-implements the pattern | consolidate into one mock adapter at the `services/api` boundary (or MSW) so screens/stores have a single code path |
| Production leak guard | A | `vite.config.ts:153-156` `define` forces `import.meta.env.VITE_ENABLE_MOCK='false'` in production → `IS_MOCK` constant-folds and mock data is tree-shaken (dist grep for `mock-doctor-001`: absent) | – | keep |
| Playwright depends on mock | A | `playwright.config.ts:44-50` webServer sets `VITE_ENABLE_MOCK=true VITE_MOCK_ROLE=patient`; specs pre-seed `localStorage.access_token='mock-token'` (`tests/e2e/other_complaint.spec.ts:22-24`) and rely on `authStore` mock user (`authStore.ts:152-191`); `i18n_en_no_cjk.spec.ts:143-178` additionally `page.route()`s 4 API endpoints | removing mock auth breaks all 3 specs | keep; if consolidating, keep the mock auth + complaints path first |
| `scripts/verify/smoothness-*.mjs` | A (not mock) | header: "Run against npm run build + vite preview (no mock mode). All backend traffic is intercepted" (`smoothness-browser.mjs:4`) | – | – |
| `.env.production` `VITE_ENABLE_MOCK=false`, `VITE_MOCK_ROLE=patient` | C | mock role is meaningless in prod but harmless (define override wins) | none | drop `VITE_MOCK_ROLE` from `.env.production` (see §11) |

---

## 5. Dependencies

| Package | Category | Where used | Risk | Recommendation |
|---|---|---|---|---|
| `@sentry/react` | C | `src/services/sentry.ts:7` only. **Absent from `dist/`** (`grep -ci sentry dist/assets/*.js` = 0, `tracesSampleRate` = 0, 69 chunks): `VITE_SENTRY_DSN` is unset in `.env.production` (and locally), so `import.meta.env.VITE_SENTRY_DSN` folds to `undefined`, `initSentry` returns early and Rollup tree-shakes the SDK | Sentry is **inert in the local prod build**; if Vercel's build env sets the DSN it would land in the main `index` chunk (no `manualChunks` entry, `vite.config.ts:132-141`) | verify Vercel env; if enabling, `await import('@sentry/react')` inside `initSentry` so it never joins `index` |
| `axios` | A | `api/client.ts`, `api/auth.ts`, `scripts/verify/*.test.mjs` → `vendor-utils` 37.5 KB | – | – |
| `date-fns` | D/E | only `format/startOfMonth/endOfMonth/addMonths` in `patientListStore.ts:5`, `PatientListPage.tsx:5`, `DashboardPage.tsx:1`; lands in shared chunk `format-CGWe5iV_.js` 20 KB (`grep -l date-fns` hits that chunk; composition not fully provable from minified output → C) | 20 KB for 4 trivial fns; `format(d,'yyyy 年 M 月')` at `PatientListPage.tsx:112` hard-codes Chinese | replace with `Intl.DateTimeFormat` (already the pattern in `utils/format.ts`) and drop the dep |
| `i18next`, `react-i18next`, `i18next-http-backend` | A | `i18n/index.ts:14-17`; many screens | – | – |
| `i18next-browser-languagedetector` | C | `i18n/index.ts:16,80-84` (order localStorage→navigator). Project rule: URL is the only language authority; `LanguageLayout.tsx:71-75` immediately overrides with URL lng | detector can pick a language ≠ URL on boot → double namespace load (see §9) | replace with `lng: extractLngFromPath(location.pathname)` at init (which also rescues the dead export in §2) |
| `lucide-react` | A | ~20 screens; tree-shakes to per-icon chunks (`createLucideIcon-*.js` 2.5 KB) | – | – |
| `react`, `react-dom`, `react-router-dom` | A | everywhere → `vendor-react` 166 KB | – | – |
| `react-hot-toast` | A | `App.tsx:6` + 10 screens | – | – |
| `uuid` | D | single use `services/websocket.ts:6` (`v4`); `ConversationPage.tsx:394` already uses `crypto.randomUUID()` | – | replace with `crypto.randomUUID()` and drop the dep |
| `zustand` | A | 8 stores → `vendor-state` 0.6 KB | – | – |
| `@playwright/test` | A | `playwright.config.ts`, 3 specs; CI `e2e-playwright` job | – | – |
| `playwright` (transitive, flagged missing by depcheck) | C | `scripts/verify/smoothness-browser.mjs:1`, `smoothness-performance.mjs:1` import `'playwright'` directly; resolves only via `@playwright/test`'s dependency | breaks on hoisting change | import from `@playwright/test` (`chromium`, `webkit` are re-exported) or add explicit devDep |
| `@eslint/js` (transitive, flagged missing) | C | `eslint.config.js:5`; present only via `eslint` | same | add as explicit devDependency |
| `@types/node`, `@types/react`, `@types/react-dom`, `typescript`, `vite`, `@vitejs/plugin-react` | A | tsc/vite toolchain (`vite.config.ts:2-4` uses `path`, `fs`) | – | – |
| `eslint`, `@typescript-eslint/*`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals` | A | `eslint.config.js`; `npm run lint` in CI (`ci.yml:117`) | – | – |
| `tailwindcss`, `postcss`, `autoprefixer` | A | `postcss.config.js`, `tailwind.config.js`, `index.css` | – | – |
| `i18next-parser` | A | `npm run i18n:extract[:check]`, `scripts/i18n-extract-check.mjs:30`, CI `i18n_staleness.yml:202` | – | – |
| `prettier`, `prettier-plugin-tailwindcss` | C | only `format`/`format:check` scripts; **no `.prettierrc`**, not run in CI, plugin never referenced | dead tooling or implicit defaults | either add config + CI check or remove both |

---

## 6. Duplicate / mergeable logic (D)

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Relative time ×2 | D | `utils/date.ts:49 relativeTime` (used) vs `utils/format.ts:139 formatRelative` (unused) — both `Intl.RelativeTimeFormat` | – | delete `formatRelative`; keep one |
| Local-day key ×4 | D | `ReportListPage.tsx:119 getDateKey`, `AlertListPage.tsx:51 getDateKey` (byte-identical), `PatientListPage.tsx:37 format(createdAt,'yyyy-MM-dd')`, `utils/date.ts:79 toDateString` (unused) | drift (one uses date-fns) | one `localDayKey()` in `utils/date.ts` (matches CLAUDE.md local-day rule) |
| Day heading ×2 | D | `ReportListPage.tsx:128 getDayLabel` ≡ `AlertListPage.tsx:60 getDateLabel` (same `formatDate` options); `PatientListPage.tsx:22 formatGroupHeading` third variant | – | merge into `utils/format.ts` |
| Month range / day-bound ISO ×3 | D | `patientListStore.ts:45 getMonthDateRange`, `AuditLogsPage.tsx:21 localDayIso`, `PatientListPage.tsx:18 formatMonthRange` + `DashboardPage.tsx:338 format(selectedMonth,'yyyy-MM')` | tz bugs fixed in one place but not another | shared `localMonthRange()` / `localDayBounds()` |
| Hard-coded zh month label | C | `PatientListPage.tsx:112 format(selectedMonthDate, 'yyyy 年 M 月')` shown in `patientList.emptyTitle` and helpers for every locale | i18n defect (en-US shows 年/月) | use `t('doctor.dashboard.monthFormat', …)` like `DashboardPage.tsx:314-318` |
| Infinite scroll | A (resolved) | `useInfiniteScroll` adopted by Patient/Report/Alert/Notification list pages; no inline `IntersectionObserver` left in screens | – | remaining non-paginated: `SessionListPage.tsx:63 limit:50`, `UserManagementPage.tsx:81 limit:50`, `AuditLogsPage.tsx:42 limit:100` |
| Click-outside | D | `useClickOutside` used by Header/PatientLayout; `LanguageSwitcher.tsx:63-77` still has an inline copy | – | use the hook |
| Refresh coalescing | D | `coalesceRefresh` used ×4; `ResearchAnalyticsPage.tsx:113-117` re-implements debounce with `setTimeout` ref; `DashboardPage.tsx:333-345` request-id guard | – | use `coalesceRefresh` in Research page |
| API error handling | D/E | 78 `catch` blocks in screens/stores; outcomes: `setError` ×12, `toast.error` ×11, `console.error` ×5, bespoke `setFormError/setPasswordError/setReviewError`; no shared `getErrorMessage(err)`; `ConversationPage.tsx` alone has 13 catches | inconsistent UX; backend `detail` never surfaced | add one `apiErrorMessage(err, t)` helper in `services/api/client.ts` and route every catch through it |
| Header vs PatientLayout user menu | D | `Header.tsx:74-124` and `PatientLayout.tsx:46-120` — same avatar button, dropdown, name/email block, logout (`useClickOutside`, `menuOpen`, `handleLogout` duplicated at `Header.tsx:21-30` / `PatientLayout.tsx:19-26`) | – | extract `<UserMenu />` (~65 lines removed) |
| Session-status → label maps ×6 | D | `enums.ts:99 sessionStatusDisplay` (dead, zh), `StatusBadge.tsx:15`, `PatientHomePage.tsx:48 statusKeyMap`, `PatientHistoryPage.tsx:87 statusLabel`, `AlertListPage.tsx:34 sessionStatusLabel`, `ReportListPage.tsx:159 sessionStatusLabel` (last two byte-identical) | new status = 6 edits | one `sessionStatusLabel(status,t)` + `<StatusBadge>` |
| Severity maps ×3 | D | `enums.ts:107 alertSeverityDisplay` (dead), `SeverityBadge.tsx:16`, `AlertItem.tsx:28 severityBorderClass` | – | delete dead one; keep badge as single source |
| Password / email validation ×3 | D | `validation.ts:19-25` (dead), `RegisterPage.tsx:30-35`, `ResetPasswordPage.tsx:27-32` identical rule chains; email regex `ForgotPasswordPage.tsx:24` vs `validation.ts:10` | – | one i18n-aware `passwordStrengthError(pw,t)` |
| Language state ×3 sources | C/D | `settingsStore.language` (persisted to `gu-settings`) + `setLanguage→i18n.changeLanguage` (`settingsStore.ts:62-66`) + `LanguageLayout` URL→i18n (`:71-75`) + `i18n.on('languageChanged')` back-sync (`settingsStore.ts:82-89`); `LanguageSwitcher.tsx:96-97` calls both `setLanguage` and `syncUrlLng` | violates "URL only authority" in spirit (localStorage copy survives), races on async changeLanguage (`LanguageSwitcher.tsx:140-144` works around it) | make `LanguageSwitcher` navigate only; derive `language` from URL; drop `settingsStore.language` |
| Type files | A | no name overlap between `types/index.ts`, `api.ts`, `websocket.ts` (`comm` on exported names = ∅); `SessionStatus/AlertSeverity` string unions are re-derived locally in some components (`AlertItem.tsx:15 severity: string`) | weak typing only | type `AlertItem.severity` as `AlertSeverity` |

---

## 7. i18n

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Mirror sync | A | `diff -rq src/i18n/locales public/locales` → no output; `check_translations.py` → `[MIRROR] frontend/public/locales OK (50 file(s) in sync)`, `Result: OK`; working tree has matching uncommitted edits in both trees (`git diff --stat`: 10 files, `common.json` ×5 ×2) | – | commit source + mirror together (project rule) |
| Coverage | A | `common.json` 100 % (246/246) for all locales; `conversation/dashboard/intake/research/session/soap/ws` reported "skipped (beta, uses fallback)" for beta locales | – | – |
| Keys used in code but missing in zh-TW | A | `npm run i18n:extract:check` → PASS (14 "Key is not a string literal" warnings = dynamic keys) | – | – |
| Dynamic key patterns found (excluded from unused scan) | A | `language.names.${lng}` (LanguageSwitcher:98,148,159,204,256), `fieldLabels.${key}`, `objective.vitalSigns.{labels,units}.${key}`, `assessment.probability.${…}`, `plan.urgency.${…}`, `section.${…}` (SOAPCard), `transcript.roles.${role}` (TranscriptPanel:218), `admin:users.roleTab.${…}`, `admin:users.role.${…}` (UserManagementPage:244), `hpi.fields.${f.field}` (ResearchAnalyticsPage:268), `conversation:supervisor.hpi.${dim}` (ConversationPage:1278), `medicalInfo.{commonAllergies,commonConditions,frequency,yearsAgo,relations}.${k}` (MedicalInfoPage), `selectComplaint.categories.${bucket}` (SelectComplaintPage:223), `t(config.labelKey)` (StatusBadge:62, SeverityBadge:56), `t(sc.labelKey)` (PatientHomePage:184), `t(key)` (SessionCompletePage:207), **`t(data.code, …, {ns:'ws'})`** (ConversationPage:804,841 — backend-supplied codes) | – | – |
| Unreferenced zh-TW keys | C/B | 1140 keys total; **43** have no static or dynamic-prefix reference (scratchpad `i18nkeys2.mjs`): `common` 11 — `back`, `save`, `login.submitting`, `roles.system`, `language.label`, `language.betaTag`, `common.emptyTitle`, `common.viewAll`, `doctor.patient.noName`, `pagination.loadMore`, `pagination.loadingMore`; `conversation` 5 — `status.thinking`, `status.speaking`, `error.disconnected`, `error.audioTooLong`, `mockMessages.systemStart`; `ws` 27 — all `errors.ws.*` / `events.session.*` | the 27 `ws` keys are **A** (resolved at runtime from backend codes, cannot be statically proven); the other 16 are B candidates but Flutter has its own locale tree so no cross-client risk | delete the 16 `common`/`conversation` keys in all 5 locales + rebuild mirror; keep `ws` |
| i18n boot cost | E | `ns: ALL_NAMESPACES` (10) preloaded (`i18n/index.ts:64`) + `fallbackLng` chain → zh-TW/en-US boot = 10 JSON requests; ja/ko/vi = up to 30 (`public/locales` = 400 KB total) | first paint waits on Suspense for namespaces the route never uses (`research`, `admin`, `soap`) | preload `common` only and let `useTranslation('research')` lazy-load per route |

---

## 8. Size / complexity hot spots (E)

Top 15 by LOC (`src/**/*.ts|tsx`, total 20 298):

| File | LOC | Category | Evidence | Recommendation |
|---|---|---|---|---|
| `screens/patient/ConversationPage.tsx` | 1547 | E | one component of **1405 lines** (L74-1478); `useState` 8, `useEffect` 13, `useRef` 11, `useCallback` 18, `useMemo` 0; one effect spans **L616-904 (289 lines)** registering 13 WS handlers with `eslint-disable react-hooks/exhaustive-deps` (also `L534-575`) | split WS handler registration into `useConversationEvents(sessionId)` and TTS queue into its own hook; voice-pipeline-invariants skill applies |
| `screens/patient/MedicalInfoPage.tsx` | 848 | E | component 715 lines; `useState` ×18, no memo/callback | split per intake section (history/medications/allergies/family) |
| `screens/doctor/SOAPReportPage.tsx` | 761 | E | component 601 lines; `useState` ×12; 50 KB chunk | extract review panel + meta cards |
| `components/medical/SOAPCard.tsx` | 686 | E | `PlanContent` 133, `SubjectiveContent` 104, `ObjectiveContent` 97, `normalizePlan` 67 | fine-grained already; consider file-per-section |
| `services/audioStream.ts` | 565 | A | service class; deprecated `createScriptProcessor` (`:195`) | AudioWorklet migration when verified on devices |
| `types/api.ts` | 518 | A/B | ≥11 interfaces become dead after §2 removals | prune |
| `screens/admin/UserManagementPage.tsx` | 517 | E | single 477-line component, `useState` ×13 | extract form modal |
| `screens/doctor/DashboardPage.tsx` | 475 | A | component 169; donut/trend cards split | – |
| `screens/doctor/ReportListPage.tsx` | 473 | A | component 294; `useMemo` ×5 | – |
| `services/websocket.ts` | 442 | A | well-tested manager | – |
| `screens/doctor/ResearchAnalyticsPage.tsx` | 440 | A | – | – |
| `screens/doctor/research/charts.tsx` | 438 | A | inline SVG charts, 13 `style={{}}` | – |
| `screens/doctor/AlertListPage.tsx` | 418 | A | component 293; `useMemo` ×3 | – |
| `types/index.ts` | 404 | A | – | – |
| `screens/patient/SelectComplaintPage.tsx` | 389 | A | – | – |

Components > 400 lines: `ConversationPage` (1405), `MedicalInfoPage` (715), `SOAPReportPage` (601), `UserManagementPage` (477).

---

## 9. Performance review (E)

| Item | Category | Evidence | Why it matters | How to measure / fix |
|---|---|---|---|---|
| Whole-store subscriptions (12 sites) | E | `LoginPage.tsx:14`, `ReportListPage.tsx:183`, `SettingsPage.tsx:15,25`, `PatientListPage.tsx:93`, `AlertListPage.tsx:142`, `NotificationPage.tsx:40`, `SOAPReportPage.tsx:175`, `PatientSettingsPage.tsx:24`, `SessionCompletePage.tsx:49`, `SelectComplaintPage.tsx:138`, `ThemeToggle.tsx:10` — `useXStore()` with no selector | any field change re-renders the page; `ThemeToggle` sits in every header and re-renders on every settings write; `ReportListPage` re-renders when `selectedReport/conversations` change in `SOAPReportPage` | React Profiler "why did this render"; switch to selectors or `useShallow` (already used in `useAudioStream.ts:62-74`) |
| Chat list re-render during streaming | E | `ConversationPage.tsx:1295-1308` builds a **new `message` object literal per bubble each render**; `ChatBubble` is a plain function (no `memo`, `ChatBubble.tsx:29`); effects at `:966-981` fire on every `aiStreamingText`/`sttPartialText` token | every streamed chunk re-renders all N bubbles | Profiler during AI reply; pass `msg` directly + `React.memo(ChatBubble)` |
| Giant WS effect | E | `ConversationPage.tsx:616-904` deps `[sessionId]` with `exhaustive-deps` disabled; handlers read store via `getState()` to avoid re-subscribe | correctness relies on manual discipline; hard to test | move to a hook with explicit `useEvent`-style refs |
| Effect cleanup — OK | A | `DoctorAlertPoller.tsx:75-80` (interval + dispose + off), `KioskIdleGuard.tsx:48-51`, `useWebSocket.ts:93-96,174-177,204-212`, `useAudioStream.ts:154-157`, `ResearchAnalyticsPage.tsx:121-125`, `ReportListPage.tsx:200`, `SessionListPage.tsx:103-109`, `LanguageLayout.tsx:111-115`; `audioStream.ts:507-553` releases rAF/interval/ScriptProcessor/AudioContext/tracks | – | – |
| Effect cleanup — minor gaps | C | `DoctorAlertPoller.tsx:62 seen` Set grows unbounded per mount; `playBeep` allocates a new `AudioContext` per beep (`:21`, closed after 400 ms); `KioskIdleGuard.tsx:45` re-arms a timeout on every `mousemove` (unthrottled); `useInfiniteScroll.ts:18-31` rebuilds the observer whenever `hasMore/isLoading` flips | low | cap `seen`, reuse one AudioContext, throttle `arm` |
| Polling vs WS | A | `DoctorAlertPoller.tsx:72-74` polls every 20 s **only** when `!dashboardWS.isConnected`; 5 WS events + `new_red_flag` drive `coalesceRefresh` otherwise; each refresh = 2 requests (`:48-53`) | fine | – |
| In-render computation | E | `PatientListPage.tsx:116 groupPatientsByCreatedDate(patients, locale)` + `:111-113` date-fns formatting run on **every render** (no `useMemo`; page has 0 `useMemo`); `UserManagementPage` has 0 `useMemo`; `Sidebar.tsx:179-183` filters nav per render (small) | O(n) per keystroke of search input | `useMemo` keyed on `[patients, locale]` |
| Lists without virtualization | A/E | page sizes 20 (`alertStore:89`, `reportStore:152`, `patientListStore:96`, `notificationStore:36`); `SessionListPage.tsx:63` 50 one-shot; transcripts 100–200 (`ConversationPage.tsx:550`, `reportStore.ts:242`); `.list-card { content-visibility:auto }` (`index.css:429-432`, with a `ponytail:` note) | acceptable at these sizes | revisit if infinite scroll exceeds ~1k rows |
| i18n namespace fan-out | E | 10 namespaces preloaded (`i18n/index.ts:34-45,64`); LanguageDetector may choose a non-URL language first (`:80-84`), then `LanguageLayout.tsx:73` switches → second fetch; `i18next-http-backend` pulls `browser-ponyfill-*.js` (11 KB cross-fetch) into the boot path (`dist/assets/index-*.js` imports it) | boot waterfall: HTML → index.js → 10–20 JSON | Network tab on cold load; preload `common` only; init `lng` from URL; pass `backend.request` or use `i18next-resources-to-backend` with `import()` of JSON to drop the ponyfill |
| Route-level code splitting | A | every screen + both layouts via `lazyWithRetry` (`RootNavigator.tsx:17-56`); chunks per page in `dist/assets` (e.g. `SOAPReportPage` 50 KB, `ConversationPage` 38 KB, `MedicalInfoPage` 22 KB) | – | – |
| `public/logo.png` **1 077 339 bytes** | E | used as favicon (`index.html:5`) and 32/80 px logo (`LoginPage.tsx:60`, `Sidebar.tsx:204`, `PatientLayout.tsx:38`) — the single largest asset, bigger than all JS combined | 1 MB on every cold load, kiosk included | replace with SVG or ≤10 KB PNG + separate 32 px favicon; Lighthouse "properly size images" |
| Google Fonts | E | `index.html:14-17` loads 6 families (Inter, Noto Sans, TC, JP, KR, Source Code Pro) for every locale | CJK woff2 for 3 scripts fetched regardless of `lng` | load the CJK family matching URL lng |
| Deprecated audio API | E | `audioStream.ts:195 createScriptProcessor` (comment acknowledges AudioWorklet) | main-thread audio callbacks | AudioWorklet after device validation |

---

## 10. Tests

| Item | Category | Evidence | Gap / Recommendation |
|---|---|---|---|
| `src/screens/patient/__tests__/endSessionNoNavigate.test.mts` | A | EM-3: `handleEndSession` must not navigate (11 asserts) | – |
| `src/screens/patient/__tests__/patientFacingSurface.test.mts` | A | SessionCompletePage must not render ICD-10/confidence; intake `no_*` tri-state (15 asserts) | – |
| `src/services/__tests__/pcmRingBuffer.test.mts`, `wavEncoder.test.mts` | A | pure-function unit tests | – |
| `src/services/__tests__/wsAuthRecoveryGuard.test.mts`, `wsStaleSocketClose.test.mts`, `wsTokenProvider.test.mts` | A | WebSocketManager 4001 one-refresh guard; stale `onclose` isolation; token provider freshness | – |
| `src/stores/__tests__/normalizeSupervisorGuidance`, `resumedConversationsPatch`, `shouldUnmuteVAD`, `userPausedStore` | A | conversationStore pure helpers + userPaused state | – |
| `src/utils/__tests__/patientFacingReport.test.mts` | A | `resolvePatientFacing` locale selection | – |
| `scripts/verify/auth-logout-retry.test.mjs`, `dashboard-ws-auth-recovery.test.mjs`, `smoothness-state.test.mjs` | A | logout retry token rotation; dashboard WS auth recovery; store/coalesce smoothness invariants — all in `npm test` glob (`package.json:16`) and CI (`ci.yml:125`) | – |
| `scripts/verify/smoothness-browser.mjs`, `smoothness-performance.mjs` (untracked `??`) | C | **not** in any npm script or CI; need `npm run build && vite preview` + Chrome channel; write JSON to `/tmp` or `$SMOOTHNESS_OUTPUT` (`:151`, `:95`); import `'playwright'` directly | silently rot | add `verify:smoothness` script + document, or move to `docs/` as a manual procedure |
| Playwright `tests/e2e/i18n_en_no_cjk.spec.ts` | A | en-US patient pages contain no CJK (per-page loop) + zh-TW sanity | – |
| `tests/e2e/multiselect_complaint.spec.ts`, `other_complaint.spec.ts` | A | complaint multi-select, "other" sentinel merge rules (7 tests) | – |
| **Coverage gaps** | E | no automated test for: login form/`ProtectedRoute`/`RoleGuard` redirects, `LanguageLayout` URL→lng redirect & preferred-language one-shot, `ConversationPage` WS event handling (only pure helpers tested), reports list/detail & review submit, alerts list/acknowledge, notifications, all 4 admin pages, `MedicalInfoPage` (848 LOC, 0 tests), `DoctorAlertPoller`, `useInfiniteScroll` | regressions in the main doctor flows are caught only manually | add mock-mode Playwright specs for login→dashboard→reports→report detail, alerts acknowledge, admin users; node tests for `LanguageLayout`/`paths.ts` helpers |

---

## 11. Config / junk

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `frontend/.env.production` **tracked** | C | `git ls-files` lists it; keys: `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_APP_ENV=production`, `VITE_ENABLE_MOCK=false`, `VITE_MOCK_ROLE=patient`. `frontend/.gitignore` ends with `.env*` (added later) but tracked files are not affected | violates "Never commit `.env*`"; anon key is public by design, but the two Supabase vars are **dead** (`vite-env.d.ts:6` "L-24 … 死設定") and the CSP still whitelists `*.supabase.co` (`vercel.json` `connect-src`) | `git rm --cached frontend/.env.production` (owner action), move values to Vercel env; delete Supabase vars + CSP hosts |
| `frontend/.env.local` | A | untracked/ignored; holds only `VERCEL_OIDC_TOKEN` | – | – |
| `.env.example` (modified in WT), `.env.local.example` | A | templates; `.env.example` still documents `VITE_SUPABASE_*`, `VITE_SENTRY_DSN`, `VITE_VAD_*` | – | drop Supabase lines |
| `vercel.json` | A/C | SPA rewrite excludes `/assets/`; immutable cache on assets; CSP `script-src 'unsafe-inline' 'unsafe-eval'`; `connect-src` includes supabase (dead) and `*.sentry.io` (inert, §5) | `unsafe-eval` is unnecessary for a Vite prod bundle | tighten CSP; remove dead hosts |
| `nginx.conf`, `Dockerfile` | A | referenced by `../docker-compose.yml:79-82`; Dockerfile handles pnpm/yarn lockfiles that don't exist (`:10-18`) | noise only | simplify to `npm ci` |
| `frontend/DESIGN.md` (35.5 KB) | C | not referenced anywhere (`docs/README.md:51` links `docs/DESIGN.md`, a different Linear-inspired doc, 22 KB; `.claude/skills/design-taste-frontend/SKILL.md` 87 KB is the active rule set per CLAUDE.md). `diff` = 1569 lines → not a duplicate, but orphaned | two "design systems" with no pointer saying which wins | move to `docs/archive/` or link from `docs/README.md` with status |
| `tsconfig.tsbuildinfo`, `tsconfig.node.tsbuildinfo` | A | ignored by `*.tsbuildinfo`; not tracked | – | – |
| `playwright-report/`, `test-results/` | A | present locally, ignored (`/playwright-report/`, `/test-results/`), `git ls-files` = 0 | – | – |
| `vite.config.d.ts` | C | staged deletion (`D ` in status) and ignored (`../.gitignore:103`), but the file **exists on disk** — regenerated by `tsc -b` because `tsconfig.node.json` has `composite + emitDeclarationOnly` | will keep reappearing on every build | set `"declaration": false, "emitDeclarationOnly": false, "composite": false` in `tsconfig.node.json` if references aren't needed, or keep the ignore and accept |
| `frontend/graphify-out/`, `.DS_Store`, `.vercel/` | A | untracked/ignored | – | – |
| CI node version | C | `ci.yml:107` pins Node 22 while `@types/node` is `^26` and local is Node 26; `engines >=22.17` | type drift between CI and dev | pin `@types/node` to 22 or bump CI |

---

## 12. Debug code

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `console.log` / `console.debug` / `console.info` | A | **0** occurrences in `src/` (excl. tests) | – | – |
| `console.error` / `console.warn` (intentional) | A | `ConversationPage.tsx` 7 error + 3 warn; `websocket.ts` 2 error + 3 warn; `audioStream.ts` 2 warn; `useAudioStream.ts` 2 error; `sentry.ts` 1; `DashboardPage.tsx:344` 1; `useWebSocket.ts:73` 1 | – | route through the shared error helper (§6) so Sentry sees them when enabled |
| `TODO/FIXME/HACK` | A | 7 hits, all cross-references to tracked IDs: `types/websocket.ts:112,127` (TODO-E2), `ConversationPage.tsx:733,780,836`, `sentry.ts:2` (P1-#9), `admin.ts:62` (H1) | – | – |
| Commented-out code blocks > 10 lines | A | none; the 5 block comments > 10 lines (`types/websocket.ts:86-97`, `conversationStore.ts:191-204`, `websocket.ts:82-92`, `client.ts:32-42, 209-223`) are JSDoc rationale, not code | – | – |
| Dev-only globals | A | `i18n/index.ts:96-98` exposes `window.i18next` under `import.meta.env.DEV` only | – | – |

---

## Summary counts

| Category | Count | Notes |
|---|---|---|
| A (keep) | ≈75 rows | incl. 6 ts-prune false positives (`types/index.ts`), 27 backend-driven `ws` i18n keys, 15 node tests, 3 e2e specs |
| B (safe to remove) | 37 | 35 ts-prune items + `validation.ts` file + 16 i18n keys (counted as one row) + unused aliases; ≈ 400 LOC + cascading dead DTOs in `types/api.ts` |
| C (verify) | 15 | Sentry inert in build, `@eslint/js`/`playwright` implicit deps, prettier config, LanguageDetector vs URL rule, `.env.production` tracked, `vite.config.d.ts` regen, DESIGN.md orphan, CSP, CI node version, WS payload types, vite-env declarations, zh month label |
| D (duplicate) | 13 | date-key ×4, day-label ×2, month-range ×3, relative-time ×2, click-outside, refresh debounce, error handling, user menu, status maps ×6, severity ×3, validation ×3, language state ×3, uuid vs `crypto.randomUUID` |
| E (perf/arch) | 16 | logo.png 1 MB, i18n fan-out, whole-store subscriptions, chat re-render, giant effect, in-render grouping, fonts, mock consolidation, `date-fns`, component size ×4, ScriptProcessor, test gaps |

## Top 10 highest-value, lowest-risk actions

1. **Shrink `public/logo.png` (1.08 MB → SVG/≤10 KB) and add a real favicon** — `index.html:5`, `LoginPage.tsx:60`, `Sidebar.tsx:204`, `PatientLayout.tsx:38`. Largest single win on kiosk cold load; zero code risk.
2. **Delete dead API functions + their DTOs** — `admin.ts:74-99`, `dashboard.ts:17-47`, `notifications.ts:47-74`, `patients.ts:24-33`, `complaints.ts:23`; then prune `types/api.ts:42-71,170-225,286-324` and `types/index.ts:330,373,396`. Proven unused via namespace-call audit.
3. **Delete `src/utils/validation.ts`** (0 importers) and the 8 unused `date.ts`/`format.ts` helpers; collapse the password rule into one i18n helper used by `RegisterPage`/`ResetPasswordPage`.
4. **Remove the 9 unused path aliases** (`tsconfig.json:30-40`, `vite.config.ts:83-93`), incl. `@pages`/`@assets` pointing at non-existent dirs and the `@types/*` scope collision; drop the stale `"vite-env.d.ts"` include.
5. **Decide Sentry**: it is tree-shaken out of the production bundle because `VITE_SENTRY_DSN` is unset at build (`dist` has 0 sentry bytes). Either set the DSN in Vercel build env and dynamic-import the SDK in `sentry.ts:44`, or remove the dep and the CSP host.
6. **Untrack `frontend/.env.production`** (owner `git rm --cached`), drop the dead `VITE_SUPABASE_*` values and matching `vercel.json` CSP hosts; add `VITE_KIOSK_IDLE_TIMEOUT_MS`/`VITE_MOCK_ROLE` to `vite-env.d.ts`.
7. **Preload only `common` namespace and init i18n `lng` from the URL** (`i18n/index.ts:64,80-84`) — removes up to 9–29 boot JSON requests and the detector-vs-URL double load; aligns with the "URL is the only authority" rule. Consider dropping `settingsStore.language`.
8. **One `localDayKey()`/`dayLabel()`/`sessionStatusLabel()`** in `utils/` and a shared `<UserMenu />` for `Header`/`PatientLayout` — removes ~150 duplicated lines across `ReportListPage`, `AlertListPage`, `PatientListPage`, `PatientHomePage`, `PatientHistoryPage`; fixes the hard-coded `'yyyy 年 M 月'` at `PatientListPage.tsx:112` while there.
9. **Selectors instead of whole-store hooks** at the 12 sites in §9 (start with `ThemeToggle.tsx:10` and `ReportListPage.tsx:183`), and `React.memo(ChatBubble)` + pass `msg` directly at `ConversationPage.tsx:1295-1308`. Verify with React Profiler during AI streaming.
10. **Replace `uuid` with `crypto.randomUUID()`** (`websocket.ts:6`) and `date-fns` with `Intl` (3 files) — two deps and ~20 KB gone; add explicit devDeps for `@eslint/js` and import `chromium/webkit` from `@playwright/test` in the smoothness scripts (or wire those scripts into an npm script so they stop rotting).
