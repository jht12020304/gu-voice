# gu-voice 產品就緒度審查報告

> 多 agent（55 個子代理）對 12 個功能域做 end-to-end 完整性 + 產品級就緒度審查，所有 critical/high 發現經對抗式驗證複核。
> 日期：2026-06-14 ｜ 工具呼叫 1,440 次 ｜ Run ID: wf_ca522357-525

---

## 總判定

- **整體裁決：`significant-gaps`（重大缺口）**
- **整體就緒度：63%**

### 執行摘要

gu-voice is NOT production-ready. The voice-intake core (mic → STT → LLM → TTS → red-flag detection) and the infra/bootstrap layer are genuinely strong, but the app handles medical PII and fails the bar on the two things that matter most: data isolation and the safety/alert path. Multi-tenant authorization is broken across nearly every read path — doctors can read ANY patient's data, reports, sessions, alerts, and dashboards regardless of ownership (confirmed in report_service.get_report, patient_service, alert_service.get_list, and the dashboard WebSocket helpers). Separately, several user-facing features crash on their happy path because routers call service methods that don't exist or pass parameters the service never declared: notifications (list_notifications/get_list mismatch, device_token/payload.token mismatch, mark_all_read returns int), admin user CRUD (create/update/toggle are literal `raise AppException("Not implemented", 501)` / hardcoded stubs), patient delete (soft_delete_patient does not exist → AttributeError), and red-flag acknowledge (action_taken passed to a method that rejects it → TypeError, meaning doctors cannot acknowledge alerts). On the safety side, the red-flag path persists alerts but swallows DB-commit failures while still emitting a fake alert_id to the frontend, push-notification failures are silently dropped (bare `pass`), and admin actions on user accounts are never audit-logged — a HIPAA-grade gap. A confirmed PII-retention violation exists: audio_lifecycle._delete_audio_blob only logs instead of deleting Supabase blobs, so audio is retained indefinitely despite the 90-day policy. Frontend has a missing ResetPasswordPage (password recovery cannot be completed) and a missing Toaster provider (user feedback silently fails). Estimate 2-4 focused engineering weeks to close blockers before this can safely touch real patient data.

---

## 各域就緒度一覽

| 功能域 | 完整度 | 就緒 | 一句話結論 |
|---|---|---|---|
| 核心基礎設施 (`infra-core`) | 92 | ✅ | Production-grade: enforced prod secrets, tuned DB pooling with PgBouncer mitigations, Redis lifecycle, PII-redacting exception handling, health checks; only fix is str(exc) leaking to the client response. |
| 前端骨架與 i18n (`frontend-shell-i18n`) | 82 | 🟡 | Strong routing/i18n with full 5-locale coverage and guarded routes, but the missing react-hot-toast Toaster provider means user feedback (incl. language-switch) silently fails to render. |
| 音訊 / STT / TTS (`audio-stt-tts`) | 72 | 🟡 | Happy-path pipeline is fully wired, but _delete_audio_blob is a confirmed stub that never deletes blobs — a PII-retention compliance blocker; unused AudioService signals abandoned storage integration. |
| 前端病患/醫師 UX (`frontend-patient-doctor-ui`) | 78 | 🟡 | All core patient/doctor journeys implemented and wired; main gap is silent error-swallowing on settings save plus sparse a11y labels — UX/robustness, not structural. |
| 認證與安全 (`auth-security`) | 72 | 🟡 | Solid RS256/bcrypt/refresh-rotation core, but missing frontend ResetPasswordPage, a UUID-cast bug breaking reset, missing role enforcement on registration, and no WS blacklist check. |
| 場次與 LLM 對話 (`sessions-conversation`) | 72 | 🟡 | Robust state machine and encryption, but reconnect API has no frontend caller, supervisor guidance has no UI binding, supervisor timeouts degrade silently, and history compression can discard red-flag context on summary failure. |
| SOAP / ICD-10 / 主訴 (`soap-icd10-complaints`) | 72 | 🟡 | SOAP/ICD-10 flow wired with good tests, but complaint update/delete enforce no is_default/ownership authorization despite docstrings, and SOAP JSON lacks Pydantic structural validation. |
| 儀表板與病患 (`dashboard-patients`) | 72 | 🟡 | Core CRUD/dashboards work, but patient delete calls a nonexistent service method (AttributeError) and list/detail/sessions/WS queries are entirely unscoped by doctor — major authorization bypass. |
| 報告 (`reports`) | 62 | 🟡 | Core generate/review/retrieve works with revision audit trail, but zero ownership checks on PII reads/PDF export, response_model schema mismatches, and no FAILED-state handling for dead Celery jobs. |
| 紅旗偵測與警示 (`red-flag-alerts`) | 62 | 🟡 | Dual-layer detection is well-designed, but acknowledge is broken by a signature mismatch, alert list is unscoped across doctors, and alert-creation + push failures are swallowed silently — unacceptable for the safety path. |
| 通知 (`notifications`) | 35 | ⛔ | Broken on happy path: router→service method-name mismatch, schema field mismatch, and return-type mismatch all crash core flows; no preferences/opt-out, no email delivery, no ownership check on token removal. |
| 管理與稽核 (`admin-audit`) | 25 | ⛔ | Severely incomplete: user create/update/toggle and health check are 501/hardcoded stubs, audit-log router calls nonexistent methods, and admin actions are never audit-logged (HIPAA gap). |

---

## 上線前必修 Blockers（排序）

1. AUTHORIZATION / DATA ISOLATION (cross-domain, CRITICAL): No ownership enforcement on medical PII reads. reports (get_report/list_reports/export_pdf), patients (get_patient/get_patient_sessions/list_patients), alerts (get_list returns all clinics' alerts), and the dashboard WebSocket (queue/alerts/stats unscoped) all let any authenticated doctor read every patient's data. current_user is accepted but never checked. Must enforce row-level scoping before launch.

2. Admin user management is entirely stubbed (admin_service.create_user/update_user raise 501; toggle_active returns hardcoded is_active=False; system_health_check returns fake 'ok'). No admin can create, edit, enable/disable, or monitor accounts. Plus admin actions are not audit-logged (HIPAA gap).

3. Red-flag acknowledge is broken (router passes action_taken to AlertService.acknowledge which doesn't accept it → TypeError) AND alert-creation DB-commit failures are swallowed while a fake alert_id is emitted to the frontend. Doctors cannot reliably acknowledge alerts and may believe an unpersisted alert exists. This is the patient-safety path and must be solid.

4. Notifications domain is broken on happy path: router calls notification_service.list_notifications() but only get_list() exists (AttributeError on every list); FCMTokenCreate.device_token vs router payload.token mismatch (AttributeError on register); mark_all_read returns int but response_model is MarkAllReadResponse (serialization failure). Core notification flows do not work.

5. Patient delete endpoint calls patient_service.soft_delete_patient(), which does not exist → AttributeError on every delete; Patient model also has no soft-delete column, contradicting the documented soft-delete behavior.

6. PII retention violation: audio_lifecycle._delete_audio_blob only logs the URL instead of deleting the Supabase Storage blob. Audio is retained indefinitely despite the 90-day AUDIO_RETENTION_DAYS policy. Confirmed stub.

7. Password recovery cannot be completed: backend /auth/reset-password works but there is no frontend ResetPasswordPage, and reset_password has a string-vs-UUID type bug that makes valid tokens return user_not_found. Role enforcement on registration is also missing (a caller can self-register as DOCTOR/ADMIN).

8. Report POST /generate and PUT /review declare response_models (GenerateReportResponse / ReviewReportResponse) that don't match the SOAPReport the service returns, and no validation enforces session==completed before generation; failed Celery report jobs leave reports stuck in 'generating' forever with no FAILED state.

---

## 系統性跨域主題

- Broken router↔service contracts that fail on the happy path, not in edge cases: method-name mismatches (notifications list_notifications/get_list, audit_logs list_audit_logs/get_audit_log), nonexistent methods (patient soft_delete_patient), parameter mismatches (alert acknowledge action_taken, FCM device_token/token), and response_model/return-type mismatches (reports POST/PUT, notifications mark_all_read, unread_count). Indicates routers and services were written against drifted interfaces with no integration/contract tests to catch it.

- Pervasive missing ownership/authorization on medical PII: current_user is threaded through service methods across reports, patients, alerts, complaints, and dashboard WS but is repeatedly accepted-and-ignored. Role gates exist at the router (require_role) but row-level data isolation is absent, so any doctor sees all patients. This is the single most serious systemic risk for a PII medical app.

- Silent failure / swallowed exceptions on safety- and audit-critical paths: bare `pass` or warn-and-continue on alert DB-commit failure (then emits a fake alert_id), push-notification dispatch, uncovered_locale audit logging, notification mark-read errors, and WebSocket dashboard query failures (returns zero/empty data). Operators and users cannot tell when the system is silently degraded.

- Stubs and half-wired features shipped behind real-looking endpoints: admin user CRUD (501), system health (hardcoded ok), audio blob deletion (log-only), report additional_notes/date filters/include_transcript (accepted-but-ignored params), notification filters. The UI exposes these as working features.

- Compliance/audit gaps for a medical app: admin user-management actions never audit-logged, audio PII retained past the 90-day policy, no notification preferences/opt-out (GDPR), and confidence/turn-context not persisted for red-flag alerts.

- Frontend feature-completion gaps that strand backend work: missing ResetPasswordPage (password reset dead-ends), missing reconnectSession client (reconnect API uncallable), no supervisor-guidance store binding, and a missing Toaster provider (notifications never render).

---

## 上線 Checklist

- [ ] Enforce row-level data isolation on ALL PII reads: add and actually use ownership checks in report_service.get_report/list_reports/export_pdf, patient_service.get_patient/get_patient_sessions, alert_service.get_list, and the dashboard WS helpers (_get_queue_status/_get_active_alerts/_get_dashboard_stats). Patients see only their own; doctors see only assigned; admins see all. Add tests proving a doctor cannot read another doctor's patient/report/alert.
- [ ] Fix the red-flag safety path: align acknowledge router↔service signature (action_taken), add the action_taken DB column or drop it, stop emitting a fake alert_id when persistence fails (send a real error to the frontend instead), and log push/audit failures at ERROR with metrics. Add an end-to-end acknowledge integration test.
- [ ] Implement admin user management for real: create_user (hash password, unique-email check, insert, audit), update_user (incl. email field in AdminUserUpdate schema), toggle_active (real DB flip + self-deactivation guard + audit), and system_health_check (DB SELECT 1, Redis PING, OpenAI probe). Return the correct response type for toggle.
- [ ] Add audit-log rules for every /api/v1/admin/* mutation (create/update/toggle) in middleware, and fix audit_logs router to call the real service methods (get_list/get_by_id).
- [ ] Repair notifications: rename/align list_notifications↔get_list (and implement is_read/type filters), fix device_token vs payload.token, return MarkAllReadResponse from mark_all_read, add ownership check to remove_fcm_token, and add a dead-letter/alert on permanent push failure.
- [ ] Fix patient delete: implement soft_delete_patient (and add is_active/deleted_at + index to the Patient model) or repoint the router to the existing delete path; pass doctor_id scoping into list_patients.
- [ ] Implement real Supabase Storage deletion in audio_lifecycle._delete_audio_blob (parse bucket/path, SERVICE_ROLE_KEY client, storage.remove); verify the 90-day retention job actually removes blobs in staging.
- [ ] Complete password recovery: build frontend ResetPasswordPage (token from query param), fix the str→UUID cast in reset_password, enforce role on registration (default PATIENT; reject self-elevation to DOCTOR/ADMIN), and add forgot-password rate limiting + WS-handshake blacklist check.
- [ ] Fix report contracts: align POST /generate and PUT /review response_model with the actual SOAPReport return, validate session.status == completed before enqueueing, and add a FAILED report state + on_failure callback so stuck 'generating' reports are surfaced.
- [ ] Add the missing frontend glue: <Toaster/> provider, reconnectSession API client wired into the reconnect path, and supervisor-guidance store binding (or explicitly defer guidance UI and notify the patient when supervision degrades).
- [ ] Harden the conversation pipeline: on history-summary failure, do not silently discard old turns (keep raw or flag incompleteness); surface supervisor-timeout degradation to the patient; persist STT confidence/duration and red-flag turn context.
- [ ] Patch infra-core leak: replace str(exc) in the global unhandled-exception handler with a generic message (log details server-side/Sentry only); document /metrics IP-restriction.
- [ ] Add contract/integration tests at the router↔service boundary across all domains to catch the method-name/param/response-type drift class of bug, and run them in CI before launch.

---

## 各域詳細發現

### 管理與稽核 (`admin-audit`) — 完整度 25 / 就緒 no

_The Admin & Audit domain is severely incomplete, with critical gaps blocking production use. Key CRUD operations (create/update user, toggle active) are not implemented—they throw 501 errors or return mock data. The audit log router calls non-existent service methods, causing runtime failures. Admin operations (user management, complaint management) are not audited at all despite HIPAA/medical compliance requirements. The backend schema for user updates is missing the email field despite frontend sending it. Response types are mismatched between backend and frontend (ToggleActiveResponse vs User). Only audit log retrieval, health check (stubbed), and listing endpoints partially exist._

**End-to-end 接線：** Broken. The audit logs router calls `audit_log_service.list_audit_logs()` and `audit_log_service.get_audit_log()` which don't exist (service has `get_list()` and `get_by_id()`). Frontend calls `toggleUserActive()` which returns `ToggleActiveResponse` but expects `User`. Frontend sends `email` in update request to a schema that doesn't accept it. Admin operations (POST/PUT /admin/users) are 501 not-implemented. System health endpoint returns hardcoded data, not real checks.

**已驗證 Critical/High：**

- **[CRITICAL]** `ADMIN-1` — Router calls non-existent AuditLogService methods  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/audit_logs.py:52, 78` ｜ 驗證：confirmed  
  問題：The audit_logs router calls `audit_log_service.list_audit_logs()` on line 52 and `audit_log_service.get_audit_log()` on line 78, but the AuditLogService class only implements `get_list()` and `get_by_id()` methods. This will cause AttributeError at runtime when admin tries to view audit logs.  
  修法：Rename service methods to `list_audit_logs()` and `get_audit_log()` or update router to call `get_list()` and `get_by_id()`.
- **[CRITICAL]** `ADMIN-3` — User update endpoint not implemented (returns 501)  
  `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:101-109` ｜ 驗證：confirmed  
  問題：The `update_user()` method raises AppException("Not implemented in stub", 501) instead of updating user fields. Frontend sends updates but backend returns 501.  
  修法：Implement user update logic: validate ownership/authz, update fields, persist changes.
- **[CRITICAL]** `ADMIN-4` — User toggle active endpoint returns hardcoded mock data  
  `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:111-118` ｜ 驗證：confirmed  
  問題：The `toggle_active()` method returns a hardcoded ToggleActiveResponse(is_active=False) instead of actually toggling the user's active status in the database. Users toggled on/off always show as inactive.  
  修法：Implement actual toggle: fetch user, flip is_active, persist to DB, log audit entry, return updated state.
- **[CRITICAL]** `ADMIN-8` — Admin operations not audited (HIPAA/compliance gap)  
  `/Users/chun/Desktop/GU_0410/backend/app/core/middleware.py:99-120` ｜ 驗證：confirmed  
  問題：The audit middleware's _AUDIT_RULES does not include any rules for /api/v1/admin/* endpoints. User creation, updates, and toggle-active operations are never logged to audit_logs table, violating medical compliance requirements (HIPAA, medical audit trail requirements). These are critical administrative actions that must be audited.  
  修法：Add audit rules for all admin endpoints: POST /admin/users (CREATE), PUT /admin/users/{id} (UPDATE), PUT /admin/users/{id}/toggle-active (UPDATE). Admin changes to user status/role are sensitive and MUST be logged.
- **[HIGH]** `ADMIN-2` — User create endpoint not implemented (returns 501)  
  `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:92-99` ｜ 驗證：confirmed  
  問題：The `create_user()` method raises AppException("Not implemented in stub", 501) instead of performing user creation. Frontend can call POST /admin/users to create users, but backend will return 501 error.  
  修法：Implement user creation logic: hash password, insert User record, log audit entry for user creation.
- **[HIGH]** `ADMIN-5` — System health check returns stubbed/hardcoded status  
  `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:120-125` ｜ 驗證：confirmed  
  問題：The `system_health_check()` method returns hardcoded 'ok' status instead of actually checking database, Redis, and external services. Admins cannot see real system health.  
  修法：Implement real health checks: SELECT 1 from DB, PING Redis, verify OpenAI API connectivity, return actual status values.
- **[HIGH]** `ADMIN-7` — UpdateUserRequest schema missing email field  
  `/Users/chun/Desktop/GU_0410/backend/app/schemas/admin.py:26-33` ｜ 驗證：confirmed  
  問題：AdminUserUpdate schema does not include email field, but frontend sends email in update payload. The email field will be silently ignored or cause validation error.  
  修法：Add email field to AdminUserUpdate schema: `email: Optional[EmailStr] = None`
- **[HIGH]** `ADMIN-9` — No self-modification checks in toggle_active endpoint  
  `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:111-118` ｜ 驗證：confirmed  
  問題：The toggle_active method does not validate that admin cannot deactivate/toggle their own account. An admin could disable their own access, locked out until another admin re-enables. The docstring says 'Do not allow self-operation' but implementation does not enforce it.  
  修法：Add check: if user_id == toggled_by: raise ForbiddenException('Cannot modify your own account')

**Medium（5）：** ADMIN-10 Complaint management may require wrong role authorization；ADMIN-12 Missing error handling for empty user list operations；ADMIN-13 AuditLogsPage missing filter implementation for audit parameters；ADMIN-14 Audit retention task uses raw SQL without parameterization；ADMIN-15 System health check does not check all advertised components

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:92-99` — async def create_user(...): raise AppException("Not implemented in stub", 501) → 影響：Users cannot be created via admin panel. POST /admin/users returns 501 error.
- `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:101-109` — async def update_user(...): raise AppException("Not implemented in stub", 501) → 影響：Users cannot be updated via admin panel. PUT /admin/users/{id} returns 501 error.
- `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:111-118` — async def toggle_active(...): return ToggleActiveResponse(user_id=user_id, is_active=False) → 影響：Toggle always returns False, never actually updates DB. User disable/enable does not work.
- `/Users/chun/Desktop/GU_0410/backend/app/services/admin_service.py:120-125` — async def system_health_check(...): return SystemHealthResponse(timestamp=datetime.now(timezone.utc)) → 影響：Health check returns hardcoded 'ok' for all components. Admin cannot see real system status. TODO comment says 'TODO: 未來接真實的 db SELECT 1 / redis PING / OpenAI client 驗證'.

**缺漏：** Full implementation of user creation (hash password, validate email uniqueness, insert User record, audit log)；Full implementation of user update (fetch, validate fields, update, persist, audit log)；Full implementation of toggle active (fetch user, flip status, persist, log, return updated User)；Real system health checks (DB connection test, Redis PING, OpenAI API connectivity verification)；Audit logging for all admin operations (user create/update/delete/toggle) — currently not in middleware rules；Self-modification check in toggle_active (prevent admin from disabling own account)；Frontend filter UI for audit logs (action, user, date range, IP filters currently disabled)；Email field in UpdateUserRequest schema；Matching service method names in AuditLogService (list_audit_logs, get_audit_log instead of get_list, get_by_id)；Correct response type for toggleUserActive (return User instead of ToggleActiveResponse)；Complaint management role authorization alignment (admin-only or doctor+admin?)


### 通知 (`notifications`) — 完整度 35 / 就緒 no

_The notifications domain has critical wiring failures that prevent core functionality from working. The router calls a non-existent service method (list_notifications instead of get_list), FCMTokenCreate schema field names don't match router usage (device_token vs token), and mark_all_read returns an int but the router expects MarkAllReadResponse object. These are not design issues—they are breaking bugs that will cause runtime AttributeError/TypeError on happy-path calls. Authorization gaps exist (remove_fcm_token doesn't validate ownership). Email integration appears stub-only (no email notifications actually sent on red flags/reports). Missing transaction commits and database consistency issues compound the problems._

**End-to-end 接線：** Partially broken. Frontend->API wiring exists but has critical service-layer breaks: (1) Router calls list_notifications() which doesn't exist (get_list instead), causes AttributeError; (2) FCMTokenCreate.device_token field mismatches router's payload.token access; (3) mark_all_read returns int instead of response object. The remove_fcm_token endpoint lacks authorization checks—any user can delete any other user's FCM token. Email notification flow is completely unwired (no calls to send_email). Push notification retries exist but have no failure handling. Frontend correctly calls API endpoints but backend will fail on list/register/mark-all-read operations.

**已驗證 Critical/High：**

- **[CRITICAL]** `NOTIF-001` — Router calls non-existent service method  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/notifications.py:47` ｜ 驗證：confirmed  
  問題：The list_notifications endpoint calls notification_service.list_notifications(), but the NotificationService class defines the method as get_list(). This will raise AttributeError at runtime on every list request.  
  修法：Rename service method from get_list to list_notifications, OR update router to call get_list(). Also need to handle is_read and notification_type filter parameters that get_list() currently ignores.
- **[CRITICAL]** `NOTIF-002` — FCMTokenCreate schema field mismatch with router  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/notifications.py:108` ｜ 驗證：confirmed  
  問題：Schema defines the field as 'device_token' but router accesses it as 'payload.token'. Will raise AttributeError when registering FCM devices.  
  修法：Either rename schema field to 'token' or update router to use 'payload.device_token'.
- **[CRITICAL]** `NOTIF-003` — mark_all_read returns int but endpoint expects MarkAllReadResponse  
  `/Users/chun/Desktop/GU_0410/backend/app/services/notification_service.py:156-175` ｜ 驗證：confirmed  
  問題：mark_all_read() returns result.rowcount (an int), but the endpoint has response_model=MarkAllReadResponse. Pydantic will fail to serialize the int into the expected MarkAllReadResponse object.  
  修法：Return a MarkAllReadResponse object from mark_all_read service method: `MarkAllReadResponse(updated_count=result.rowcount)`
- **[HIGH]** `NOTIF-004` — Missing authorization check in remove_fcm_token  
  `/Users/chun/Desktop/GU_0410/backend/app/services/notification_service.py:265-276` ｜ 驗證：confirmed  
  問題：remove_fcm_token does not verify that the token belongs to the user before marking it inactive. Any authenticated user can remove any other user's FCM device token by knowing the token string (which may be leaked). Medical PII concern.  
  修法：Add ownership verification: check that FCMDevice.user_id == provided user_id before marking inactive.
- **[HIGH]** `NOTIF-007` — No notification preferences/opt-out mechanism  
  `/Users/chun/Desktop/GU_0410/backend/app/services/notification_service.py:1-315` ｜ 驗證：confirmed  
  問題：No user notification preferences model or service to allow users to opt-out of notification types. Critical for GDPR/privacy compliance in a medical app.  
  修法：Create NotificationPreference model with (user_id, notification_type, enabled_email, enabled_push) and add CRUD endpoints.

**Medium（6）：** NOTIF-008 get_unread_count returns raw int, not UnreadCountResponse；NOTIF-009 List endpoint doesn't support is_read and type filters；NOTIF-010 Email client has no secrets masking in logs；NOTIF-011 No error propagation to frontend for notification failures；NOTIF-012 Redis exception handling swallows all errors silently；NOTIF-013 Celery task retry logic has no dead letter handling

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/services/notification_service.py:47` — notification_service.list_notifications(...) but method is get_list() → 影響：API endpoint /notifications returns AttributeError, feature completely broken
- `/Users/chun/Desktop/GU_0410/backend/app/services/notification_service.py:69-122` — get_list() accepts no filter parameters, doesn't implement is_read or type filtering → 影響：Filtering UI in NotificationPage won't work, query parameters silently ignored
- `/Users/chun/Desktop/GU_0410/backend/app/services/notification_service.py:175` — return result.rowcount (returns int, not MarkAllReadResponse) → 影響：mark_all_read endpoint returns wrong type, Pydantic serialization failure
- `/Users/chun/Desktop/GU_0410/backend/app/services/notification_service.py:265-276` — remove_fcm_token(db, token) doesn't check token ownership → 影響：Any user can unregister any other user's device, authorization bypass

**缺漏：** Email notification delivery (no send_email call in notification creation flow)；User notification preferences/opt-out mechanism；Notification filtering by type and read status (parameters accepted but not implemented)；Dead letter queue for failed push notifications；Error alerting for permanent notification failures；Secrets masking in logs for SENDGRID_API_KEY and SMTP credentials；Tenant/user ownership validation in remove_fcm_token endpoint


### 紅旗偵測與警示 (`red-flag-alerts`) — 完整度 62 / 就緒 partial

_The red-flag detection and alert system is partially functional end-to-end but has critical gaps in error handling, data integrity, and security. The dual-layer detection (rule-based + semantic LLM) is well-designed and i18n-aware, but the acknowledge flow has a broken method signature mismatch that prevents alert acknowledgement from working. Authorization checks are missing—doctors can view all system alerts regardless of ownership. Missing data model fields (action_taken) are requested but never persisted. Error handling is inadequate with swallowed exceptions in the alert creation path. The system lacks integration tests and comprehensive error scenarios._

**End-to-end 接線：** PARTIALLY: Detection → creation works (alert created in DB, pushed to frontend via WS); acknowledge endpoint exists but calls non-matching service method signature. Frontend can call acknowledge API, but backend method signature mismatches (accepts `action_taken` param that doesn't exist in service method). Alert list endpoint returns all system alerts to any authorized doctor, with no tenant/ownership filter.

**已驗證 Critical/High：**

- **[CRITICAL]** `AUTH-1` — Missing doctor ownership filter in alert list query  
  `/Users/chun/Desktop/GU_0410/backend/app/services/alert_service.py:30-101` ｜ 驗證：confirmed  
  問題：The get_list() method returns ALL alerts in the system without filtering by the current doctor's assigned sessions. A doctor at clinic A can see all red flags from clinic B's sessions. In a multi-tenant or multi-doctor scenario, this is a critical breach of patient privacy and data isolation. The method receives no user_id/doctor_id and does not filter by doctor_id on the session FK.  
  修法：Add user_id parameter to get_list(). Filter alerts by session.doctor_id == user_id or (for admins) return all. Frontend auth check via require_role() is insufficient—backend must enforce data isolation.
- **[CRITICAL]** `API-1` — Router passes action_taken parameter that service method doesn't accept  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/alerts.py:160-175` ｜ 驗證：confirmed  
  問題：The acknowledge_alert endpoint (line 160) extracts action_taken from payload (line 168) and passes it to alert_service.acknowledge_alert() (line 174). However, the actual AlertService.acknowledge() method (line 229 in alert_service.py) only accepts db, alert_id, user_id, and notes—it has no action_taken parameter. This will cause a TypeError at runtime when action_taken is passed as a keyword argument.  
  修法：Either: (1) remove action_taken extraction from router (lines 168, 174); (2) add action_taken to RedFlagAlert model and acknowledge() method; or (3) if field is required for audit trail, add it to model and service method. Currently, code will raise TypeError on acknowledge attempt.
- **[HIGH]** `ERROR-1` — Alert creation exception swallowed with bare pass, no user feedback  
  `/Users/chun/Desktop/GU_0410/backend/app/websocket/conversation_handler.py:1206-1224` ｜ 驗證：confirmed  
  問題：When AlertService.create() fails (line 1187), the exception is caught (line 1206) and logged, but then a placeholder uuid is emitted to the frontend anyway (alert_id = str(uuid.uuid4()), line 1182 set before try block). The frontend receives a fake alert_id, believes the alert was created, but it was never persisted. Later queries for that alert fail silently. No error is sent to the frontend or user.  
  修法：On AlertService.create() failure, send error message to frontend via send_to_session(). Do not emit a fake alert. Add retry logic or inform doctor that alert persistence failed. Log all exceptions at ERROR level, not WARNING.

**Medium（7）：** DATA-1 action_taken schema field defined but never persisted；ERROR-2 AuditLogService.log() failure silently swallowed in alert creation；ERROR-3 Push notification task failure silently discarded；COMPLETENESS-1 No integration test for acknowledge endpoint；COMPLETENESS-2 No test coverage for multi-language red-flag rule coverage fallback；DESIGN-1 Confidence values (rule_hit/semantic_only/uncovered_locale) not visible in frontend UI；MONITORING-1 No observable way to detect if alert creation DB commit succeeded

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/routers/alerts.py:160-175` — action_taken = payload.action_taken if payload else None
...return await alert_service.acknowledge_alert(
    db,
    alert_id=alert_id,
    acknowledged_by=current_user.id,
    acknowledge_notes=acknowledge_notes,
    action_taken=action_taken,
) → 影響：CRITICAL: Will raise TypeError at runtime when user tries to acknowledge an alert. The service method does not accept action_taken parameter.
- `/Users/chun/Desktop/GU_0410/backend/app/services/alert_service.py:222-224` — except Exception:
    # 推播失敗不應影響警示建立
    pass → 影響：MEDIUM: Silent failure of push notification task. Critical red-flag alerts may not reach doctor. No logging, no retry, no fallback.
- `/Users/chun/Desktop/GU_0410/backend/app/websocket/conversation_handler.py:1206-1211` — except Exception as _e:
    logger.warning("紅旗警示儲存失敗 | session=%s, error=%s", session_id, str(_e))
    try:
        await db.rollback()
    except Exception:
        pass → 影響：HIGH: DB commit failure swallowed. Fake alert_id still emitted to frontend. Alert never persisted but frontend shows it.
- `/Users/chun/Desktop/GU_0410/backend/app/services/alert_service.py:184-190` — except Exception:
    # audit 失敗不應阻擋警示建立,但要 log 以便排查
    import logging
    logging.getLogger(__name__).warning(
        "uncovered_locale escalation audit log failed",
        exc_info=True,
    ) → 影響：MEDIUM: Audit log for uncovered_locale escalation (i18n coverage failure) is lost. Should fail-safe escalate or retry.

**缺漏：** Doctor-scoped alert listing (alerts filtered by current doctor's sessions only)；Action_taken field persistence in acknowledge flow (schema defined but no DB column)；Frontend UI display of alert confidence level (rule_hit vs semantic_only vs uncovered_locale)；Integration test for acknowledge endpoint end-to-end；Integration test for multi-language uncovered_locale escalation flow；Explicit error messaging to frontend when alert creation fails；Metrics/instrumentation for DB commit failures in alert creation；Frontend canonical_id field in RedFlagAlert type；Regex complexity validation/rate-limiting for rule patterns；Acknowledgement error handling—no test for 'already acknowledged' exception path


### 報告 (`reports`) — 完整度 62 / 就緒 partial

_The Reports feature achieves the core flow end-to-end (report generation, review, retrieval) with solid async queue handling and revision audit trails. However, it has critical gaps: (1) no ownership/access control verification despite medical PII, (2) schema mismatch on POST /generate endpoint returning SOAPReport instead of GenerateReportResponse, (3) date filtering parameters accepted but never used, (4) unused `additional_notes` parameter in generation request, and (5) missing error handling for edge cases like failed Celery tasks. The backend correctly handles role-based access for review/PDF export (doctor/admin only), but patient/session ownership is never validated in list or detail endpoints._

**End-to-end 接線：** Backend API is wired end-to-end: frontend triggers reportStore.generateReport() → calls POST /sessions/{sessionId}/reports/generate → ReportService.generate_report() queues Celery task → _async_generate() calls SOAPGenerator → updates SOAPReport → frontend polls GET /reports/{id} → ReportService.get_report() returns report. However, the ownership verification is missing on the GET side, and schema mismatches on POST and PUT endpoints mean FastAPI serialization will fail or return wrong shape to frontend. Review flow (frontend → PUT /reports/{id}/review → service → update DB) is wired but also has schema mismatch and no ownership check.

**已驗證 Critical/High：**

- **[CRITICAL]** `REPORTS-1` — Missing ownership/access control on report retrieval (CRITICAL for medical PII)  
  `/Users/chun/Desktop/GU_0410/backend/app/services/report_service.py:163-180` ｜ 驗證：confirmed  
  問題：get_report() accepts current_user but never validates ownership. A patient could access any report by ID, or a doctor could access reports they didn't review. The docstring claims '病患僅可查看自己的報告' (patients can only view own reports) but the code has zero enforcement.  
  修法：Query session.patient_id and validate current_user.id == session.patient_id for patients, or current_user.role in [DOCTOR, ADMIN] for doctors. Same for list_reports() which advertises patient filtering but never actually restricts the query.
- **[HIGH]** `REPORTS-2` — Schema type mismatch on POST /reports/generate endpoint  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/reports.py:93-119` ｜ 驗證：confirmed  
  問題：Endpoint declares response_model=GenerateReportResponse (with fields: report_id, session_id, status, message) but ReportService.generate_report() returns SOAPReport (with 50+ fields: subjective, objective, assessment, plan, icd10_codes, etc.). FastAPI will serialize the SOAPReport into GenerateReportResponse schema, silently dropping most fields and potentially failing if report.id doesn't map to report_id.  
  修法：Either: (a) Change response_model=SOAPReportResponse, or (b) Update service to return a dict matching GenerateReportResponse schema. Frontend expects SOAPReport structure per reportStore.ts:206 set({selectedReport: report}), so option (a) is safer.
- **[HIGH]** `REPORTS-7` — Role-based access control missing on list_reports and get_report endpoints  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/reports.py:34-88` ｜ 驗證：confirmed  
  問題：list_reports() and get_report() have no role check—patients and doctors both have access. The code tries to enforce ownership in the service layer (current_user parameter) but the service never checks role or ownership, so both endpoints are fully open.  
  修法：Either: (a) add dependencies=[Depends(require_role('doctor', 'admin'))] to both GET endpoints if reports are doctor-only, or (b) implement row-level filtering in service based on current_user.role (patients see only own reports, doctors see all or assigned reviews).
- **[HIGH]** `REPORTS-10` — PDF export endpoint lacks ownership check despite role-based access  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/reports.py:183-210` ｜ 驗證：confirmed  
  問題：export_report_pdf() requires doctor/admin role but does NOT validate that the doctor reviewing/exporting the report is the one assigned to it. A doctor could export any report for any patient. Combined with missing get_report ownership check, a logged-in doctor has unrestricted read access to all patient data via PDF endpoint.  
  修法：In export_pdf() service method, after fetching the report, verify the report belongs to the current user's scope (e.g., if doctor: report.reviewed_by == current_user.id or allow export of unreviewed reports only if assigned to current doctor).

**Medium（6）：** REPORTS-3 Unused parameters in generate_report (additional_notes, include_transcript in PDF export)；REPORTS-4 Date filtering parameters accepted but never applied in list_reports()；REPORTS-5 No monitoring of Celery task failure or retry logic visibility；REPORTS-6 No validation that session is in 'completed' state before generating report；REPORTS-9 ReviewReportResponse schema mismatch: endpoint returns full SOAPReport instead of declared schema；REPORTS-11 Celery task does not validate report record exists before writing

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/services/report_service.py:92, 183-188` — additional_notes: Optional[str] = None ... # parameter accepted but never used → 影響：API signature declares this parameter but it's never stored, logged, or passed to Celery. Clients may expect notes to be persisted; feature is half-implemented.
- `/Users/chun/Desktop/GU_0410/backend/app/services/report_service.py:94-95` — date_from: Optional[str] = None, date_to: Optional[str] = None, ... # parameters accepted but never used in query → 影響：Clients may attempt date filtering but queries ignore the parameters. Users cannot filter reports by date range.
- `/Users/chun/Desktop/GU_0410/backend/app/services/report_service.py:356` — include_transcript: bool = False, ... # parameter accepted but never used in _build_report_html() → 影響：PDF export always excludes transcript regardless of parameter. Feature is half-wired.

**缺漏：** Patient-scoped access control on report listing and retrieval (critical for medical data isolation)；Validation that session is in 'completed' state before report generation；Failed Celery task handling: no mechanism to mark reports as FAILED or retry notification；Monitoring/observability for stalled report generation (reports stuck in 'generating' state)；API documentation or contract tests for schema mismatch on POST /generate and PUT /review endpoints；Implementation of date range filtering in list_reports；Implementation of include_transcript in PDF export；Implementation of additional_notes in report generation；Idempotency key or duplicate guard for report regeneration (two requests could create duplicate jobs)；Rate limiting on report generation (no throttle per user/session)


### 認證與安全 (`auth-security`) — 完整度 72 / 就緒 partial

_The Auth & Security domain has solid foundational architecture with RS256 JWT, bcrypt password hashing, Redis-based token blacklist, rate limiting, and comprehensive refresh token rotation + reuse detection. However, there are critical data-type bugs in the password reset flow, a missing reset-password frontend page, and incomplete role-enforcement on user creation that prevent full production readiness. Email delivery for forgot-password is graceful but unverified. The WebSocket auth handshake is well-implemented with proper timeout handling._

**End-to-end 接線：** Login/register/logout/refresh flows are complete E2E. Password reset backend is wired but lacks the frontend UI page to complete the user-facing flow. WebSocket auth is complete. Email delivery for forgot-password is present but relies on external SMTP/SendGrid integration which could be misconfigured at deployment.

**已驗證 Critical/High：**

- **[HIGH]** `AUTH-2` — Missing frontend Reset Password page  
  `/Users/chun/Desktop/GU_0410/frontend/src/screens/auth/:N/A` ｜ 驗證：confirmed  
  問題：The backend `/auth/reset-password` endpoint exists and is fully functional, but the frontend lacks the UI page where users can enter the reset token and new password. Only ForgotPasswordPage, LoginPage, RegisterPage exist. Users cannot complete password recovery flow from the UI.  
  修法：Create /Users/chun/Desktop/GU_0410/frontend/src/screens/auth/ResetPasswordPage.tsx that accepts token from query param (e.g. /reset-password?token=abc123) and calls authApi.resetPassword(token, password).
- **[HIGH]** `AUTH-3` — Role enforcement not enforced during user registration  
  `/Users/chun/Desktop/GU_0410/backend/app/services/auth_service.py:178-213` ｜ 驗證：confirmed  
  問題：RegisterRequest includes a `role` field (line 45 in schemas/auth.py defaults to PATIENT) but does not validate that non-patient roles (DOCTOR, ADMIN) require proper authorization. The schema allows `role: UserRole` but the docstring says 'medical and admin accounts must be created by admin'. No code enforces this restriction.  
  修法：In auth_service.register(), add check: if data.role != UserRole.PATIENT and (current_user is None or current_user.role != UserRole.ADMIN), raise ForbiddenException(). Or remove role from RegisterRequest entirely and default all new registrations to PATIENT.

**Medium（5）：** AUTH-1 UUID type conversion missing in reset_password；AUTH-4 Forgot-password endpoint lacks rate limiting；AUTH-5 Email delivery failure swallowed silently in forgot_password；AUTH-7 Refresh token reuse detection may not catch certain race conditions；AUTH-10 WebSocket token validation does not check token blacklist

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/services/auth_service.py:47` — # refresh token rotation 登記表 key 前綴
# 每發一張 refresh token，就寫一筆 gu:refresh:{user_id}:{jti} = "1"，TTL = token exp
# refresh 時必須先 atomic 刪除舊 jti；刪不到就視為 replay，撤銷該 user 所有 refresh token → 影響：Not a stub—this is design documentation and is fully implemented via _refresh_key, _register_refresh_token, _consume_refresh_jti functions.

**缺漏：** Frontend ResetPasswordPage.tsx to allow users to complete password recovery flow；Rate limiting on forgot_password endpoint to prevent email enumeration/spam；Blacklist check in WebSocket auth handshake to invalidate logged-out tokens；Email delivery success signal/verification in forgot_password flow；Configurable reset password token TTL (currently hardcoded to 30 minutes)


### 場次與 LLM 對話 (`sessions-conversation`) — 完整度 72 / 就緒 partial

_The sessions & LLM conversation domain has strong foundational architecture (proper state machine, transaction safety with advisory locks, end-to-end encryption of critical paths), but has critical gaps in production readiness: (1) the reconnect API endpoint exists but has NO frontend caller, leaving users without recovery after network interruption; (2) missing supervisor API binding on frontend for dynamic next_focus guidance display; (3) Supervisor analysis runs fully async with NO feedback to patient about completion status or fallback on timeout. Error handling is sound with proper localization, message ordering is protected by sequence_number + advisory locks, and authorization checks are comprehensive for tenant isolation._

**End-to-end 接線：** Mostly yes, but critically incomplete on reconnection path. WebSocket conversation flow (audio → STT → LLM → TTS → red flags) is fully wired from frontend hook through backend handler to database persistence. Session CRUD endpoints are fully wired with proper state machine enforcement. However: (1) POST /api/v1/sessions/{id}/reconnect endpoint exists (backend lines 198-251) but NO frontend API client method exists to call it (frontend sessions.ts lines 1-74 missing reconnectSession function). Frontend WebSocket manager has reconnect logic but doesn't consume the reconnect state API. (2) Supervisor guidance (supervisor.py analyze_next_step) stores results in Redis, but frontend has no store binding to read/display missing_hpi or dynamic next_focus to the conversation UI.

**已驗證 Critical/High：**

- **[HIGH]** `CONV-1` — Missing Frontend Reconnect API Client  
  `frontend/src/services/api/sessions.ts:1-74` ｜ 驗證：confirmed  
  問題：Backend endpoint POST /sessions/{id}/reconnect exists and returns conversation history + checksum, but frontend has no API client function to call it. When WebSocket reconnects after network failure, the frontend cannot fetch recovery state to validate resumeFrom token and prevent duplicate message ingestion.  
  修法：Add reconnectSession function to frontend/src/services/api/sessions.ts; call it in useConversationWebSocket hook before reconnect attempt; pass returned checksum as resumeFrom query param to WebSocket URL.
- **[HIGH]** `CONV-2` — No Frontend UI Binding for Supervisor Guidance  
  `frontend/src/stores/conversationStore.ts:1-178` ｜ 驗證：confirmed  
  問題：Backend Supervisor engine analyzes conversation every turn and writes next_focus + missing_hpi to Redis, but frontend conversationStore has no state fields to store or display this guidance. Patient sees no indication of what HPI dimensions the doctor expects next, breaking the feedback loop promised in backend (pipeline/supervisor.py line 6-7: 'produce next_focus guidance for dynamic readout').  
  修法：Add supervisorGuidance, missingHpi, hpiCompletionPercentage to ConversationState; extend useConversationWebSocket to fetch and display guidance; emit supervisor_guidance event from WebSocket manager.
- **[HIGH]** `CONV-3` — Supervisor Timeout Has Silent Fallback Without User Notification  
  `backend/app/websocket/conversation_handler.py:1095-1143` ｜ 驗證：confirmed  
  問題：If Supervisor.analyze_next_step exceeds 30-second timeout, backend writes generic fallback guidance ('supervisor unavailable, continuing with default guidance') to Redis without notifying the patient or LLM that guidance quality has degraded. This means the AI may miss critical HPI dimensions without any visible warning, and the patient is unaware supervision is partially disabled.  
  修法：Send explicit session_status/warning event to patient when supervisor times out; set supervisor_reliability flag in session context; log as high-priority error for monitoring.
- **[HIGH]** `CONV-4` — Conversation History Compression May Silently Lose Critical HPI Data  
  `backend/app/websocket/conversation_handler.py:150-207` ｜ 驗證：confirmed  
  問題：When conversation_history exceeds 50 turns, oldest segments are summarized by gpt-4o-mini and replaced with a single [front segment summary] system message. If summarization fails, old turns are silently discarded entirely (line 205-206: '若摘要失敗且沒有既有摘要：硬丟棄舊輪次'), potentially losing critical red-flag context or HPI details that the LLM and Supervisor need to make correct decisions.  
  修法：On summary failure, either: (a) keep original history unsummarized (trades token cost for safety); (b) explicitly mark summary failure in system message so LLM/Supervisor know context is incomplete; (c) reject the turn and ask patient to repeat.

**Medium（4）：** CONV-5 Session State Mismatch Between DB and Redis；CONV-6 STT Confidence and Audio Duration Not Persisted for Patient Responses；CONV-7 Red Flag Alert Persistence Doesn't Record Which Turn It Occurred In；CONV-8 Session Timeout Task Uses Outdated Timestamp Logic

**真實 stub / 半接功能：**
- `backend/app/websocket/conversation_handler.py:1198-1199` — # TODO-E6 / TODO-M8：把 canonical_id + confidence 穿到 DB, supply serializer 按 Accept-Language 渲染、前端 banner 呈現信心層級。 → 影響：Red flag alert confidence scores (e.g., 'rule_hit' vs 'semantic_inference') are not being persisted to the database, preventing analysis of alert quality or doctor-side confidence filtering.
- `frontend/src/screens/patient/ConversationPage.tsx:433` — // TODO-E2：canonical code payload；code/params 渲染走 i18n → 影響：Session status change events sometimes use 'status' field, sometimes 'code' field, making frontend error handling inconsistent. i18n fallback relies on default values rather than structured canonical codes.
- `frontend/src/screens/patient/ConversationPage.tsx:455` — // TODO-E2：canonical code payload → 影響：WebSocket error payloads use code/params but fallback to generic error string, inconsistent with canonical i18n error handling in other parts of the app.

**缺漏：** Frontend API client function: reconnectSession(sessionId) to consume POST /sessions/{id}/reconnect；Frontend state binding for supervisor guidance: missing ConversationStore fields for supervisorGuidance, missingHpi, hpiCompletionPercentage；Frontend UI display: HPI progress bar or missing dimensions indicator based on supervisor data；Patient notification on supervisor timeout: no session_status event alerting user that guidance is degraded；Idempotency tokens for audio chunks: no mechanism to prevent duplicate message creation on retry；Explicit language validation in reconnect flow: no check that frontend's Accept-Language matches session.language before WS connect；Separate idle_started_at timestamp: conversation_handler doesn't distinguish between 'actively receiving messages' and 'truly idle'；STT confidence/duration persistence: audio quality metrics from Whisper not stored for patient responses；Alert context metadata: red flag alerts lack turn numbers or full conversation context for doctor navigation


### 音訊 / STT / TTS (`audio-stt-tts`) — 完整度 72 / 就緒 partial

_The audio/STT/TTS domain is mostly complete end-to-end from browser mic capture through WebSocket streaming, STT transcription, and TTS synthesis with bi-directional audio delivery. Core functionality is wired and error handling covers common paths. However, a critical blocker remains: audio lifecycle cleanup (audio_lifecycle.py) only logs deletion instead of actually deleting Supabase Storage blobs—this violates PII retention policies. Additionally, the unused AudioService class with upload_audio/get_audio_url methods suggests incomplete/abandoned storage integration. TTS sentence-level streaming and graceful degradation work well, but some edge cases in timeouts and production observability are underaddressed._

**End-to-end 接線：** The audio pipeline is wired end-to-end for the happy path: browser getUserMedia() → audioStream.ts VAD → WebSocket audio_chunk (base64) → conversation_handler STT → LLM → TTS synthesis → ai_response_chunk (base64 audio) → frontend playback via AudioContext. All major endpoints exist and are called. However, unused code paths (AudioService, TTSPipeline.synthesize_to_url, audio lifecycle cleanup stub) suggest incomplete or abandoned storage integration. The primary delivery mechanism (base64 in-memory) is fully wired; persistent storage is partially wired (code exists but never invoked or only logs). For a HIPAA/compliant medical app, the missing persistent deletion is a blocker that must be resolved before production.

**已驗證 Critical/High：**

- **[CRITICAL]** `AUDIO-1` — Audio lifecycle cleanup stub: _delete_audio_blob only logs instead of deleting  
  `/Users/chun/Desktop/GU_0410/backend/app/tasks/audio_lifecycle.py:132-144` ｜ 驗證：confirmed  
  問題：The _delete_audio_blob() function is marked with TODO and only logs the Supabase Storage URL—it does NOT actually delete audio blobs from storage. Per the product spec, conversations.audio_url blobs older than AUDIO_RETENTION_DAYS (90 days) must be deleted to comply with PII retention policies. The cleanup_old_audio_files Celery task calls this stub, marking DB rows audio_url=NULL but leaving the physical blob in Supabase Storage indefinitely.  
  修法：Implement actual Supabase Storage deletion: parse bucket/path from audio_url, instantiate Supabase client with SERVICE_ROLE_KEY, call storage.from_(bucket).remove([path]). Alternatively, if retention is not enforced, remove the TODO task entirely and audit compliance annually.

**Medium（5）：** AUDIO-2 Unused AudioService with incomplete Supabase integration；AUDIO-3 STT error does not explicitly handle empty recognition result；AUDIO-4 Audio buffer DoS hardening: 10-min limit enforced but no per-chunk timeout on streaming；AUDIO-5 TTS synthesis timeout not explicitly handled in sentence-level streaming；AUDIO-6 MediaRecorder ondataavailable race: chunk from stop() after segment end can pollute next segment

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/tasks/audio_lifecycle.py:136-144` — async def _delete_audio_blob(audio_url: str) -> None:
    """
    實際刪除 blob 的 helper。

    TODO: 整合 Supabase Storage client，解析 bucket/object path 後呼叫
          `storage.from_(bucket).remove([path])`。目前先 log 出來，
          讓工作流程其他部分先上線。
    """
    parsed = urlparse(audio_url)
    logger.info(
        "[audio-delete TODO] host=%s path=%s (Supabase Storage 整合待接)",
        parsed.netloc, parsed.path,
    ) → 影響：CRITICAL: Audio blobs are never actually deleted from Supabase Storage. Conversations marked as 'audio_url=NULL' in DB, but physical files remain indefinitely. Violates PII retention policy (90-day max).
- `/Users/chun/Desktop/GU_0410/backend/app/tasks/audio_lifecycle.py:9` — - 實際刪除動作目前只 log；Supabase Storage 整合尚未拉好，留 TODO。 → 影響：CRITICAL: Design comment confirms stub status. Task runs monthly but produces no actual cleanup.

**缺漏：** Actual Supabase Storage blob deletion in _delete_audio_blob() function (blocking PII retention compliance)；Integration of AudioService.upload_audio() or decision to deprecate it (unused code)；Per-task timeout wrapping for sentence-level TTS synthesis (could block ai_response_chunk stream)；Explicit Supabase required-at-startup check if persistent TTS storage is a product requirement


### SOAP / ICD-10 / 主訴 (`soap-icd10-complaints`) — 完整度 72 / 就緒 partial

_The SOAP/ICD-10/Complaints domain is substantially wired end-to-end with proper data structures, validation pipelines, and i18n support. Core features (SOAP generation, ICD-10 filtering, complaint CRUD) are implemented with good test coverage. However, there are critical security gaps (missing authorization enforcement on complaint update/delete), incomplete urgency handling in the SOAP schema (missing icd10_verified field in the schema layer), and potential race conditions on soft-deletes. The system lacks proper error handling for LLM hallucinations in differential diagnoses._

**End-to-end 接線：** The SOAP generation flow is wired end-to-end: Session/Conversation → Celery task (report_queue.generate_soap_report) → SOAPGenerator.generate() → validate_icd10_codes() → SOAPReport model persistence → API endpoint (GET /api/v1/reports/{id}) → Frontend (reportStore.ts, reports API). Complaint selection is also wired: Frontend SelectComplaintPage → complaintStore.fetchComplaints() → GET /api/v1/complaints → complaintsApi.getComplaints(). SOAP report generation endpoint (/api/v1/sessions/{session_id}/reports/generate) exists and is called from frontend (reports.ts). However, complaint update/delete endpoints lack enforcement of the documented authorization rules (docstring claims "系統預設主訴僅限管理員修改" but service layer does not enforce this).

**已驗證 Critical/High：**

- **[HIGH]** `AUTHZ-1` — Missing authorization enforcement on complaint update/delete  
  `/Users/chun/Desktop/GU_0410/backend/app/services/complaint_service.py:333-351` ｜ 驗證：confirmed  
  問題：The `update_complaint` and `delete_complaint` methods in the service layer accept `current_user` parameter but never use it. The router docstrings claim 'システム予設主訴僅限管理員修改；醫師僅可修改自訂主訴' (system default complaints only admins can edit; doctors can only edit custom ones), but the service does not enforce is_default check or ownership validation. Any authenticated user can modify/delete any complaint.  
  修法：Add authorization checks in the service layer: (1) Check if complaint.is_default; if True, require admin role. (2) If complaint.is_default is False, check complaint.created_by == current_user.id or admin role. Implement this in both update() and delete() static methods.
- **[HIGH]** `ERROR-1` — No error boundary for LLM JSON parse failures in SOAP generation  
  `/Users/chun/Desktop/GU_0410/backend/app/pipelines/soap_generator.py:369-383` ｜ 驗證：confirmed  
  問題：If the LLM returns malformed JSON (despite the response_format constraint), the JSONDecodeError is caught and converted to AIServiceUnavailableException, which is correct. However, if the LLM returns valid JSON but with unexpected structure (e.g., missing 'subjective' or 'assessment' keys), the _validate_and_fill method will create empty dicts/lists for missing keys, but it will NOT validate that differential_diagnoses entries have required 'diagnosis' and 'likelihood' fields. This could result in a malformed report being persisted.  
  修法：Add schema validation using Pydantic after JSON parsing. Create a SOAPReportSchema Pydantic model with nested models for Subjective, Objective, Assessment (including DifferentialDiagnosis with required fields), and Plan. Use parse_obj() after json.loads() to catch structural errors before persistence.

**Medium（4）：** SOAP-1 icd10_verified field missing from SOAPReportDetailResponse schema；SOAP-2 Insufficient reasoning validation in differential_diagnoses；ICD10-1 ICD-10 symptom_id resolution may fail for non-English chief complaints；EDGE-1 Soft-delete of complaints creates orphan sessions

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/routers/complaints.py:141-154` — """更新指定主訴的內容。
    系統預設主訴僅限管理員修改；醫師僅可修改自訂主訴。
    """ → 影響：Docstring promises authorization enforcement (is_default + owner checks) but service layer does not implement these checks. Any authenticated user can modify any complaint.
- `/Users/chun/Desktop/GU_0410/backend/app/routers/complaints.py:160-174` — """軟刪除指定主訴（設定 is_active 為 False）。
    系統預設主訴僅限管理員刪除；醫師僅可刪除自訂主訴。
    """ → 影響：Docstring claims authorization checks but service layer delete() does not validate is_default or ownership. Any authenticated user can soft-delete any complaint.

**缺漏：** Pydantic schema validation for SOAP report structure (post-LLM JSON parse)；Authorization enforcement in complaint update/delete (is_default + owner checks)；icd10_verified field in revision snapshots (audit trail gap)；Cascade logic for soft-deleted complaints (orphan session handling)；English name_en requirement for chief complaints to enable reliable ICD-10 mapping；Differential diagnosis reasoning validation (prevent 'clinically common' placeholders)；Frontend integration of icd10_verified status display in report detail view


### 儀表板與病患 (`dashboard-patients`) — 完整度 72 / 就緒 partial

_The dashboard-patients domain has solid core functionality for patient CRUD, doctor dashboard metrics, queue management, and WebSocket real-time updates. Patient list/detail pages are wired end-to-end with cursor-based pagination, search, and month filtering. However, there are critical gaps: (1) the soft_delete_patient endpoint calls a non-existent method in the service layer, (2) patient detail/session access lacks ownership verification (a doctor can read any patient's data), (3) the list_patients router never passes doctor_id filtering to the service despite the service supporting it, and (4) the WebSocket dashboard handler doesn't apply doctor_id scoping to queue/alerts/stats queries. Edge cases like empty pagination results and division-by-zero in completion rate calculations are partially handled._

**End-to-end 接線：** Partially wired. Patient list endpoint is fully integrated (API→service→DB→frontend store). Patient detail, session list, and monthly dashboard load data correctly. However: (1) delete endpoint calls undefined soft_delete_patient() method, (2) list_patients router does not pass current_user context or doctor_id to service despite service supporting doctor_id filtering, (3) get_patient / get_patient_sessions lack ownership checks, (4) WebSocket dashboard queries are not scoped to requesting doctor's data, (5) frontend mock mode is enabled via env var but production integration uses real endpoints without fallback.

**已驗證 Critical/High：**

- **[CRITICAL]** `PATIENT-DELETE-1` — soft_delete_patient() method does not exist in service layer  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/patients.py:139-143` ｜ 驗證：confirmed  
  問題：The delete_patient endpoint calls patient_service.soft_delete_patient() which is not defined in PatientService. Only delete() and delete_patient() (alias for delete()) exist. The endpoint will raise AttributeError at runtime when called.  
  修法：Either: (1) Implement soft_delete_patient() in PatientService with is_deleted flag, or (2) Change router to call patient_service.delete_patient(db, patient_id, current_user). Patient model has no is_deleted field, so option (2) is simpler.
- **[HIGH]** `PATIENT-AUTHZ-1` — Missing ownership checks on patient detail and sessions endpoints  
  `/Users/chun/Desktop/GU_0410/backend/app/services/patient_service.py:299-300, 325-327` ｜ 驗證：confirmed  
  問題：The get_patient() and get_patient_sessions() methods accept current_user parameter but do not validate that the patient belongs to the requesting doctor. This allows any doctor to read any other doctor's patients' data and session history.  
  修法：Add ownership check: compare patient.user_id == current_user.id before returning, or check user role (admin can see all). Similar check needed for patient detail and sessions pages.
- **[HIGH]** `PATIENT-AUTHZ-2` — Patient list does not filter by requesting doctor (authorization bypass)  
  `/Users/chun/Desktop/GU_0410/backend/app/routers/patients.py:55-84` ｜ 驗證：confirmed  
  問題：The list_patients() router endpoint accepts current_user but never passes doctor_id to the service. The backend service get_list() method supports doctor_id filtering, but the router does not call it. This means all doctors see all patients in the system regardless of ownership.  
  修法：Extract doctor_id from current_user (if role=='doctor') or allow admin to pass doctor_id query param. Call: patient_service.list_patients(db, doctor_id=current_user.id if current_user.role=='doctor' else None, ...)
- **[HIGH]** `DASHBOARD-WS-AUTHZ-1` — WebSocket dashboard queries not scoped to requesting doctor  
  `/Users/chun/Desktop/GU_0410/backend/app/websocket/dashboard_handler.py:177-220, 252-298, 300-393` ｜ 驗證：confirmed  
  問題：The _get_queue_status(), _get_active_alerts(), and _get_dashboard_stats() functions accept doctor_id but do not filter Session/RedFlagAlert queries by doctor_id except in _get_dashboard_stats (line 317-318, but only for cache key, not the query itself). Any doctor connected to the dashboard WebSocket receives data for all doctors' sessions, alerts, and queue.  
  修法：Apply doctor_id filtering in WebSocket helpers: 'query.where(Session.doctor_id == doctor_id)' and join RedFlagAlert→Session to filter by session.doctor_id. Or refactor to call DashboardService methods which already have scoping.

**Medium（5）：** PATIENT-LIST-FILTER-1 Patient list router ignores gender, age, has_active_session filters；WEBSOCKET-INIT-1 WebSocket initial_state includes doctor-specific cache keys but passes user_id as string；ERROR-HANDLING-1 WebSocket handlers swallow exceptions and return fallback data silently；PATIENT-MODEL-1 Patient model lacks soft-delete field despite delete endpoint implying soft-delete；FRONTEND-MOCK-1 Frontend mock mode enabled via env var, may ship to production

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/routers/patients.py:139` — await patient_service.soft_delete_patient(
    db,
    patient_id=patient_id,
    deleted_by=current_user.id,
) → 影響：Delete patient endpoint will fail with AttributeError('PatientService' object has no attribute 'soft_delete_patient'). Feature is broken on happy path.
- `/Users/chun/Desktop/GU_0410/backend/app/routers/patients.py:71-84` — return await patient_service.list_patients(
    db,
    cursor=cursor,
    limit=limit,
    search=search,
    created_from=created_from,
    created_to=created_to,
    # gender, age_from, age_to, has_active_session never passed
) → 影響：Doctor can see all patients in system (no doctor_id filtering). Major authorization bypass — feature works but is insecure.
- `/Users/chun/Desktop/GU_0410/backend/app/services/patient_service.py:299-306` — async def get_patient(self, db, patient_id, current_user=None):
    return await self.get_by_id(db, patient_id)

async def delete_patient(self, db, patient_id, current_user=None):
    return await self.delete(db, patient_id) → 影響：current_user parameter accepted but never checked. Any doctor can access/delete any patient. Ownership checks are stubs.
- `/Users/chun/Desktop/GU_0410/backend/app/websocket/dashboard_handler.py:177-220, 252-298` — async def _get_queue_status(db, redis):
    waiting_stmt = select(func.count()).select_from(Session).where(Session.status == 'waiting')
    # No doctor_id filter applied

async def _get_active_alerts(db, redis, doctor_id):
    stmt = select(RedFlagAlert).where(RedFlagAlert.acknowledged_at.is_(None))
    # No doctor_id filter despite doctor_id parameter → 影響：WebSocket sends all doctors' queue and alerts to any connected doctor. Confidentiality breach — all query paths return data for all doctors.

**缺漏：** Access control enforcement on patient detail and patient sessions endpoints — no check that patient.user_id == current_user.id；Doctor_id filtering in list_patients router — service supports it but router doesn't pass it；Doctor_id scoping in WebSocket dashboard helpers — _get_queue_status, _get_active_alerts return all-system data；soft_delete_patient implementation in service — endpoint calls undefined method；Patient model soft-delete fields (is_deleted, deleted_at) — model supports hard delete only；Gender, age, has_active_session filtering in patient list — parameters accepted but not implemented；Error signaling to frontend on WebSocket data unavailability — exceptions silently return empty/zero data；Explicit access control for admin role on WebSocket dashboard — currently allows but doesn't specify scoping behavior；Doctor_id filtering in list_patients call from frontend store — could defensively pass filter if available from auth context


### 前端病患/醫師 UX (`frontend-patient-doctor-ui`) — 完整度 78 / 就緒 partial

_The frontend patient and doctor UI is substantially complete with all core journey screens implemented (home, complaint selection, medical info intake, voice conversation, session completion, history, settings). Forms include validation, error handling, and i18n support across 5 languages. Patient voice conversation is fully wired with real-time WebSocket streaming, audio playback, red-flag visualization, and barge-in detection. Doctor settings page is functional. However, there are critical gaps: PatientSettingsPage lacks error feedback on profile save failures (silent catches), sparse accessibility attributes (missing aria-labels on key interactive elements), no loading/success toast notifications in settings, and two unresolved design-tracking TODOs for canonical error code rendering. Chat bubbles correctly support TTS replay and failure indicators. All major API endpoints are properly wired and called._

**End-to-end 接線：** Yes. Patient journey is end-to-end from home → complaint selection (complaint list API) → medical info form (session creation API) → voice conversation (WebSocket) → session complete (report API) → history (session list API). Doctor settings wired to auth.updateMe. All navigation routes properly configured. Form submissions correctly call APIs and redirect. WebSocket payload handling maps all event types to UI state.

**已驗證 Critical/High：**

- **[HIGH]** `SETTINGS-1` — PatientSettingsPage: Silent error on profile save  
  `/Users/chun/Desktop/GU_0410/frontend/src/screens/patient/PatientSettingsPage.tsx:28-38` ｜ 驗證：confirmed  
  問題：The handleSaveProfile function catches errors from updateProfile but never displays them to the user. If the API call fails (e.g., validation error, network failure), the user is left without feedback and the loading state remains false, but no error message appears. The success message is set without checking if the operation actually succeeded.  
  修法：Wrap updateProfile in try-catch, display error message via setMessage on failure, and only show success if status is actually 'success'. Pattern: useAuthStore also shows error state—mirror that in settings page.

**Medium（2）：** A11Y-1 Sparse ARIA labels and roles across patient screens；UX-1 No success/error feedback in settings profile save

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/frontend/src/screens/patient/ConversationPage.tsx:433` — // TODO-E2: canonical code payload; code/params rendering via i18n → 影響：Design-tracking comment only. Code actually implements canonical code rendering via t(data.code, {ns: 'ws', ...}). Implementation is complete and correct, not a real gap.
- `/Users/chun/Desktop/GU_0410/frontend/src/screens/patient/ConversationPage.tsx:455` — // 後端錯誤（TODO-E2: canonical code payload） → 影響：Same as above—design-tracking comment. Error code rendering is already implemented correctly.

**缺漏：** Toast notification system for settings profile save feedback (currently shows plain text message with no timeout)；Error feedback display when profile save fails in PatientSettingsPage；Auto-dismissal timeout for settings save success message；Doctor name/title resolution in PatientSessionDetailPage (currently shows raw doctorId)；Full 5-language support in PatientSettingsPage language dropdown (hardcoded to 2 languages only)；Comprehensive aria-labels on quick-add buttons and remove buttons in medical intake form；Client-side validation to prevent empty medical history/family history rows being added before submission


### 前端骨架與 i18n (`frontend-shell-i18n`) — 完整度 82 / 就緒 partial

_The Frontend Shell, Routing & i18n implementation is well-architected with strong patterns for language handling, authentication routing, and websocket management. Multi-language support is complete with all 5 locales having identical key coverage and proper fallback chains (en-US → zh-TW for beta locales). URL-based language prefix routing is properly guarded and syncs across i18n, localStorage, and HTML lang attribute. However, there is one critical gap: react-hot-toast is used for user notifications (especially language switch feedback) but the Toaster provider is missing from the app tree, preventing toasts from rendering. Additionally, the websocket reconnection logic, while solid with exponential backoff, lacks user-facing feedback beyond internal error state for critical connection failures._

**End-to-end 接線：** The frontend shell routes are fully wired end-to-end: RootNavigator → LanguageLayout (i18n sync) → ProtectedRoute (auth) → RoleGuard (role-based) → MainLayout/PatientLayout → individual pages. Websocket integration is complete (useConversationWebSocket/useDashboardWebSocket hooks → conversationWS/dashboardWS managers → ConversationPage listens for _connected/_disconnected/_reconnecting). Language switching (LanguageSwitcher) integrates with settingsStore, authApi.updateMe for persistence, and conversationStore to detect active sessions. All routes properly guard with ProtectedRoute before RoleGuard, and catch-all routes are protected (no unauthenticated access).

**已驗證 Critical/High：**

- **[HIGH]** `TOAST-1` — Missing react-hot-toast Toaster provider  
  `frontend/src/App.tsx, frontend/src/main.tsx:N/A` ｜ 驗證：confirmed  
  問題：LanguageSwitcher.tsx calls toast.success() and toast.error() to provide user feedback on language switches, but neither App.tsx nor main.tsx includes a <Toaster/> provider from react-hot-toast. Without this provider, the toast notifications will not render.  
  修法：Add <Toaster /> component to App.tsx or main.tsx (typically in a top-level wrapper or directly in App). Import via: import { Toaster } from 'react-hot-toast';

**Medium（1）：** WS-2 Websocket reconnection uses exponential backoff without user feedback

**真實 stub / 半接功能：**
- `frontend/src/services/ws/types.ts:2` — // TODO-E2: WebSocket canonical payload types（TODO-E2） → 影響：Design tracking comment only. No functional code is stubbed. E2E-style code is fully implemented.

**缺漏：** react-hot-toast Toaster provider in app tree (causes toast notifications to fail silently)；Dark mode theme variants on ErrorState and LoadingSpinner components；User-visible retry mechanism for websocket reconnection failures (currently only internal error state)


### 核心基礎設施 (`infra-core`) — 完整度 92 / 就緒 yes

_Core infrastructure and app bootstrap are solid and production-ready. App startup enforces production secrets at runtime, database connection pooling is properly tuned with PgBouncer mitigations (UUID prepared statement names, cache disabling), Redis lifecycle is correctly managed (cache/celery/result dbs separated via indexes), global exception handling with PII redaction is in place, and middleware ordering respects security-first design. Health checks (shallow + deep with 2s timeouts) are properly instrumented. WebSocket lifecycle cleanup (finally blocks, idle watchdog cancellation, disconnection handlers) is complete. Audit logging is fire-and-forget with proper rollback handling. Minor issue: unhandled exception handler leaks str(exc) to API response which may contain PII in edge cases._

**End-to-end 接線：** All core infrastructure is wired end-to-end: app startup → lifespan context manager → Sentry/Firebase/Redis initialization → DB engine creation with proper pooling → middleware stack → exception handlers → health check endpoints. WebSocket endpoints are correctly mounted with proper dependency injection. No missing endpoints or dangling callers detected. All TODOs are tracking codes (e.g. TODO-O2 for metrics i18n tags, TODO-O4 for SLO coverage metrics) with fully functional surrounding code — not actual gaps.

**已驗證 Critical/High：**

- **[HIGH]** `INFRA-1` — Unhandled exception handler leaks exception details to client  
  `/Users/chun/Desktop/GU_0410/backend/app/core/exceptions.py:330` ｜ 驗證：confirmed  
  問題：The global unhandled exception handler includes str(exc) in the API response payload under the details field. This can leak sensitive information (database connection strings, file paths, internal system details) if an unexpected exception occurs during request handling. This bypasses the Sentry PII redaction which only applies to the Sentry event, not to the client-facing response.  
  修法：Replace str(exc) with generic message. Details should only be logged server-side or to Sentry, never returned to client. AppException handler correctly uses exc.details which is under developer control.

**Medium（2）：** INFRA-2 Prometheus /metrics endpoint exposed without authentication；INFRA-3 Redis client initialization has no timeout or graceful fallback

**真實 stub / 半接功能：**
- `/Users/chun/Desktop/GU_0410/backend/app/main.py:133` — # Prometheus metrics (TODO P1-#10 / TODO-O2) → 影響：Tracking code for metrics i18n tagging. Infrastructure is production-ready; TODO is future feature flag implementation.
- `/Users/chun/Desktop/GU_0410/backend/app/core/metrics.py:2` — Prometheus metrics registration + instrumentation (TODO-O2) → 影響：Fully functional metrics infrastructure; TODO-O2 is i18n attribute tagging enhancement.
- `/Users/chun/Desktop/GU_0410/backend/app/core/config.py:230` — ja-JP / ko-KR / vi-VN beta languages awaiting TODO-M1/M2/M13 sign-off → 影響：Three beta languages have complete i18n scaffolding; await clinical content sign-off. Intentional beta state, no broken code.


---

_本報告由 12 域審查 agent + 對抗式驗證 agent + 彙整 agent 產生；critical/high 發現已重讀實際程式碼複核，refuted 項目已剔除。_
