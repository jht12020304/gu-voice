# Flutter iOS App — Read-only Codebase Audit (2026-10-23)

Repo `gu-voice`, branch `refactor/codebase-audit-2026-10`, app `flutter_app/` (Flutter 3.41.3 via fvm). Working tree untouched (256 uncommitted files; 71 M / 2 D / 10 ?? under flutter_app).
Baseline re-verified read-only: `fvm flutter analyze --no-pub` → No issues; `fvm flutter test --no-pub` → 321 passed.
All paths below are relative to `flutter_app/` unless prefixed with `docs/`, `scripts/`, `.github/`.

Categories: **A** in use/keep · **B** safe to remove (proof given) · **C** suspect, needs verification · **D** duplicate/mergeable · **E** perf/architecture opportunity.

---

## 1. Module map

### 1a. lib/ subdirectories

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `lib/main.dart` (68) | A | Entry: `installErrorBoundary()` :19, `usePathUrlStrategyIfWeb()` :24, `ApiClient.instance.init()` :25, `Locales.loadForBoot(seed)` :34, `bootstrap()` **not awaited** :54, `runApp(UncontrolledProviderScope(App))` :56, `warmRemaining` after 2 s :65-67 | — | Keep; the three load-bearing boot invariants in README are intact |
| `lib/app.dart` (117) | A | `App` watches `authProvider.select(!booted ∥ bootOffline)` :41; `_shell` (BootGate) vs `_routed` (builds `routerProvider` only after boot) :86-87; wraps `KioskIdleGuard→DoctorAlertWatcher→DoctorPushWatcher` :101-103 | — | Keep |
| `lib/core/config/env.dart` | A | `API_BASE`/`WS_BASE`/`KIOSK_IDLE_TIMEOUT_SECONDS` dart-defines; 9 importers | — | Keep |
| `lib/core/error_boundary.dart` | A | Imported only by main.dart:8; `FlutterError.onError`/`PlatformDispatcher.onError`/`ErrorWidget.builder` | — | Keep |
| `lib/core/i18n/{loc,locales_loader}.dart` | A | `t()` dot-namespace lookup loc.dart:34; loader loads 10 ns × lng | — | Keep |
| `lib/core/router/{app_router,route_guard,lng,url_strategy*}.dart` | A | Router §1b; `url_strategy.dart` conditional import `if (dart.library.js_interop)` → `url_strategy_web.dart`, else `_noop` | — | Keep |
| `lib/core/theme/{app_theme,app_tokens}.dart` | A | `AppTheme.light/dark` static final (app_theme.dart:18-19) | — | Keep |
| `lib/data/api/*` (16 files) | A | §1d | — | Keep |
| `lib/data/models/*` (9 files) | A | §1d | — | Keep |
| `lib/features/auth/*` | A | login/register/forgot/reset pages, `auth_notifier`, `boot_gate`, `password_rules` | — | Keep |
| `lib/features/patient/*` | A | home/select_complaint/medical_info/history/settings/complete/thank_you + `kiosk_idle_guard`, `intake_payload`, `intake_route`, `patient_facing_summary`, `patient_session_tile`(new) | — | Keep |
| `lib/features/voice/{screens,state,services,models}` | A | §1e | — | Keep |
| `lib/features/doctor/{screens,state,services,research}` + `doctor_alert_watcher`, `doctor_push_watcher` | A | 17 screens, 3 controllers, dashboard_ws, push_service, push_backend (conditional) | — | Keep |
| `lib/features/admin/screens/*` (4) | A | users/complaints/health/audit-logs; each imported by app_router only | — | Keep |
| `lib/shared/{format,toast,share_bytes,pdf_download*}.dart`, `lib/shared/widgets/*` | A | `toast.dart` (new) 37 callers; `share_bytes.dart` (new) 2 importers; `pdf_download.dart` conditional → `_web`/`_noop` | — | Keep |

### 1b. Route table (`lib/core/router/app_router.dart`)

Guard: single `redirect` :67-96 → lng-prefix seeding :72-80, `setCurrentLng` :82, `if (!auth.booted) return null` :85, then pure `resolveGuardRedirect()` (route_guard.dart:60-96: unauthenticated→`/login`; `/login`→landing; `/:lng`→landing; `/patient-unsupported`→landing; patient outside own area→landing). `onException` :66 → `/`.
**Every `GoRoute` builder is wrapped in `_lngKeyed()`** (lines 113-254 — 28 builders, 0 misses). `refreshListenable` on `authProvider` :55-56; router rebuilt on `user?.id` change :54.

| Path | Page | Shell/branch | _lngKeyed |
|---|---|---|---|
| `/:lng/login` :113 | `LoginPage` | top | ✓ |
| `/:lng/register` :114 | `RegisterPage` | top | ✓ |
| `/:lng/forgot-password` :115 | `ForgotPasswordPage` | top | ✓ |
| `/:lng/reset-password?token=` :116 | `ResetPasswordPage(token)` | top | ✓ |
| `/:lng/patient` :121 | `PatientHomePage` | top | ✓ |
| `…/patient/start` :125 | `SelectComplaintPage` | nested | ✓ |
| `…/patient/medical-info` :126 | `MedicalInfoPage(args from URI)` | nested | ✓ |
| `…/patient/history` :133 / `:sessionId` :137 | `PatientHistoryPage` / `PatientSessionDetailPage` | nested | ✓ |
| `…/patient/settings` :144 | `PatientSettingsPage` | nested | ✓ |
| `…/patient/session/:id/complete` :145 | `SessionCompletePage` | nested | ✓ |
| `…/patient/session/:id/thank-you` :149 | `SessionThankYouPage(abortedRedFlag via extra)` | nested | ✓ |
| `/:lng/conversation/:sessionId` :157 | `ConversationPage(session via extra)` | **top-level, no parent (no back)** | ✓ |
| `StatefulShellRoute.indexedStack` :164 → `DoctorShell` | branch 0: `/:lng/dashboard` :170, `/patients` :172 (+`:patientId`), `/reports` :183 (+`:sessionId`→`SoapReportPage`), `/orders/:sessionId` :194, `/research` :197, `/admin/users` :198, `/admin/complaints` :200, `/admin/health` :203, `/admin/audit-logs` :204 | ✓ |
| | branch 1: `/:lng/sessions` :211 (+`:sessionId`→`SessionDetailPage`) | ✓ |
| | branch 2: `/:lng/alerts` :227 (+`:alertId`→`AlertDetailPage`) | ✓ |
| | branch 3: `/:lng/notifications` :241 | ✓ |
| | branch 4: `/:lng/settings` :247 → `DoctorSettingsPage` | ✓ |
| `/:lng` :254 | `SizedBox.shrink()` fallback (redirect always bounces) | top | ✓ |

### 1c. Providers inventory

| Provider | File:line | autoDispose | Holds | Ext. refs |
|---|---|---|---|---|
| `routerProvider` | core/router/app_router.dart:52 | no (`Provider<GoRouter>`) | GoRouter; disposed via `ref.onDispose(router.dispose)` :257 | 25 |
| `authProvider` | features/auth/auth_notifier.dart:239 | no | `AuthState` (user, booted, bootOffline, isAuthenticated) | 93 |
| `settingsProvider` | features/voice/state/settings_notifier.dart:61 | no | `VoiceSettings` (themeMode, textScale, ttsSpeed, ttsMuted) | 19 |
| `dashboardWsProvider` | features/doctor/services/dashboard_ws.dart:42 | no; `Provider<DashboardWs?>` keyed on `(user.id, role)` via select | shared doctor WS; null for patients | 28 |
| `sessionsListProvider` | features/doctor/state/sessions_list_controller.dart:99 | no | `SessionsListState` (≤50 sessions) | 13 |
| `alertsProvider` | features/doctor/state/alerts_controller.dart:302 | no | `AlertsState` (alerts, filter, unacknowledgedCount, seq) | 23 |
| `notificationsProvider` | features/doctor/state/notifications_controller.dart:241 | no | `NotifState` (list, unreadCount, error) | 26 |
| `voiceServicesProvider` | features/voice/state/conversation_controller.dart:133 | no (`const VoiceServices()` factories) | DI seam for audio/tts/ws/sessions | 2 (tests override) |
| `conversationControllerProvider` | features/voice/state/conversation_controller.dart:623 | **yes** — `NotifierProvider.autoDispose` (invariant intact) | `ConversationState` | 67 |

### 1d. Data layer

| File | One line |
|---|---|
| `data/api/dio_client.dart` (199) | `ApiClient` singleton; interceptors for Accept-Language, bearer, 401→single-flight refresh+retry, epoch-based session-change rejection :133-150; **only** place that maps `DioException` |
| `data/api/token_store.dart` (72) | `TokenStore` over flutter_secure_storage; serialised `_persist` |
| `data/api/case_convert.dart` (29) | `snakeToCamelKey`/`camelToSnakeKey` + deep converters |
| `data/api/parse_page.dart` (15, **new**) | `CursorPage<T>` record + `parsePage()` — used by patients/alerts/reports/admin/notifications APIs |
| `data/api/auth_api.dart` | login/register/logout/getMe/updateMe/changePassword/forgot/reset |
| `data/api/sessions_api.dart` (167) | create/getDoctors/get/getSessions/getSessionsPage/calendarSummary/delete/assign/updateStatus/endSessionForLanguageSwitch/getConversations/reconnectResumeToken |
| `data/api/reports_api.dart` (91) | list (with `reviewCounts`), review, getPdf, getReport, generateReport (always `regenerate:true`), `getReportBySession` (2 trips) |
| `data/api/alerts_api.dart` | list/acknowledgeAll/get/acknowledge/unacknowledgedCount |
| `data/api/notifications_api.dart` | list/markRead/markAllRead/unreadCount/registerFcmToken/removeFcmToken |
| `data/api/patients_api.dart` | list/get/delete/getSessions |
| `data/api/admin_api.dart` | getUsers/createUser/updateUser/toggleUserActive/resetUserPassword/getSystemHealth |
| `data/api/complaints_api.dart` | getComplaints/create/update/delete |
| `data/api/exam_orders_api.dart` | getLatest/submit |
| `data/api/dashboard_api.dart` | `BucketItem`, `DailyTrendItem`, `MonthlySummary`, `getMonthlySummary` |
| `data/api/research_api.dart` | `getAnalytics(dateFrom,dateTo)` |
| `data/models/session.dart` | `Session`, `Complaint`, `otherComplaintId` |
| `data/models/soap_report.dart` | `SoapReport` (+`hasSessionContext`), `PatientFacingLocalized.tryParse`, `ConversationTurn` |
| `data/models/alert.dart` | `RedFlagAlert` + `mergeAck` |
| `data/models/notification.dart` | `AppNotification` + `route()` |
| `data/models/exam_order.dart` | `ExamOrderItem.fromPlanTest`, `ExamOrder` |
| `data/models/patient.dart`, `user.dart` | `Patient`, `User` (isPatient/isAdmin) |
| `data/models/research_analytics.dart` (190) | `ResearchAnalytics` + 8 value classes; local `_d/_i/_dl` helpers |

### 1e. Voice pipeline services (`lib/features/voice/services/`)

| File | Role | Evidence |
|---|---|---|
| `audio_stream_service.dart` (418) | mic → PCM frames → ring buffer pre-roll → RMS VAD → segment WAV → base64 `onChunk`; `MuteMode {none,hard,soft}`; waveform throttled 20 Hz & silenced under hard mute :369-379 | `_onFrame` :266-278, `_processVad` :289-312, `_endSegment` :338-357 |
| `pcm_ring_buffer.dart` (47) | fixed `Int16List` ring for pre-roll | port of web |
| `wav_encoder.dart` (56) | `encodeWav(frames, rate)`, `bytesToBase64` | used by audio service :355 and `tool/voice_encode_benchmark.dart` |
| `tts_playback_controller.dart` (157) | epoch-generation cancellation, `_BytesAudioSource` (just_audio `StreamAudioSource`, `ignore_for_file: experimental_member_use` :1), `stopActive` force-completes chain | `_playStep` :66-94 |
| `ws_manager.dart` (286) | generic WS: auth handshake, ping (`Timer.periodic` :258), exponential backoff `wsRetryDelayMs` :22, resume token, permanent close codes; `_clearTimers` :261-266, `_sub?.cancel()` :269 | reused by `dashboard_ws.dart` |
| `audio_session_config.dart` (19) | `playAndRecord` + `voiceChat` via audio_session | imported by conversation_controller only |
| `state/vad_logic.dart` (73) | `shouldUnmuteVAD` decision matrix + `normalizeSupervisorGuidance` | 64-combination test in `voice_kernel_test.dart` |
| `state/conversation_controller.dart` (626) | the interlock: WS events → state + mic-lock/TTS side-effects; `_noSpeechTimer` :151 cancelled :585/:603; `_teardown` disposes tts+audio :607-608 | autoDispose provider :623 |

---

## 2. Unused files (import graph of `lib/`)

Method: parsed every `import/export/part` (incl. conditional `if (dart.library.x)` targets) across `lib/ test/ integration_test/ tool/ test_driver/` (script: scratchpad `importgraph.py`). Result: **111 lib files, every one has ≥1 importer except `lib/main.dart`** (entry).

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `lib/core/router/url_strategy_web.dart` | A | conditional target of `url_strategy.dart` (`if (dart.library.js_interop)`); imports `flutter_web_plugins` | — | Keep (web preview) |
| `lib/core/router/url_strategy_noop.dart` | A | default branch of same conditional | — | Keep |
| `lib/shared/pdf_download_web.dart` / `pdf_download_noop.dart` | A | conditional targets of `pdf_download.dart`, which is imported by `share_bytes.dart` (soap_report_page, research_analytics_page) | — | Keep |
| `lib/features/doctor/services/push_backend_firebase.dart` | A | conditional target `if (dart.library.io)` of `push_backend.dart` (imported by `doctor_push_watcher.dart`); only Firebase importer | — | Keep |
| `lib/features/doctor/services/push_backend_stub.dart` | A | default branch + `test/push_service_test.dart` | — | Keep |
| `lib/shared/pdf_share.dart`, `lib/shared/png_share.dart` (**deleted in WT**) | B | `grep -rn 'pdf_share\|png_share\|sharePdf\|sharePng' lib test integration_test tool docs/*.md` → only `docs/TODO.md:1275` mentions `sharePngBytes` (historical note) | none | Deletion is clean; optionally tidy the TODO.md wording |
| `lib/shared/share_bytes.dart` (**new, untracked**) | A | imported by `soap_report_page.dart`, `research_analytics_page.dart` | — | Commit with the WT |
| `lib/data/api/parse_page.dart` (**new**) | A | 5 API files call `parsePage` | — | Commit; see D-item sessions_api |
| `lib/shared/toast.dart` (**new**) | A | 37 `showToast` callers | — | Commit |
| `lib/features/patient/patient_session_tile.dart` (**new**) | A | imported by patient_history_page, patient_home_page | — | Commit |
| Single-importer files (`error_boundary`, `boot_gate`, all admin/auth/doctor pages, `dashboard_api`, `exam_orders_api`, `research_api`, `audio_session_config`, `doctor_push_watcher`) | A | each is reached from main/app/router | — | Keep |

**No B-class files in lib/.**

---

## 3. Unused top-level public symbols

Method: regex-enumerated public `class/enum/typedef/final/function` declarations in lib/, grepped `\bName\b` across lib/ test/ integration_test/ tool/ excluding the declaring file; manually verified every zero-external hit.

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| `wsRetryDelayMs`, `isPermanentCloseCode` (ws_manager.dart:22/36) | A | used in-file :213/:186 + `test/ws_backoff_test.dart` | — | Keep |
| `sessionLocalDay/bucketByLocalDay/monthGridDays/sessionLocalStart/End` (session_calendar_view.dart:33-82) | A | in-file + `test/session_calendar_test.dart` | — | Keep (reference impl) |
| `bytesToBase64`, `encodeWav` (wav_encoder.dart:11/56) | A | audio_stream_service.dart:355, voice_kernel_test, tool benchmark | — | Keep |
| `pcmRms` (audio_stream_service.dart:23) | A | :278 + voice_kernel_test | — | Keep |
| `medicalInfoPath` (intake_route.dart:13), `openPatientSession` (patient_session_tile.dart:14), `complaintNameBudget` (select_complaint_page.dart:20), `resolutionChain` (locales_loader.dart:29), `isSupportedLanguage` (lng.dart:69) | A | each used in its own file (:23, :40, :158, :60, :73/:92); exported only incidentally | none | Optional: make private (`_`) — cosmetic, skip |
| `DailyTrendItem` (dashboard_api.dart:12) | A | `MonthlySummary.dailyTrend` consumed by dashboard_page.dart:176-180 | — | Keep |
| `UserPage/AlertPage/PatientPage/ReportPage` typedefs | A | return types used by callers via inference | — | Keep |
| `PatientFacingSummary` (patient_facing_summary.dart:34) | A | used by session_complete_page via file import (5 in-file + test) | — | Keep |
| `VoiceServices`, `voiceServicesProvider` | A | overridden in 3 tests | — | Keep |

**Result: zero dead public symbols found.** (The analyzer's `unused_element` already covers private ones; analyze is clean.)

---

## 4. Dependencies (pubspec.yaml)

| Package | Category | Importers (lib / test / tool) | Risk | Recommendation |
|---|---|---|---|---|
| `dio ^5.10` | A | lib: auth_api, dio_client, reports_api, auth_notifier; test: 4 | — | Keep |
| `go_router ^17.3` | A | 27 lib files; 2 test; 3 integration | — | Keep |
| `flutter_riverpod ^3.3` | A | 31 lib / 15 test / 10 integration | — | Keep |
| `flutter_secure_storage ^10.3` | A | token_store.dart; 2 tests | — | Keep |
| `google_fonts ^8.2` | A/E | only `core/theme/app_theme.dart:35` (`GoogleFonts.interTextTheme`) — **runtime network fetch**, no bundled font (pubspec has no `fonts:`) | medium (kiosk LAN/firewall; first-paint reflow) | See §7-E6 — decision item from perf audit §4d still open |
| `intl: any` | A/C | lib: `shared/format.dart` only (resolved 0.20.2 via flutter_localizations) | low | Pin `intl: ^0.20.2` instead of `any` (pub resolution is driven by flutter_localizations anyway) |
| `flutter_localizations` | A | app.dart:2 delegates | — | Keep |
| `flutter_web_plugins` (sdk) | A | `url_strategy_web.dart` only (web preview) | — | Keep while web preview is retained |
| `record ^6.2` | A | audio_stream_service.dart (+2 tests) | — | Keep |
| `just_audio ^0.10` | A | tts_playback_controller.dart (+3 tests) | — | Keep |
| `audio_session ^0.2` | A | audio_session_config.dart | — | Keep |
| `permission_handler ^12` | **C** | **0 Dart importers** in lib/test/integration/tool (`grep -rn 'permission_handler\|Permission\.'` → none). Pod `permission_handler_apple 9.4.8` present in `ios/Podfile.lock:77/93/147`; Podfile has no `PERMISSION_*` macros. Mic permission is handled by `record` (`RecordMicRecorder.hasPermission` audio_stream_service.dart:116) | medium: removal changes `Podfile.lock` (pod drop) and the TestFlight pipeline treats Podfile.lock drift as a signal | Verify on a scratch checkout: remove dep → `fvm flutter pub get` → `pod install` → confirm only `permission_handler_apple` lines leave Podfile.lock and `fvm flutter test` still 321. Then remove in a dedicated commit |
| `path_provider ^2.1` | **C→B-leaning** | 0 Dart importers; **no pod in Podfile.lock** (`grep path_provider ios/Podfile.lock` → absent); still resolved transitively via `google_fonts` and `just_audio` (`fvm dart pub deps`) | low: removing the direct entry changes only pubspec.lock's `dependency:` tag, not the graph | Remove direct entry |
| `cupertino_icons ^1.0` | **C→B-leaning** | 0 Dart uses (`CupertinoIcons` never referenced); font-only package from template | none | Remove (pubspec.lock only) |
| `web_socket_channel ^3` | A | ws_manager.dart | — | Keep |
| `uuid ^4` | A | ws_manager.dart, conversation_controller.dart | — | Keep |
| `share_plus ^13` | A | shared/share_bytes.dart | — | Keep |
| `fl_chart ^1.2` | A | research/charts.dart, research_analytics_page.dart | — | Keep |
| `web ^1.1` | A | shared/pdf_download_web.dart (js_interop branch only) | — | Keep while web preview retained |
| `firebase_core ^4`, `firebase_messaging ^16` | A | only `push_backend_firebase.dart` behind `dart.library.io` conditional; pubspec comment :77 references `isDoctorOnlyPlatform`, **which no longer exists in lib** (stale comment) | low | Keep; fix the pubspec comment to say `shouldEnablePush`/native-only |
| dev `flutter_test`, `integration_test`, `flutter_lints ^6` | A | 34 test files / 10 integration + test_driver / analysis_options include | — | Keep |

---

## 5. Duplicate logic (D)

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Request-sequencing/stale-response guard hand-rolled in 3 controllers | D | `alerts_controller.dart:70,109,112,122,133,136,145` (`_listRequest` + `if (!lifecycle.mounted ∥ ws.isDisposed ∥ request != _listRequest) return` ×6), `notifications_controller.dart:79-80,118-152,196-199` (same, ×6 + `_countRequest`), `sessions_list_controller.dart:34,77,82,85` (`_request`); plus the identical `ws.on/off` registration loops (alerts :88/:92, notifications :92/:98, sessions :50-57) and debounce `Timer` (notifications :226-228, sessions :67-70) | low-medium (future drift between the three; CLAUDE.md F05 fix must stay consistent) | Extract a small mixin/helper e.g. `WsRefreshingNotifier` { `nextRequest()`, `isStale(req)`, `scheduleRefresh()` } in `features/doctor/state/`; keep `smoothness_regression_test` + `notifications_ws_refresh_test` as the guard |
| Same guard in pages (StatefulWidget) | D | `++_request` in `patient_list_page.dart:66,78`, `report_list_page.dart`, `dashboard_page.dart`, `session_calendar_view.dart:235,247,269` | low | Same helper or a tiny `RequestSeq` value class |
| Infinite-scroll listener | D | identical `_scroll.addListener(() { if (pixels >= maxScrollExtent - 300) _fetchMore(); })` in notification_page:29, alert_list_page:31, patient_list_page:44, report_list_page:51, user_management_page:45, audit_logs_page:38 | low | `ScrollController` extension `onNearEnd(void Function())` in `shared/` (one line each) |
| Initial fetch kick-off | D | `Future.microtask(() => _fetch(reset: true))` in audit_logs_page, user_management_page, patient_list_page, report_list_page | none | Fold into the same helper or leave |
| Pagination parsing | D | `sessions_api.dart:100-106` still parses `data/pagination/nextCursor/hasMore` by hand into `SessionsPage` while 5 other APIs use `parsePage` (`parse_page.dart:5`) | low | Replace `getSessionsPage` body with `parsePage(res.data, Session.fromJson)`; `SessionsPage` → `CursorPage<Session>` |
| Local-day bucketing — two implementations | D | `session_calendar_view.dart:33-57` (`sessionLocalDay` → `DateTime` key, `bucketByLocalDay`) vs `shared/format.dart:33` (`localDayKey` → `yyyy-MM-dd` string) used by `alert_list_page.dart:54` | low (both are local-day; different key types) | Make `localDayKey` call `isoDate(sessionLocalDay-like)`; or expose `localDay(String iso) → DateTime?` in format.dart and have calendar use it. **Note:** CLAUDE.md §U15 claim ("patient_list/alert_list/audit_logs still use old pattern") is **partly stale**: alert_list uses `localDayKey` (local), patient_list sends `toUtc().toIso8601String()` (patient_list_page.dart:61 — same form as the calendar's `calendarSummary` sessions_api.dart:112), audit_logs_page has **no date bucketing/filtering at all** (only `formatDateTime` :208). Update CLAUDE.md |
| Grouped flat list `<Object>[GroupHeader, ...rows, spinner]` | D | `alert_list_page.dart:166-176` and `patient_list_page.dart:180-199` byte-for-byte same shape (header + rows + trailing spinner, `item is Widget ? item : _row(...)`) | low | `GroupedListView<T>` in ui_kit (keeps `ListView.builder`) |
| Horizontal `ChoiceChip` filter strip | D | `alert_list_page.dart:133-149`, `report_list_page.dart:306-323`, `session_list_page.dart:89-104`, `user_management_page.dart:258-288` (`roleChip`/`activeChip` local fns) | low | `FilterChipBar(Map<String,String> options, selected, onSelected)` in ui_kit |
| Chat bubble container | D | `conversation_page.dart:406-409`, `session_detail_page.dart:377-380`, `soap_report_page.dart:302-305` — same `margin 4 / padding 14×10 / maxWidth % / BorderRadius 16` | low | `ChatBubble` widget in `shared/widgets/` (voice page keeps its own role colours) |
| JSON parse helpers | D | `research_analytics.dart:3-5` (`_d/_i/_dl`), `:146` `m(dynamic)`; `soap_report_page.dart:118-125` (`_map/_s/_strOnly/_arr`); `soap_report.dart:66` `_str`; `alert.dart:54` `strList`; `exam_order.dart:24` `nonEmpty` | very low | Optional `data/models/json_read.dart` (`asMap/asStr/asStrList/asDouble`) — only if touched anyway |
| Toast/snackbar | A (mostly done) | `shared/toast.dart` now has 37 callers; remaining direct `ScaffoldMessenger`: `doctor_alert_watcher.dart:51-56` (needs action button + `hideCurrentSnackBar` — legit), `language_action.dart:31,70,82` (uses `maybeOf` captured before await — legit), `user_management_page.dart:188` (plain toast inside dialog `ctx`) | none | Swap user_management:188 to `showToast(ctx, …)`; leave the other two |
| API error mapping | A | `DioException` handled only in `dio_client.dart:92-130,164-195` and `auth_notifier.dart:173-174,227`; no per-API duplicates | — | Nothing to do |
| ui_kit adoption | A | PillTag 16 files, EmptyState 16, SkeletonList 20, ErrorState 13, GroupHeader 12, StatCell 5, MonthStatsCard 3; no private `_Pill/_Empty/_Skeleton/_Stat` classes left in features (`grep '^class _(Pill|Tag|Chip|Empty|Skeleton|Stat…)'` → 0) | — | Good; `SkeletonList` still `shrinkWrap: true` (ui_kit.dart:278 region) |

---

## 6. Size / complexity hot spots (E)

Top 15 lib files by LOC: `patient/medical_info_page.dart` 826 · `doctor/screens/soap_report_page.dart` 751 · `doctor/screens/session_calendar_view.dart` 727 · `voice/state/conversation_controller.dart` 626 · `voice/screens/conversation_page.dart` 609 · `doctor/screens/research_analytics_page.dart` 544 · `admin/screens/user_management_page.dart` 511 · `auth/login_page.dart` 452 · `shared/widgets/ui_kit.dart` 430 · `doctor/screens/report_list_page.dart` 423 · `voice/services/audio_stream_service.dart` 418 · `doctor/screens/session_detail_page.dart` 389 · `patient/patient_settings_page.dart` 361 · `admin/screens/complaint_management_page.dart` 354 · `doctor/screens/quick_orders_page.dart` 345. (lib total 18 113 LOC / 111 files.)

| Item | Category | Evidence (longest functions: name, lines, length, max indent) | Risk | Recommendation |
|---|---|---|---|---|
| `medical_info_page.dart` | E | `build` 275-453 (**179 lines**, indent depth 16); `_submit` 204-274 (71); sections already split (`_allergySection` :481, `_medicationSection` :556, `_familySection` :617, `_historySection` :710) but `build` inlines the patient-info card + doctor picker | medium (readability; one `setState` rebuilds all sections) | Lift the patient-info/doctor card into `_patientSection`; consider per-section `StatefulWidget`s so a chip tap rebuilds one card |
| `login_page.dart` | E | `build` 134-385 (**252 lines**, indent depth **25**) | medium | Split hero / form / test-login-buttons into 3 private widgets |
| `session_calendar_view.dart` | E | `_dayPanel` 529-640 (112, depth 14), `_dayCell` 442-528 (87, depth 17), `_sessionRow` 641-726 (86, depth 15) | low-medium | Extract `_DayCell`, `_SessionRow` as `const`-able StatelessWidgets (also helps month-grid rebuilds, 42 cells) |
| `soap_report_page.dart` | E | `_plan` 566-651 (86), `build` 201-265 (65), `_objective` 472-527 (56, depth 12) | low | Fine as sections; consider moving `_map/_s/_arr` to models (§5) |
| `conversation_page.dart` | E | `_redFlagBanner` 232-314 (83), `build` 47-124 (78), `_transcript` 380-457 (78), `_supervisorBanner` 128-198 (71) | low | Banners → `const` widgets taking only the fields they read |
| `research_analytics_page.dart` | E | `build` 88-159 (72), `_figure` 186-238 (53, depth 13) | low | — |
| `user_management_page.dart` | E | `build` 445-510 (66), `_row` 320-372 (53) | low | — |
| `report_list_page.dart` | E | `_row` 341-420 (80, depth 12) | low | — |
| Widgets > 500 lines | E | 7 files listed above (medical_info, soap_report, session_calendar_view, conversation_controller, conversation_page, research_analytics, user_management) | — | Only medical_info/login builds are structurally problematic |

---

## 7. Performance review (E)

Mapping to `docs/perf_audit_2026-08-22.md` (2026-10-03 section): F01 (StatefulShellRoute) ✔ app_router.dart:164; F02/F09/F11 ✔; F05 (coalesce+seq) ✔ sessions_list_controller.dart:65-71; F08 (status subtree) ✔ conversation_page.dart:51-60 `select`; F12 (builder lists) ✔ alert/patient/report/notification/user/complaint/audit all `ListView.builder`; format.dart DateFormat hoist ✔ (:3-6); sessions debounce ✔. **Still open from §4c/4d:** reports two-trip, WAV-at-end, Firebase post-frame, google_fonts, LaunchScreen white.

| Item | Category | Evidence | Why / measure | Recommendation |
|---|---|---|---|---|
| E1 Whole-state `ref.watch` in list pages | E | `notification_page.dart:65 ref.watch(notificationsProvider)`, `alert_list_page.dart:75 ref.watch(alertsProvider)`, `session_list_page.dart:43 ref.watch(sessionsListProvider)`; `conversation_page.dart:118` `Consumer` watching **whole** `conversationControllerProvider` for the status bar | Each WS-driven refresh rebuilds the full page incl. filter strip and app bar; measure with DevTools "Track widget rebuilds" while firing 3 dashboard events | Status bar: `select((s) => (s.waveform, s.recordingDuration, s.status…))`; list pages: watch `(isLoading, error, items.length/identity)` tuples or split body into a `Consumer` |
| E2 `ListView(children:)` for the sessions list | E | `session_list_page.dart:124-127` builds all `_card`s (≤50, bounded by `getSessions(limit: 50)` sessions_list_controller.dart:81) | bounded, so low; measure scroll jank with `flutter run --profile` on the slowest iPhone | Switch to `ListView.builder` for parity with the other 7 lists (3 lines) |
| E3 Per-frame `Int16List` copy loop | E | `audio_stream_service.dart:266-273` — manual `getInt16` loop per mic buffer (~47/s on iOS) | ~1024 samples × 47/s; negligible on A-series but free win | `Int16List.view(bytes.buffer, bytes.offsetInBytes, n)` when `(offsetInBytes & 1)==0`, then copy once via `Int16List.fromList` (still owned); keep RMS/waveform as is |
| E4 WAV encode + base64 on main isolate at segment end | E (open 4c) | `audio_stream_service.dart:355` `bytesToBase64(encodeWav(frames,…))`; 60 s cap (:295) ⇒ ≤1.9 MB PCM ⇒ ~2.6 MB base64 string; benchmark `tool/voice_encode_benchmark.dart` p95 ≈ 4.4/9.4/11.9 ms @10/30/60 s on Mac AOT | perf audit 2026-10-03 decided *not* to add an isolate yet; iPhone cost unmeasured | Measure once on device (`Timeline.startSync('wav')` around :355, view in DevTools); if >8 ms, `Isolate.run` or stream chunks |
| E5 `getReportBySession` two round-trips × polling | E (open 4c) | `reports_api.dart:83-91` (list limit 1 → getReport); `session_complete_page.dart:62-74` polls every 3 s up to `_maxAttempts` | Up to 2×N requests while patient waits; count in Charles/proxy or Dio `LogInterceptor` | Backend `GET /sessions/{id}/report` or have list endpoint return full report; client then 1 trip/poll |
| E6 google_fonts runtime fetch | E (open 4d) | `app_theme.dart:35` `GoogleFonts.interTextTheme`; pubspec has no `fonts:`; CSP in `tool/prepare_vercel_output.dart` whitelists fonts.gstatic.com | First launch on restricted clinic Wi-Fi → fallback font + reflow; measure first-frame font swap via DevTools timeline / `GoogleFonts.config.allowRuntimeFetching=false` test | Decision item: bundle Inter 400/500/600/700 (~1.3 MB) for iOS; keep runtime fetch only for web preview, or drop Inter (CJK text is system font anyway) |
| E7 Firebase init + permission prompt in first post-frame | E (open 4c, low) | `doctor_push_watcher.dart:40-42` → `PushService.start` → `Firebase.initializeApp` (push_backend_firebase) | Competes with the doctor's first tap; measure with DevTools "App startup" + `Timeline` | Delay by `Future.delayed(1–2 s)` after first frame (same pattern as `warmRemaining` main.dart:66) |
| E8 LaunchScreen hard-coded white | E (open 4d) | `ios/Runner/Base.lproj/LaunchScreen.storyboard:22` `red=1 green=1 blue=1` | dark-mode flash on cold start | Add dark appearance variant (not a Flutter change) |
| E9 Timers / subscriptions | A | Every `Timer?`/`StreamSubscription` field has a matching `cancel()` + dispose hook: boot_gate, kiosk_idle_guard, session_complete (`_pollTimer` :33/:46), session_thank_you, patient_list, audit_logs, user_management, research_analytics, notifications/sessions controllers (`ref.onDispose`), ws_manager `_clearTimers` :261-266 + `_sub?.cancel()` :269, tts `sub?.cancel()` :91, audio service (4 cancels), conversation_controller `_teardown` :603-608; `ScrollController.addListener` sites all `dispose()` the controller | — | No leaks found |
| E10 Dashboard WS reconnect/backoff | A | `dashboard_ws.dart:14-16` reuses `WebSocketManager` (backoff `wsRetryDelayMs`, ping `Timer.periodic`, 4003 permanent); one socket per `(user.id, role)` via provider :42-48 | — | OK |
| E11 Polling timers | A | `doctor_alert_watcher.dart` is WS-driven (no `Timer`); only polling is `session_complete_page` (E5) | — | — |
| E12 Heavy work in build | A (mostly) | `AppTheme.light/dark` static (app_theme.dart:18-19); `_grouped()` sort+bucket runs every build in `alert_list_page.dart:50-66` and `patient_list_page` (unmemoised, O(n log n) on ≤ page size) | low | Memoise groups in state when list identity unchanged |
| E13 N+1 API calls | A (fallback only) | `report_list_page.dart:146-165` `_loadMeta` fetches `getSession` **only** for rows lacking `hasSessionContext` (old backend), in parallel via `Future.wait`; summary = 4 parallel `limit:1` calls only when `reviewCounts` absent (:90,:116-119) | — | Keep; remove fallback once backend ≥ F02 is the only deployed one |
| E14 `prefer_const_constructors` not enabled | E | `analysis_options.yaml` has only `flutter_lints` defaults (rule not in that set) | unknown count of missed `const` | Enable `prefer_const_constructors`, `prefer_const_literals_to_create_immutables` in a dedicated PR (expect many info-level hits; CI fails on info) |

---

## 8. Tests

### 8a. `test/` (34 files, 321 tests, CI runs all + `session_calendar_test` again under `TZ=America/New_York`)

| File | Covers |
|---|---|
| api_auth_recovery_test (7, **new**) | refresh 401/403 clears session; 503/timeout keeps login |
| boot_gate_test (4) | no router before boot; bootOffline retry |
| boot_locale_load_test (9) | `loadForBoot` loads only fallback chain |
| branding_test (3) | mascot asset registered, app title |
| case_convert_test (3) | snake↔camel |
| conversation_page_ux_test (4) | narrow phone layout, speed numeric, waveform doesn't rebuild text (F08) |
| doctor_alert_watcher_test (1, **new**) | red-flag toast "view" navigates to /alerts above router |
| doctor_session_lifecycle_test (3, **new**) | account switch tears down controllers/ws |
| intake_payload_test (12) | IN-1 no_* tri-state |
| intake_route_test (17) | intake params survive reload/deep link |
| kiosk_idle_guard_test (5) | timer arming rules |
| language_switch_guard_test (12) | conversation session id in path; mid-consult switch |
| medical_info_family_test (5) | family-history rows |
| mic_degradation_test (9) | openMic pre-checks, noInputDevice |
| notifications_ws_refresh_test (13) | ordering/stale guards, debounce |
| patient_facing_summary_test (25) | `PatientFacingLocalized.tryParse` + widget |
| push_service_test (28) | gating, token register/unregister, foreground banner |
| quick_orders_test (11) | push landing, order submit |
| red_flag_banner_wording_test (9) | L2/L3 doctor fields never on patient side (reads locale JSON) |
| report_session_context_test (5) | `hasSessionContext` |
| research_stats_test (4) | Wilson CI |
| resume_failed_recovery_test (5) | REST refetch on resume_failed |
| role_guard_test (16) | `resolveGuardRedirect`, `/patients` hole |
| session_calendar_test (21) + session_calendar_widget_test (6) | bucketing, DST, grid |
| session_delete_admin_only_test (4) | delete gated by isAdmin (source-grep style) |
| settings_text_scale_test (1) | 100–140 % clamp |
| smoothness_regression_test (6, **new**) | retained tabs, request budget, event coalescing |
| soap_regenerate_gate_test (15) | generate/regenerate gates |
| status_badge_i18n_test (2) | 5 langs × statuses |
| tts_playback_controller_test (6) | epoch cancellation |
| vercel_output_config_test (3) | `tool/prepare_vercel_output.dart` config |
| voice_kernel_test (22) | VAD matrix 64 combos, ring buffer, WAV, RMS |
| ws_backoff_test (10) | backoff sequence, permanent codes |
| support/api_stub.dart | Dio stub adapter |

### 8b. `integration_test/` (10) and `test_driver/`

| File | Category | Referenced by | Notes |
|---|---|---|---|
| patient_text_flow_test (247) | A | README, docs/TODO.md §V2, `voice-pipeline-invariants` skill | canonical E2E |
| login_smoke_test (108) | A | README | |
| kiosk_idle_logout_test (97) | A | README, TODO.md:1223 | |
| demo_walkthrough_test (909) | A | README, `tool/record_demo.sh` | not a test; video driver |
| patient_language_switch_test (240) | A | TODO.md:1317 | |
| ios_doctor_app_test (292) | **C** | README | Tests A/B/C are current (B asserts `/patient` :205-230), but header comments :5,:14 still describe the deleted `/patient-unsupported` flow → stale doc |
| mobile_layout_walkthrough_test (146) | **C** | README | SHOTS screenshot path uses `test_driver` `onScreenshot`; README no longer has the "web chapter" the driver comment points to |
| doctor_walkthrough_test (492) | **C** | **nothing** (no doc/skill/tool reference) | verify it still passes against current backend seed; otherwise fold into demo_walkthrough |
| doctor_dashboard_ws_test (161) | **C** | **nothing** | same |
| lng_deep_link_test (128) | **C** | **nothing** (CLAUDE.md says 5-lang deep links were verified 2026-08-17 on web) | keep if still run manually; document in README |
| test_driver/integration_test.dart (22) | A/C | nothing in docs (`grep 'flutter drive\|test_driver' README.md` → none) | needed for `flutter drive`/SHOTS; its comment "用法見 README 的 web 章節" is stale |

### 8c. Coverage gaps (unit/widget level)

| Flow | Status | Evidence |
|---|---|---|
| Login | partial — auth recovery + guard; no `LoginPage` widget test (252-line build) | only integration login_smoke |
| Complaint select | **gap** — `select_complaint_page.dart` (288) has no unit/widget test (`complaintNameBudget`, `clampCp`, custom text required) | |
| Intake | good — intake_payload/intake_route/medical_info_family | |
| Conversation voice/text | good on kernel (VAD, TTS, WS, resume, mic degradation, UX); **no test for `_redFlagBanner`/`_supervisorBanner` rendering** beyond wording | |
| Session complete / thank-you | partial — patient_facing_summary; no polling test for `session_complete_page` | |
| Doctor dashboard | **gap** — `dashboard_page.dart` only via smoothness (tab retention); no monthly-summary rendering test | |
| Sessions / alerts / reports / notifications | good (controllers + smoothness + quick_orders) | |
| Admin pages (users/complaints/health/audit) | **gap** — zero unit/widget tests; only mobile_layout_walkthrough (integration) | |
| Language switch | good (language_switch_guard, status_badge_i18n, boot_locale) | |
| Kiosk idle logout | good (unit) + integration | |
| Push | good (28) | |

---

## 9. `tool/` scripts

| File | What | Referenced by | Category |
|---|---|---|---|
| `build_ios_testflight.sh` (845) | 6-gate TestFlight build (sources `env.production.sh`) | docs/deployment_guide, docs/ios_release_settings, docs/TODO, CLAUDE.md, README, `.claude/skills/ios-testflight/SKILL.md`, build_vercel_output.sh | A |
| `build_vercel_output.sh` (61) | analyze+test+web build → Vercel output; runs `dart run tool/prepare_vercel_output.dart` :56 | docs/flutter_web_cutover, ios_release_settings, README, CLAUDE.md, TODO | A |
| `prepare_vercel_output.dart` (64) | writes Vercel `config.json` (CSP, headers) | build_vercel_output.sh:56, `test/vercel_output_config_test.dart`, perf_audit | A |
| `gen_app_icons.py` (204) | App icon set generation/`--check` | deployment_guide, ios_release_settings, README, ios-testflight skill, build_ios_testflight.sh | A |
| `record_demo.sh` (229) | sim reboot → record → run demo_walkthrough → cut | README, docs/README.md, make_demo_video.sh | A |
| `make_demo_video.sh` (397) | ffmpeg post (Pillow captions) | README, record_demo.sh, demo_captions.py | A |
| `demo_captions.py` (278), `demo_captions.example.json` | caption PNGs / timeline | README, make_demo_video.sh, record_demo.sh | A |
| `env.production.sh` (6, **untracked, new**) | `PROD_API_BASE`/`PROD_WS_BASE` only (2 vars: an `https://…/api/v1` and a `wss://…/api/v1/ws` URL, 69 chars each). **No secret-shaped values** (no keys/tokens/passwords; the two "pattern hits" are the word *railway* in the hostnames, which is already public in CLAUDE.md). `git check-ignore` → **NOT ignored** (`.env*` glob only matches basenames starting with `.env`); it is `source`d by `build_ios_testflight.sh:45` and `build_vercel_output.sh:7` and documented in `docs/ios_release_settings.md:49` | both build scripts, ios_release_settings | **A — must be committed**, otherwise both build scripts fail on a fresh clone |
| `voice_encode_benchmark.dart` (31, **untracked, new**) | AOT host benchmark of `encodeWav`+base64 (10/30/60 s) | **only its own header** (`fvm dart compile exe …`); the perf audit's "WAV 編碼保留既有實作… P95 4.4/9.4/11.9ms" numbers come from it but the doc does not name the file | **C** → keep and reference it from `docs/perf_audit_2026-08-22.md` (one line), or drop it. Note it imports `package:gu_voice/...` so it must stay under flutter_app |

---

## 10. Platform dirs

| Item | Category | Evidence | Recommendation |
|---|---|---|---|
| `ios/Podfile` (M) | A | diff: uncomment `platform :ios, '15.0'`; `post_install` forces `IPHONEOS_DEPLOYMENT_TARGET ≥ 15.0` on pods (Xcode 27 rejects old pod targets — matches perf_audit 2026-10-03 "CocoaPods 最低版本對齊 Runner 原有的 iOS 15") | Commit with WT; does not raise app min version |
| `ios/Podfile.lock` (M) | A | only `PODFILE CHECKSUM` line changed (3ba3a7→94386d); pod set/versions unchanged | Expected consequence of the Podfile edit |
| `ios/Runner/Runner.entitlements` | A | not modified (`git status` clean) — aps-environment invariant intact | — |
| `ios/` others (ExportOptions.plist, Runner.xcodeproj, RunnerTests, Pods/) | A | unchanged | — |
| `android/` | C (by decision) | present, unchanged; docs say never exercised; release signing intentionally fails without keystore | Leave; not in maintenance scope |
| `web/` (`index.html`, `flutter_bootstrap.js`, `manifest.json`, `icons/`) | A (preview) | kept by decision (CLAUDE.md); boot mask in index.html per perf audit | Leave |
| `.flutter-plugins-dependencies` | — | ignored (`.gitignore:30`), untracked | — |
| `build/` 2.6 GB, `.dart_tool/` 2.8 GB | — | ignored (`.gitignore:33/:29`) | `fvm flutter clean` when disk matters (then `pod install` zero-diff per README) |

---

## 11. i18n

`python3 scripts/check_translations.py --locales-dir flutter_app/assets/locales` → **Result: OK** (en-US 100 % 1211/1211 across 10 namespaces; ja/ko/vi beta 100 % on `common.json` 252/252).

Key convention: `t('ns.path…')` (first dot segment = namespace, `loc.dart:5-6`). Scan (scratchpad `i18n_diff2.py`): 1211 zh-TW leaf keys; 729 distinct literal keys in lib (incl. keys stored in maps such as `status_badge.dart:14-18`); **24 dynamic prefixes** detected and excluded: `common.doctor.dashboard.`, `common.gender.`, `common.language.names.`, `common.patient.home.`, `conversation.supervisor.hpi.`, `intake.medicalInfo.{commonAllergies,commonConditions,frequency,relations,yearsAgo}.`, `intake.medicalInfo.patient.gender*`, `research.hpi.fields.`, `research.safety.{layer,severity,urgency}.`, `session.complete.`, `session.doctor.calendar.weekday.`, `soap.{assessment.probability,fieldLabels,objective.vitalSigns.labels,objective.vitalSigns.units,plan.urgency,subjective.hpi}.`, `ws.`.

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Keys used in lib but missing in zh-TW | A | **0** | — | — |
| zh-TW keys with no lib reference (outside dynamic prefixes) | C | **305 / 1211** — admin 33, auth 11, common 70, conversation 18, dashboard 56, intake 38, research 17, session 13, soap 49. Spot-verified truly unreferenced: `common.status.*` (6), `common.severity.*` (3), `common.patientUnsupported.*` (4 — page deleted 2026-08-22), `dashboard.transcript.*` (18), `soap.metaCard.*` (12), `soap.highlights.*` (8), `intake.medicalInfo.summary.*` (8), `session.patientHistory.status.*` (5), `dashboard.alertList.sessionStatus.*` (5), `admin.*.col*` table headers (14) | low (dead weight ~25 % of strings ×5 langs; some are React-only leftovers) | Prune in one PR across all 5 locale dirs (checker requires parity), namespace by namespace; keep anything referenced by a dynamic prefix. `common.patientUnsupported.*` is the safest first cut (route gone, `route_guard.dart:82` only redirects) |
| `t()` fallback renders raw key | A | loc.dart:41 | — | Already the "visible gap" design |

---

## 12. Debug code

| Item | Category | Evidence | Risk | Recommendation |
|---|---|---|---|---|
| Bare `print(` in lib | A | **0** | — | — |
| `debugPrint` in lib (14 lines) | A (intentional) | `push_service.dart` ×9 (:125-217, all `[push]`-prefixed error paths), `core/error_boundary.dart:44-45` (the error sink), `main.dart:41` (`[gu-voice:boot]`), `auth_notifier.dart:113` (`[auto-login]`), `ws_manager.dart:164` (`ws handler error`) | none (debugPrint is a no-op-ish in release) | Keep; optionally route push_service's 9 through one `_log(String)` |
| `// ignore:` suppressions | A | 5 total: `avoid_print` ×4 — all in `integration_test/ios_doctor_app_test.dart:257,265,275` and `doctor_dashboard_ws_test.dart:136`; `ignore_for_file: experimental_member_use` ×1 in `tts_playback_controller.dart:1` (just_audio `StreamAudioSource`) | none | Keep |
| `TODO/FIXME/HACK/XXX` | A | 32 lines contain "TODO" but **27 are references to `docs/TODO.md` items** (`TODO G5`, `TODO §V7`…); real markers: `conversation_controller.dart:383` `TODO(voice): speak … aborted_red_flag once (flutter_tts)` + 4 `(TODO G-medium)` notes (:474,:489,:520; conversation_page.dart:462). 0 FIXME/HACK/XXX | none | Fine |
| Commented-out code blocks > 10 lines | A | scan of consecutive `//` (non-`///`) runs with ≥50 % code-like lines → **0** | — | — |
| Stale comments | C | `pubspec.yaml:77` mentions `isDoctorOnlyPlatform` (symbol removed); `integration_test/ios_doctor_app_test.dart:5,14` describe `/patient-unsupported`; `test_driver/integration_test.dart:10` points to a README "web chapter" that no longer exists | low | Fix wording in the same housekeeping PR |

---

## Summary counts

| Category | Count (distinct findings) | Highlights |
|---|---|---|
| A (confirmed in use) | ~95 rows | all 111 lib files reachable; all routes `_lngKeyed`; conversation provider autoDispose; timers/subs all cancelled |
| B (safe to remove) | 3 | deleted `pdf_share/png_share` confirmed reference-free; `path_provider` & `cupertino_icons` direct deps (no Dart use, no pod impact) |
| C (verify) | 12 | `permission_handler` (pod drop), `voice_encode_benchmark.dart` (unreferenced), 3 unreferenced integration tests, `ios_doctor_app_test`/`test_driver` stale comments, 305 unreferenced locale keys, `intl: any`, android/, pubspec stale comment, CLAUDE.md §U15 wording |
| D (duplicate/mergeable) | 10 | request-seq guards ×3 controllers (+4 pages), scroll listener ×6, chip filter strip ×4, grouped list ×2, chat bubble ×3, sessions_api page parsing, two local-day impls, JSON helpers ×5, microtask kick-off ×4, 1 leftover SnackBar |
| E (perf/arch) | 14 | whole-state watches (4 sites), session_list `ListView(children)`, per-frame PCM copy, WAV-on-main-isolate (measure), report 2-trip polling, google_fonts runtime, Firebase post-frame, LaunchScreen white, `prefer_const_constructors` off, medical_info/login giant builds, calendar cell nesting |

## Top 10 highest-value, lowest-risk actions

1. **Commit `tool/env.production.sh`** (A, not ignored, no secrets) — both build scripts `source` it; a fresh clone currently cannot build.
2. **Remove `path_provider` and `cupertino_icons` from pubspec** (B) — zero Dart use, no Podfile.lock change (path_provider stays transitive via google_fonts/just_audio). Verify `permission_handler` separately on a scratch checkout (pod drop → Podfile.lock diff) before removing it.
3. **`sessions_api.getSessionsPage` → `parsePage`** (D) — 8 lines deleted, matches the 5 sibling APIs; covered by `smoothness_regression_test`.
4. **Extract the WS-refresh/stale-guard helper** used by alerts/notifications/sessions controllers (D) — removes ~12 copies of the same 3-clause guard; existing `notifications_ws_refresh_test` + `smoothness_regression_test` pin behaviour.
5. **`ScrollController.onNearEnd` extension + `FilterChipBar` + `GroupedListView` in ui_kit** (D) — six list pages shrink; no behaviour change.
6. **`select` for the conversation status bar** (`conversation_page.dart:118`) and the three list pages (E1) — measurable with DevTools rebuild counts; small diff.
7. **Prune `common.patientUnsupported.*` then the other 300 unreferenced locale keys** across 5 locale dirs (C→B after a second grep per namespace) — run `check_translations.py` after each namespace.
8. **Decide google_fonts** (E6): bundle Inter for iOS or drop it; kiosk LAN risk is the argument, 1.3 MB the cost.
9. **Enable `prefer_const_constructors` / `prefer_const_literals_to_create_immutables`** in analysis_options in a dedicated PR (E14) — CI already fails on info, so land the fixes with the rule.
10. **Housekeeping comments**: pubspec.yaml:77 (`isDoctorOnlyPlatform`), ios_doctor_app_test header, test_driver README pointer, CLAUDE.md §U15 (alert_list already local-day; audit_logs has no date filter), and either reference or delete `tool/voice_encode_benchmark.dart`.
