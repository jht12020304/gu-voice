# 左側邊欄與頁面連動問題盤點

## 文件目的

本文件盤點目前前端左側邊欄、相關頁面結構、跳轉關係、連動狀態，以及已確認需要修改的問題。

範圍以 `frontend/src/components/layout/Sidebar.tsx` 對應的醫師端 / 管理員端功能為主，並補充與其直接連動的病患流程、Header 功能與共用路由。

---

## 本輪修正計畫

### 執行順序

1. 修正文檔，將問題盤點轉為可執行修正清單
2. 修正明確斷鏈與錯誤路由
3. 補齊缺失頁面：通知頁、病患詳情頁
4. 統一告警導覽，讓 `AlertDetail` 成為可進入的真實頁面
5. 修補高優先但不需大改後端的功能缺口
6. 執行建置與關鍵流程驗證

### 本輪目標

- 補上 `NotificationsPage`
- 補上 `PatientDetailPage`
- 修正 `/patient/home` 錯誤導向
- 讓 `AlertList` / `Dashboard` 可進入 `AlertDetail`
- 讓 `AlertDetail` 接真實 API 並可執行確認處理
- 將病患病史表單升級為正式 `session intake schema`
- 修正 `ReportList` 在真實模式顯示 `sessionId` 的問題
- 將管理端可直接接 API 的頁面從 mock 提升為真實資料頁

### 驗證方式

- 執行前端 build，確認 TypeScript / bundling 通過
- 檢查新增 route 是否都有對應頁面
- 檢查主要跳轉是否落到存在路徑
- 將本輪完成 / 未完成項目回寫到本文件

---

## 一、目前左側邊欄功能結構

### 醫師 / 管理員共用

- `儀表板` → `/dashboard`
- `病患列表` → `/patients`
- `問診場次` → `/sessions`
- `SOAP 報告` → `/reports`
- `紅旗警示` → `/alerts`
- `體驗對話流程` → `/patient`
- `設定` → `/settings`

### 僅管理員可見

- `使用者管理` → `/admin/users`
- `主訴模版管理` → `/admin/complaints`
- `系統狀態` → `/admin/health`
- `稽核日誌` → `/admin/audit-logs`

---

## 二、目前主要頁面鏈路

### 1. 醫師主工作流

- `儀表板`
- `問診場次`
- `場次詳情`
- `SOAP 報告`
- `對話頁`

目前狀態：

- 這條鏈路大致可用。
- `Dashboard -> SessionDetail`
- `SessionList -> SessionDetail`
- `SessionDetail -> SOAPReport`
- `SessionDetail -> Conversation`

### 2. 告警監控流

- `儀表板 / 紅旗警示`
- `紅旗警示列表`
- `場次詳情`
- `警示詳情（理論上存在）`

目前狀態：

- `Dashboard` 與 `AlertList` 都會導去 `SessionDetail`
- `AlertDetail` 雖然有路由，但主流程沒有真正導進去

### 3. 病患體驗流

- `體驗對話流程`
- `選擇症狀`
- `填寫病史`
- `問診對話`
- `完成頁 / 歷史紀錄`

目前狀態：

- 這條路由鏈最完整
- 但病史資料沒有完整提交到後端

---

## 三、已確認問題清單

以下問題都屬於建議修正項目。

### P1. `病患列表 -> 病患詳情` 鏈路中斷

狀態：已修正

現況：

- `PatientListPage` 點擊病患列會跳到 `/patients/:id`
- 但 `RootNavigator` 中沒有 `Route path="/patients/:patientId"` 或等價病患詳情頁
- 實際上會落入 `*` fallback，再被重導到 `/dashboard`

影響：

- 左側邊欄中的 `病患列表` 無法完成「列表 -> 個案詳情」的基本流程

建議修改：

- 補上病患詳情頁路由與頁面
- 或先改成暫時不可點，避免假入口

相關程式碼：

- [frontend/src/screens/doctor/PatientListPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/doctor/PatientListPage.tsx:103)
- [frontend/src/navigation/RootNavigator.tsx](/Users/chun/Desktop/GU_0410/frontend/src/navigation/RootNavigator.tsx:132)

### P2. Header `通知` 按鈕有跳轉，但沒有對應頁面

狀態：已修正

現況：

- Header 鈴鐺按鈕會跳到 `/notifications`
- 有 `notificationStore`
- 有 `notifications` API service
- 但沒有 `NotificationsPage`，也沒有對應 route

影響：

- Header 右上角功能是斷的
- 使用者點擊後會被 fallback 導回首頁邏輯

建議修改：

- 補 `NotificationsPage` 與 route
- 若暫時不做，先移除按鈕或禁用跳轉

相關程式碼：

- [frontend/src/components/layout/Header.tsx](/Users/chun/Desktop/GU_0410/frontend/src/components/layout/Header.tsx:69)
- [frontend/src/stores/notificationStore.ts](/Users/chun/Desktop/GU_0410/frontend/src/stores/notificationStore.ts:1)
- [frontend/src/navigation/RootNavigator.tsx](/Users/chun/Desktop/GU_0410/frontend/src/navigation/RootNavigator.tsx:131)

### P3. `AlertDetail` 路由存在，但主流程沒有導入

狀態：已修正

現況：

- 路由有 `/alerts/:alertId`
- 但 `Dashboard` 右側紅旗卡片與 `AlertListPage` 都是跳去 `/sessions/:sessionId`
- 使用者幾乎無法從正常流程進入 `AlertDetail`

影響：

- `AlertDetailPage` 變成資訊架構中的孤島頁
- 既有頁面與詳細頁之間沒有一致的導覽策略

建議修改：

- 明確決定告警的主詳情頁應該是 `AlertDetail` 還是 `SessionDetail`
- 若保留 `AlertDetail`，列表與 dashboard 應提供一致入口

相關程式碼：

- [frontend/src/screens/doctor/AlertListPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/doctor/AlertListPage.tsx:67)
- [frontend/src/screens/doctor/DashboardPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/doctor/DashboardPage.tsx:209)
- [frontend/src/navigation/RootNavigator.tsx](/Users/chun/Desktop/GU_0410/frontend/src/navigation/RootNavigator.tsx:138)

### P4. `AlertDetailPage` 本身仍是 mock，且內部連結不完整

狀態：已修正

現況：

- `AlertDetailPage` 使用 `useParams()` 取 `alertId`，但內容完全是 `mockAlert`
- 「影響病患」只連回 `/patients` 列表，不是對應病患
- 「標示為已處理」「誤報忽略」按鈕沒有事件處理

影響：

- 告警詳情頁即使能打開，也不是實際資料頁
- 與列表頁可 `acknowledgeAlert` 的行為不一致

建議修改：

- 接入 alerts API 取得單一 alert detail
- 讓處理動作與 `alertStore` 行為一致
- 補病患詳情頁後，病患連結改成個案詳情

相關程式碼：

- [frontend/src/screens/doctor/AlertDetailPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/doctor/AlertDetailPage.tsx:8)
- [frontend/src/screens/doctor/AlertDetailPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/doctor/AlertDetailPage.tsx:107)
- [frontend/src/screens/doctor/AlertDetailPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/doctor/AlertDetailPage.tsx:123)

### P5. 病患病史表單沒有完整寫入後端

狀態：已修正

原始現況：

- `MedicalInfoPage` 蒐集了過敏史、用藥史、過去病史、家族史
- 但送出時只呼叫 `sessionsApi.createSession`
- 實際 payload 只有：
  - `patientId`
  - `chiefComplaintId`
  - `chiefComplaintText`
  - `language`

影響：

- UI 上看起來有完整問診前資料收集
- 但實際資料沒有被建立在 session 或其他後端實體上
- 容易造成使用者與醫師誤解，以為這些資料已被系統保存

建議修改：

- 與後端確認病史資料要掛在哪個實體
- 擴充 `createSession` payload 或另開 pre-intake API
- 在未完成前，需避免 UI 傳達「已保存」的錯誤預期

本輪實作：

- 後端 `sessions` 新增正式 `intake_data` 與 `intake_completed_at`
- `SessionCreate` 擴充為可接收結構化 `intake`
- `MedicalInfoPage` 改為建立 session 時直接送出：
  - `noKnownAllergies`
  - `allergies`
  - `noCurrentMedications`
  - `currentMedications`
  - `noPastMedicalHistory`
  - `medicalHistory`
  - `familyHistory`
- websocket 問診上下文與 SOAP 生成也會優先讀取本次 session intake，而非覆寫病患長期 profile

相關程式碼：

- [frontend/src/screens/patient/MedicalInfoPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/patient/MedicalInfoPage.tsx:154)
- [frontend/src/services/api/sessions.ts](/Users/chun/Desktop/GU_0410/frontend/src/services/api/sessions.ts:20)
- [backend/app/schemas/session.py](/Users/chun/Desktop/GU_0410/backend/app/schemas/session.py:16)
- [backend/app/models/session.py](/Users/chun/Desktop/GU_0410/backend/app/models/session.py:23)
- [backend/app/websocket/conversation_handler.py](/Users/chun/Desktop/GU_0410/backend/app/websocket/conversation_handler.py:883)

### P6. 管理端 3 個頁面仍是純 mock / 靜態骨架

狀態：已修正

頁面如下：

- `主訴模版管理`
- `系統狀態`
- `稽核日誌`

現況：

- 這 3 頁直接在 component 中內嵌 mock data
- 沒有 store
- 沒有 API
- 主要按鈕沒有實際行為

影響：

- 左側邊欄看起來完整，但管理端能力實際尚未接線
- 容易讓使用者誤判為可用功能

建議修改：

- 若要短期上線，需標註為 beta / 即將推出
- 中期應補對應 API、store、頁面互動

相關程式碼：

- [frontend/src/screens/admin/ComplaintManagementPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/admin/ComplaintManagementPage.tsx:7)
- [frontend/src/screens/admin/SystemHealthPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/admin/SystemHealthPage.tsx:4)
- [frontend/src/screens/admin/AuditLogsPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/admin/AuditLogsPage.tsx:7)

### P7. `SOAP 報告列表` 在真實模式下顯示資訊不足

狀態：已修正

現況：

- `ReportListPage` 在 mock 模式會顯示病患姓名
- 真實模式下標題 fallback 成 `report.sessionId`

影響：

- 報告列表辨識性不足
- 醫師在列表上很難快速辨認病患

建議修改：

- 報表列表 API 增加病患名稱 / session.patient.name
- 或前端補做 session 關聯資料取得

相關程式碼：

- [frontend/src/screens/doctor/ReportListPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/doctor/ReportListPage.tsx:94)

### P8. `useAuth` 仍保留舊路由 `/patient/home`

狀態：已修正

現況：

- `useAuth` 在 patient 登入成功後會 `navigate('/patient/home')`
- 但實際路由只有 `/patient`

影響：

- 若任何地方實際使用這個 hook 的 `login()`，病患登入後會跳到不存在的路徑

建議修改：

- 將 `/patient/home` 統一改為 `/patient`

相關程式碼：

- [frontend/src/hooks/useAuth.ts](/Users/chun/Desktop/GU_0410/frontend/src/hooks/useAuth.ts:23)
- [frontend/src/navigation/RootNavigator.tsx](/Users/chun/Desktop/GU_0410/frontend/src/navigation/RootNavigator.tsx:115)

### P9. 病患歷史詳情頁仍是純 mock

狀態：已修正

現況：

- `PatientSessionDetailPage` 只讀 `sessionId`
- 頁面內容完全使用 `mockSession`
- 沒有 API、沒有 store

影響：

- 病患端歷史列表雖然有詳情頁路由
- 但內容不是實際 session 資料

建議修改：

- 接入病患可讀的 session detail API
- 或至少顯示從歷史列表傳入的真實資料

相關程式碼：

- [frontend/src/screens/patient/PatientSessionDetailPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/patient/PatientSessionDetailPage.tsx:7)

### P10. 病患端 `PatientSettingsPage` 仍偏向靜態頁

狀態：部分修正

現況：

- 可切 tab、可編輯部分欄位
- 但沒有 API 寫回
- 也沒有和全域設定 store 做完整同步

影響：

- 看起來像可設定頁
- 實際上大多數修改不會持久化

建議修改：

- 明確區分「暫存 UI」和「可保存設定」
- 接入 profile / notification / security API 後再開放保存

本輪實作：

- `profile` 區塊已接入 `updateProfile`
- 語言 / 通知偏好已改用 `settingsStore`
- `security` 區塊仍未接變更密碼 API

相關程式碼：

- [frontend/src/screens/patient/PatientSettingsPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/patient/PatientSettingsPage.tsx:1)

### P11. 註冊頁仍標註為 mock 流程

狀態：已修正

現況：

- `RegisterPage` 內有明確註解：尚未接後端註冊 endpoint
- 目前是 mock successful registration

影響：

- 若專案預期已有完整 auth 流程，這裡會造成真實註冊不可用

建議修改：

- 接上實際後端註冊 API
- 或在 UI 明示目前不開放自行註冊

相關程式碼：

- [frontend/src/screens/auth/RegisterPage.tsx](/Users/chun/Desktop/GU_0410/frontend/src/screens/auth/RegisterPage.tsx:34)

---

## 四、目前判定「已接得比較完整」的鏈路

以下功能雖然仍可能有資料完整度或 mock fallback 問題，但整體流程已具備基本可用性：

- `Dashboard -> SessionDetail`
- `SessionList -> SessionDetail`
- `SessionDetail -> SOAPReport`
- `SessionDetail -> Conversation`
- `PatientHome -> SelectComplaint -> MedicalInfo -> Conversation -> SessionComplete`
- `PatientHome / PatientHistory -> 已完成場次 -> SessionComplete`

---

## 五、建議修正優先順序

### 第一優先

- 補 `PatientDetail` 路由與頁面
- 補 `NotificationsPage` 路由與頁面
- 修正 `useAuth` 的 `/patient/home`
- 決定告警詳情主路徑，統一 `AlertList` / `Dashboard` 行為

### 第二優先

- 讓 `MedicalInfoPage` 真正把病史資料送進後端
- 讓 `AlertDetailPage` 使用真實資料與真實操作
- 補 `ReportListPage` 的病患名稱顯示

### 第三優先

- 將管理端 mock 頁面逐步接 API
- 將病患端 `PatientSessionDetailPage`、`PatientSettingsPage` 從 mock 升級為真實頁
- 補齊註冊流程

---

## 六、漏掃結果

本次已額外檢查：

- 所有 `RootNavigator` route
- `Sidebar`、`Header`、`PatientLayout` 的主要入口
- 主要 `navigate()` / `Link` / `NavLink` 跳轉
- 主要 screen 中的 `IS_MOCK` / mock data / TODO / 靜默失敗

### 本輪補抓到的遺漏項

- `useAuth` 仍導向不存在的 `/patient/home`
- `PatientSessionDetailPage` 仍是純 mock
- `PatientSettingsPage` 仍未接持久化
- `RegisterPage` 仍是 mock 註冊流程

### 目前結論

截至本輪修正與複查，沒有再看到比上述更明顯、且與左側結構直接相關的遺漏項。

---

## 七、本輪完成項目

- 新增 `NotificationsPage` 並補上 `/notifications` route
- 新增 `PatientDetailPage` 並補上 `/patients/:patientId` route
- 修正 `useAuth` 導向 `/patient/home` 的錯誤路由
- 將 `AlertList` 與 `Dashboard` 的告警卡點擊改為進入 `AlertDetail`
- 將 `AlertDetailPage` 改為真實 API 頁面，並補上確認處理動作
- 在 `MedicalInfoPage` 送出前回寫病患過敏史 / 用藥 / 病史
- 修正 `ReportListPage` 真實模式下病患名稱顯示
- 將 `SystemHealthPage`、`AuditLogsPage`、`ComplaintManagementPage` 接上 API
- 將 `PatientSessionDetailPage` 改為真實資料頁
- 將 `RegisterPage` 改為使用實際註冊 API
- 將 `PatientSettingsPage` 的個人資料與偏好設定接上 store / profile update

## 八、本輪驗證

- 已執行 `frontend` 的 `npm run build`
- 結果：通過
- 驗證時間點：本輪修正完成後

## 九、剩餘風險

- 病史資料目前是透過 `updatePatient` 回寫，屬於前端可落地補法；若未來後端新增正式 intake / pre-session schema，需要再調整資料結構
- `PatientSettingsPage` 的帳號安全區塊仍未接變更密碼 API

若下一步要進入修改，建議先從：

1. `PatientDetail`
2. `NotificationsPage`
3. `Alert` 導覽策略統一
4. `MedicalInfo` 資料提交

開始。
