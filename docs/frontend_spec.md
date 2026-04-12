> **本文件的型別定義、Enum 值、資料模型以 shared_types.md 為準。**

# 泌尿科 AI 語音問診助手 -- 前端規格書

> **專案名稱**: Urology AI Voice Consultation Assistant  
> **版本**: 1.0.0  
> **建立日期**: 2026-04-10  
> **技術棧**: React Native (iOS/Android) + React (Web Dashboard)  
> **狀態管理**: Zustand  
> **導航**: React Navigation (mobile) / React Router (web)  
> **即時通訊**: WebSocket  
> **推播通知**: Firebase Cloud Messaging (FCM)

---

## 目錄

1. [頁面清單與功能描述](#1-頁面清單與功能描述)
2. [元件清單 (Component Inventory)](#2-元件清單-component-inventory)
3. [狀態管理設計 (State Management)](#3-狀態管理設計-state-management)
4. [路由與導航結構 (Navigation Architecture)](#4-路由與導航結構-navigation-architecture)
5. [目錄結構 (Project Structure)](#5-目錄結構-project-structure)
6. [即時通訊設計 (Real-time Communication)](#6-即時通訊設計-real-time-communication)
7. [頁面 Wireframe 描述](#7-頁面-wireframe-描述)
8. [第三方套件清單](#8-第三方套件清單)

---

## 1. 頁面清單與功能描述

### 1.1 共用頁面 (Shared)

#### 1.1.1 登入頁 (Login Screen)

| 項目 | 說明 |
|------|------|
| **Route** | `/login` |
| **角色** | 病患端 / 醫師端 / 管理員端 |
| **說明** | 使用者輸入 Email 與密碼或透過第三方 OAuth 登入。系統依據帳號角色 (role) 自動導向對應首頁。支援「記住我」及生物辨識 (Face ID / Touch ID) 快速登入。 |
| **主要互動** | (a) 輸入 Email 與密碼 (b) 點擊「登入」按鈕送出驗證 (c) 切換「病患登入 / 醫師登入」分頁 (d) 點擊「忘記密碼」進入重設流程 (e) 點擊第三方登入按鈕 (Google / Apple) |

#### 1.1.2 註冊頁 (Registration Screen)

| 項目 | 說明 |
|------|------|
| **Route** | `/register` |
| **角色** | 病患端 / 醫師端 |
| **說明** | 新使用者註冊。病患端需填寫基本資料 (姓名、生日、性別、Email)；醫師端另需填寫醫師證書號碼與所屬院所，由後端審核後啟用帳號。 |
| **主要互動** | (a) 步驟式表單填寫 (Step 1: 基本資料 / Step 2: 驗證 Email OTP / Step 3: 設定密碼) (b) 醫師端額外上傳證書影像 (c) 同意服務條款與隱私政策勾選 |

#### 1.1.3 忘記密碼頁 (Forgot Password Screen)

| 項目 | 說明 |
|------|------|
| **Route** | `/forgot-password` |
| **角色** | 病患端 / 醫師端 |
| **說明** | 使用者輸入註冊 Email，系統寄送 OTP 驗證碼，驗證成功後設定新密碼。對應 API: `POST /api/v1/auth/forgot-password` 及 `POST /api/v1/auth/reset-password`。 |
| **主要互動** | (a) 輸入 Email (b) 接收並輸入 OTP 驗證碼 (c) 設定新密碼並確認 |

#### 1.1.4 啟動畫面 (Splash Screen)

| 項目 | 說明 |
|------|------|
| **Route** | `/` (App 啟動時自動顯示) |
| **角色** | 病患端 / 醫師端 / 管理員端 |
| **說明** | App 開啟時的品牌啟動畫面，同時在背景進行 token 驗證與自動登入檢查。若 token 有效則直接跳轉至首頁，否則導向登入頁。 |
| **主要互動** | 無主動互動，自動轉場 |

---

### 1.2 病患端頁面 (Patient)

#### 1.2.1 主訴選擇頁 (Chief Complaint Selection)

| 項目 | 說明 |
|------|------|
| **Route** | `/patient/complaint-select` |
| **角色** | 病患端 |
| **說明** | 顯示泌尿科常見主訴清單，以分類 chip 方式呈現 (例如：排尿困難、血尿、頻尿、腰痛、性功能障礙等)。病患可點選一個或多個主訴，也可透過搜尋框自行輸入。選定後進入 AI 語音問診對話。 |
| **主要互動** | (a) 瀏覽分類標籤 (泌尿道症狀 / 疼痛 / 性功能 / 其他) (b) 點選主訴 chip (支援多選，最多 5 項) (c) 搜尋框模糊搜尋主訴 (d) 點選「自訂主訴」手動輸入 (e) 點擊「開始問診」按鈕進入語音對話頁 |

#### 1.2.2 語音問診對話頁 (Voice Conversation Screen)

| 項目 | 說明 |
|------|------|
| **Route** | `/patient/conversation/:sessionId` |
| **角色** | 病患端 |
| **說明** | 核心頁面。病患與 AI 進行語音對話。畫面中央為對話記錄 (氣泡式)，底部為麥克風按鈕。AI 以語音 (TTS) 回應問診問題，並以文字同步顯示。支援即時語音辨識 (STT) 將病患語音轉為文字。對話過程中若 AI 偵測到紅旗警示 (Red Flag)，會即時通知醫師端。 |
| **主要互動** | (a) 長按或點擊麥克風按鈕開始/停止錄音 (b) 錄音過程中顯示聲波動畫與錄音時長 (c) 即時顯示 STT 辨識結果 (逐字顯示) (d) 播放 AI 語音回應 (可暫停/重播) (e) 查看對話文字紀錄 (捲動) (f) 點擊「結束問診」完成本次對話 (g) 紅旗警示彈窗顯示 (不可關閉，需確認已知悉) |

#### 1.2.3 問診等候室 (Waiting Room)

| 項目 | 說明 |
|------|------|
| **Route** | `/patient/waiting-room/:sessionId` |
| **角色** | 病患端 |
| **說明** | AI 問診結束後，病患進入等候室等待醫師審閱 SOAP 報告。顯示目前等候狀態 (排隊中 / 醫師審閱中 / 已完成)。可查看問診摘要，或回到歷史記錄。 |
| **主要互動** | (a) 查看等候狀態動畫與預估時間 (b) 查看本次問診摘要 (主訴、AI 產生的初步評估) (c) 收到醫師回覆通知後點擊查看結果 (d) 點擊「返回首頁」離開等候室 |

#### 1.2.4 問診歷史記錄頁 (Conversation History)

| 項目 | 說明 |
|------|------|
| **Route** | `/patient/history` |
| **角色** | 病患端 |
| **說明** | 列出病患所有歷史問診記錄，以卡片形式呈現。每張卡片顯示日期、主訴、問診狀態 (進行中 / 等候中 / 已完成)。可依日期範圍篩選、搜尋。 |
| **主要互動** | (a) 捲動瀏覽歷史記錄列表 (支援下拉刷新與無限捲動) (b) 點擊卡片查看該次問診詳情 (c) 日期範圍篩選器 (d) 搜尋框 (依主訴關鍵字搜尋) |

#### 1.2.5 問診詳情頁 (Conversation Detail)

| 項目 | 說明 |
|------|------|
| **Route** | `/patient/history/:sessionId` |
| **角色** | 病患端 |
| **說明** | 顯示單次問診的完整對話紀錄、AI 產生的問診摘要、醫師批註 (若有)。可重新播放對話錄音。 |
| **主要互動** | (a) 捲動瀏覽完整對話記錄 (b) 點擊播放按鈕重聽錄音片段 (c) 查看醫師批註與建議 (d) 下載 / 分享問診報告 (PDF) |

#### 1.2.6 病患個人設定頁 (Patient Settings)

| 項目 | 說明 |
|------|------|
| **Route** | `/patient/settings` |
| **角色** | 病患端 |
| **說明** | 病患個人資料管理、通知偏好設定、語言選擇、App 版本資訊、登出功能。 |
| **主要互動** | (a) 編輯個人資料 (姓名、生日、聯絡方式) (b) 開啟/關閉推播通知 (c) 選擇語音問診語言 (國語 / 台語 / English) (d) 查看服務條款 / 隱私政策 (e) 登出 |

#### 1.2.7 病患首頁 (Patient Home)

| 項目 | 說明 |
|------|------|
| **Route** | `/patient/home` |
| **角色** | 病患端 |
| **說明** | 病患端主畫面。顯示歡迎訊息、快速開始問診按鈕、近期問診紀錄摘要、系統公告。提供進入主訴選擇與歷史紀錄的快捷入口。 |
| **主要互動** | (a) 點擊「開始問診」大按鈕進入主訴選擇頁 (b) 查看近期問診卡片 (最多 3 筆) (c) 點擊「查看全部」進入歷史記錄 (d) 查看系統公告橫幅 |

---

### 1.3 醫師端頁面 (Doctor)

#### 1.3.1 醫師總覽儀表板 (Doctor Dashboard)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/dashboard` |
| **角色** | 醫師端 |
| **說明** | 醫師登入後的首頁。以統計卡片與圖表呈現今日概覽：今日問診數、等候中病患數、紅旗警示數、已完成審閱數。下方顯示紅旗警示列表 (依緊急程度排序) 與待審閱病患列表。 |
| **主要互動** | (a) 查看統計卡片 (今日問診數 / 等候中 / 紅旗數 / 已完成) (b) 點擊統計卡片跳轉對應列表 (c) 查看紅旗警示快捷列表 (最新 5 筆) (d) 點擊紅旗項目進入警示詳情 (e) 查看待審閱病患列表 (f) 下拉刷新資料 |

#### 1.3.2 病患列表頁 (Patient List)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/patients` |
| **角色** | 醫師端 |
| **說明** | 顯示所有病患清單，支援依狀態篩選 (全部 / 問診中 / 等候中 / 已完成 / 紅旗中止 / 已取消)。每列顯示病患姓名、主訴摘要、問診狀態、等候時間。列表支援搜尋與排序。 |
| **主要互動** | (a) 頂部分頁標籤切換狀態篩選 (b) 搜尋框 (依姓名、主訴搜尋) (c) 排序切換 (依等候時間 / 緊急程度) (d) 點擊病患列進入該病患歷史頁或即時監控頁 (e) 下拉刷新列表 (f) 無限捲動載入更多 |

#### 1.3.3 即時監控頁 (Live Monitoring)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/monitor/:sessionId` |
| **角色** | 醫師端 |
| **說明** | 即時監看特定病患與 AI 的對話過程。畫面以聊天氣泡形式即時更新 (透過 WebSocket 接收)。醫師可觀看但不介入對話。頁面頂部顯示病患基本資訊與主訴，右側 (Web) 或底部 (Mobile) 顯示 AI 即時產生的 SOAP 草稿。紅旗項目以醒目橫幅標示。 |
| **主要互動** | (a) 即時觀看對話串流 (自動捲動至最新訊息) (b) 切換「對話 / SOAP 草稿」檢視 (c) 查看紅旗標記項目 (d) 點擊「介入對話」按鈕 (進階功能，向 AI 傳送指示) (e) 點擊「標記為緊急」提升該對話優先層級 |

#### 1.3.4 SOAP 報告檢視頁 (SOAP Report Viewer)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/report/:sessionId` |
| **角色** | 醫師端 |
| **說明** | 顯示 AI 依據問診對話產生的 SOAP (Subjective, Objective, Assessment, Plan) 報告。每個區塊可展開/收合。醫師可編輯、批註、確認或退回報告。報告包含 AI 信心分數與參考依據。 |
| **主要互動** | (a) 檢視 SOAP 四大區塊內容 (b) 展開/收合各區塊 (c) 點擊「編輯」按鈕修改報告內容 (inline editing) (d) 新增批註 (annotation) 到特定段落 (e) 點擊「確認報告」完成審閱 (f) 點擊「退回修改」要求補充資訊 (g) 點擊「匯出 PDF」下載報告 |

#### 1.3.5 紅旗警示詳情頁 (Red Flag Alert Detail)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/alert/:alertId` |
| **角色** | 醫師端 |
| **說明** | 顯示特定紅旗警示的完整資訊。包含觸發原因 (例如：疑似急性尿滯留、血尿合併發燒)、觸發時間、對應對話片段、AI 建議處置、病患基本資訊。醫師須確認已閱讀並採取行動。 |
| **主要互動** | (a) 查看警示詳細內容與觸發原因 (b) 查看對應的對話片段 (高亮觸發句) (c) 查看 AI 建議處置 (d) 點擊「確認已處理」標記警示為已處理 (e) 點擊「聯繫病患」發起電話或訊息 (f) 點擊「轉介急診」進行緊急轉介流程 (g) 新增處理備註 |

#### 1.3.6 紅旗警示列表頁 (Red Flag Alert List)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/alerts` |
| **角色** | 醫師端 |
| **說明** | 所有紅旗警示的列表。依緊急程度與時間排序。支援篩選 (未處理 / 已處理 / 全部) 與搜尋。未處理警示以紅色背景標記。 |
| **主要互動** | (a) 切換篩選標籤 (未處理 / 已處理 / 全部) (b) 點擊警示項目進入詳情頁 (c) 滑動刪除已處理警示 (d) 批次標記為已處理 |

#### 1.3.7 主訴管理頁 (Complaint Management)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/complaints` |
| **角色** | 醫師端 |
| **說明** | 管理系統中的主訴清單。醫師可新增、編輯、停用主訴項目。每個主訴包含名稱 (中文/英文)、分類、關聯的問診模板。支援拖曳排序。 |
| **主要互動** | (a) 瀏覽主訴清單 (依分類分組) (b) 點擊「新增主訴」開啟表單 Modal (c) 點擊主訴項目進入編輯模式 (d) 切換主訴啟用/停用狀態 (e) 拖曳調整主訴顯示順序 |

#### 1.3.8 病患歷史查詢頁 (Patient History)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/patients/:patientId/history` |
| **角色** | 醫師端 |
| **說明** | 顯示特定病患的所有問診歷史。以時間軸 (timeline) 方式呈現。每筆記錄顯示日期、主訴、問診狀態、SOAP 報告摘要。可展開查看完整報告或對話記錄。 |
| **主要互動** | (a) 瀏覽時間軸上的問診紀錄 (b) 展開/收合各筆紀錄 (c) 點擊「查看完整報告」跳轉 SOAP 報告頁 (d) 點擊「查看對話記錄」跳轉對話詳情 (e) 日期範圍篩選 (f) 匯出病患完整病歷 (PDF) |

#### 1.3.9 醫師設定頁 (Doctor Settings)

| 項目 | 說明 |
|------|------|
| **Route** | `/doctor/settings` |
| **角色** | 醫師端 |
| **說明** | 醫師個人偏好設定。包含個人資料管理、通知偏好 (紅旗警示音效、推播開關)、問診偏好 (預設語言、自動播放語音)、SOAP 報告模板設定、帳號安全 (變更密碼、兩步驟驗證)。 |
| **主要互動** | (a) 編輯個人資料 (姓名、職稱、院所) (b) 設定紅旗通知音效與震動偏好 (c) 設定問診語言偏好 (d) 管理 SOAP 報告模板 (e) 變更密碼 (f) 啟用/停用兩步驟驗證 (g) 登出 |

---

### 1.4 管理員端頁面 (Admin)

#### 1.4.1 使用者管理頁 (User Management)

| 項目 | 說明 |
|------|------|
| **Route** | `/admin/users` |
| **角色** | 管理員端 |
| **說明** | 管理所有系統使用者（病患、醫師、管理員）。支援搜尋、篩選、新增、編輯、停用帳號。可審核醫師註冊申請。 |
| **主要互動** | (a) 瀏覽使用者列表 (b) 搜尋使用者 (依姓名、Email) (c) 依角色篩選 (patient / doctor / admin) (d) 新增/編輯使用者 (e) 停用/啟用帳號 (f) 審核醫師註冊 |

#### 1.4.2 紅旗規則管理頁 (Red Flag Rule Management)

| 項目 | 說明 |
|------|------|
| **Route** | `/admin/red-flag-rules` |
| **角色** | 管理員端 |
| **說明** | 管理系統中的紅旗偵測規則。可新增、編輯、停用規則。每條規則包含名稱、分類、觸發關鍵字、正則表達式、嚴重度、建議處置。 |
| **主要互動** | (a) 瀏覽規則列表 (b) 新增/編輯規則 (c) 切換規則啟用/停用 (d) 設定關鍵字與正則表達式 (e) 設定嚴重度 (critical / high / medium) |

#### 1.4.3 系統健康狀態頁 (System Health)

| 項目 | 說明 |
|------|------|
| **Route** | `/admin/system-health` |
| **角色** | 管理員端 |
| **說明** | 顯示系統健康狀態，包含 API 回應時間、WebSocket 連線數、資料庫連線池狀態、Redis 狀態、AI 服務可用性等監控指標。 |
| **主要互動** | (a) 查看各服務健康狀態 (b) 查看效能指標圖表 (c) 查看錯誤日誌摘要 |

#### 1.4.4 稽核日誌頁 (Audit Logs)

| 項目 | 說明 |
|------|------|
| **Route** | `/admin/audit-logs` |
| **角色** | 管理員端 |
| **說明** | 瀏覽系統稽核日誌。支援依操作類型、使用者、時間範圍篩選。顯示操作者、操作類型、資源、時間、IP 等資訊。 |
| **主要互動** | (a) 瀏覽日誌列表 (b) 依操作類型篩選 (create / read / update / delete / login / logout 等) (c) 依使用者篩選 (d) 日期範圍篩選 (e) 匯出日誌 |

---

## 2. 元件清單 (Component Inventory)

### 2.1 Layout Components (版面配置元件)

#### 2.1.1 `AppHeader`

```typescript
interface AppHeaderProps {
  title: string;
  subtitle?: string;
  showBackButton?: boolean;
  onBackPress?: () => void;
  rightActions?: HeaderAction[];
  variant?: 'default' | 'transparent' | 'colored';
  testID?: string;
}

interface HeaderAction {
  icon: string;
  onPress: () => void;
  badge?: number;
  accessibilityLabel: string;
}
```

**說明**: 通用頂部導航列。支援返回按鈕、標題、右側操作按鈕 (最多 3 個)。`variant` 控制背景風格。

#### 2.1.2 `BottomTabBar`

```typescript
interface BottomTabBarProps {
  tabs: TabItem[];
  activeTab: string;
  onTabPress: (tabKey: string) => void;
  badgeCounts?: Record<string, number>;
}

interface TabItem {
  key: string;
  label: string;
  icon: string;
  activeIcon: string;
}
```

**說明**: 底部分頁導航列。病患端包含：首頁、歷史、設定。醫師端包含：儀表板、病患、警示、設定。管理員端包含：使用者、規則、系統、日誌。支援未讀數字徽章 (badge)。

#### 2.1.3 `SafeAreaContainer`

```typescript
interface SafeAreaContainerProps {
  children: React.ReactNode;
  edges?: ('top' | 'bottom' | 'left' | 'right')[];
  backgroundColor?: string;
  style?: ViewStyle;
}
```

**說明**: 封裝 SafeAreaView，確保內容不會被瀏海或圓角裁切。

#### 2.1.4 `ScreenContainer`

```typescript
interface ScreenContainerProps {
  children: React.ReactNode;
  scrollable?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  keyboardAware?: boolean;
  padding?: 'none' | 'default' | 'compact';
  testID?: string;
}
```

**說明**: 頁面外層容器。整合下拉刷新、鍵盤自動閃避、統一內距。

#### 2.1.5 `SectionHeader`

```typescript
interface SectionHeaderProps {
  title: string;
  actionLabel?: string;
  onActionPress?: () => void;
  count?: number;
}
```

**說明**: 區塊標題元件。右側可帶操作連結 (例如「查看全部」)。

#### 2.1.6 `Divider`

```typescript
interface DividerProps {
  orientation?: 'horizontal' | 'vertical';
  spacing?: number;
  color?: string;
}
```

**說明**: 分隔線元件，用於區分區塊。

---

### 2.2 Form Components (表單元件)

#### 2.2.1 `TextInput`

```typescript
interface TextInputProps {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  error?: string;
  helperText?: string;
  secureTextEntry?: boolean;
  keyboardType?: KeyboardTypeOptions;
  maxLength?: number;
  multiline?: boolean;
  numberOfLines?: number;
  leftIcon?: string;
  rightIcon?: string;
  onRightIconPress?: () => void;
  disabled?: boolean;
  required?: boolean;
  testID?: string;
}
```

**說明**: 通用文字輸入框。支援錯誤訊息、輔助文字、圖示、密碼遮蔽。

#### 2.2.2 `Button`

```typescript
interface ButtonProps {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
  size?: 'small' | 'medium' | 'large';
  loading?: boolean;
  disabled?: boolean;
  leftIcon?: string;
  rightIcon?: string;
  fullWidth?: boolean;
  testID?: string;
}
```

**說明**: 通用按鈕元件。`variant` 控制視覺風格，`loading` 顯示轉圈動畫並禁用點擊。

#### 2.2.3 `OTPInput`

```typescript
interface OTPInputProps {
  length: number;
  value: string;
  onChange: (otp: string) => void;
  error?: string;
  autoFocus?: boolean;
  onComplete?: (otp: string) => void;
}
```

**說明**: OTP 驗證碼輸入元件。每個數字一個獨立輸入格，自動跳轉焦點。

#### 2.2.4 `SearchBar`

```typescript
interface SearchBarProps {
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  onSubmit?: () => void;
  onClear?: () => void;
  autoFocus?: boolean;
  debounceMs?: number;
  testID?: string;
}
```

**說明**: 搜尋列元件。內建搜尋圖示、清除按鈕、支援防抖 (debounce)。

#### 2.2.5 `FilterTabBar`

```typescript
interface FilterTabBarProps {
  tabs: FilterTab[];
  activeTabKey: string;
  onTabPress: (key: string) => void;
  scrollable?: boolean;
}

interface FilterTab {
  key: string;
  label: string;
  count?: number;
}
```

**說明**: 水平篩選分頁列。用於病患列表狀態篩選、警示篩選等場景。

#### 2.2.6 `DateRangePicker`

```typescript
interface DateRangePickerProps {
  startDate: Date | null;
  endDate: Date | null;
  onRangeChange: (start: Date | null, end: Date | null) => void;
  minDate?: Date;
  maxDate?: Date;
  locale?: string;
}
```

**說明**: 日期範圍選擇器。用於歷史記錄篩選。

#### 2.2.7 `Checkbox`

```typescript
interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  disabled?: boolean;
  error?: string;
}
```

**說明**: 核取方塊元件。用於同意條款、批次選取等場景。

#### 2.2.8 `Switch`

```typescript
interface SwitchProps {
  value: boolean;
  onValueChange: (value: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}
```

**說明**: 開關切換元件。用於設定頁的各項偏好開關。

#### 2.2.9 `Dropdown`

```typescript
interface DropdownProps {
  label: string;
  options: DropdownOption[];
  selectedValue: string | null;
  onSelect: (value: string) => void;
  placeholder?: string;
  error?: string;
  searchable?: boolean;
}

interface DropdownOption {
  label: string;
  value: string;
  icon?: string;
}
```

**說明**: 下拉選單元件。支援搜尋篩選。

---

### 2.3 Medical Components (醫療元件)

#### 2.3.1 `ComplaintChip`

```typescript
interface ComplaintChipProps {
  label: string;
  selected: boolean;
  onPress: () => void;
  icon?: string;
  disabled?: boolean;
  category?: string;
  testID?: string;
}
```

**說明**: 主訴選擇 chip。選中狀態以填色背景區分，支援分類圖示。

#### 2.3.2 `ComplaintChipGroup`

```typescript
interface ComplaintChipGroupProps {
  complaints: Complaint[];
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
  maxSelection?: number;
  categoryFilter?: string;
}

interface Complaint {
  id: string;
  name: string;
  nameEn: string;
  category: string;
  icon?: string;
}
```

**說明**: 主訴 chip 群組容器。管理多選邏輯與上限限制。

#### 2.3.3 `SOAPCard`

```typescript
interface SOAPCardProps {
  section: 'subjective' | 'objective' | 'assessment' | 'plan';
  title: string;
  content: SOAPSectionContent;
  expanded?: boolean;
  onToggleExpand?: () => void;
  editable?: boolean;
  onContentChange?: (content: SOAPSectionContent) => void;
  annotations?: Annotation[];
  onAddAnnotation?: (text: string, position: number) => void;
  confidenceScore?: number;
  aiReferences?: string[];
}

interface Annotation {
  id: string;
  text: string;
  position: number;
  author: string;
  createdAt: string;
}
```

**說明**: SOAP 報告區塊卡片。支援展開收合、行內編輯、批註功能。依 section 類型以不同顏色標示左側色條。`SOAPSectionContent` 為結構化 JSONB 物件（詳見 SOAPReportFull 定義）。

#### 2.3.4 `SOAPReport`

```typescript
interface SOAPReportProps {
  report: SOAPReportFull;
  editable?: boolean;
  onSave?: (report: SOAPReportDraft) => void;
  onApprove?: () => void;
  onRequestRevision?: (reason: string) => void;
  reportStatus: ReportStatus;
  reviewStatus: ReviewStatus;
  annotations?: Record<string, Annotation[]>;
}

type ReportStatus = 'generating' | 'generated' | 'failed';
type ReviewStatus = 'pending' | 'approved' | 'revision_needed';
```

**說明**: 完整 SOAP 報告組合元件。整合四張 SOAPCard 與操作按鈕。使用 `ReportStatus` 追蹤報告產生狀態，使用 `ReviewStatus` 追蹤審閱狀態。

#### 2.3.5 `StatusBadge`

```typescript
interface StatusBadgeProps {
  status: 'waiting' | 'in_progress' | 'completed' | 'aborted_red_flag' | 'cancelled';
  size?: 'small' | 'medium';
  showIcon?: boolean;
}
```

**說明**: 狀態標記徽章。以色彩與圖示區分不同狀態：等候中 (橙)、進行中 (藍)、已完成 (綠)、紅旗中止 (紅)、已取消 (灰)。

#### 2.3.6 `RedFlagBanner`

```typescript
interface RedFlagBannerProps {
  message: string;
  severity: 'critical' | 'high' | 'medium';
  onPress?: () => void;
  onDismiss?: () => void;
  dismissible?: boolean;
  timestamp?: string;
}
```

**說明**: 紅旗警示橫幅。`critical` 以紅色背景脈動動畫呈現，`high` 以橙色背景呈現，`medium` 以黃色背景呈現。置於頁面頂部或對話區內。

#### 2.3.7 `RedFlagAlertItem`

```typescript
interface RedFlagAlertItemProps {
  alert: {
    id: string;
    patientName: string;
    title: string;
    description?: string;
    severity: 'critical' | 'high' | 'medium';
    alertType: 'rule_based' | 'semantic' | 'combined';
    timestamp: string;
    isAcknowledged: boolean;
    suggestedActions: string[];
    sessionId: string;
  };
  onPress: () => void;
  onAcknowledge?: () => void;
}
```

**說明**: 紅旗警示列表項目。未確認項目以紅色左側色條標示，支援右滑確認。

#### 2.3.8 `PatientInfoCard`

```typescript
interface PatientInfoCardProps {
  patient: {
    id: string;
    name: string;
    age: number;
    gender: 'male' | 'female' | 'other';
    chiefComplaints: string[];
    sessionStatus: string;
  };
  compact?: boolean;
  onPress?: () => void;
  showActions?: boolean;
}
```

**說明**: 病患資訊卡片。用於監控頁頂部或病患列表中，顯示病患基本資訊與當前主訴。

#### 2.3.9 `ConversationTimeline`

```typescript
interface ConversationTimelineProps {
  sessions: SessionSummary[];
  onSessionPress: (sessionId: string) => void;
  loading?: boolean;
}

interface SessionSummary {
  id: string;
  date: string;
  chiefComplaints: string[];
  status: string;
  soapSummary?: string;
  hasRedFlag: boolean;
}
```

**說明**: 問診歷史時間軸元件。用於醫師端病患歷史頁。

---

### 2.4 Audio Components (音訊元件)

#### 2.4.1 `MicButton`

```typescript
interface MicButtonProps {
  state: 'idle' | 'recording' | 'processing' | 'disabled';
  onPressIn?: () => void;
  onPressOut?: () => void;
  onPress?: () => void;
  mode?: 'hold' | 'toggle';
  size?: 'medium' | 'large';
  testID?: string;
}
```

**說明**: 麥克風錄音按鈕。核心互動元件。`hold` 模式為長按錄音，`toggle` 模式為點擊切換。`recording` 狀態時顯示脈動動畫與紅色環圈。`processing` 狀態時顯示轉圈。

#### 2.4.2 `WaveformVisualizer`

```typescript
interface WaveformVisualizerProps {
  audioData: number[];
  isActive: boolean;
  color?: string;
  height?: number;
  barCount?: number;
  animated?: boolean;
}
```

**說明**: 聲波視覺化元件。即時顯示錄音或播放的音訊波形，以柱狀動畫呈現音量變化。

#### 2.4.3 `TTSPlayer`

```typescript
interface TTSPlayerProps {
  text: string;
  audioUrl?: string;
  autoPlay?: boolean;
  onPlayStart?: () => void;
  onPlayEnd?: () => void;
  onError?: (error: Error) => void;
  showControls?: boolean;
  compact?: boolean;
}
```

**說明**: 文字轉語音播放器。可使用預先合成的音訊 URL 或呼叫裝置 TTS 引擎即時播放。支援播放/暫停/重播控制。

#### 2.4.4 `RecordingIndicator`

```typescript
interface RecordingIndicatorProps {
  isRecording: boolean;
  duration: number;
  maxDuration?: number;
  showTimer?: boolean;
}
```

**說明**: 錄音中指示器。顯示紅點脈動動畫與錄音計時 (MM:SS 格式)。可選顯示進度條 (對照最大錄音時長)。

#### 2.4.5 `AudioPlaybackBar`

```typescript
interface AudioPlaybackBarProps {
  audioUrl: string;
  duration: number;
  onPlay: () => void;
  onPause: () => void;
  onSeek: (position: number) => void;
  currentPosition: number;
  isPlaying: boolean;
}
```

**說明**: 音訊播放控制列。用於歷史對話錄音重播。顯示播放/暫停按鈕、進度條、時間標記。

---

### 2.5 Dashboard Components (儀表板元件)

#### 2.5.1 `StatCard`

```typescript
interface StatCardProps {
  title: string;
  value: number | string;
  icon: string;
  trend?: {
    direction: 'up' | 'down' | 'neutral';
    percentage: number;
    label: string;
  };
  color?: string;
  onPress?: () => void;
  loading?: boolean;
}
```

**說明**: 統計數據卡片。用於醫師儀表板，以大數字顯示關鍵指標，可選顯示趨勢 (較昨日增減百分比)。

#### 2.5.2 `PatientListRow`

```typescript
interface PatientListRowProps {
  patient: {
    id: string;
    name: string;
    age: number;
    gender: 'male' | 'female' | 'other';
    chiefComplaints: string[];
    status: 'waiting' | 'in_progress' | 'completed' | 'aborted_red_flag' | 'cancelled';
    waitingTime?: number;
    lastActivity: string;
  };
  onPress: () => void;
  onLongPress?: () => void;
  showStatus?: boolean;
  showWaitingTime?: boolean;
  highlighted?: boolean;
}
```

**說明**: 病患列表行元件。顯示病患名稱、主訴 chip、狀態徽章、等候時間。紅旗中止病患以紅色左側色條標記。

#### 2.5.3 `AlertListItem`

```typescript
interface AlertListItemProps {
  alert: RedFlagAlert;
  onPress: () => void;
  onSwipeAction?: (action: 'acknowledge' | 'dismiss') => void;
  compact?: boolean;
}

interface RedFlagAlert {
  id: string;
  patientName: string;
  patientId: string;
  sessionId: string;
  title: string;
  description?: string;
  alertType: 'rule_based' | 'semantic' | 'combined';
  severity: 'critical' | 'high' | 'medium';
  triggerKeywords: string[];
  suggestedActions: string[];
  timestamp: string;
  isAcknowledged: boolean;
  acknowledgedBy?: string;
  acknowledgedAt?: string;
}
```

**說明**: 警示列表項目元件。支援左滑出現操作按鈕 (確認 / 查看詳情)。

#### 2.5.4 `WaitingQueueCard`

```typescript
interface WaitingQueueCardProps {
  position: number;
  totalWaiting: number;
  estimatedTime?: number;
  status: 'queued' | 'reviewing' | 'done';
  onCancel?: () => void;
}
```

**說明**: 等候隊列狀態卡片。用於病患等候室頁。顯示目前排隊位置、預估等候時間、狀態動畫。

#### 2.5.5 `DashboardChart`

```typescript
interface DashboardChartProps {
  type: 'bar' | 'line' | 'pie';
  data: ChartDataPoint[];
  title: string;
  height?: number;
  showLegend?: boolean;
  period?: 'daily' | 'weekly' | 'monthly';
}

interface ChartDataPoint {
  label: string;
  value: number;
  color?: string;
}
```

**說明**: 儀表板統計圖表元件。用於顯示問診趨勢、主訴分布等視覺化資料。

---

### 2.6 Chat Components (對話元件)

#### 2.6.1 `ChatBubble`

```typescript
interface ChatBubbleProps {
  message: {
    id: string;
    content: string;
    sender: 'patient' | 'assistant' | 'system';
    timestamp: string;
    audioUrl?: string;
    sttConfidence?: number;
    isStreaming?: boolean;
  };
  showTimestamp?: boolean;
  showAvatar?: boolean;
  onAudioPlay?: () => void;
  onLongPress?: () => void;
  highlighted?: boolean;
}
```

**說明**: 對話氣泡元件。根據 `sender` 決定對齊方向與顏色：病患 (右側、藍色)、assistant (左側、灰色)、系統 (居中、淡色)。支援串流文字動畫 (逐字顯示)。

#### 2.6.2 `ChatMessageList`

```typescript
interface ChatMessageListProps {
  messages: ChatMessage[];
  onEndReached?: () => void;
  onScrollToTop?: () => void;
  autoScrollToBottom?: boolean;
  loading?: boolean;
  headerComponent?: React.ReactNode;
  isLiveMonitoring?: boolean;
}
```

**說明**: 對話訊息列表。封裝 FlatList，支援自動捲動至最新訊息、上拉載入更多歷史訊息。

#### 2.6.3 `STTLiveText`

```typescript
interface STTLiveTextProps {
  text: string;
  isPartial: boolean;
  confidence: number;
}
```

**說明**: 即時語音辨識文字顯示。`isPartial` 為 true 時以淺色斜體顯示 (表示尚未確定)，確定後轉為正常文字。

#### 2.6.4 `TypingIndicator`

```typescript
interface TypingIndicatorProps {
  visible: boolean;
  label?: string;
}
```

**說明**: AI 正在回應的動畫指示器。顯示三個跳動圓點與「AI 正在思考...」文字。

---

### 2.7 Common Components (通用元件)

#### 2.7.1 `Modal`

```typescript
interface ModalProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  actions?: ModalAction[];
  closable?: boolean;
  size?: 'small' | 'medium' | 'large' | 'fullscreen';
  testID?: string;
}

interface ModalAction {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  loading?: boolean;
}
```

**說明**: 通用 Modal 對話框。支援自訂內容與底部操作按鈕。

#### 2.7.2 `ConfirmDialog`

```typescript
interface ConfirmDialogProps {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  destructive?: boolean;
}
```

**說明**: 確認對話框。用於結束問診、確認報告、刪除等需要二次確認的操作。

#### 2.7.3 `LoadingOverlay`

```typescript
interface LoadingOverlayProps {
  visible: boolean;
  message?: string;
  transparent?: boolean;
}
```

**說明**: 全頁載入遮罩。以半透明背景搭配轉圈動畫與訊息文字。

#### 2.7.4 `LoadingSkeleton`

```typescript
interface LoadingSkeletonProps {
  type: 'card' | 'list-item' | 'text-block' | 'avatar' | 'chart';
  count?: number;
  animated?: boolean;
}
```

**說明**: 骨架屏載入元件。在資料載入前以灰色區塊模擬最終版面。

#### 2.7.5 `ErrorState`

```typescript
interface ErrorStateProps {
  title: string;
  message: string;
  icon?: string;
  retryLabel?: string;
  onRetry?: () => void;
  type?: 'network' | 'server' | 'permission' | 'generic';
}
```

**說明**: 錯誤狀態全頁提示。依錯誤類型顯示對應圖示與建議操作。

#### 2.7.6 `EmptyState`

```typescript
interface EmptyStateProps {
  title: string;
  message: string;
  icon?: string;
  actionLabel?: string;
  onAction?: () => void;
}
```

**說明**: 空狀態提示。用於列表無資料、搜尋無結果等場景。

#### 2.7.7 `Toast`

```typescript
interface ToastProps {
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
  duration?: number;
  action?: {
    label: string;
    onPress: () => void;
  };
  position?: 'top' | 'bottom';
}
```

**說明**: 輕量通知提示。自動消失。用於操作成功/失敗的即時回饋。

#### 2.7.8 `Avatar`

```typescript
interface AvatarProps {
  name: string;
  imageUrl?: string;
  size?: 'small' | 'medium' | 'large';
  showOnlineStatus?: boolean;
  isOnline?: boolean;
}
```

**說明**: 使用者頭像元件。無圖片時以姓名首字生成顏色區塊。

#### 2.7.9 `Badge`

```typescript
interface BadgeProps {
  count: number;
  maxCount?: number;
  color?: string;
  size?: 'small' | 'medium';
  dot?: boolean;
}
```

**說明**: 數字徽章。附著於圖示或按鈕右上角，顯示未讀數量。超過 `maxCount` 顯示 "99+"。

#### 2.7.10 `BottomSheet`

```typescript
interface BottomSheetProps {
  visible: boolean;
  onClose: () => void;
  children: React.ReactNode;
  snapPoints?: number[];
  enableDragDown?: boolean;
  title?: string;
}
```

**說明**: 底部彈出面板。用於手機端的篩選器、詳情預覽等。支援拖曳高度切換。

#### 2.7.11 `ProgressBar`

```typescript
interface ProgressBarProps {
  progress: number;
  total: number;
  label?: string;
  showPercentage?: boolean;
  color?: string;
  height?: number;
}
```

**說明**: 進度條元件。用於註冊步驟進度、錄音時長進度等。

---

## 3. 狀態管理設計 (State Management)

所有狀態使用 Zustand 管理。以下定義各 store 的 state shape、actions 與 selectors。

### 3.1 `authStore`

```typescript
// ==================== State Interface ====================
interface AuthState {
  // ---- Session State ----
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  tokenExpiresAt: number | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  // ---- Biometric Auth ----
  biometricEnabled: boolean;
  biometricType: 'face' | 'fingerprint' | null;
}

interface User {
  id: string;
  name: string;
  email: string;
  phone?: string;
  role: 'patient' | 'doctor' | 'admin';
  avatarUrl?: string;
  gender?: 'male' | 'female' | 'other';
  birthDate?: string;
  // Doctor-specific
  licenseNumber?: string;
  hospital?: string;
  specialty?: string;
  // Patient-specific
  medicalRecordNumber?: string;
}

// ==================== Actions ====================
interface AuthActions {
  login: (credentials: { email: string; password: string }) => Promise<void>;
  loginWithOAuth: (provider: 'google' | 'apple') => Promise<void>;
  loginWithBiometric: () => Promise<void>;
  register: (data: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (otp: string, newPassword: string) => Promise<void>;
  updateProfile: (data: Partial<User>) => Promise<void>;
  enableBiometric: () => Promise<void>;
  disableBiometric: () => void;
  clearError: () => void;
  setLoading: (loading: boolean) => void;
  hydrateFromStorage: () => Promise<void>;
}

// ==================== Selectors ====================
// selectIsPatient: (state) => state.user?.role === 'patient'
// selectIsDoctor: (state) => state.user?.role === 'doctor'
// selectIsAdmin: (state) => state.user?.role === 'admin'
// selectUserDisplayName: (state) => state.user?.name ?? ''
// selectTokenValid: (state) => state.tokenExpiresAt ? Date.now() < state.tokenExpiresAt : false
```

---

### 3.2 `conversationStore`

```typescript
// ==================== State Interface ====================
interface ConversationState {
  // ---- Active Session ----
  activeSessionId: string | null;
  sessionStatus: 'waiting' | 'in_progress' | 'completed' | 'aborted_red_flag' | 'cancelled';
  selectedComplaints: Complaint[];

  // ---- Messages ----
  messages: ChatMessage[];
  isLoadingMessages: boolean;
  hasMoreMessages: boolean;
  messageCursor: string | null;

  // ---- Recording State ----
  recordingState: 'idle' | 'recording' | 'processing' | 'error';
  recordingDuration: number;
  audioLevel: number;

  // ---- STT State ----
  sttPartialText: string;
  sttFinalText: string;
  sttConfidence: number;
  sttLanguage: string;

  // ---- TTS State ----
  ttsPlaying: boolean;
  ttsCurrentMessageId: string | null;

  // ---- AI State ----
  aiThinking: boolean;
  aiStreamingText: string;

  // ---- Red Flag ----
  activeRedFlags: RedFlagEvent[];

  // ---- Error ----
  error: string | null;
}

interface ChatMessage {
  id: string;
  sessionId: string;
  sender: 'patient' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  audioUrl?: string;
  audioDuration?: number;
  sttConfidence?: number;
  isStreaming?: boolean;
  metadata?: Record<string, unknown>;
}

interface Complaint {
  id: string;
  name: string;
  nameEn: string;
  category: string;
  icon?: string;
}

interface RedFlagEvent {
  id: string;
  title: string;
  description?: string;
  severity: 'critical' | 'high' | 'medium';
  alertType: 'rule_based' | 'semantic' | 'combined';
  timestamp: string;
  triggerMessageId: string;
  suggestedActions: string[];
  isAcknowledged: boolean;
}

// ==================== Actions ====================
interface ConversationActions {
  // Session lifecycle
  startSession: (complaints: Complaint[]) => Promise<string>;
  endSession: () => Promise<void>;
  resumeSession: (sessionId: string) => Promise<void>;
  resetSession: () => void;

  // Messages
  loadMessages: (sessionId: string, cursor?: string) => Promise<void>;
  addMessage: (message: ChatMessage) => void;
  updateMessage: (messageId: string, updates: Partial<ChatMessage>) => void;

  // Recording
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
  cancelRecording: () => void;
  setAudioLevel: (level: number) => void;
  setRecordingDuration: (duration: number) => void;

  // STT
  updateSTTPartial: (text: string) => void;
  finalizeSTT: (text: string, confidence: number) => void;
  clearSTT: () => void;

  // TTS
  playTTS: (messageId: string) => Promise<void>;
  stopTTS: () => void;

  // AI
  setAIThinking: (thinking: boolean) => void;
  appendAIStreamingText: (chunk: string) => void;
  finalizeAIResponse: () => void;

  // Red flags
  addRedFlag: (event: RedFlagEvent) => void;
  acknowledgeRedFlag: (flagId: string) => void;

  // Complaints
  setSelectedComplaints: (complaints: Complaint[]) => void;

  // Error
  setError: (error: string | null) => void;
}

// ==================== Selectors ====================
// selectActiveMessages: (state) => state.messages.filter(m => m.sessionId === state.activeSessionId)
// selectIsRecording: (state) => state.recordingState === 'recording'
// selectHasActiveRedFlag: (state) => state.activeRedFlags.some(f => !f.isAcknowledged)
// selectCriticalRedFlags: (state) => state.activeRedFlags.filter(f => f.severity === 'critical')
// selectMessageCount: (state) => state.messages.length
// selectLastMessage: (state) => state.messages[state.messages.length - 1]
```

---

### 3.3 `patientListStore`

```typescript
// ==================== State Interface ====================
interface PatientListState {
  // ---- Patient Queue ----
  patients: PatientEntry[];
  totalCount: number;
  isLoading: boolean;
  isRefreshing: boolean;
  hasMore: boolean;
  cursor: string | null;

  // ---- Filters ----
  statusFilter: PatientStatusFilter;
  searchQuery: string;
  sortBy: 'waiting_time' | 'severity' | 'name' | 'last_activity';
  sortOrder: 'asc' | 'desc';

  // ---- Error ----
  error: string | null;
}

type PatientStatusFilter = 'all' | 'waiting' | 'in_progress' | 'completed' | 'aborted_red_flag' | 'cancelled';

interface PatientEntry {
  id: string;
  patientId: string;
  name: string;
  age: number;
  gender: 'male' | 'female' | 'other';
  chiefComplaints: string[];
  sessionId: string;
  status: 'waiting' | 'in_progress' | 'completed' | 'aborted_red_flag' | 'cancelled';
  waitingTime: number;        // 等候秒數
  lastActivity: string;       // ISO timestamp
  hasRedFlag: boolean;
  redFlagSeverity?: 'critical' | 'high' | 'medium';
  assignedDoctor?: string;
  createdAt: string;
}

// ==================== Actions ====================
interface PatientListActions {
  fetchPatients: (reset?: boolean) => Promise<void>;
  refreshPatients: () => Promise<void>;
  loadMorePatients: () => Promise<void>;
  setStatusFilter: (filter: PatientStatusFilter) => void;
  setSearchQuery: (query: string) => void;
  setSortBy: (sort: 'waiting_time' | 'severity' | 'name' | 'last_activity') => void;
  toggleSortOrder: () => void;
  updatePatientStatus: (patientId: string, status: string) => void;
  removePatient: (patientId: string) => void;
  handleRealtimeUpdate: (event: PatientUpdateEvent) => void;
  clearError: () => void;
}

// ==================== Selectors ====================
// selectFilteredPatients: 依 statusFilter + searchQuery 篩選
// selectWaitingCount: (state) => state.patients.filter(p => p.status === 'waiting').length
// selectRedFlagCount: (state) => state.patients.filter(p => p.hasRedFlag).length
// selectInProgressCount: (state) => state.patients.filter(p => p.status === 'in_progress').length
```

---

### 3.4 `alertStore`

```typescript
// ==================== State Interface ====================
interface AlertState {
  // ---- Alerts ----
  alerts: RedFlagAlert[];
  totalCount: number;
  unacknowledgedCount: number;
  isLoading: boolean;
  hasMore: boolean;
  cursor: string | null;

  // ---- Filter ----
  filter: 'all' | 'unacknowledged' | 'acknowledged';

  // ---- Active Alert Detail ----
  activeAlertId: string | null;
  activeAlertDetail: RedFlagAlertDetail | null;
  isLoadingDetail: boolean;

  // ---- Notification ----
  newAlertReceived: boolean;
  lastAlertTimestamp: string | null;

  // ---- Error ----
  error: string | null;
}

interface RedFlagAlert {
  id: string;
  patientId: string;
  patientName: string;
  sessionId: string;
  title: string;
  description?: string;
  alertType: 'rule_based' | 'semantic' | 'combined';
  severity: 'critical' | 'high' | 'medium';
  triggerKeywords: string[];
  suggestedActions: string[];
  timestamp: string;
  isAcknowledged: boolean;
  acknowledgedBy?: string;
  acknowledgedAt?: string;
}

interface RedFlagAlertDetail extends RedFlagAlert {
  conversationExcerpt: ChatMessage[];
  triggerMessageId: string;
  llmAnalysis?: object;
  patientInfo: {
    name: string;
    age: number;
    gender: 'male' | 'female' | 'other';
    phone: string;
    chiefComplaints: string[];
  };
  acknowledgeNotes?: string;
}

// ==================== Actions ====================
interface AlertActions {
  fetchAlerts: (reset?: boolean) => Promise<void>;
  loadMoreAlerts: () => Promise<void>;
  fetchAlertDetail: (alertId: string) => Promise<void>;
  acknowledgeAlert: (alertId: string) => Promise<void>;
  addAcknowledgeNote: (alertId: string, note: string) => Promise<void>;
  markAsEscalated: (alertId: string, escalationType: 'emergency' | 'referral') => Promise<void>;
  setFilter: (filter: 'all' | 'unacknowledged' | 'acknowledged') => void;
  handleNewAlert: (alert: RedFlagAlert) => void;
  clearNewAlertFlag: () => void;
  clearError: () => void;
}

// ==================== Selectors ====================
// selectUnacknowledgedAlerts: (state) => state.alerts.filter(a => !a.isAcknowledged)
// selectCriticalAlerts: (state) => state.alerts.filter(a => a.severity === 'critical' && !a.isAcknowledged)
// selectAlertById: (id: string) => (state) => state.alerts.find(a => a.id === id)
// selectHasNewAlert: (state) => state.newAlertReceived
```

---

### 3.5 `complaintStore`

```typescript
// ==================== State Interface ====================
interface ComplaintState {
  // ---- Complaint List ----
  complaints: ComplaintItem[];
  categories: ComplaintCategory[];
  isLoading: boolean;

  // ---- Search ----
  searchQuery: string;
  searchResults: ComplaintItem[];

  // ---- Custom Complaints ----
  customComplaints: ComplaintItem[];

  // ---- Active Filter ----
  activeCategoryFilter: string | null;

  // ---- Error ----
  error: string | null;
}

interface ComplaintItem {
  id: string;
  name: string;
  nameEn: string;
  category: string;
  description?: string;
  isActive: boolean;
  isDefault: boolean;
  displayOrder: number;
  createdBy?: string;
  createdAt: string;
  updatedAt: string;
}

interface ComplaintCategory {
  name: string;
  nameEn: string;
  count: number;
  description?: string;
}

// ==================== Actions ====================
interface ComplaintActions {
  fetchComplaints: () => Promise<void>;
  fetchCategories: () => Promise<void>;
  searchComplaints: (query: string) => void;
  setCategoryFilter: (category: string | null) => void;
  // Doctor-only CRUD
  createComplaint: (data: Omit<ComplaintItem, 'id' | 'createdAt' | 'updatedAt'>) => Promise<void>;
  updateComplaint: (id: string, data: Partial<ComplaintItem>) => Promise<void>;
  toggleComplaintActive: (id: string) => Promise<void>;
  reorderComplaints: (orderedIds: string[]) => Promise<void>;
  clearError: () => void;
}

// ==================== Selectors ====================
// selectActiveComplaints: (state) => state.complaints.filter(c => c.isActive)
// selectComplaintsByCategory: (cat: string) => (state) => state.complaints.filter(c => c.category === cat)
// selectFilteredComplaints: 依 searchQuery + activeCategoryFilter 綜合篩選
// selectComplaintById: (id: string) => (state) => state.complaints.find(c => c.id === id)
```

---

### 3.6 `reportStore`

```typescript
// ==================== State Interface ====================
interface ReportState {
  // ---- Reports List ----
  reports: SOAPReportSummary[];
  isLoading: boolean;
  hasMore: boolean;
  cursor: string | null;

  // ---- Active Report ----
  activeReport: SOAPReportFull | null;
  isLoadingDetail: boolean;
  isSaving: boolean;

  // ---- Editing State ----
  editDraft: SOAPReportDraft | null;
  isDirty: boolean;

  // ---- Filter ----
  statusFilter: 'all' | 'generating' | 'generated' | 'failed';
  reviewStatusFilter: 'all' | 'pending' | 'approved' | 'revision_needed';

  // ---- Error ----
  error: string | null;
}

interface SOAPReportSummary {
  id: string;
  sessionId: string;
  patientId: string;
  patientName: string;
  chiefComplaints: string[];
  status: 'generating' | 'generated' | 'failed';
  reviewStatus: 'pending' | 'approved' | 'revision_needed';
  createdAt: string;
  updatedAt: string;
  reviewedBy?: string;
  reviewedAt?: string;
}

interface SOAPReportFull extends SOAPReportSummary {
  subjective: SOAPSubjective;
  objective: SOAPObjective;
  assessment: SOAPAssessment;
  plan: SOAPPlan;
  rawTranscript?: string;
  summary?: string;
  icd10Codes?: string[];
  annotations: Record<string, Annotation[]>;
  aiConfidenceScore: number;
  aiReferences: string[];
  conversationSummary: string;
  reviewNotes?: string;
  generatedAt?: string;
}

// SOAP JSONB 結構化型別 (對齊 shared_types.md 3.6)
interface SOAPSubjective {
  chiefComplaint: string;
  hpi: {
    onset: string;
    location: string;
    duration: string;
    characteristics: string;
    severity: string;
    aggravatingFactors: string[];
    relievingFactors: string[];
    associatedSymptoms: string[];
    timing: string;
    context: string;
  };
  pastMedicalHistory: {
    conditions: string[];
    surgeries: string[];
    hospitalizations: string[];
  };
  medicationHistory: {
    current: string[];
    past: string[];
    otc: string[];
  };
  systemReview: Record<string, string>;
  socialHistory: Record<string, string>;
}

interface SOAPObjective {
  vitalSigns?: {
    bloodPressure?: string;
    heartRate?: number;
    respiratoryRate?: number;
    temperature?: number;
    spo2?: number;
  };
  physicalExam?: Record<string, string>;
  labResults?: Array<{
    testName: string;
    result: string;
    referenceRange?: string;
    isAbnormal?: boolean;
    date?: string;
  }>;
  imagingResults?: Array<{
    testName: string;
    result: string;
    date?: string;
  }>;
}

interface SOAPAssessment {
  differentialDiagnoses: Array<{
    diagnosis: string;
    icd10: string;
    probability: string;
    reasoning: string;
  }>;
  clinicalImpression: string;
}

interface SOAPPlan {
  recommendedTests: Array<{
    testName: string;
    rationale: string;
    urgency: 'urgent' | 'routine' | 'elective';
  }>;
  treatments: Array<{
    type: string;
    name: string;
    instruction?: string;
    note?: string;
  }>;
  followUp: {
    interval: string;
    reason: string;
    additionalNotes?: string;
  };
  referrals: string[];
  patientEducation: string[];
}

interface SOAPReportDraft {
  subjective: SOAPSubjective;
  objective: SOAPObjective;
  assessment: SOAPAssessment;
  plan: SOAPPlan;
}

interface Annotation {
  id: string;
  section: 'subjective' | 'objective' | 'assessment' | 'plan';
  text: string;
  position: number;
  author: string;
  authorId: string;
  createdAt: string;
}

// ==================== Actions ====================
interface ReportActions {
  fetchReports: (reset?: boolean) => Promise<void>;
  loadMoreReports: () => Promise<void>;
  fetchReportDetail: (reportId: string) => Promise<void>;
  startEditing: () => void;
  updateDraft: (section: keyof SOAPReportDraft, content: SOAPReportDraft[keyof SOAPReportDraft]) => void;
  cancelEditing: () => void;
  saveReport: () => Promise<void>;
  approveReport: (reportId: string) => Promise<void>;
  requestRevision: (reportId: string, reason: string) => Promise<void>;
  addAnnotation: (section: string, annotation: Omit<Annotation, 'id' | 'createdAt'>) => Promise<void>;
  deleteAnnotation: (section: string, annotationId: string) => Promise<void>;
  exportReportPDF: (reportId: string) => Promise<string>;
  setStatusFilter: (filter: 'all' | 'generating' | 'generated' | 'failed') => void;
  setReviewStatusFilter: (filter: 'all' | 'pending' | 'approved' | 'revision_needed') => void;
  clearActiveReport: () => void;
  clearError: () => void;
}

// ==================== Selectors ====================
// selectPendingReports: (state) => state.reports.filter(r => r.reviewStatus === 'pending')
// selectApprovedReports: (state) => state.reports.filter(r => r.reviewStatus === 'approved')
// selectReportById: (id: string) => (state) => state.reports.find(r => r.id === id)
// selectIsEditing: (state) => state.editDraft !== null
// selectHasUnsavedChanges: (state) => state.isDirty
```

---

### 3.7 `notificationStore`

```typescript
// ==================== State Interface ====================
interface NotificationState {
  // ---- Notifications ----
  notifications: NotificationItem[];
  unreadCount: number;
  isLoading: boolean;
  hasMore: boolean;
  cursor: string | null;

  // ---- Error ----
  error: string | null;
}

interface NotificationItem {
  id: string;
  type: 'red_flag' | 'session_complete' | 'report_ready' | 'system';
  title: string;
  body?: string;
  data?: Record<string, unknown>;
  isRead: boolean;
  readAt?: string;
  createdAt: string;
}

// ==================== Actions ====================
interface NotificationActions {
  fetchNotifications: (reset?: boolean) => Promise<void>;
  loadMoreNotifications: () => Promise<void>;
  markAsRead: (notificationId: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  deleteNotification: (notificationId: string) => Promise<void>;
  handleIncomingNotification: (notification: NotificationItem) => void;
  clearError: () => void;
}

// ==================== Selectors ====================
// selectUnreadNotifications: (state) => state.notifications.filter(n => !n.isRead)
// selectNotificationsByType: (type: NotificationType) => (state) => state.notifications.filter(n => n.type === type)
// selectHasUnread: (state) => state.unreadCount > 0
```

---

### 3.8 `settingsStore`

```typescript
// ==================== State Interface ====================
interface SettingsState {
  // ---- Notification Preferences ----
  pushNotificationsEnabled: boolean;
  redFlagSoundEnabled: boolean;
  redFlagVibrationEnabled: boolean;
  waitingRoomNotificationEnabled: boolean;

  // ---- Consultation Preferences ----
  preferredLanguage: 'zh-TW' | 'zh-TW-tai' | 'en';
  micMode: 'hold' | 'toggle';
  autoPlayTTS: boolean;
  showSTTConfidence: boolean;

  // ---- Display Preferences ----
  fontSize: 'small' | 'medium' | 'large';
  darkMode: boolean;

  // ---- SOAP Template (Doctor) ----
  soapTemplateId: string | null;
  soapTemplates: SOAPTemplate[];

  // ---- App Info ----
  appVersion: string;
  buildNumber: string;

  // ---- FCM Token ----
  fcmToken: string | null;

  // ---- Loading ----
  isLoading: boolean;
  error: string | null;
}

interface SOAPTemplate {
  id: string;
  name: string;
  sections: {
    subjective: string;
    objective: string;
    assessment: string;
    plan: string;
  };
  isDefault: boolean;
}

// ==================== Actions ====================
interface SettingsActions {
  loadSettings: () => Promise<void>;
  saveSettings: () => Promise<void>;
  togglePushNotifications: () => void;
  toggleRedFlagSound: () => void;
  toggleRedFlagVibration: () => void;
  toggleWaitingRoomNotification: () => void;
  setPreferredLanguage: (lang: 'zh-TW' | 'zh-TW-tai' | 'en') => void;
  setMicMode: (mode: 'hold' | 'toggle') => void;
  toggleAutoPlayTTS: () => void;
  toggleShowSTTConfidence: () => void;
  setFontSize: (size: 'small' | 'medium' | 'large') => void;
  toggleDarkMode: () => void;
  setFCMToken: (token: string, deviceType: 'ios' | 'android' | 'web') => void;
  setSOAPTemplate: (templateId: string) => void;
  createSOAPTemplate: (template: Omit<SOAPTemplate, 'id'>) => Promise<void>;
  updateSOAPTemplate: (id: string, data: Partial<SOAPTemplate>) => Promise<void>;
  deleteSOAPTemplate: (id: string) => Promise<void>;
  resetToDefaults: () => void;
  clearError: () => void;
}

// ==================== Selectors ====================
// selectActiveSOAPTemplate: (state) => state.soapTemplates.find(t => t.id === state.soapTemplateId)
// selectNotificationSettings: (state) => ({ push: state.pushNotificationsEnabled, sound: state.redFlagSoundEnabled, vibration: state.redFlagVibrationEnabled })
```

---

## 4. 路由與導航結構 (Navigation Architecture)

### 4.1 導航樹狀圖 (Navigation Tree)

```
Root Navigator (Stack)
|
|-- SplashScreen
|
|-- AuthNavigator (Stack) [未登入]
|   |-- LoginScreen
|   |-- RegisterScreen
|   |-- ForgotPasswordScreen
|
|-- PatientNavigator (Tab) [role === 'patient']
|   |
|   |-- HomeTab (Stack)
|   |   |-- PatientHomeScreen
|   |   |-- ComplaintSelectScreen
|   |   |-- VoiceConversationScreen
|   |   |-- WaitingRoomScreen
|   |
|   |-- HistoryTab (Stack)
|   |   |-- ConversationHistoryScreen
|   |   |-- ConversationDetailScreen
|   |
|   |-- SettingsTab (Stack)
|       |-- PatientSettingsScreen
|       |-- EditProfileScreen
|       |-- LanguageSelectScreen
|       |-- TermsScreen
|       |-- PrivacyScreen
|
|-- DoctorNavigator (Tab) [role === 'doctor']
|   |
|   |-- DashboardTab (Stack)
|   |   |-- DashboardScreen
|   |   |-- AlertDetailScreen (from dashboard quick links)
|   |
|   |-- PatientsTab (Stack)
|   |   |-- PatientListScreen
|   |   |-- LiveMonitoringScreen
|   |   |-- SOAPReportScreen
|   |   |-- PatientHistoryScreen
|   |   |-- ConversationDetailScreen (reused)
|   |
|   |-- AlertsTab (Stack)
|   |   |-- AlertListScreen
|   |   |-- AlertDetailScreen
|   |
|   |-- SettingsTab (Stack)
|       |-- DoctorSettingsScreen
|       |-- ComplaintManagementScreen
|       |-- SOAPTemplateScreen
|       |-- EditProfileScreen
|       |-- SecurityScreen
|
|-- AdminNavigator (Tab) [role === 'admin']
    |
    |-- UsersTab (Stack)
    |   |-- UserManagementScreen
    |   |-- UserDetailScreen
    |
    |-- RulesTab (Stack)
    |   |-- RedFlagRuleManagementScreen
    |   |-- RedFlagRuleDetailScreen
    |
    |-- SystemTab (Stack)
    |   |-- SystemHealthScreen
    |
    |-- AuditTab (Stack)
        |-- AuditLogsScreen
```

### 4.2 Auth Flow (認證流程)

```
App 啟動
  |
  v
[SplashScreen]
  |
  +--> 檢查 AsyncStorage 中的 token
  |
  +--> token 存在且有效?
  |      |
  |      +--> YES --> 取得 user.role
  |      |             |
  |      |             +--> role === 'patient' --> PatientNavigator
  |      |             |
  |      |             +--> role === 'doctor'  --> DoctorNavigator
  |      |             |
  |      |             +--> role === 'admin'   --> AdminNavigator
  |      |
  |      +--> NO  --> token 已過期?
  |                    |
  |                    +--> YES --> 嘗試 refreshToken
  |                    |            |
  |                    |            +--> 成功 --> 依 role 導向
  |                    |            +--> 失敗 --> AuthNavigator (LoginScreen)
  |                    |
  |                    +--> NO (無 token) --> AuthNavigator (LoginScreen)
  |
[LoginScreen]
  |
  +--> 使用者輸入 Email 密碼 / OAuth
  |
  +--> 登入成功 --> 取得 role
  |                  |
  |                  +--> role === 'patient' --> PatientNavigator
  |                  +--> role === 'doctor'  --> DoctorNavigator
  |                  +--> role === 'admin'   --> AdminNavigator
  |
  +--> 登入失敗 --> 顯示錯誤訊息，留在 LoginScreen
```

### 4.3 Patient Flow (病患端流程)

```
[PatientHomeScreen]
  |
  +--> 點擊「開始問診」
  |
  v
[ComplaintSelectScreen]
  |
  +--> 選擇主訴 (1~5 項)
  +--> 點擊「開始問診」
  |
  v
[VoiceConversationScreen]
  |
  +--> 與 AI 語音對話
  |     |
  |     +--> 長按麥克風錄音 --> 音訊串流至 server
  |     +--> 接收 STT 結果 --> 顯示辨識文字
  |     +--> AI 回應 --> TTS 播放 + 文字顯示
  |     +--> 紅旗偵測 --> 顯示警示通知
  |
  +--> 點擊「結束問診」--> 確認對話框
  |
  v
[WaitingRoomScreen]
  |
  +--> 顯示等候狀態
  +--> 收到醫師審閱完成推播 --> 查看結果
  +--> 或返回首頁
  |
  v
[ConversationDetailScreen] (查看結果)
```

### 4.4 Doctor Flow (醫師端流程)

```
[DashboardScreen]
  |
  +--> 查看統計概覽
  |
  +--> 點擊紅旗警示 --> [AlertDetailScreen]
  |                       |
  |                       +--> 確認已處理
  |                       +--> 聯繫病患
  |                       +--> 轉介急診
  |
  +--> 點擊待審閱病患 --> [SOAPReportScreen]
  |                         |
  |                         +--> 檢視/編輯 SOAP
  |                         +--> 確認報告 / 退回修改
  |                         +--> 匯出 PDF
  |
  +--> 切換至 PatientsTab
       |
       v
[PatientListScreen]
  |
  +--> 篩選/搜尋病患
  |
  +--> 點擊進行中的病患 --> [LiveMonitoringScreen]
  |                          |
  |                          +--> 即時觀看對話
  |                          +--> 查看 SOAP 草稿
  |                          +--> 介入對話
  |
  +--> 點擊已完成的病患 --> [PatientHistoryScreen]
                             |
                             +--> 瀏覽問診時間軸
                             +--> 查看完整 SOAP 報告
```

### 4.5 Deep Linking (深層連結)

用於推播通知跳轉至特定頁面。

| 通知類型 | Deep Link URI | 目標頁面 |
|---------|--------------|---------|
| 紅旗警示 (醫師) | `uroai://doctor/alert/{alertId}` | AlertDetailScreen |
| 新病患等候 (醫師) | `uroai://doctor/patients?filter=waiting` | PatientListScreen (篩選等候中) |
| 問診完成 (醫師) | `uroai://doctor/report/{sessionId}` | SOAPReportScreen |
| 審閱完成 (病患) | `uroai://patient/history/{sessionId}` | ConversationDetailScreen |
| 等候狀態更新 (病患) | `uroai://patient/waiting-room/{sessionId}` | WaitingRoomScreen |

Deep Link 處理流程：

```
推播通知點擊
  |
  v
App 是否在前景?
  |
  +--> YES --> 解析 URI --> 導航至目標頁面
  |
  +--> NO  --> 啟動 App
               |
               +--> SplashScreen 完成認證
               +--> 解析儲存的 pending deep link
               +--> 導航至目標頁面
```

---

## 5. 目錄結構 (Project Structure)

```
uro-ai-consultation/
|
|-- package.json
|-- tsconfig.json
|-- babel.config.js
|-- metro.config.js
|-- app.json
|-- index.js
|-- .env
|-- .env.staging
|-- .env.production
|-- .eslintrc.js
|-- .prettierrc
|-- jest.config.js
|
|-- android/                        # Android 原生專案
|   |-- app/
|   |-- build.gradle
|   |-- ...
|
|-- ios/                            # iOS 原生專案
|   |-- UroAI/
|   |-- UroAI.xcodeproj/
|   |-- Podfile
|   |-- ...
|
|-- web/                            # React Web Dashboard 入口
|   |-- public/
|   |   |-- index.html
|   |   |-- favicon.ico
|   |-- vite.config.ts
|   |-- tsconfig.json
|
|-- src/
|   |
|   |-- app/                        # App 進入點與全域設定
|   |   |-- App.tsx                  # 根元件，Provider 組裝
|   |   |-- AppProviders.tsx         # Context Providers 集合 (Theme, Navigation, etc.)
|   |   |-- linking.ts              # Deep link 設定
|   |   |-- theme.ts                # 設計 token (色彩、字型、間距)
|   |   |-- i18n.ts                 # 多語系初始化
|   |
|   |-- assets/                     # 靜態資源
|   |   |-- images/                 # 圖片 (PNG, SVG)
|   |   |   |-- logo.png
|   |   |   |-- splash.png
|   |   |   |-- empty-state.png
|   |   |   |-- ...
|   |   |-- icons/                  # 自訂圖示
|   |   |-- fonts/                  # 自訂字型
|   |   |-- animations/             # Lottie 動畫檔
|   |       |-- recording.json
|   |       |-- waiting.json
|   |       |-- success.json
|   |       |-- red-flag.json
|   |
|   |-- components/                 # 可重用 UI 元件
|   |   |-- layout/                 # 版面配置元件
|   |   |   |-- AppHeader.tsx
|   |   |   |-- BottomTabBar.tsx
|   |   |   |-- SafeAreaContainer.tsx
|   |   |   |-- ScreenContainer.tsx
|   |   |   |-- SectionHeader.tsx
|   |   |   |-- Divider.tsx
|   |   |
|   |   |-- form/                   # 表單元件
|   |   |   |-- TextInput.tsx
|   |   |   |-- Button.tsx
|   |   |   |-- OTPInput.tsx
|   |   |   |-- SearchBar.tsx
|   |   |   |-- FilterTabBar.tsx
|   |   |   |-- DateRangePicker.tsx
|   |   |   |-- Checkbox.tsx
|   |   |   |-- Switch.tsx
|   |   |   |-- Dropdown.tsx
|   |   |
|   |   |-- medical/                # 醫療相關元件
|   |   |   |-- ComplaintChip.tsx
|   |   |   |-- ComplaintChipGroup.tsx
|   |   |   |-- SOAPCard.tsx
|   |   |   |-- SOAPReport.tsx
|   |   |   |-- StatusBadge.tsx
|   |   |   |-- RedFlagBanner.tsx
|   |   |   |-- RedFlagAlertItem.tsx
|   |   |   |-- PatientInfoCard.tsx
|   |   |   |-- ConversationTimeline.tsx
|   |   |
|   |   |-- audio/                  # 音訊相關元件
|   |   |   |-- MicButton.tsx
|   |   |   |-- WaveformVisualizer.tsx
|   |   |   |-- TTSPlayer.tsx
|   |   |   |-- RecordingIndicator.tsx
|   |   |   |-- AudioPlaybackBar.tsx
|   |   |
|   |   |-- chat/                   # 對話元件
|   |   |   |-- ChatBubble.tsx
|   |   |   |-- ChatMessageList.tsx
|   |   |   |-- STTLiveText.tsx
|   |   |   |-- TypingIndicator.tsx
|   |   |
|   |   |-- dashboard/              # 儀表板元件
|   |   |   |-- StatCard.tsx
|   |   |   |-- PatientListRow.tsx
|   |   |   |-- AlertListItem.tsx
|   |   |   |-- WaitingQueueCard.tsx
|   |   |   |-- DashboardChart.tsx
|   |   |
|   |   |-- common/                 # 通用元件
|   |       |-- Modal.tsx
|   |       |-- ConfirmDialog.tsx
|   |       |-- LoadingOverlay.tsx
|   |       |-- LoadingSkeleton.tsx
|   |       |-- ErrorState.tsx
|   |       |-- EmptyState.tsx
|   |       |-- Toast.tsx
|   |       |-- Avatar.tsx
|   |       |-- Badge.tsx
|   |       |-- BottomSheet.tsx
|   |       |-- ProgressBar.tsx
|   |
|   |-- screens/                    # 頁面元件
|   |   |-- auth/                   # 認證相關頁面
|   |   |   |-- SplashScreen.tsx
|   |   |   |-- LoginScreen.tsx
|   |   |   |-- RegisterScreen.tsx
|   |   |   |-- ForgotPasswordScreen.tsx
|   |   |
|   |   |-- patient/                # 病患端頁面
|   |   |   |-- PatientHomeScreen.tsx
|   |   |   |-- ComplaintSelectScreen.tsx
|   |   |   |-- VoiceConversationScreen.tsx
|   |   |   |-- WaitingRoomScreen.tsx
|   |   |   |-- ConversationHistoryScreen.tsx
|   |   |   |-- ConversationDetailScreen.tsx
|   |   |   |-- PatientSettingsScreen.tsx
|   |   |
|   |   |-- doctor/                 # 醫師端頁面
|   |   |   |-- DashboardScreen.tsx
|   |   |   |-- PatientListScreen.tsx
|   |   |   |-- LiveMonitoringScreen.tsx
|   |   |   |-- SOAPReportScreen.tsx
|   |   |   |-- AlertListScreen.tsx
|   |   |   |-- AlertDetailScreen.tsx
|   |   |   |-- ComplaintManagementScreen.tsx
|   |   |   |-- PatientHistoryScreen.tsx
|   |   |   |-- DoctorSettingsScreen.tsx
|   |   |
|   |   |-- admin/                  # 管理員端頁面
|   |       |-- UserManagementScreen.tsx
|   |       |-- RedFlagRuleManagementScreen.tsx
|   |       |-- SystemHealthScreen.tsx
|   |       |-- AuditLogsScreen.tsx
|   |
|   |-- navigation/                 # 導航設定
|   |   |-- RootNavigator.tsx        # 根導航器
|   |   |-- AuthNavigator.tsx        # 認證流程導航
|   |   |-- PatientNavigator.tsx     # 病患端 Tab + Stack 導航
|   |   |-- DoctorNavigator.tsx      # 醫師端 Tab + Stack 導航
|   |   |-- AdminNavigator.tsx       # 管理員端 Tab + Stack 導航
|   |   |-- navigationRef.ts         # 導航參考 (供非元件使用)
|   |   |-- types.ts                 # 導航參數型別定義
|   |
|   |-- stores/                     # Zustand 狀態管理
|   |   |-- authStore.ts
|   |   |-- conversationStore.ts
|   |   |-- patientListStore.ts
|   |   |-- alertStore.ts
|   |   |-- complaintStore.ts
|   |   |-- reportStore.ts
|   |   |-- notificationStore.ts
|   |   |-- settingsStore.ts
|   |   |-- index.ts                 # Store 統一匯出
|   |
|   |-- services/                   # 服務層
|   |   |-- api/                     # REST API 客戶端
|   |   |   |-- client.ts            # Axios instance 與攔截器 (含 snake/camel 自動轉換)
|   |   |   |-- authApi.ts           # 認證相關 API
|   |   |   |-- conversationApi.ts   # 問診對話 API
|   |   |   |-- patientApi.ts        # 病患資料 API
|   |   |   |-- reportApi.ts         # SOAP 報告 API
|   |   |   |-- alertApi.ts          # 紅旗警示 API
|   |   |   |-- complaintApi.ts      # 主訴管理 API
|   |   |   |-- notificationApi.ts   # 通知 API
|   |   |   |-- settingsApi.ts       # 設定 API
|   |   |   |-- adminApi.ts          # 管理員 API
|   |   |
|   |   |-- websocket/              # WebSocket 管理
|   |   |   |-- WebSocketManager.ts  # 連線管理 (連線、重連、心跳)
|   |   |   |-- messageHandlers.ts   # 訊息處理器
|   |   |   |-- types.ts             # WebSocket 訊息型別
|   |   |
|   |   |-- audio/                   # 音訊服務
|   |   |   |-- AudioRecorder.ts     # 錄音管理 (PCM 擷取)
|   |   |   |-- AudioPlayer.ts       # 音訊播放管理
|   |   |   |-- AudioStreamer.ts     # 音訊串流上傳
|   |   |   |-- TTSService.ts        # TTS 管理
|   |   |
|   |   |-- notification/           # 推播通知
|   |   |   |-- FCMService.ts        # FCM 初始化與 token 管理
|   |   |   |-- NotificationHandler.ts  # 通知接收處理
|   |   |   |-- DeepLinkHandler.ts   # 深層連結解析
|   |   |
|   |   |-- storage/                 # 本地儲存
|   |       |-- secureStorage.ts     # 加密儲存 (token, credentials)
|   |       |-- asyncStorage.ts      # 一般持久化儲存
|   |
|   |-- hooks/                      # 自訂 React Hooks
|   |   |-- useAuth.ts               # 認證相關 hooks
|   |   |-- useConversation.ts       # 問診對話 hooks
|   |   |-- useAudioRecorder.ts      # 錄音 hooks
|   |   |-- useWebSocket.ts          # WebSocket 連線 hooks
|   |   |-- useRedFlagAlerts.ts      # 紅旗警示 hooks
|   |   |-- useNotification.ts       # 推播通知 hooks
|   |   |-- useDebounce.ts           # 防抖 hooks
|   |   |-- useTimer.ts              # 計時器 hooks
|   |   |-- usePermissions.ts        # 權限請求 hooks (麥克風, 通知)
|   |   |-- useNetworkStatus.ts      # 網路狀態 hooks
|   |   |-- useAppState.ts           # App 前後景狀態 hooks
|   |
|   |-- types/                      # TypeScript 型別定義
|   |   |-- index.ts                 # 共用型別（對齊 shared_types.md）
|   |   |-- enums.ts                 # Enum 定義
|   |   |-- api.ts                   # API 請求/回應型別
|   |   |-- models.ts                # 資料模型型別
|   |   |-- navigation.ts            # 導航參數型別
|   |   |-- components.ts            # 元件 Props 型別
|   |   |-- websocket.ts             # WebSocket 訊息型別
|   |   |-- audio.ts                 # 音訊相關型別
|   |
|   |-- utils/                      # 工具函式
|   |   |-- formatters.ts            # 格式化 (日期、時間、數字)
|   |   |-- validators.ts            # 表單驗證
|   |   |-- constants.ts             # 常數定義
|   |   |-- permissions.ts           # 權限工具
|   |   |-- logger.ts                # 日誌工具
|   |   |-- errorHandler.ts          # 全域錯誤處理
|   |   |-- platform.ts              # 平台判斷工具
|   |
|   |-- locales/                    # 多語系翻譯檔
|   |   |-- zh-TW.json               # 繁體中文
|   |   |-- en.json                  # 英文
|   |
|   |-- __tests__/                  # 測試檔案
|       |-- components/              # 元件單元測試
|       |-- screens/                 # 頁面整合測試
|       |-- stores/                  # Store 單元測試
|       |-- services/                # 服務層測試
|       |-- hooks/                   # Hooks 測試
|       |-- __mocks__/               # Mock 資料
|       |-- setup.ts                 # 測試環境設定
```

### 目錄說明

| 目錄 | 用途 |
|------|------|
| `src/app/` | App 進入點、全域 Provider 組裝、主題設定、Deep Link 設定、多語系初始化。 |
| `src/assets/` | 靜態資源檔案，包含圖片、圖示、字型、Lottie 動畫。 |
| `src/components/` | 所有可重用 UI 元件，依功能分類至子目錄 (layout / form / medical / audio / chat / dashboard / common)。 |
| `src/screens/` | 各頁面元件，依角色分類 (auth / patient / doctor / admin)。每個 Screen 負責組裝元件與連接 Store。 |
| `src/navigation/` | React Navigation 導航器定義。包含根導航器、認證導航器、病患/醫師/管理員 Tab 導航器、導航參考與型別定義。 |
| `src/stores/` | Zustand store 定義。每個 store 為獨立檔案，統一由 index.ts 匯出。包含 notificationStore。 |
| `src/services/` | 服務層，封裝所有外部通訊邏輯。包含 REST API 客戶端、WebSocket 管理、音訊處理、推播通知、本地儲存。 |
| `src/hooks/` | 自訂 React Hooks。封裝複雜邏輯供元件使用，例如錄音控制、WebSocket 事件監聽、權限請求。 |
| `src/utils/` | 純函式工具。格式化、驗證、常數、日誌等不依賴 React 的工具函式。 |
| `src/types/` | 全域 TypeScript 型別定義。集中管理 Enum、API 回應型別、資料模型、導航參數、WebSocket 訊息型別等。對齊 shared_types.md。 |
| `src/locales/` | i18n 翻譯檔案。支援繁體中文與英文。 |
| `src/__tests__/` | 測試檔案，鏡射 src 的目錄結構。包含 Mock 資料與測試環境設定。 |
| `web/` | React Web Dashboard 專用入口。使用 Vite 作為打包工具。共用 src 內的元件與邏輯。 |
| `android/` / `ios/` | React Native 原生專案目錄，由 CLI 自動生成。 |

---

## 6. 即時通訊設計 (Real-time Communication)

### 6.1 WebSocket 連線管理

#### 6.1.1 連線建立

系統使用兩個獨立的 WebSocket 端點：

- **語音對話 WebSocket**: `wss://{host}/api/v1/ws/sessions/{id}/stream?token={access_token}`
- **醫師儀表板 WebSocket**: `wss://{host}/api/v1/ws/dashboard?token={access_token}`

```typescript
interface WebSocketConfig {
  url: string;
  token: string;
  reconnectAttempts: number;     // 最大重連次數，預設 10
  reconnectInterval: number;     // 重連間隔基數 (ms)，預設 1000
  reconnectBackoffMax: number;   // 最大重連間隔 (ms)，預設 30000
  heartbeatInterval: number;     // 心跳間隔 (ms)，預設 30000
  heartbeatTimeout: number;      // 心跳逾時 (ms)，預設 10000
}
```

#### 6.1.2 通用訊息信封

所有 WebSocket 訊息使用統一包裝格式（對齊 shared_types.md 4.1）：

```typescript
interface WSMessage {
  type: string;           // 訊息類型
  id: string;             // 訊息唯一 ID (UUID)
  timestamp: string;      // ISO 8601 時間戳
  payload: object;        // 訊息內容
}
```

#### 6.1.3 重連策略

```
連線中斷偵測 (onclose / onerror / 心跳逾時)
  |
  v
記錄斷線原因與時間
  |
  v
開始重連循環:
  |
  +--> attempt = 1
  |
  +--> 計算延遲: delay = min(baseInterval * 2^(attempt-1) + jitter, maxInterval)
  |      例: 1s, 2s, 4s, 8s, 16s, 30s, 30s, ...
  |
  +--> 等待 delay 後嘗試連線
  |      |
  |      +--> 成功 --> 重設計數器 --> 重新訂閱頻道 --> 恢復正常
  |      |
  |      +--> 失敗 --> attempt++ --> attempt <= maxAttempts?
  |                      |
  |                      +--> YES --> 回到計算延遲步驟
  |                      +--> NO  --> 顯示「連線失敗」錯誤畫面
  |                                   提供「手動重連」按鈕
```

#### 6.1.4 心跳機制

```typescript
// Client 端每 30 秒發送 ping
// WSMessage 格式: { type: 'ping', id: '...', timestamp: '...', payload: {} }

// Server 端回應 pong
// WSMessage 格式: { type: 'pong', id: '...', timestamp: '...', payload: { server_time: '...' } }

// 若 10 秒內未收到 pong，判定連線已中斷，觸發重連
```

#### 6.1.5 連線生命週期狀態

```typescript
type WebSocketStatus =
  | 'disconnected'    // 未連線
  | 'connecting'      // 連線中
  | 'connected'       // 已連線
  | 'reconnecting'    // 重連中
  | 'failed';         // 連線失敗 (已耗盡重連次數)
```

---

### 6.2 語音對話 WebSocket 訊息定義

**端點**: `wss://{host}/api/v1/ws/sessions/{id}/stream?token={access_token}`

#### 6.2.1 Client --> Server 訊息

```typescript
// ---- 音訊串流 ----
// type: 'audio_chunk'
interface WSAudioChunkPayload {
  audioData: string;       // Base64 encoded audio
  chunkIndex: number;
  isFinal: boolean;        // 最後一個 chunk 設為 true（取代 audio_end）
  format: 'wav';
  sampleRate: 16000;
}

// ---- 文字訊息 ----
// type: 'text_message'
interface WSTextMessagePayload {
  text: string;
}

// ---- 控制指令 ----
// type: 'control'
interface WSControlPayload {
  action: 'end_session' | 'pause_recording' | 'resume_recording';
}

// ---- 心跳 ----
// type: 'ping'
// payload: {}
```

#### 6.2.2 Server --> Client 訊息

```typescript
// ---- 連線確認 ----
// type: 'connection_ack'
interface WSConnectionAckPayload {
  sessionId: string;
  status: string;
  config: {
    audioFormat: string;
    sampleRate: number;
    maxChunkSizeBytes: number;
  };
}

// ---- STT 中間結果 ----
// type: 'stt_partial'
interface WSSTTPartialPayload {
  text: string;
  confidence: number;
  isFinal: false;
}

// ---- STT 最終結果 ----
// type: 'stt_final'
interface WSSTTFinalPayload {
  messageId: string;
  text: string;
  confidence: number;
  isFinal: true;
}

// ---- AI 回應開始 ----
// type: 'ai_response_start'
interface WSAIResponseStartPayload {
  messageId: string;
}

// ---- AI 回應串流片段 ----
// type: 'ai_response_chunk'
interface WSAIResponseChunkPayload {
  messageId: string;
  text: string;
  chunkIndex: number;
}

// ---- AI 回應結束 ----
// type: 'ai_response_end'
interface WSAIResponseEndPayload {
  messageId: string;
  fullText: string;
  ttsAudioUrl: string;
}

// ---- 紅旗警示 ----
// type: 'red_flag_alert'
interface WSRedFlagAlertPayload {
  alertId: string;
  severity: 'critical' | 'high' | 'medium';
  title: string;
  description?: string;
  suggestedActions: string[];
}

// ---- 場次狀態變更 ----
// type: 'session_status'
interface WSSessionStatusPayload {
  sessionId: string;
  status: 'waiting' | 'in_progress' | 'completed' | 'aborted_red_flag' | 'cancelled';
  previousStatus: string;
  reason?: string;
}

// ---- 錯誤 ----
// type: 'error'
interface WSErrorPayload {
  code: string;
  message: string;
}

// ---- 心跳回應 ----
// type: 'pong'
interface WSPongPayload {
  serverTime: string;
}
```

---

### 6.3 醫師儀表板 WebSocket 訊息定義

**端點**: `wss://{host}/api/v1/ws/dashboard?token={access_token}`

#### Server --> Client 事件

```typescript
// ---- 新場次建立 ----
// type: 'session_created'
interface WSSessionCreatedPayload {
  sessionId: string;
  patientName: string;
  chiefComplaint: string;
  status: string;
}

// ---- 場次狀態變更 ----
// type: 'session_status_changed'
interface WSSessionStatusChangedPayload {
  sessionId: string;
  status: string;
  previousStatus: string;
  reason?: string;
}

// ---- 新紅旗觸發 ----
// type: 'new_red_flag'
interface WSNewRedFlagPayload {
  alertId: string;
  sessionId: string;
  patientName: string;
  severity: 'critical' | 'high' | 'medium';
  title: string;
  description?: string;
}

// ---- 紅旗已確認 ----
// type: 'red_flag_acknowledged'
interface WSRedFlagAcknowledgedPayload {
  alertId: string;
  acknowledgedBy: string;
}

// ---- 報告產生完成 ----
// type: 'report_generated'
interface WSReportGeneratedPayload {
  reportId: string;
  sessionId: string;
  patientName: string;
  status: string;
}

// ---- 排隊狀態更新 ----
// type: 'queue_updated'
interface WSQueueUpdatedPayload {
  totalWaiting: number;
  totalInProgress: number;
  queue: Array<{
    sessionId: string;
    patientName: string;
    status: string;
    waitingTime: number;
  }>;
}

// ---- 統計更新 ----
// type: 'stats_updated'
interface WSStatsUpdatedPayload {
  sessionsToday: number;
  completed: number;
  redFlags: number;
  pendingReviews: number;
}
```

---

### 6.4 音訊串流流程 (Audio Streaming Flow)

```
[病患裝置]                    [Server]                    [醫師裝置]
     |                           |                           |
     |  1. 按下麥克風按鈕         |                           |
     |  2. 請求麥克風權限         |                           |
     |  3. 開始 PCM 錄音          |                           |
     |     (16kHz, 16bit, mono)  |                           |
     |                           |                           |
     |  4. audio_chunk (每 200ms) |                           |
     |  ========================>|                           |
     |  { type: "audio_chunk",   |                           |
     |    id: "...",             |  5. 轉送至 STT 引擎        |
     |    timestamp: "...",      |                           |
     |    payload: {             |                           |
     |      audioData: "<b64>",  |                           |
     |      chunkIndex: 0,       |                           |
     |      isFinal: false,      |                           |
     |      format: "wav",       |                           |
     |      sampleRate: 16000    |                           |
     |    } }                    |                           |
     |                           |                           |
     |  6. stt_partial           |                           |
     |  <========================|                           |
     |  { type: "stt_partial",   |  7. 轉送對話更新            |
     |    payload: {             |  ========================>|
     |      text: "我最近...",    |                           |
     |      confidence: 0.72,    |                           |
     |      isFinal: false       |                           |
     |    } }                    |                           |
     |                           |                           |
     |  8. 放開麥克風按鈕         |                           |
     |  9. audio_chunk (isFinal) |                           |
     |  ========================>|                           |
     |  { type: "audio_chunk",   |                           |
     |    payload: {             |                           |
     |      audioData: "<b64>",  |                           |
     |      chunkIndex: 15,      |                           |
     |      isFinal: true        |                           |
     |    } }                    |                           |
     |                           |                           |
     | 10. stt_final             |                           |
     |  <========================|                           |
     |  { type: "stt_final",     |                           |
     |    payload: {             |                           |
     |      messageId: "msg_123",|                           |
     |      text: "我最近排尿困難",|                           |
     |      confidence: 0.95,    |                           |
     |      isFinal: true        |                           |
     |    } }                    |                           |
     |                           |                           |
     |                           | 11. AI 處理對話             |
     |                           |     產生回應                |
     |                           |                           |
     | 12. ai_response_start     |                           |
     |  <========================|                           |
     |  { type: "ai_response_    |                           |
     |    start", payload: {     |                           |
     |    messageId: "msg_124"}  |                           |
     |  }                        |                           |
     |                           |                           |
     | 13. ai_response_chunk     | 14. 同步至醫師端            |
     |  <========================|  ========================>|
     |  { type: "ai_response_    |                           |
     |    chunk", payload: {     |                           |
     |    messageId: "msg_124",  |                           |
     |    text: "請問...",        |                           |
     |    chunkIndex: 0 } }      |                           |
     |                           |                           |
     | 15. ai_response_end       |                           |
     |  <========================|                           |
     |  { type: "ai_response_    |                           |
     |    end", payload: {       |                           |
     |    messageId: "msg_124",  |                           |
     |    fullText: "請問這個症狀  |                           |
     |      持續多久了？",        |                           |
     |    ttsAudioUrl: "..." } } |                           |
     |                           |                           |
     | 16. 自動播放 TTS 音訊      |                           |
```

---

### 6.5 紅旗警示推送流程 (Red Flag Alert Push Flow)

```
[AI 引擎]                    [Server]                    [醫師裝置]
     |                           |                           |
     | 1. 對話分析偵測到           |                           |
     |    紅旗關鍵字/條件          |                           |
     |                           |                           |
     | 2. red_flag_detected      |                           |
     |  ========================>|                           |
     |  { patientId: "...",      |                           |
     |    sessionId: "...",      |                           |
     |    title: "血尿合併發燒",   |                           |
     |    description: "...",    |                           |
     |    severity: "critical",  |                           |
     |    alertType:             |                           |
     |      "rule_based",        |                           |
     |    triggerKeywords:       |                           |
     |      ["血尿","發燒"],     |                           |
     |    suggestedActions:      |                           |
     |      ["安排急診評估"],     |                           |
     |    triggerMessageId:      |                           |
     |      "msg_125" }          |                           |
     |                           |                           |
     |                           | 3a. WebSocket 即時推送      |
     |                           |  ========================>|
     |                           |  { type: "new_red_flag",  |
     |                           |    id: "...",             |
     |                           |    timestamp: "...",      |
     |                           |    payload: { ... } }     |
     |                           |                           |
     |                           | 3b. FCM 推播通知 (背景)     |
     |                           |  ========================>|
     |                           |  { notification: {        |
     |                           |    title: "紅旗警示",      |
     |                           |    body: "病患王小明:      |
     |                           |     血尿合併發燒" },       |
     |                           |   data: {                 |
     |                           |    type: "red_flag",      |
     |                           |    alertId: "alert_456",  |
     |                           |    deepLink:              |
     |                           |     "uroai://doctor/      |
     |                           |      alert/alert_456"     |
     |                           |   } }                     |
     |                           |                           |
     |                           |                 4. 收到通知 |
     |                           |                   |        |
     |                           |           前景 <--+--> 背景 |
     |                           |             |          |   |
     |                           |     顯示 Banner    系統通知 |
     |                           |     + 音效/震動   列顯示    |
     |                           |             |          |   |
     |                           |         點擊跳轉至          |
     |                           |       AlertDetailScreen    |
```

---

## 7. 頁面 Wireframe 描述

### 7.1 登入頁 (Login Screen)

```
+------------------------------------------+
|              [Status Bar]                |
|                                          |
|                                          |
|            +------------+                |
|            |   LOGO     |                |
|            | 泌尿科 AI   |                |
|            | 語音問診助手 |                |
|            +------------+                |
|                                          |
|  +------------------------------------+  |
|  | [病患登入]  |  [醫師登入]           |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  | (icon) Email                        |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  | (icon) 密碼              (eye icon) |  |
|  +------------------------------------+  |
|                                          |
|  [x] 記住我              忘記密碼? >    |
|                                          |
|  +------------------------------------+  |
|  |          [  登入  ]                 |  |
|  +------------------------------------+  |
|                                          |
|  ------------ 或 ----------------        |
|                                          |
|  +------------------------------------+  |
|  | (G)  使用 Google 帳號登入           |  |
|  +------------------------------------+  |
|  +------------------------------------+  |
|  | (A)  使用 Apple 帳號登入            |  |
|  +------------------------------------+  |
|                                          |
|       還沒有帳號？ 立即註冊 >            |
|                                          |
+------------------------------------------+
```

**佈局說明**:
- 頁面垂直置中佈局
- Logo 區域佔據上方 25% 空間，包含品牌圖示與應用名稱
- 病患/醫師登入以 Segmented Control 切換，切換時表單內容不變
- 輸入框採用 Material Design 風格，帶有左側圖示
- 登入欄位為 Email（非手機號碼）
- 密碼欄位右側有顯示/隱藏切換圖示
- 「記住我」與「忘記密碼」同列，左右對齊
- 登入按鈕為 Primary 色 full-width 按鈕
- OAuth 按鈕以分隔線「或」隔開，帶有品牌圖示
- 底部「立即註冊」為文字連結

---

### 7.2 主訴選擇頁 (Chief Complaint Selection)

```
+------------------------------------------+
| [<]  選擇您的主訴                         |
+------------------------------------------+
|                                          |
|  +------------------------------------+  |
|  | (search) 搜尋症狀...                |  |
|  +------------------------------------+  |
|                                          |
|  -- 泌尿道症狀 --                         |
|  +--------+ +--------+ +--------+       |
|  | 排尿    | | 頻尿    | | 急尿    |       |
|  | 困難    | |        | |        |       |
|  +--------+ +--------+ +--------+       |
|  +--------+ +--------+ +--------+       |
|  | 夜尿    | | 尿失禁  | | 尿流    |       |
|  |        | |        | | 減弱    |       |
|  +--------+ +--------+ +--------+       |
|                                          |
|  -- 血尿與異常 --                          |
|  +--------+ +--------+ +--------+       |
|  | *血尿*  | | 腰痛    | | 下腹    |       |
|  |        | |        | | 疼痛    |       |
|  +--------+ +--------+ +--------+       |
|  +--------+ +--------+                  |
|  | 睪丸    | | 排尿    |                  |
|  | 疼痛    | | 疼痛    |                  |
|  +--------+ +--------+                  |
|                                          |
|  -- 性功能障礙 --                          |
|  +--------+ +--------+ +--------+       |
|  | 勃起    | | 早洩    | | 性慾    |       |
|  | 障礙    | |        | | 降低    |       |
|  +--------+ +--------+ +--------+       |
|                                          |
|  -- 其他 --                               |
|  +--------+ +--------+                  |
|  | 腎結石  | | +自訂   |                  |
|  |        | | 主訴    |                  |
|  +--------+ +--------+                  |
|                                          |
|  已選擇: 血尿 (1/5)                       |
|                                          |
|  +------------------------------------+  |
|  |        [  開始問診  ]               |  |
|  +------------------------------------+  |
+------------------------------------------+
```

**佈局說明**:
- 頂部 Header 含返回按鈕與標題
- 搜尋框位於 Header 下方，固定不隨捲動
- 主訴以分類群組呈現，每組有分類標題（對齊 shared_types.md 預設分類：排尿症狀 / 血尿與異常 / 疼痛 / 腫塊與外觀 / 性功能障礙 / 其他）
- 每個主訴以 Chip 形式呈現，3 列 Grid 佈局
- 選中的 Chip 以填色背景 + 勾選圖示標示 (示意以 * 標記)
- 「+自訂主訴」chip 以虛線邊框呈現
- 底部固定區域顯示已選數量與「開始問診」按鈕
- 按鈕在至少選取 1 個主訴後才可點擊
- 整個主訴區域可垂直捲動

---

### 7.3 語音問診對話頁 (Voice Conversation Screen)

```
+------------------------------------------+
| [<]  AI 語音問診          [結束問診]      |
+------------------------------------------+
| 主訴: 血尿                                |
+------------------------------------------+
|                                          |
|        +---------------------------+     |
|        | AI 助手                    |     |
|        | 您好，我是泌尿科 AI 問診    |     |
|        | 助手。您提到有血尿的症狀，   |     |
|        | 請問這個情況持續多久了？     |     |
|        |            14:30  (play)  |     |
|        +---------------------------+     |
|                                          |
|  +---------------------------+           |
|  | 大概兩個禮拜了              |           |
|  | (confidence: 95%)         |           |
|  | 14:31                     |           |
|  +---------------------------+           |
|                                          |
|        +---------------------------+     |
|        | AI 助手                    |     |
|        | 了解。請問血尿的顏色是偏    |     |
|        | 粉紅色還是深紅色？排尿時     |     |
|        | 會感到疼痛嗎？              |     |
|        |            14:31  (play)  |     |
|        +---------------------------+     |
|                                          |
|  +---------------------------+           |
|  | 深紅色的，而且排尿的時候     |           |
|  | 會痛                       |           |
|  | 14:32                     |           |
|  +---------------------------+           |
|                                          |
|  +- - - - - - - - - - - - - -+           |
|  | 我還有發燒...  (辨識中)     |           |
|  +- - - - - - - - - - - - - -+           |
|                                          |
+------------------------------------------+
|                                          |
|  +------------------------------------+  |
|  |    ||||| (waveform) |||||           |  |
|  +------------------------------------+  |
|  REC 00:03                               |
|                                          |
|              +--------+                  |
|              |  (MIC)  |                  |
|              | 錄音中   |                  |
|              +--------+                  |
|                                          |
+------------------------------------------+
```

**佈局說明**:
- 頂部 Header 含返回按鈕、標題、「結束問診」文字按鈕
- Header 下方顯示本次主訴標籤
- 對話區佔據頁面主體 (約 70%)，以 FlatList 垂直捲動
- AI 訊息氣泡靠左對齊 (灰色背景)，帶有「AI 助手」標籤、時間戳、播放按鈕
- 病患訊息氣泡靠右對齊 (藍色背景)，顯示 STT 辨識結果與信心分數
- 即時辨識中的文字以虛線框 + 斜體顯示
- 底部固定區域包含：聲波視覺化動畫列、錄音指示器 (REC 動畫 + 計時)、麥克風按鈕 (錄音中以紅色脈動環呈現)
- 當 AI 正在回應時，底部顯示「AI 正在回應...」動畫，麥克風按鈕暫時禁用

---

### 7.4 等候室 (Waiting Room)

```
+------------------------------------------+
| [<]  問診等候室                           |
+------------------------------------------+
|                                          |
|                                          |
|           +----------------+             |
|           |   (waiting     |             |
|           |    animation)  |             |
|           |   Lottie 動畫   |             |
|           +----------------+             |
|                                          |
|          您的問診已完成                    |
|        目前正在等待醫師審閱                |
|                                          |
|  +------------------------------------+  |
|  |                                    |  |
|  |  目前排隊位置:  第 3 位              |  |
|  |  預估等候時間:  約 15 分鐘           |  |
|  |  問診狀態:      [等候中]            |  |
|  |                                    |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  | 問診摘要                            |  |
|  +------------------------------------+  |
|  | 主訴: 血尿                          |  |
|  | 問診時間: 14:30 - 14:45             |  |
|  | AI 初步評估: 建議進一步檢查泌尿道     |  |
|  |   感染可能性                        |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  |        [  返回首頁  ]               |  |
|  +------------------------------------+  |
|                                          |
|  (系統會在醫師審閱完成後通知您)            |
|                                          |
+------------------------------------------+
```

**佈局說明**:
- 頁面以垂直居中佈局為主
- 頂部 Lottie 等候動畫 (時鐘或波紋效果)
- 大標題文字說明目前狀態
- 狀態資訊卡片以淡色背景卡片呈現，包含排隊位置、預估等候時間、狀態徽章
- 問診摘要卡片列出本次問診的關鍵資訊
- 底部「返回首頁」按鈕 (secondary 風格)
- 最底部以小字提示系統會推播通知
- 狀態變更時 (例如從「等候中」變為「審閱中」)，頁面即時更新動畫與文字

---

### 7.5 醫師儀表板 (Doctor Dashboard)

```
+------------------------------------------+
| 泌尿科 AI 問診助手        (bell) (avatar) |
+------------------------------------------+
| 早安，陳醫師                 2026-04-10   |
+------------------------------------------+
|                                          |
|  +--------+ +--------+ +--------+ +---+ |
|  | 今日    | | 等候中  | | 紅旗    | |已 | |
|  | 問診數  | | 病患    | | 警示    | |完 | |
|  |   12   | |   3    | |   2    | |成 | |
|  | +20%   | |        | | !!     | | 7 | |
|  +--------+ +--------+ +--------+ +---+ |
|                                          |
|  -- 紅旗警示 (2)              查看全部 > --|
|  +------------------------------------+  |
|  | !! 王小明  血尿合併發燒              |  |
|  |    critical  3 分鐘前   [未處理]    |  |
|  +------------------------------------+  |
|  +------------------------------------+  |
|  | !  李大華  疑似急性尿滯留            |  |
|  |    high     15 分鐘前   [未處理]    |  |
|  +------------------------------------+  |
|                                          |
|  -- 待審閱病患 (3)            查看全部 > --|
|  +------------------------------------+  |
|  | 張三  男 45歲                       |  |
|  | 排尿困難, 頻尿                      |  |
|  | [等候中]  等候 8 分鐘               |  |
|  +------------------------------------+  |
|  +------------------------------------+  |
|  | 林小美  女 62歲                     |  |
|  | 血尿                               |  |
|  | [等候中]  等候 12 分鐘              |  |
|  +------------------------------------+  |
|  +------------------------------------+  |
|  | 陳大明  男 38歲                     |  |
|  | 腰痛, 排尿疼痛                      |  |
|  | [等候中]  等候 20 分鐘              |  |
|  +------------------------------------+  |
|                                          |
+------------------------------------------+
| [儀表板] | [病患] | [警示(2)] | [設定]    |
+------------------------------------------+
```

**佈局說明**:
- 頂部 Header 區域：左側為 App 名稱，右側為通知鈴鐺 (帶 badge) 與使用者頭像
- Header 下方為歡迎訊息與日期
- 統計卡片以水平捲動的 4 格 Grid 呈現，每張卡片包含標題、數值、趨勢指標
- 紅旗卡片以紅色 critical / 橙色 high 左側色條區分，顯示病患名稱、原因、時間、狀態
- 待審閱病患列表以卡片形式呈現，含病患基本資訊、主訴 chip、狀態 badge、等候時間
- 各區塊標題右側帶「查看全部」連結
- 底部 Tab Bar 四個分頁：儀表板、病患、警示 (帶未讀 badge)、設定
- 整頁可垂直捲動，支援下拉刷新

---

### 7.6 即時監控頁 (Live Monitoring)

```
+------------------------------------------+
| [<]  即時監控           [標記為緊急]      |
+------------------------------------------+
| +--------------------------------------+ |
| | 王小明  男 55歲                       | |
| | 主訴: 血尿, 排尿疼痛                  | |
| | 狀態: [問診中]  開始時間: 14:30       | |
| +--------------------------------------+ |
+------------------------------------------+
| [對話]  |  [SOAP 草稿]                   |
+------------------------------------------+
|                                          |
|        +---------------------------+     |
|        | AI 助手                    |     |
|        | 您好，我是泌尿科 AI 問診    |     |
|        | 助手。您提到有血尿和排尿     |     |
|        | 疼痛的症狀...              |     |
|        |            14:30          |     |
|        +---------------------------+     |
|                                          |
|  +---------------------------+           |
|  | 對，最近一兩個禮拜         |           |
|  | 14:31                     |           |
|  +---------------------------+           |
|                                          |
| !! 紅旗: 血尿合併發燒 -- 14:35           |
|                                          |
|        +---------------------------+     |
|        | AI 助手                    |     |
|        | 您提到有發燒的情況，請問    |     |
|        | 體溫大約是幾度？有沒有      |     |
|        | 畏寒的感覺？               |     |
|        |            14:35          |     |
|        +---------------------------+     |
|                                          |
|  +---------------------------+           |
|  | (typing indicator ...)     |           |
|  +---------------------------+           |
|                                          |
+------------------------------------------+
| +------------------------------------+   |
| |  [介入對話]                         |   |
| +------------------------------------+   |
+------------------------------------------+
```

**佈局說明**:
- 頂部 Header 含返回按鈕、標題、「標記為緊急」操作按鈕
- 病患資訊卡片顯示基本資訊、主訴、狀態、開始時間
- Segmented Control 切換「對話」/「SOAP 草稿」檢視
- 對話區域與病患端類似，但醫師端為唯讀觀看模式
- 紅旗警示以紅色橫幅 inline 插入對話流中
- 對話透過 WebSocket 即時更新，自動捲動至最新訊息
- 底部固定區域的「介入對話」按鈕允許醫師向 AI 發送指示
- SOAP 草稿分頁以四區塊 (S/O/A/P) 呈現即時更新的草稿內容

---

### 7.7 SOAP 報告檢視頁 (SOAP Report Viewer)

```
+------------------------------------------+
| [<]  SOAP 報告              [匯出 PDF]   |
+------------------------------------------+
| 病患: 王小明  男 55歲                     |
| 主訴: 血尿, 排尿疼痛                     |
| 問診日期: 2026-04-10  14:30-14:50        |
| 狀態: [待審閱]    AI 信心分數: 87%        |
+------------------------------------------+
|                                          |
|  [v] S - Subjective (主觀)       [編輯]  |
|  +------------------------------------+  |
|  | 55 歲男性，主訴近兩週出現血尿及排    |  |
|  | 尿疼痛。血尿為深紅色，排尿時感到灼   |  |
|  | 熱痛。伴隨發燒 (自述體溫約 38.5 度)  |  |
|  | 及畏寒。否認外傷史。過去病史：高血   |  |
|  | 壓 (服藥控制中)。                    |  |
|  |                                    |  |
|  | [Dr. 陳批註] 需確認是否有結石病史    |  |
|  +------------------------------------+  |
|                                          |
|  [v] O - Objective (客觀)        [編輯]  |
|  +------------------------------------+  |
|  | (AI 語音問診無法取得理學檢查資料，   |  |
|  |  建議臨床補充)                      |  |
|  | - 生命徵象: 待測                     |  |
|  | - 尿液分析: 待檢                     |  |
|  +------------------------------------+  |
|                                          |
|  [>] A - Assessment (評估)       [編輯]  |
|  +------------------------------------+  |
|  | (收合狀態，點擊展開)                 |  |
|  +------------------------------------+  |
|                                          |
|  [>] P - Plan (計畫)             [編輯]  |
|  +------------------------------------+  |
|  | (收合狀態，點擊展開)                 |  |
|  +------------------------------------+  |
|                                          |
+------------------------------------------+
| +----------------+ +------------------+  |
| | [確認報告]      | | [退回修改]       |  |
| +----------------+ +------------------+  |
+------------------------------------------+
```

**佈局說明**:
- 頂部 Header 含返回按鈕、標題、匯出 PDF 按鈕
- 病患資訊摘要區域顯示基本資訊、主訴、日期、狀態、AI 信心分數 (以進度條或百分比顯示)
- 四個 SOAP 區塊以手風琴 (Accordion) 形式呈現
- 每個區塊有展開/收合圖示 ([v] 展開 / [>] 收合)
- 每個區塊右上角有「編輯」按鈕，點擊後內容變為可編輯的結構化表單
- 批註以不同背景色的區塊顯示在該段落下方
- 底部固定操作區域：「確認報告」(primary 按鈕) 與「退回修改」(outline 按鈕)
- 點擊「退回修改」時彈出 Modal 要求輸入退回原因

---

### 7.8 紅旗警示詳情頁 (Red Flag Alert Detail)

```
+------------------------------------------+
| [<]  紅旗警示詳情                         |
+------------------------------------------+
|                                          |
| +--------------------------------------+ |
| | !! 嚴重警示 (CRITICAL)                | |
| |                                      | |
| | 標題: 血尿合併發燒                    | |
| | 描述: 病患出現持續性血尿合併高燒...    | |
| | 偵測方式: rule_based                  | |
| | 觸發時間: 2026-04-10 14:35           | |
| | 嚴重程度: Critical                    | |
| | 觸發關鍵字: 血尿, 發燒, 38.5度        | |
| +--------------------------------------+ |
|                                          |
| -- 病患資訊 --                            |
| +--------------------------------------+ |
| | 姓名: 王小明                          | |
| | 年齡/性別: 55歲 / 男                  | |
| | 聯絡電話: 0912-345-678                | |
| | 主訴: 血尿, 排尿疼痛                  | |
| +--------------------------------------+ |
|                                          |
| -- 觸發對話片段 --                        |
| +--------------------------------------+ |
| | ...                                  | |
| | [病患] 深紅色的，而且排尿的時候        | |
| |        會痛                          | |
| | [AI]   除了血尿和排尿疼痛，還有       | |
| |        其他不舒服嗎？                 | |
| | [病患] **我還有發燒，大概38.5度**     | |  <-- 高亮標記
| |        **還會畏寒**                  | |
| | ...                                  | |
| +--------------------------------------+ |
|                                          |
| -- 建議處置 --                            |
| +--------------------------------------+ |
| | - 安排急診評估                        | |
| | - 排除急性腎盂腎炎                    | |
| | - 安排尿液培養與血液檢查              | |
| +--------------------------------------+ |
|                                          |
| -- 處理備註 --                            |
| +--------------------------------------+ |
| | (textarea) 輸入處理備註...            | |
| +--------------------------------------+ |
|                                          |
| +----------+ +----------+ +-----------+ |
| | [確認     | | [聯繫    | | [轉介     | |
| |  已處理]  | |  病患]   | |  急診]    | |
| +----------+ +----------+ +-----------+ |
|                                          |
+------------------------------------------+
```

**佈局說明**:
- 頂部警示嚴重程度以紅色 (critical) 或橙色 (high) 或黃色 (medium) 背景卡片呈現
- 顯示標題、描述、偵測方式（alert_type）、觸發關鍵字等資訊
- 病患資訊以資料列表形式呈現
- 觸發對話片段以對話氣泡形式呈現，觸發句以黃色高亮背景標記
- 建議處置 (suggested_actions) 以條列式呈現
- 處理備註為可輸入的 TextArea
- 底部三個操作按鈕並排：「確認已處理」(primary)、「聯繫病患」(secondary)、「轉介急診」(danger)
- 整頁可垂直捲動

---

### 7.9 病患列表頁 (Patient List)

```
+------------------------------------------+
|  病患列表                    (sort icon)  |
+------------------------------------------+
|  +------------------------------------+  |
|  | (search) 搜尋病患姓名或主訴...      |  |
|  +------------------------------------+  |
|                                          |
|  [全部(15)] [問診中(5)] [等候中(3)]      |
|  [已完成(7)] [紅旗中止(1)] [已取消(0)]   |
+------------------------------------------+
|                                          |
|  +------------------------------------+  |
|  | !! 王小明  男 55歲          14:30   |  |
|  |    血尿, 排尿疼痛                   |  |
|  |    [問診中] [紅旗中止]  等候 --     |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  |    張三  男 45歲            14:15   |  |
|  |    排尿困難, 頻尿                   |  |
|  |    [等候中]           等候 23 分鐘  |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  |    林小美  女 62歲          14:05   |  |
|  |    血尿                            |  |
|  |    [等候中]           等候 33 分鐘  |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  |    陳大明  男 38歲          13:50   |  |
|  |    腰痛, 排尿疼痛                   |  |
|  |    [已完成]                         |  |
|  +------------------------------------+  |
|                                          |
|  +------------------------------------+  |
|  |    黃小華  男 72歲          13:30   |  |
|  |    頻尿, 夜尿                       |  |
|  |    [已完成]                         |  |
|  +------------------------------------+  |
|                                          |
|  ... (infinite scroll)                   |
|                                          |
+------------------------------------------+
| [儀表板] | [*病患*] | [警示(2)] | [設定]  |
+------------------------------------------+
```

**佈局說明**:
- 頂部固定搜尋框與篩選標籤列
- 篩選標籤以水平捲動的 FilterTabBar 呈現，每個標籤顯示計數
- 篩選狀態對齊 SessionStatus: 全部 / 問診中(in_progress) / 等候中(waiting) / 已完成(completed) / 紅旗中止(aborted_red_flag) / 已取消(cancelled)
- 右上角排序圖示點擊彈出排序選項 BottomSheet
- 列表項目以卡片形式呈現，含紅旗左側色條標記 (若有)
- 每列顯示：姓名、年齡性別、開始時間、主訴 chips、狀態 badge、等候時間
- 列表支援下拉刷新與無限捲動
- 點擊列表項目依狀態導向不同頁面：問診中跳轉即時監控，等候中跳轉 SOAP 報告，已完成跳轉病患歷史

---

## 8. 第三方套件清單

### 8.1 核心框架

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react` | ^18.3.0 | UI 框架核心 |
| `react-native` | ^0.75.0 | 跨平台行動應用框架 |
| `react-dom` | ^18.3.0 | Web 端 React DOM 渲染 |
| `typescript` | ^5.5.0 | TypeScript 編譯器 |

### 8.2 導航

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `@react-navigation/native` | ^6.2.0 | React Native 導航核心 |
| `@react-navigation/stack` | ^6.4.0 | Stack 導航器 (頁面堆疊) |
| `@react-navigation/bottom-tabs` | ^6.6.0 | Bottom Tab 導航器 (底部分頁) |
| `@react-navigation/native-stack` | ^6.10.0 | Native Stack 導航器 (效能較佳) |
| `react-native-screens` | ^3.34.0 | 原生導航畫面容器 |
| `react-native-safe-area-context` | ^4.11.0 | Safe Area 邊距處理 |
| `react-router-dom` | ^6.26.0 | Web 端路由管理 |

### 8.3 狀態管理

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `zustand` | ^4.5.0 | 輕量級狀態管理 |
| `immer` | ^10.1.0 | 不可變狀態更新輔助 (搭配 Zustand middleware) |

### 8.4 網路通訊

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `axios` | ^1.7.0 | HTTP 客戶端 (REST API 呼叫) |
| `react-native-url-polyfill` | ^2.0.0 | React Native URL API polyfill |

### 8.5 音訊處理

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react-native-audio-api` | ^0.4.0 | 音訊錄製與播放 (PCM 擷取) |
| `react-native-live-audio-stream` | ^1.1.0 | 即時音訊串流擷取 (低延遲 PCM) |
| `expo-av` | ^14.0.0 | 音訊/影片播放 (TTS 音訊播放) |
| `react-native-tts` | ^4.1.0 | 原生 TTS 引擎呼叫 |

### 8.6 推播通知

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `@react-native-firebase/app` | ^20.3.0 | Firebase 核心 |
| `@react-native-firebase/messaging` | ^20.3.0 | FCM 推播通知 |
| `@notifee/react-native` | ^9.1.0 | 本地通知管理 (自訂通知樣式) |

### 8.7 本地儲存

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `@react-native-async-storage/async-storage` | ^2.0.0 | 非敏感資料持久化 |
| `react-native-keychain` | ^9.1.0 | 安全儲存 (token、密碼等敏感資料) |

### 8.8 UI 元件庫

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react-native-reanimated` | ^3.15.0 | 高效能動畫引擎 |
| `react-native-gesture-handler` | ^2.18.0 | 手勢處理 (滑動、長按等) |
| `lottie-react-native` | ^7.0.0 | Lottie 動畫播放 (等候動畫、錄音動畫) |
| `react-native-svg` | ^15.7.0 | SVG 渲染 (圖示、聲波) |
| `@gorhom/bottom-sheet` | ^4.6.0 | 底部彈出面板 |
| `react-native-vector-icons` | ^10.2.0 | 圖示庫 |
| `react-native-linear-gradient` | ^2.9.0 | 漸層背景 |

### 8.9 表單與驗證

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react-hook-form` | ^7.53.0 | 表單管理 |
| `zod` | ^3.23.0 | Schema 驗證 (搭配 react-hook-form) |
| `@hookform/resolvers` | ^3.9.0 | react-hook-form 驗證 resolver |

### 8.10 日期時間

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `date-fns` | ^3.6.0 | 日期格式化與計算 |
| `react-native-date-picker` | ^5.0.0 | 日期選擇器 (原生) |

### 8.11 圖表

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `victory-native` | ^41.4.0 | React Native 圖表元件 (儀表板統計圖) |
| `react-native-skia` | ^1.3.0 | Skia 2D 繪圖引擎 (聲波視覺化) |

### 8.12 多語系

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `i18next` | ^23.15.0 | 多語系框架核心 |
| `react-i18next` | ^15.0.0 | React 整合 |
| `react-native-localize` | ^3.2.0 | 裝置語系偵測 |

### 8.13 生物辨識

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react-native-biometrics` | ^3.0.0 | Face ID / Touch ID / 指紋辨識 |

### 8.14 權限管理

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react-native-permissions` | ^4.1.0 | 統一權限請求 API (麥克風、通知等) |

### 8.15 PDF

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react-native-pdf` | ^6.7.0 | PDF 檢視器 |
| `react-native-share` | ^11.0.0 | 系統分享功能 (分享 PDF 報告) |
| `react-native-blob-util` | ^0.21.0 | 檔案下載管理 |

### 8.16 網路與裝置狀態

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `@react-native-community/netinfo` | ^11.4.0 | 網路狀態偵測 |
| `react-native-device-info` | ^11.1.0 | 裝置資訊取得 |

### 8.17 開發工具

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `eslint` | ^9.10.0 | 程式碼品質檢查 |
| `prettier` | ^3.3.0 | 程式碼格式化 |
| `jest` | ^29.7.0 | 測試框架 |
| `@testing-library/react-native` | ^12.7.0 | React Native 元件測試 |
| `@testing-library/react` | ^16.0.0 | Web 端元件測試 |
| `react-native-flipper` | ^0.212.0 | Flipper 除錯工具 |
| `reactotron-react-native` | ^5.1.0 | 狀態與網路偵錯 |

### 8.18 Web Dashboard 專用

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `vite` | ^5.4.0 | Web 端打包工具 |
| `@vitejs/plugin-react` | ^4.3.0 | Vite React 插件 |
| `tailwindcss` | ^3.4.0 | Web 端 CSS 工具 (僅 Web Dashboard) |
| `recharts` | ^2.13.0 | Web 端圖表元件 (儀表板) |

### 8.19 深層連結

| 套件名稱 | 版本 | 用途 |
|---------|------|------|
| `react-native-deep-linking` | ^2.2.0 | Deep Link 處理 |
| `expo-linking` | ^6.3.0 | Universal Links / App Links 處理 |

---

> **文件結尾**
>
> 本規格書涵蓋泌尿科 AI 語音問診助手前端系統的完整設計。所有頁面、元件、狀態管理、導航架構、即時通訊機制、頁面佈局與技術依賴均已詳細定義。型別定義、Enum 值與資料模型以 shared_types.md 為唯一權威來源。開發團隊應以此文件為基準進行實作，並於開發過程中依實際需求進行迭代更新。
