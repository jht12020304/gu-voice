# 泌尿科 AI 語音問診助手 -- 後端規格書

> **本文件的型別定義、Enum 值、資料模型以 shared_types.md 為準。**

> 版本: 2.0.0
> 日期: 2026-04-10
> 技術棧: Python FastAPI / PostgreSQL / Redis / WebSocket / Claude API / Google Cloud STT & TTS / Firebase Cloud Messaging / S3

---

## 目錄

1. [服務模組架構 (Service Architecture)](#1-服務模組架構-service-architecture)
2. [目錄結構 (Project Structure)](#2-目錄結構-project-structure)
3. [業務邏輯流程 (Business Logic Flows)](#3-業務邏輯流程-business-logic-flows)
4. [AI Pipeline 詳細設計](#4-ai-pipeline-詳細設計)
5. [背景任務 (Background Tasks)](#5-背景任務-background-tasks)
6. [錯誤處理策略 (Error Handling)](#6-錯誤處理策略-error-handling)
7. [環境配置 (Configuration)](#7-環境配置-configuration)

---

## 1. 服務模組架構 (Service Architecture)

### 1-A. 認證與授權服務 (Auth Service)

#### 概述

本服務負責所有使用者身分驗證、權杖管理與角色存取控制。採用 JWT (JSON Web Token) 雙權杖機制，搭配 Redis 實現權杖黑名單與即時撤銷。

#### 角色定義 (Roles)

| 角色 (Role) | 代碼 | 說明 |
|---|---|---|
| 病患 | `patient` | 透過行動裝置進行問診的使用者 |
| 醫師 | `doctor` | 檢閱問診結果、管理主訴項目、確認 SOAP 報告的醫療人員 |
| 管理員 | `admin` | 系統管理者，可管理所有使用者、設定與稽核日誌 |

#### JWT 權杖規格

**Access Token:**
- 演算法: RS256 (非對稱加密，支援 key rotation)
- 有效期: 15 分鐘
- Payload 欄位:
  - `sub`: 使用者 UUID
  - `role`: 角色代碼
  - `exp`: 過期時間 (Unix timestamp)
  - `iat`: 簽發時間
  - `jti`: 權杖唯一識別碼 (UUID v4)

**Refresh Token:**
- 有效期: 7 天
- 儲存於 Redis，key 格式: `gu:refresh_token:{jti}`
- 支援一次性使用 (rotation)，每次 refresh 後舊 token 失效並產生新 token

#### API 端點

**POST /api/v1/auth/register**
- 說明: 使用者註冊
- Request Body:
  ```json
  {
    "email": "user@example.com",
    "password": "hashed_at_client_or_raw",
    "name": "王大明",
    "role": "patient",
    "phone": "+886912345678",
    "department": "泌尿科",
    "license_number": "醫字第012345號"
  }
  ```
- 流程:
  1. 驗證 email 格式
  2. 檢查 email 是否已註冊
  3. 使用 bcrypt 雜湊密碼 (cost factor=12)
  4. 若角色為 `doctor`，驗證 `license_number` 不得為空
  5. 建立使用者記錄於 PostgreSQL
  6. 回傳 access_token + refresh_token
- Response: `201 Created`
  ```json
  {
    "user_id": "uuid",
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 900
  }
  ```

**POST /api/v1/auth/login**
- 說明: 使用者登入
- Request Body:
  ```json
  {
    "email": "user@example.com",
    "password": "raw_password"
  }
  ```
- 流程:
  1. 根據 email 查詢使用者
  2. 使用 bcrypt 驗證密碼
  3. 檢查帳號狀態 (是否停用)
  4. 產生 access_token 與 refresh_token
  5. 將 refresh_token 的 jti 存入 Redis (TTL=7d)
  6. 更新 `last_login_at`
  7. 記錄登入稽核日誌
- Response: `200 OK` (同 register response 格式)
- 錯誤: `401 Unauthorized` -- 帳號或密碼錯誤

**POST /api/v1/auth/refresh**
- 說明: 更新 access token
- Request Body:
  ```json
  {
    "refresh_token": "eyJ..."
  }
  ```
- 流程:
  1. 解碼 refresh_token，驗證簽名與過期時間
  2. 檢查 jti 是否存在於 Redis (未被撤銷)
  3. 從 Redis 移除舊 jti (一次性使用)
  4. 產生新的 access_token 與 refresh_token
  5. 將新 refresh_token 的 jti 存入 Redis
- Response: `200 OK` (新的 token pair)

**POST /api/v1/auth/logout**
- 說明: 使用者登出
- Request Header: `Authorization: Bearer {access_token}`
- 流程:
  1. 將 access_token 的 jti 加入 Redis 黑名單 (TTL=剩餘有效時間)
  2. 從 Redis 移除對應的 refresh_token jti
  3. 記錄登出稽核日誌
- Response: `204 No Content`

#### RBAC Middleware 設計

```python
# 權限矩陣定義
PERMISSIONS = {
    "patient": [
        "session:create",
        "session:read:own",
        "conversation:participate",
        "report:read:own",
        "complaint:read",
    ],
    "doctor": [
        "session:read:all",
        "session:assign",
        "conversation:read:all",
        "report:read:all",
        "report:confirm",
        "report:export",
        "complaint:create",
        "complaint:update",
        "complaint:delete",
        "dashboard:read",
        "red_flag:read",
        "red_flag:acknowledge",
    ],
    "admin": [
        "*",  # 所有權限
    ],
}
```

Middleware 執行流程:
1. 從 Request Header 擷取 Bearer Token
2. 使用 RS256 公鑰解碼並驗證 JWT 簽名
3. 檢查 jti 是否在黑名單 (Redis)
4. 從 payload 取得 `role`
5. 比對 endpoint 所需權限與角色權限矩陣
6. 權限不足則回傳 `403 Forbidden`
7. 將 `current_user` 注入 request state

---

### 1-B. 主訴管理服務 (Chief Complaint Service)

#### 概述

管理問診場次可選用的主訴項目 (chief complaints)。系統預設一組泌尿科常見主訴，醫師可自訂額外項目。主訴用於引導 AI 對話方向。

#### 資料模型

```
ChiefComplaint:
  id: UUID (PK)
  name: str (e.g., "頻尿")
  name_en: str (e.g., "Frequent urination")
  description: str (詳細說明)
  category: str (分類名稱, e.g., "排尿症狀")
  is_default: bool (系統預設=true)
  created_by: UUID (FK -> User, nullable for defaults)
  display_order: int
  is_active: bool
  created_at: datetime
  updated_at: datetime
```

#### 預設分類 (6 類)

- 排尿症狀
- 血尿與異常
- 疼痛
- 腫塊與外觀
- 性功能障礙
- 其他

#### 系統預設主訴清單

| 分類 | 主訴 | 英文 |
|---|---|---|
| 排尿症狀 | 頻尿 | Frequent urination |
| 排尿症狀 | 急尿 | Urinary urgency |
| 排尿症狀 | 夜尿 | Nocturia |
| 排尿症狀 | 排尿困難 | Dysuria |
| 排尿症狀 | 尿流細弱 | Weak stream |
| 排尿症狀 | 尿滯留 | Urinary retention |
| 排尿症狀 | 尿失禁 | Urinary incontinence |
| 疼痛 | 腰痛 | Flank pain |
| 疼痛 | 下腹痛 | Lower abdominal pain |
| 疼痛 | 會陰部疼痛 | Perineal pain |
| 疼痛 | 睪丸疼痛 | Testicular pain |
| 血尿與異常 | 血尿 | Hematuria |
| 血尿與異常 | 尿液混濁 | Cloudy urine |
| 血尿與異常 | 尿道分泌物 | Urethral discharge |
| 性功能障礙 | 性功能障礙 | Sexual dysfunction |
| 其他 | 腎結石 | Kidney stones |
| 其他 | 攝護腺相關 | Prostate-related |
| 其他 | 泌尿道感染 | Urinary tract infection |

#### API 端點

**GET /api/v1/complaints**
- 說明: 取得所有啟用中的主訴清單 (含分類)
- 權限: `patient`, `doctor`, `admin`
- Query Parameters:
  - `category` (optional): 依分類名稱篩選
  - `include_custom` (optional, default=true): 是否包含醫師自訂項目
- Response:
  ```json
  {
    "data": [
      {
        "category": "排尿症狀",
        "complaints": [
          {
            "id": "uuid",
            "name": "頻尿",
            "name_en": "Frequent urination",
            "description": "...",
            "is_default": true
          }
        ]
      }
    ]
  }
  ```

**POST /api/v1/complaints**
- 說明: 醫師新增自訂主訴
- 權限: `doctor`, `admin`
- Request Body:
  ```json
  {
    "name": "排尿中斷",
    "name_en": "Intermittent stream",
    "description": "排尿過程中尿流中斷再恢復",
    "category": "排尿症狀"
  }
  ```
- Response: `201 Created`

**PUT /api/v1/complaints/{complaint_id}**
- 說明: 更新主訴資訊
- 權限: `doctor` (僅自己建立的), `admin`
- 限制: 系統預設主訴 (`is_default=true`) 僅 admin 可修改

**DELETE /api/v1/complaints/{complaint_id}**
- 說明: 停用主訴 (軟刪除，設 `is_active=false`)
- 權限: `doctor` (僅自己建立的), `admin`
- 限制: 系統預設主訴不可刪除

**GET /api/v1/complaints/categories**
- 說明: 取得所有分類
- 權限: 所有角色

---

### 1-C. 病患管理服務 (Patient Service)

#### 概述

管理病患的基本資料、病史、過敏史及用藥資訊。病患透過 User 帳號關聯，但病患的醫療資訊獨立儲存於 patients 表。

#### 資料模型

```
Patient:
  id: UUID (PK)
  user_id: UUID (FK -> User)
  medical_record_number: str (病歷號碼，唯一)
  name: str (姓名)
  gender: gender_type (性別)
  date_of_birth: date (出生日期)
  phone: str (nullable, 手機號碼)
  emergency_contact: JSONB (nullable, 緊急聯絡人 {name, relationship, phone})
  medical_history: JSONB (nullable, 過去病史)
  allergies: JSONB (nullable, 過敏史)
  current_medications: JSONB (nullable, 目前用藥)
  created_at: datetime
  updated_at: datetime
```

**JSONB 結構定義：**

```jsonc
// emergency_contact
{
  "name": "王小明",
  "relationship": "配偶",
  "phone": "0912345678"
}

// medical_history
[
  {
    "condition": "高血壓",
    "diagnosed_year": 2018,
    "status": "controlled",     // "active" | "controlled" | "resolved"
    "notes": "規律服藥中"
  }
]

// allergies
[
  {
    "allergen": "Penicillin",
    "type": "drug",             // "drug" | "food" | "environmental" | "other"
    "reaction": "皮疹",
    "severity": "moderate"      // "mild" | "moderate" | "severe"
  }
]

// current_medications
[
  {
    "name": "Amlodipine",
    "dose": "5mg",
    "frequency": "QD",
    "route": "oral",
    "indication": "高血壓"
  }
]
```

#### API 端點

**POST /api/v1/patients**
- 說明: 建立病患資料
- 權限: `doctor`, `admin`
- Request Body:
  ```json
  {
    "user_id": "uuid",
    "medical_record_number": "MRN-20260001",
    "name": "王大明",
    "gender": "male",
    "date_of_birth": "1985-03-15",
    "phone": "0912345678"
  }
  ```

**GET /api/v1/patients**
- 說明: 查詢病患列表
- 權限: `doctor`, `admin`
- Query Parameters: `cursor`, `limit`, `name`, `medical_record_number`

**GET /api/v1/patients/{patient_id}**
- 說明: 取得病患詳情
- 權限: `patient` (僅自己), `doctor`, `admin`

**PATCH /api/v1/patients/{patient_id}**
- 說明: 更新病患資料
- 權限: `doctor`, `admin`

---

### 1-D. 問診場次服務 (Session Service)

#### 概述

管理問診場次的完整生命週期，包括建立、進行中、完成或因紅旗中止。同時管理病患等候佇列與醫師指派。

#### 場次狀態機 (State Machine)

```
               +---> in_progress ---+---> completed
               |                    |
  waiting -----+                    +---> aborted_red_flag
               |                    |
               +---> cancelled <----+
```

狀態說明:
- `waiting`: 場次已建立，等待開始問診
- `in_progress`: 問診進行中，AI 對話活躍
- `completed`: 問診正常完成，SOAP 報告已產生或產生中
- `aborted_red_flag`: 因偵測到紅旗症狀而中止，已發出警報
- `cancelled`: 病患或系統取消

合法狀態轉移：

| 起始狀態 | 可轉移至 |
|---------|---------|
| `waiting` | `in_progress`, `cancelled` |
| `in_progress` | `completed`, `aborted_red_flag`, `cancelled` |
| `completed` | (終態) |
| `aborted_red_flag` | (終態) |
| `cancelled` | (終態) |

#### 資料模型

```
Session:
  id: UUID (PK)
  patient_id: UUID (FK -> patients.id)
  doctor_id: UUID (FK -> users.id, nullable, 可稍後指派)
  chief_complaint_id: UUID (FK -> chief_complaints.id)
  chief_complaint_text: str (nullable, 自訂主訴文字)
  status: session_status (default: 'waiting')
  red_flag: bool (default: false)
  red_flag_reason: text (nullable)
  language: str (default: 'zh-TW')
  started_at: datetime (nullable)
  completed_at: datetime (nullable)
  duration_seconds: int (nullable)
  created_at: datetime
  updated_at: datetime
```

#### API 端點

**POST /api/v1/sessions**
- 說明: 病患建立新問診場次
- 權限: `patient`
- Request Body:
  ```json
  {
    "patient_id": "uuid",
    "chief_complaint_id": "uuid",
    "chief_complaint_text": "最近一週症狀加重",
    "language": "zh-TW"
  }
  ```
- 流程:
  1. 驗證 chief_complaint_id 為有效且啟用的主訴
  2. 驗證 patient_id 對應有效的病患
  3. 檢查病患是否有進行中的場次 (同時僅允許一個)
  4. 建立 Session 記錄，狀態為 `waiting`
  5. 將場次加入等候佇列 (Redis sorted set `gu:queue:patients`)
  6. 透過 WebSocket 通知儀表板佇列更新
- Response: `201 Created`

**PATCH /api/v1/sessions/{session_id}/start**
- 說明: 啟動問診 (狀態轉移: waiting -> in_progress)
- 權限: `patient` (僅自己的場次)
- 流程:
  1. 驗證場次狀態為 `waiting`
  2. 更新狀態為 `in_progress`，記錄 `started_at`
  3. 初始化對話上下文於 Redis (`gu:session:{id}:context`)
  4. 透過 WebSocket 通知儀表板

**PATCH /api/v1/sessions/{session_id}/complete**
- 說明: 完成問診 (狀態轉移: in_progress -> completed)
- 權限: `patient`, `doctor`
- 流程:
  1. 驗證場次狀態為 `in_progress`
  2. 更新狀態為 `completed`，記錄 `completed_at` 與 `duration_seconds`
  3. 觸發 SOAP 報告產生 (背景任務)
  4. 從等候佇列移除
  5. 透過 WebSocket 通知儀表板

**PATCH /api/v1/sessions/{session_id}/abort**
- 說明: 因紅旗中止問診 (系統自動或醫師手動)
- 權限: `system`, `doctor`
- 流程:
  1. 更新狀態為 `aborted_red_flag`，設定 `red_flag=true` 與 `red_flag_reason`
  2. 結束 WebSocket 對話連線
  3. 傳送緊急通知給所有當值醫師
  4. 記錄紅旗警示

**PATCH /api/v1/sessions/{session_id}/assign**
- 說明: 醫師指派 (或自動指派)
- 權限: `doctor`, `admin`
- Request Body:
  ```json
  {
    "doctor_id": "uuid"
  }
  ```

**GET /api/v1/sessions**
- 說明: 查詢場次列表
- 權限: `patient` (僅自己的), `doctor` (所有), `admin` (所有)
- Query Parameters:
  - `status`: 依狀態篩選
  - `date_from`, `date_to`: 日期範圍
  - `patient_id`: 依病患篩選 (僅 doctor/admin)
  - `cursor`, `limit`: 游標分頁

**GET /api/v1/sessions/{session_id}**
- 說明: 取得單一場次詳情 (含對話摘要)
- 權限: `patient` (僅自己的), `doctor`, `admin`

#### 等候佇列管理

使用 Redis Sorted Set 管理即時佇列:
- Key: `gu:queue:patients`
- Score: 場次建立時間的 Unix timestamp
- Value: session_id

佇列操作:
- 加入佇列: `ZADD gu:queue:patients {timestamp} {session_id}`
- 取得佇列: `ZRANGEBYSCORE gu:queue:patients -inf +inf`
- 取得位置: `ZRANK gu:queue:patients {session_id}`
- 移除: `ZREM gu:queue:patients {session_id}`

---

### 1-E. 對話服務 (Conversation Service)

#### 概述

核心服務，負責即時音訊串流處理、語音辨識 (STT)、LLM 對話引擎、語音合成 (TTS) 的全流程協調。透過 WebSocket 實現雙向即時通訊。

#### 資料模型

> **設計決策：單層扁平結構，一行一輪對話。**

```
Conversation:
  id: UUID (PK)
  session_id: UUID (FK -> sessions)
  sequence_number: int (場次內遞增)
  role: conversation_role ("patient" | "assistant" | "system")
  content_text: text (文字內容)
  audio_url: str (nullable, 語音檔案 URL)
  audio_duration_seconds: numeric(8,2) (nullable)
  stt_confidence: numeric(5,4) (nullable, 0~1)
  red_flag_detected: bool (default false)
  metadata: JSONB (nullable, 擴充欄位)
  created_at: datetime

ConversationContext (Redis):
  key: "gu:session:{session_id}:context"
  value: JSON {
    "session_id": "uuid",
    "complaint_name": "頻尿",
    "turns": [
      {"role": "assistant", "content": "..."},
      {"role": "patient", "content": "..."}
    ],
    "current_topic": "symptom_duration",
    "asked_questions": ["onset", "frequency"],
    "red_flags_found": [],
    "turn_count": 5
  }
  TTL: 3600 (1 小時, 每次互動重設)
```

**metadata JSONB 結構：**

```jsonc
{
  "stt_engine": "google-chirp-v2",
  "stt_language": "zh-TW",
  "llm_model": "claude-sonnet-4-20250514",
  "llm_tokens_used": 256,
  "tts_engine": "google-neural2",
  "tts_voice": "cmn-TW-Wavenet-A",
  "audio_format": "wav",
  "audio_sample_rate": 16000
}
```

**分區策略：** 按月 Range Partition（以 `created_at` 為分區鍵）。

**唯一約束：** `UNIQUE (session_id, sequence_number)`

#### WebSocket 端點

**WS /api/v1/ws/sessions/{id}/stream**

連線方式: `wss://{host}/api/v1/ws/sessions/{id}/stream?token={access_token}`

連線建立流程:
1. 驗證 WebSocket 升級請求中的 JWT token (query parameter `token`)
2. 驗證 session_id 對應的場次存在且狀態為 `in_progress`
3. 驗證連線使用者為該場次的病患
4. 註冊連線至 ConnectionManager
5. 從 Redis 載入或初始化對話上下文
6. 傳送歡迎訊息 (AI 開場白)

訊息協定 (Message Protocol):

所有 WebSocket 訊息使用統一包裝格式：

```json
{
  "type": "string",
  "id": "uuid",
  "timestamp": "ISO 8601",
  "payload": {}
}
```

**Client -> Server 訊息:**

| type | payload | 說明 |
|------|---------|------|
| `audio_chunk` | `{audio_data: string(base64), chunk_index: int, is_final: bool, format: "wav", sample_rate: 16000}` | 音訊片段 |
| `text_message` | `{text: string}` | 文字訊息（非語音備用） |
| `control` | `{action: "end_session" \| "pause_recording" \| "resume_recording"}` | 控制指令 |
| `ping` | `{}` | 心跳（每 30 秒） |

**Server -> Client 訊息:**

| type | payload | 說明 |
|------|---------|------|
| `connection_ack` | `{session_id, status, config: {audio_format, sample_rate, max_chunk_size_bytes}}` | 連線確認 |
| `stt_partial` | `{text: string, confidence: float, is_final: false}` | STT 中間結果 |
| `stt_final` | `{message_id: string, text: string, confidence: float, is_final: true}` | STT 最終結果 |
| `ai_response_start` | `{message_id: string}` | AI 回應開始 |
| `ai_response_chunk` | `{message_id: string, text: string, chunk_index: int}` | AI 回應串流片段 |
| `ai_response_end` | `{message_id: string, full_text: string, tts_audio_url: string}` | AI 回應結束 + TTS 音訊 |
| `red_flag_alert` | `{alert_id, severity, title, description, suggested_actions: string[]}` | 紅旗警示 |
| `session_status` | `{session_id, status, previous_status, reason: string?}` | 場次狀態變更 |
| `error` | `{code: string, message: string}` | 錯誤訊息 |
| `pong` | `{server_time: string}` | 心跳回應 |

#### 對話處理管線 (Conversation Pipeline)

完整的單一輪次處理流程:

```
1. 接收音訊串流
   |
2. 累積 audio chunks (buffer)
   |
3. 收到 audio_end 信號
   |
4. +--> [STT Pipeline] 語音辨識 (串流處理)
   |     |
   |     +--> 傳送即時 transcription 給前端
   |
5. 取得最終轉譯文字
   |
6. +-------+-------+
   |               |
   v               v
7. [LLM Pipeline] [Red Flag Pipeline] (並行處理)
   |               |
   |               +--> 若偵測到紅旗 -> 通知服務
   |
8. 取得 LLM 回應文字
   |
9. [TTS Pipeline] 語音合成
   |
10. 串流傳送 audio chunks 給前端
    |
11. 儲存本輪對話記錄至 DB (conversations 表)
    |
12. 更新 Redis 對話上下文
```

#### 對話上下文管理策略

**滑動視窗 (Sliding Window):**
- 最大保留最近 20 輪對話於 Redis context
- 超過 20 輪時，移除最舊的輪次但保留摘要
- 對話摘要由 LLM 自動產生 (每 10 輪)

**Context 重建:**
- WebSocket 斷線重連時，從 Redis 還原上下文
- Redis 過期後，從 PostgreSQL 的 conversations 表重建最近 10 輪

---

### 1-F. 紅旗偵測服務 (Red Flag Detection Service)

#### 概述

雙層並行偵測管線，同時使用規則引擎 (Rule Engine) 與 LLM 語意分析 (Semantic Analysis) 偵測病患描述中的危險信號。任一層偵測到紅旗即觸發警報。

#### 資料模型

```
RedFlagRule:
  id: UUID (PK)
  name: str (規則名稱)
  description: str
  category: str (分類)
  keywords: TEXT[] (觸發關鍵字陣列)
  regex_pattern: str (nullable, 正則表達式)
  severity: alert_severity ("critical" | "high" | "medium")
  suspected_diagnosis: str (nullable, 疑似診斷)
  suggested_action: str (nullable, 建議處置)
  is_active: bool
  created_by: UUID (FK -> User)
  created_at: datetime
  updated_at: datetime

RedFlagAlert:
  id: UUID (PK)
  session_id: UUID (FK -> sessions)
  conversation_id: UUID (觸發的對話訊息 ID，不設外鍵約束，因 conversations 為分區表)
  alert_type: alert_type ("rule_based" | "semantic" | "combined")
  severity: alert_severity
  title: str (警示標題)
  description: text (nullable, 警示描述)
  trigger_reason: text (觸發原因)
  trigger_keywords: TEXT[] (nullable, 觸發的關鍵字)
  matched_rule_id: UUID (FK -> RedFlagRule, nullable)
  llm_analysis: JSONB (nullable, LLM 語意分析結果)
  suggested_actions: TEXT[] (nullable, 建議處置)
  acknowledged_by: UUID (FK -> User, nullable)
  acknowledged_at: datetime (nullable)
  acknowledge_notes: text (nullable, 確認備註)
  created_at: datetime
```

**注意：** `conversation_id` 不使用外鍵約束，因為 `conversations` 表為分區表，PostgreSQL 不支援外鍵引用分區表的非主鍵欄位。改以應用層保證參照完整性。

#### 規則引擎 (Rule Engine) 設計

**預設紅旗規則:**

| 嚴重度 | 規則名稱 | 觸發條件 | 疑似診斷 | 建議處置 |
|---|---|---|---|---|
| critical | 大量血尿 | keywords: ["大量血尿","整個馬桶都是血","血塊"] regex: `血尿.*(大量\|很多\|嚴重\|止不住)` | 泌尿道大出血 | 立即就醫 |
| critical | 急性尿滯留 | keywords: ["完全尿不出來","脹痛","腹部鼓起"] regex: `(尿不出來\|排不出).*(好幾個小時\|一整天\|肚子很脹)` | 急性尿滯留 | 立即就醫導尿 |
| critical | 劇烈疼痛 | keywords: ["痛到無法忍受","痛到打滾","劇痛"] regex: `(腰\|肚子\|睪丸).*(劇痛\|劇烈\|受不了)` | 腎絞痛/睪丸扭轉 | 立即就醫 |
| high | 發燒合併泌尿症狀 | keywords: ["發燒","發高燒","體溫很高"] regex: `(發燒\|高燒).*(尿\|腰痛\|寒顫)` | 泌尿道感染 | 儘速就醫 |
| high | 外傷 | keywords: ["撞到","外傷","受傷","車禍"] regex: `(生殖器\|睪丸\|腰部).*(受傷\|撞\|外傷)` | 泌尿系統外傷 | 儘速就醫 |
| high | 睪丸急性腫痛 | keywords: ["睪丸突然腫","睪丸突然痛"] regex: `睪丸.*(突然\|急性).*(腫\|痛\|扭轉)` | 睪丸扭轉 | 立即就醫 |
| medium | 體重急劇下降 | keywords: ["瘦很多","體重下降","食慾不振"] | 惡性腫瘤疑慮 | 安排進一步檢查 |
| medium | 持續性血尿 | regex: `血尿.*(持續\|好幾天\|一個月\|反覆)` | 泌尿道腫瘤 | 安排進一步檢查 |

**關鍵字比對演算法:**
1. 對病患輸入文字進行繁簡體正規化
2. 移除標點符號與多餘空白
3. 逐一比對 keywords 清單 (部分匹配)
4. 執行 regex 匹配 (若有定義)

**規則引擎效能最佳化:**
- 所有啟用規則在服務啟動時載入記憶體
- 使用 Aho-Corasick 演算法進行多模式字串匹配
- 規則更新時透過 Redis Pub/Sub 通知所有 worker 重新載入

#### LLM 語意分析引擎

並行於規則引擎執行，使用 Claude API 進行語意理解:

```
System Prompt:
你是一個泌尿科醫療紅旗偵測系統。根據以下病患對話內容，判斷是否存在需要
緊急處理的危險信號。

評估標準:
1. critical (立即危險): 可能危及生命或器官功能的情況
   - 大量活動性出血
   - 急性尿滯留 (>8小時)
   - 嚴重感染徵兆 (高燒+泌尿症狀)
   - 睪丸扭轉疑慮
   - 嚴重外傷

2. high (需緊急處理): 需要醫師盡快評估的情況
   - 中度持續出血
   - 發燒合併感染症狀
   - 急性劇烈疼痛
   - 生殖器或泌尿系統外傷

3. medium (需注意): 需要記錄並追蹤的情況
   - 不明原因體重下降
   - 慢性持續症狀惡化
   - 複發性感染

4. none: 未偵測到紅旗

請僅以 JSON 格式回應:
{
  "severity": "critical|high|medium|none",
  "detected": true|false,
  "reason": "簡要說明偵測原因",
  "matched_symptoms": ["症狀1", "症狀2"],
  "confidence": 0.0-1.0
}
```

#### 偵測後動作流程

```
紅旗偵測結果
  |
  +--> severity == "critical"
  |      |
  |      +--> 1. 立即中止問診場次 (abort_session)
  |      +--> 2. 透過 WebSocket 傳送病患端警告訊息
  |      +--> 3. 透過 FCM 推播通知所有當值醫師
  |      +--> 4. 透過 WebSocket 推送儀表板即時警報
  |      +--> 5. 建立 RedFlagAlert 記錄
  |
  +--> severity == "high"
  |      |
  |      +--> 1. 標記當前對話輪次
  |      +--> 2. 透過 WebSocket 傳送病患端建議訊息
  |      +--> 3. 透過 FCM 推播通知指派醫師
  |      +--> 4. 透過 WebSocket 推送儀表板警報
  |      +--> 5. 建立 RedFlagAlert 記錄
  |      +--> 6. 對話繼續但加入追問
  |
  +--> severity == "medium"
         |
         +--> 1. 標記當前對話輪次
         +--> 2. 建立 RedFlagAlert 記錄
         +--> 3. 對話正常繼續
```

#### API 端點

**GET /api/v1/red-flags/rules**
- 說明: 取得所有紅旗規則
- 權限: `doctor`, `admin`

**POST /api/v1/red-flags/rules**
- 說明: 新增紅旗規則
- 權限: `admin`

**PUT /api/v1/red-flags/rules/{rule_id}**
- 說明: 更新紅旗規則
- 權限: `admin`

**GET /api/v1/alerts**
- 說明: 查詢紅旗警示列表
- 權限: `doctor`, `admin`
- Query Parameters: `session_id`, `severity`, `date_from`, `date_to`, `acknowledged`, `cursor`, `limit`

**PATCH /api/v1/alerts/{alert_id}/acknowledge**
- 說明: 醫師確認紅旗警示
- 權限: `doctor`
- Request Body:
  ```json
  {
    "acknowledge_notes": "已電話聯繫病患，安排急診"
  }
  ```

---

### 1-G. SOAP 報告服務 (SOAP Report Service)

#### 概述

在問診完成後，根據完整對話記錄自動產生結構化 SOAP 報告。報告包含鑑別診斷、建議檢查項目，並支援醫師審閱確認與 PDF 匯出。

#### 資料模型

```
SOAPReport:
  id: UUID (PK)
  session_id: UUID (FK -> Session, unique)
  status: report_status ("generating" | "generated" | "failed")
  review_status: review_status ("pending" | "approved" | "revision_needed")
  subjective: JSONB (主觀資料 — 結構化)
  objective: JSONB (客觀資料 — 結構化)
  assessment: JSONB (評估 — 結構化)
  plan: JSONB (計畫 — 結構化)
  raw_transcript: text (nullable, 完整對話逐字稿)
  summary: text (nullable, 摘要)
  icd10_codes: TEXT[] (nullable, ICD-10 診斷碼)
  ai_confidence_score: numeric(3,2) (nullable, AI 信心分數 0~1)
  reviewed_by: UUID (FK -> User, nullable)
  reviewed_at: datetime (nullable)
  review_notes: text (nullable, 審閱備註)
  generated_at: datetime (nullable)
  created_at: datetime
  updated_at: datetime
```

**SOAP JSONB 結構定義：**

```jsonc
// subjective
{
  "chief_complaint": "血尿持續三天",
  "hpi": {
    "onset": "三天前",
    "location": "排尿時",
    "duration": "持續三天",
    "characteristics": "肉眼可見血尿，無血塊",
    "severity": "中度",
    "aggravating_factors": ["劇烈運動後加重"],
    "relieving_factors": [],
    "associated_symptoms": ["輕微腰痛", "頻尿"],
    "timing": "每次排尿都有",
    "context": "無外傷史"
  },
  "past_medical_history": {
    "conditions": ["高血壓"],
    "surgeries": [],
    "hospitalizations": []
  },
  "medication_history": {
    "current": ["Amlodipine 5mg QD"],
    "past": [],
    "otc": []
  },
  "system_review": {
    "constitutional": "無發燒、體重下降",
    "genitourinary": "頻尿、血尿",
    "gastrointestinal": "正常",
    "musculoskeletal": "輕微腰痛"
  },
  "social_history": {
    "smoking": "無",
    "alcohol": "偶爾",
    "occupation": "辦公室工作"
  }
}

// objective
{
  "vital_signs": {
    "blood_pressure": "135/85 mmHg",
    "heart_rate": 78,
    "respiratory_rate": 18,
    "temperature": 36.8,
    "spo2": 98
  },
  "physical_exam": {
    "general": "病患意識清醒，表情平靜",
    "abdomen": "腹部柔軟，無壓痛",
    "costovertebral_angle": "左側輕度叩擊痛"
  },
  "lab_results": [
    {
      "test_name": "尿液分析",
      "result": "RBC >50/HPF",
      "reference_range": "0-5/HPF",
      "is_abnormal": true,
      "date": "2026-04-10"
    }
  ],
  "imaging_results": []
}

// assessment
{
  "differential_diagnoses": [
    {
      "diagnosis": "泌尿道結石",
      "icd10": "N20.0",
      "probability": "high",
      "reasoning": "血尿合併腰痛，年齡性別符合好發族群"
    },
    {
      "diagnosis": "膀胱腫瘤",
      "icd10": "C67.9",
      "probability": "medium",
      "reasoning": "持續性肉眼血尿，需排除惡性"
    },
    {
      "diagnosis": "泌尿道感染",
      "icd10": "N39.0",
      "probability": "low",
      "reasoning": "無發燒、無排尿灼熱感"
    }
  ],
  "clinical_impression": "持續性肉眼血尿，最可能為泌尿道結石，但需排除膀胱腫瘤"
}

// plan
{
  "recommended_tests": [
    {
      "test_name": "尿液分析 + 尿液細胞學",
      "rationale": "確認血尿嚴重度及排除惡性細胞",
      "urgency": "routine"
    },
    {
      "test_name": "腎功能 (BUN/Cr)",
      "rationale": "評估腎功能是否受影響",
      "urgency": "routine"
    },
    {
      "test_name": "腹部超音波",
      "rationale": "檢查結石、腎水腫或腫塊",
      "urgency": "routine"
    }
  ],
  "treatments": [
    {
      "type": "medication",
      "name": "Tamsulosin 0.4mg QD",
      "instruction": "睡前服用",
      "note": "若為結石，協助排石"
    }
  ],
  "follow_up": {
    "interval": "2 週後",
    "reason": "追蹤檢查結果",
    "additional_notes": "若血尿加重或出現發燒請立即就醫"
  },
  "referrals": [],
  "patient_education": [
    "多喝水，每日 2000ml 以上",
    "避免劇烈運動",
    "觀察尿液顏色變化，若出現血塊請立即就醫"
  ]
}
```

#### SOAP 產生流程

1. 問診場次狀態變更為 `completed` 時觸發
2. 從 PostgreSQL 載入該場次的所有 conversations 記錄 (依 sequence_number 排序)
3. 組裝完整對話記錄文字
4. 使用 Claude API 與 SOAP 專用 prompt 產生報告
5. 解析 LLM 回應，驗證 JSON 結構
6. 建立 SOAPReport 記錄，status 為 `generated`，review_status 為 `pending`
7. 透過 WebSocket 通知醫師報告已就緒

(SOAP Prompt 設計詳見 4-E 節)

#### API 端點

**GET /api/v1/reports/{session_id}**
- 說明: 取得場次的 SOAP 報告
- 權限: `patient` (僅自己的簡化版), `doctor`, `admin`
- 病患僅可見 assessment 中的白話摘要，不含鑑別診斷與技術細節

**PATCH /api/v1/reports/{report_id}/review**
- 說明: 醫師審閱報告
- 權限: `doctor`
- Request Body:
  ```json
  {
    "review_status": "approved",
    "review_notes": "建議加做 PSA 檢查",
    "modifications": {
      "plan": { "...": "amended plan..." }
    }
  }
  ```
- 流程:
  1. 更新 `review_status`
  2. 記錄 `reviewed_by` 與 `reviewed_at`
  3. 保存 `review_notes`
  4. 通知病患報告已審閱

**POST /api/v1/reports/{report_id}/regenerate**
- 說明: 重新產生報告 (若醫師認為品質不佳)
- 權限: `doctor`, `admin`
- 流程:
  1. 重新呼叫 LLM 產生 (可選擇不同 prompt 變體)
  2. 更新報告內容，status 設為 `generating`

**GET /api/v1/reports/{report_id}/export/pdf**
- 說明: 匯出報告為 PDF
- 權限: `doctor`, `admin`
- 回應: PDF 檔案串流 (Content-Type: application/pdf)
- 實作: 使用 WeasyPrint 或 ReportLab 從 HTML 模板產生 PDF

**GET /api/v1/reports**
- 說明: 查詢報告列表
- 權限: `doctor`, `admin`
- Query Parameters: `status`, `review_status`, `date_from`, `date_to`, `patient_id`, `cursor`, `limit`

---

### 1-H. 儀表板服務 (Dashboard Service)

#### 概述

提供醫師端儀表板所需的彙總統計資料、即時佇列狀態與紅旗警報聚合。

#### API 端點

**GET /api/v1/dashboard/today-summary**
- 說明: 今日場次統計摘要
- 權限: `doctor`, `admin`
- Response:
  ```json
  {
    "date": "2026-04-10",
    "total_sessions": 23,
    "completed_sessions": 18,
    "in_progress_sessions": 3,
    "waiting_sessions": 2,
    "aborted_sessions": 0,
    "cancelled_sessions": 0,
    "average_duration_seconds": 482,
    "red_flag_count": {
      "critical": 0,
      "high": 2,
      "medium": 5
    },
    "reports_pending_review": 4,
    "reports_approved": 14
  }
  ```

**GET /api/v1/dashboard/queue**
- 說明: 即時等候佇列
- 權限: `doctor`, `admin`
- Response:
  ```json
  {
    "queue": [
      {
        "session_id": "uuid",
        "patient_name": "王XX",
        "chief_complaint": "頻尿",
        "status": "waiting",
        "waiting_since": "2026-04-10T14:30:00+08:00",
        "wait_duration_minutes": 12
      }
    ],
    "active": [
      {
        "session_id": "uuid",
        "patient_name": "李XX",
        "chief_complaint": "血尿",
        "status": "in_progress",
        "started_at": "2026-04-10T14:20:00+08:00",
        "duration_minutes": 8,
        "has_red_flag": false
      }
    ]
  }
  ```

**GET /api/v1/dashboard/red-flag-alerts**
- 說明: 今日紅旗警報聚合
- 權限: `doctor`, `admin`
- Response:
  ```json
  {
    "alerts": [
      {
        "alert_id": "uuid",
        "session_id": "uuid",
        "patient_name": "陳XX",
        "severity": "high",
        "title": "發燒合併泌尿症狀",
        "description": "發燒合併頻尿，疑似泌尿道感染",
        "detected_at": "2026-04-10T13:45:00+08:00",
        "acknowledged": false
      }
    ],
    "unacknowledged_count": 2
  }
  ```

**GET /api/v1/dashboard/history**
- 說明: 歷史報告查詢
- 權限: `doctor`, `admin`
- Query Parameters: `date_from`, `date_to`, `patient_name`, `complaint`, `has_red_flag`, `review_status`, `cursor`, `limit`

#### 即時更新機制

儀表板資料透過 WebSocket 推送即時更新:

**WS /api/v1/ws/dashboard**

連線方式: `wss://{host}/api/v1/ws/dashboard?token={access_token}`

- 連線驗證: JWT token, role 必須為 `doctor` 或 `admin`
- 推送事件:

| type | payload | 說明 |
|------|---------|------|
| `session_created` | `{session_id, patient_name, chief_complaint, status}` | 新場次建立 |
| `session_status_changed` | `{session_id, status, previous_status, reason}` | 場次狀態變更 |
| `new_red_flag` | `{alert_id, session_id, patient_name, severity, title, description}` | 新紅旗觸發 |
| `red_flag_acknowledged` | `{alert_id, acknowledged_by}` | 紅旗已確認 |
| `report_generated` | `{report_id, session_id, patient_name, status}` | 報告產生完成 |
| `queue_updated` | `{total_waiting, total_in_progress, queue: Array}` | 排隊狀態更新 |
| `stats_updated` | `{sessions_today, completed, red_flags, pending_reviews}` | 統計更新 |

---

### 1-I. 通知服務 (Notification Service)

#### 概述

統一管理所有通知的傳送、儲存與狀態追蹤。支援 WebSocket 即時推送 (應用程式前景) 與 FCM 推播 (應用程式背景/鎖屏)。

#### 資料模型

```
Notification:
  id: UUID (PK)
  user_id: UUID (FK -> User)
  type: notification_type ("red_flag" | "session_complete" | "report_ready" | "system")
  title: str
  body: str
  data: JSONB (附加資料，如 session_id, report_id 等)
  is_read: bool (default false)
  read_at: datetime (nullable)
  created_at: datetime

FCMDevice:
  id: UUID (PK)
  user_id: UUID (FK -> User)
  device_token: str (FCM token)
  platform: device_platform ("ios" | "android" | "web")
  device_name: str (nullable, 裝置名稱)
  is_active: bool
  created_at: datetime
  updated_at: datetime
```

#### 通知類型

| 類型代碼 | 說明 | 對象 | 使用場景 |
|---|---|---|---|
| `red_flag` | 紅旗警報 | 醫師 | 偵測到紅旗症狀時 |
| `session_complete` | 問診完成 | 醫師 | 問診場次正常完成 |
| `report_ready` | 報告就緒 | 醫師 | SOAP 報告產生完成 |
| `system` | 系統通知 | 全部 | 系統公告、超時通知等 |

#### FCM 推播實作

```python
# FCM 訊息格式
{
    "message": {
        "token": "device_fcm_token",
        "notification": {
            "title": "紅旗警報",
            "body": "病患陳XX偵測到危急症狀：大量血尿"
        },
        "data": {
            "type": "red_flag",
            "session_id": "uuid",
            "alert_id": "uuid",
            "click_action": "OPEN_RED_FLAG_DETAIL"
        },
        "android": {
            "priority": "high",
            "notification": {
                "channel_id": "red_flag_alerts",
                "sound": "alert_urgent"
            }
        },
        "apns": {
            "headers": {
                "apns-priority": "10"
            },
            "payload": {
                "aps": {
                    "alert": {
                        "title": "紅旗警報",
                        "body": "病患陳XX偵測到危急症狀：大量血尿"
                    },
                    "sound": "alert_urgent.caf",
                    "badge": 1,
                    "content-available": 1
                }
            }
        }
    }
}
```

#### API 端點

**GET /api/v1/notifications**
- 說明: 取得通知列表
- 權限: 所有角色 (僅自己的)
- Query Parameters: `is_read`, `type`, `cursor`, `limit`

**PATCH /api/v1/notifications/{notification_id}/read**
- 說明: 標記通知為已讀
- 權限: 所有角色 (僅自己的)

**POST /api/v1/notifications/read-all**
- 說明: 全部標記已讀
- 權限: 所有角色

**POST /api/v1/devices/register**
- 說明: 註冊裝置 FCM token
- 權限: 所有角色
- Request Body:
  ```json
  {
    "device_token": "fcm_token_string",
    "platform": "ios",
    "device_name": "iPhone 15 Pro"
  }
  ```

**DELETE /api/v1/devices/{device_id}**
- 說明: 移除裝置
- 權限: 所有角色 (僅自己的)

---

### 1-J. 音訊檔案服務 (Audio File Service)

#### 概述

管理問診過程中產生的音訊檔案。上傳至 S3 相容儲存空間，產生預簽名 URL 供存取，並執行保留政策與自動清理。

#### 資料模型

```
AudioFile:
  id: UUID (PK)
  session_id: UUID (FK -> Session)
  conversation_id: UUID (nullable, 對應的對話記錄)
  file_type: str ("patient_input" | "ai_response")
  s3_bucket: str
  s3_key: str
  file_size_bytes: int
  duration_seconds: float
  mime_type: str (e.g., "audio/webm", "audio/mp3")
  sample_rate: int
  is_deleted: bool (default false)
  deleted_at: datetime (nullable)
  retention_expires_at: datetime
  created_at: datetime
```

#### S3 儲存結構

```
bucket: gu-voice-assistant-audio
  /sessions/{session_id}/
    /patient/{sequence_number}_{timestamp}.webm
    /assistant/{sequence_number}_{timestamp}.mp3
```

#### 保留政策

| 檔案類型 | 保留天數 | 說明 |
|---|---|---|
| 一般場次音訊 | 90 天 | 正常完成的問診場次 |
| 紅旗場次音訊 | 365 天 | 包含紅旗事件的場次 |
| 中止場次音訊 | 365 天 | 因紅旗中止的場次 |

#### API 端點

**POST /api/v1/audio/upload**
- 說明: 上傳音訊檔案
- 權限: `patient` (僅問診中), `system`
- Content-Type: multipart/form-data
- 流程:
  1. 驗證檔案格式與大小 (上限 50MB)
  2. 產生 S3 key
  3. 上傳至 S3
  4. 建立 AudioFile 記錄
  5. 計算 `retention_expires_at`
- Response: `201 Created` 含 file_id

**GET /api/v1/audio/{file_id}/url**
- 說明: 取得預簽名下載 URL
- 權限: `doctor`, `admin`
- Response:
  ```json
  {
    "url": "https://s3.../presigned_url",
    "expires_in": 3600
  }
  ```
- 預簽名 URL 有效期: 1 小時

**DELETE /api/v1/audio/{file_id}**
- 說明: 手動刪除音訊檔案
- 權限: `admin`
- 流程: 軟刪除 (設 `is_deleted=true`)，S3 物件由排程清理

---

### 1-K. 稽核日誌服務 (Audit Log Service)

#### 概述

記錄所有關鍵操作與資料存取行為，符合醫療資訊安全規範要求。

#### 資料模型

```
AuditLog:
  id: BIGINT GENERATED ALWAYS AS IDENTITY (PK, 自增)
  user_id: UUID (FK -> User, nullable -- 系統操作時為 null)
  action: audit_action (操作類型 enum)
  resource_type: str (資源類型)
  resource_id: str (資源 ID)
  details: JSONB (操作詳情)
  ip_address: inet
  user_agent: str
  created_at: datetime (索引)
```

**分區策略：** 按月 Range Partition（以 `created_at` 為分區鍵）。
**權限：** 僅 INSERT，禁止 UPDATE / DELETE。

#### 稽核操作類型 (audit_action enum)

| action | 說明 |
|---|---|
| `create` | 建立資源 |
| `read` | 讀取資源 |
| `update` | 更新資源 |
| `delete` | 刪除資源 |
| `login` | 使用者登入 |
| `logout` | 使用者登出 |
| `export` | 匯出資料 |
| `review` | 審閱報告 |
| `acknowledge` | 確認紅旗 |
| `session_start` | 開始問診 |
| `session_end` | 結束問診 |

#### Middleware 實作

使用 FastAPI middleware 自動記錄需要稽核的操作:

```python
class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 根據 route 判斷是否需要記錄
        if self._should_log(request.url.path):
            await self._create_log(
                user_id=request.state.current_user.id if hasattr(request.state, 'current_user') else None,
                action=self._resolve_action(request.method, request.url.path),
                resource_type=self._resolve_resource_type(request.url.path),
                resource_id=self._extract_resource_id(request.url.path),
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent"),
            )
        return response
```

#### API 端點

**GET /api/v1/audit-logs**
- 說明: 查詢稽核日誌
- 權限: `admin`
- Query Parameters:
  - `user_id`: 依使用者篩選
  - `action`: 依操作類型篩選
  - `resource_type`: 依資源類型篩選
  - `date_from`, `date_to`: 日期範圍
  - `cursor`, `limit`: 游標分頁
- Response: 分頁的稽核日誌列表

**GET /api/v1/audit-logs/export**
- 說明: 匯出稽核日誌 (CSV)
- 權限: `admin`
- Query Parameters: 同上
- Response: CSV 檔案串流

---

### 1-L. 管理員服務 (Admin Service)

#### 概述

提供管理員專用的使用者管理、紅旗規則管理與系統健康監控 API。

#### API 端點

**GET /api/v1/admin/users**
- 說明: 查詢所有使用者列表
- 權限: `admin`
- Query Parameters: `role`, `is_active`, `cursor`, `limit`

**POST /api/v1/admin/users**
- 說明: 管理員建立使用者
- 權限: `admin`

**PATCH /api/v1/admin/users/{user_id}**
- 說明: 更新使用者資訊 (含停用/啟用)
- 權限: `admin`

**GET /api/v1/admin/red-flag-rules**
- 說明: 管理紅旗規則
- 權限: `admin`

**POST /api/v1/admin/red-flag-rules**
- 說明: 新增紅旗規則
- 權限: `admin`

**PUT /api/v1/admin/red-flag-rules/{rule_id}**
- 說明: 更新紅旗規則
- 權限: `admin`

**DELETE /api/v1/admin/red-flag-rules/{rule_id}**
- 說明: 停用紅旗規則
- 權限: `admin`

**GET /api/v1/admin/system-health**
- 說明: 系統健康檢查
- 權限: `admin`
- Response:
  ```json
  {
    "status": "healthy",
    "database": "connected",
    "redis": "connected",
    "s3": "connected",
    "claude_api": "reachable",
    "google_stt": "reachable",
    "google_tts": "reachable",
    "uptime_seconds": 86400,
    "active_ws_connections": 12
  }
  ```

---

## 2. 目錄結構 (Project Structure)

```
app/
  __init__.py
  main.py                       # FastAPI 入口
  core/
    __init__.py
    config.py                   # pydantic-settings 配置
    security.py                 # JWT（RS256）、密碼雜湊
    dependencies.py             # 共用依賴注入
    middleware.py               # CORS、audit logging、error handling
    exceptions.py               # 自定義例外類別
  models/
    __init__.py
    user.py                     # User SQLAlchemy model
    patient.py                  # Patient model
    session.py                  # Session model
    conversation.py             # Conversation model（單層扁平）
    chief_complaint.py          # ChiefComplaint model
    soap_report.py              # SOAPReport model
    red_flag_alert.py           # RedFlagAlert model
    red_flag_rule.py            # RedFlagRule model
    notification.py             # Notification model
    audit_log.py                # AuditLog model
    fcm_device.py               # FCMDevice model
  schemas/
    __init__.py
    common.py                   # 分頁（cursor-based）、錯誤回應等共用 schema
    auth.py                     # 登入、註冊 request/response
    patient.py                  # Patient schemas
    session.py                  # Session schemas
    conversation.py             # Conversation schemas
    complaint.py                # ChiefComplaint schemas
    report.py                   # SOAPReport schemas
    alert.py                    # RedFlagAlert schemas
    dashboard.py                # Dashboard schemas
    notification.py             # Notification schemas
    admin.py                    # Admin schemas
  routers/
    __init__.py
    auth.py                     # /api/v1/auth/*
    patients.py                 # /api/v1/patients/*
    sessions.py                 # /api/v1/sessions/*
    complaints.py               # /api/v1/complaints/*
    reports.py                  # /api/v1/reports/*
    alerts.py                   # /api/v1/alerts/*
    dashboard.py                # /api/v1/dashboard/*
    notifications.py            # /api/v1/notifications/*
    admin.py                    # /api/v1/admin/*
    audit_logs.py               # /api/v1/audit-logs/*
  services/
    __init__.py
    auth_service.py
    patient_service.py
    session_service.py
    conversation_service.py
    complaint_service.py
    report_service.py
    alert_service.py
    dashboard_service.py
    notification_service.py
    audio_service.py
    audit_service.py
  pipelines/
    __init__.py
    stt_pipeline.py             # Google Cloud STT 串流
    llm_conversation.py         # Claude 對話引擎
    tts_pipeline.py             # Google Cloud TTS
    red_flag_detector.py        # 規則層 + 語意層並行偵測
    soap_generator.py           # SOAP 報告 LLM 生成
  websocket/
    __init__.py
    connection_manager.py       # WebSocket 連線管理
    conversation_handler.py     # 語音對話 WS 處理器
    dashboard_handler.py        # 儀表板 WS 處理器
  cache/
    __init__.py
    redis_client.py             # Redis 連線
    context_manager.py          # 對話上下文快取
  tasks/
    __init__.py
    audio_cleanup.py            # 音訊檔案清理排程
    session_timeout.py          # 場次超時處理
    report_queue.py             # 報告產生佇列
    notification_retry.py       # 通知重試佇列
    partition_manager.py        # 資料表分區管理
  utils/
    __init__.py
    datetime_utils.py
    audio_utils.py
    pdf_generator.py
tests/
  unit/
  integration/
  e2e/
alembic/
  versions/
  env.py
  alembic.ini
scripts/
  seed_data.py                  # 種子資料
  create_admin.py               # 建立管理員帳號
```

### 各模組詳細說明

#### app/main.py
應用程式進入點。建立 FastAPI 實例，註冊所有 router，掛載 middleware (CORS, Audit Log, Error Handler)，設定 lifespan event handlers (啟動時初始化 DB pool, Redis 連線, 排程器; 關閉時清理資源)。

```python
# 主要責任:
# 1. 建立 FastAPI app instance (含 title, version, docs_url 等)
# 2. 設定 CORS middleware (允許的 origins, methods, headers)
# 3. 掛載 AuditLogMiddleware
# 4. 掛載 GlobalExceptionHandler
# 5. 註冊所有 API routers (prefix: /api/v1)
# 6. 註冊 WebSocket routers
# 7. lifespan: startup (DB pool, Redis, scheduler, rule engine warm-up)
# 8. lifespan: shutdown (close DB pool, Redis, scheduler)
# 9. Health check endpoint: GET /health
```

#### app/core/config.py
使用 pydantic-settings 管理所有環境變數。定義 `Settings` class，從 `.env` 檔案或環境變數載入設定。包含 DB, Redis, JWT (RS256 公私鑰路徑), S3, Google Cloud, Claude API, FCM 等所有外部服務的連線設定。詳見第 7 節。

#### app/core/security.py
JWT 權杖的建立、解碼、驗證邏輯 (使用 RS256 非對稱加密)。包含:
- `create_access_token(user_id, role)`: 使用私鑰產生 access token
- `create_refresh_token(user_id)`: 使用私鑰產生 refresh token
- `decode_token(token)`: 使用公鑰解碼並驗證 token
- `hash_password(raw)`: 使用 bcrypt 雜湊密碼
- `verify_password(raw, hashed)`: 驗證密碼

#### app/core/dependencies.py
FastAPI Dependency Injection 定義:
- `get_db()`: 取得 SQLAlchemy AsyncSession (from connection pool)
- `get_redis()`: 取得 Redis 連線
- `get_current_user()`: 從 JWT token 解析當前使用者
- `require_role(roles: list[str])`: 角色權限驗證 dependency
- `get_s3_client()`: 取得 S3 client
- `get_conversation_context()`: 取得對話上下文管理器

#### app/core/middleware.py
自訂 middleware:
- `AuditLogMiddleware`: 自動記錄所有 API 請求至稽核日誌
- `RequestIDMiddleware`: 為每個請求產生唯一 request_id (用於日誌追蹤)
- `RateLimitMiddleware`: 速率限制 (基於 Redis, 滑動視窗演算法)

#### app/core/exceptions.py
定義所有領域特定例外 class 與全域例外處理器。詳見第 6 節。

---

#### app/models/user.py
使用者模型，包含 `User` table 定義:
- 欄位: id, email, password_hash, name, role, phone, department, license_number, is_active, last_login_at
- 關聯: sessions, notifications, fcm_devices, audit_logs
- 索引: email (unique), role
- 約束: 當 `role = 'doctor'` 時，`license_number` 不得為 NULL

#### app/models/patient.py
病患模型，包含 `Patient` table 定義:
- 欄位: id, user_id, medical_record_number, name, gender, date_of_birth, phone, emergency_contact, medical_history, allergies, current_medications
- 關聯: user, sessions
- 索引: user_id, medical_record_number (unique)

#### app/models/session.py
問診場次模型:
- `Session` table: 場次主表
- 欄位: id, patient_id (FK -> patients), doctor_id (FK -> users, nullable), chief_complaint_id, chief_complaint_text, status, red_flag, red_flag_reason, language, started_at, completed_at, duration_seconds
- 關聯: patient (Patient), doctor (User), chief_complaint, conversations, report, red_flag_alerts, audio_files
- 索引: patient_id, doctor_id, status, created_at

#### app/models/conversation.py
對話模型 (單層扁平結構):
- `Conversation` table: 直接儲存每輪對話
- 欄位: id, session_id, sequence_number, role, content_text, audio_url, audio_duration_seconds, stt_confidence, red_flag_detected, metadata, created_at
- 關聯: session
- 索引: session_id + sequence_number (unique)
- 分區: 按月 Range Partition

#### app/models/chief_complaint.py
主訴模型:
- `ChiefComplaint` table
- 欄位: id, name, name_en, description, category, is_default, created_by, display_order, is_active
- 關聯: created_by (User)
- 索引: category, is_default, is_active

#### app/models/red_flag_alert.py
紅旗警示模型:
- `RedFlagAlert` table: 紅旗警示記錄
- 關聯: session, matched_rule, acknowledged_by (User)
- 注意: conversation_id 不設外鍵 (分區表限制)
- 索引: session_id, severity, created_at

#### app/models/red_flag_rule.py
紅旗規則模型:
- `RedFlagRule` table: 紅旗規則定義
- 欄位: id, name, description, category, keywords (TEXT[]), regex_pattern, severity, suspected_diagnosis, suggested_action, is_active, created_by
- 索引: severity, is_active

#### app/models/soap_report.py
SOAP 報告模型:
- `SOAPReport` table
- 欄位: S/O/A/P 為 JSONB，含 status (report_status), review_status (review_status), ai_confidence_score, icd10_codes, raw_transcript, summary
- 關聯: session, reviewed_by (User)
- 索引: session_id (unique), status, review_status

#### app/models/notification.py
通知模型:
- `Notification` table
- 欄位: type 使用 notification_type enum (red_flag, session_complete, report_ready, system)
- 關聯: user
- 索引: user_id + is_read, created_at

#### app/models/fcm_device.py
推播裝置模型:
- `FCMDevice` table
- 欄位: id, user_id, device_token, platform (device_platform enum: ios/android/web), device_name, is_active
- 關聯: user
- 索引: user_id, device_token (unique where active)

#### app/models/audit_log.py
稽核日誌模型:
- `AuditLog` table
- 主鍵: BIGINT 自增 (非 UUID)
- 欄位: action 使用 audit_action enum (11 種)
- 索引: user_id, action, resource_type, created_at
- 分區策略: 依 `created_at` 月份分區 (PostgreSQL table partitioning)

---

#### app/schemas/ (Pydantic Schemas)

每個 schema 模組包含以下模式:
- `{Entity}Create`: 建立請求的 request body
- `{Entity}Update`: 更新請求的 request body
- `{Entity}Response`: 回應格式
- `{Entity}ListResponse`: 列表回應 (含游標分頁)
- `{Entity}InDB`: 內部使用 (含 DB 欄位)

**app/schemas/common.py:**
- `CursorPaginationParams`: 游標分頁參數 (cursor, limit)
- `PaginatedResponse[T]`: 泛型游標分頁回應 (含 next_cursor, has_more, limit, total_count)
- `ErrorResponse`: 統一錯誤回應格式
- `SuccessResponse`: 統一成功回應格式

**app/schemas/websocket.py:**
- `WSMessage`: WebSocket 訊息基礎 schema (type, id, timestamp, payload)
- `WSAudioChunk`: 音訊片段訊息
- `WSTranscription`: 轉譯結果訊息
- `WSAIResponse`: AI 回應訊息
- `WSRedFlagAlert`: 紅旗警報訊息
- `WSControl`: 控制訊息

---

#### app/routers/

每個 router 模組:
- 定義 `APIRouter` instance (含 prefix, tags)
- 使用 `Depends` 注入 service, db session, current_user
- 處理 HTTP request/response 轉換
- 不包含業務邏輯 (委派給 service 層)

---

#### app/services/

每個 service 模組:
- 封裝業務邏輯
- 接收 DB session, Redis client 等依賴
- 回傳領域物件或 Pydantic schema
- 處理交易管理 (transaction scope)

---

#### app/pipelines/

**app/pipelines/stt_pipeline.py:**
Google Cloud STT 串流語音辨識管線。詳見 4-A 節。

**app/pipelines/tts_pipeline.py:**
Google Cloud TTS 語音合成管線。詳見 4-C 節。

**app/pipelines/llm_conversation.py:**
Claude API 對話引擎管線。詳見 4-B 節。

**app/pipelines/red_flag_detector.py:**
雙層紅旗偵測管線 (規則引擎 + LLM 語意分析)。詳見 4-D 節。

**app/pipelines/soap_generator.py:**
SOAP 報告產生管線。詳見 4-E 節。

---

#### app/websocket/connection_manager.py
WebSocket 連線管理器:
- 維護所有活躍連線的字典 (session_id -> WebSocket)
- 維護儀表板連線列表 (所有醫師/管理員)
- `connect(websocket, session_id, user_id)`: 註冊連線
- `disconnect(session_id)`: 移除連線
- `send_to_session(session_id, message)`: 傳送至特定場次
- `broadcast_to_dashboard(message)`: 廣播至所有儀表板
- 心跳機制 (ping/pong, 30 秒間隔)

#### app/websocket/conversation_handler.py
對話 WebSocket 訊息處理器:
- `handle_audio_chunk(ws, data)`: 接收音訊片段，緩衝至 buffer
- `handle_audio_end(ws)`: 音訊結束，觸發管線處理
- `handle_text_input(ws, content)`: 文字輸入，跳過 STT 直接進 LLM
- `handle_control(ws, action)`: 控制指令 (結束場次等)

#### app/websocket/dashboard_handler.py
儀表板 WebSocket 訊息處理器:
- 管理醫師端儀表板的即時連線
- 推送佇列更新、紅旗警報、報告通知

---

#### app/cache/context_manager.py
對話上下文 Redis 管理:
- `load_context(session_id)`: 從 Redis 載入上下文 (`gu:session:{id}:context`)
- `save_context(session_id, context)`: 儲存上下文至 Redis
- `add_turn(session_id, role, content)`: 新增一輪對話
- `get_recent_turns(session_id, n)`: 取得最近 n 輪對話
- `clear_context(session_id)`: 清除上下文
- `set_ttl(session_id, seconds)`: 設定過期時間

---

#### app/tasks/partition_manager.py
資料表分區管理:
- 自動建立新月份分區 (conversations, audit_logs)
- 定期執行 (每月 25 日建立下月分區)

#### app/tasks/scheduler.py
使用 APScheduler 設定所有排程任務:
- 音訊清理: 每日凌晨 3:00 執行
- 場次超時: 每 5 分鐘檢查
- 通知重試: 每 2 分鐘執行
- Redis context 清理: 每小時執行
- 分區管理: 每月 25 日

---

#### app/utils/

**app/utils/audio_utils.py:**
- `convert_audio_format(data, from_format, to_format)`: 音訊格式轉換 (使用 pydub / ffmpeg)
- `get_audio_duration(file_path)`: 取得音訊長度
- `validate_audio_file(data, max_size)`: 驗證音訊檔案

**app/utils/datetime_utils.py:**
- 時間工具函數

**app/utils/pdf_generator.py:**
- `generate_soap_pdf(report: SOAPReport)`: 從 SOAP 報告產生 PDF
- 使用 Jinja2 模板引擎產生 HTML，再用 WeasyPrint 轉換為 PDF

---

#### tests/conftest.py
測試共用 fixtures:
- `test_app`: FastAPI TestClient
- `test_db`: 測試用 PostgreSQL (使用 Docker 或 SQLite in-memory)
- `test_redis`: 測試用 Redis (fakeredis)
- `auth_headers_patient`: 病患角色 JWT header
- `auth_headers_doctor`: 醫師角色 JWT header
- `auth_headers_admin`: 管理員角色 JWT header
- `mock_claude_api`: Claude API mock
- `mock_google_stt`: Google STT mock
- `mock_google_tts`: Google TTS mock

---

## 3. 業務邏輯流程 (Business Logic Flows)

### 3-A. 完整對話流程 (Audio In -> STT -> LLM -> TTS -> Audio Out + Red Flag Check)

```
病患 (Client)                    後端 (Server)                    外部服務
    |                                |                                |
    |-- [WS] 建立連線 ------------->|                                |
    |   (token=JWT)                  |                                |
    |                                |-- 驗證 JWT (RS256 公鑰)        |
    |                                |-- 驗證 Session 狀態             |
    |                                |-- 載入/初始化 Redis Context     |
    |                                |   (gu:session:{id}:context)    |
    |                                |                                |
    |<-- [WS] 歡迎訊息 -------------|                                |
    |   {type: "ai_response_text",   |                                |
    |    content: "您好，我是泌尿科  |                                |
    |    AI 問診助手..."}            |                                |
    |                                |                                |
    |<-- [WS] AI 語音 --------------|-- [TTS] 合成歡迎語音 --------->|
    |   {type: "ai_response_audio",  |<-- 語音資料 ------------------|
    |    data: base64}               |                                |
    |                                |                                |
    |== 問診對話迴圈開始 ============================================|
    |                                |                                |
    |-- [WS] 音訊片段 1 ----------->|                                |
    |   {type: "audio_chunk",        |-- 暫存至 audio buffer          |
    |    data: base64, seq: 1}       |                                |
    |                                |                                |
    |-- [WS] 音訊片段 2 ----------->|                                |
    |   {type: "audio_chunk",        |-- 暫存至 audio buffer          |
    |    data: base64, seq: 2}       |                                |
    |                                |                                |
    |-- [WS] ... (更多片段)          |                                |
    |                                |                                |
    |-- [WS] 音訊結束 ------------->|                                |
    |   {type: "audio_end"}          |                                |
    |                                |                                |
    |                                |== STT Pipeline ================|
    |                                |-- 組裝完整音訊                  |
    |                                |-- [STT] 串流辨識 ------------>|
    |                                |<-- 即時部分結果 ---------------|
    |<-- [WS] 即時轉譯 -------------|                                |
    |   {type: "stt_partial",        |                                |
    |    text: "我最近...",           |                                |
    |    is_final: false}            |                                |
    |                                |<-- 最終辨識結果 ---------------|
    |<-- [WS] 最終轉譯 -------------|                                |
    |   {type: "stt_final",          |                                |
    |    text: "我最近頻尿...",       |                                |
    |    is_final: true,             |                                |
    |    confidence: 0.95}           |                                |
    |                                |                                |
    |                                |== 並行處理 ====================|
    |                                |                                |
    |                                |--+-- [LLM] 對話引擎 -------->|
    |                                |  |   (送出對話上下文 +         |
    |                                |  |    病患最新發言)            |
    |                                |  |                             |
    |                                |  +-- [Red Flag] 偵測 -------->|
    |                                |      |                         |
    |                                |      +-- 規則引擎比對          |
    |                                |      +-- LLM 語意分析 ------->|
    |                                |                                |
    |                                |<-- LLM 回應 ------------------|
    |                                |<-- 紅旗偵測結果 ---------------|
    |                                |                                |
    |                                |-- 判斷紅旗結果                  |
    |                                |   |                            |
    |                                |   +-- 若 critical:             |
    |                                |   |   中止場次，發送警報       |
    |                                |   |   (跳至中止流程)           |
    |                                |   |                            |
    |                                |   +-- 若 high/medium:          |
    |                                |   |   記錄事件，通知醫師       |
    |                                |   |   對話繼續                 |
    |                                |   |                            |
    |                                |   +-- 若 none:                 |
    |                                |       正常繼續                 |
    |                                |                                |
    |<-- [WS] AI 文字回應 ----------|                                |
    |   {type: "ai_response_chunk",  |                                |
    |    text: "了解，請問...",       |                                |
    |    chunk_index: 1}             |                                |
    |                                |                                |
    |                                |== TTS Pipeline ================|
    |                                |-- [TTS] 合成語音 ------------>|
    |                                |<-- 語音資料 (chunked) --------|
    |                                |                                |
    |<-- [WS] AI 語音片段 1 --------|                                |
    |   {type: "ai_response_audio",  |                                |
    |    data: base64, seq: 1,       |                                |
    |    is_final: false}            |                                |
    |                                |                                |
    |<-- [WS] AI 語音片段 N --------|                                |
    |   {type: "ai_response_audio",  |                                |
    |    data: base64, seq: N,       |                                |
    |    is_final: true}             |                                |
    |                                |                                |
    |                                |-- 儲存對話記錄 (conversations) |
    |                                |-- 更新 Redis Context           |
    |                                |-- 上傳音訊至 S3 (背景)        |
    |                                |                                |
    |== 問診對話迴圈結束 (重複上方流程) ==============================|
    |                                |                                |
    |-- [WS] 結束問診 ------------->|                                |
    |   {type: "control",            |                                |
    |    action: "end_session"}      |                                |
    |                                |                                |
    |                                |-- 更新 Session 狀態 completed  |
    |                                |-- 觸發 SOAP 報告產生 (背景)    |
    |                                |-- 清除 Redis Context           |
    |                                |-- 更新佇列                     |
    |                                |                                |
    |<-- [WS] 場次結束 -------------|                                |
    |   {type: "session_status",     |                                |
    |    status: "completed"}        |                                |
    |                                |                                |
    |-- [WS] 關閉連線 ------------->|                                |
```

### 3-B. 紅旗偵測與升級流程

```
對話輪次文字輸入
  |
  v
+================================+
| 雙層並行偵測                    |
|                                |
|  +----------+  +------------+  |
|  | 規則引擎 |  | LLM 語意   |  |
|  | (同步)   |  | 分析(非同步)|  |
|  +----+-----+  +-----+------+  |
|       |              |          |
|       v              v          |
|  +----------+  +------------+  |
|  | keywords |  | Claude API |  |
|  | + regex  |  | 紅旗 prompt|  |
|  | 比對     |  | 語意判斷   |  |
|  +----+-----+  +-----+------+  |
|       |              |          |
+=======#==============#==========+
        |              |
        v              v
  +---------------------------+
  | 結果合併 (取較高嚴重度)   |
  +-------------+-------------+
                |
                v
        +-------+--------+
        | severity 判斷   |
        +--+---------+---+
           |         |        \
           v         v         v
     [critical]   [high]    [medium/none]
           |         |         |
           v         v         v
   +-------+--+ +---+------+ +--+------+
   | 1.中止    | | 1.標記   | | 1.標記  |
   |   場次    | |   輪次   | |   輪次  |
   | 2.斷開    | | 2.建立   | | 2.建立  |
   |   WS      | |   警示   | |   警示  |
   | 3.建立    | | 3.FCM    | | 3.對話  |
   |   警示    | |   推播   | |   正常  |
   | 4.FCM     | |   醫師   | |   繼續  |
   |   推播    | | 4.WS推送 | +--------+
   |   全醫師  | |   儀表板 |
   | 5.WS推送  | | 5.對話   |
   |   儀表板  | |   加入   |
   | 6.WS推送  | |   追問   |
   |   病患    | +----------+
   |   警告    |
   +----------+
```

### 3-C. SOAP 報告產生流程

```
觸發條件: Session 狀態 -> completed
  |
  v
[1] 建立 SOAPReport 記錄 (status: "generating", review_status: "pending")
  |
  v
[2] 載入完整對話記錄
  |-- 從 DB 取得所有 conversations 記錄 (依 sequence_number 排序)
  |-- 組裝對話文字記錄 (含角色標記)
  |
  v
[3] 載入場次元資料
  |-- 病患基本資料 (年齡、性別)
  |-- 選擇的主訴
  |-- 紅旗警示 (若有)
  |
  v
[4] 組裝 SOAP Prompt
  |-- System prompt (SOAP 格式規範)
  |-- 對話記錄 (user message)
  |-- 元資料上下文
  |
  v
[5] 呼叫 Claude API
  |-- model: claude-sonnet-4-20250514 (或指定版本)
  |-- max_tokens: 4096
  |-- temperature: 0.3 (低溫度以確保一致性)
  |
  v
[6] 解析 LLM 回應
  |-- 解析 JSON 結構
  |-- 驗證 JSONB 結構 (S, O, A, P)
  |-- 驗證鑑別診斷格式 (在 assessment JSONB 內)
  |-- 驗證建議檢查格式 (在 plan JSONB 內)
  |
  +-- 解析失敗?
  |     |
  |     v
  |   [6a] 重試 (最多 3 次)
  |     |-- 調整 prompt (加入格式修正提示)
  |     |-- 重新呼叫 Claude API
  |     |-- 若仍失敗: 記錄錯誤，status 設為 "failed"
  |
  v
[7] 儲存報告
  |-- 更新 SOAPReport 各 JSONB 欄位
  |-- 儲存 raw_transcript
  |-- 更新 status 為 "generated"
  |
  v
[8] 通知醫師
  |-- WebSocket 推送 (若醫師在線)
  |-- FCM 推播 (背景通知)
  |
  v
[9] 等待醫師審閱
  |
  +-- 醫師核准
  |     |-- 更新 review_status 為 "approved"
  |     |-- 記錄審閱資訊
  |     |-- 通知病患
  |
  +-- 醫師要求修改
        |-- 更新 review_status 為 "revision_needed"
        |-- 可選擇重新產生
```

### 3-D. 場次生命週期管理

```
[病患操作]                    [系統狀態]                 [醫師操作]
    |                            |                          |
    v                            |                          |
  選擇主訴                       |                          |
    |                            |                          |
    v                            |                          |
  建立場次 ----------------> [waiting]                      |
    |                            |                          |
    |                            |-- 加入等候佇列            |
    |                            |   (gu:queue:patients)    |
    |                            |-- 推送佇列更新 -------->  |
    |                            |                          |
    v                            |                          |
  開始問診 ----------------> [in_progress]                  |
    |                            |                          |
    |                            |-- 初始化對話上下文        |
    |                            |-- 建立 WS 連線           |
    |                            |                          |
    v                            |                          |
  進行對話                       |                          |
    |                            |                          |
    +-- 正常完成 ----------> [completed]                    |
    |                            |                          |
    |                            |-- 觸發 SOAP 產生         |
    |                            |-- 清除 Redis 上下文      |
    |                            |-- 從佇列移除             |
    |                            |-- 推送通知 ----------->  |
    |                            |                          |
    +-- 紅旗中止 (系統) ---> [aborted_red_flag]             |
    |                            |                          |
    |                            |-- 紅旗警報 ----------->  |
    |                            |-- 強制斷開 WS             |
    |                            |-- 從佇列移除             |
    |                            |                          |
    +-- 主動取消 ----------> [cancelled]                    |
                                 |                          |
                                 |-- 從佇列移除             |
                                 |                          |
                                 |                          v
                                 |                     指派場次
                                 |                     (doctor_id)
                                 |                          |
                                 |                          v
                                 |                     檢閱報告
                                 |                     審閱/修改
                                 |                          |
                                 |                          v
                                 |                     匯出 PDF

[超時機制]
  |-- 場次在 [waiting] 狀態超過 30 分鐘 -> 自動設為 [cancelled]
  |-- 場次在 [in_progress] 狀態超過 60 分鐘 -> 發送提醒通知
  |-- 場次在 [in_progress] 狀態超過 120 分鐘 -> 自動設為 [completed]
  |-- WS 連線斷開超過 5 分鐘未重連 -> 自動設為 [completed]
```

### 3-E. 病患等候佇列管理

```
[佇列操作流程]

1. 新場次加入:
   病患建立場次
     |
     v
   ZADD gu:queue:patients {timestamp} {session_id}
     |
     v
   廣播佇列更新至儀表板 (WS)
     |
     v
   回傳預估等待時間給病患

2. 場次開始/完成/取消:
   狀態變更觸發
     |
     v
   ZREM gu:queue:patients {session_id}
     |
     v
   重新計算所有等待中病患的預估等待時間
     |
     v
   廣播佇列更新至儀表板 (WS)
     |
     v
   推送更新至等待中的病患 (WS)

3. 預估等待時間計算:
   estimated_wait = queue_position * average_session_duration
     |
     v
   average_session_duration = 過去 7 天已完成場次的平均時長
     |
     v
   快取於 Redis (TTL=10min)
```

---

## 4. AI Pipeline 詳細設計

### 4-A. STT Pipeline (語音辨識管線)

#### 串流設定 (Google Cloud Speech-to-Text v2)

```python
# STT 串流辨識設定
stt_config = {
    "config": {
        "auto_decoding_config": {},
        "language_codes": ["zh-TW"],
        "model": "long",  # 或 "latest_long" -- 適合長時間對話
        "features": {
            "enable_automatic_punctuation": True,
            "enable_word_time_offsets": True,
            "enable_word_confidence": True,
        },
        "adaptation": {
            "phrase_sets": [
                {
                    "phrases": [
                        # 泌尿科專有名詞 boost
                        {"value": "頻尿", "boost": 15.0},
                        {"value": "急尿", "boost": 15.0},
                        {"value": "夜尿", "boost": 15.0},
                        {"value": "血尿", "boost": 20.0},
                        {"value": "排尿困難", "boost": 15.0},
                        {"value": "尿失禁", "boost": 15.0},
                        {"value": "尿滯留", "boost": 15.0},
                        {"value": "攝護腺", "boost": 18.0},
                        {"value": "攝護腺肥大", "boost": 18.0},
                        {"value": "膀胱", "boost": 15.0},
                        {"value": "膀胱炎", "boost": 15.0},
                        {"value": "腎結石", "boost": 18.0},
                        {"value": "輸尿管", "boost": 15.0},
                        {"value": "尿道", "boost": 15.0},
                        {"value": "尿道炎", "boost": 15.0},
                        {"value": "泌尿道感染", "boost": 18.0},
                        {"value": "PSA", "boost": 20.0},
                        {"value": "睪丸", "boost": 15.0},
                        {"value": "包皮", "boost": 12.0},
                        {"value": "會陰", "boost": 12.0},
                        {"value": "腰痛", "boost": 10.0},
                        {"value": "下腹痛", "boost": 10.0},
                        {"value": "腎臟", "boost": 12.0},
                        {"value": "解尿", "boost": 12.0},
                        {"value": "殘尿", "boost": 12.0},
                        {"value": "尿流速", "boost": 12.0},
                        {"value": "勃起功能障礙", "boost": 15.0},
                        {"value": "性功能障礙", "boost": 15.0},
                        # 常用藥物名稱
                        {"value": "坦姆適", "boost": 15.0},
                        {"value": "Tamsulosin", "boost": 12.0},
                        {"value": "波斯卡", "boost": 15.0},
                        {"value": "Finasteride", "boost": 12.0},
                        {"value": "適尿通", "boost": 15.0},
                        {"value": "Dutasteride", "boost": 12.0},
                    ]
                }
            ]
        }
    },
    "streaming_config": {
        "streaming_features": {
            "interim_results": True,  # 回傳中間結果
        }
    }
}
```

#### 音訊處理流程

```
1. 接收 WebSocket audio_chunk (base64 encoded)
   |
   v
2. Base64 解碼
   |
   v
3. 格式驗證
   |-- 檢查 sample_rate (期望 16000 Hz)
   |-- 檢查 encoding (期望 LINEAR16 或 OGG_OPUS)
   |-- 若格式不符: 使用 pydub/ffmpeg 轉換
   |
   v
4. 累積至 buffer (每 100ms 或 3200 bytes 為一個 chunk)
   |
   v
5. 收到 audio_end 後:
   |
   v
6. 建立 Google STT StreamingRecognize 串流
   |-- 傳送 streaming_config (首個 request)
   |-- 逐 chunk 傳送音訊資料
   |
   v
7. 接收辨識結果 (串流回傳)
   |
   +-- interim result (is_final=false):
   |     傳送即時轉譯至 WebSocket client
   |
   +-- final result (is_final=true):
         |
         v
8. 取得最終轉譯文字與 confidence score
   |
   v
9. 後處理:
   |-- 醫學術語校正 (常見錯誤修正字典)
   |-- 移除語氣詞 (選擇性)
   |-- 正規化數字表達
   |
   v
10. 回傳處理後的文字與原始音訊資料
```

#### 醫學術語校正字典 (post-processing)

```python
MEDICAL_TERM_CORRECTIONS = {
    "品尿": "頻尿",
    "血尿素": "血尿",  # 僅在非特定上下文
    "社會線": "攝護腺",
    "社護腺": "攝護腺",
    "膀胱演": "膀胱炎",
    "尿到感染": "尿道感染",
    "碎石機": "腎結石",  # 上下文判斷
    "高完": "睪丸",
    # ... 更多常見 STT 錯誤修正
}
```

### 4-B. LLM 對話引擎 (Claude API Conversation Pipeline)

#### System Prompt 模板

```
你是一位經驗豐富的泌尿科 AI 問診助手。你的任務是透過對話收集病患的病史
資訊，以協助醫師進行初步評估。

## 角色與行為規範

1. 你是問診助手，不是醫師。不可以做出診斷或開立處方。
2. 使用親切但專業的語氣，以繁體中文與病患對話。
3. 每次只問一個問題，不要一次問太多。
4. 根據病患的回答，決定下一個最相關的追問方向。
5. 使用通俗易懂的語言，避免過多醫學專業術語。
6. 若病患表達不清楚，禮貌地請求釐清。
7. 展現同理心，對病患的不適表示理解。
8. 若偵測到可能的緊急狀況，立即提醒病患就醫。

## 問診結構

請依據以下結構化順序進行問診。不需要嚴格按照順序，但應涵蓋所有相關面向:

### 第一階段: 主訴確認與症狀描述
- 確認病患主要困擾的症狀
- 症狀的具體表現 (如: 頻尿的頻率、每次量多少)
- 症狀開始的時間 (onset)
- 症狀的嚴重程度 (1-10 分)

### 第二階段: 症狀特徵
- 誘發因素 (什麼情況下會加重)
- 緩解因素 (什麼情況下會減輕)
- 伴隨症狀 (是否有其他不適)
- 症狀變化 (是持續、漸進、還是間歇性)

### 第三階段: 病史與用藥
- 過去是否有類似症狀
- 是否曾就醫或檢查
- 目前使用的藥物
- 過去的手術史 (特別是泌尿相關)
- 已知的慢性疾病 (高血壓、糖尿病等)

### 第四階段: 生活習慣與其他
- 飲水習慣
- 排尿日誌 (若適用)
- 性生活相關 (若與主訴相關，敏感詢問)
- 家族病史 (泌尿相關)
- 其他影響因素 (壓力、睡眠等)

### 問診結束
- 當你認為已收集足夠資訊時，進行簡短總結
- 詢問病患是否有遺漏或想補充的
- 告知病患問診結束，報告將產生

## 特定主訴的追問重點

{complaint_specific_guidelines}

## 當前場次資訊

- 病患年齡: {patient_age}
- 病患性別: {patient_gender}
- 主訴: {complaint_name}

## 回應格式

請直接以自然對話的方式回應，不要使用 markdown 格式、項目符號或任何特殊
標記。回應應簡短精練，通常在 1-3 句話以內。
```

#### 主訴特定追問指引 (complaint_specific_guidelines)

```python
COMPLAINT_GUIDELINES = {
    "頻尿": """
    - 每天排尿次數 (日間/夜間分別)
    - 每次排尿量 (多/少)
    - 是否有急迫感
    - 是否有漏尿
    - 是否有喝水量改變
    - 是否有攝取咖啡因或酒精
    """,
    "血尿": """
    - 血尿的顏色 (淡紅/鮮紅/深紅/茶色)
    - 是肉眼可見還是檢查才發現
    - 出現的時機 (排尿初段/中段/末段/全程)
    - 是否有血塊
    - 是否有疼痛
    - 是否有外傷史
    - 最近是否有做過侵入性檢查
    """,
    "排尿困難": """
    - 是否需要很用力才能排出
    - 是否需要等待才能開始
    - 尿流是否中斷
    - 是否有殘尿感
    - 排尿時是否疼痛
    - 是否有完全無法排出的情況
    """,
    # ... 其他主訴的追問指引
}
```

#### Context Window 管理策略

```python
class ConversationContextManager:
    MAX_CONTEXT_TURNS = 20        # 最大保留輪數
    SUMMARIZE_THRESHOLD = 10      # 超過此數開始摘要
    MAX_TOKENS_ESTIMATE = 8000    # 上下文 token 上限估算

    def build_messages(self, context: dict) -> list[dict]:
        """
        組裝傳送給 Claude API 的 messages 列表。

        策略:
        1. System message (system prompt, 固定)
        2. 若有先前摘要，加入 assistant message 作為上下文
        3. 最近 N 輪對話 (role 交替)
        4. 當前使用者輸入

        Token 估算:
        - 中文約每字 2 token
        - 每輪平均 50-100 字 (100-200 tokens)
        - System prompt 約 2000 tokens
        - 保留 4096 tokens 給 response
        """
        messages = []

        # 加入摘要 (若有)
        if context.get("summary"):
            messages.append({
                "role": "assistant",
                "content": f"[先前對話摘要] {context['summary']}"
            })

        # 加入最近對話輪次
        recent_turns = context["turns"][-self.MAX_CONTEXT_TURNS:]
        for turn in recent_turns:
            messages.append({
                "role": "user" if turn["role"] == "patient" else "assistant",
                "content": turn["content"]
            })

        return messages

    async def maybe_summarize(self, context: dict) -> dict:
        """
        當對話輪數超過 SUMMARIZE_THRESHOLD 時，
        對較早的對話進行摘要。
        """
        if len(context["turns"]) >= self.SUMMARIZE_THRESHOLD:
            older_turns = context["turns"][:-5]  # 保留最近 5 輪
            summary = await self._generate_summary(older_turns)
            context["summary"] = summary
            context["turns"] = context["turns"][-5:]  # 只保留最近 5 輪
        return context
```

#### Claude API 呼叫設定

```python
# Claude API 對話呼叫設定
llm_config = {
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 512,        # 回應簡短，通常 1-3 句
    "temperature": 0.7,       # 適度的創造性，使對話自然
    "system": system_prompt,  # 上方定義的 system prompt
    "messages": messages,     # 由 ContextManager 組裝
    "stop_sequences": [],     # 不需要額外的 stop sequence
}

# 超時與重試設定
API_TIMEOUT = 30              # 秒
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1          # 指數退避基數 (秒)
```

### 4-C. TTS Pipeline (語音合成管線)

#### Google Cloud TTS 設定

```python
# TTS 語音設定
tts_config = {
    "voice": {
        "language_code": "zh-TW",
        "name": "cmn-TW-Wavenet-A",  # Wavenet 最佳品質
        "ssml_gender": "FEMALE"
    },
    "audio_config": {
        "audio_encoding": "MP3",           # 或 OGG_OPUS (較小檔案)
        "speaking_rate": 0.9,              # 語速
        "pitch": 0.0,                      # 音高 (-20.0-20.0)
        "volume_gain_db": 0.0,             # 音量
        "sample_rate_hertz": 24000,        # 取樣率
        "effects_profile_id": ["handset-class-device"]  # 行動裝置最佳化
    }
}
```

#### SSML 模板

```python
def build_ssml(text: str) -> str:
    """
    將純文字轉換為 SSML 格式，加入適當的停頓與語調控制。
    """
    ssml = '<speak>'

    # 在句號後加入短暫停頓
    text = text.replace('。', '。<break time="300ms"/>')

    # 在逗號後加入更短的停頓
    text = text.replace('，', '，<break time="150ms"/>')

    # 在問號後加入停頓
    text = text.replace('？', '？<break time="400ms"/>')

    # 醫學術語使用較慢語速
    # (依據 medical_terms 字典進行標記)
    for term in MEDICAL_TERMS_FOR_SLOW_READ:
        if term in text:
            text = text.replace(
                term,
                f'<prosody rate="slow">{term}</prosody>'
            )

    ssml += text
    ssml += '</speak>'
    return ssml
```

#### 分段串流策略

```
1. 接收 LLM 完整回應文字
   |
   v
2. 依據句子切分 (句號、問號)
   |-- 切分為多個 text segments
   |-- 若單一句子超過 200 字，在逗號處再切分
   |
   v
3. 對每個 segment:
   |
   +-- 建構 SSML
   +-- 呼叫 Google TTS API
   +-- 取得 audio content (bytes)
   +-- Base64 編碼
   +-- 透過 WebSocket 傳送至 client
   |   {type: "ai_response_audio", data: base64, seq: N, is_final: false}
   |
   v
4. 最後一個 segment 傳送時標記 is_final: true
   |
   v
5. 合併所有 audio segments，上傳至 S3 (背景任務)
```

### 4-D. 紅旗偵測管線 (Red Flag Detection Pipeline)

#### 規則引擎設定

```python
class RuleEngine:
    """
    基於規則的紅旗偵測引擎。
    使用 Aho-Corasick 演算法進行多模式字串匹配。
    """

    def __init__(self):
        self.automaton = ahocorasick.Automaton()
        self.rules: dict[str, RedFlagRule] = {}
        self.compiled_regex: dict[str, re.Pattern] = {}

    def load_rules(self, rules: list[RedFlagRule]):
        """
        載入所有啟用的紅旗規則至記憶體。
        建構 Aho-Corasick 自動機。
        """
        for rule in rules:
            self.rules[rule.id] = rule

            # 加入關鍵字至自動機
            if rule.keywords:
                for keyword in rule.keywords:
                    self.automaton.add_word(keyword, (rule.id, keyword))

            # 編譯正則表達式
            if rule.regex_pattern:
                self.compiled_regex[rule.id] = re.compile(
                    rule.regex_pattern, re.IGNORECASE
                )

        self.automaton.make_automaton()

    def detect(self, text: str) -> list[RuleMatchResult]:
        """
        對輸入文字執行規則比對。

        回傳所有匹配的規則及其匹配詳情。
        """
        results = []
        normalized_text = normalize_chinese(text)
        normalized_text = remove_punctuation(normalized_text)

        # Aho-Corasick 多模式匹配
        for end_index, (rule_id, keyword) in self.automaton.iter(normalized_text):
            start_index = end_index - len(keyword) + 1
            results.append(RuleMatchResult(
                rule_id=rule_id,
                rule=self.rules[rule_id],
                matched_text=keyword,
                position=(start_index, end_index),
                match_type="keyword"
            ))

        # 正則表達式匹配
        for rule_id, pattern in self.compiled_regex.items():
            matches = pattern.finditer(normalized_text)
            for match in matches:
                results.append(RuleMatchResult(
                    rule_id=rule_id,
                    rule=self.rules[rule_id],
                    matched_text=match.group(),
                    position=(match.start(), match.end()),
                    match_type="regex"
                ))

        # 去重 (同一規則多次匹配只計一次，取最高嚴重度)
        deduplicated = self._deduplicate(results)

        return deduplicated
```

#### LLM 語意分析 Prompt

```
你是一個泌尿科醫療紅旗偵測系統。分析以下病患在問診中的發言，判斷是否存在
需要緊急醫療處理的危險信號 (red flags)。

## 評估標準

### critical (立即危險 -- 需要中止問診並立即就醫)
- 大量活動性血尿 (特別是伴隨血塊、無法止住)
- 急性尿滯留超過 8 小時 (完全無法排尿，腹部脹痛)
- 疑似睪丸扭轉 (睪丸突發劇烈疼痛，特別是兒童/青少年)
- 嚴重感染徵兆 (高燒 >39度 合併泌尿症狀、寒顫、意識變化)
- 腎絞痛伴隨生命徵象不穩 (劇烈腰痛、冷汗、嘔吐不止)
- 泌尿生殖系統嚴重外傷

### high (需盡速處理 -- 標記但繼續問診)
- 中度出血但尚穩定
- 發燒 (38-39度) 合併泌尿症狀
- 急性劇烈疼痛但可忍受
- 陰囊或生殖器腫脹
- 排尿困難明顯惡化

### medium (需注意 -- 記錄追蹤)
- 不明原因體重下降
- 慢性症狀持續惡化
- 複發性泌尿道感染
- 不明原因持續疲勞

### none
- 一般症狀描述，無危險信號

## 對話上下文

{conversation_context}

## 當前病患發言

"{patient_utterance}"

## 回應格式 (嚴格 JSON)

{
  "severity": "critical" | "high" | "medium" | "none",
  "detected": true | false,
  "reason": "簡要說明判斷理由 (繁體中文)",
  "matched_symptoms": ["具體匹配的症狀描述"],
  "confidence": 0.0 - 1.0,
  "recommended_action": "建議採取的行動"
}
```

#### 雙層偵測結果合併邏輯

```python
async def detect_red_flags(
    text: str,
    context: dict
) -> RedFlagDetectionResult:
    """
    並行執行規則引擎與 LLM 語意分析，合併結果。
    """
    # 並行執行
    rule_result, llm_result = await asyncio.gather(
        rule_engine.detect(text),
        llm_semantic_analysis(text, context),
        return_exceptions=True
    )

    # 處理個別失敗
    if isinstance(rule_result, Exception):
        logger.error(f"Rule engine failed: {rule_result}")
        rule_result = []
    if isinstance(llm_result, Exception):
        logger.error(f"LLM analysis failed: {llm_result}")
        llm_result = RedFlagLLMResult(severity="none", detected=False)

    # 合併結果: 取最高嚴重度
    severity_order = {"critical": 4, "high": 3, "medium": 2, "none": 1}

    rule_severity = max(
        (severity_order[r.rule.severity] for r in rule_result),
        default=1
    )
    llm_severity = severity_order.get(llm_result.severity, 1)

    final_severity_value = max(rule_severity, llm_severity)
    final_severity = {v: k for k, v in severity_order.items()}[final_severity_value]

    # 決定 alert_type
    if rule_severity >= 2 and llm_severity >= 2:
        alert_type = "combined"
    elif rule_severity >= llm_severity:
        alert_type = "rule_based"
    else:
        alert_type = "semantic"

    return RedFlagDetectionResult(
        severity=final_severity,
        detected=final_severity != "none",
        alert_type=alert_type,
        rule_matches=rule_result,
        llm_analysis=llm_result,
    )
```

### 4-E. SOAP 報告產生管線 (SOAP Generation Pipeline)

#### 完整 SOAP Prompt 模板

```
你是一位經驗豐富的泌尿科醫師，正在根據 AI 問診助手與病患的對話記錄撰寫
SOAP 格式的病歷報告。

## 病患資訊
- 年齡: {patient_age} 歲
- 性別: {patient_gender}
- 主訴: {complaint_name}

## 對話記錄

{conversation_transcript}

## 紅旗事件 (若有)

{red_flag_alerts}

## 報告格式要求

請以嚴格的 JSON 格式產生 SOAP 報告。每個 section (subjective, objective,
assessment, plan) 都是結構化的 JSONB 物件。

(詳細 JSONB 結構參見 shared_types.md section 3.6)

## 注意事項
1. 所有內容必須基於對話記錄中的實際資訊，不可臆測
2. 鑑別診斷至少列出 2 個，最多 5 個，依可能性排序 (放在 assessment 內)
3. 建議檢查須與鑑別診斷相關 (放在 plan 內)
4. ICD-10 代碼必須正確
5. 若對話資訊不足以進行完整評估，在 assessment 中明確指出
6. 回應必須是合法的 JSON 格式
```

#### 輸出驗證

```python
from pydantic import BaseModel, validator

class SOAPOutput(BaseModel):
    subjective: dict       # JSONB
    objective: dict        # JSONB
    assessment: dict       # JSONB (含 differential_diagnoses)
    plan: dict             # JSONB (含 recommended_tests)
    summary: str           # 給病患的白話摘要

    @validator("assessment")
    def validate_assessment(cls, v):
        if "differential_diagnoses" not in v:
            raise ValueError("assessment must contain differential_diagnoses")
        diagnoses = v["differential_diagnoses"]
        if len(diagnoses) < 2:
            raise ValueError("At least 2 differential diagnoses required")
        if len(diagnoses) > 5:
            raise ValueError("At most 5 differential diagnoses allowed")
        return v
```

#### 錯誤處理與重試

```python
async def generate_soap_report(session_id: str) -> SOAPReport:
    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES):
        try:
            # 呼叫 Claude API
            response = await claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                temperature=0.3,
                system=SOAP_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": formatted_transcript}]
            )

            # 擷取 JSON 內容
            raw_text = response.content[0].text
            json_str = extract_json_from_response(raw_text)

            # 驗證與解析
            soap_data = SOAPOutput.model_validate_json(json_str)

            return soap_data

        except json.JSONDecodeError as e:
            logger.warning(f"SOAP JSON parse failed (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                # 在下次嘗試的 prompt 中加入格式修正提示
                formatted_transcript += (
                    "\n\n[系統提示: 上次回應的 JSON 格式有誤，"
                    "請確保回應是合法的 JSON 格式，不要包含 markdown 標記]"
                )
                await asyncio.sleep(2 ** attempt)  # 指數退避
            else:
                raise SOAPGenerationError(
                    f"Failed to generate valid SOAP after {MAX_RETRIES} attempts"
                )

        except ValidationError as e:
            logger.warning(f"SOAP validation failed (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                formatted_transcript += (
                    f"\n\n[系統提示: 上次回應缺少必要欄位或格式不正確。"
                    f"錯誤: {str(e)}。請修正後重新產生]"
                )
                await asyncio.sleep(2 ** attempt)
            else:
                raise SOAPGenerationError(
                    f"SOAP validation failed after {MAX_RETRIES} attempts: {e}"
                )

        except anthropic.APIError as e:
            logger.error(f"Claude API error (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise
```

---

## 5. 背景任務 (Background Tasks)

### 5-A. 音訊檔案清理排程 (Audio Cleanup Scheduler)

```python
# 排程: 每日凌晨 03:00 (Asia/Taipei)
# 檔案: app/tasks/audio_cleanup.py

async def cleanup_expired_audio():
    """
    清理已過保留期限的音訊檔案。

    流程:
    1. 查詢 retention_expires_at < now() 且 is_deleted = false 的記錄
    2. 批次處理 (每批 100 筆)
    3. 對每筆記錄:
       a. 從 S3 刪除檔案
       b. 更新 DB 記錄 (is_deleted=true, deleted_at=now())
    4. 記錄清理統計至稽核日誌
    """
    batch_size = 100
    total_deleted = 0
    total_freed_bytes = 0

    while True:
        expired_files = await db.execute(
            select(AudioFile)
            .where(AudioFile.retention_expires_at < datetime.utcnow())
            .where(AudioFile.is_deleted == False)
            .limit(batch_size)
        )
        files = expired_files.scalars().all()

        if not files:
            break

        for file in files:
            try:
                await s3_service.delete_file(file.s3_bucket, file.s3_key)
                file.is_deleted = True
                file.deleted_at = datetime.utcnow()
                total_deleted += 1
                total_freed_bytes += file.file_size_bytes
            except Exception as e:
                logger.error(f"Failed to delete audio file {file.id}: {e}")
                # 個別失敗不影響整批處理

        await db.commit()

    logger.info(
        f"Audio cleanup completed: {total_deleted} files deleted, "
        f"{total_freed_bytes / 1024 / 1024:.2f} MB freed"
    )
```

### 5-B. 場次超時處理 (Session Timeout Handler)

```python
# 排程: 每 5 分鐘
# 檔案: app/tasks/session_timeout.py

TIMEOUT_RULES = {
    "waiting": {
        "timeout_minutes": 30,
        "action": "cancel",
        "target_status": "cancelled",
    },
    "in_progress": {
        "warning_minutes": 60,
        "timeout_minutes": 120,
        "action": "complete",
        "target_status": "completed",
    },
}

async def check_session_timeouts():
    """
    檢查並處理超時的問診場次。

    流程:
    1. 查詢所有 waiting 狀態超過 30 分鐘的場次 -> 自動取消
    2. 查詢所有 in_progress 狀態超過 60 分鐘的場次 -> 發送提醒
    3. 查詢所有 in_progress 狀態超過 120 分鐘的場次 -> 自動完成
    4. 更新佇列與通知
    """
    now = datetime.utcnow()

    # 處理 waiting 超時
    stale_waiting = await db.execute(
        select(Session)
        .where(Session.status == "waiting")
        .where(Session.created_at < now - timedelta(minutes=30))
    )
    for session in stale_waiting.scalars():
        session.status = "cancelled"
        await queue_service.remove_from_queue(session.id)
        await notification_service.send(
            user_id=session.patient_id,
            type="system",
            title="問診場次已逾時取消",
            body="您的問診場次因超過 30 分鐘未開始已自動取消。如需問診請重新建立。"
        )

    # 處理 in_progress 警告 (60 分鐘)
    long_sessions = await db.execute(
        select(Session)
        .where(Session.status == "in_progress")
        .where(Session.started_at < now - timedelta(minutes=60))
        .where(Session.started_at >= now - timedelta(minutes=120))
    )
    for session in long_sessions.scalars():
        await notification_service.send(
            user_id=session.patient_id,
            type="system",
            title="問診時間提醒",
            body="您的問診已進行超過 60 分鐘。如已完成請結束問診。"
        )

    # 處理 in_progress 超時 (120 分鐘)
    expired_sessions = await db.execute(
        select(Session)
        .where(Session.status == "in_progress")
        .where(Session.started_at < now - timedelta(minutes=120))
    )
    for session in expired_sessions.scalars():
        session.status = "completed"
        session.completed_at = now
        session.duration_seconds = int((now - session.started_at).total_seconds())
        await queue_service.remove_from_queue(session.id)
        # 觸發 SOAP 報告產生
        await report_generation_queue.enqueue(session.id)

    await db.commit()
```

### 5-C. 報告產生佇列 (Report Generation Queue)

```python
# 檔案: app/tasks/report_queue.py
# 使用 Redis List 作為簡單的任務佇列

QUEUE_KEY = "gu:report_generation_queue"

async def enqueue_report_generation(session_id: str):
    """將報告產生任務加入佇列。"""
    await redis.rpush(QUEUE_KEY, session_id)

async def process_report_queue():
    """
    排程: 持續執行 (worker process)

    流程:
    1. 從 Redis 佇列取出 session_id (BLPOP, 阻塞等待)
    2. 呼叫 SOAP 產生管線
    3. 成功: 更新報告狀態，通知醫師
    4. 失敗: 重試 (最多 3 次)，超過後標記失敗，通知管理員
    """
    while True:
        result = await redis.blpop(QUEUE_KEY, timeout=30)
        if result is None:
            continue

        _, session_id = result
        session_id = session_id.decode()
        retry_key = f"gu:report_retry:{session_id}"
        retry_count = int(await redis.get(retry_key) or 0)

        try:
            await soap_generation_pipeline.generate(session_id)
            await redis.delete(retry_key)

            # 通知醫師
            session = await session_service.get(session_id)
            if session.doctor_id:
                await notification_service.send(
                    user_id=session.doctor_id,
                    type="report_ready",
                    title="SOAP 報告已產生",
                    body=f"病患的問診報告已產生，請審閱。",
                    data={"session_id": session_id}
                )

        except Exception as e:
            logger.error(f"Report generation failed for session {session_id}: {e}")
            retry_count += 1
            if retry_count < 3:
                await redis.set(retry_key, retry_count, ex=3600)
                # 延遲重試 (指數退避)
                delay = 2 ** retry_count * 60  # 2, 4, 8 分鐘
                await asyncio.sleep(delay)
                await redis.rpush(QUEUE_KEY, session_id)
            else:
                logger.critical(
                    f"Report generation permanently failed for session {session_id}"
                )
                await redis.delete(retry_key)
                # 通知管理員
                await notification_service.send_to_admins(
                    type="system",
                    title="報告產生失敗",
                    body=f"場次 {session_id} 的報告產生失敗，已重試 3 次。"
                )
```

### 5-D. 通知重試佇列 (Notification Retry Queue)

```python
# 排程: 每 2 分鐘
# 檔案: app/tasks/notification_retry.py

RETRY_QUEUE_KEY = "gu:notification_retry_queue"
MAX_RETRIES = 5

async def retry_failed_notifications():
    """
    重試傳送失敗的通知 (主要是 FCM 推播)。

    流程:
    1. 從 Redis retry queue 取出失敗的通知
    2. 重新嘗試傳送
    3. 成功: 更新通知狀態
    4. 失敗: 累加重試次數
       - 未超過上限: 放回佇列 (指數退避)
       - 超過上限: 標記為永久失敗，檢查裝置 token 有效性
    """
    batch = await redis.lrange(RETRY_QUEUE_KEY, 0, 49)  # 每次處理 50 筆
    if not batch:
        return

    await redis.ltrim(RETRY_QUEUE_KEY, len(batch), -1)

    for item_raw in batch:
        item = json.loads(item_raw)
        notification_id = item["notification_id"]
        retry_count = item.get("retry_count", 0)

        try:
            notification = await notification_service.get(notification_id)
            await fcm_service.send_notification(
                device_token=item["device_token"],
                title=notification.title,
                body=notification.body,
                data=notification.data
            )
            await db.commit()

        except fcm_errors.InvalidRegistrationError:
            # FCM token 無效，停用裝置
            await device_service.deactivate_device(item["device_token"])
            logger.info(f"Deactivated invalid FCM token: {item['device_token'][:20]}...")

        except Exception as e:
            retry_count += 1
            if retry_count < MAX_RETRIES:
                item["retry_count"] = retry_count
                await redis.rpush(RETRY_QUEUE_KEY, json.dumps(item))
            else:
                logger.error(
                    f"Notification {notification_id} permanently failed "
                    f"after {MAX_RETRIES} retries: {e}"
                )
```

### 5-E. 排程器設定 (Scheduler Configuration)

```python
# 檔案: app/tasks/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")

    # 音訊清理: 每日凌晨 03:00
    scheduler.add_job(
        cleanup_expired_audio,
        trigger=CronTrigger(hour=3, minute=0),
        id="audio_cleanup",
        name="清理過期音訊檔案",
        misfire_grace_time=3600,
        max_instances=1,
    )

    # 場次超時檢查: 每 5 分鐘
    scheduler.add_job(
        check_session_timeouts,
        trigger=IntervalTrigger(minutes=5),
        id="session_timeout",
        name="檢查場次超時",
        misfire_grace_time=60,
        max_instances=1,
    )

    # 通知重試: 每 2 分鐘
    scheduler.add_job(
        retry_failed_notifications,
        trigger=IntervalTrigger(minutes=2),
        id="notification_retry",
        name="重試失敗通知",
        misfire_grace_time=30,
        max_instances=1,
    )

    # Redis context 清理: 每小時
    scheduler.add_job(
        cleanup_stale_contexts,
        trigger=IntervalTrigger(hours=1),
        id="context_cleanup",
        name="清理過期 Redis 對話上下文",
        misfire_grace_time=300,
        max_instances=1,
    )

    # 每日統計快照: 每日 23:59
    scheduler.add_job(
        generate_daily_stats_snapshot,
        trigger=CronTrigger(hour=23, minute=59),
        id="daily_stats",
        name="產生每日統計快照",
        misfire_grace_time=3600,
        max_instances=1,
    )

    return scheduler
```

---

## 6. 錯誤處理策略 (Error Handling)

### 6-A. 全域例外處理器 (Global Exception Handler)

```python
# 檔案: app/core/exceptions.py

from fastapi import Request
from fastapi.responses import JSONResponse
import uuid

# ================================================================
# 基礎例外類別
# ================================================================

class AppException(Exception):
    """應用程式基礎例外"""
    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 500,
        details: dict = None
    ):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


# ================================================================
# 領域特定例外（error_code 使用語意名稱）
# ================================================================

# --- 認證相關 ---

class AuthenticationError(AppException):
    def __init__(self, message="認證失敗"):
        super().__init__("INVALID_CREDENTIALS", message, 401)

class UnauthorizedError(AppException):
    def __init__(self, message="未認證或 Token 過期"):
        super().__init__("UNAUTHORIZED", message, 401)

class ForbiddenError(AppException):
    def __init__(self, message="權限不足"):
        super().__init__("FORBIDDEN", message, 403)

class AccountDisabledError(AppException):
    def __init__(self, message="帳號已停用"):
        super().__init__("ACCOUNT_DISABLED", message, 403)

class EmailAlreadyExistsError(AppException):
    def __init__(self, message="此 Email 已註冊"):
        super().__init__("EMAIL_ALREADY_EXISTS", message, 409)

# --- 場次相關 ---

class SessionNotFoundError(AppException):
    def __init__(self, session_id: str = ""):
        super().__init__("SESSION_NOT_FOUND", f"找不到場次: {session_id}", 404)

class SessionNotActiveError(AppException):
    def __init__(self, message="場次非活躍狀態"):
        super().__init__("SESSION_NOT_ACTIVE", message, 409)

class InvalidStatusTransitionError(AppException):
    def __init__(self, current_state: str, target_state: str):
        super().__init__(
            "INVALID_STATUS_TRANSITION",
            f"不合法的狀態轉移: {current_state} -> {target_state}",
            409
        )

class ConflictError(AppException):
    def __init__(self, message="資源衝突"):
        super().__init__("CONFLICT", message, 409)

# --- 報告相關 ---

class ReportNotReadyError(AppException):
    def __init__(self, message="報告尚未產生完成"):
        super().__init__("REPORT_NOT_READY", message, 409)

class ReportAlreadyExistsError(AppException):
    def __init__(self, message="報告已存在"):
        super().__init__("REPORT_ALREADY_EXISTS", message, 409)

# --- 紅旗相關 ---

class AlertAlreadyAcknowledgedError(AppException):
    def __init__(self, message="警示已確認"):
        super().__init__("ALERT_ALREADY_ACKNOWLEDGED", message, 409)

# --- 外部服務 ---

class AIServiceUnavailableError(AppException):
    def __init__(self, message="AI 服務不可用"):
        super().__init__("AI_SERVICE_UNAVAILABLE", message, 503)

class RateLimitExceededError(AppException):
    def __init__(self, message="超過速率限制"):
        super().__init__("RATE_LIMIT_EXCEEDED", message, 429)

# --- 通用 ---

class NotFoundError(AppException):
    def __init__(self, resource_type: str = "資源", resource_id: str = ""):
        super().__init__("NOT_FOUND", f"找不到 {resource_type}: {resource_id}", 404)

class ValidationError(AppException):
    def __init__(self, message: str, details: dict = None):
        super().__init__("VALIDATION_ERROR", message, 422, details)

class InternalError(AppException):
    def __init__(self, message="內部伺服器錯誤"):
        super().__init__("INTERNAL_ERROR", message, 500)


# ================================================================
# 全域例外處理器
# ================================================================

async def app_exception_handler(request: Request, exc: AppException):
    """處理所有 AppException 及其子類別"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "request_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        }
    )

async def generic_exception_handler(request: Request, exc: Exception):
    """處理所有未預期的例外"""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "系統內部錯誤，請稍後再試",
                "details": {},
                "request_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        }
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """處理 Pydantic 驗證錯誤"""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "請求資料驗證失敗",
                "details": {
                    "errors": [
                        {
                            "field": ".".join(str(loc) for loc in err["loc"]),
                            "message": err["msg"],
                            "type": err["type"]
                        }
                        for err in exc.errors()
                    ]
                },
                "request_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        }
    )
```

### 6-B. 錯誤碼對照表

| 錯誤碼 | HTTP 狀態碼 | 說明 |
|--------|-------------|------|
| `UNAUTHORIZED` | 401 | 未認證或 Token 過期 |
| `FORBIDDEN` | 403 | 權限不足 |
| `NOT_FOUND` | 404 | 資源不存在 |
| `VALIDATION_ERROR` | 422 | 請求參數驗證失敗 |
| `CONFLICT` | 409 | 資源衝突 |
| `INVALID_CREDENTIALS` | 401 | 帳號或密碼錯誤 |
| `ACCOUNT_DISABLED` | 403 | 帳號已停用 |
| `EMAIL_ALREADY_EXISTS` | 409 | Email 已註冊 |
| `SESSION_NOT_FOUND` | 404 | 場次不存在 |
| `SESSION_NOT_ACTIVE` | 409 | 場次非活躍狀態 |
| `INVALID_STATUS_TRANSITION` | 409 | 不合法的狀態轉移 |
| `REPORT_NOT_READY` | 409 | 報告尚未產生完成 |
| `REPORT_ALREADY_EXISTS` | 409 | 報告已存在 |
| `ALERT_ALREADY_ACKNOWLEDGED` | 409 | 警示已確認 |
| `AI_SERVICE_UNAVAILABLE` | 503 | AI 服務不可用 |
| `RATE_LIMIT_EXCEEDED` | 429 | 超過速率限制 |
| `INTERNAL_ERROR` | 500 | 內部伺服器錯誤 |

### 6-C. 外部 API 重試策略 (Retry Strategies)

```python
# 檔案: app/core/retry.py

import asyncio
from functools import wraps

class RetryConfig:
    """外部 API 重試設定"""

    # Claude API (LLM)
    LLM = {
        "max_retries": 3,
        "base_delay": 1.0,        # 秒
        "max_delay": 30.0,        # 秒
        "exponential_base": 2,
        "retryable_status_codes": [429, 500, 502, 503, 529],
        "retryable_exceptions": ["APIConnectionError", "InternalServerError"],
    }

    # Google Cloud STT
    STT = {
        "max_retries": 2,
        "base_delay": 0.5,
        "max_delay": 10.0,
        "exponential_base": 2,
        "retryable_status_codes": [429, 500, 503],
    }

    # Google Cloud TTS
    TTS = {
        "max_retries": 2,
        "base_delay": 0.5,
        "max_delay": 10.0,
        "exponential_base": 2,
        "retryable_status_codes": [429, 500, 503],
    }

    # Firebase Cloud Messaging
    FCM = {
        "max_retries": 3,
        "base_delay": 1.0,
        "max_delay": 60.0,
        "exponential_base": 2,
        "retryable_status_codes": [429, 500, 503],
    }

    # S3
    S3 = {
        "max_retries": 3,
        "base_delay": 0.5,
        "max_delay": 15.0,
        "exponential_base": 2,
        "retryable_exceptions": [
            "EndpointConnectionError",
            "ConnectionClosedError"
        ],
    }


def with_retry(config: dict):
    """帶有指數退避的重試裝飾器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(config["max_retries"] + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt == config["max_retries"]:
                        raise
                    if not _is_retryable(e, config):
                        raise
                    delay = min(
                        config["base_delay"] * (
                            config["exponential_base"] ** attempt
                        ),
                        config["max_delay"]
                    )
                    # 加入 jitter (0-25%)
                    jitter = delay * 0.25 * random.random()
                    await asyncio.sleep(delay + jitter)
                    logger.warning(
                        f"Retrying {func.__name__} "
                        f"(attempt {attempt + 1}/{config['max_retries']}): {e}"
                    )
            raise last_exception
        return wrapper
    return decorator


def _is_retryable(exception: Exception, config: dict) -> bool:
    """判斷例外是否可重試"""
    exception_name = type(exception).__name__
    if exception_name in config.get("retryable_exceptions", []):
        return True
    if hasattr(exception, "status_code"):
        return exception.status_code in config.get("retryable_status_codes", [])
    return False
```

#### WebSocket 特殊錯誤處理

```python
# WebSocket 連線中的錯誤處理策略

async def handle_conversation_ws(websocket: WebSocket, session_id: str):
    try:
        await websocket.accept()
        # ... 對話處理
    except WebSocketDisconnect:
        # 正常斷線 -- 記錄並清理
        logger.info(f"WebSocket disconnected: session={session_id}")
        await connection_manager.disconnect(session_id)
        # 設定重連等待計時器 (5 分鐘)
        await redis.setex(
            f"gu:ws_reconnect_wait:{session_id}",
            300,
            "disconnected"
        )
    except AIServiceUnavailableError:
        # STT/LLM/TTS 失敗 -- 通知前端
        await websocket.send_json({
            "type": "error",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": {
                "code": "AI_SERVICE_UNAVAILABLE",
                "message": "AI 服務暫時無法使用，請稍後再試"
            }
        })
    except Exception as e:
        logger.exception(f"Unexpected WS error: session={session_id}, error={e}")
        try:
            await websocket.send_json({
                "type": "error",
                "id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "payload": {
                    "code": "INTERNAL_ERROR",
                    "message": "發生未預期的錯誤，請重新連線"
                }
            })
        except Exception:
            pass
        finally:
            await connection_manager.disconnect(session_id)
```

---

## 7. 環境配置 (Configuration)

### 7-A. 環境變數清單 (Environment Variables)

```bash
# ================================================================
# 應用程式基本設定
# ================================================================
APP_NAME=gu-voice-assistant
APP_ENV=development                    # development | staging | production
APP_DEBUG=true                         # true | false
APP_HOST=0.0.0.0
APP_PORT=8000
APP_WORKERS=4                          # uvicorn worker 數量
APP_LOG_LEVEL=INFO                     # DEBUG | INFO | WARNING | ERROR
APP_SECRET_KEY=your-256-bit-secret     # 應用程式主密鑰
APP_ALLOWED_ORIGINS=http://localhost:3000,https://app.example.com
APP_API_PREFIX=/api/v1
APP_TIMEZONE=Asia/Taipei

# ================================================================
# PostgreSQL 資料庫
# ================================================================
DB_HOST=localhost
DB_PORT=5432
DB_NAME=gu_voice_assistant
DB_USER=gu_admin
DB_PASSWORD=your-db-password
DB_ECHO=false                          # SQLAlchemy echo (SQL 日誌)
DB_POOL_SIZE=10                        # 連線池大小
DB_MAX_OVERFLOW=20                     # 連線池溢出上限
DB_POOL_TIMEOUT=30                     # 連線等待超時 (秒)
DB_POOL_RECYCLE=3600                   # 連線回收時間 (秒)
DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}

# ================================================================
# Redis
# ================================================================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
REDIS_DB=0
REDIS_MAX_CONNECTIONS=50
REDIS_SOCKET_TIMEOUT=5
REDIS_KEY_PREFIX=gu:
REDIS_URL=redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}

# ================================================================
# JWT 認證 (RS256 非對稱加密)
# ================================================================
JWT_ALGORITHM=RS256
JWT_PRIVATE_KEY_PATH=/path/to/private.pem
JWT_PUBLIC_KEY_PATH=/path/to/public.pem
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
JWT_ISSUER=gu-voice-assistant
JWT_AUDIENCE=gu-app

# ================================================================
# Google Cloud (STT / TTS)
# ================================================================
GOOGLE_CLOUD_PROJECT_ID=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
GOOGLE_STT_LANGUAGE_CODE=zh-TW
GOOGLE_STT_MODEL=chirp_2
GOOGLE_STT_SAMPLE_RATE=16000
GOOGLE_TTS_VOICE_NAME=cmn-TW-Wavenet-A
GOOGLE_TTS_SPEAKING_RATE=0.9
GOOGLE_TTS_SAMPLE_RATE=24000

# ================================================================
# Claude API (Anthropic)
# ================================================================
ANTHROPIC_API_KEY=sk-ant-your-api-key
CLAUDE_MODEL_CONVERSATION=claude-sonnet-4-20250514
CLAUDE_MODEL_SOAP=claude-sonnet-4-20250514
CLAUDE_MODEL_RED_FLAG=claude-haiku-4-5-20251001
CLAUDE_TEMPERATURE_CONVERSATION=0.7
CLAUDE_TEMPERATURE_SOAP=0.3
CLAUDE_TEMPERATURE_RED_FLAG=0.2
CLAUDE_MAX_TOKENS_CONVERSATION=512
CLAUDE_MAX_TOKENS_SOAP=4096
CLAUDE_API_TIMEOUT=30
CLAUDE_MAX_RETRIES=3

# ================================================================
# Firebase Cloud Messaging
# ================================================================
FCM_CREDENTIALS_PATH=/path/to/firebase-service-account.json
FCM_PROJECT_ID=your-firebase-project-id

# ================================================================
# S3 相容儲存 (MinIO / AWS S3 / GCS)
# ================================================================
S3_ENDPOINT_URL=https://s3.amazonaws.com   # MinIO: http://localhost:9000
S3_BUCKET=gu-voice-assistant-audio
S3_REGION=ap-northeast-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
S3_PRESIGNED_URL_EXPIRY=3600               # 預簽名 URL 有效期 (秒)

# ================================================================
# 音訊保留政策
# ================================================================
AUDIO_RETENTION_DAYS=1095                  # 音訊保留天數（3 年）
AUDIO_RETENTION_DAYS_NORMAL=90
AUDIO_RETENTION_DAYS_RED_FLAG=365
AUDIO_RETENTION_DAYS_ABORTED=365
AUDIO_MAX_FILE_SIZE_MB=50

# ================================================================
# 場次設定
# ================================================================
SESSION_TIMEOUT_CREATED_MINUTES=30
SESSION_TIMEOUT_WARNING_MINUTES=60
SESSION_TIMEOUT_MAX_MINUTES=120
SESSION_WS_RECONNECT_TIMEOUT_SECONDS=300

# ================================================================
# 對話設定
# ================================================================
CONVERSATION_MAX_CONTEXT_TURNS=20
CONVERSATION_SUMMARIZE_THRESHOLD=10
CONVERSATION_CONTEXT_TTL_SECONDS=3600

# ================================================================
# 速率限制
# ================================================================
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_WS_MESSAGES_PER_SECOND=10
RATE_LIMIT_AUTH_ATTEMPTS_PER_HOUR=10

# ================================================================
# 排程器
# ================================================================
SCHEDULER_AUDIO_CLEANUP_HOUR=3
SCHEDULER_AUDIO_CLEANUP_MINUTE=0
SCHEDULER_SESSION_TIMEOUT_INTERVAL_MINUTES=5
SCHEDULER_NOTIFICATION_RETRY_INTERVAL_MINUTES=2
SCHEDULER_CONTEXT_CLEANUP_INTERVAL_HOURS=1

# ================================================================
# 監控
# ================================================================
SENTRY_DSN=                               # Sentry DSN (選用)
PROMETHEUS_PORT=9090                       # Prometheus metrics 埠

# ================================================================
# 日誌
# ================================================================
LOG_FORMAT=json                            # json | text
LOG_FILE_PATH=/var/log/gu-assistant/app.log
LOG_FILE_MAX_SIZE_MB=100
LOG_FILE_BACKUP_COUNT=10
```

### 7-B. Config Management (pydantic-settings)

```python
# 檔案: app/core/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 應用程式基本設定 ---
    app_name: str = "gu-voice-assistant"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_workers: int = 4
    app_log_level: str = "INFO"
    app_secret_key: str
    app_allowed_origins: str = "http://localhost:3000"
    app_api_prefix: str = "/api/v1"
    app_timezone: str = "Asia/Taipei"

    # --- PostgreSQL ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "gu_voice_assistant"
    db_user: str = "gu_admin"
    db_password: str
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_max_connections: int = 50
    redis_socket_timeout: int = 5
    redis_key_prefix: str = "gu:"

    # --- JWT (RS256) ---
    jwt_algorithm: str = "RS256"
    jwt_private_key_path: str = ""
    jwt_public_key_path: str = ""
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    jwt_issuer: str = "gu-voice-assistant"
    jwt_audience: str = "gu-app"

    # --- Google Cloud ---
    google_cloud_project_id: str = ""
    google_application_credentials: str = ""
    google_stt_language_code: str = "zh-TW"
    google_stt_model: str = "chirp_2"
    google_stt_sample_rate: int = 16000
    google_tts_voice_name: str = "cmn-TW-Wavenet-A"
    google_tts_speaking_rate: float = 0.9
    google_tts_sample_rate: int = 24000

    # --- Claude API ---
    anthropic_api_key: str = ""
    claude_model_conversation: str = "claude-sonnet-4-20250514"
    claude_model_soap: str = "claude-sonnet-4-20250514"
    claude_model_red_flag: str = "claude-haiku-4-5-20251001"
    claude_temperature_conversation: float = 0.7
    claude_temperature_soap: float = 0.3
    claude_temperature_red_flag: float = 0.2
    claude_max_tokens_conversation: int = 512
    claude_max_tokens_soap: int = 4096
    claude_api_timeout: int = 30
    claude_max_retries: int = 3

    # --- FCM ---
    fcm_credentials_path: str = ""
    fcm_project_id: str = ""

    # --- S3 ---
    s3_endpoint_url: str = "https://s3.amazonaws.com"
    s3_bucket: str = "gu-voice-assistant-audio"
    s3_region: str = "ap-northeast-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_presigned_url_expiry: int = 3600

    # --- 音訊保留 ---
    audio_retention_days: int = 1095
    audio_retention_days_normal: int = 90
    audio_retention_days_red_flag: int = 365
    audio_retention_days_aborted: int = 365
    audio_max_file_size_mb: int = 50

    # --- 場次 ---
    session_timeout_created_minutes: int = 30
    session_timeout_warning_minutes: int = 60
    session_timeout_max_minutes: int = 120
    session_ws_reconnect_timeout_seconds: int = 300

    # --- 對話 ---
    conversation_max_context_turns: int = 20
    conversation_summarize_threshold: int = 10
    conversation_context_ttl_seconds: int = 3600

    # --- 速率限制 ---
    rate_limit_requests_per_minute: int = 60
    rate_limit_ws_messages_per_second: int = 10
    rate_limit_auth_attempts_per_hour: int = 10

    # --- 排程器 ---
    scheduler_audio_cleanup_hour: int = 3
    scheduler_audio_cleanup_minute: int = 0
    scheduler_session_timeout_interval_minutes: int = 5
    scheduler_notification_retry_interval_minutes: int = 2
    scheduler_context_cleanup_interval_hours: int = 1

    # --- 監控 ---
    sentry_dsn: str = ""
    prometheus_port: int = 9090

    # --- 日誌 ---
    log_format: str = "json"
    log_file_path: str = "/var/log/gu-assistant/app.log"
    log_file_max_size_mb: int = 100
    log_file_backup_count: int = 10

    # --- 衍生屬性 ---
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        password_part = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{password_part}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.app_allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    # --- 驗證器 ---
    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v):
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"app_env must be one of: {allowed}")
        return v

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, v):
        allowed = ["RS256", "RS384", "RS512"]
        if v not in allowed:
            raise ValueError(f"jwt_algorithm must be one of: {allowed}")
        return v

    @field_validator("app_log_level")
    @classmethod
    def validate_log_level(cls, v):
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"app_log_level must be one of: {allowed}")
        return v.upper()


@lru_cache()
def get_settings() -> Settings:
    """取得設定實例 (單例)"""
    return Settings()
```

### 7-C. Secrets 管理

#### 開發環境
- 使用 `.env` 檔案 (已加入 `.gitignore`)
- 提供 `.env.example` 作為範本

#### Staging / Production 環境
- 推薦使用雲端密鑰管理服務:
  - AWS Secrets Manager
  - Google Cloud Secret Manager
  - HashiCorp Vault
- 環境變數透過容器編排工具 (Docker Compose / Kubernetes) 注入
- 敏感資料 (API keys, DB passwords) 不得存入版本控制

#### 敏感變數清單 (必須使用密鑰管理):

| 變數名稱 | 說明 | 敏感等級 |
|---|---|---|
| `APP_SECRET_KEY` | 應用程式主密鑰 | 最高 |
| `JWT_PRIVATE_KEY_PATH` | JWT RSA 私鑰路徑 | 最高 |
| `DB_PASSWORD` | 資料庫密碼 | 最高 |
| `REDIS_PASSWORD` | Redis 密碼 | 高 |
| `ANTHROPIC_API_KEY` | Claude API 金鑰 | 最高 |
| `AWS_ACCESS_KEY_ID` | S3 存取金鑰 ID | 高 |
| `AWS_SECRET_ACCESS_KEY` | S3 存取金鑰密碼 | 最高 |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP 服務帳號金鑰路徑 | 最高 |
| `FCM_CREDENTIALS_PATH` | Firebase 服務帳號金鑰路徑 | 高 |
| `SENTRY_DSN` | Sentry DSN | 中 |

---

## 附錄 A: 資料庫 Schema (PostgreSQL DDL 概要)

```sql
-- 使用擴充
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Enum 型別
CREATE TYPE user_role AS ENUM ('patient', 'doctor', 'admin');
CREATE TYPE session_status AS ENUM ('waiting', 'in_progress', 'completed', 'aborted_red_flag', 'cancelled');
CREATE TYPE conversation_role AS ENUM ('patient', 'assistant', 'system');
CREATE TYPE alert_severity AS ENUM ('critical', 'high', 'medium');
CREATE TYPE alert_type AS ENUM ('rule_based', 'semantic', 'combined');
CREATE TYPE report_status AS ENUM ('generating', 'generated', 'failed');
CREATE TYPE review_status AS ENUM ('pending', 'approved', 'revision_needed');
CREATE TYPE notification_type AS ENUM ('red_flag', 'session_complete', 'report_ready', 'system');
CREATE TYPE audit_action AS ENUM ('create', 'read', 'update', 'delete', 'login', 'logout', 'export', 'review', 'acknowledge', 'session_start', 'session_end');
CREATE TYPE device_platform AS ENUM ('ios', 'android', 'web');
CREATE TYPE gender_type AS ENUM ('male', 'female', 'other');

-- 使用者
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    role user_role NOT NULL,
    phone VARCHAR(20),
    department VARCHAR(100),
    license_number VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_doctor_license CHECK (
        role != 'doctor' OR license_number IS NOT NULL
    )
);
CREATE INDEX idx_users_role ON users(role);

-- 病患
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    medical_record_number VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    gender gender_type NOT NULL,
    date_of_birth DATE NOT NULL,
    phone VARCHAR(20),
    emergency_contact JSONB,
    medical_history JSONB,
    allergies JSONB,
    current_medications JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_patients_user ON patients(user_id);

-- 主訴
CREATE TABLE chief_complaints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    description TEXT,
    category VARCHAR(100) NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    created_by UUID REFERENCES users(id),
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_complaints_category ON chief_complaints(category);
CREATE INDEX idx_complaints_active ON chief_complaints(is_active);

-- 問診場次
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id UUID NOT NULL REFERENCES patients(id),
    doctor_id UUID REFERENCES users(id),
    chief_complaint_id UUID NOT NULL REFERENCES chief_complaints(id),
    chief_complaint_text VARCHAR(200),
    status session_status NOT NULL DEFAULT 'waiting',
    red_flag BOOLEAN NOT NULL DEFAULT FALSE,
    red_flag_reason TEXT,
    language VARCHAR(10) NOT NULL DEFAULT 'zh-TW',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sessions_patient ON sessions(patient_id);
CREATE INDEX idx_sessions_doctor ON sessions(doctor_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_created ON sessions(created_at);

-- 對話 (單層扁平結構，按月分區)
CREATE TABLE conversations (
    id UUID DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    sequence_number INT NOT NULL,
    role conversation_role NOT NULL,
    content_text TEXT NOT NULL,
    audio_url VARCHAR(500),
    audio_duration_seconds NUMERIC(8,2),
    stt_confidence NUMERIC(5,4),
    red_flag_detected BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 建立每月分區 (範例)
CREATE TABLE conversations_2026_04 PARTITION OF conversations
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE conversations_2026_05 PARTITION OF conversations
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE UNIQUE INDEX idx_conv_session_seq ON conversations(session_id, sequence_number);

-- 紅旗規則
CREATE TABLE red_flag_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,
    keywords TEXT[] NOT NULL,
    regex_pattern TEXT,
    severity alert_severity NOT NULL,
    suspected_diagnosis VARCHAR(200),
    suggested_action TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 紅旗警示
CREATE TABLE red_flag_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    conversation_id UUID NOT NULL,  -- 不設 FK（conversations 為分區表）
    alert_type alert_type NOT NULL,
    severity alert_severity NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    trigger_reason TEXT NOT NULL,
    trigger_keywords TEXT[],
    matched_rule_id UUID REFERENCES red_flag_rules(id),
    llm_analysis JSONB,
    suggested_actions TEXT[],
    acknowledged_by UUID REFERENCES users(id),
    acknowledged_at TIMESTAMPTZ,
    acknowledge_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_alerts_session ON red_flag_alerts(session_id);
CREATE INDEX idx_alerts_severity ON red_flag_alerts(severity);
CREATE INDEX idx_alerts_created ON red_flag_alerts(created_at);

-- SOAP 報告
CREATE TABLE soap_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID UNIQUE NOT NULL REFERENCES sessions(id),
    status report_status NOT NULL DEFAULT 'generating',
    review_status review_status NOT NULL DEFAULT 'pending',
    subjective JSONB,
    objective JSONB,
    assessment JSONB,
    plan JSONB,
    raw_transcript TEXT,
    summary TEXT,
    icd10_codes TEXT[],
    ai_confidence_score NUMERIC(3,2),
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    review_notes TEXT,
    generated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_reports_status ON soap_reports(status);
CREATE INDEX idx_reports_review_status ON soap_reports(review_status);

-- 通知
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    type notification_type NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT,
    data JSONB DEFAULT '{}',
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_notifications_user_read ON notifications(user_id, is_read);
CREATE INDEX idx_notifications_created ON notifications(created_at);

-- FCM 推播裝置
CREATE TABLE fcm_devices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    device_token VARCHAR(500) NOT NULL,
    platform device_platform NOT NULL,
    device_name VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_fcm_devices_user ON fcm_devices(user_id);
CREATE UNIQUE INDEX idx_fcm_devices_token ON fcm_devices(device_token) WHERE is_active = TRUE;

-- 音訊檔案
CREATE TABLE audio_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    conversation_id UUID,
    file_type VARCHAR(30) NOT NULL CHECK (file_type IN ('patient_input', 'ai_response')),
    s3_bucket VARCHAR(200) NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    duration_seconds FLOAT,
    mime_type VARCHAR(50),
    sample_rate INT,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    retention_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audio_session ON audio_files(session_id);
CREATE INDEX idx_audio_retention ON audio_files(retention_expires_at) WHERE is_deleted = FALSE;

-- 稽核日誌 (分區表, BIGINT 自增 ID)
CREATE TABLE audit_logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    user_id UUID,
    action audit_action NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(100),
    details JSONB DEFAULT '{}',
    ip_address INET,
    user_agent VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 建立每月分區 (範例)
CREATE TABLE audit_logs_2026_04 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE audit_logs_2026_05 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
```

---

## 附錄 B: Redis Key 命名規範

統一前綴：`gu:`

| Key Pattern | 型別 | TTL | 說明 |
|-------------|------|-----|------|
| `gu:session:{id}:context` | Hash | 3600s (1hr) | 活躍對話的 LLM 上下文 |
| `gu:session:{id}:state` | Hash | 1800s (30min) | 場次狀態快取 |
| `gu:user:{id}:profile` | Hash | 3600s (1hr) | 使用者資料快取 |
| `gu:dashboard:stats:{doctor_id}` | String(JSON) | 300s (5min) | 儀表板統計快取 |
| `gu:alert:active:{doctor_id}` | Sorted Set | 無 TTL | 進行中紅旗警示 |
| `gu:queue:patients` | Sorted Set | 無 TTL | 病患等候佇列 |
| `gu:token_blacklist:{jti}` | String | 等同 token 剩餘效期 | Access token 黑名單 |
| `gu:refresh_token:{jti}` | String | 604800s (7d) | Refresh token 管理 |
| `gu:complaints:defaults` | String(JSON) | 3600s (1hr) | 預設主訴清單快取 |
| `gu:notifications:unread:{user_id}` | String(int) | 300s (5min) | 未讀通知計數快取 |
| `gu:ws_reconnect_wait:{session_id}` | String | 300s | WS 重連等待 |
| `gu:rate_limit:{user_id}:{window}` | String (counter) | 60s | 速率限制計數 |
| `gu:report_generation_queue` | List | 無 | 報告產生任務佇列 |
| `gu:notification_retry_queue` | List | 無 | 通知重試佇列 |
| `gu:report_retry:{session_id}` | String (counter) | 3600s | 報告重試計數 |
| `gu:red_flag_rules_version` | String | 無 | 規則版本號 (Pub/Sub 用) |

---

## 附錄 C: 依賴套件清單 (requirements.txt)

```
# Web Framework
fastapi==0.111.0
uvicorn[standard]==0.30.1
python-multipart==0.0.9

# Database
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
alembic==1.13.1

# Redis
redis[hiredis]==5.0.4

# Authentication (RS256)
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
cryptography==42.0.7

# Validation / Settings
pydantic==2.7.1
pydantic-settings==2.3.0
email-validator==2.1.1

# AI / ML
anthropic==0.28.0
google-cloud-speech==2.26.0
google-cloud-texttospeech==2.16.3

# Firebase
firebase-admin==6.5.0

# AWS S3
boto3==1.34.100
botocore==1.34.100

# Background Tasks
apscheduler==3.10.4

# Audio Processing
pydub==0.25.1

# String Matching
ahocorasick==2.0.0

# PDF Generation
weasyprint==62.1
jinja2==3.1.4

# HTTP Client
httpx==0.27.0

# Logging
structlog==24.2.0

# Monitoring (optional)
sentry-sdk[fastapi]==2.5.1

# Utilities
python-dateutil==2.9.0
orjson==3.10.3
```

```
# requirements-dev.txt

-r requirements.txt

# Testing
pytest==8.2.1
pytest-asyncio==0.23.7
pytest-cov==5.0.0
httpx==0.27.0
fakeredis[lua]==2.23.2
factory-boy==3.3.0

# Code Quality
ruff==0.4.4
mypy==1.10.0
black==24.4.2

# Development
ipython==8.24.0
pre-commit==3.7.1
```
