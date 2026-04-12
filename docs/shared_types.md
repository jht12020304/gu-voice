# 泌尿科 AI 語音問診助手 — 共用型別定義 (Single Source of Truth)

> **本文件為所有規格書的唯一權威定義。**
> 當其他規格書（frontend_spec / backend_spec / api_spec / database_spec / infrastructure_spec）
> 與本文件產生衝突時，以本文件為準。

---

## 1. 設計決策摘要

以下為針對交叉比對發現的所有衝突，所做出的統一設計決策：

| 衝突項目 | 統一決策 | 理由 |
|---------|---------|------|
| 登入欄位 | `email` | 醫療系統需要穩定識別，email 較手機號碼不易變動 |
| 前端框架 | React Native (mobile) + React (web) | 生態系成熟，音訊串流支援好 |
| 後端框架 | Python FastAPI | AI/ML 生態系優勢 |
| LLM | OpenAI API | GPT-4o 用於對話與 SOAP 生成，GPT-4o-mini 用於紅旗偵測 |
| STT | Google Cloud STT v2 (Chirp) | 串流支援 + 繁中醫療術語加權 |
| TTS | Google Cloud TTS Neural2 | `cmn-TW-Wavenet-A`，繁中最佳 |
| 資料庫 | PostgreSQL 15+ | JSONB + 分區 |
| 快取 | Redis 7+ | 對話上下文 + 即時狀態 |
| Session 初始狀態 | `waiting` | 語意更清晰 |
| Session-主訴關聯 | 單一外鍵 + 文字欄位 | MVP 階段一個場次聚焦一個主訴 |
| 對話紀錄表結構 | 單層扁平 `conversations` | 簡單直覺，一行一輪 |
| SOAP 四段欄位型別 | JSONB 結構化 | 支援欄位級查詢、前端結構化渲染 |
| ConversationRole | `patient`, `assistant`, `system` | `assistant` 對 LLM 對話角色語意明確 |
| JWT 演算法 | RS256 | 非對稱加密，支援 key rotation |
| 分頁方式 | Cursor-based | 效能穩定，適合即時資料流 |
| 專案目錄 | `app/` | Python 慣例 |
| WebSocket 訊息格式 | 包裝結構 `{type, id, timestamp, payload}` | 結構統一、可擴展 |
| AlertSeverity | 3 級: `critical`, `high`, `medium` | 醫療急診不需要 `low` 級別 |
| 角色 | 3 種: `patient`, `doctor`, `admin` | MVP 精簡 |
| PII 加密 | 欄位級加密 (pgcrypto) | 醫療合規要求 |
| Access Token 有效期 | 15 分鐘 | 醫療系統安全要求 |
| TTS Voice | `cmn-TW-Wavenet-A` | 品質優先 |
| TTS Sample Rate | 24000 Hz | Wavenet 最佳品質 |

---

## 2. Enum 型別定義

### 2.1 UserRole

```typescript
// TypeScript (前端)
type UserRole = 'patient' | 'doctor' | 'admin';
```

```python
# Python (後端)
class UserRole(str, Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"
```

```sql
-- PostgreSQL
CREATE TYPE user_role AS ENUM ('patient', 'doctor', 'admin');
```

---

### 2.2 SessionStatus

```typescript
type SessionStatus =
  | 'waiting'           // 等待中 — 場次已建立，等待開始
  | 'in_progress'       // 進行中 — 語音對話進行中
  | 'completed'         // 已完成 — 對話正常結束
  | 'aborted_red_flag'  // 紅旗中止 — 偵測到急性症狀，對話被強制中斷
  | 'cancelled';        // 已取消 — 手動取消或超時取消
```

```python
class SessionStatus(str, Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED_RED_FLAG = "aborted_red_flag"
    CANCELLED = "cancelled"
```

```sql
CREATE TYPE session_status AS ENUM (
    'waiting', 'in_progress', 'completed', 'aborted_red_flag', 'cancelled'
);
```

**狀態轉移圖：**

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

**合法狀態轉移：**

| 起始狀態 | 可轉移至 |
|---------|---------|
| `waiting` | `in_progress`, `cancelled` |
| `in_progress` | `completed`, `aborted_red_flag`, `cancelled` |
| `completed` | (終態) |
| `aborted_red_flag` | (終態) |
| `cancelled` | (終態) |

---

### 2.3 ConversationRole

```typescript
type ConversationRole = 'patient' | 'assistant' | 'system';
```

```python
class ConversationRole(str, Enum):
    PATIENT = "patient"
    ASSISTANT = "assistant"
    SYSTEM = "system"
```

```sql
CREATE TYPE conversation_role AS ENUM ('patient', 'assistant', 'system');
```

| 角色 | 說明 |
|------|------|
| `patient` | 病患的語音/文字輸入 |
| `assistant` | AI 助手的回覆（LLM 生成） |
| `system` | 系統訊息（紅旗警示、場次狀態變更等） |

---

### 2.4 AlertSeverity

```typescript
type AlertSeverity = 'critical' | 'high' | 'medium';
```

```python
class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
```

```sql
CREATE TYPE alert_severity AS ENUM ('critical', 'high', 'medium');
```

| 等級 | 說明 | 處置 |
|------|------|------|
| `critical` | 立即危及生命 | 中斷對話 + 即時推播 + 彈窗強制確認 |
| `high` | 需緊急處理 | 中斷對話 + 推播通知 |
| `medium` | 需注意但非急性 | 標記警示，不中斷對話 |

---

### 2.5 AlertType

```typescript
type AlertType = 'rule_based' | 'semantic' | 'combined';
```

```python
class AlertType(str, Enum):
    RULE_BASED = "rule_based"
    SEMANTIC = "semantic"
    COMBINED = "combined"
```

```sql
CREATE TYPE alert_type AS ENUM ('rule_based', 'semantic', 'combined');
```

---

### 2.6 ReportStatus

```typescript
type ReportStatus = 'generating' | 'generated' | 'failed';
```

```python
class ReportStatus(str, Enum):
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"
```

```sql
CREATE TYPE report_status AS ENUM ('generating', 'generated', 'failed');
```

---

### 2.7 ReviewStatus

```typescript
type ReviewStatus = 'pending' | 'approved' | 'revision_needed';
```

```python
class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REVISION_NEEDED = "revision_needed"
```

```sql
CREATE TYPE review_status AS ENUM ('pending', 'approved', 'revision_needed');
```

---

### 2.8 NotificationType

```typescript
type NotificationType = 'red_flag' | 'session_complete' | 'report_ready' | 'system';
```

```python
class NotificationType(str, Enum):
    RED_FLAG = "red_flag"
    SESSION_COMPLETE = "session_complete"
    REPORT_READY = "report_ready"
    SYSTEM = "system"
```

```sql
CREATE TYPE notification_type AS ENUM ('red_flag', 'session_complete', 'report_ready', 'system');
```

---

### 2.9 AuditAction

```typescript
type AuditAction =
  | 'create' | 'read' | 'update' | 'delete'
  | 'login' | 'logout'
  | 'export' | 'review' | 'acknowledge'
  | 'session_start' | 'session_end';
```

```python
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
```

```sql
CREATE TYPE audit_action AS ENUM (
    'create', 'read', 'update', 'delete',
    'login', 'logout', 'export', 'review', 'acknowledge',
    'session_start', 'session_end'
);
```

---

### 2.10 DevicePlatform

```typescript
type DevicePlatform = 'ios' | 'android' | 'web';
```

```python
class DevicePlatform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"
```

```sql
CREATE TYPE device_platform AS ENUM ('ios', 'android', 'web');
```

---

### 2.11 Gender

```typescript
type Gender = 'male' | 'female' | 'other';
```

```python
class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
```

```sql
CREATE TYPE gender_type AS ENUM ('male', 'female', 'other');
```

---

## 3. 核心資料模型

### 3.1 User (使用者)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `email` | VARCHAR(255) | YES | 唯一，登入帳號 |
| `password_hash` | VARCHAR(255) | YES | bcrypt 雜湊 |
| `name` | VARCHAR(100) | YES | 姓名 |
| `role` | user_role | YES | 角色 |
| `phone` | VARCHAR(20) | NO | 手機號碼 |
| `department` | VARCHAR(100) | NO | 科別（醫師用） |
| `license_number` | VARCHAR(50) | NO | 醫師執照號碼 |
| `is_active` | BOOLEAN | YES | 帳號啟用狀態，預設 true |
| `last_login_at` | TIMESTAMPTZ | NO | 最後登入時間 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |
| `updated_at` | TIMESTAMPTZ | YES | 更新時間 |

**約束：** 當 `role = 'doctor'` 時，`license_number` 不得為 NULL。

---

### 3.2 Patient (病患)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `user_id` | UUID FK -> users | YES | 關聯使用者帳號 |
| `medical_record_number` | VARCHAR(50) | YES | 病歷號碼，唯一 |
| `name` | VARCHAR(100) | YES | 姓名 |
| `gender` | gender_type | YES | 性別 |
| `date_of_birth` | DATE | YES | 出生日期 |
| `phone` | VARCHAR(20) | NO | 手機號碼 |
| `emergency_contact` | JSONB | NO | 緊急聯絡人 `{name, relationship, phone}` |
| `medical_history` | JSONB | NO | 過去病史 |
| `allergies` | JSONB | NO | 過敏史 |
| `current_medications` | JSONB | NO | 目前用藥 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |
| `updated_at` | TIMESTAMPTZ | YES | 更新時間 |

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

---

### 3.3 ChiefComplaint (主訴)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `name` | VARCHAR(100) | YES | 主訴名稱（中文） |
| `name_en` | VARCHAR(100) | NO | 主訴名稱（英文） |
| `description` | TEXT | NO | 詳細描述 |
| `category` | VARCHAR(100) | YES | 分類名稱 |
| `is_default` | BOOLEAN | YES | 是否為系統預設，預設 false |
| `is_active` | BOOLEAN | YES | 是否啟用，預設 true |
| `display_order` | INTEGER | YES | 顯示排序，預設 0 |
| `created_by` | UUID FK -> users | NO | 自訂主訴的建立者（NULL 表示系統預設） |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |
| `updated_at` | TIMESTAMPTZ | YES | 更新時間 |

**預設分類：**
- 排尿症狀
- 血尿與異常
- 疼痛
- 腫塊與外觀
- 性功能障礙
- 其他

---

### 3.4 Session (問診場次)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `patient_id` | UUID FK -> patients | YES | 病患 |
| `doctor_id` | UUID FK -> users | NO | 負責醫師（可稍後指派） |
| `chief_complaint_id` | UUID FK -> chief_complaints | YES | 主訴 |
| `chief_complaint_text` | VARCHAR(200) | NO | 主訴文字（自訂主訴時使用） |
| `status` | session_status | YES | 場次狀態，預設 `waiting` |
| `red_flag` | BOOLEAN | YES | 是否觸發紅旗，預設 false |
| `red_flag_reason` | TEXT | NO | 紅旗原因 |
| `language` | VARCHAR(10) | YES | 對話語言，預設 `zh-TW` |
| `started_at` | TIMESTAMPTZ | NO | 開始時間 |
| `completed_at` | TIMESTAMPTZ | NO | 結束時間 |
| `duration_seconds` | INTEGER | NO | 對話持續秒數 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |
| `updated_at` | TIMESTAMPTZ | YES | 更新時間 |

---

### 3.5 Conversation (對話紀錄)

> **設計決策：單層扁平結構，一行一輪對話。**

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `session_id` | UUID FK -> sessions | YES | 所屬場次 |
| `sequence_number` | INTEGER | YES | 對話序號（場次內遞增） |
| `role` | conversation_role | YES | 角色 |
| `content_text` | TEXT | YES | 文字內容 |
| `audio_url` | VARCHAR(500) | NO | 語音檔案 URL |
| `audio_duration_seconds` | NUMERIC(8,2) | NO | 語音長度（秒） |
| `stt_confidence` | NUMERIC(5,4) | NO | STT 信心分數 0~1 |
| `red_flag_detected` | BOOLEAN | YES | 本輪是否偵測到紅旗，預設 false |
| `metadata` | JSONB | NO | 擴充欄位 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |

**metadata JSONB 結構：**

```jsonc
{
  "stt_engine": "google-chirp-v2",
  "stt_language": "zh-TW",
  "llm_model": "gpt-4o",
  "llm_tokens_used": 256,
  "tts_engine": "google-neural2",
  "tts_voice": "cmn-TW-Wavenet-A",
  "audio_format": "wav",
  "audio_sample_rate": 16000
}
```

**分區策略：** 按月 Range Partition（以 `created_at` 為分區鍵）。

**唯一約束：** `UNIQUE (session_id, sequence_number)`

---

### 3.6 SOAPReport (SOAP 報告)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `session_id` | UUID FK -> sessions | YES | 所屬場次（唯一） |
| `status` | report_status | YES | 報告狀態，預設 `generating` |
| `review_status` | review_status | YES | 審閱狀態，預設 `pending` |
| `subjective` | JSONB | NO | S 主觀 |
| `objective` | JSONB | NO | O 客觀 |
| `assessment` | JSONB | NO | A 評估 |
| `plan` | JSONB | NO | P 計畫 |
| `raw_transcript` | TEXT | NO | 完整對話逐字稿 |
| `summary` | TEXT | NO | 摘要 |
| `icd10_codes` | TEXT[] | NO | ICD-10 診斷碼 |
| `ai_confidence_score` | NUMERIC(3,2) | NO | AI 信心分數 0~1 |
| `reviewed_by` | UUID FK -> users | NO | 審閱醫師 |
| `reviewed_at` | TIMESTAMPTZ | NO | 審閱時間 |
| `review_notes` | TEXT | NO | 審閱備註 |
| `generated_at` | TIMESTAMPTZ | NO | 報告產生時間 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |
| `updated_at` | TIMESTAMPTZ | YES | 更新時間 |

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
      "urgency": "routine"    // "urgent" | "routine" | "elective"
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

---

### 3.7 RedFlagAlert (紅旗警示)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `session_id` | UUID FK -> sessions | YES | 所屬場次 |
| `conversation_id` | UUID | YES | 觸發的對話訊息 ID（不設外鍵約束，因 conversations 為分區表） |
| `alert_type` | alert_type | YES | 偵測方式 |
| `severity` | alert_severity | YES | 嚴重度 |
| `title` | VARCHAR(200) | YES | 警示標題 |
| `description` | TEXT | NO | 警示描述 |
| `trigger_reason` | TEXT | YES | 觸發原因 |
| `trigger_keywords` | TEXT[] | NO | 觸發的關鍵字 |
| `matched_rule_id` | UUID FK -> red_flag_rules | NO | 匹配的規則（規則觸發時） |
| `llm_analysis` | JSONB | NO | LLM 語意分析結果 |
| `suggested_actions` | TEXT[] | NO | 建議處置 |
| `acknowledged_by` | UUID FK -> users | NO | 確認醫師 |
| `acknowledged_at` | TIMESTAMPTZ | NO | 確認時間 |
| `acknowledge_notes` | TEXT | NO | 確認備註 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |

**注意：** `conversation_id` 不使用外鍵約束，因為 `conversations` 表為分區表，PostgreSQL 不支援外鍵引用分區表的非主鍵欄位。改以應用層保證參照完整性。

---

### 3.8 RedFlagRule (紅旗規則)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `name` | VARCHAR(200) | YES | 規則名稱 |
| `description` | TEXT | NO | 規則描述 |
| `category` | VARCHAR(100) | YES | 分類 |
| `keywords` | TEXT[] | YES | 觸發關鍵字陣列 |
| `regex_pattern` | TEXT | NO | 正則表達式（可選） |
| `severity` | alert_severity | YES | 嚴重度 |
| `suspected_diagnosis` | VARCHAR(200) | NO | 疑似診斷 |
| `suggested_action` | TEXT | NO | 建議處置 |
| `is_active` | BOOLEAN | YES | 是否啟用，預設 true |
| `created_by` | UUID FK -> users | NO | 建立者 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |
| `updated_at` | TIMESTAMPTZ | YES | 更新時間 |

---

### 3.9 Notification (通知)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `user_id` | UUID FK -> users | YES | 通知對象 |
| `type` | notification_type | YES | 通知類型 |
| `title` | VARCHAR(200) | YES | 通知標題 |
| `body` | TEXT | NO | 通知內容 |
| `data` | JSONB | NO | 附加資料（Deep Link 等） |
| `is_read` | BOOLEAN | YES | 是否已讀，預設 false |
| `read_at` | TIMESTAMPTZ | NO | 已讀時間 |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |

---

### 3.10 AuditLog (稽核日誌)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | BIGINT GENERATED ALWAYS AS IDENTITY | YES | 主鍵（自增） |
| `user_id` | UUID FK -> users | NO | 操作者（系統操作時為 NULL） |
| `action` | audit_action | YES | 操作類型 |
| `resource_type` | VARCHAR(50) | YES | 資源類型 |
| `resource_id` | VARCHAR(100) | NO | 資源 ID |
| `details` | JSONB | NO | 操作詳情 |
| `ip_address` | INET | NO | IP 位址 |
| `user_agent` | VARCHAR(500) | NO | User Agent |
| `created_at` | TIMESTAMPTZ | YES | 操作時間 |

**分區策略：** 按月 Range Partition（以 `created_at` 為分區鍵）。
**權限：** 僅 INSERT，禁止 UPDATE / DELETE。

---

### 3.11 FCMDevice (推播裝置)

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `id` | UUID | YES | 主鍵 |
| `user_id` | UUID FK -> users | YES | 使用者 |
| `device_token` | VARCHAR(500) | YES | FCM Token |
| `platform` | device_platform | YES | 裝置平台 |
| `device_name` | VARCHAR(200) | NO | 裝置名稱 |
| `is_active` | BOOLEAN | YES | 是否有效，預設 true |
| `created_at` | TIMESTAMPTZ | YES | 建立時間 |
| `updated_at` | TIMESTAMPTZ | YES | 更新時間 |

---

## 4. WebSocket 訊息格式

### 4.1 通用訊息信封

所有 WebSocket 訊息使用統一包裝格式：

```typescript
interface WSMessage {
  type: string;           // 訊息類型
  id: string;             // 訊息唯一 ID (UUID)
  timestamp: string;      // ISO 8601 時間戳
  payload: object;        // 訊息內容
}
```

---

### 4.2 語音對話 WebSocket (`/api/v1/ws/sessions/{id}/stream`)

**連線方式：** `wss://{host}/api/v1/ws/sessions/{id}/stream?token={access_token}`

#### Client -> Server 訊息

| type | payload | 說明 |
|------|---------|------|
| `audio_chunk` | `{audio_data: string(base64), chunk_index: int, is_final: bool, format: "wav", sample_rate: 16000}` | 音訊片段 |
| `text_message` | `{text: string}` | 文字訊息（非語音備用） |
| `control` | `{action: "end_session" \| "pause_recording" \| "resume_recording"}` | 控制指令 |
| `ping` | `{}` | 心跳（每 30 秒） |

#### Server -> Client 訊息

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

---

### 4.3 醫師儀表板 WebSocket (`/api/v1/ws/dashboard`)

**連線方式：** `wss://{host}/api/v1/ws/dashboard?token={access_token}`

#### Server -> Client 事件

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

## 5. API 通用規範

### 5.1 認證

- **方式：** JWT Bearer Token (RS256)
- **Access Token 有效期：** 15 分鐘
- **Refresh Token 有效期：** 7 天
- **Header：** `Authorization: Bearer {access_token}`

### 5.2 分頁

所有列表 API 使用 Cursor-based Pagination：

```typescript
// Request Query Parameters
interface PaginationParams {
  cursor?: string;    // 上一頁最後一筆的 cursor
  limit?: number;     // 每頁筆數，預設 20，最大 100
}

// Response Wrapper
interface PaginatedResponse<T> {
  data: T[];
  pagination: {
    next_cursor: string | null;
    has_more: boolean;
    limit: number;
    total_count: number;      // 近似值
  };
}
```

### 5.3 錯誤回應格式

```typescript
interface ErrorResponse {
  error: {
    code: string;           // 錯誤碼（如 "UNAUTHORIZED"）
    message: string;        // 人類可讀訊息
    details?: object;       // 詳細錯誤資訊
    request_id: string;     // 請求追蹤 ID
    timestamp: string;      // ISO 8601
  };
}
```

### 5.4 錯誤碼對照表

| 錯誤碼 | HTTP Status | 說明 |
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

### 5.5 欄位命名慣例

| 層級 | 慣例 | 範例 |
|------|------|------|
| PostgreSQL | snake_case | `chief_complaint_id`, `created_at` |
| Python (Pydantic/SQLAlchemy) | snake_case | `chief_complaint_id`, `created_at` |
| API JSON | snake_case | `chief_complaint_id`, `created_at` |
| TypeScript (前端) | camelCase | `chiefComplaintId`, `createdAt` |

**前端轉換：** 在 API Client 層（Axios interceptor）統一做 snake_case <-> camelCase 自動轉換。

---

## 6. Redis Key 命名規範

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

---

## 7. 環境變數統一定義

### 7.1 應用程式

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `APP_ENV` | string | `development` | 環境 (development/staging/production) |
| `APP_HOST` | string | `0.0.0.0` | 監聽地址 |
| `APP_PORT` | int | `8000` | REST API 埠 |
| `APP_WORKERS` | int | `4` | Uvicorn worker 數量 |
| `APP_LOG_LEVEL` | string | `info` | 日誌等級 |
| `APP_SECRET_KEY` | string | (required) | 應用程式主密鑰 |

### 7.2 資料庫

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `DB_HOST` | string | `localhost` | 資料庫主機 |
| `DB_PORT` | int | `5432` | 資料庫埠 |
| `DB_NAME` | string | `gu_voice` | 資料庫名稱 |
| `DB_USER` | string | `gu_app` | 資料庫使用者 |
| `DB_PASSWORD` | string | (required) | 資料庫密碼 |
| `DB_POOL_SIZE` | int | `10` | 連線池大小 |
| `DB_MAX_OVERFLOW` | int | `20` | 連線池溢出上限 |

### 7.3 Redis

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `REDIS_HOST` | string | `localhost` | Redis 主機 |
| `REDIS_PORT` | int | `6379` | Redis 埠 |
| `REDIS_PASSWORD` | string | (optional) | Redis 密碼 |
| `REDIS_DB` | int | `0` | Redis 資料庫編號 |
| `REDIS_KEY_PREFIX` | string | `gu:` | Key 前綴 |

### 7.4 認證

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `JWT_ALGORITHM` | string | `RS256` | JWT 演算法 |
| `JWT_PRIVATE_KEY_PATH` | string | (required) | RSA 私鑰路徑 |
| `JWT_PUBLIC_KEY_PATH` | string | (required) | RSA 公鑰路徑 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `15` | Access Token 有效期 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | int | `7` | Refresh Token 有效期 |

### 7.5 OpenAI API

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `OPENAI_API_KEY` | string | (required) | OpenAI API Key |
| `OPENAI_MODEL_CONVERSATION` | string | `gpt-4o` | 對話用模型 |
| `OPENAI_MODEL_SOAP` | string | `gpt-4o` | SOAP 生成用模型 |
| `OPENAI_MODEL_RED_FLAG` | string | `gpt-4o-mini` | 紅旗偵測用模型 |
| `OPENAI_TEMPERATURE_CONVERSATION` | float | `0.7` | 對話 temperature |
| `OPENAI_TEMPERATURE_SOAP` | float | `0.3` | SOAP temperature |
| `OPENAI_TEMPERATURE_RED_FLAG` | float | `0.2` | 紅旗 temperature |
| `OPENAI_MAX_TOKENS_CONVERSATION` | int | `512` | 對話 max tokens |
| `OPENAI_MAX_TOKENS_SOAP` | int | `4096` | SOAP max tokens |

### 7.6 Google Cloud STT

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `GOOGLE_CLOUD_PROJECT_ID` | string | (required) | GCP 專案 ID |
| `GOOGLE_STT_LANGUAGE_CODE` | string | `zh-TW` | STT 語言 |
| `GOOGLE_STT_MODEL` | string | `chirp_2` | STT 模型 |
| `GOOGLE_STT_SAMPLE_RATE` | int | `16000` | 音訊取樣率 |

### 7.7 Google Cloud TTS

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `GOOGLE_TTS_VOICE_NAME` | string | `cmn-TW-Wavenet-A` | TTS 語音 |
| `GOOGLE_TTS_SPEAKING_RATE` | float | `0.9` | 語速 |
| `GOOGLE_TTS_SAMPLE_RATE` | int | `24000` | TTS 取樣率 |

### 7.8 S3 / Object Storage

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `S3_BUCKET` | string | (required) | S3 Bucket 名稱 |
| `S3_REGION` | string | `ap-northeast-1` | S3 區域 |
| `AWS_ACCESS_KEY_ID` | string | (required) | AWS Access Key |
| `AWS_SECRET_ACCESS_KEY` | string | (required) | AWS Secret Key |
| `AUDIO_RETENTION_DAYS` | int | `1095` | 音訊保留天數（3 年） |

### 7.9 Firebase Cloud Messaging

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `FCM_CREDENTIALS_PATH` | string | (required) | Firebase 服務帳號 JSON 路徑 |
| `FCM_PROJECT_ID` | string | (required) | Firebase 專案 ID |

### 7.10 監控

| 變數名 | 型別 | 預設值 | 說明 |
|--------|------|--------|------|
| `SENTRY_DSN` | string | (optional) | Sentry DSN |
| `PROMETHEUS_PORT` | int | `9090` | Prometheus metrics 埠 |

---

## 8. 後端專案目錄結構（統一）

```
app/
  __init__.py
  main.py                       # FastAPI 入口
  core/
    config.py                   # pydantic-settings 配置
    security.py                 # JWT、密碼雜湊
    dependencies.py             # 共用依賴注入
    middleware.py               # CORS、audit logging、error handling
    exceptions.py               # 自定義例外類別
  models/
    __init__.py
    user.py                     # User SQLAlchemy model
    patient.py                  # Patient model
    session.py                  # Session model
    conversation.py             # Conversation model
    chief_complaint.py          # ChiefComplaint model
    soap_report.py              # SOAPReport model
    red_flag_alert.py           # RedFlagAlert model
    red_flag_rule.py            # RedFlagRule model
    notification.py             # Notification model
    audit_log.py                # AuditLog model
    fcm_device.py               # FCMDevice model
  schemas/
    __init__.py
    common.py                   # 分頁、錯誤回應等共用 schema
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
    llm_conversation.py         # OpenAI GPT-4o 對話引擎
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

---

## 9. 前端專案目錄結構（統一）

```
src/
  navigation/
    RootNavigator.tsx           # 根導航（Auth / Patient / Doctor）
    AuthNavigator.tsx           # 認證導航
    PatientNavigator.tsx        # 病患端導航
    DoctorNavigator.tsx         # 醫師端導航
    linking.ts                  # Deep Link 設定
  screens/
    auth/                       # Login, Register, ForgotPassword
    patient/                    # Home, ComplaintSelect, Conversation, WaitingRoom, History, Settings
    doctor/                     # Dashboard, PatientList, LiveMonitor, SOAPReport, AlertDetail, AlertList, ComplaintManagement, PatientHistory, Settings
    admin/                      # UserManagement, RedFlagRuleManagement, SystemHealth, AuditLogs
  components/
    layout/                     # Header, TabBar, NavigationBar
    form/                       # Input, Button, Select, SearchBar
    medical/                    # ComplaintChip, SOAPCard, StatusBadge, RedFlagBanner
    audio/                      # MicButton, WaveformVisualizer, TTSPlayer
    chat/                       # ChatBubble, ChatList, TranscriptViewer
    dashboard/                  # StatCard, PatientListRow, AlertItem, QueueCard
    common/                     # Modal, Loading, ErrorState, EmptyState
  services/
    api/
      client.ts                 # Axios 實例 + snake/camel 轉換
      auth.ts
      patients.ts
      sessions.ts
      complaints.ts
      reports.ts
      alerts.ts
      dashboard.ts
      notifications.ts
      admin.ts
    websocket.ts                # WebSocket 管理器
    audioStream.ts              # 音訊串流
    notifications.ts            # FCM 處理
  stores/
    authStore.ts                # Zustand: 認證狀態
    conversationStore.ts        # Zustand: 對話狀態
    patientListStore.ts         # Zustand: 病患列表
    alertStore.ts               # Zustand: 紅旗警示
    complaintStore.ts           # Zustand: 主訴管理
    reportStore.ts              # Zustand: SOAP 報告
    notificationStore.ts        # Zustand: 通知
    settingsStore.ts            # Zustand: 設定
  hooks/
    useAudioStream.ts
    useRedFlagAlerts.ts
    useWebSocket.ts
    useAuth.ts
  types/
    index.ts                    # 共用型別（對齊 shared_types.md）
    enums.ts                    # Enum 定義
    api.ts                      # API 請求/回應型別
    websocket.ts                # WebSocket 訊息型別
  utils/
    format.ts
    validation.ts
    date.ts
```

---

## 10. 前端 Enum 與後端的映射

前端使用 camelCase，但 Enum 值本身不做轉換（保持 snake_case），以避免額外映射：

```typescript
// types/enums.ts — 直接使用後端的值
export const SessionStatus = {
  WAITING: 'waiting',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  ABORTED_RED_FLAG: 'aborted_red_flag',
  CANCELLED: 'cancelled',
} as const;

export const ConversationRole = {
  PATIENT: 'patient',
  ASSISTANT: 'assistant',
  SYSTEM: 'system',
} as const;

export const AlertSeverity = {
  CRITICAL: 'critical',
  HIGH: 'high',
  MEDIUM: 'medium',
} as const;

export const ReportStatus = {
  GENERATING: 'generating',
  GENERATED: 'generated',
  FAILED: 'failed',
} as const;

export const ReviewStatus = {
  PENDING: 'pending',
  APPROVED: 'approved',
  REVISION_NEEDED: 'revision_needed',
} as const;
```

**前端 UI 狀態映射：** 前端可定義額外的 UI 顯示狀態（如顏色、圖示），但必須基於後端回傳的 Enum 值衍生，不可自行發明後端不存在的狀態值。

```typescript
// 範例: 將後端狀態映射為 UI 顯示
const statusDisplayMap: Record<string, { label: string; color: string }> = {
  waiting: { label: '等待中', color: 'gray' },
  in_progress: { label: '對話中', color: 'blue' },
  completed: { label: '已完成', color: 'green' },
  aborted_red_flag: { label: '紅旗中止', color: 'red' },
  cancelled: { label: '已取消', color: 'gray' },
};
```
