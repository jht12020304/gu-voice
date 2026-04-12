# 泌尿科 AI 語音問診助手 -- API 規格書

> 版本: 1.1.0
> 最後更新: 2026-04-10
> 後端框架: Python FastAPI
> 認證方式: JWT Bearer Token (RS256)
> 即時通訊: WebSocket

> **本文件的型別定義、Enum 值、資料模型以 shared_types.md 為準。**

---

## 目錄

1. [API 總覽](#1-api-總覽)
2. [認證 API](#2-認證-api)
3. [主訴管理 API](#3-主訴管理-api)
4. [問診場次 API](#4-問診場次-api)
5. [對話 API](#5-對話-api)
6. [SOAP 報告 API](#6-soap-報告-api)
7. [紅旗警示 API](#7-紅旗警示-api)
8. [儀表板 API](#8-儀表板-api)
9. [病患管理 API](#9-病患管理-api)
10. [通知 API](#10-通知-api)
11. [稽核日誌 API](#11-稽核日誌-api)
12. [系統管理 API](#12-系統管理-api)
13. [WebSocket API](#13-websocket-api)
14. [共用資料模型](#14-共用資料模型)
15. [錯誤碼對照表](#15-錯誤碼對照表)

---

## 1. API 總覽

### 1.1 Base URL

```
https://{host}/api/v1
```

所有 REST 端點皆以 `/api/v1` 為前綴。未來若有破壞性變更，將以 `/api/v2` 發布新版本，舊版本至少維護 12 個月。

### 1.2 版本策略

- 主版本號 (major) 以 URL 路徑區分 (`/api/v1`, `/api/v2`)
- 非破壞性更新 (新增欄位、新增端點) 不會升版
- 回應中包含 `X-API-Version` 標頭，值為語意版本號 (例如 `1.2.3`)

### 1.3 認證機制

本系統採用 JWT (JSON Web Token) Bearer Token 認證，演算法為 RS256 (非對稱加密，支援 key rotation)。

- 透過 `POST /api/v1/auth/login` 取得 `access_token` 與 `refresh_token`
- 所有需認證的請求必須在 HTTP 標頭中帶入:

```
Authorization: Bearer <access_token>
```

- `access_token` 有效期限: **15 分鐘**
- `refresh_token` 有效期限: 7 天
- Token 過期後需透過 `POST /api/v1/auth/refresh` 換發新 Token

### 1.4 共用標頭 (Common Headers)

| 標頭名稱 | 方向 | 說明 |
|---|---|---|
| `Authorization` | Request | `Bearer <access_token>`，認證用 |
| `Content-Type` | Request | `application/json` (預設) 或 `multipart/form-data` (檔案上傳) |
| `Accept-Language` | Request | 語系偏好，預設 `zh-TW`，支援 `en-US` |
| `X-Request-ID` | Request | 選填，用戶端產生的 UUID，用於追蹤請求 |
| `X-API-Version` | Response | 目前 API 語意版本號 |
| `X-Request-ID` | Response | 回傳請求端帶入的 Request ID，若未帶則由伺服器產生 |
| `X-RateLimit-Limit` | Response | 當前速率限制上限 |
| `X-RateLimit-Remaining` | Response | 剩餘可用次數 |
| `X-RateLimit-Reset` | Response | 速率限制重置時間 (Unix timestamp) |

### 1.5 分頁格式 (Cursor-based Pagination)

本系統所有列表端點均採用 Cursor-based Pagination，避免大量資料時的效能問題。

**請求參數:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 上一頁回傳的 `next_cursor`，首次查詢不帶此參數 |
| `limit` | `integer` | `20` | 每頁筆數，最小 1，最大 100 |

**回應格式:**

```json
{
  "data": [ ... ],
  "pagination": {
    "next_cursor": "eyJpZCI6MTAwfQ==",
    "has_more": true,
    "limit": 20,
    "total_count": 156
  }
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `data` | `array` | 資料陣列 |
| `pagination.next_cursor` | `string \| null` | 下一頁的 cursor，若為 `null` 表示已是最後一頁 |
| `pagination.has_more` | `boolean` | 是否還有更多資料 |
| `pagination.limit` | `integer` | 本次查詢的每頁筆數 |
| `pagination.total_count` | `integer` | 符合條件的總筆數 (近似值) |

### 1.6 標準錯誤回應格式

所有錯誤回應統一使用以下 JSON 結構:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "欄位驗證失敗",
    "details": [
      {
        "field": "email",
        "reason": "格式不正確",
        "value": "not-an-email"
      }
    ],
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-04-10T08:30:00Z"
  }
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `error.code` | `string` | 系統錯誤碼，詳見 [錯誤碼對照表](#15-錯誤碼對照表) |
| `error.message` | `string` | 人類可讀的錯誤訊息 |
| `error.details` | `array \| null` | 詳細錯誤資訊 (例如欄位驗證失敗時) |
| `error.request_id` | `string` | 請求追蹤 ID |
| `error.timestamp` | `string` | 錯誤發生的 ISO 8601 時間戳 |

### 1.7 速率限制 (Rate Limiting)

| 端點類別 | 限制 | 視窗 |
|---|---|---|
| 認證端點 (`/auth/*`) | 10 次 | 每分鐘 |
| 語音上傳 (`/conversations/audio`) | 60 次 | 每分鐘 |
| 一般讀取 (GET) | 120 次 | 每分鐘 |
| 一般寫入 (POST/PUT/PATCH/DELETE) | 60 次 | 每分鐘 |
| WebSocket 訊息 | 30 則 | 每秒 |

超過限制時回傳 `429 Too Many Requests`，回應中包含 `Retry-After` 標頭 (秒數)。

---

## 2. 認證 API

### 2.1 登入

- **方法:** `POST`
- **路徑:** `/api/v1/auth/login`
- **說明:** 以帳號密碼登入，取得 JWT Token
- **需要認證:** 否
- **允許角色:** 不限

**Request Body:**

```json
{
  "email": "string (required, email format)",
  "password": "string (required, min 8 chars)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `email` | `string` | 是 | 使用者電子郵件 |
| `password` | `string` | 是 | 密碼，至少 8 字元 |

**Response Body (200 OK):**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "usr_abc123",
    "email": "doctor@hospital.com",
    "name": "王大明",
    "role": "doctor",
    "department": "泌尿科",
    "created_at": "2026-01-15T10:00:00Z"
  }
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `access_token` | `string` | JWT Access Token |
| `refresh_token` | `string` | JWT Refresh Token |
| `token_type` | `string` | 固定為 `"Bearer"` |
| `expires_in` | `integer` | Access Token 有效秒數 (900 = 15 分鐘) |
| `user` | `User` | 使用者基本資訊 |

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 缺少必填欄位或格式錯誤 |
| `401` | `INVALID_CREDENTIALS` | 帳號或密碼錯誤 |
| `403` | `ACCOUNT_DISABLED` | 帳號已停用 |
| `429` | `RATE_LIMIT_EXCEEDED` | 登入嘗試過於頻繁 |

---

### 2.2 註冊

- **方法:** `POST`
- **路徑:** `/api/v1/auth/register`
- **說明:** 註冊新使用者帳號。病患可自行註冊；醫師與管理員帳號需由管理員建立。
- **需要認證:** 否 (病患註冊) / 是 (建立醫師/管理員帳號)
- **允許角色:** 不限 (病患) / `admin` (醫師/管理員)

**Request Body:**

```json
{
  "email": "string (required, email format)",
  "password": "string (required, min 8 chars, must contain uppercase, lowercase, digit)",
  "name": "string (required, max 100 chars)",
  "role": "string (optional, enum: patient|doctor|admin, default: patient)",
  "phone": "string (optional, E.164 format)",
  "department": "string (optional, max 100 chars, for doctor)",
  "license_number": "string (optional, max 50 chars, required for doctor)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `email` | `string` | 是 | 電子郵件，必須唯一 |
| `password` | `string` | 是 | 密碼，至少 8 字元，需包含大小寫字母與數字 |
| `name` | `string` | 是 | 姓名 |
| `role` | `string` | 否 | 角色，預設 `patient`；設定為 `doctor` 或 `admin` 需管理員權限 |
| `phone` | `string` | 否 | 手機號碼，E.164 格式 (例如 `+886912345678`) |
| `department` | `string` | 否 | 科別 (醫師用) |
| `license_number` | `string` | 條件式 | 醫師執照號碼，`role=doctor` 時必填 |

**Response Body (201 Created):**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "usr_def456",
    "email": "patient@example.com",
    "name": "李小華",
    "role": "patient",
    "created_at": "2026-04-10T08:00:00Z"
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `403` | `FORBIDDEN` | 非管理員嘗試建立醫師/管理員帳號 |
| `409` | `EMAIL_ALREADY_EXISTS` | 電子郵件已被註冊 |

---

### 2.3 更新 Token

- **方法:** `POST`
- **路徑:** `/api/v1/auth/refresh`
- **說明:** 以 Refresh Token 換發新的 Access Token 與 Refresh Token (Refresh Token Rotation)
- **需要認證:** 否 (透過 Request Body 帶入 Refresh Token)
- **允許角色:** 不限

**Request Body:**

```json
{
  "refresh_token": "string (required)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `refresh_token` | `string` | 是 | 有效的 Refresh Token |

**Response Body (200 OK):**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 900
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 缺少 `refresh_token` 欄位 |
| `401` | `TOKEN_EXPIRED` | Refresh Token 已過期 |
| `401` | `TOKEN_INVALID` | Refresh Token 無效或已被撤銷 |
| `401` | `TOKEN_REUSE_DETECTED` | 偵測到 Refresh Token 重複使用，所有 Token 將被撤銷 (安全機制) |

---

### 2.4 登出

- **方法:** `POST`
- **路徑:** `/api/v1/auth/logout`
- **說明:** 登出並撤銷目前的 Refresh Token
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Request Body:**

```json
{
  "refresh_token": "string (optional)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `refresh_token` | `string` | 否 | 欲撤銷的 Refresh Token；若未提供，將撤銷該使用者所有 Refresh Token |

**Response Body (200 OK):**

```json
{
  "message": "登出成功"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未提供有效的 Access Token |

---

### 2.5 取得目前使用者資訊

- **方法:** `GET`
- **路徑:** `/api/v1/auth/me`
- **說明:** 取得目前已認證使用者的完整資料
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Request Body:** 無

**Response Body (200 OK):**

```json
{
  "id": "usr_abc123",
  "email": "doctor@hospital.com",
  "name": "王大明",
  "role": "doctor",
  "phone": "+886912345678",
  "department": "泌尿科",
  "license_number": "DOC-2020-12345",
  "is_active": true,
  "created_at": "2026-01-15T10:00:00Z",
  "updated_at": "2026-03-20T14:30:00Z",
  "last_login_at": "2026-04-10T08:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未提供有效的 Access Token |
| `401` | `TOKEN_EXPIRED` | Access Token 已過期 |

---

### 2.6 更新目前使用者資訊

- **方法:** `PUT`
- **路徑:** `/api/v1/auth/me`
- **說明:** 更新目前已認證使用者的個人資料
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Request Body:**

```json
{
  "name": "string (optional, max 100 chars)",
  "phone": "string (optional, E.164 format)",
  "department": "string (optional, max 100 chars)",
  "password": "string (optional, min 8 chars)",
  "current_password": "string (required if password is provided)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | `string` | 否 | 姓名 |
| `phone` | `string` | 否 | 手機號碼 |
| `department` | `string` | 否 | 科別 (醫師用) |
| `password` | `string` | 否 | 新密碼 |
| `current_password` | `string` | 條件式 | 變更密碼時，必須提供目前密碼 |

**Response Body (200 OK):**

```json
{
  "id": "usr_abc123",
  "email": "doctor@hospital.com",
  "name": "王大明",
  "role": "doctor",
  "phone": "+886912345678",
  "department": "泌尿科",
  "license_number": "DOC-2020-12345",
  "is_active": true,
  "created_at": "2026-01-15T10:00:00Z",
  "updated_at": "2026-04-10T09:00:00Z",
  "last_login_at": "2026-04-10T08:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未提供有效的 Access Token |
| `401` | `INVALID_CREDENTIALS` | 目前密碼不正確 (變更密碼時) |

---

### 2.7 忘記密碼

- **方法:** `POST`
- **路徑:** `/api/v1/auth/forgot-password`
- **說明:** 發送密碼重設連結至使用者的電子郵件
- **需要認證:** 否
- **允許角色:** 不限

**Request Body:**

```json
{
  "email": "string (required, email format)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `email` | `string` | 是 | 使用者電子郵件 |

**Response Body (200 OK):**

```json
{
  "message": "若此電子郵件已註冊，密碼重設連結已寄出"
}
```

> **注意:** 無論電子郵件是否存在，皆回傳相同訊息，避免帳號列舉攻擊。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 電子郵件格式不正確 |
| `429` | `RATE_LIMIT_EXCEEDED` | 請求過於頻繁 |

---

### 2.8 重設密碼

- **方法:** `POST`
- **路徑:** `/api/v1/auth/reset-password`
- **說明:** 使用重設 Token 設定新密碼
- **需要認證:** 否
- **允許角色:** 不限

**Request Body:**

```json
{
  "token": "string (required, reset token from email)",
  "new_password": "string (required, min 8 chars, must contain uppercase, lowercase, digit)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `token` | `string` | 是 | 密碼重設 Token (從電子郵件取得) |
| `new_password` | `string` | 是 | 新密碼，至少 8 字元，需包含大小寫字母與數字 |

**Response Body (200 OK):**

```json
{
  "message": "密碼重設成功，請使用新密碼登入"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 密碼格式不符合要求 |
| `401` | `TOKEN_INVALID` | 重設 Token 無效 |
| `401` | `TOKEN_EXPIRED` | 重設 Token 已過期 |

---

## 3. 主訴管理 API

### 3.1 取得主訴列表

- **方法:** `GET`
- **路徑:** `/api/v1/complaints`
- **說明:** 取得所有主訴項目，包含系統預設與自訂項目，支援篩選與搜尋
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `category` | `string` | `null` | 依分類篩選 (例如 `排尿症狀`, `疼痛`, `血尿與異常`) |
| `is_default` | `boolean` | `null` | `true` (系統預設) 或 `false` (自訂) |
| `search` | `string` | `null` | 關鍵字搜尋 (模糊比對主訴名稱與描述) |
| `is_active` | `boolean` | `true` | 僅顯示啟用中的項目 |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "cmp_001",
      "name": "頻尿",
      "name_en": "Frequent Urination",
      "description": "排尿次數異常增加，日間超過 8 次或夜間超過 2 次",
      "category": "排尿症狀",
      "is_default": true,
      "follow_up_questions": [
        "每天大約排尿幾次?",
        "夜間需要起床排尿幾次?",
        "每次排尿量大約多少?",
        "是否伴隨急尿感?"
      ],
      "red_flag_keywords": ["血尿", "發燒", "劇烈疼痛"],
      "is_active": true,
      "display_order": 1,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6ImNtcF8wMjAifQ==",
    "has_more": true,
    "limit": 20,
    "total_count": 45
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

### 3.2 取得系統預設主訴

- **方法:** `GET`
- **路徑:** `/api/v1/complaints/defaults`
- **說明:** 僅取得系統預設的主訴項目 (不含自訂)，常用於前端初始化選單
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `category` | `string` | `null` | 依分類篩選 |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "cmp_001",
      "name": "頻尿",
      "name_en": "Frequent Urination",
      "description": "排尿次數異常增加",
      "category": "排尿症狀",
      "is_default": true,
      "follow_up_questions": [...],
      "red_flag_keywords": [...],
      "is_active": true,
      "display_order": 1,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": null,
    "has_more": false,
    "limit": 100,
    "total_count": 25
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |

---

### 3.3 取得單一主訴

- **方法:** `GET`
- **路徑:** `/api/v1/complaints/{id}`
- **說明:** 依 ID 取得單一主訴的完整資訊
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 主訴 ID (例如 `cmp_001`) |

**Response Body (200 OK):**

```json
{
  "id": "cmp_001",
  "name": "頻尿",
  "name_en": "Frequent Urination",
  "description": "排尿次數異常增加，日間超過 8 次或夜間超過 2 次",
  "category": "排尿症狀",
  "is_default": true,
  "follow_up_questions": [
    "每天大約排尿幾次?",
    "夜間需要起床排尿幾次?",
    "每次排尿量大約多少?",
    "是否伴隨急尿感?"
  ],
  "red_flag_keywords": ["血尿", "發燒", "劇烈疼痛"],
  "is_active": true,
  "display_order": 1,
  "created_by": null,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `404` | `NOT_FOUND` | 指定 ID 的主訴不存在 |

---

### 3.4 建立自訂主訴

- **方法:** `POST`
- **路徑:** `/api/v1/complaints`
- **說明:** 建立新的自訂主訴項目
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Request Body:**

```json
{
  "name": "string (required, max 100 chars)",
  "name_en": "string (optional, max 100 chars)",
  "description": "string (optional, max 500 chars)",
  "category": "string (required)",
  "follow_up_questions": ["string"],
  "red_flag_keywords": ["string"],
  "display_order": "integer (optional, default: 0)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | `string` | 是 | 主訴名稱 (中文) |
| `name_en` | `string` | 否 | 主訴名稱 (英文) |
| `description` | `string` | 否 | 詳細描述 |
| `category` | `string` | 是 | 所屬分類 |
| `follow_up_questions` | `string[]` | 否 | AI 應追問的問題列表 |
| `red_flag_keywords` | `string[]` | 否 | 觸發紅旗警示的關鍵字 |
| `display_order` | `integer` | 否 | 顯示排序，數字越小排越前面 |

**Response Body (201 Created):**

```json
{
  "id": "cmp_046",
  "name": "陰囊腫脹",
  "name_en": "Scrotal Swelling",
  "description": "陰囊出現腫脹或腫塊",
  "category": "腫塊與外觀",
  "is_default": false,
  "follow_up_questions": [
    "腫脹持續多久了?",
    "是否伴隨疼痛?",
    "腫脹的大小是否有變化?"
  ],
  "red_flag_keywords": ["劇烈疼痛", "突然發生"],
  "is_active": true,
  "display_order": 0,
  "created_by": "usr_abc123",
  "created_at": "2026-04-10T09:00:00Z",
  "updated_at": "2026-04-10T09:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `409` | `COMPLAINT_ALREADY_EXISTS` | 同名主訴已存在 |

---

### 3.5 更新主訴

- **方法:** `PUT`
- **路徑:** `/api/v1/complaints/{id}`
- **說明:** 更新指定主訴的內容。系統預設主訴僅限管理員修改。
- **需要認證:** 是
- **允許角色:** `doctor` (僅自訂), `admin` (全部)

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 主訴 ID |

**Request Body:**

```json
{
  "name": "string (optional, max 100 chars)",
  "name_en": "string (optional, max 100 chars)",
  "description": "string (optional, max 500 chars)",
  "category": "string (optional)",
  "follow_up_questions": ["string"],
  "red_flag_keywords": ["string"],
  "display_order": "integer (optional)",
  "is_active": "boolean (optional)"
}
```

**Response Body (200 OK):**

回傳更新後的完整主訴物件 (格式同 3.3)。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權修改此主訴 (例如醫師嘗試修改系統預設主訴) |
| `404` | `NOT_FOUND` | 指定 ID 的主訴不存在 |

---

### 3.6 刪除主訴 (軟刪除)

- **方法:** `DELETE`
- **路徑:** `/api/v1/complaints/{id}`
- **說明:** 軟刪除指定主訴 (設定 `is_active` 為 `false`，不實際刪除資料)。系統預設主訴僅限管理員刪除。
- **需要認證:** 是
- **允許角色:** `doctor` (僅自訂), `admin` (全部)

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 主訴 ID |

**Response Body (200 OK):**

```json
{
  "message": "主訴已停用",
  "id": "cmp_046"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權刪除此主訴 |
| `404` | `NOT_FOUND` | 指定 ID 的主訴不存在 |
| `409` | `COMPLAINT_IN_USE` | 主訴正在進行中的場次使用，無法停用 |

---

### 3.7 取得主訴分類列表

- **方法:** `GET`
- **路徑:** `/api/v1/complaints/categories`
- **說明:** 取得所有主訴分類及其下主訴數量
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "name": "排尿症狀",
      "name_en": "Voiding Symptoms",
      "count": 8,
      "description": "與排尿功能相關的症狀"
    },
    {
      "name": "血尿與異常",
      "name_en": "Hematuria and Abnormalities",
      "count": 3,
      "description": "尿液中出現血液或其他異常"
    },
    {
      "name": "疼痛",
      "name_en": "Pain",
      "count": 6,
      "description": "泌尿系統相關疼痛症狀"
    },
    {
      "name": "腫塊與外觀",
      "name_en": "Mass and Appearance",
      "count": 5,
      "description": "泌尿生殖系統腫塊或外觀異常"
    },
    {
      "name": "性功能障礙",
      "name_en": "Sexual Dysfunction",
      "count": 4,
      "description": "男性性功能相關問題"
    },
    {
      "name": "其他",
      "name_en": "Others",
      "count": 4,
      "description": "其他泌尿科相關症狀"
    }
  ]
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |

---

### 3.8 批次重新排序主訴

- **方法:** `PATCH`
- **路徑:** `/api/v1/complaints/reorder`
- **說明:** 批次更新多個主訴的顯示排序 (display_order)
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Request Body:**

```json
{
  "items": [
    { "id": "cmp_001", "display_order": 1 },
    { "id": "cmp_002", "display_order": 2 },
    { "id": "cmp_003", "display_order": 3 }
  ]
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `items` | `array` | 是 | 主訴 ID 與新排序值的配對列表 |
| `items[].id` | `string` | 是 | 主訴 ID |
| `items[].display_order` | `integer` | 是 | 新的顯示排序值 |

**Response Body (200 OK):**

```json
{
  "message": "排序已更新",
  "updated_count": 3
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `404` | `NOT_FOUND` | 部分主訴 ID 不存在 |

---

## 4. 問診場次 API

### 4.1 建立新場次

- **方法:** `POST`
- **路徑:** `/api/v1/sessions`
- **說明:** 建立新的問診場次。病患開始語音問診前必須先建立場次。
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Request Body:**

```json
{
  "patient_id": "string (required for doctor/admin, auto-filled for patient)",
  "chief_complaint_id": "string (required, UUID of chief complaint)",
  "chief_complaint_text": "string (optional, max 200 chars, for custom complaint text)",
  "doctor_id": "string (optional, assigned later if not specified)",
  "language": "string (optional, enum: zh-TW|en-US, default: zh-TW)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `patient_id` | `string` | 條件式 | 病患 ID (FK -> patients)，病患角色自動填入，醫師/管理員必填 |
| `chief_complaint_id` | `string` | 是 | 主訴 ID (UUID)，單一主訴 |
| `chief_complaint_text` | `string` | 否 | 主訴文字描述 (自訂主訴時使用) |
| `doctor_id` | `string` | 否 | 指定醫師 ID，未指定則進入待分配佇列 |
| `language` | `string` | 否 | 問診語言，預設繁體中文 |

**Response Body (201 Created):**

```json
{
  "id": "ses_20260410_001",
  "patient_id": "pat_def456",
  "patient": {
    "id": "pat_def456",
    "name": "李小華",
    "gender": "female",
    "date_of_birth": "1995-08-20"
  },
  "doctor_id": "usr_abc123",
  "doctor": {
    "id": "usr_abc123",
    "name": "王大明"
  },
  "chief_complaint_id": "cmp_001",
  "chief_complaint_text": null,
  "chief_complaint": {
    "id": "cmp_001",
    "name": "頻尿"
  },
  "status": "waiting",
  "language": "zh-TW",
  "red_flag": false,
  "red_flag_reason": null,
  "duration_seconds": null,
  "started_at": null,
  "completed_at": null,
  "created_at": "2026-04-10T09:00:00Z",
  "updated_at": "2026-04-10T09:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `404` | `PATIENT_NOT_FOUND` | 指定的病患 ID 不存在 |
| `404` | `COMPLAINT_NOT_FOUND` | 指定的主訴 ID 不存在 |
| `409` | `SESSION_ALREADY_ACTIVE` | 該病患已有進行中的場次 |

---

### 4.2 取得場次列表

- **方法:** `GET`
- **路徑:** `/api/v1/sessions`
- **說明:** 取得場次列表，支援多條件篩選。病患僅能查看自己的場次。
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `status` | `string` | `null` | 依狀態篩選，支援逗號分隔多值 (例如 `waiting,in_progress`) |
| `patient_id` | `string` | `null` | 依病患 ID 篩選 |
| `doctor_id` | `string` | `null` | 依醫師 ID 篩選 |
| `date_from` | `string` | `null` | 起始日期 (ISO 8601，例如 `2026-04-01`) |
| `date_to` | `string` | `null` | 結束日期 (ISO 8601) |
| `sort_by` | `string` | `created_at` | 排序欄位: `created_at`, `updated_at`, `status` |
| `sort_order` | `string` | `desc` | 排序方向: `asc`, `desc` |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "ses_20260410_001",
      "patient_id": "pat_def456",
      "patient": {
        "id": "pat_def456",
        "name": "李小華",
        "gender": "female",
        "date_of_birth": "1995-08-20"
      },
      "doctor_id": "usr_abc123",
      "doctor": {
        "id": "usr_abc123",
        "name": "王大明"
      },
      "chief_complaint_id": "cmp_001",
      "chief_complaint": {
        "id": "cmp_001",
        "name": "頻尿"
      },
      "status": "in_progress",
      "language": "zh-TW",
      "red_flag": false,
      "red_flag_reason": null,
      "duration_seconds": 600,
      "started_at": "2026-04-10T09:05:00Z",
      "completed_at": null,
      "created_at": "2026-04-10T09:00:00Z",
      "updated_at": "2026-04-10T09:15:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6InNlc18yMDI2MDQwOV8wMTAifQ==",
    "has_more": true,
    "limit": 20,
    "total_count": 87
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 查詢參數格式錯誤 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 病患嘗試查看他人場次 |

---

### 4.3 取得場次詳情

- **方法:** `GET`
- **路徑:** `/api/v1/sessions/{id}`
- **說明:** 取得指定場次的完整詳細資料
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |

**Response Body (200 OK):**

```json
{
  "id": "ses_20260410_001",
  "patient_id": "pat_def456",
  "patient": {
    "id": "pat_def456",
    "name": "李小華",
    "gender": "female",
    "date_of_birth": "1995-08-20",
    "phone": "+886987654321"
  },
  "doctor_id": "usr_abc123",
  "doctor": {
    "id": "usr_abc123",
    "name": "王大明"
  },
  "chief_complaint_id": "cmp_001",
  "chief_complaint_text": null,
  "chief_complaint": {
    "id": "cmp_001",
    "name": "頻尿",
    "category": "排尿症狀"
  },
  "status": "in_progress",
  "language": "zh-TW",
  "red_flag": false,
  "red_flag_reason": null,
  "duration_seconds": 600,
  "started_at": "2026-04-10T09:05:00Z",
  "completed_at": null,
  "created_at": "2026-04-10T09:00:00Z",
  "updated_at": "2026-04-10T09:15:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權存取此場次 |
| `404` | `NOT_FOUND` | 場次不存在 |

---

### 4.4 更新場次狀態

- **方法:** `PATCH`
- **路徑:** `/api/v1/sessions/{id}/status`
- **說明:** 更新場次狀態。狀態轉移需遵循合法流程 (見狀態機說明)。
- **需要認證:** 是
- **允許角色:** `patient` (僅限取消), `doctor`, `admin`

**合法狀態轉移 (5 種狀態):**

```
waiting -> in_progress     (場次開始)
waiting -> cancelled       (取消)
in_progress -> completed   (完成問診)
in_progress -> aborted_red_flag  (紅旗中止)
in_progress -> cancelled   (取消)
```

> **注意:** `completed`、`aborted_red_flag`、`cancelled` 均為終態，不可再轉移。

**狀態轉移圖:**

```
                    ┌──────────────────────────────────────┐
                    │                                      │
  [建立場次]        │                                      │
      │             │                                      │
      v             │                                      │
  ┌─────────┐   手動取消   ┌──────────────┐   正常結束   ┌───────────┐
  │ waiting │────────────>│  cancelled   │<────────────│ completed │
  └────┬────┘             └──────────────┘             └───────────┘
       │                         ^                          ^
       │ 開始對話                 │ 手動取消                  │ 對話結束
       v                         │                          │
  ┌─────────────┐────────────────┘                          │
  │ in_progress │───────────────────────────────────────────┘
  └──────┬──────┘
         │ 紅旗偵測觸發
         v
  ┌──────────────────┐
  │ aborted_red_flag │
  └──────────────────┘
```

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |

**Request Body:**

```json
{
  "status": "string (required, enum: waiting|in_progress|completed|aborted_red_flag|cancelled)",
  "reason": "string (optional, required when cancelling, max 500 chars)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `status` | `string` | 是 | 目標狀態 |
| `reason` | `string` | 條件式 | 取消原因 (狀態設為 `cancelled` 時必填) |

**Response Body (200 OK):**

```json
{
  "id": "ses_20260410_001",
  "status": "completed",
  "previous_status": "in_progress",
  "updated_at": "2026-04-10T09:30:00Z",
  "completed_at": "2026-04-10T09:30:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `409` | `INVALID_STATUS_TRANSITION` | 不合法的狀態轉移 (例如 `completed` -> `in_progress`) |
| `422` | `VALIDATION_ERROR` | 取消時未提供原因 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權更新此場次狀態 |
| `404` | `NOT_FOUND` | 場次不存在 |

---

### 4.5 取得場次對話記錄

- **方法:** `GET`
- **路徑:** `/api/v1/sessions/{id}/conversations`
- **說明:** 取得指定場次的完整對話記錄 (逐字稿)
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `50` | 每頁筆數 (1-200) |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "msg_001",
      "session_id": "ses_20260410_001",
      "sequence_number": 1,
      "role": "assistant",
      "content_text": "您好，我是泌尿科 AI 問診助手。請問您今天主要不舒服的地方是什麼?",
      "audio_url": "https://storage.example.com/tts/msg_001.mp3",
      "audio_duration_seconds": 3.2,
      "stt_confidence": null,
      "red_flag_detected": false,
      "metadata": {
        "tts_engine": "google-neural2",
        "tts_voice": "cmn-TW-Wavenet-A",
        "llm_model": "claude-sonnet-4-20250514"
      },
      "created_at": "2026-04-10T09:05:00Z"
    },
    {
      "id": "msg_002",
      "session_id": "ses_20260410_001",
      "sequence_number": 2,
      "role": "patient",
      "content_text": "我最近頻尿很嚴重，晚上要起來好幾次",
      "audio_url": "https://storage.example.com/audio/msg_002.webm",
      "audio_duration_seconds": 4.5,
      "stt_confidence": 0.95,
      "red_flag_detected": false,
      "metadata": {
        "stt_engine": "google-chirp-v2",
        "stt_language": "zh-TW",
        "audio_format": "wav",
        "audio_sample_rate": 16000
      },
      "created_at": "2026-04-10T09:05:15Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6Im1zZ18wNTAifQ==",
    "has_more": false,
    "limit": 50,
    "total_count": 12
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權存取此場次 |
| `404` | `NOT_FOUND` | 場次不存在 |

---

### 4.6 取消場次

- **方法:** `DELETE`
- **路徑:** `/api/v1/sessions/{id}`
- **說明:** 取消指定場次。等同於將狀態設為 `cancelled`。僅允許取消 `waiting` 或 `in_progress` 狀態的場次。
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |

**Request Body:**

```json
{
  "reason": "string (required, max 500 chars)"
}
```

**Response Body (200 OK):**

```json
{
  "id": "ses_20260410_001",
  "status": "cancelled",
  "reason": "病患要求取消",
  "cancelled_at": "2026-04-10T09:10:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 未提供取消原因 |
| `409` | `INVALID_STATUS_TRANSITION` | 場次狀態不允許取消 (例如已完成) |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權取消此場次 |
| `404` | `NOT_FOUND` | 場次不存在 |

---

## 5. 對話 API

### 5.1 新增文字訊息

- **方法:** `POST`
- **路徑:** `/api/v1/sessions/{id}/conversations`
- **說明:** 以文字方式新增對話訊息 (非語音備用方案)。伺服器將回傳 AI 的回覆訊息。
- **需要認證:** 是
- **允許角色:** `patient` (僅自己的場次), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |

**Request Body:**

```json
{
  "content_text": "string (required, max 2000 chars)",
  "role": "string (optional, enum: patient|assistant|system, auto-detected from auth)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `content_text` | `string` | 是 | 訊息內容 |
| `role` | `string` | 否 | 發話者角色，預設依認證身份自動判定 |

**Response Body (201 Created):**

```json
{
  "user_message": {
    "id": "msg_013",
    "session_id": "ses_20260410_001",
    "sequence_number": 13,
    "role": "patient",
    "content_text": "我尿尿的時候會痛",
    "audio_url": null,
    "audio_duration_seconds": null,
    "stt_confidence": null,
    "red_flag_detected": false,
    "metadata": {},
    "created_at": "2026-04-10T09:20:00Z"
  },
  "ai_response": {
    "id": "msg_014",
    "session_id": "ses_20260410_001",
    "sequence_number": 14,
    "role": "assistant",
    "content_text": "了解，排尿時會疼痛。請問疼痛的感覺是灼熱感還是刺痛感呢? 疼痛主要是在排尿的開始、中間還是結束的時候?",
    "audio_url": "https://storage.example.com/tts/msg_014.mp3",
    "audio_duration_seconds": 5.1,
    "stt_confidence": null,
    "red_flag_detected": false,
    "metadata": {
      "llm_model": "claude-sonnet-4-20250514",
      "llm_tokens_used": 128,
      "tts_engine": "google-neural2",
      "tts_voice": "cmn-TW-Wavenet-A"
    },
    "created_at": "2026-04-10T09:20:02Z"
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 訊息內容為空或超過長度限制 |
| `409` | `SESSION_NOT_ACTIVE` | 場次狀態非 `in_progress` |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權在此場次中發送訊息 |
| `404` | `NOT_FOUND` | 場次不存在 |
| `503` | `AI_SERVICE_UNAVAILABLE` | AI 服務暫時不可用 |

---

### 5.2 取得單一訊息

- **方法:** `GET`
- **路徑:** `/api/v1/sessions/{id}/conversations/{msgId}`
- **說明:** 取得指定對話訊息的詳細資料
- **需要認證:** 是
- **允許角色:** `patient` (僅自己的場次), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |
| `msgId` | `string` | 訊息 ID |

**Response Body (200 OK):**

```json
{
  "id": "msg_002",
  "session_id": "ses_20260410_001",
  "sequence_number": 2,
  "role": "patient",
  "content_text": "我最近頻尿很嚴重，晚上要起來好幾次",
  "audio_url": "https://storage.example.com/audio/msg_002.webm",
  "audio_duration_seconds": 4.5,
  "stt_confidence": 0.95,
  "red_flag_detected": false,
  "metadata": {
    "stt_engine": "google-chirp-v2",
    "stt_language": "zh-TW",
    "audio_format": "wav",
    "audio_sample_rate": 16000
  },
  "created_at": "2026-04-10T09:05:15Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權存取此訊息 |
| `404` | `NOT_FOUND` | 場次或訊息不存在 |

---

### 5.3 上傳語音片段

- **方法:** `POST`
- **路徑:** `/api/v1/sessions/{id}/conversations/audio`
- **說明:** 上傳語音片段。伺服器將進行 STT (語音轉文字) 並產生 AI 回覆。此端點為非即時語音上傳方案，即時語音串流請使用 WebSocket。
- **需要認證:** 是
- **允許角色:** `patient` (僅自己的場次)
- **Content-Type:** `multipart/form-data`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |

**Request Body (multipart/form-data):**

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `audio` | `file` | 是 | 語音檔案，支援格式: `audio/webm`, `audio/wav`, `audio/mp3`, `audio/ogg`。最大 10MB。 |
| `duration_ms` | `integer` | 否 | 音訊時長 (毫秒)，由客戶端提供，用於驗證 |
| `sample_rate` | `integer` | 否 | 取樣率 (Hz)，預設 16000 |

**Response Body (201 Created):**

```json
{
  "user_message": {
    "id": "msg_015",
    "session_id": "ses_20260410_001",
    "sequence_number": 15,
    "role": "patient",
    "content_text": "尿尿的時候會有灼熱感，而且尿很少",
    "audio_url": "https://storage.example.com/audio/msg_015.webm",
    "audio_duration_seconds": 3.8,
    "stt_confidence": 0.92,
    "red_flag_detected": false,
    "metadata": {
      "stt_engine": "google-chirp-v2",
      "stt_language": "zh-TW",
      "audio_format": "webm",
      "audio_sample_rate": 16000,
      "file_size_bytes": 45600
    },
    "created_at": "2026-04-10T09:22:00Z"
  },
  "ai_response": {
    "id": "msg_016",
    "session_id": "ses_20260410_001",
    "sequence_number": 16,
    "role": "assistant",
    "content_text": "排尿時有灼熱感且尿量減少，這可能是泌尿道感染的徵兆。請問您是否有以下症狀: 發燒、腰痛、或尿液顏色改變?",
    "audio_url": "https://storage.example.com/tts/msg_016.mp3",
    "audio_duration_seconds": 6.2,
    "stt_confidence": null,
    "red_flag_detected": false,
    "metadata": {
      "llm_model": "claude-sonnet-4-20250514",
      "llm_tokens_used": 156,
      "tts_engine": "google-neural2",
      "tts_voice": "cmn-TW-Wavenet-A"
    },
    "created_at": "2026-04-10T09:22:03Z"
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 檔案格式不支援或超過大小限制 |
| `409` | `SESSION_NOT_ACTIVE` | 場次狀態非 `in_progress` |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權在此場次上傳語音 |
| `404` | `NOT_FOUND` | 場次不存在 |
| `413` | `FILE_TOO_LARGE` | 檔案超過 10MB 限制 |
| `415` | `UNSUPPORTED_MEDIA_TYPE` | 不支援的音訊格式 |
| `503` | `STT_SERVICE_UNAVAILABLE` | 語音辨識服務暫時不可用 |
| `503` | `AI_SERVICE_UNAVAILABLE` | AI 服務暫時不可用 |

---

## 6. SOAP 報告 API

### 6.1 觸發 SOAP 報告生成

- **方法:** `POST`
- **路徑:** `/api/v1/sessions/{id}/report`
- **說明:** 依指定場次的對話記錄，觸發 AI 生成 SOAP 格式報告。場次必須處於 `completed` 狀態。生成為非同步作業，回傳報告 ID 與狀態。
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 場次 ID |

**Request Body:**

```json
{
  "regenerate": "boolean (optional, default: false)",
  "additional_notes": "string (optional, max 2000 chars)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `regenerate` | `boolean` | 否 | 若已有報告，是否重新生成 |
| `additional_notes` | `string` | 否 | 醫師補充備註，將納入報告生成 |

**Response Body (202 Accepted):**

```json
{
  "report_id": "rpt_20260410_001",
  "session_id": "ses_20260410_001",
  "status": "generating",
  "estimated_completion_seconds": 15,
  "created_at": "2026-04-10T09:35:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `409` | `SESSION_NOT_COMPLETED` | 場次尚未完成 |
| `409` | `INSUFFICIENT_CONVERSATION` | 對話內容不足，無法生成有意義的報告 (至少需 4 輪對話) |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `404` | `NOT_FOUND` | 場次不存在 |
| `409` | `REPORT_ALREADY_EXISTS` | 報告已存在且未設定 `regenerate: true` |
| `503` | `AI_SERVICE_UNAVAILABLE` | AI 服務暫時不可用 |

---

### 6.2 取得報告

- **方法:** `GET`
- **路徑:** `/api/v1/reports/{id}`
- **說明:** 取得指定 SOAP 報告的完整內容
- **需要認證:** 是
- **允許角色:** `patient` (僅自己的報告), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 報告 ID |

**Response Body (200 OK):**

```json
{
  "id": "rpt_20260410_001",
  "session_id": "ses_20260410_001",
  "patient_id": "pat_def456",
  "patient": {
    "id": "pat_def456",
    "name": "李小華",
    "gender": "female",
    "date_of_birth": "1995-08-20"
  },
  "doctor_id": "usr_abc123",
  "doctor": {
    "id": "usr_abc123",
    "name": "王大明"
  },
  "status": "generated",
  "soap": {
    "subjective": {
      "chief_complaint": "頻尿、排尿疼痛",
      "hpi": {
        "onset": "一週前",
        "location": "排尿時",
        "duration": "持續一週",
        "characteristics": "灼熱感",
        "severity": "中度",
        "aggravating_factors": [],
        "relieving_factors": [],
        "associated_symptoms": ["頻尿", "急尿", "尿量減少"],
        "timing": "每次排尿",
        "context": "無特殊誘因"
      },
      "past_medical_history": {
        "conditions": [],
        "surgeries": [],
        "hospitalizations": []
      },
      "medication_history": {
        "current": [],
        "past": [],
        "otc": []
      },
      "system_review": {
        "constitutional": "無發燒、體重下降",
        "genitourinary": "頻尿、排尿灼熱感、尿量減少",
        "gastrointestinal": "正常",
        "musculoskeletal": "正常"
      },
      "social_history": {
        "smoking": "無",
        "alcohol": "偶爾",
        "occupation": "上班族"
      }
    },
    "objective": {
      "vital_signs": {
        "blood_pressure": null,
        "heart_rate": null,
        "respiratory_rate": null,
        "temperature": null,
        "spo2": null
      },
      "physical_exam": {
        "general": "由 AI 問診收集，未進行理學檢查"
      },
      "lab_results": [],
      "imaging_results": []
    },
    "assessment": {
      "differential_diagnoses": [
        {
          "diagnosis": "泌尿道感染",
          "icd10": "N39.0",
          "probability": "high",
          "reasoning": "頻尿合併排尿灼熱感，女性好發"
        },
        {
          "diagnosis": "膀胱過動症",
          "icd10": "N32.81",
          "probability": "medium",
          "reasoning": "頻尿、急尿，但有灼熱感較支持感染"
        },
        {
          "diagnosis": "間質性膀胱炎",
          "icd10": "N30.1",
          "probability": "low",
          "reasoning": "需排除感染後進一步評估"
        }
      ],
      "clinical_impression": "疑似泌尿道感染，頻尿合併排尿灼熱感"
    },
    "plan": {
      "recommended_tests": [
        {
          "test_name": "尿液常規檢查",
          "rationale": "確認泌尿道感染",
          "urgency": "routine"
        },
        {
          "test_name": "尿液培養",
          "rationale": "確認致病菌與抗生素敏感度",
          "urgency": "routine"
        }
      ],
      "treatments": [
        {
          "type": "medication",
          "name": "經驗性抗生素治療",
          "instruction": "依尿液培養結果調整",
          "note": "建議就診後開立"
        }
      ],
      "follow_up": {
        "interval": "一週後",
        "reason": "追蹤尿液培養結果",
        "additional_notes": "若症狀加重或出現發燒請立即就醫"
      },
      "referrals": [],
      "patient_education": [
        "多喝水，每日 2000ml 以上",
        "避免憋尿",
        "注意個人衛生",
        "如出現發燒或腰痛請立即就醫"
      ]
    }
  },
  "raw_transcript": "AI: 您好，我是泌尿科 AI 問診助手...\n病患: 我最近頻尿很嚴重...",
  "summary": "30 歲女性，主訴近一週頻尿合併排尿灼熱感，疑似泌尿道感染，建議尿液常規與培養檢查。",
  "icd10_codes": ["N39.0"],
  "ai_confidence_score": 0.87,
  "review_status": "pending",
  "reviewed_by": null,
  "reviewed_at": null,
  "review_notes": null,
  "version": 1,
  "generated_at": "2026-04-10T09:35:15Z",
  "created_at": "2026-04-10T09:35:00Z",
  "updated_at": "2026-04-10T09:35:15Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權存取此報告 |
| `404` | `NOT_FOUND` | 報告不存在 |

---

### 6.3 取得報告列表

- **方法:** `GET`
- **路徑:** `/api/v1/reports`
- **說明:** 取得報告列表，支援多條件篩選。病患僅能查看自己的報告。
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `patient_id` | `string` | `null` | 依病患 ID 篩選 |
| `doctor_id` | `string` | `null` | 依醫師 ID 篩選 |
| `review_status` | `string` | `null` | 依審閱狀態篩選: `pending`, `approved`, `revision_needed` |
| `status` | `string` | `null` | 依報告狀態篩選: `generating`, `generated`, `failed` |
| `date_from` | `string` | `null` | 起始日期 |
| `date_to` | `string` | `null` | 結束日期 |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "rpt_20260410_001",
      "session_id": "ses_20260410_001",
      "patient_id": "pat_def456",
      "patient": {
        "id": "pat_def456",
        "name": "李小華"
      },
      "doctor_id": "usr_abc123",
      "doctor": {
        "id": "usr_abc123",
        "name": "王大明"
      },
      "status": "generated",
      "review_status": "pending",
      "summary": "疑似泌尿道感染，主訴頻尿及排尿疼痛",
      "icd10_codes": ["N39.0"],
      "ai_confidence_score": 0.87,
      "version": 1,
      "generated_at": "2026-04-10T09:35:15Z",
      "created_at": "2026-04-10T09:35:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6InJwdF8yMDI2MDQwOV8wMDUifQ==",
    "has_more": true,
    "limit": 20,
    "total_count": 42
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

### 6.4 醫師審閱/確認報告

- **方法:** `PATCH`
- **路徑:** `/api/v1/reports/{id}/review`
- **說明:** 醫師審閱 SOAP 報告，可核准或標記需修訂
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 報告 ID |

**Request Body:**

```json
{
  "review_status": "string (required, enum: approved|revision_needed)",
  "review_notes": "string (optional, max 2000 chars)",
  "soap_overrides": {
    "subjective": {},
    "objective": {},
    "assessment": {},
    "plan": {}
  }
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `review_status` | `string` | 是 | `approved`: 核准 / `revision_needed`: 需修訂 |
| `review_notes` | `string` | 否 | 審閱備註 |
| `soap_overrides` | `object` | 否 | 醫師修正的 SOAP 欄位，僅提供需修改的部分 (JSONB 結構，同 shared_types.md 3.6) |

**Response Body (200 OK):**

```json
{
  "id": "rpt_20260410_001",
  "review_status": "approved",
  "reviewed_by": "usr_abc123",
  "reviewed_at": "2026-04-10T10:00:00Z",
  "review_notes": "報告內容正確",
  "version": 2,
  "updated_at": "2026-04-10T10:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `409` | `REPORT_NOT_READY` | 報告仍在生成中 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `404` | `NOT_FOUND` | 報告不存在 |

---

### 6.5 匯出報告為 PDF

- **方法:** `GET`
- **路徑:** `/api/v1/reports/{id}/export/pdf`
- **說明:** 將 SOAP 報告匯出為 PDF 格式檔案
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 報告 ID |

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `include_transcript` | `boolean` | `false` | 是否包含完整對話逐字稿 |
| `language` | `string` | `zh-TW` | 報告語言: `zh-TW`, `en-US` |

**Response:**

- **Content-Type:** `application/pdf`
- **Content-Disposition:** `attachment; filename="SOAP_Report_ses_20260410_001.pdf"`
- **狀態碼:** `200 OK`

回傳二進位 PDF 檔案串流。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `409` | `REPORT_NOT_READY` | 報告仍在生成中 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `404` | `NOT_FOUND` | 報告不存在 |

---

## 7. 紅旗警示 API

### 7.1 取得警示列表

- **方法:** `GET`
- **路徑:** `/api/v1/alerts`
- **說明:** 取得紅旗警示列表，支援篩選
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `severity` | `string` | `null` | 依嚴重程度篩選: `medium`, `high`, `critical` |
| `alert_type` | `string` | `null` | 依偵測方式篩選: `rule_based`, `semantic`, `combined` |
| `is_acknowledged` | `boolean` | `null` | 依確認狀態篩選 |
| `session_id` | `string` | `null` | 依場次 ID 篩選 |
| `patient_id` | `string` | `null` | 依病患 ID 篩選 |
| `date_from` | `string` | `null` | 起始日期 |
| `date_to` | `string` | `null` | 結束日期 |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "alt_001",
      "session_id": "ses_20260410_002",
      "patient_id": "pat_ghi789",
      "patient": {
        "id": "pat_ghi789",
        "name": "張志偉",
        "gender": "male",
        "date_of_birth": "1960-11-03"
      },
      "conversation_id": "msg_045",
      "alert_type": "rule_based",
      "severity": "critical",
      "title": "病患回報肉眼可見血尿",
      "description": "病患於問診中表示近三天出現肉眼可見的血尿，無明顯外傷史，需排除泌尿道惡性腫瘤可能性。",
      "trigger_reason": "關鍵字比對觸發: 血尿、紅色",
      "trigger_keywords": ["血尿", "紅色"],
      "suggested_actions": [
        "安排尿液細胞學檢查",
        "安排膀胱鏡檢查",
        "安排腎臟超音波"
      ],
      "is_acknowledged": false,
      "acknowledged_by": null,
      "acknowledged_at": null,
      "created_at": "2026-04-10T10:15:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6ImFsdF8wMTAifQ==",
    "has_more": true,
    "limit": 20,
    "total_count": 15
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

### 7.2 取得警示詳情

- **方法:** `GET`
- **路徑:** `/api/v1/alerts/{id}`
- **說明:** 取得指定紅旗警示的完整詳細資料
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 警示 ID |

**Response Body (200 OK):**

```json
{
  "id": "alt_001",
  "session_id": "ses_20260410_002",
  "patient_id": "pat_ghi789",
  "patient": {
    "id": "pat_ghi789",
    "name": "張志偉",
    "gender": "male",
    "date_of_birth": "1960-11-03",
    "phone": "+886955123456"
  },
  "conversation_id": "msg_045",
  "matched_rule_id": "rule_001",
  "rule": {
    "id": "rule_001",
    "name": "肉眼可見血尿",
    "keywords": ["血尿", "紅色的尿", "尿有血"]
  },
  "alert_type": "rule_based",
  "severity": "critical",
  "title": "病患回報肉眼可見血尿",
  "description": "病患於問診中表示近三天出現肉眼可見的血尿，無明顯外傷史，需排除泌尿道惡性腫瘤可能性。",
  "trigger_reason": "關鍵字比對觸發: 紅色",
  "trigger_keywords": ["紅色"],
  "llm_analysis": null,
  "suggested_actions": [
    "安排尿液細胞學檢查",
    "安排膀胱鏡檢查",
    "安排腎臟超音波"
  ],
  "is_acknowledged": false,
  "acknowledged_by": null,
  "acknowledged_at": null,
  "acknowledge_notes": null,
  "created_at": "2026-04-10T10:15:00Z",
  "updated_at": "2026-04-10T10:15:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `404` | `NOT_FOUND` | 警示不存在 |

---

### 7.3 確認警示

- **方法:** `PATCH`
- **路徑:** `/api/v1/alerts/{id}/acknowledge`
- **說明:** 醫師確認已查看並處理紅旗警示
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 警示 ID |

**Request Body:**

```json
{
  "acknowledge_notes": "string (optional, max 1000 chars)",
  "action_taken": "string (optional, max 1000 chars)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `acknowledge_notes` | `string` | 否 | 確認備註 |
| `action_taken` | `string` | 否 | 已採取的處置措施 |

**Response Body (200 OK):**

```json
{
  "id": "alt_001",
  "is_acknowledged": true,
  "acknowledged_by": "usr_abc123",
  "acknowledged_at": "2026-04-10T10:20:00Z",
  "acknowledge_notes": "已安排膀胱鏡檢查",
  "action_taken": "安排明日膀胱鏡檢查，並開立尿液細胞學檢查",
  "updated_at": "2026-04-10T10:20:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `409` | `ALERT_ALREADY_ACKNOWLEDGED` | 警示已被確認 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `404` | `NOT_FOUND` | 警示不存在 |

---

### 7.4 取得未確認警示

- **方法:** `GET`
- **路徑:** `/api/v1/alerts/active`
- **說明:** 取得所有未確認的紅旗警示，依嚴重程度排序 (critical 優先)
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `severity` | `string` | `null` | 依嚴重程度篩選: `medium`, `high`, `critical` |
| `limit` | `integer` | `50` | 每頁筆數 (1-100) |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "alt_001",
      "session_id": "ses_20260410_002",
      "patient_id": "pat_ghi789",
      "patient": {
        "id": "pat_ghi789",
        "name": "張志偉"
      },
      "alert_type": "rule_based",
      "severity": "critical",
      "title": "病患回報肉眼可見血尿",
      "is_acknowledged": false,
      "created_at": "2026-04-10T10:15:00Z"
    }
  ],
  "total_count": 3,
  "counts_by_severity": {
    "critical": 1,
    "high": 1,
    "medium": 1
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

## 8. 儀表板 API

### 8.1 取得今日摘要

- **方法:** `GET`
- **路徑:** `/api/v1/dashboard/summary`
- **說明:** 取得今日的統計摘要資料，用於儀表板首頁
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `date` | `string` | 今日 | 指定日期 (ISO 8601 date)，預設為今日 |
| `doctor_id` | `string` | `null` | 依醫師篩選 (admin 可指定，doctor 自動帶入自己) |

**Response Body (200 OK):**

```json
{
  "date": "2026-04-10",
  "sessions": {
    "total": 25,
    "waiting": 3,
    "in_progress": 2,
    "completed": 18,
    "aborted_red_flag": 0,
    "cancelled": 2
  },
  "patients": {
    "total_today": 23,
    "new_patients": 5,
    "returning_patients": 18
  },
  "reports": {
    "total_generated": 18,
    "pending_review": 3,
    "approved": 15,
    "revision_needed": 0
  },
  "alerts": {
    "total": 4,
    "unacknowledged": 1,
    "by_severity": {
      "critical": 1,
      "high": 1,
      "medium": 2
    }
  },
  "performance": {
    "average_session_duration_seconds": 480,
    "average_ai_confidence_score": 0.89,
    "average_messages_per_session": 14
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

### 8.2 取得病患佇列

- **方法:** `GET`
- **路徑:** `/api/v1/dashboard/queue`
- **說明:** 取得目前的病患佇列，包含等待中與進行中的場次，用於即時看診排隊資訊
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `doctor_id` | `string` | `null` | 依醫師篩選 |
| `status` | `string` | `waiting,in_progress` | 篩選狀態，逗號分隔 |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "position": 1,
      "session_id": "ses_20260410_010",
      "patient": {
        "id": "pat_patient_010",
        "name": "陳美玲",
        "gender": "female",
        "date_of_birth": "1988-02-14"
      },
      "chief_complaint": {
        "id": "cmp_005",
        "name": "尿失禁"
      },
      "status": "in_progress",
      "doctor": {
        "id": "usr_abc123",
        "name": "王大明"
      },
      "waiting_since": "2026-04-10T09:50:00Z",
      "started_at": "2026-04-10T10:00:00Z",
      "estimated_remaining_seconds": 180,
      "red_flag": false
    },
    {
      "position": 2,
      "session_id": "ses_20260410_011",
      "patient": {
        "id": "pat_patient_011",
        "name": "林建宏",
        "gender": "male",
        "date_of_birth": "1975-06-30"
      },
      "chief_complaint": {
        "id": "cmp_002",
        "name": "排尿困難"
      },
      "status": "waiting",
      "doctor": null,
      "waiting_since": "2026-04-10T10:05:00Z",
      "started_at": null,
      "estimated_remaining_seconds": null,
      "red_flag": false
    }
  ],
  "total_waiting": 3,
  "total_in_progress": 2,
  "average_wait_time_seconds": 600
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

### 8.3 取得歷史資料

- **方法:** `GET`
- **路徑:** `/api/v1/dashboard/history`
- **說明:** 取得指定日期範圍的歷史統計資料，用於趨勢分析
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `date_from` | `string` | 7 天前 | 起始日期 (ISO 8601 date) |
| `date_to` | `string` | 今日 | 結束日期 (ISO 8601 date) |
| `granularity` | `string` | `day` | 資料粒度: `day`, `week`, `month` |
| `doctor_id` | `string` | `null` | 依醫師篩選 |

**Response Body (200 OK):**

```json
{
  "date_from": "2026-04-03",
  "date_to": "2026-04-10",
  "granularity": "day",
  "data_points": [
    {
      "date": "2026-04-03",
      "sessions_total": 22,
      "sessions_completed": 20,
      "new_patients": 4,
      "reports_generated": 20,
      "alerts_total": 2,
      "alerts_critical": 0,
      "avg_session_duration_seconds": 450,
      "avg_ai_confidence": 0.88
    },
    {
      "date": "2026-04-04",
      "sessions_total": 19,
      "sessions_completed": 17,
      "new_patients": 3,
      "reports_generated": 17,
      "alerts_total": 1,
      "alerts_critical": 1,
      "avg_session_duration_seconds": 520,
      "avg_ai_confidence": 0.86
    }
  ],
  "summary": {
    "total_sessions": 155,
    "total_completed": 140,
    "total_new_patients": 28,
    "total_reports": 140,
    "total_alerts": 12,
    "overall_avg_duration_seconds": 475,
    "overall_avg_confidence": 0.87
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 日期範圍無效 (例如 date_from 晚於 date_to，或範圍超過 365 天) |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

## 9. 病患管理 API

### 9.1 取得病患列表

- **方法:** `GET`
- **路徑:** `/api/v1/patients`
- **說明:** 取得病患列表，支援搜尋與篩選
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `search` | `string` | `null` | 模糊搜尋 (姓名、病歷號碼、手機號碼) |
| `gender` | `string` | `null` | 依性別篩選: `male`, `female`, `other` |
| `age_from` | `integer` | `null` | 最小年齡 |
| `age_to` | `integer` | `null` | 最大年齡 |
| `has_active_session` | `boolean` | `null` | 是否有進行中的場次 |
| `sort_by` | `string` | `created_at` | 排序欄位: `created_at`, `name`, `last_visit_at` |
| `sort_order` | `string` | `desc` | 排序方向: `asc`, `desc` |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "pat_def456",
      "medical_record_number": "MRN-2026-001234",
      "name": "李小華",
      "gender": "female",
      "date_of_birth": "1995-08-20",
      "age": 30,
      "phone": "+886987654321",
      "total_sessions": 5,
      "last_visit_at": "2026-04-10T09:00:00Z",
      "has_active_session": true,
      "created_at": "2026-02-01T08:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6InVzcl9wYXRpZW50XzA1MCJ9",
    "has_more": true,
    "limit": 20,
    "total_count": 230
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |

---

### 9.2 取得病患詳情

- **方法:** `GET`
- **路徑:** `/api/v1/patients/{id}`
- **說明:** 取得指定病患的完整資料
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 病患 ID |

**Response Body (200 OK):**

```json
{
  "id": "pat_def456",
  "user_id": "usr_def456",
  "medical_record_number": "MRN-2026-001234",
  "name": "李小華",
  "gender": "female",
  "date_of_birth": "1995-08-20",
  "age": 30,
  "phone": "+886987654321",
  "medical_history": [
    {
      "condition": "無特殊病史",
      "diagnosed_year": null,
      "status": "resolved",
      "notes": null
    }
  ],
  "allergies": [
    {
      "allergen": "Penicillin",
      "type": "drug",
      "reaction": "皮疹",
      "severity": "moderate"
    }
  ],
  "current_medications": [],
  "emergency_contact": {
    "name": "李大明",
    "relationship": "父親",
    "phone": "+886911222333"
  },
  "total_sessions": 5,
  "total_reports": 4,
  "last_visit_at": "2026-04-10T09:00:00Z",
  "is_active": true,
  "created_at": "2026-02-01T08:00:00Z",
  "updated_at": "2026-04-10T09:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權存取此病患資料 |
| `404` | `NOT_FOUND` | 病患不存在 |

---

### 9.3 建立病患

- **方法:** `POST`
- **路徑:** `/api/v1/patients`
- **說明:** 由醫師或管理員手動建立病患資料
- **需要認證:** 是
- **允許角色:** `doctor`, `admin`

**Request Body:**

```json
{
  "name": "string (required, max 100 chars)",
  "email": "string (required, email format)",
  "password": "string (required, min 8 chars)",
  "medical_record_number": "string (required, unique)",
  "phone": "string (optional, E.164 format)",
  "gender": "string (required, enum: male|female|other)",
  "date_of_birth": "string (required, ISO 8601 date)",
  "medical_history": "array (optional, JSONB)",
  "allergies": "array (optional, JSONB)",
  "current_medications": "array (optional, JSONB)",
  "emergency_contact": {
    "name": "string (optional)",
    "relationship": "string (optional)",
    "phone": "string (optional)"
  }
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | `string` | 是 | 姓名 |
| `email` | `string` | 是 | 電子郵件 |
| `password` | `string` | 是 | 初始密碼 |
| `medical_record_number` | `string` | 是 | 病歷號碼，唯一 |
| `phone` | `string` | 否 | 手機號碼 |
| `gender` | `string` | 是 | 性別 |
| `date_of_birth` | `string` | 是 | 出生日期 |
| `medical_history` | `array` | 否 | 過去病史 (JSONB 陣列) |
| `allergies` | `array` | 否 | 過敏史 (JSONB 陣列) |
| `current_medications` | `array` | 否 | 目前用藥 (JSONB 陣列) |
| `emergency_contact` | `object` | 否 | 緊急聯絡人 (JSONB `{name, relationship, phone}`) |

**Response Body (201 Created):**

回傳完整病患物件 (格式同 9.2)。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 角色權限不足 |
| `409` | `EMAIL_ALREADY_EXISTS` | 電子郵件已被註冊 |

---

### 9.4 更新病患資料

- **方法:** `PUT`
- **路徑:** `/api/v1/patients/{id}`
- **說明:** 更新指定病患的資料
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 病患 ID |

**Request Body:**

```json
{
  "name": "string (optional)",
  "phone": "string (optional)",
  "gender": "string (optional)",
  "date_of_birth": "string (optional)",
  "medical_history": "array (optional, JSONB)",
  "allergies": "array (optional, JSONB)",
  "current_medications": "array (optional, JSONB)",
  "emergency_contact": {
    "name": "string (optional)",
    "relationship": "string (optional)",
    "phone": "string (optional)"
  }
}
```

**Response Body (200 OK):**

回傳更新後的完整病患物件 (格式同 9.2)。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權更新此病患資料 |
| `404` | `NOT_FOUND` | 病患不存在 |

---

### 9.5 取得病患的場次歷史

- **方法:** `GET`
- **路徑:** `/api/v1/patients/{id}/sessions`
- **說明:** 取得指定病患的所有問診場次記錄
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 病患 ID |

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `status` | `string` | `null` | 依狀態篩選 |
| `date_from` | `string` | `null` | 起始日期 |
| `date_to` | `string` | `null` | 結束日期 |

**Response Body (200 OK):**

格式同 [4.2 取得場次列表](#42-取得場次列表) 的回應格式，僅包含該病患的場次。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權存取此病患的場次 |
| `404` | `NOT_FOUND` | 病患不存在 |

---

### 9.6 取得病患的 SOAP 報告

- **方法:** `GET`
- **路徑:** `/api/v1/patients/{id}/reports`
- **說明:** 取得指定病患的所有 SOAP 報告
- **需要認證:** 是
- **允許角色:** `patient` (僅自己), `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 病患 ID |

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `review_status` | `string` | `null` | 依審閱狀態篩選 |
| `date_from` | `string` | `null` | 起始日期 |
| `date_to` | `string` | `null` | 結束日期 |

**Response Body (200 OK):**

格式同 [6.3 取得報告列表](#63-取得報告列表) 的回應格式，僅包含該病患的報告。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 無權存取此病患的報告 |
| `404` | `NOT_FOUND` | 病患不存在 |

---

## 10. 通知 API

### 10.1 取得通知列表

- **方法:** `GET`
- **路徑:** `/api/v1/notifications`
- **說明:** 取得目前使用者的通知列表
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `is_read` | `boolean` | `null` | 依已讀狀態篩選 |
| `type` | `string` | `null` | 依類型篩選: `red_flag`, `session_complete`, `report_ready`, `system` |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "ntf_001",
      "user_id": "usr_abc123",
      "type": "red_flag",
      "title": "新的紅旗警示",
      "body": "病患 張志偉 的問診中偵測到嚴重警示: 肉眼可見血尿",
      "is_read": false,
      "data": {
        "alert_id": "alt_001",
        "session_id": "ses_20260410_002",
        "severity": "critical"
      },
      "created_at": "2026-04-10T10:15:00Z"
    },
    {
      "id": "ntf_002",
      "user_id": "usr_abc123",
      "type": "session_complete",
      "title": "問診場次已完成",
      "body": "病患 李小華 的問診場次已完成，可開始生成 SOAP 報告",
      "is_read": true,
      "read_at": "2026-04-10T09:40:00Z",
      "data": {
        "session_id": "ses_20260410_001"
      },
      "created_at": "2026-04-10T09:30:00Z"
    },
    {
      "id": "ntf_003",
      "user_id": "usr_abc123",
      "type": "report_ready",
      "title": "SOAP 報告已生成",
      "body": "病患 李小華 的 SOAP 報告已完成生成，等待審閱",
      "is_read": true,
      "read_at": "2026-04-10T09:40:00Z",
      "data": {
        "report_id": "rpt_20260410_001",
        "session_id": "ses_20260410_001"
      },
      "created_at": "2026-04-10T09:35:15Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6Im50Zl8wNTAifQ==",
    "has_more": true,
    "limit": 20,
    "total_count": 68
  },
  "unread_count": 5
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |

---

### 10.2 標記通知為已讀

- **方法:** `PATCH`
- **路徑:** `/api/v1/notifications/{id}/read`
- **說明:** 將指定通知標記為已讀
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 通知 ID |

**Request Body:** 無

**Response Body (200 OK):**

```json
{
  "id": "ntf_001",
  "is_read": true,
  "read_at": "2026-04-10T10:25:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 此通知不屬於目前使用者 |
| `404` | `NOT_FOUND` | 通知不存在 |

---

### 10.3 標記所有通知為已讀

- **方法:** `PATCH`
- **路徑:** `/api/v1/notifications/read-all`
- **說明:** 將目前使用者的所有未讀通知標記為已讀
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Request Body:** 無

**Response Body (200 OK):**

```json
{
  "updated_count": 5,
  "read_at": "2026-04-10T10:30:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |

---

### 10.4 註冊 FCM 裝置 Token

- **方法:** `POST`
- **路徑:** `/api/v1/notifications/fcm-token`
- **說明:** 註冊或更新 Firebase Cloud Messaging (FCM) 裝置 Token，用於推播通知
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Request Body:**

```json
{
  "token": "string (required)",
  "platform": "string (required, enum: ios|android|web)",
  "device_name": "string (optional, max 200 chars)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `token` | `string` | 是 | FCM 裝置 Token |
| `platform` | `string` | 是 | 裝置平台 (DevicePlatform enum) |
| `device_name` | `string` | 否 | 裝置名稱 (例如 `iPhone 15 Pro`) |

**Response Body (201 Created):**

```json
{
  "id": "fcm_001",
  "user_id": "usr_abc123",
  "platform": "ios",
  "device_name": "iPhone 15 Pro",
  "is_active": true,
  "created_at": "2026-04-10T08:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |

---

### 10.5 移除 FCM 裝置 Token

- **方法:** `DELETE`
- **路徑:** `/api/v1/notifications/fcm-token`
- **說明:** 移除指定的 FCM 裝置 Token (例如使用者登出或卸載 App 時)
- **需要認證:** 是
- **允許角色:** `patient`, `doctor`, `admin`

**Request Body:**

```json
{
  "token": "string (required)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `token` | `string` | 是 | 欲移除的 FCM 裝置 Token |

**Response Body (200 OK):**

```json
{
  "message": "裝置 Token 已移除"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `404` | `NOT_FOUND` | Token 不存在 |

---

## 11. 稽核日誌 API

### 11.1 取得稽核日誌列表

- **方法:** `GET`
- **路徑:** `/api/v1/audit-logs`
- **說明:** 取得系統稽核日誌，記錄所有使用者操作。僅限管理員存取。
- **需要認證:** 是
- **允許角色:** `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `50` | 每頁筆數 (1-200) |
| `user_id` | `string` | `null` | 依操作者 ID 篩選 |
| `action` | `string` | `null` | 依操作類型篩選: `create`, `read`, `update`, `delete`, `login`, `logout`, `export`, `review`, `acknowledge`, `session_start`, `session_end` |
| `resource_type` | `string` | `null` | 依資源類型篩選: `session`, `report`, `alert`, `patient`, `complaint`, `user`, `red_flag_rule` |
| `resource_id` | `string` | `null` | 依資源 ID 篩選 |
| `date_from` | `string` | `null` | 起始時間 (ISO 8601 datetime) |
| `date_to` | `string` | `null` | 結束時間 (ISO 8601 datetime) |
| `ip_address` | `string` | `null` | 依來源 IP 篩選 |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "log_00001",
      "user_id": "usr_abc123",
      "user": {
        "id": "usr_abc123",
        "name": "王大明",
        "role": "doctor"
      },
      "action": "review",
      "resource_type": "report",
      "resource_id": "rpt_20260410_001",
      "description": "醫師審閱並核准 SOAP 報告",
      "changes": {
        "review_status": {
          "old": "pending",
          "new": "approved"
        }
      },
      "ip_address": "192.168.1.100",
      "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
      "created_at": "2026-04-10T10:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6ImxvZ18wMDIwMCJ9",
    "has_more": true,
    "limit": 50,
    "total_count": 5432
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |

---

### 11.2 匯出稽核日誌

- **方法:** `GET`
- **路徑:** `/api/v1/audit-logs/export`
- **說明:** 匯出指定條件的稽核日誌為 CSV 檔案
- **需要認證:** 是
- **允許角色:** `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `date_from` | `string` | 30 天前 | 起始時間 (必填) |
| `date_to` | `string` | 今日 | 結束時間 |
| `format` | `string` | `csv` | 匯出格式: `csv`, `json` |
| `user_id` | `string` | `null` | 依操作者篩選 |
| `action` | `string` | `null` | 依操作類型篩選 |
| `resource_type` | `string` | `null` | 依資源類型篩選 |

**Response:**

- **Content-Type:** `text/csv; charset=utf-8` 或 `application/json`
- **Content-Disposition:** `attachment; filename="audit_logs_20260403_20260410.csv"`
- **狀態碼:** `200 OK`

**CSV 欄位:**

```
id,user_id,user_name,user_role,action,resource_type,resource_id,description,ip_address,created_at
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 日期範圍無效或超過 90 天限制 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |

---

## 12. 系統管理 API

### 12.1 取得使用者列表

- **方法:** `GET`
- **路徑:** `/api/v1/admin/users`
- **說明:** 取得系統中所有使用者的列表
- **需要認證:** 是
- **允許角色:** `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `role` | `string` | `null` | 依角色篩選: `patient`, `doctor`, `admin` |
| `is_active` | `boolean` | `null` | 依啟用狀態篩選 |
| `search` | `string` | `null` | 模糊搜尋 (姓名、電子郵件) |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "usr_abc123",
      "email": "doctor@hospital.com",
      "name": "王大明",
      "role": "doctor",
      "phone": "+886912345678",
      "department": "泌尿科",
      "license_number": "DOC-2020-12345",
      "is_active": true,
      "last_login_at": "2026-04-10T08:00:00Z",
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6InVzcl8xMDAifQ==",
    "has_more": true,
    "limit": 20,
    "total_count": 256
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |

---

### 12.2 變更使用者角色

- **方法:** `PATCH`
- **路徑:** `/api/v1/admin/users/{id}/role`
- **說明:** 變更指定使用者的角色
- **需要認證:** 是
- **允許角色:** `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 使用者 ID |

**Request Body:**

```json
{
  "role": "string (required, enum: patient|doctor|admin)",
  "reason": "string (optional, max 500 chars)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `role` | `string` | 是 | 新角色 |
| `reason` | `string` | 否 | 變更原因 (將記錄於稽核日誌) |

**Response Body (200 OK):**

```json
{
  "id": "usr_def456",
  "name": "李小華",
  "previous_role": "patient",
  "role": "doctor",
  "updated_at": "2026-04-10T11:00:00Z"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 角色值無效 |
| `409` | `CANNOT_CHANGE_OWN_ROLE` | 不可變更自己的角色 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |
| `404` | `NOT_FOUND` | 使用者不存在 |

---

### 12.3 取得紅旗規則列表

- **方法:** `GET`
- **路徑:** `/api/v1/admin/red-flag-rules`
- **說明:** 取得所有紅旗警示觸發規則
- **需要認證:** 是
- **允許角色:** `admin`

**Query Parameters:**

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `cursor` | `string` | `null` | 分頁游標 |
| `limit` | `integer` | `20` | 每頁筆數 (1-100) |
| `severity` | `string` | `null` | 依嚴重程度篩選: `medium`, `high`, `critical` |
| `is_active` | `boolean` | `true` | 依啟用狀態篩選 |
| `category` | `string` | `null` | 依分類篩選 |

**Response Body (200 OK):**

```json
{
  "data": [
    {
      "id": "rule_001",
      "name": "肉眼可見血尿",
      "name_en": "Gross Hematuria",
      "description": "病患回報尿液中有肉眼可見的血液",
      "category": "血尿",
      "severity": "critical",
      "keywords": ["血尿", "紅色的尿", "尿有血", "尿血", "血色"],
      "regex_pattern": null,
      "suspected_diagnosis": "泌尿道惡性腫瘤",
      "suggested_actions": [
        "安排尿液細胞學檢查",
        "安排膀胱鏡檢查",
        "安排腎臟超音波"
      ],
      "is_active": true,
      "created_by": "usr_admin001",
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-03-15T14:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": null,
    "has_more": false,
    "limit": 20,
    "total_count": 15
  }
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |

---

### 12.4 新增紅旗規則

- **方法:** `POST`
- **路徑:** `/api/v1/admin/red-flag-rules`
- **說明:** 新增紅旗警示觸發規則
- **需要認證:** 是
- **允許角色:** `admin`

**Request Body:**

```json
{
  "name": "string (required, max 200 chars)",
  "description": "string (optional)",
  "category": "string (required, max 100 chars)",
  "severity": "string (required, enum: medium|high|critical)",
  "keywords": ["string (required, at least 1)"],
  "regex_pattern": "string (optional, regex)",
  "suspected_diagnosis": "string (optional, max 200 chars)",
  "suggested_action": "string (optional)",
  "is_active": "boolean (optional, default: true)"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | `string` | 是 | 規則名稱 |
| `description` | `string` | 否 | 規則描述 |
| `category` | `string` | 是 | 分類 |
| `severity` | `string` | 是 | 嚴重程度 (3 級: `medium`, `high`, `critical`) |
| `keywords` | `string[]` | 是 | 觸發關鍵字陣列 |
| `regex_pattern` | `string` | 否 | 正則表達式 (可選) |
| `suspected_diagnosis` | `string` | 否 | 疑似診斷 |
| `suggested_action` | `string` | 否 | 建議處置 |
| `is_active` | `boolean` | 否 | 是否啟用 |

**Response Body (201 Created):**

回傳完整紅旗規則物件 (格式同 12.3 中的單一物件)。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |
| `409` | `RULE_ALREADY_EXISTS` | 同名規則已存在 |

---

### 12.5 更新紅旗規則

- **方法:** `PUT`
- **路徑:** `/api/v1/admin/red-flag-rules/{id}`
- **說明:** 更新指定紅旗規則
- **需要認證:** 是
- **允許角色:** `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 規則 ID |

**Request Body:**

格式同 [12.4 新增紅旗規則](#124-新增紅旗規則)，所有欄位皆為選填 (僅更新提供的欄位)。

**Response Body (200 OK):**

回傳更新後的完整紅旗規則物件。

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `422` | `VALIDATION_ERROR` | 欄位驗證失敗 |
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |
| `404` | `NOT_FOUND` | 規則不存在 |

---

### 12.6 刪除紅旗規則

- **方法:** `DELETE`
- **路徑:** `/api/v1/admin/red-flag-rules/{id}`
- **說明:** 刪除指定紅旗規則 (硬刪除)
- **需要認證:** 是
- **允許角色:** `admin`

**Path Parameters:**

| 參數 | 型別 | 說明 |
|---|---|---|
| `id` | `string` | 規則 ID |

**Response Body (200 OK):**

```json
{
  "message": "紅旗規則已刪除",
  "id": "rule_005"
}
```

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |
| `404` | `NOT_FOUND` | 規則不存在 |

---

### 12.7 系統健康檢查

- **方法:** `GET`
- **路徑:** `/api/v1/admin/system/health`
- **說明:** 取得系統各元件的健康狀態
- **需要認證:** 是
- **允許角色:** `admin`

**Response Body (200 OK):**

```json
{
  "status": "healthy",
  "version": "1.1.0",
  "uptime_seconds": 864000,
  "timestamp": "2026-04-10T11:00:00Z",
  "components": {
    "database": {
      "status": "healthy",
      "latency_ms": 5,
      "details": "PostgreSQL 16.2"
    },
    "redis": {
      "status": "healthy",
      "latency_ms": 2,
      "details": "Redis 7.2"
    },
    "ai_service": {
      "status": "healthy",
      "latency_ms": 120,
      "details": "Claude API"
    },
    "stt_service": {
      "status": "healthy",
      "latency_ms": 85,
      "details": "Google Cloud STT"
    },
    "tts_service": {
      "status": "healthy",
      "latency_ms": 95,
      "details": "Google Cloud TTS"
    },
    "storage": {
      "status": "healthy",
      "latency_ms": 15,
      "details": "S3 compatible storage",
      "usage_percent": 42.5
    }
  }
}
```

若任一元件異常:

```json
{
  "status": "degraded",
  "version": "1.1.0",
  "uptime_seconds": 864000,
  "timestamp": "2026-04-10T11:00:00Z",
  "components": {
    "stt_service": {
      "status": "unhealthy",
      "latency_ms": null,
      "details": "Connection timeout",
      "error": "Failed to connect to Google Cloud STT service after 5000ms"
    }
  }
}
```

**回應狀態碼:**
- `200 OK`: 系統健康或部分降級 (`healthy` 或 `degraded`)
- `503 Service Unavailable`: 系統不可用 (`unhealthy`)

**錯誤回應:**

| 狀態碼 | 錯誤碼 | 說明 |
|---|---|---|
| `401` | `UNAUTHORIZED` | 未認證 |
| `403` | `FORBIDDEN` | 僅限管理員存取 |

---

## 13. WebSocket API

### 13.1 語音對話串流

- **路徑:** `wss://{host}/api/v1/ws/sessions/{id}/stream`
- **說明:** 建立語音問診的即時雙向通訊頻道。用戶端傳送語音片段，伺服器回傳 STT 辨識結果、AI 回覆文字、TTS 語音 URL 及紅旗警示。
- **允許角色:** `patient` (僅自己的場次), `doctor`

#### 13.1.1 連線握手

連線時需在 Query Parameter 中帶入 JWT Token:

```
wss://{host}/api/v1/ws/sessions/{id}/stream?token=<access_token>
```

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `token` | `string` | 是 | 有效的 JWT Access Token |

**連線成功回應:**

伺服器在 WebSocket 連線建立後，立即發送一則 `connection_ack` 訊息:

```json
{
  "type": "connection_ack",
  "id": "550e8400-e29b-41d4-a716-446655440099",
  "timestamp": "2026-04-10T09:05:00Z",
  "payload": {
    "session_id": "ses_20260410_001",
    "status": "in_progress",
    "config": {
      "audio_format": "wav",
      "sample_rate": 16000,
      "max_chunk_size_bytes": 65536
    }
  }
}
```

**連線失敗回應:**

若認證失敗，伺服器將在發送錯誤訊息後關閉連線:

```json
{
  "type": "error",
  "id": "550e8400-e29b-41d4-a716-446655440098",
  "timestamp": "2026-04-10T09:05:00Z",
  "payload": {
    "code": "UNAUTHORIZED",
    "message": "JWT Token 無效或已過期"
  }
}
```

WebSocket 關閉碼:

| 關閉碼 | 說明 |
|---|---|
| `1000` | 正常關閉 |
| `1008` | 認證失敗 |
| `1011` | 伺服器內部錯誤 |
| `4001` | Token 過期 |
| `4003` | 無權存取此場次 |
| `4004` | 場次不存在 |
| `4009` | 場次狀態不允許連線 |

#### 13.1.2 訊息格式

所有 WebSocket 訊息皆為 JSON 格式 (文字幀)，語音資料除外 (二進位幀)。

**通用訊息結構 (WSMessage):**

```json
{
  "type": "string (required)",
  "id": "string (required, UUID)",
  "timestamp": "string (ISO 8601)",
  "payload": {}
}
```

#### 13.1.3 用戶端 -> 伺服器 訊息

**1. audio_chunk -- 語音片段**

以二進位幀 (Binary Frame) 傳送，前 36 位元組為 UTF-8 編碼的訊息 ID (UUID)，其餘為語音資料。

或者使用 JSON 格式包裝 Base64 編碼的語音資料:

```json
{
  "type": "audio_chunk",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-04-10T09:05:10.000Z",
  "payload": {
    "audio_data": "<base64 encoded audio>",
    "chunk_index": 0,
    "is_final": false,
    "format": "wav",
    "sample_rate": 16000
  }
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `payload.audio_data` | `string` | 是 | Base64 編碼的語音資料 |
| `payload.chunk_index` | `integer` | 是 | 片段序號，從 0 開始 |
| `payload.is_final` | `boolean` | 是 | 是否為本段語音的最後一個片段 |
| `payload.format` | `string` | 否 | 音訊格式，預設 `wav` |
| `payload.sample_rate` | `integer` | 否 | 取樣率，預設 `16000` |

**2. text_message -- 文字訊息**

```json
{
  "type": "text_message",
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "timestamp": "2026-04-10T09:05:15.000Z",
  "payload": {
    "text": "我最近頻尿很嚴重"
  }
}
```

**3. control -- 控制訊息**

```json
{
  "type": "control",
  "id": "550e8400-e29b-41d4-a716-446655440002",
  "timestamp": "2026-04-10T09:05:20.000Z",
  "payload": {
    "action": "end_session | pause_recording | resume_recording"
  }
}
```

| action 值 | 說明 |
|---|---|
| `pause_recording` | 暫停錄音 |
| `resume_recording` | 恢復錄音 |
| `end_session` | 結束問診場次 |

**4. ping -- 心跳 (用戶端)**

```json
{
  "type": "ping",
  "id": "550e8400-e29b-41d4-a716-446655440003",
  "timestamp": "2026-04-10T09:05:30.000Z",
  "payload": {}
}
```

#### 13.1.4 伺服器 -> 用戶端 訊息

**1. stt_partial -- 即時語音辨識 (中間結果)**

```json
{
  "type": "stt_partial",
  "id": "550e8400-e29b-41d4-a716-446655440010",
  "timestamp": "2026-04-10T09:05:11.000Z",
  "payload": {
    "text": "我最近頻",
    "is_final": false,
    "confidence": 0.85
  }
}
```

**2. stt_final -- 語音辨識最終結果**

```json
{
  "type": "stt_final",
  "id": "550e8400-e29b-41d4-a716-446655440011",
  "timestamp": "2026-04-10T09:05:12.000Z",
  "payload": {
    "message_id": "msg_020",
    "text": "我最近頻尿很嚴重，晚上要起來好幾次",
    "is_final": true,
    "confidence": 0.95
  }
}
```

**3. ai_response_start -- AI 回覆開始**

```json
{
  "type": "ai_response_start",
  "id": "550e8400-e29b-41d4-a716-446655440012",
  "timestamp": "2026-04-10T09:05:13.000Z",
  "payload": {
    "message_id": "msg_021"
  }
}
```

**4. ai_response_chunk -- AI 回覆串流片段**

```json
{
  "type": "ai_response_chunk",
  "id": "550e8400-e29b-41d4-a716-446655440013",
  "timestamp": "2026-04-10T09:05:13.500Z",
  "payload": {
    "message_id": "msg_021",
    "text": "了解，",
    "chunk_index": 0
  }
}
```

**5. ai_response_end -- AI 回覆結束**

```json
{
  "type": "ai_response_end",
  "id": "550e8400-e29b-41d4-a716-446655440014",
  "timestamp": "2026-04-10T09:05:15.000Z",
  "payload": {
    "message_id": "msg_021",
    "full_text": "了解，您提到晚上頻尿的情況。請問每晚大約需要起床幾次呢? 白天的排尿次數大概是多少?",
    "tts_audio_url": "https://storage.example.com/tts/msg_021.mp3"
  }
}
```

**6. red_flag_alert -- 紅旗警示**

```json
{
  "type": "red_flag_alert",
  "id": "550e8400-e29b-41d4-a716-446655440015",
  "timestamp": "2026-04-10T09:10:00.000Z",
  "payload": {
    "alert_id": "alt_002",
    "severity": "high",
    "title": "病患回報劇烈疼痛",
    "description": "病患表示排尿時有劇烈刺痛感，可能需要進一步評估",
    "suggested_actions": [
      "安排尿液常規檢查",
      "評估是否需要止痛藥物"
    ]
  }
}
```

**7. session_status -- 場次狀態變更**

```json
{
  "type": "session_status",
  "id": "550e8400-e29b-41d4-a716-446655440016",
  "timestamp": "2026-04-10T09:30:00.000Z",
  "payload": {
    "session_id": "ses_20260410_001",
    "status": "completed",
    "previous_status": "in_progress",
    "reason": "問診完成"
  }
}
```

**8. pong -- 心跳回應**

```json
{
  "type": "pong",
  "id": "550e8400-e29b-41d4-a716-446655440017",
  "timestamp": "2026-04-10T09:05:30.000Z",
  "payload": {
    "server_time": "2026-04-10T09:05:30.000Z"
  }
}
```

**9. error -- 錯誤訊息**

```json
{
  "type": "error",
  "id": "550e8400-e29b-41d4-a716-446655440018",
  "timestamp": "2026-04-10T09:05:30.000Z",
  "payload": {
    "code": "STT_SERVICE_UNAVAILABLE",
    "message": "語音辨識服務暫時不可用，請稍後再試"
  }
}
```

#### 13.1.5 心跳協定 (Heartbeat / Ping-Pong)

- 伺服器每 **30 秒** 發送一次 WebSocket 協定層級的 Ping 幀
- 用戶端應在收到 Ping 後立即回應 Pong 幀 (多數 WebSocket 函式庫會自動處理)
- 應用層級: 用戶端可每 **30 秒** 發送 `ping` 訊息，伺服器回應 `pong` 訊息
- 若伺服器連續 **3 次** (90 秒) 未收到用戶端的 Pong 回應，將主動斷開連線
- 若用戶端連續 **3 次** (90 秒) 未收到伺服器的 Pong 回應，應主動重新連線

#### 13.1.6 重連協定 (Reconnection Protocol)

1. 連線斷開後，用戶端應使用指數退避策略 (Exponential Backoff) 嘗試重新連線
2. 退避間隔: 1 秒 -> 2 秒 -> 4 秒 -> 8 秒 -> 16 秒 -> 30 秒 (上限)
3. 每次退避加入隨機抖動 (Jitter): `interval * (0.5 + random() * 0.5)`
4. 重連時帶入 `last_message_id` 參數，伺服器會回補斷線期間的訊息:

```
wss://{host}/api/v1/ws/sessions/{id}/stream?token=<token>&last_message_id=msg_020
```

5. 伺服器在重連成功後發送 `reconnection_ack` 訊息:

```json
{
  "type": "reconnection_ack",
  "id": "550e8400-e29b-41d4-a716-446655440020",
  "timestamp": "2026-04-10T09:12:00.000Z",
  "payload": {
    "session_id": "ses_20260410_001",
    "missed_messages_count": 2,
    "last_processed_message_id": "msg_020"
  }
}
```

6. 接著伺服器依序重送斷線期間的訊息
7. 若 Access Token 已過期，用戶端應先透過 REST API 換發新 Token 再重連
8. 最大重試次數: **10 次**，超過後用戶端應提示使用者手動重新整理

---

### 13.2 醫師儀表板即時更新

- **路徑:** `wss://{host}/api/v1/ws/dashboard`
- **說明:** 醫師儀表板的即時資料推送頻道。伺服器推送場次狀態變更、新紅旗警示、佇列更新等事件。
- **允許角色:** `doctor`, `admin`

#### 13.2.1 連線握手

```
wss://{host}/api/v1/ws/dashboard?token=<access_token>
```

**連線成功回應:**

```json
{
  "type": "connection_ack",
  "id": "550e8400-e29b-41d4-a716-446655440030",
  "timestamp": "2026-04-10T08:00:00Z",
  "payload": {
    "subscribed_events": [
      "session_created",
      "session_status_changed",
      "new_red_flag",
      "red_flag_acknowledged",
      "report_generated",
      "queue_updated",
      "stats_updated"
    ]
  }
}
```

#### 13.2.2 伺服器 -> 用戶端 訊息

**1. session_created -- 新場次建立**

```json
{
  "type": "session_created",
  "id": "550e8400-e29b-41d4-a716-446655440031",
  "timestamp": "2026-04-10T10:05:00Z",
  "payload": {
    "session_id": "ses_20260410_011",
    "patient_name": "林建宏",
    "chief_complaint": "排尿困難",
    "status": "waiting"
  }
}
```

**2. session_status_changed -- 場次狀態變更**

```json
{
  "type": "session_status_changed",
  "id": "550e8400-e29b-41d4-a716-446655440032",
  "timestamp": "2026-04-10T10:10:00Z",
  "payload": {
    "session_id": "ses_20260410_010",
    "status": "in_progress",
    "previous_status": "waiting",
    "reason": null
  }
}
```

**3. new_red_flag -- 新紅旗觸發**

```json
{
  "type": "new_red_flag",
  "id": "550e8400-e29b-41d4-a716-446655440033",
  "timestamp": "2026-04-10T10:15:00Z",
  "payload": {
    "alert_id": "alt_001",
    "session_id": "ses_20260410_002",
    "patient_name": "張志偉",
    "severity": "critical",
    "title": "病患回報肉眼可見血尿",
    "description": "病患於問診中表示近三天出現肉眼可見的血尿"
  }
}
```

**4. red_flag_acknowledged -- 紅旗已確認**

```json
{
  "type": "red_flag_acknowledged",
  "id": "550e8400-e29b-41d4-a716-446655440034",
  "timestamp": "2026-04-10T10:20:00Z",
  "payload": {
    "alert_id": "alt_001",
    "acknowledged_by": "usr_abc123"
  }
}
```

**5. report_generated -- 報告產生完成**

```json
{
  "type": "report_generated",
  "id": "550e8400-e29b-41d4-a716-446655440035",
  "timestamp": "2026-04-10T09:35:15Z",
  "payload": {
    "report_id": "rpt_20260410_001",
    "session_id": "ses_20260410_001",
    "patient_name": "李小華",
    "status": "generated"
  }
}
```

**6. queue_updated -- 佇列更新**

```json
{
  "type": "queue_updated",
  "id": "550e8400-e29b-41d4-a716-446655440036",
  "timestamp": "2026-04-10T10:05:00Z",
  "payload": {
    "total_waiting": 4,
    "total_in_progress": 2,
    "queue": [
      {
        "session_id": "ses_20260410_011",
        "patient_name": "林建宏",
        "status": "waiting",
        "position": 1
      }
    ]
  }
}
```

**7. stats_updated -- 統計更新**

```json
{
  "type": "stats_updated",
  "id": "550e8400-e29b-41d4-a716-446655440037",
  "timestamp": "2026-04-10T10:30:00Z",
  "payload": {
    "sessions_today": 25,
    "completed": 18,
    "red_flags": 4,
    "pending_reviews": 3
  }
}
```

**8. pong -- 心跳回應**

格式同 13.1.4 的 pong。

**9. error -- 錯誤**

格式同 13.1.4 的 error。

#### 13.2.3 用戶端 -> 伺服器 訊息

**1. ping -- 心跳**

```json
{
  "type": "ping",
  "id": "550e8400-e29b-41d4-a716-446655440040",
  "timestamp": "2026-04-10T09:05:30.000Z",
  "payload": {}
}
```

**2. subscribe -- 訂閱特定事件 (選用)**

```json
{
  "type": "subscribe",
  "id": "550e8400-e29b-41d4-a716-446655440041",
  "timestamp": "2026-04-10T08:00:05.000Z",
  "payload": {
    "events": ["new_red_flag", "session_status_changed"],
    "filters": {
      "doctor_id": "usr_abc123"
    }
  }
}
```

**3. unsubscribe -- 取消訂閱 (選用)**

```json
{
  "type": "unsubscribe",
  "id": "550e8400-e29b-41d4-a716-446655440042",
  "timestamp": "2026-04-10T08:30:00.000Z",
  "payload": {
    "events": ["queue_updated"]
  }
}
```

#### 13.2.4 心跳與重連

心跳協定與重連協定同 [13.1.5](#1315-心跳協定-heartbeat--ping-pong) 及 [13.1.6](#1316-重連協定-reconnection-protocol)。

儀表板 WebSocket 重連 URL:

```
wss://{host}/api/v1/ws/dashboard?token=<token>&last_event_id=<last_received_event_id>
```

---

### 13.3 病患佇列位置 (WebSocket 事件)

病患可透過語音對話 WebSocket (13.1) 接收佇列位置更新。當場次狀態為 `waiting` 時，伺服器會定期推送佇列位置訊息:

```json
{
  "type": "queue_position",
  "id": "550e8400-e29b-41d4-a716-446655440050",
  "timestamp": "2026-04-10T10:05:00Z",
  "payload": {
    "session_id": "ses_20260410_011",
    "position": 3,
    "estimated_wait_seconds": 900,
    "total_waiting": 5
  }
}
```

---

## 14. 共用資料模型

以下定義系統中使用的所有共用資料模型，以 TypeScript 介面與 Python Pydantic 模型對照呈現。所有型別定義以 shared_types.md 為準。

### 14.1 User (使用者)

**TypeScript:**

```typescript
interface User {
  id: string;                    // 使用者 ID (UUID)
  email: string;                 // 電子郵件
  name: string;                  // 姓名
  role: UserRole;                // 角色
  phone: string | null;          // 手機號碼 (E.164)
  department: string | null;     // 科別 (醫師用)
  license_number: string | null; // 醫師執照號碼
  is_active: boolean;            // 是否啟用
  created_at: string;            // 建立時間 (ISO 8601)
  updated_at: string;            // 更新時間 (ISO 8601)
  last_login_at: string | null;  // 最後登入時間 (ISO 8601)
}
```

**Python Pydantic:**

```python
class User(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: UserRole
    phone: Optional[str] = None
    department: Optional[str] = None
    license_number: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None
```

---

### 14.2 Patient (病患)

**TypeScript:**

```typescript
interface Patient {
  id: string;                                // 病患 ID (UUID)
  user_id: string;                           // 關聯使用者帳號
  medical_record_number: string;             // 病歷號碼
  name: string;                              // 姓名
  gender: Gender;                            // 性別
  date_of_birth: string;                     // 出生日期 (ISO 8601 date)
  phone: string | null;                      // 手機號碼
  emergency_contact: EmergencyContact | null; // 緊急聯絡人
  medical_history: MedicalHistoryItem[];     // 過去病史
  allergies: AllergyItem[];                  // 過敏史
  current_medications: MedicationItem[];     // 目前用藥
  total_sessions: number;                    // 總場次數 (計算欄位)
  total_reports: number;                     // 總報告數 (計算欄位)
  last_visit_at: string | null;              // 最後就診時間 (計算欄位)
  created_at: string;                        // 建立時間
  updated_at: string;                        // 更新時間
}

interface EmergencyContact {
  name: string;           // 聯絡人姓名
  relationship: string;   // 與病患的關係
  phone: string;          // 聯絡電話
}

interface MedicalHistoryItem {
  condition: string;              // 疾病名稱
  diagnosed_year: number | null;  // 診斷年份
  status: string;                 // "active" | "controlled" | "resolved"
  notes: string | null;           // 備註
}

interface AllergyItem {
  allergen: string;      // 過敏原
  type: string;          // "drug" | "food" | "environmental" | "other"
  reaction: string;      // 過敏反應
  severity: string;      // "mild" | "moderate" | "severe"
}

interface MedicationItem {
  name: string;          // 藥物名稱
  dose: string;          // 劑量
  frequency: string;     // 頻率
  route: string;         // 給藥途徑
  indication: string;    // 適應症
}
```

**Python Pydantic:**

```python
class EmergencyContact(BaseModel):
    name: str
    relationship: str
    phone: str

class MedicalHistoryItem(BaseModel):
    condition: str
    diagnosed_year: Optional[int] = None
    status: str  # "active" | "controlled" | "resolved"
    notes: Optional[str] = None

class AllergyItem(BaseModel):
    allergen: str
    type: str  # "drug" | "food" | "environmental" | "other"
    reaction: str
    severity: str  # "mild" | "moderate" | "severe"

class MedicationItem(BaseModel):
    name: str
    dose: str
    frequency: str
    route: str
    indication: str

class Patient(BaseModel):
    id: str
    user_id: str
    medical_record_number: str
    name: str
    gender: Gender
    date_of_birth: date
    phone: Optional[str] = None
    emergency_contact: Optional[EmergencyContact] = None
    medical_history: List[MedicalHistoryItem] = []
    allergies: List[AllergyItem] = []
    current_medications: List[MedicationItem] = []
    total_sessions: int = 0
    total_reports: int = 0
    last_visit_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
```

---

### 14.3 Session (問診場次)

**TypeScript:**

```typescript
interface Session {
  id: string;                         // 場次 ID (UUID)
  patient_id: string;                 // 病患 ID (FK -> patients)
  patient: PatientSummary;            // 病患摘要資訊
  doctor_id: string | null;           // 醫師 ID
  doctor: DoctorSummary | null;       // 醫師摘要資訊
  chief_complaint_id: string;         // 主訴 ID (UUID)
  chief_complaint_text: string | null; // 主訴文字 (自訂時使用)
  chief_complaint: ComplaintSummary;  // 主訴摘要
  status: SessionStatus;             // 場次狀態
  language: string;                   // 問診語言
  red_flag: boolean;                  // 是否觸發紅旗
  red_flag_reason: string | null;     // 紅旗原因
  duration_seconds: number | null;    // 場次時長 (秒)
  started_at: string | null;          // 開始時間
  completed_at: string | null;        // 完成時間
  created_at: string;                 // 建立時間
  updated_at: string;                 // 更新時間
}

interface PatientSummary {
  id: string;
  name: string;
  gender: Gender | null;
  date_of_birth: string | null;
}

interface DoctorSummary {
  id: string;
  name: string;
}

interface ComplaintSummary {
  id: string;
  name: string;
  category?: string;
}
```

**Python Pydantic:**

```python
class PatientSummary(BaseModel):
    id: str
    name: str
    gender: Optional[Gender] = None
    date_of_birth: Optional[date] = None

class DoctorSummary(BaseModel):
    id: str
    name: str

class ComplaintSummary(BaseModel):
    id: str
    name: str
    category: Optional[str] = None

class Session(BaseModel):
    id: str
    patient_id: str
    patient: PatientSummary
    doctor_id: Optional[str] = None
    doctor: Optional[DoctorSummary] = None
    chief_complaint_id: str
    chief_complaint_text: Optional[str] = None
    chief_complaint: ComplaintSummary
    status: SessionStatus
    language: str = "zh-TW"
    red_flag: bool = False
    red_flag_reason: Optional[str] = None
    duration_seconds: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
```

---

### 14.4 Conversation (對話訊息)

**TypeScript:**

```typescript
interface Conversation {
  id: string;                     // 訊息 ID (UUID)
  session_id: string;             // 所屬場次 ID
  sequence_number: number;        // 對話序號 (場次內遞增)
  role: ConversationRole;         // 發話者角色: patient | assistant | system
  content_text: string;           // 文字內容
  audio_url: string | null;       // 語音檔案 URL
  audio_duration_seconds: number | null; // 語音長度 (秒)
  stt_confidence: number | null;  // STT 信心分數 0~1
  red_flag_detected: boolean;     // 本輪是否偵測到紅旗
  metadata: Record<string, unknown>; // 擴充欄位 (JSONB)
  created_at: string;             // 建立時間
}
```

**Python Pydantic:**

```python
class Conversation(BaseModel):
    id: str
    session_id: str
    sequence_number: int
    role: ConversationRole  # "patient" | "assistant" | "system"
    content_text: str
    audio_url: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    stt_confidence: Optional[float] = None
    red_flag_detected: bool = False
    metadata: Dict[str, Any] = {}
    created_at: datetime
```

---

### 14.5 SOAPReport (SOAP 報告)

**TypeScript:**

```typescript
interface SOAPReport {
  id: string;                            // 報告 ID (UUID)
  session_id: string;                    // 所屬場次 ID
  patient_id: string;                    // 病患 ID
  patient: PatientSummary;               // 病患摘要
  doctor_id: string;                     // 醫師 ID
  doctor: DoctorSummary;                 // 醫師摘要
  status: ReportStatus;                  // 報告狀態: generating | generated | failed
  soap: SOAPContent;                     // SOAP 內容 (JSONB 結構化)
  raw_transcript: string | null;         // 完整對話逐字稿
  summary: string | null;                // 摘要
  icd10_codes: string[];                 // ICD-10 診斷碼
  ai_confidence_score: number;           // AI 信心分數 (0-1)
  review_status: ReviewStatus;           // 審閱狀態: pending | approved | revision_needed
  reviewed_by: string | null;            // 審閱醫師 ID
  reviewed_at: string | null;            // 審閱時間
  review_notes: string | null;           // 審閱備註
  version: number;                       // 版本號
  generated_at: string | null;           // 報告生成完成時間
  created_at: string;                    // 建立時間
  updated_at: string;                    // 更新時間
}

// SOAP JSONB 結構化定義 (同 shared_types.md 3.6)
interface SOAPContent {
  subjective: SubjectiveSection;
  objective: ObjectiveSection;
  assessment: AssessmentSection;
  plan: PlanSection;
}

interface SubjectiveSection {
  chief_complaint: string;
  hpi: {
    onset: string;
    location: string;
    duration: string;
    characteristics: string;
    severity: string;
    aggravating_factors: string[];
    relieving_factors: string[];
    associated_symptoms: string[];
    timing: string;
    context: string;
  };
  past_medical_history: {
    conditions: string[];
    surgeries: string[];
    hospitalizations: string[];
  };
  medication_history: {
    current: string[];
    past: string[];
    otc: string[];
  };
  system_review: Record<string, string>;
  social_history: Record<string, string>;
}

interface ObjectiveSection {
  vital_signs: {
    blood_pressure: string | null;
    heart_rate: number | null;
    respiratory_rate: number | null;
    temperature: number | null;
    spo2: number | null;
  };
  physical_exam: Record<string, string>;
  lab_results: LabResult[];
  imaging_results: ImagingResult[];
}

interface LabResult {
  test_name: string;
  result: string;
  reference_range: string;
  is_abnormal: boolean;
  date: string;
}

interface ImagingResult {
  test_name: string;
  result: string;
  date: string;
}

interface AssessmentSection {
  differential_diagnoses: DifferentialDiagnosis[];
  clinical_impression: string;
}

interface DifferentialDiagnosis {
  diagnosis: string;
  icd10: string;
  probability: string;   // "high" | "medium" | "low"
  reasoning: string;
}

interface PlanSection {
  recommended_tests: RecommendedTest[];
  treatments: Treatment[];
  follow_up: {
    interval: string;
    reason: string;
    additional_notes: string;
  };
  referrals: string[];
  patient_education: string[];
}

interface RecommendedTest {
  test_name: string;
  rationale: string;
  urgency: string;   // "urgent" | "routine" | "elective"
}

interface Treatment {
  type: string;
  name: string;
  instruction: string;
  note: string;
}
```

**Python Pydantic:**

```python
class HPIDetail(BaseModel):
    onset: str = ""
    location: str = ""
    duration: str = ""
    characteristics: str = ""
    severity: str = ""
    aggravating_factors: List[str] = []
    relieving_factors: List[str] = []
    associated_symptoms: List[str] = []
    timing: str = ""
    context: str = ""

class SubjectiveSection(BaseModel):
    chief_complaint: str
    hpi: HPIDetail = HPIDetail()
    past_medical_history: Dict[str, Any] = {}
    medication_history: Dict[str, Any] = {}
    system_review: Dict[str, str] = {}
    social_history: Dict[str, str] = {}

class VitalSigns(BaseModel):
    blood_pressure: Optional[str] = None
    heart_rate: Optional[int] = None
    respiratory_rate: Optional[int] = None
    temperature: Optional[float] = None
    spo2: Optional[int] = None

class LabResult(BaseModel):
    test_name: str
    result: str
    reference_range: str
    is_abnormal: bool
    date: str

class ObjectiveSection(BaseModel):
    vital_signs: VitalSigns = VitalSigns()
    physical_exam: Dict[str, str] = {}
    lab_results: List[LabResult] = []
    imaging_results: List[Dict[str, Any]] = []

class DifferentialDiagnosis(BaseModel):
    diagnosis: str
    icd10: str
    probability: str  # "high" | "medium" | "low"
    reasoning: str

class AssessmentSection(BaseModel):
    differential_diagnoses: List[DifferentialDiagnosis] = []
    clinical_impression: str = ""

class RecommendedTest(BaseModel):
    test_name: str
    rationale: str
    urgency: str = "routine"  # "urgent" | "routine" | "elective"

class Treatment(BaseModel):
    type: str
    name: str
    instruction: str = ""
    note: str = ""

class FollowUp(BaseModel):
    interval: str = ""
    reason: str = ""
    additional_notes: str = ""

class PlanSection(BaseModel):
    recommended_tests: List[RecommendedTest] = []
    treatments: List[Treatment] = []
    follow_up: FollowUp = FollowUp()
    referrals: List[str] = []
    patient_education: List[str] = []

class SOAPContent(BaseModel):
    subjective: SubjectiveSection
    objective: ObjectiveSection
    assessment: AssessmentSection
    plan: PlanSection

class SOAPReport(BaseModel):
    id: str
    session_id: str
    patient_id: str
    patient: PatientSummary
    doctor_id: str
    doctor: DoctorSummary
    status: ReportStatus
    soap: SOAPContent
    raw_transcript: Optional[str] = None
    summary: Optional[str] = None
    icd10_codes: List[str] = []
    ai_confidence_score: float
    review_status: ReviewStatus
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    version: int = 1
    generated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
```

---

### 14.6 Alert (紅旗警示)

**TypeScript:**

```typescript
interface Alert {
  id: string;                              // 警示 ID (UUID)
  session_id: string;                      // 所屬場次 ID
  conversation_id: string;                 // 觸發的對話訊息 ID
  patient_id: string;                      // 病患 ID
  patient: PatientSummary;                 // 病患摘要
  matched_rule_id: string | null;          // 匹配的規則 ID
  rule: RedFlagRuleSummary | null;         // 觸發規則摘要
  alert_type: AlertType;                   // 偵測方式: rule_based | semantic | combined
  severity: AlertSeverity;                 // 嚴重程度: critical | high | medium
  title: string;                           // 標題
  description: string;                     // 描述
  trigger_reason: string;                  // 觸發原因
  trigger_keywords: string[];              // 觸發的關鍵字
  llm_analysis: Record<string, unknown> | null; // LLM 語意分析結果
  suggested_actions: string[];             // 建議處置
  is_acknowledged: boolean;                // 是否已確認
  acknowledged_by: string | null;          // 確認者 ID
  acknowledged_at: string | null;          // 確認時間
  acknowledge_notes: string | null;        // 確認備註
  created_at: string;                      // 建立時間
  updated_at: string;                      // 更新時間
}

interface RedFlagRuleSummary {
  id: string;
  name: string;
  keywords: string[];
}
```

**Python Pydantic:**

```python
class RedFlagRuleSummary(BaseModel):
    id: str
    name: str
    keywords: List[str] = []

class Alert(BaseModel):
    id: str
    session_id: str
    conversation_id: str
    patient_id: str
    patient: PatientSummary
    matched_rule_id: Optional[str] = None
    rule: Optional[RedFlagRuleSummary] = None
    alert_type: AlertType  # "rule_based" | "semantic" | "combined"
    severity: AlertSeverity  # "critical" | "high" | "medium"
    title: str
    description: str
    trigger_reason: str
    trigger_keywords: List[str] = []
    llm_analysis: Optional[Dict[str, Any]] = None
    suggested_actions: List[str] = []
    is_acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledge_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

---

### 14.7 Notification (通知)

**TypeScript:**

```typescript
interface Notification {
  id: string;                          // 通知 ID (UUID)
  user_id: string;                     // 接收者 ID
  type: NotificationType;              // 通知類型: red_flag | session_complete | report_ready | system
  title: string;                       // 標題
  body: string;                        // 內容
  is_read: boolean;                    // 是否已讀
  read_at: string | null;              // 已讀時間
  data: Record<string, unknown>;       // 附加資料 (JSONB)
  created_at: string;                  // 建立時間
}
```

**Python Pydantic:**

```python
class Notification(BaseModel):
    id: str
    user_id: str
    type: NotificationType  # "red_flag" | "session_complete" | "report_ready" | "system"
    title: str
    body: str
    is_read: bool = False
    read_at: Optional[datetime] = None
    data: Dict[str, Any] = {}
    created_at: datetime
```

---

### 14.8 ChiefComplaint (主訴)

**TypeScript:**

```typescript
interface ChiefComplaint {
  id: string;                         // 主訴 ID (UUID)
  name: string;                       // 主訴名稱 (中文)
  name_en: string | null;             // 主訴名稱 (英文)
  description: string | null;         // 描述
  category: string;                   // 分類
  is_default: boolean;                // 是否為系統預設
  follow_up_questions: string[];      // AI 追問問題列表
  red_flag_keywords: string[];        // 紅旗關鍵字
  is_active: boolean;                 // 是否啟用
  display_order: number;              // 顯示排序
  created_by: string | null;          // 建立者 ID (NULL 表示系統預設)
  created_at: string;                 // 建立時間
  updated_at: string;                 // 更新時間
}
```

**Python Pydantic:**

```python
class ChiefComplaint(BaseModel):
    id: str
    name: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: str
    is_default: bool = False
    follow_up_questions: List[str] = []
    red_flag_keywords: List[str] = []
    is_active: bool = True
    display_order: int = 0
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

---

### 14.9 AuditLog (稽核日誌)

**TypeScript:**

```typescript
interface AuditLog {
  id: string;                         // 日誌 ID (BIGINT)
  user_id: string | null;             // 操作者 ID (系統操作時為 null)
  user: UserSummary | null;           // 操作者摘要
  action: AuditAction;                // 操作類型
  resource_type: ResourceType;        // 資源類型
  resource_id: string | null;         // 資源 ID
  details: Record<string, unknown> | null; // 操作詳情
  ip_address: string | null;          // 來源 IP
  user_agent: string | null;          // User Agent
  created_at: string;                 // 建立時間
}

interface UserSummary {
  id: string;
  name: string;
  role: UserRole;
}
```

**Python Pydantic:**

```python
class UserSummary(BaseModel):
    id: str
    name: str
    role: UserRole

class AuditLog(BaseModel):
    id: str
    user_id: Optional[str] = None
    user: Optional[UserSummary] = None
    action: AuditAction
    resource_type: str
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
```

---

### 14.10 RedFlagRule (紅旗規則)

**TypeScript:**

```typescript
interface RedFlagRule {
  id: string;                              // 規則 ID (UUID)
  name: string;                            // 規則名稱
  description: string | null;              // 描述
  category: string;                        // 分類
  keywords: string[];                      // 觸發關鍵字陣列
  regex_pattern: string | null;            // 正則表達式
  severity: AlertSeverity;                 // 嚴重程度: critical | high | medium
  suspected_diagnosis: string | null;      // 疑似診斷
  suggested_action: string | null;         // 建議處置
  is_active: boolean;                      // 是否啟用
  created_by: string | null;               // 建立者 ID
  created_at: string;                      // 建立時間
  updated_at: string;                      // 更新時間
}
```

**Python Pydantic:**

```python
class RedFlagRule(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category: str
    keywords: List[str] = []
    regex_pattern: Optional[str] = None
    severity: AlertSeverity  # "critical" | "high" | "medium"
    suspected_diagnosis: Optional[str] = None
    suggested_action: Optional[str] = None
    is_active: bool = True
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

---

### 14.11 FCMDevice (推播裝置)

**TypeScript:**

```typescript
interface FCMDevice {
  id: string;                    // 裝置 ID (UUID)
  user_id: string;               // 使用者 ID
  device_token: string;          // FCM Token
  platform: DevicePlatform;      // 裝置平台: ios | android | web
  device_name: string | null;    // 裝置名稱
  is_active: boolean;            // 是否有效
  created_at: string;            // 建立時間
  updated_at: string;            // 更新時間
}
```

**Python Pydantic:**

```python
class FCMDevice(BaseModel):
    id: str
    user_id: str
    device_token: str
    platform: DevicePlatform  # "ios" | "android" | "web"
    device_name: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
```

---

### 14.12 列舉型別 (Enum Types)

**TypeScript:**

```typescript
type UserRole = 'patient' | 'doctor' | 'admin';

type Gender = 'male' | 'female' | 'other';

type SessionStatus =
  | 'waiting'           // 等待中
  | 'in_progress'       // 進行中
  | 'completed'         // 已完成
  | 'aborted_red_flag'  // 紅旗中止
  | 'cancelled';        // 已取消

type ConversationRole = 'patient' | 'assistant' | 'system';

type ReportStatus = 'generating' | 'generated' | 'failed';

type ReviewStatus = 'pending' | 'approved' | 'revision_needed';

type AlertSeverity = 'critical' | 'high' | 'medium';

type AlertType = 'rule_based' | 'semantic' | 'combined';

type NotificationType = 'red_flag' | 'session_complete' | 'report_ready' | 'system';

type AuditAction =
  | 'create' | 'read' | 'update' | 'delete'
  | 'login' | 'logout'
  | 'export' | 'review' | 'acknowledge'
  | 'session_start' | 'session_end';

type DevicePlatform = 'ios' | 'android' | 'web';

type ResourceType =
  | 'session' | 'report' | 'alert'
  | 'patient' | 'complaint' | 'user'
  | 'red_flag_rule';
```

**Python Pydantic:**

```python
from enum import Enum

class UserRole(str, Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"

class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"

class SessionStatus(str, Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED_RED_FLAG = "aborted_red_flag"
    CANCELLED = "cancelled"

class ConversationRole(str, Enum):
    PATIENT = "patient"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class ReportStatus(str, Enum):
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"

class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REVISION_NEEDED = "revision_needed"

class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"

class AlertType(str, Enum):
    RULE_BASED = "rule_based"
    SEMANTIC = "semantic"
    COMBINED = "combined"

class NotificationType(str, Enum):
    RED_FLAG = "red_flag"
    SESSION_COMPLETE = "session_complete"
    REPORT_READY = "report_ready"
    SYSTEM = "system"

class AuditAction(str, Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    EXPORT = "export"
    REVIEW = "review"
    ACKNOWLEDGE = "acknowledge"
    SESSION_START = "session_start"
    SESSION_END = "session_end"

class DevicePlatform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"

class ResourceType(str, Enum):
    SESSION = "session"
    REPORT = "report"
    ALERT = "alert"
    PATIENT = "patient"
    COMPLAINT = "complaint"
    USER = "user"
    RED_FLAG_RULE = "red_flag_rule"
```

---

### 14.13 分頁包裝型別 (Pagination Wrapper)

**TypeScript:**

```typescript
interface PaginatedResponse<T> {
  data: T[];
  pagination: PaginationInfo;
}

interface PaginationInfo {
  next_cursor: string | null;
  has_more: boolean;
  limit: number;
  total_count: number;
}
```

**Python Pydantic:**

```python
from typing import TypeVar, Generic, List, Optional
from pydantic.generics import GenericModel

T = TypeVar("T")

class PaginationInfo(BaseModel):
    next_cursor: Optional[str] = None
    has_more: bool
    limit: int
    total_count: int

class PaginatedResponse(GenericModel, Generic[T]):
    data: List[T]
    pagination: PaginationInfo
```

---

### 14.14 錯誤回應型別 (Error Response)

**TypeScript:**

```typescript
interface ErrorResponse {
  error: {
    code: string;           // 錯誤碼 (如 "UNAUTHORIZED")
    message: string;        // 人類可讀訊息
    details?: object;       // 詳細錯誤資訊
    request_id: string;     // 請求追蹤 ID
    timestamp: string;      // ISO 8601
  };
}
```

**Python Pydantic:**

```python
class ErrorDetail(BaseModel):
    field: Optional[str] = None
    reason: str
    value: Optional[Any] = None

class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[List[ErrorDetail]] = None
    request_id: str
    timestamp: datetime

class ErrorResponse(BaseModel):
    error: ErrorBody
```

---

## 15. 錯誤碼對照表

以下列出系統中所有可能的錯誤碼、對應的 HTTP 狀態碼、說明及範例情境。

### 15.1 認證與授權相關

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `UNAUTHORIZED` | `401` | 未提供認證資訊或認證資訊無效 | 未帶 Authorization 標頭 |
| `TOKEN_EXPIRED` | `401` | JWT Token 已過期 | Access Token 超過 15 分鐘有效期 |
| `TOKEN_INVALID` | `401` | JWT Token 格式無效或簽章驗證失敗 | Token 遭竄改或格式錯誤 |
| `TOKEN_REUSE_DETECTED` | `401` | 偵測到 Refresh Token 重複使用 | 可能的 Token 竊取攻擊，所有 Token 已撤銷 |
| `INVALID_CREDENTIALS` | `401` | 帳號或密碼不正確 | 登入時輸入錯誤的密碼 |
| `FORBIDDEN` | `403` | 已認證但無權執行此操作 | 病患嘗試存取管理員端點 |
| `ACCOUNT_DISABLED` | `403` | 帳號已被停用 | 管理員已停用此使用者帳號 |

### 15.2 驗證相關

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `VALIDATION_ERROR` | `422` | 請求參數或 Body 驗證失敗 | 缺少必填欄位、格式錯誤、值超出範圍 |
| `INVALID_STATUS_TRANSITION` | `409` | 不合法的狀態轉移 | 嘗試將已完成的場次改為進行中 |
| `CANNOT_CHANGE_OWN_ROLE` | `409` | 不允許變更自己的角色 | 管理員嘗試變更自己的角色 |

### 15.3 資源相關

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `NOT_FOUND` | `404` | 請求的資源不存在 | 查詢不存在的場次 ID |
| `PATIENT_NOT_FOUND` | `404` | 指定的病患不存在 | 建立場次時提供不存在的 patient_id |
| `COMPLAINT_NOT_FOUND` | `404` | 指定的主訴不存在 | 建立場次時提供不存在的 complaint_id |

### 15.4 衝突相關

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `EMAIL_ALREADY_EXISTS` | `409` | 電子郵件已被註冊 | 使用已存在的 email 註冊新帳號 |
| `SESSION_ALREADY_ACTIVE` | `409` | 該病患已有進行中的場次 | 病患尚有未完成的場次時嘗試建立新場次 |
| `REPORT_ALREADY_EXISTS` | `409` | 該場次已有報告且未要求重新生成 | 重複觸發報告生成但未設定 regenerate=true |
| `COMPLAINT_ALREADY_EXISTS` | `409` | 同名主訴已存在 | 建立與現有主訴名稱重複的自訂主訴 |
| `COMPLAINT_IN_USE` | `409` | 主訴正被使用中，無法停用 | 嘗試停用正在進行中場次所使用的主訴 |
| `RULE_ALREADY_EXISTS` | `409` | 同名紅旗規則已存在 | 建立與現有規則名稱重複的紅旗規則 |
| `ALERT_ALREADY_ACKNOWLEDGED` | `409` | 警示已被確認 | 重複確認同一個紅旗警示 |

### 15.5 業務邏輯相關

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `SESSION_NOT_ACTIVE` | `409` | 場次狀態非進行中，無法執行此操作 | 嘗試在已完成的場次中發送訊息 |
| `SESSION_NOT_COMPLETED` | `409` | 場次尚未完成，無法生成報告 | 嘗試為進行中的場次生成 SOAP 報告 |
| `INSUFFICIENT_CONVERSATION` | `409` | 對話內容不足 | 場次對話不足 4 輪即嘗試生成報告 |
| `REPORT_NOT_READY` | `409` | 報告尚在生成中 | 嘗試審閱或匯出仍在生成中的報告 |

### 15.6 檔案相關

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `FILE_TOO_LARGE` | `413` | 上傳檔案超過大小限制 | 語音檔案超過 10MB |
| `UNSUPPORTED_MEDIA_TYPE` | `415` | 不支援的檔案格式 | 上傳非支援的音訊格式 (例如 .flac) |

### 15.7 速率限制

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `RATE_LIMIT_EXCEEDED` | `429` | 請求頻率超過限制 | 在一分鐘內發送超過 120 次 GET 請求 |

### 15.8 伺服器相關

| 錯誤碼 | HTTP 狀態碼 | 說明 | 範例情境 |
|---|---|---|---|
| `INTERNAL_SERVER_ERROR` | `500` | 伺服器內部錯誤 | 未預期的系統異常 |
| `AI_SERVICE_UNAVAILABLE` | `503` | AI 語言模型服務不可用 | Claude API 暫時無法連線 |
| `STT_SERVICE_UNAVAILABLE` | `503` | 語音辨識服務不可用 | Google Cloud STT 服務暫時無法連線 |
| `TTS_SERVICE_UNAVAILABLE` | `503` | 語音合成服務不可用 | Google Cloud TTS 服務暫時無法連線 |
| `DATABASE_ERROR` | `503` | 資料庫連線異常 | PostgreSQL 連線逾時 |
| `STORAGE_ERROR` | `503` | 檔案儲存服務異常 | S3 儲存服務無法連線 |

---

> 文件結尾
>
> 本 API 規格書涵蓋泌尿科 AI 語音問診助手的所有端點定義、資料模型與錯誤處理規範。
> 所有型別定義以 shared_types.md 為準。如有任何疑問或需要修訂，請聯繫後端開發團隊。
