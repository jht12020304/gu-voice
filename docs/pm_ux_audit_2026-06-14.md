# gu-voice 產品可用性審查（PM 視角：逐頁逐按鈕 + 流程正確性）

> 7 個 journey agent 審查 27 頁、清點每一個互動元件並追 handler→store/api→後端 endpoint；critical/broken 發現已人工複核。日期 2026-06-14。

## 總判定：`notable-gaps` — UX 就緒度 **71%**

gu-voice is structurally sound but NOT launch-ready, because the single most important path — a patient starting an intake — is hard-blocked in production. The GET /api/v1/complaints endpoint requires doctor/admin role (confirmed: complaints.py line 35), so in non-mock mode patients hit a dead wall at step 1 of intake and the core product never runs. That one line is the launch gate. Beyond it, the product's spine has the right bones: the WebSocket conversation layer (barge-in, TTS queue, supervisor guidance) is well-built, navigation is clean with no broken routes, route guards work, and every page loads. But the doctor clinical path — the other half of the spine — silently drops its most valuable actions: report Export-PDF and Regenerate exist in the API/store layer yet have no button (confirmed: exportReportPDF/generateReport defined but never called from UI), red-flag alerts have no acknowledge button on the detail/list, and session status / assign-doctor / patient-delete are all backend-ready but unreachable. So a doctor can read but cannot fully act. Layered on top are two systemic UX defects: (1) hardcoded Chinese strings across auth, patient-settings, doctor-patients, and admin pages break the promised 5-language experience for any non-Chinese user; (2) async action buttons across admin, doctor, and the medical-info form lack loading/disabled states, inviting double-submits and a destructive complaint-delete with no confirmation. Two truly dead buttons ship today (Change Password no-op, Audit Logs Filter stub). Net: the happy paths are 90% wired but the spine has one hard block and several missing action surfaces. Fix the complaints role check, surface the alert-acknowledge and report actions, add loading/confirmation guards, and finish i18n — then it ships.

**覆蓋**：清點 181 個互動元件；驗證 broken 3 個，其餘多數可用。

## 各 Journey 健康度

| Journey | 健康 | 一句話 |
|---|---|---|
| Auth (register / login / forgot / reset) | 62 | Flow is complete and completable end-to-end, but hardcoded Chinese strings across Register/Forgot/Reset break i18n for the 4 non-Chinese languages, plus inconsistent password-strength rules. |
| Patient Intake — SPINE (complaint → medical info → live voice → complete) | 55 | Well-architected and 95% wired, but a single backend role guard hard-blocks complaint loading in production, plus no form-disable on submit and no WS offline handling — the core path does not run as shipped. |
| Patient Account (post-session, history, settings) | 85 | Solid and completable; only a dead Change-Password button and a missing i18n key (falls back to Chinese) hold it back. |
| Doctor Core (dashboard → patients → sessions → reports, CRUD) | 68 | Read/navigate works smoothly, but every backend-ready mutation (delete, status, assign, acknowledge) lacks UI, and PatientList has hardcoded strings + no loading states. |
| Doctor Clinical — SPINE (alerts → acknowledge → SOAP report → notifications) | 64 | Clean navigation but the highest-value actions are missing buttons: alert action_taken, report Export-PDF, and Regenerate are all implemented in code yet unreachable. |
| Admin (users, complaints, audit logs) | 66 | Completes end-to-end but unsafe: destructive delete without confirmation, two dead/stub buttons, no loading states, silent validation, and no i18n. |
| Shell / Navigation | 82 | Strong — all 23 nav buttons route correctly, guards and lang-prefixing work; only orphaned /sessions and /notifications entry points remain. |

## 🚨 P0 上線阻斷

- **病患無法載入主訴清單**：`backend/app/routers/complaints.py:35` 的 GET 端點 `require_role("doctor","admin")`，但 `SelectComplaintPage` 走 `fetchComplaints()` → 該端點 → 病患角色 403。production（非 mock）下問診第一步直接卡死，核心流程跑不起來。

## ❌ 確認壞掉 / 死控制項

- Patient Intake / SelectComplaintPage :: Complaint list load (blocked by backend role guard) :: GET /api/v1/complaints requires require_role('doctor','admin') at complaints.py:35 — patient role excluded, so in production (non-mock) the list never loads and intake cannot begin. Hard launch blocker on the product's spine.
- PatientSettingsPage :: Change Password button :: No onClick handler (line ~206). Renders as a clickable, hover-styled button but does nothing — user clicks and nothing happens. Dead UI element on the account flow.
- ComplaintManagementPage (admin) :: Delete button :: Calls complaintsApi.deleteComplaint(id) immediately with no confirmation dialog and no disabled state during the call — accidental, unrecoverable deletion of complaint templates that patients depend on at intake.
- AuditLogsPage (admin) :: Filter button :: Permanently disabled stub with no explanation or handler — looks actionable but cannot be used; confusing dead control.
- SOAPReportPage (doctor) :: Export PDF action :: reportsApi.exportReportPDF() is implemented (reports.ts:47) but no button calls it — doctors cannot print/archive/share a report. Missing action surface on the report path.
- SOAPReportPage (doctor) :: Regenerate Report action :: generateReport() is implemented (reportStore.ts:202 / reports.ts:35) but no button calls it — doctors cannot iterate on an AI report. Missing action surface on the report path.
- AlertDetailPage (doctor) :: Red-flag acknowledge :: No action_taken capture and no list-level acknowledge — clinician cannot document the clinical action when acknowledging an alert. Incomplete on the alert path (the product's other spine).
- SessionDetailPage (doctor) :: Session status / Assign doctor / Acknowledge alert / Delete patient actions :: Backend endpoints exist (PUT /sessions/{id}/status, POST /sessions/{id}/assign, acknowledge, patientsApi.deletePatient) but no buttons or modals are surfaced — update/delete/triage workflows are unreachable from the UI.

## ▲ 重要流程問題（PM）

- DEAD-END (spine, critical): Patient intake breaks at step 1 in production — complaint list 403s for patient role, so register→login→start-intake leads nowhere. The core happy path is non-functional outside mock mode.
- BROKEN HAPPY PATH (spine): Doctor can navigate alert→detail→report and read everything, but the value-delivery actions (acknowledge with action_taken, export PDF, regenerate report) are missing — the clinician journey ends in 'view only', unable to close the loop.
- MISSING FEEDBACK (data-integrity): MedicalInfoPage form inputs are not disabled during submit (600ms mock delay / real network latency) — users can edit or cancel mid-submit, risking race conditions and data loss on the intake form.
- MISSING FEEDBACK / RESILIENCE: ConversationPage has no offline/reconnection banner — if the network drops mid-conversation the patient keeps talking to a dead socket with no indication, silently losing the session.
- DESTRUCTIVE WITHOUT GUARD: Admin complaint Delete fires immediately with no confirm and no disabled state — one stray click removes a template patients select during intake.
- SILENT FAILURE: ComplaintManagementPage Save shows no error on validation failure — user clicks, nothing visibly happens, cannot tell success from failure.
- ORPHAN ROUTES: /sessions list page and SessionCompletePage→/history navigation are unreachable (no entry point links to them) — dead code paths that signal unfinished navigation wiring.
- NO LOADING STATES on async buttons across admin (Toggle Active) and doctor flows — double-clicks can fire duplicate mutations.

## 系統性主題

- Incomplete i18n is the most pervasive theme: hardcoded Chinese strings appear in auth (Register/Forgot/Reset), patient settings, doctor patient-list, and all admin pages — any user on EN/JA/KO/VI sees broken mixed-language UI, undermining the app's headline multi-language promise.
- Missing loading/disabled states on async buttons is systemic (medical-info form, admin Toggle Active & Save & Delete, doctor action buttons) — invites double-submits, duplicate mutations, and mid-submit data edits.
- Backend-ready, UI-missing features are a recurring pattern: soft-delete, session status, assign-doctor, alert-acknowledge, report export/regenerate all have working endpoints with no surface — significant built value is stranded, concentrated on the doctor spine.
- Destructive actions lack confirmation (admin complaint delete; doctor patient delete would too once added) — no safety net before irreversible operations.
- Missing user feedback on outcomes — silent validation failures (admin Save) and no success/error toasts after operations leave users unsure whether actions worked.
- Orphaned routes / dead UI controls (/sessions, /history nav, Change-Password no-op, Audit Filter stub) indicate WIP code shipping to production without gating.

## PM Punchlist（依優先序）

1. P0 — LAUNCH BLOCKER: In backend/app/routers/complaints.py line 35, add 'patient' to the GET role guard (or expose a read-only patient endpoint) so patients can load the complaint list and start intake. Verify the full intake path in non-mock mode before anything else ships.
2. P0 — Surface red-flag alert ACKNOWLEDGE on AlertDetailPage with an action_taken text field; ensure acknowledge is reachable from both alert detail and list. This is the doctor spine's core action.
3. P0 — Add a loading/disabled state to MedicalInfoPage: set disabled={isCreating} on every input and the submit button to make intake submission atomic and prevent data loss.
4. P1 — Wire the two existing report actions on SOAPReportPage: an Export-PDF button → reportsApi.exportReportPDF(), and a Regenerate button → generateReport(). Code already exists; only the buttons are missing.
5. P1 — Add reconnection handling to ConversationPage: persistent disconnect/reconnecting banner with a manual Retry, so patients never talk to a dead socket.
6. P1 — Add a confirmation modal + disabled-during-call state to the admin ComplaintManagementPage Delete button; protect intake templates from accidental deletion.
7. P1 — Surface the doctor mutation UIs: patient soft-delete (confirm modal), session-status actions, and assign-doctor — all backed by existing endpoints.
8. P1 — Fix the PatientSettingsPage Change Password button: either implement the change-password flow/modal or remove the button and security tab until ready (no dead controls).
9. P2 — Complete i18n: extract all hardcoded Chinese strings in Register/Forgot/Reset, patient-settings (add patient.settings.saveFailedMessage), doctor patient-list, and admin pages into locale files; smoke-test all 5 languages on each page.
10. P2 — Add loading/disabled states to all remaining async buttons (admin Toggle Active & Save, doctor action buttons) and show success/error feedback after operations; show the validation error in the complaint Save form instead of failing silently.
11. P2 — Fix the AuditLogsPage Filter stub: either implement filtering or remove the disabled button; remove or wire the orphaned /sessions and SessionComplete→/history routes.
12. P3 — Align password policy: add the password-strength validation present in ResetPassword to RegisterPage; add character limits and add-item feedback on the medical-info free-text fields.

---

## 各頁完整按鈕清單

### auth（健康 62）

_The auth journey is functionally complete and all interactive elements work correctly. Navigation routes exist, backend endpoints are implemented, form validation occurs, loading states display, and error handling is in place. However, there is a critical localization failure: multiple pages (RegisterPage, ForgotPasswordPage, ResetPasswordPage) contain hardcoded Chinese strings in UI labels, button text, success messages, and error messages instead of using i18n. This breaks the multi-language experience for users selecting English, Japanese, Korean, or Vietnamese. The LoginPage is properly localized. Additionally, RegisterPage lacks password strength validation that is present in ResetPasswordPage, creating inconsistent password policies. Flow is clean and completable: register → login works, login → forgot password → email → reset password → login works, logout is available in header menus. All form submissions properly disable buttons during loading and show spinner feedback. No dead-ends or unreachable pages detected._

| 頁面 | 元件 | 類型 | 目標 | 判定 | 備註 |
|---|---|---|---|---|---|
| LoginPage | Email input field | no-op | email state | ✅ | Input with id='email', onChange handler sets email state. Validates non-empty on submit vi |
| LoginPage | Password input field | no-op | password state | ✅ | Input with id='password', onChange handler sets password state. Validates non-empty on sub |
| LoginPage | Show/Hide Password toggle button | toggle | showPassword state | ✅ | Button with type='button', toggles password field between text/password type. Has tabIndex |
| LoginPage | Forgot Password link | navigate | /:lng/forgot-password | ✅ | Link component with to={`/${lng}/forgot-password`}. Routes exist in RootNavigator. Uses t( |
| LoginPage | Login submit button | form-submit | authApi.login() | ✅ | Button type='submit' with disabled={isLoading}. Shows loading spinner when isLoading=true. |
| LoginPage | LanguageSwitcher (header) | open-modal | language selection dropdown | ✅ | Component renders language selection dropdown. Switches interface language and updates URL |
| RegisterPage | Name input field | no-op | formData.name state | ✅ | Input with name='name', required attribute, onChange updates formData state. Has placehold |
| RegisterPage | Email input field | no-op | formData.email state | ✅ | Input type='email', name='email', required, onChange updates formData. Placeholder 'your@e |
| RegisterPage | Medical Record / ID field (optional) | no-op | formData.mrrn state | ✅ | Input type='text', name='mrrn', optional field for medical record number. onChange updates |
| RegisterPage | Password input field | no-op | formData.password state | ✅ | Input type='password', name='password', required, onChange updates formData. Placeholder s |
| RegisterPage | Confirm Password input field | no-op | formData.confirmPassword state | ✅ | Input type='password', name='confirmPassword', required, onChange updates formData. |
| RegisterPage | Register submit button | form-submit | authApi.register() | ✅ | Button type='submit', disabled={isLoading}, shows spinner when loading. Calls handleSubmit |
| RegisterPage | Sign in link | navigate | /:lng/login | ✅ | Link with to={`/${lng}/login`}. Routes exist. Text='立即登入' (hardcoded Chinese). |
| ForgotPasswordPage | Email input field | no-op | email state | ✅ | Input type='email', onChange sets email state. Validates via validateEmail() on submit wit |
| ForgotPasswordPage | Send Reset Link button | form-submit | authApi.forgotPassword() | ✅ | Button type='submit', disabled={isLoading}, shows spinner. Calls handleSubmit which valida |
| ForgotPasswordPage | Back to Login link (form state) | navigate | /:lng/login | ✅ | Link with to={`/${lng}/login`}. Rendered in form when isSent=false. Text='返回登入' (hardcoded |
| ForgotPasswordPage | Back to Login link (success state) | navigate | /:lng/login | ✅ | Link with to={`/${lng}/login`}. Rendered when isSent=true after successful email send. Tex |
| ResetPasswordPage | New Password input field | no-op | password state | ✅ | Input type='password', id='password', onChange sets password state. Validates via validate |
| ResetPasswordPage | Confirm New Password input field | no-op | confirmPassword state | ✅ | Input type='password', id='confirmPassword', onChange sets confirmPassword state. Validate |
| ResetPasswordPage | Reset Password submit button | form-submit | authApi.resetPassword() | ✅ | Button type='submit', disabled={isLoading}, shows spinner. Calls handleSubmit which extrac |
| ResetPasswordPage | Back to Login link (form state) | navigate | /:lng/login | ✅ | Link with to={`/${lng}/login`}. Rendered when isDone=false. Text='返回登入' (hardcoded Chinese |
| ResetPasswordPage | Back to Login link (success state) | navigate | /:lng/login | ✅ | Link with to={`/${lng}/login`}. Rendered when isDone=true after successful password reset. |

### Home → Start Complaint Selection → Medical Info (2-step form) → Live Voice Conversation → Session Complete → Thank You → Back to Home（健康 72）

_The patient intake core flow is 95% complete and functional, with excellent code structure and comprehensive error handling for most happy-path scenarios. All 44 interactive elements are properly wired and routed. However, there are 2 critical blockers: (1) **The complaints list API requires doctor/admin role, blocking patients from entering the flow** — this must be fixed immediately in production; (2) **Medical info form lacks input disabling during submission**, allowing race conditions. The flow also has 8 medium-severity UX gaps (offline handling, red flag list truncation, no end-session confirmation, error state handling) and 5 low-severity polish issues (hardcoded mock data language, missing character limits, no add-item feedback). The WebSocket conversation layer is well-architected with barge-in support, TTS audio queuing, and supervisor guidance integration. Routes and API integration are correct end-to-end. Session complete and thank-you pages properly close the loop. **Recommend: Fix the complaints endpoint role check immediately, add form disabling on submit, implement end-session confirmation, and handle red flag truncation before production launch.**_

| 頁面 | 元件 | 類型 | 目標 | 判定 | 備註 |
|---|---|---|---|---|---|
| PatientHomePage | Start Intake Button (primary card) | navigate | /patient/start | ✅ | Button exists (line 104-125), onClick navigates to SelectComplaintPage. Route exists in Ro |
| PatientHomePage | View All Sessions Link | navigate | /patient/history | ✅ | Button exists (line 134-140), visible when recentSessions.length > 0. Route exists (RootNa |
| PatientHomePage | Recent Session Row (clickable) | navigate | /patient/session/{id}/complete OR /c | ✅ | Line 157-168: routes by status - completed/aborted_red_flag → complete page (route 146); i |
| SelectComplaintPage | Back Button | navigate | /patient | ✅ | Line 128-135, back to home. |
| SelectComplaintPage | Complaint Option Buttons | store-action | setSelected(complaint) | ✅ | Lines 156-186: local state only. |
| SelectComplaintPage | Start Button (Next CTA) | navigate | /patient/medical-info?complaintId=.. | ✅ | Lines 211-217: disabled={!selected}, constructs URL with params. |
| MedicalInfoPage | Back Button (header, step 1) | navigate | /patient/start | ✅ | Line 283-290. |
| MedicalInfoPage | Back Button (footer, step 1) | navigate | /patient/start | ✅ | Line 732: When stepIndex=0. |
| MedicalInfoPage | Previous Button (footer, step 2) | store-action | setCurrentStep('critical') | ✅ | Line 727-730: Shown when stepIndex > 0. |
| MedicalInfoPage | Next Button (footer, step 1) | store-action | handleNext() validates and transitio | ✅ | Lines 751-757: Validates critical fields, shows errors if invalid. |
| MedicalInfoPage | Submit Button (footer, step 2) | api-call | POST /api/v1/sessions | ✅ | Lines 737-758: calls createSession API, then navigates to /conversation/{sessionId}. Endpo |
| MedicalInfoPage | Patient Name Input | form-submit | setPatientName | ✅ | Line 341-351: Required, maxLength=100, validates on next/submit. |
| MedicalInfoPage | Gender Radio Buttons (M/F/Other) | form-submit | setGender | ✅ | Line 359-387: Required, 3 options. |
| MedicalInfoPage | Date of Birth Input | form-submit | setDateOfBirth | ✅ | Line 391-404: Required. |
| MedicalInfoPage | Phone Number Input | form-submit | setPhone | ✅ | Line 407-419: Optional, maxLength=20. |
| MedicalInfoPage | No Known Allergies Checkbox | toggle | setNoAllergies, conditionally clears | ✅ | Line 434-442. |
| MedicalInfoPage | Allergy Quick-Add Chips | store-action | addAllergy(item) | ✅ | Line 449-452: Shows filtered common allergies. |
| MedicalInfoPage | Add Allergy Button | store-action | addAllergy() | ✅ | Line 480. |
| MedicalInfoPage | Allergy Allergen Input | form-submit | updateAllergy | ✅ | Line 459-463. |
| MedicalInfoPage | Allergy Hospitalization Checkbox | toggle | updateAllergy 'hadHospitalization' | ✅ | Line 465-473. |
| MedicalInfoPage | Allergy Remove Button | store-action | removeAllergy(i) | ✅ | Line 474. |
| MedicalInfoPage | No Current Medications Checkbox | toggle | setNoMedications, conditionally clea | ✅ | Line 497-504. |
| MedicalInfoPage | Add Medication Button | store-action | addMedication() | ✅ | Line 534. |
| MedicalInfoPage | Medication Name Input | form-submit | updateMedication 'name' | ✅ | Line 513-517. |
| MedicalInfoPage | Medication Frequency Dropdown | form-submit | updateMedication 'frequency' | ✅ | Line 519-527. |
| MedicalInfoPage | Medication Remove Button | store-action | removeMedication(i) | ✅ | Line 528. |
| MedicalInfoPage | No Past History Checkbox | toggle | setNoHistory, conditionally clears l | ✅ | Line 559-566. |
| MedicalInfoPage | History Quick-Add Chips | store-action | addHistory(item) | ✅ | Line 573-576: Shows filtered common conditions. |
| MedicalInfoPage | Add History Button | store-action | addHistory() | ✅ | Line 622. |
| MedicalInfoPage | History Condition Input | form-submit | updateHistory 'condition' | ✅ | Line 585-589. |
| MedicalInfoPage | History Years Ago Dropdown | form-submit | updateHistory 'yearsAgo' | ✅ | Line 594-602: 4 options (within1, oneToFive, overFive, unsure). |
| MedicalInfoPage | History Still Has Checkbox | toggle | updateHistory 'stillHas' | ✅ | Line 604-612. |
| MedicalInfoPage | History Remove Button | store-action | removeHistory(i) | ✅ | Line 615. |
| MedicalInfoPage | Family History Expand Button | toggle | setFamilyOpen((v) => !v) | ✅ | Line 629-646: Chevron toggles collapsible section. |
| MedicalInfoPage | Add Family History Button | store-action | addFamily() | ✅ | Line 679. |
| MedicalInfoPage | Family Relation Dropdown | form-submit | updateFamily 'relation' | ✅ | Line 658-665: 8 relation options. |
| MedicalInfoPage | Family Condition Input | form-submit | updateFamily 'condition' | ✅ | Line 667-671. |
| MedicalInfoPage | Family Remove Button | store-action | removeFamily(i) | ✅ | Line 673. |
| ConversationPage | Back Button (header) | navigate | History back (-1) | ✅ | Line 605-612: onclick navigate(-1). |
| ConversationPage | End Session Button | api-call | WebSocket send control message, navi | ✅ | Line 619-624: handleEndSession() sends WS control action='end_session' and navigates with  |
| ConversationPage | Red Flag Acknowledge Button | store-action | acknowledgeRedFlag(alert.id) | ✅ | Line 665-670: Updates store, removes from unacknowledged list. |
| ConversationPage | Scroll to Latest Button | store-action | scrollChatToBottom(true) | ✅ | Line 784-798: Appears when userScrolledUp=true, smooth scroll. |
| ConversationPage (ChatBubble) | AI Message Replay Button (speaker icon) | store-action | onReplay(messageId) triggers replayM | ✅ | ChatBubble line 96-105: Shown when canReplay=true. ConversationPage line 236-252: Replays  |
| ConversationPage (ChatBubble) | AI Message Clickable Bubble | store-action | handleBubbleClick() → onReplay(messa | ✅ | ChatBubble line 72-106: Click and keyboard handlers if replayable. |

### patient-account（健康 85）

_JOURNEY HEALTH: 85/100. The patient post-session and account flow is largely complete and functional. All five pages (SessionCompletePage, SessionThankYouPage, PatientHistoryPage, PatientSessionDetailPage, PatientSettingsPage) have correct navigation, working buttons, and API integration. The critical user journey—completing a session, viewing it in history, and accessing account settings—works end-to-end with no broken navigation. However, two issues reduce the score: (1) a missing i18n key (patient.settings.saveFailedMessage) causes fallback to hardcoded Chinese in error messages, breaking i18n contract; (2) a Change Password button in the security tab is a dead UI element with no onClick handler, confusing users who expect it to work. No data loss risks, no security issues, no blocking bugs. Both issues are fixable in hours. Session detail page correctly has zero interactive elements (read-only view), and all API endpoints exist in the backend. Recommendation: add the missing i18n key and either implement or remove the change password button._

| 頁面 | 元件 | 類型 | 目標 | 判定 | 備註 |
|---|---|---|---|---|---|
| SessionCompletePage | Home Button | navigate | /patient | ✅ | onClick={() => navigate('/patient')} routes to patient home via useLocalizedNavigate. Rout |
| SessionCompletePage | View History Button | navigate | /patient/history | ✅ | onClick={() => navigate('/patient/history')} routes to history page. Route exists in RootN |
| SessionThankYouPage | Back Now Button | navigate | /patient | ✅ | onClick={() => navigate('/patient', { replace: true })} navigates home with replace flag.  |
| PatientHistoryPage | Back Arrow Button | navigate | /patient | ✅ | onClick={() => navigate('/patient')} in header. SVG icon button with arrow left symbol. Ro |
| PatientHistoryPage | Filter All Tab | store-action | setFilter('all') | ✅ | onClick={() => setFilter('all')} sets local state. No API call, filters frontend session a |
| PatientHistoryPage | Filter Completed Tab | store-action | setFilter('completed') | ✅ | onClick={() => setFilter('completed')} filters sessions. Local state management. |
| PatientHistoryPage | Filter In Progress Tab | store-action | setFilter('in_progress') | ✅ | onClick={() => setFilter('in_progress')} filters sessions. Local state management. |
| PatientHistoryPage | Filter Cancelled Tab | store-action | setFilter('cancelled') | ✅ | onClick={() => setFilter('cancelled')} filters sessions. Local state management. |
| PatientHistoryPage | Session List Items (Row Buttons) | navigate | /patient/session/{sessionId}/complet | ✅ | onClick dispatches navigation based on session status: completed/aborted_red_flag → /patie |
| PatientSessionDetailPage | Back Link (Arrow Icon) | navigate | /{lng}/patient/history | ✅ | <Link to={`/${lng}/patient/history`}> uses react-router Link. Target route exists. Histori |
| PatientSettingsPage | Profile Tab Button | store-action | setActiveTab('profile') | ✅ | onClick={() => setActiveTab('profile')} sets local tab state. Renders profile form with ed |
| PatientSettingsPage | Notifications Tab Button | store-action | setActiveTab('notifications') | ✅ | onClick={() => setActiveTab('notifications')} switches to notifications tab. Renders toggl |
| PatientSettingsPage | Security Tab Button | store-action | setActiveTab('security') | ✅ | onClick={() => setActiveTab('security')} switches to security tab. Displays change passwor |
| PatientSettingsPage | Save Changes Button | api-call | authStore.updateProfile() → PUT /aut | ✅ | onClick={handleSaveProfile} calls updateProfile({email, phone, preferredLanguage}) from au |
| PatientSettingsPage | Email Notifications Toggle | store-action | setNotificationsEnabled(e.target.che | ✅ | onChange={(e) => setNotificationsEnabled(e.target.checked)} from settingsStore. Local stat |
| PatientSettingsPage | Push Notifications Toggle | store-action | setSoundEnabled(e.target.checked) | ✅ | onChange={(e) => setSoundEnabled(e.target.checked)} from settingsStore. Local state, persi |
| PatientSettingsPage | Change Password Button | no-op | none | ❌ | Button has no onClick handler. Line 206 defines <button> with hover styling but no onClick |
| PatientSettingsPage | Language Dropdown (Preferred Language Se | store-action | setLanguage(e.target.value as 'zh-TW | ✅ | onChange={(e) => setLanguage(e.target.value)} updates settingsStore.language. Dropdown has |

### Doctor login → Dashboard (view stats, navigate months) → Patients list (search, filter by month, infinite scroll) → Patient detail (view sessions) → Session detail (view conversation, generate report) → Report detail (view/edit SOAP note) → Back to sessions/patients. Full CRUD: view, create patient, assign doctor, update session status, delete patient, acknowledge alert.（健康 68）

_The doctor-core journey is substantially complete with functional navigation and CRUD retrieval. All 15 interactive elements tested route to existing pages and call real backend endpoints. Navigation between dashboard → patients → sessions → reports works smoothly. However, 6 medium-to-high severity issues prevent 100% workflow completion: (1) HARDCODED I18N STRINGS in PatientListPage violate localization standards; (2) NO LOADING STATES on async buttons risk double-submit bugs; (3) MISSING DELETE UI for patient soft-delete (backend ready, frontend not surfaced); (4) MISSING SESSION STATUS ACTIONS (complete, cancel, abort); (5) MISSING ASSIGN DOCTOR UI; (6) INCOMPLETE RED FLAG WORKFLOW (no acknowledge button). These are backend-ready features blocked only by UI. The core read/view/navigate flow works but the update/delete/action workflows are incomplete._

| 頁面 | 元件 | 類型 | 目標 | 判定 | 備註 |
|---|---|---|---|---|---|
| DashboardPage | Previous month button (left arrow) | store-action | setSelectedMonth(addMonths(current,  | ✅ | Line 384. onClick handler updates selectedMonth state & re-fetches dashboard via dashboard |
| DashboardPage | Next month button (right arrow) | store-action | setSelectedMonth(addMonths(current,  | ✅ | Line 397. Symmetrical to prev button. |
| PatientListPage | Previous month button (left arrow) | store-action | setSelectedMonth() + fetchPatients(t | ✅ | Line 164. Updates selectedMonth state, triggers fetch with new date range. Backend endpoin |
| PatientListPage | Next month button (right arrow) | store-action | setSelectedMonth() + fetchPatients(t | ✅ | Line 177. Symmetrical. |
| PatientListPage | SearchBar (search by name/MRN) | form-submit | setSearch() → fetchPatients(true) | ✅ | Line 203-207. SearchBar onChange at line 101-107 calls handleSearch(query) → setSearch(que |
| PatientListPage | Patient row (entire clickable button) | navigate | /(lng)/patients/{patient.id} | ✅ | Line 249. Navigates via useLocalizedNavigate(). Route: RootNavigator.tsx line 159 <Route p |
| PatientListPage | Infinite scroll sentinel (load more) | api-call | fetchMore() → patientsApi.getPatient | ✅ | Lines 109-126. IntersectionObserver on sentinelRef (line 285) triggers fetchMore() when vi |
| PatientDetailPage | Back button (left arrow icon) | navigate | /(lng)/patients | ✅ | Line 64. onClick={() => navigate('/patients')}. |
| PatientDetailPage | Recent Sessions card row (clickable) | navigate | /(lng)/sessions/{session.id} | ✅ | Line 138. onClick navigates to /sessions/{session.id}. Route: RootNavigator.tsx line 161. |
| SessionListPage | Search bar (search by patient name or ch | store-action | setSearchQuery() + local filter | ✅ | Line 77. SearchBar onChange → setSearchQuery(). Frontend filters by patient.name or chiefC |
| SessionListPage | Status filter tabs (All / In Progress /  | store-action | setStatusFilter(key) | ✅ | Lines 80-92. Four button tabs. onClick calls setStatusFilter(tab.key). Re-filters sessions |
| SessionListPage | Session card (entire clickable row) | navigate | /(lng)/sessions/{session.id} | ✅ | Line 104-110. onClick navigates to /sessions/{session.id}. |
| SessionDetailPage | Back button (left arrow icon) | navigate | navigate(-1) (browser back) | ✅ | Line 86. onClick={() => navigate(-1)}. |
| SessionDetailPage | View Report button (primary, with docume | navigate | /(lng)/reports/{session.id} | ✅ | Lines 126-132. onClick navigates to /reports/{session.id}. Route exists: RootNavigator.tsx |
| SessionDetailPage | Enter Conversation button (secondary) | navigate | /(lng)/conversation/{session.id} | ✅ | Lines 133-141. onClick navigates to /conversation/{session.id}. Route exists: RootNavigato |

### Doctor Clinical: Alert List → Alert Detail (acknowledge) → Report List → SOAP Report (review/approve) → Notifications → Settings（健康 72）

_Doctor journey is 95% complete. All routes exist and work. All backend endpoints implemented. Two major missing UI features (export PDF, regenerate) despite full backend support. Alert acknowledge missing action_taken field. Settings not backend-synced. Otherwise clean flow: navigate→acknowledge→review→mark read→adjust settings. No dead ends. Most feedback present except list-level acknowledge._

| 頁面 | 元件 | 類型 | 目標 | 判定 | 備註 |
|---|---|---|---|---|---|
| AlertListPage | Filter: All | store-action | setFilter('all') | ✅ | Works |
| AlertListPage | Filter: Unacknowledged | store-action | setFilter('unacknowledged') | ✅ | Works |
| AlertListPage | Filter: Acknowledged | store-action | setFilter('acknowledged') | ✅ | Works |
| AlertListPage | Search | store-action | setSearchQuery() | ✅ | Filters alerts |
| AlertListPage | View Detail | navigate | /alerts/{alertId} | ✅ | Route exists |
| AlertListPage | Acknowledge (item) | api-call | POST /api/v1/alerts/{id}/acknowledge | ✅ | Backend exists |
| AlertDetailPage | Back | navigate | /:lng/alerts | ✅ | Works |
| AlertDetailPage | Acknowledge | api-call | POST /api/v1/alerts/{id}/acknowledge | ✅ | Missing action_taken collection |
| AlertDetailPage | View Session | navigate | /:lng/sessions/{sessionId} | ✅ | Works |
| ReportListPage | Filter: All | store-action | setReviewFilter('') | ✅ | Works |
| ReportListPage | Filter: Pending | store-action | setReviewFilter('pending') | ✅ | Works |
| ReportListPage | Filter: Approved | store-action | setReviewFilter('approved') | ✅ | Works |
| ReportListPage | Filter: Revision | store-action | setReviewFilter('revision_needed') | ✅ | Works |
| ReportListPage | Report card | navigate | /reports/{sessionId} | ✅ | Route exists |
| SOAPReportPage | Back | navigate | navigate(-1) | ✅ | Works |
| SOAPReportPage | View Session | navigate | /sessions/{sessionId} | ✅ | Works |
| SOAPReportPage | Patient Info | navigate | /patients/{patientId} | ✅ | Works |
| SOAPReportPage | Tab Report | toggle | setActiveTab('report') | ✅ | Mobile |
| SOAPReportPage | Tab Transcript | toggle | setActiveTab('transcript') | ✅ | Mobile |
| SOAPReportPage | Approve | open-modal | Review modal | ✅ | Opens modal |
| SOAPReportPage | Request Revision | open-modal | Review modal | ✅ | Opens modal |
| SOAPReportPage | Modal Cancel | toggle | Close | ✅ | Works |
| SOAPReportPage | Modal Confirm | api-call | PUT /api/v1/reports/{id}/review | ✅ | Backend exists |
| NotificationPage | Mark All Read | api-call | PUT /api/v1/notifications/read-all | ✅ | Backend exists |
| NotificationPage | Card click | api-call | markRead + navigate | ✅ | Works |
| SettingsPage | Light theme | store-action | setTheme('light') | ✅ | Local |
| SettingsPage | Dark theme | store-action | setTheme('dark') | ✅ | Local |
| SettingsPage | Language | store-action | setLanguage() | ✅ | Local |
| SettingsPage | Notifications | toggle | setNotificationsEnabled() | ✅ | Local only |
| SettingsPage | Sound | toggle | setSoundEnabled() | ✅ | Local only |
| SettingsPage | Audio device | store-action | setAudioDevice() | ✅ | Works |

### admin（健康 68）

_The admin journey is functionally complete: all four pages load, backend APIs match frontend calls, navigation works, and role guards are in place. However, there are critical UX gaps: (1) destructive delete lacks confirmation, (2) validation errors not shown in all cases, (3) action buttons lack loading states allowing double-clicks, (4) no success/error feedback after operations, (5) pages not internationalized. The journey completes end-to-end but needs safety and feedback improvements for production use."_

| 頁面 | 元件 | 類型 | 目標 | 判定 | 備註 |
|---|---|---|---|---|---|
| UserManagementPage | New User button | open-modal | showCreateModal state | ✅ | Opens create user modal, initializes form state correctly |
| UserManagementPage | Role filter tabs | store-action | setRoleFilter | ✅ | Filters users by role, refetches data via fetchUsers() |
| UserManagementPage | SearchBar | store-action | setSearchQuery | ✅ | Search updates user list via fetchUsers callback |
| UserManagementPage | Edit button in table | open-modal | openEditModal(user) | ✅ | Opens modal with user data pre-filled |
| UserManagementPage | Toggle Active button | api-call | adminApi.toggleUserActive(user.id) | ⚠️ | Works but no disabled/loading state during API call; allows double-click |
| UserManagementPage | Modal Cancel button | store-action | setShowCreateModal(false) | ✅ | Closes modal |
| UserManagementPage | Modal Create/Update button | form-submit | handleSubmit | ✅ | Validates fields, calls API, closes modal, refetches list. Button disabled while submittin |
| UserManagementPage | Email input | no-op | form validation | ✅ | Type email with browser validation |
| UserManagementPage | Phone input | no-op | form input | ✅ | Optional field |
| UserManagementPage | Active checkbox | no-op | form toggle | ✅ | Toggle isActive |
| ComplaintManagementPage | New Complaint button | open-modal | openCreateModal | ✅ | Opens modal with blank form |
| ComplaintManagementPage | Search input | store-action | setSearchTerm | ✅ | Client-side filter on complaints |
| ComplaintManagementPage | Edit button | open-modal | openEditModal(complaint) | ✅ | Opens modal with complaint data pre-filled |
| ComplaintManagementPage | Delete button | api-call | complaintsApi.deleteComplaint(id) | ❌ | No confirmation dialog; no disabled state during API call; allows accidental deletion |
| ComplaintManagementPage | Modal Cancel button | store-action | setShowModal(false) | ✅ | Closes modal |
| ComplaintManagementPage | Modal Save button | form-submit | handleSubmit | ⚠️ | Validates but does not show error message if validation fails; button disabled while submi |
| ComplaintManagementPage | Name input | no-op | form input | ✅ | Text field |
| ComplaintManagementPage | Category input | no-op | form input | ✅ | Required field |
| ComplaintManagementPage | Description textarea | no-op | form input | ✅ | Optional field |
| ComplaintManagementPage | Active checkbox | no-op | form toggle | ✅ | Toggle isActive |
| SystemHealthPage | Refresh button | api-call | adminApi.getSystemHealth() | ✅ | Refetches health data from backend |
| SystemHealthPage | Health metrics cards | no-op | display only | ✅ | Displays API response data |
| SystemHealthPage | System events section | no-op | display only | ✅ | Shows health status and timestamp |
| SystemHealthPage | Service quota section | no-op | display only | ✅ | Displays database and redis status |
| AuditLogsPage | Refresh button | api-call | adminApi.getAuditLogs() | ✅ | Refetches audit logs list |
| AuditLogsPage | Search input | store-action | setSearchTerm | ✅ | Client-side filter on logs |
| AuditLogsPage | Filter button | no-op | disabled button | ❌ | Button disabled with no explanation; confusing UX |
| AuditLogsPage | Audit log table | no-op | display only | ✅ | Displays audit log data |

### shell-nav（健康 82）

_Shell navigation complete. 25 buttons inventoried: all navigate to real routes or call existing APIs. Route guards work correctly. One medium issue: /sessions unreachable. All navigation localized and lang-prefixed. API param conversion auto-handled. Language switching verified. Multi-role support correct._

| 頁面 | 元件 | 類型 | 目標 | 判定 | 備註 |
|---|---|---|---|---|---|
| Header | Theme Toggle | toggle | setTheme() | ✅ | Toggles dark/light theme via useSettingsStore; aria-label localized |
| Header | Bell Icon | navigate | /notifications | ✅ | Route exists at RootNavigator:166; role-gated doctor/admin; unreadCount badge shown |
| Header | Avatar Menu | toggle | setMenuOpen | ✅ | Opens dropdown menu; includes outside-click and ESC handlers |
| Header Menu | Settings Link | navigate | /settings | ✅ | Route RootNavigator:167; closes menu after |
| Header Menu | Logout | api-call | POST /auth/logout | ✅ | Endpoint auth.py:140; clears tokens; nav to /login |
| Sidebar | Dashboard | navigate | /dashboard | ✅ | Doctor/admin; RootNavigator:157 |
| Sidebar | Try Convo | navigate | /patient | ✅ | Doctor/admin; RootNavigator:140 |
| Sidebar | Patients | navigate | /patients | ✅ | Doctor/admin; RootNavigator:158 |
| Sidebar | Reports | navigate | /reports | ✅ | Doctor/admin; RootNavigator:162 |
| Sidebar | Alerts | navigate | /alerts | ✅ | Badge with count; RootNavigator:164 |
| Sidebar | Users (Admin) | navigate | /admin/users | ✅ | Admin only; RootNavigator:171 |
| Sidebar | Complaints | navigate | /admin/complaints | ✅ | Admin; RootNavigator:172 |
| Sidebar | Health | navigate | /admin/health | ✅ | Admin; RootNavigator:173 |
| Sidebar | Audit | navigate | /admin/audit-logs | ✅ | Admin; RootNavigator:174 |
| Sidebar | Settings | navigate | /settings | ✅ | All users; RootNavigator:167 |
| PatientLayout | Logo | navigate | role !== patient ? /dashboard : /pat | ✅ | Multi-role support |
| PatientMenu | Back | navigate | /dashboard | ✅ | Conditional doctor/admin |
| PatientMenu | History | navigate | /patient/history | ✅ | RootNavigator:143 |
| PatientMenu | Settings | navigate | /patient/settings | ✅ | RootNavigator:145 |
| LangSwitcher | Button | toggle | setOpen | ✅ | Opens dropdown |
| LangMenu | Options | store-action | handleSelect with modal | ✅ | M16: shows modal if active session |
| LangModal | Cancel | toggle | handleCancel | ✅ | Closes without switch |
| LangModal | Confirm | api-call | POST /sessions/{id}/end-for-language | ✅ | sessions.py:149 |

