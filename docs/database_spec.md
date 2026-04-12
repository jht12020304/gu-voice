# 泌尿科 AI 語音問診助手 -- 資料庫規格文件

> **版本**: 1.1.0
> **日期**: 2026-04-10
> **資料庫**: PostgreSQL 15+
> **快取**: Redis 7+
> **ORM**: SQLAlchemy 2.0
> **遷移工具**: Alembic
> **音檔儲存**: S3-compatible Object Storage

> **⚠️ 本文件的型別定義、Enum 值、資料模型以 shared_types.md 為準。**

---

## 目錄

1. [實體關係圖 (ER Diagram)](#1-實體關係圖-er-diagram)
2. [完整資料表定義 (Complete Table Definitions)](#2-完整資料表定義-complete-table-definitions)
3. [索引設計 (Index Design)](#3-索引設計-index-design)
4. [JSONB 欄位結構定義](#4-jsonb-欄位結構定義)
5. [Enum 類型定義](#5-enum-類型定義)
6. [Redis 快取策略 (Redis Cache Strategy)](#6-redis-快取策略-redis-cache-strategy)
7. [資料分割與保留策略 (Partitioning & Retention)](#7-資料分割與保留策略-partitioning--retention)
8. [遷移策略 (Migration Strategy)](#8-遷移策略-migration-strategy)
9. [備份與災難復原 (Backup & Recovery)](#9-備份與災難復原-backup--recovery)

---

## 1. 實體關係圖 (ER Diagram)

以下為系統完整的實體關係圖，以 ASCII 形式呈現。所有外鍵關係均以箭頭表示，
`1` 代表一端，`N` 代表多端。

```
+------------------+          +---------------------+
|     users        |          |     fcm_devices     |
|------------------|          |---------------------|
| PK id (UUID)     |---1---N--| PK id (UUID)        |
| email            |          | FK user_id (UUID)   |
| password_hash    |          | device_token        |
| name             |          | platform            |
| role (enum)      |          | device_name         |
| phone            |          | is_active           |
| department       |          | created_at          |
| license_number   |          | updated_at          |
| is_active        |          +---------------------+
| last_login_at    |
| created_at       |          +---------------------+
| updated_at       |          |   notifications     |
|                  |---1---N--+---------------------|
|                  |          | PK id (UUID)        |
|                  |          | FK user_id (UUID)   |
|                  |          | type (enum)         |
|                  |          | title               |
|                  |          | body                |
|                  |          | data (JSONB)        |
|                  |          | is_read             |
|                  |          | read_at             |
|                  |          | created_at          |
|                  |          +---------------------+
|                  |
|                  |          +---------------------+
|                  |---1---N--| audit_logs          |
|                  |          |---------------------|
|                  |          | PK id (BIGINT)      |
|                  |          | FK user_id (UUID)   |
|                  |          | action (enum)       |
|                  |          | resource_type       |
|                  |          | resource_id         |
|                  |          | details (JSONB)     |
|                  |          | ip_address          |
|                  |          | user_agent          |
|                  |          | created_at          |
|                  |          +---------------------+
+------------------+
        |
        | 1 (user_id)
        |
        N
+------------------+
|    patients      |
|------------------|
| PK id (UUID)     |
| FK user_id (UUID)|--unique
| medical_record_  |
|   number (unique)|
| name             |
| gender           |
| date_of_birth    |
| phone            |
| emergency_contact|
|   (JSONB)        |
| medical_history  |
|   (JSONB)        |
| allergies (JSONB)|
| current_         |
|  medications     |
|   (JSONB)        |
| created_at       |
| updated_at       |
+------------------+
        |
        | 1 (patient_id)
        |
        N
+---------------------------+       +------------------------+
|       sessions            |       |   chief_complaints     |
|---------------------------|       |------------------------|
| PK id (UUID)              |--N--1-| PK id (UUID)           |
| FK patient_id (UUID)      |       | name                   |
| FK doctor_id (UUID) ------+--N--1-+ name_en                |
|   (nullable)              |       | description            |
| FK chief_complaint_id     |       | category               |
|   (UUID)                  |       | is_default             |
| chief_complaint_text      |       | is_active              |
| status (enum)             |       | FK created_by (UUID)   |
| red_flag (BOOLEAN)        |       |   (nullable) ----------+---N--1--- users
| red_flag_reason           |       | display_order          |
| language                  |       | created_at             |
| started_at                |       | updated_at             |
| completed_at              |       +------------------------+
| duration_seconds          |
| created_at                |
| updated_at                |
+---------------------------+
        |                 |
        | 1               | 1 (session_id, unique)
        |                 |
        N                 1
+-------------------+   +---------------------------+
| conversations     |   |      soap_reports         |
|-------------------|   |---------------------------|
| PK id (UUID)      |   | PK id (UUID)              |
| FK session_id     |   | FK session_id (UUID)      |
|   (UUID)          |   |   (unique)                |
| sequence_number   |   | status (report_status)    |
| role (enum)       |   | review_status             |
| content_text      |   |   (review_status)         |
| audio_url         |   | subjective (JSONB)        |
| audio_duration_   |   | objective (JSONB)         |
|   seconds         |   | assessment (JSONB)        |
| stt_confidence    |   | plan (JSONB)              |
| red_flag_detected |   | raw_transcript (TEXT)     |
|   (BOOLEAN)       |   | summary (TEXT)            |
| metadata (JSONB)  |   | icd10_codes (TEXT[])      |
| created_at        |   | ai_confidence_score       |
+-------------------+   | FK reviewed_by (UUID) ----+---N--1--- users
        |                | reviewed_at               |
        | (無 FK 約束，   | review_notes              |
        |  因分區表限制)  | generated_at              |
        N                | created_at                |
+---------------------------+   | updated_at                |
|    red_flag_alerts        |   +---------------------------+
|---------------------------|
| PK id (UUID)              |       +------------------------+
| FK session_id (UUID)      |       |   red_flag_rules       |
| conversation_id (UUID)    |       |------------------------|
|   (無 FK，分區表限制)     |       | PK id (UUID)           |
| alert_type (enum)         |       | name                   |
| severity (enum)           |       | description            |
| title                     |       | category               |
| description               |       | keywords (TEXT[])      |
| trigger_reason            |       | regex_pattern          |
| trigger_keywords (TEXT[]) |       | severity (enum)        |
| FK matched_rule_id (UUID) |--N--1-| is_active              |
|   (nullable)              |       | suggested_action       |
| llm_analysis (JSONB)      |       | suspected_diagnosis    |
| suggested_actions (TEXT[]) |      | FK created_by (UUID)---+---N--1--- users
| FK acknowledged_by (UUID) |--N--1-+ created_at             |
| acknowledged_at           |       | updated_at             |
| acknowledge_notes         |       +------------------------+
| created_at                |
+---------------------------+
```

### 關係摘要表

| 關係                                      | 類型 | 說明                                       |
|-------------------------------------------|------|--------------------------------------------|
| users -> patients                         | 1:N  | 一個使用者帳號對應一筆病患資料 (1:1 實務上) |
| users -> sessions (doctor_id)             | 1:N  | 一位醫師可進行多場問診                     |
| users -> notifications                    | 1:N  | 一位使用者可收到多則通知                   |
| users -> audit_logs                       | 1:N  | 一位使用者可產生多筆稽核紀錄               |
| users -> fcm_devices                      | 1:N  | 一位使用者可註冊多個推播裝置               |
| users -> chief_complaints (created_by)    | 1:N  | 一位使用者可建立多筆主訴項目               |
| users -> red_flag_rules (created_by)      | 1:N  | 一位使用者可建立多筆紅旗規則               |
| users -> soap_reports (reviewed_by)       | 1:N  | 一位使用者可審核多份 SOAP 報告             |
| users -> red_flag_alerts (acknowledged_by)| 1:N  | 一位使用者可確認多筆紅旗警示               |
| patients -> sessions                      | 1:N  | 一位病患可進行多場問診                     |
| chief_complaints -> sessions              | 1:N  | 一項主訴可對應多場問診                     |
| sessions -> conversations                 | 1:N  | 一場問診包含多筆對話紀錄                   |
| sessions -> soap_reports                  | 1:1  | 一場問診對應一份 SOAP 報告                 |
| sessions -> red_flag_alerts               | 1:N  | 一場問診可觸發多筆紅旗警示                 |
| conversations -> red_flag_alerts          | 1:N  | 一筆對話可觸發多筆紅旗警示（應用層保證參照完整性） |
| red_flag_rules -> red_flag_alerts         | 1:N  | 一條規則可匹配多筆紅旗警示                 |

---

## 2. 完整資料表定義 (Complete Table Definitions)

### 2.0 Enum 類型建立 (前置作業)

在建立資料表之前，必須先定義所有 PostgreSQL ENUM 類型。完整定義請見[第 5 節](#5-enum-類型定義)，以下僅列出建立語句：

```sql
-- 使用者角色
CREATE TYPE user_role AS ENUM ('patient', 'doctor', 'admin');

-- 問診場次狀態
CREATE TYPE session_status AS ENUM (
    'waiting', 'in_progress', 'completed', 'aborted_red_flag', 'cancelled'
);

-- 對話角色
CREATE TYPE conversation_role AS ENUM ('patient', 'assistant', 'system');

-- 紅旗警示類型
CREATE TYPE alert_type AS ENUM ('rule_based', 'semantic', 'combined');

-- 紅旗嚴重程度
CREATE TYPE alert_severity AS ENUM ('critical', 'high', 'medium');

-- 報告狀態
CREATE TYPE report_status AS ENUM ('generating', 'generated', 'failed');

-- 審閱狀態
CREATE TYPE review_status AS ENUM ('pending', 'approved', 'revision_needed');

-- 通知類型
CREATE TYPE notification_type AS ENUM (
    'red_flag', 'session_complete', 'report_ready', 'system'
);

-- 稽核操作類型
CREATE TYPE audit_action AS ENUM (
    'create', 'read', 'update', 'delete',
    'login', 'logout', 'export', 'review',
    'acknowledge', 'session_start', 'session_end'
);

-- 裝置平台
CREATE TYPE device_platform AS ENUM ('ios', 'android', 'web');

-- 性別
CREATE TYPE gender_type AS ENUM ('male', 'female', 'other');
```

---

### 2.1 users (使用者/醫師帳號)

儲存系統所有使用者的帳號資訊，包含病患、醫師與管理員。

```sql
CREATE TABLE users (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255)    NOT NULL,
    password_hash   VARCHAR(255)    NOT NULL,
    name            VARCHAR(100)    NOT NULL,
    role            user_role       NOT NULL DEFAULT 'patient',
    phone           VARCHAR(20),
    department      VARCHAR(100),
    license_number  VARCHAR(50),
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 唯一約束
    CONSTRAINT uq_users_email UNIQUE (email),

    -- 檢查約束：醫師必須填寫執照號碼
    CONSTRAINT chk_users_doctor_license CHECK (
        (role != 'doctor') OR (license_number IS NOT NULL AND license_number != '')
    ),

    -- 檢查約束：email 格式基本驗證
    CONSTRAINT chk_users_email_format CHECK (
        email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    )
);

-- 自動更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE users IS '使用者帳號表，儲存所有角色的帳號資訊';
COMMENT ON COLUMN users.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN users.email IS '電子信箱，作為登入帳號，全系統唯一';
COMMENT ON COLUMN users.password_hash IS '密碼雜湊值 (bcrypt/argon2)';
COMMENT ON COLUMN users.name IS '使用者姓名';
COMMENT ON COLUMN users.role IS '角色：patient (病患) / doctor (醫師) / admin (管理員)';
COMMENT ON COLUMN users.phone IS '聯絡電話';
COMMENT ON COLUMN users.department IS '所屬科別，醫師適用';
COMMENT ON COLUMN users.license_number IS '醫師執照號碼，僅醫師角色必填';
COMMENT ON COLUMN users.is_active IS '帳號是否啟用，停用後無法登入';
COMMENT ON COLUMN users.last_login_at IS '最後登入時間';
COMMENT ON COLUMN users.created_at IS '建立時間';
COMMENT ON COLUMN users.updated_at IS '最後更新時間';
```

---

### 2.2 patients (病患)

儲存病患的詳細醫療相關資料，透過 `user_id` 與 `users` 表建立一對一關係。

```sql
CREATE TABLE patients (
    id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID            NOT NULL,
    medical_record_number   VARCHAR(50)     NOT NULL,
    name                    VARCHAR(100)    NOT NULL,
    gender                  gender_type     NOT NULL,
    date_of_birth           DATE            NOT NULL,
    phone                   VARCHAR(20),
    emergency_contact       JSONB,
    medical_history         JSONB           NOT NULL DEFAULT '[]'::JSONB,
    allergies               JSONB           NOT NULL DEFAULT '[]'::JSONB,
    current_medications     JSONB           NOT NULL DEFAULT '[]'::JSONB,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_patients_user_id
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    -- 唯一約束
    CONSTRAINT uq_patients_user_id UNIQUE (user_id),
    CONSTRAINT uq_patients_medical_record_number UNIQUE (medical_record_number),

    -- 檢查約束
    CONSTRAINT chk_patients_dob CHECK (
        date_of_birth <= CURRENT_DATE
    )
);

CREATE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE patients IS '病患資料表，儲存病患醫療相關資訊';
COMMENT ON COLUMN patients.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN patients.user_id IS '對應使用者帳號 (外鍵至 users.id)，一對一';
COMMENT ON COLUMN patients.medical_record_number IS '病歷號碼，全系統唯一';
COMMENT ON COLUMN patients.name IS '病患姓名';
COMMENT ON COLUMN patients.gender IS '性別：male / female / other (使用 gender_type enum)';
COMMENT ON COLUMN patients.date_of_birth IS '出生日期';
COMMENT ON COLUMN patients.phone IS '聯絡電話';
COMMENT ON COLUMN patients.emergency_contact IS '緊急聯絡人資訊 (JSONB)：{name, relationship, phone}';
COMMENT ON COLUMN patients.medical_history IS '過去病史 (JSONB 陣列)';
COMMENT ON COLUMN patients.allergies IS '過敏史 (JSONB 陣列)';
COMMENT ON COLUMN patients.current_medications IS '目前用藥清單 (JSONB 陣列)';
COMMENT ON COLUMN patients.created_at IS '建立時間';
COMMENT ON COLUMN patients.updated_at IS '最後更新時間';
```

---

### 2.3 chief_complaints (主訴清單)

儲存問診主訴的預設與自訂選項，用於病患選擇就診主因。

```sql
CREATE TABLE chief_complaints (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200)    NOT NULL,
    name_en         VARCHAR(100),
    description     TEXT,
    category        VARCHAR(100)    NOT NULL,
    is_default      BOOLEAN         NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_by      UUID,
    display_order   INTEGER         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_chief_complaints_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,

    -- 唯一約束：同分類下名稱不可重複
    CONSTRAINT uq_chief_complaints_category_name UNIQUE (category, name),

    -- 檢查約束
    CONSTRAINT chk_chief_complaints_display_order CHECK (display_order >= 0)
);

CREATE TRIGGER trg_chief_complaints_updated_at
    BEFORE UPDATE ON chief_complaints
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE chief_complaints IS '主訴清單表，泌尿科常見主訴項目';
COMMENT ON COLUMN chief_complaints.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN chief_complaints.name IS '主訴名稱（中文），例如「血尿」「排尿疼痛」';
COMMENT ON COLUMN chief_complaints.name_en IS '主訴名稱（英文），例如「Hematuria」';
COMMENT ON COLUMN chief_complaints.description IS '主訴描述，提供更詳細的說明';
COMMENT ON COLUMN chief_complaints.category IS '主訴分類，例如「排尿症狀」「疼痛」「腫塊與外觀」';
COMMENT ON COLUMN chief_complaints.is_default IS '是否為系統預設主訴 (不可刪除)';
COMMENT ON COLUMN chief_complaints.is_active IS '是否啟用';
COMMENT ON COLUMN chief_complaints.created_by IS '建立者 (外鍵至 users.id)，系統預設項目為 NULL';
COMMENT ON COLUMN chief_complaints.display_order IS '顯示排序，數值越小越前面';
COMMENT ON COLUMN chief_complaints.created_at IS '建立時間';
COMMENT ON COLUMN chief_complaints.updated_at IS '最後更新時間';
```

---

### 2.4 sessions (問診場次)

記錄每一次 AI 問診互動的完整場次資訊。

```sql
CREATE TABLE sessions (
    id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id              UUID            NOT NULL,
    doctor_id               UUID,
    chief_complaint_id      UUID            NOT NULL,
    chief_complaint_text    VARCHAR(500),
    status                  session_status  NOT NULL DEFAULT 'waiting',
    red_flag                BOOLEAN         NOT NULL DEFAULT FALSE,
    red_flag_reason         TEXT,
    language                VARCHAR(10)     NOT NULL DEFAULT 'zh-TW',
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    duration_seconds        INTEGER,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_sessions_patient_id
        FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE RESTRICT,
    CONSTRAINT fk_sessions_doctor_id
        FOREIGN KEY (doctor_id) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_sessions_chief_complaint_id
        FOREIGN KEY (chief_complaint_id) REFERENCES chief_complaints(id) ON DELETE RESTRICT,

    -- 檢查約束
    CONSTRAINT chk_sessions_completed_after_started CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    ),
    CONSTRAINT chk_sessions_duration_positive CHECK (
        duration_seconds IS NULL OR duration_seconds >= 0
    ),
    CONSTRAINT chk_sessions_red_flag_reason CHECK (
        (red_flag = FALSE) OR (red_flag = TRUE AND red_flag_reason IS NOT NULL)
    )
);

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE sessions IS '問診場次表，記錄每次 AI 語音問診的完整過程';
COMMENT ON COLUMN sessions.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN sessions.patient_id IS '病患 ID (外鍵至 patients.id)';
COMMENT ON COLUMN sessions.doctor_id IS '負責醫師 ID (外鍵至 users.id)，可稍後指派，故為 NULLABLE';
COMMENT ON COLUMN sessions.chief_complaint_id IS '主訴項目 ID (外鍵至 chief_complaints.id)';
COMMENT ON COLUMN sessions.chief_complaint_text IS '病患自述主訴文字，可為主訴項目的補充說明';
COMMENT ON COLUMN sessions.status IS '場次狀態：waiting/in_progress/completed/aborted_red_flag/cancelled';
COMMENT ON COLUMN sessions.red_flag IS '是否觸發紅旗警示';
COMMENT ON COLUMN sessions.red_flag_reason IS '紅旗警示原因說明，red_flag 為 TRUE 時必填';
COMMENT ON COLUMN sessions.language IS '對話語言，預設 zh-TW';
COMMENT ON COLUMN sessions.started_at IS '問診開始時間';
COMMENT ON COLUMN sessions.completed_at IS '問診結束時間';
COMMENT ON COLUMN sessions.duration_seconds IS '問診持續秒數';
COMMENT ON COLUMN sessions.created_at IS '建立時間';
COMMENT ON COLUMN sessions.updated_at IS '最後更新時間';
```

---

### 2.5 conversations (對話紀錄)

儲存問診過程中每一輪對話的內容，包含語音轉文字結果與音檔位址。
此表採用月份 Range Partitioning，詳見[第 7 節](#7-資料分割與保留策略-partitioning--retention)。

```sql
CREATE TABLE conversations (
    id                      UUID                NOT NULL DEFAULT gen_random_uuid(),
    session_id              UUID                NOT NULL,
    sequence_number         INTEGER             NOT NULL,
    role                    conversation_role   NOT NULL,
    content_text            TEXT,
    audio_url               VARCHAR(500),
    audio_duration_seconds  NUMERIC(8,2),
    stt_confidence          NUMERIC(5,4),
    red_flag_detected       BOOLEAN             NOT NULL DEFAULT FALSE,
    metadata                JSONB               NOT NULL DEFAULT '{}'::JSONB,
    created_at              TIMESTAMPTZ         NOT NULL DEFAULT NOW(),

    -- 主鍵
    CONSTRAINT pk_conversations PRIMARY KEY (id, created_at),

    -- 外鍵約束
    CONSTRAINT fk_conversations_session_id
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,

    -- 唯一約束：同一場次內序號不可重複
    CONSTRAINT uq_conversations_session_sequence UNIQUE (session_id, sequence_number),

    -- 檢查約束
    CONSTRAINT chk_conversations_stt_confidence CHECK (
        stt_confidence IS NULL OR (stt_confidence >= 0 AND stt_confidence <= 1)
    ),
    CONSTRAINT chk_conversations_audio_duration CHECK (
        audio_duration_seconds IS NULL OR audio_duration_seconds >= 0
    ),
    CONSTRAINT chk_conversations_sequence_positive CHECK (
        sequence_number > 0
    )
) PARTITION BY RANGE (created_at);

COMMENT ON TABLE conversations IS '對話紀錄表，儲存問診中每一輪 AI 與病患的互動，按月份分割';
COMMENT ON COLUMN conversations.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN conversations.session_id IS '所屬問診場次 ID (外鍵至 sessions.id)';
COMMENT ON COLUMN conversations.sequence_number IS '對話序號，同場次內依序遞增 (從 1 開始)';
COMMENT ON COLUMN conversations.role IS '發言者角色：patient (病患) / assistant (AI 助手) / system (系統)';
COMMENT ON COLUMN conversations.content_text IS '對話文字內容 (語音轉文字結果或 AI 回覆)';
COMMENT ON COLUMN conversations.audio_url IS '音檔 S3 URL (僅病患語音訊息)';
COMMENT ON COLUMN conversations.audio_duration_seconds IS '音檔長度 (秒)';
COMMENT ON COLUMN conversations.stt_confidence IS 'STT 語音辨識信心分數，0 至 1 之間';
COMMENT ON COLUMN conversations.red_flag_detected IS '此輪對話是否偵測到紅旗關鍵字';
COMMENT ON COLUMN conversations.metadata IS '附加中繼資料 (JSONB)，如 STT 引擎版本等';
COMMENT ON COLUMN conversations.created_at IS '建立時間，同時作為分割鍵';

-- 建立初始分割區 (範例：2026 年各月)
CREATE TABLE conversations_y2026m01 PARTITION OF conversations
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE conversations_y2026m02 PARTITION OF conversations
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE conversations_y2026m03 PARTITION OF conversations
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE conversations_y2026m04 PARTITION OF conversations
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE conversations_y2026m05 PARTITION OF conversations
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE conversations_y2026m06 PARTITION OF conversations
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE conversations_y2026m07 PARTITION OF conversations
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE conversations_y2026m08 PARTITION OF conversations
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE conversations_y2026m09 PARTITION OF conversations
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE conversations_y2026m10 PARTITION OF conversations
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE conversations_y2026m11 PARTITION OF conversations
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE conversations_y2026m12 PARTITION OF conversations
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

-- 建立 default 分割區，防止超出範圍的資料寫入失敗
CREATE TABLE conversations_default PARTITION OF conversations DEFAULT;
```

---

### 2.6 soap_reports (SOAP 報告)

儲存 AI 生成的 SOAP 結構化報告，每場問診對應一份。

```sql
CREATE TABLE soap_reports (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID            NOT NULL,
    status              report_status   NOT NULL DEFAULT 'generating',
    review_status       review_status   NOT NULL DEFAULT 'pending',
    subjective          JSONB           NOT NULL DEFAULT '{}'::JSONB,
    objective           JSONB           NOT NULL DEFAULT '{}'::JSONB,
    assessment          JSONB           NOT NULL DEFAULT '{}'::JSONB,
    plan                JSONB           NOT NULL DEFAULT '{}'::JSONB,
    raw_transcript      TEXT,
    summary             TEXT,
    icd10_codes         TEXT[]          NOT NULL DEFAULT '{}',
    ai_confidence_score NUMERIC(3,2),
    reviewed_by         UUID,
    reviewed_at         TIMESTAMPTZ,
    review_notes        TEXT,
    generated_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_soap_reports_session_id
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    CONSTRAINT fk_soap_reports_reviewed_by
        FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,

    -- 唯一約束：一場問診只對應一份 SOAP 報告
    CONSTRAINT uq_soap_reports_session_id UNIQUE (session_id),

    -- 檢查約束
    CONSTRAINT chk_soap_reports_review_consistency CHECK (
        (reviewed_by IS NULL AND reviewed_at IS NULL) OR
        (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
    ),
    CONSTRAINT chk_soap_reports_ai_confidence CHECK (
        ai_confidence_score IS NULL OR (ai_confidence_score >= 0 AND ai_confidence_score <= 1)
    )
);

CREATE TRIGGER trg_soap_reports_updated_at
    BEFORE UPDATE ON soap_reports
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE soap_reports IS 'SOAP 報告表，儲存 AI 生成的結構化問診報告';
COMMENT ON COLUMN soap_reports.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN soap_reports.session_id IS '對應問診場次 ID (外鍵至 sessions.id)，一對一';
COMMENT ON COLUMN soap_reports.status IS '報告狀態：generating (生成中) / generated (已生成) / failed (失敗)';
COMMENT ON COLUMN soap_reports.review_status IS '審閱狀態：pending (待審閱) / approved (已核准) / revision_needed (需修改)';
COMMENT ON COLUMN soap_reports.subjective IS '主觀資料 (S)，包含主訴、現病史等 (JSONB)';
COMMENT ON COLUMN soap_reports.objective IS '客觀資料 (O)，包含生命徵象、理學檢查等 (JSONB)';
COMMENT ON COLUMN soap_reports.assessment IS '評估 (A)，包含鑑別診斷、臨床印象 (JSONB)';
COMMENT ON COLUMN soap_reports.plan IS '計畫 (P)，包含建議檢查、治療、追蹤 (JSONB)';
COMMENT ON COLUMN soap_reports.raw_transcript IS '完整原始對話逐字稿';
COMMENT ON COLUMN soap_reports.summary IS 'AI 生成的問診摘要';
COMMENT ON COLUMN soap_reports.icd10_codes IS 'ICD-10 診斷碼陣列';
COMMENT ON COLUMN soap_reports.ai_confidence_score IS 'AI 信心分數，0 至 1 之間';
COMMENT ON COLUMN soap_reports.reviewed_by IS '審核醫師 ID (外鍵至 users.id)';
COMMENT ON COLUMN soap_reports.reviewed_at IS '審核時間';
COMMENT ON COLUMN soap_reports.review_notes IS '醫師審核備註';
COMMENT ON COLUMN soap_reports.generated_at IS 'AI 報告生成時間';
COMMENT ON COLUMN soap_reports.created_at IS '建立時間';
COMMENT ON COLUMN soap_reports.updated_at IS '最後更新時間';
```

---

### 2.7 red_flag_alerts (紅旗警示)

記錄問診過程中觸發的紅旗警示，可由規則引擎或語意分析產生。

> **注意：** `conversation_id` 不使用外鍵約束，因為 `conversations` 表為分區表，PostgreSQL 不支援外鍵引用分區表的非主鍵欄位。改以應用層保證參照完整性。

```sql
CREATE TABLE red_flag_alerts (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID            NOT NULL,
    conversation_id     UUID            NOT NULL,
    -- conversation_id 不設外鍵約束，因 conversations 為分區表 (partitioned table)，
    -- PostgreSQL 不支援外鍵引用分區表。改以應用層保證參照完整性。
    alert_type          alert_type      NOT NULL,
    severity            alert_severity  NOT NULL,
    title               VARCHAR(200)    NOT NULL,
    description         TEXT,
    trigger_reason      TEXT            NOT NULL,
    trigger_keywords    TEXT[]          NOT NULL DEFAULT '{}',
    matched_rule_id     UUID,
    llm_analysis        JSONB,
    suggested_actions   TEXT[],
    acknowledged_by     UUID,
    acknowledged_at     TIMESTAMPTZ,
    acknowledge_notes   TEXT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_red_flag_alerts_session_id
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    -- 注意：conversation_id 無 FK 約束 (分區表限制)
    CONSTRAINT fk_red_flag_alerts_matched_rule_id
        FOREIGN KEY (matched_rule_id) REFERENCES red_flag_rules(id) ON DELETE SET NULL,
    CONSTRAINT fk_red_flag_alerts_acknowledged_by
        FOREIGN KEY (acknowledged_by) REFERENCES users(id) ON DELETE SET NULL,

    -- 檢查約束
    CONSTRAINT chk_red_flag_alerts_ack_consistency CHECK (
        (acknowledged_by IS NULL AND acknowledged_at IS NULL) OR
        (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL)
    ),
    CONSTRAINT chk_red_flag_alerts_rule_based CHECK (
        alert_type != 'rule_based' OR matched_rule_id IS NOT NULL
    )
);

COMMENT ON TABLE red_flag_alerts IS '紅旗警示表，記錄問診中偵測到的危急情況';
COMMENT ON COLUMN red_flag_alerts.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN red_flag_alerts.session_id IS '所屬問診場次 ID (外鍵至 sessions.id)';
COMMENT ON COLUMN red_flag_alerts.conversation_id IS '觸發對話 ID（無外鍵約束，因 conversations 為分區表）';
COMMENT ON COLUMN red_flag_alerts.alert_type IS '警示類型：rule_based (規則) / semantic (語意) / combined (混合)';
COMMENT ON COLUMN red_flag_alerts.severity IS '嚴重程度：critical (緊急) / high (高) / medium (中)';
COMMENT ON COLUMN red_flag_alerts.title IS '警示標題';
COMMENT ON COLUMN red_flag_alerts.description IS '警示描述';
COMMENT ON COLUMN red_flag_alerts.trigger_reason IS '觸發原因說明';
COMMENT ON COLUMN red_flag_alerts.trigger_keywords IS '觸發的關鍵字列表';
COMMENT ON COLUMN red_flag_alerts.matched_rule_id IS '匹配的紅旗規則 ID (外鍵至 red_flag_rules.id)，語意型可為 NULL';
COMMENT ON COLUMN red_flag_alerts.llm_analysis IS 'LLM 語意分析結果 (JSONB)';
COMMENT ON COLUMN red_flag_alerts.suggested_actions IS '建議處置列表 (TEXT 陣列)';
COMMENT ON COLUMN red_flag_alerts.acknowledged_by IS '確認處理的醫師 ID (外鍵至 users.id)';
COMMENT ON COLUMN red_flag_alerts.acknowledged_at IS '確認處理時間';
COMMENT ON COLUMN red_flag_alerts.acknowledge_notes IS '確認備註';
COMMENT ON COLUMN red_flag_alerts.created_at IS '建立時間';
```

---

### 2.8 red_flag_rules (紅旗規則配置)

儲存紅旗關鍵字與規則配置，供規則引擎即時比對。

```sql
CREATE TABLE red_flag_rules (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(200)    NOT NULL,
    description         TEXT,
    category            VARCHAR(100)    NOT NULL,
    keywords            TEXT[]          NOT NULL DEFAULT '{}',
    regex_pattern       TEXT,
    severity            alert_severity  NOT NULL DEFAULT 'medium',
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    suggested_action    TEXT,
    suspected_diagnosis VARCHAR(500),
    created_by          UUID            NOT NULL,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_red_flag_rules_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT,

    -- 唯一約束
    CONSTRAINT uq_red_flag_rules_name UNIQUE (name),

    -- 檢查約束：至少要有關鍵字或正則表達式其一
    CONSTRAINT chk_red_flag_rules_has_pattern CHECK (
        array_length(keywords, 1) > 0 OR regex_pattern IS NOT NULL
    )
);

CREATE TRIGGER trg_red_flag_rules_updated_at
    BEFORE UPDATE ON red_flag_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE red_flag_rules IS '紅旗規則配置表，定義危急情況的偵測規則';
COMMENT ON COLUMN red_flag_rules.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN red_flag_rules.name IS '規則名稱，全系統唯一';
COMMENT ON COLUMN red_flag_rules.description IS '規則描述說明';
COMMENT ON COLUMN red_flag_rules.category IS '規則分類，例如「泌尿道急症」「腎臟急症」';
COMMENT ON COLUMN red_flag_rules.keywords IS '觸發關鍵字陣列';
COMMENT ON COLUMN red_flag_rules.regex_pattern IS '觸發正則表達式 (可選)';
COMMENT ON COLUMN red_flag_rules.severity IS '嚴重程度：critical / high / medium (使用 alert_severity enum)';
COMMENT ON COLUMN red_flag_rules.is_active IS '規則是否啟用';
COMMENT ON COLUMN red_flag_rules.suggested_action IS '建議處置方式';
COMMENT ON COLUMN red_flag_rules.suspected_diagnosis IS '疑似診斷';
COMMENT ON COLUMN red_flag_rules.created_by IS '建立者 (外鍵至 users.id)';
COMMENT ON COLUMN red_flag_rules.created_at IS '建立時間';
COMMENT ON COLUMN red_flag_rules.updated_at IS '最後更新時間';
```

---

### 2.9 notifications (通知)

儲存推播與站內通知訊息。

```sql
CREATE TABLE notifications (
    id          UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID                NOT NULL,
    type        notification_type   NOT NULL,
    title       VARCHAR(255)        NOT NULL,
    body        TEXT                NOT NULL,
    data        JSONB               NOT NULL DEFAULT '{}'::JSONB,
    is_read     BOOLEAN             NOT NULL DEFAULT FALSE,
    read_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ         NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_notifications_user_id
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    -- 檢查約束
    CONSTRAINT chk_notifications_read_consistency CHECK (
        (is_read = FALSE AND read_at IS NULL) OR
        (is_read = TRUE AND read_at IS NOT NULL)
    )
);

COMMENT ON TABLE notifications IS '通知表，儲存推播與站內通知訊息';
COMMENT ON COLUMN notifications.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN notifications.user_id IS '接收通知的使用者 ID (外鍵至 users.id)';
COMMENT ON COLUMN notifications.type IS '通知類型：red_flag / session_complete / report_ready / system';
COMMENT ON COLUMN notifications.title IS '通知標題';
COMMENT ON COLUMN notifications.body IS '通知內文';
COMMENT ON COLUMN notifications.data IS '附加資料 (JSONB)，例如 session_id、report_id';
COMMENT ON COLUMN notifications.is_read IS '是否已讀';
COMMENT ON COLUMN notifications.read_at IS '已讀時間';
COMMENT ON COLUMN notifications.created_at IS '建立時間';
```

---

### 2.10 audit_logs (稽核日誌)

記錄所有使用者操作的稽核軌跡，符合醫療資訊系統合規要求。
此表採用月份 Range Partitioning。

```sql
CREATE TABLE audit_logs (
    id              BIGINT          GENERATED ALWAYS AS IDENTITY,
    user_id         UUID,
    action          audit_action    NOT NULL,
    resource_type   VARCHAR(100)    NOT NULL,
    resource_id     VARCHAR(255),
    details         JSONB           NOT NULL DEFAULT '{}'::JSONB,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 主鍵 (包含分割鍵)
    CONSTRAINT pk_audit_logs PRIMARY KEY (id, created_at),

    -- 外鍵約束 (不使用 CASCADE，稽核日誌需保留)
    CONSTRAINT fk_audit_logs_user_id
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) PARTITION BY RANGE (created_at);

COMMENT ON TABLE audit_logs IS '稽核日誌表，記錄系統所有操作軌跡，按月份分割';
COMMENT ON COLUMN audit_logs.id IS '主鍵，自動遞增 BIGINT';
COMMENT ON COLUMN audit_logs.user_id IS '操作使用者 ID (外鍵至 users.id)，系統操作可為 NULL';
COMMENT ON COLUMN audit_logs.action IS '操作類型：create/read/update/delete/login/logout/export/review/acknowledge/session_start/session_end';
COMMENT ON COLUMN audit_logs.resource_type IS '操作對象類型，例如 session / patient / soap_report';
COMMENT ON COLUMN audit_logs.resource_id IS '操作對象 ID';
COMMENT ON COLUMN audit_logs.details IS '操作詳細資訊 (JSONB)，記錄變更前後差異等';
COMMENT ON COLUMN audit_logs.ip_address IS '操作來源 IP 位址';
COMMENT ON COLUMN audit_logs.user_agent IS '操作來源 User-Agent';
COMMENT ON COLUMN audit_logs.created_at IS '操作時間，同時作為分割鍵';

-- 建立初始分割區 (範例：2026 年各月)
CREATE TABLE audit_logs_y2026m01 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE audit_logs_y2026m02 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE audit_logs_y2026m03 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE audit_logs_y2026m04 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE audit_logs_y2026m05 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE audit_logs_y2026m06 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE audit_logs_y2026m07 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE audit_logs_y2026m08 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE audit_logs_y2026m09 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE audit_logs_y2026m10 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE audit_logs_y2026m11 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE audit_logs_y2026m12 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT;
```

---

### 2.11 fcm_devices (裝置推播 token)

儲存使用者的 Firebase Cloud Messaging 裝置 token，用於推播通知。

```sql
CREATE TABLE fcm_devices (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL,
    device_token    VARCHAR(512)    NOT NULL,
    platform        device_platform NOT NULL,
    device_name     VARCHAR(200),
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 外鍵約束
    CONSTRAINT fk_fcm_devices_user_id
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    -- 唯一約束：同一裝置 token 不可重複
    CONSTRAINT uq_fcm_devices_device_token UNIQUE (device_token)
);

CREATE TRIGGER trg_fcm_devices_updated_at
    BEFORE UPDATE ON fcm_devices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE fcm_devices IS '裝置推播 token 表，儲存 FCM 推播所需的裝置識別資訊';
COMMENT ON COLUMN fcm_devices.id IS '主鍵，UUID v4 自動產生';
COMMENT ON COLUMN fcm_devices.user_id IS '所屬使用者 ID (外鍵至 users.id)';
COMMENT ON COLUMN fcm_devices.device_token IS 'FCM 裝置 token';
COMMENT ON COLUMN fcm_devices.platform IS '裝置平台：ios / android / web';
COMMENT ON COLUMN fcm_devices.device_name IS '裝置名稱，例如「iPhone 15 Pro」';
COMMENT ON COLUMN fcm_devices.is_active IS 'token 是否有效';
COMMENT ON COLUMN fcm_devices.created_at IS '建立時間';
COMMENT ON COLUMN fcm_devices.updated_at IS '最後更新時間';
```

---

## 3. 索引設計 (Index Design)

### 3.1 users 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 唯一索引 (已由 UNIQUE 約束自動建立)
-- uq_users_email ON users(email)

-- 角色查詢：依角色篩選使用者列表
CREATE INDEX idx_users_role ON users(role)
    WHERE is_active = TRUE;
-- 查詢場景：列出所有啟用的醫師帳號

-- 姓名搜尋：模糊搜尋使用者姓名
CREATE INDEX idx_users_name ON users(name);
-- 查詢場景：搜尋醫師姓名進行指派

-- 最後登入時間查詢
CREATE INDEX idx_users_last_login_at ON users(last_login_at DESC)
    WHERE is_active = TRUE;
-- 查詢場景：查看最近登入的使用者
```

### 3.2 patients 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 唯一索引 (已由 UNIQUE 約束自動建立)
-- uq_patients_user_id ON patients(user_id)
-- uq_patients_medical_record_number ON patients(medical_record_number)

-- 姓名查詢：搜尋病患姓名
CREATE INDEX idx_patients_name ON patients(name);
-- 查詢場景：護理師或醫師搜尋病患

-- 出生日期：年齡統計與篩選
CREATE INDEX idx_patients_date_of_birth ON patients(date_of_birth);
-- 查詢場景：依年齡區間篩選病患

-- JSONB GIN 索引：醫療史查詢
CREATE INDEX idx_patients_medical_history ON patients
    USING GIN (medical_history jsonb_path_ops);
-- 查詢場景：搜尋具有特定病史的病患

-- JSONB GIN 索引：過敏史查詢
CREATE INDEX idx_patients_allergies ON patients
    USING GIN (allergies jsonb_path_ops);
-- 查詢場景：確認病患是否有特定藥物過敏
```

### 3.3 chief_complaints 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 唯一索引 (已由 UNIQUE 約束自動建立)
-- uq_chief_complaints_category_name ON chief_complaints(category, name)

-- 分類與排序：載入主訴選單
CREATE INDEX idx_chief_complaints_category_order ON chief_complaints(category, display_order)
    WHERE is_active = TRUE;
-- 查詢場景：前端依分類與排序載入可用主訴清單

-- 預設主訴篩選
CREATE INDEX idx_chief_complaints_is_default ON chief_complaints(is_default)
    WHERE is_default = TRUE AND is_active = TRUE;
-- 查詢場景：載入系統預設的主訴項目
```

### 3.4 sessions 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 病患場次查詢：列出病患的所有問診
CREATE INDEX idx_sessions_patient_id ON sessions(patient_id, created_at DESC);
-- 查詢場景：查看特定病患的問診歷史

-- 醫師場次查詢：列出醫師的所有問診
CREATE INDEX idx_sessions_doctor_id ON sessions(doctor_id, created_at DESC);
-- 查詢場景：醫師查看自己的問診列表

-- 主訴場次查詢
CREATE INDEX idx_sessions_chief_complaint_id ON sessions(chief_complaint_id);
-- 查詢場景：統計各主訴的問診次數

-- 狀態篩選：篩選特定狀態的場次
CREATE INDEX idx_sessions_status ON sessions(status, created_at DESC);
-- 查詢場景：列出進行中或等待中的場次

-- 紅旗場次：快速找出觸發紅旗的場次
CREATE INDEX idx_sessions_red_flag ON sessions(doctor_id, created_at DESC)
    WHERE red_flag = TRUE;
-- 查詢場景：醫師查看所有紅旗警示場次

-- 等待中場次：候診佇列
CREATE INDEX idx_sessions_waiting ON sessions(created_at ASC)
    WHERE status = 'waiting';
-- 查詢場景：候診佇列排序

-- 時間範圍查詢：依日期範圍篩選
CREATE INDEX idx_sessions_created_at ON sessions(created_at DESC);
-- 查詢場景：依日期區間查詢問診紀錄

-- 複合索引：醫師 + 狀態 + 時間
CREATE INDEX idx_sessions_doctor_status ON sessions(doctor_id, status, created_at DESC);
-- 查詢場景：醫師查看自己特定狀態的問診

-- 語言篩選
CREATE INDEX idx_sessions_language ON sessions(language);
-- 查詢場景：依語言篩選問診場次
```

### 3.5 conversations 索引

```sql
-- 主鍵索引 (自動建立)
-- pk_conversations ON conversations(id, created_at)

-- 唯一索引 (已由 UNIQUE 約束自動建立)
-- uq_conversations_session_sequence ON conversations(session_id, sequence_number)

-- 場次對話查詢：載入某場問診的所有對話
CREATE INDEX idx_conversations_session_id_seq ON conversations(session_id, sequence_number ASC);
-- 查詢場景：依序載入一場問診的完整對話

-- 紅旗對話篩選
CREATE INDEX idx_conversations_red_flag ON conversations(session_id)
    WHERE red_flag_detected = TRUE;
-- 查詢場景：快速找出觸發紅旗的對話

-- 時間查詢 (分割鍵)
CREATE INDEX idx_conversations_created_at ON conversations(created_at DESC);
-- 查詢場景：分割區裁剪 (partition pruning) 用途
```

### 3.6 soap_reports 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 唯一索引 (已由 UNIQUE 約束自動建立)
-- uq_soap_reports_session_id ON soap_reports(session_id)

-- 報告狀態查詢：篩選特定狀態的報告
CREATE INDEX idx_soap_reports_status ON soap_reports(status, generated_at DESC);
-- 查詢場景：列出生成中或失敗的報告

-- 審閱狀態查詢：列出待審核的報告
CREATE INDEX idx_soap_reports_review_status ON soap_reports(review_status, generated_at DESC);
-- 查詢場景：醫師查看待審閱的 SOAP 報告

-- 審核狀態查詢：列出待審核的報告 (相容舊查詢)
CREATE INDEX idx_soap_reports_unreviewed ON soap_reports(generated_at DESC)
    WHERE reviewed_by IS NULL;
-- 查詢場景：醫師查看尚未審核的 SOAP 報告

-- 審核醫師查詢
CREATE INDEX idx_soap_reports_reviewed_by ON soap_reports(reviewed_by, reviewed_at DESC)
    WHERE reviewed_by IS NOT NULL;
-- 查詢場景：查看特定醫師審核過的報告

-- ICD-10 碼查詢
CREATE INDEX idx_soap_reports_icd10 ON soap_reports USING GIN (icd10_codes);
-- 查詢場景：依 ICD-10 碼搜尋相關報告

-- JSONB GIN 索引：評估內容查詢
CREATE INDEX idx_soap_reports_assessment ON soap_reports
    USING GIN (assessment jsonb_path_ops);
-- 查詢場景：搜尋包含特定診斷的報告

-- 生成時間查詢
CREATE INDEX idx_soap_reports_generated_at ON soap_reports(generated_at DESC);
-- 查詢場景：依時間排序查看最近的報告
```

### 3.7 red_flag_alerts 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 場次警示查詢
CREATE INDEX idx_red_flag_alerts_session_id ON red_flag_alerts(session_id, created_at DESC);
-- 查詢場景：查看特定場次的所有紅旗警示

-- 對話警示查詢
CREATE INDEX idx_red_flag_alerts_conversation_id ON red_flag_alerts(conversation_id);
-- 查詢場景：查看特定對話觸發的警示

-- 未確認警示 (部分索引)
CREATE INDEX idx_red_flag_alerts_unacknowledged ON red_flag_alerts(severity, created_at DESC)
    WHERE acknowledged_by IS NULL;
-- 查詢場景：列出所有待處理的紅旗警示 (依嚴重度排序)

-- 嚴重度篩選
CREATE INDEX idx_red_flag_alerts_severity ON red_flag_alerts(severity, created_at DESC);
-- 查詢場景：依嚴重度篩選警示

-- 規則匹配查詢
CREATE INDEX idx_red_flag_alerts_matched_rule ON red_flag_alerts(matched_rule_id)
    WHERE matched_rule_id IS NOT NULL;
-- 查詢場景：查看特定規則觸發的歷史警示

-- 時間範圍查詢
CREATE INDEX idx_red_flag_alerts_created_at ON red_flag_alerts(created_at DESC);
-- 查詢場景：依時間查詢警示歷史
```

### 3.8 red_flag_rules 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 唯一索引 (已由 UNIQUE 約束自動建立)
-- uq_red_flag_rules_name ON red_flag_rules(name)

-- 啟用規則查詢
CREATE INDEX idx_red_flag_rules_active ON red_flag_rules(category, severity)
    WHERE is_active = TRUE;
-- 查詢場景：載入所有啟用的規則供引擎比對

-- 關鍵字 GIN 索引
CREATE INDEX idx_red_flag_rules_keywords ON red_flag_rules USING GIN (keywords);
-- 查詢場景：搜尋包含特定關鍵字的規則

-- 建立者查詢
CREATE INDEX idx_red_flag_rules_created_by ON red_flag_rules(created_by);
-- 查詢場景：查看特定使用者建立的規則
```

### 3.9 notifications 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 使用者通知查詢：載入使用者的通知列表
CREATE INDEX idx_notifications_user_id ON notifications(user_id, created_at DESC);
-- 查詢場景：載入使用者的通知列表 (最新優先)

-- 未讀通知計數
CREATE INDEX idx_notifications_unread ON notifications(user_id, type)
    WHERE is_read = FALSE;
-- 查詢場景：計算使用者未讀通知數量 (可依類型篩選)

-- 通知類型篩選
CREATE INDEX idx_notifications_type ON notifications(type, created_at DESC);
-- 查詢場景：依類型篩選通知
```

### 3.10 audit_logs 索引

```sql
-- 主鍵索引 (自動建立)
-- pk_audit_logs ON audit_logs(id, created_at)

-- 使用者操作查詢
CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id, created_at DESC);
-- 查詢場景：查看特定使用者的操作記錄

-- 資源操作查詢
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id, created_at DESC);
-- 查詢場景：查看特定資源 (如某筆 session) 的所有操作記錄

-- 操作類型篩選
CREATE INDEX idx_audit_logs_action ON audit_logs(action, created_at DESC);
-- 查詢場景：篩選特定操作類型的稽核記錄

-- 時間範圍查詢
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at DESC);
-- 查詢場景：依時間區間查詢稽核記錄 (搭配分割區裁剪)
```

### 3.11 fcm_devices 索引

```sql
-- 主鍵索引 (自動建立)
-- PRIMARY KEY (id)

-- 唯一索引 (已由 UNIQUE 約束自動建立)
-- uq_fcm_devices_device_token ON fcm_devices(device_token)

-- 使用者裝置查詢
CREATE INDEX idx_fcm_devices_user_id ON fcm_devices(user_id)
    WHERE is_active = TRUE;
-- 查詢場景：取得特定使用者所有啟用的裝置 token 以推播通知

-- 平台篩選
CREATE INDEX idx_fcm_devices_platform ON fcm_devices(platform)
    WHERE is_active = TRUE;
-- 查詢場景：依平台統計裝置數或批次推播
```

---

## 4. JSONB 欄位結構定義

本節定義所有 JSONB 欄位的內部資料結構。雖然 PostgreSQL JSONB 本身不強制 schema，但應用程式層 (SQLAlchemy model + Pydantic validator) 必須嚴格遵循以下結構。

### 4.1 soap_reports.subjective (主觀資料)

```jsonc
{
    // 主訴
    "chief_complaint": "血尿持續三天",

    // 現病史 (History of Present Illness)
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

    // 過去病史
    "past_medical_history": {
        "conditions": ["高血壓"],
        "surgeries": [],
        "hospitalizations": []
    },

    // 藥物史
    "medication_history": {
        "current": ["Amlodipine 5mg QD"],
        "past": [],
        "otc": []
    },

    // 系統性回顧 (Review of Systems)
    "system_review": {
        "constitutional": "無發燒、體重下降",
        "genitourinary": "頻尿、血尿",
        "gastrointestinal": "正常",
        "musculoskeletal": "輕微腰痛"
    },

    // 社會史
    "social_history": {
        "smoking": "無",
        "alcohol": "偶爾",
        "occupation": "辦公室工作"
    }
}
```

### 4.2 soap_reports.objective (客觀資料)

```jsonc
{
    // 生命徵象
    "vital_signs": {
        "blood_pressure": "135/85 mmHg",
        "heart_rate": 78,
        "respiratory_rate": 18,
        "temperature": 36.8,
        "spo2": 98
    },

    // 理學檢查
    "physical_exam": {
        "general": "病患意識清醒，表情平靜",
        "abdomen": "腹部柔軟，無壓痛",
        "costovertebral_angle": "左側輕度叩擊痛"
    },

    // 實驗室檢查結果
    "lab_results": [
        {
            "test_name": "尿液分析",
            "result": "RBC >50/HPF",
            "reference_range": "0-5/HPF",
            "is_abnormal": true,
            "date": "2026-04-10"
        }
    ],

    // 影像檢查結果
    "imaging_results": []
}
```

### 4.3 soap_reports.assessment (評估)

```jsonc
{
    // 鑑別診斷列表
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

    // 臨床整體印象
    "clinical_impression": "持續性肉眼血尿，最可能為泌尿道結石，但需排除膀胱腫瘤"
}
```

### 4.4 soap_reports.plan (計畫)

```jsonc
{
    // 建議檢查
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

    // 治療計畫
    "treatments": [
        {
            "type": "medication",
            "name": "Tamsulosin 0.4mg QD",
            "instruction": "睡前服用",
            "note": "若為結石，協助排石"
        }
    ],

    // 追蹤計畫
    "follow_up": {
        "interval": "2 週後",
        "reason": "追蹤檢查結果",
        "additional_notes": "若血尿加重或出現發燒請立即就醫"
    },

    // 轉介
    "referrals": [],

    // 病患衛教
    "patient_education": [
        "多喝水，每日 2000ml 以上",
        "避免劇烈運動",
        "觀察尿液顏色變化，若出現血塊請立即就醫"
    ]
}
```

### 4.5 patients.emergency_contact (緊急聯絡人)

```jsonc
{
    "name": "王小明",
    "relationship": "配偶",
    "phone": "0912345678"
}
```

### 4.6 patients.medical_history (過去病史)

```jsonc
[
    {
        "condition": "高血壓",
        "diagnosed_year": 2018,
        "status": "controlled",     // "active" | "controlled" | "resolved"
        "notes": "規律服藥中"
    }
]
```

### 4.7 patients.allergies (過敏史)

```jsonc
[
    {
        "allergen": "Penicillin",
        "type": "drug",             // "drug" | "food" | "environmental" | "other"
        "reaction": "皮疹",
        "severity": "moderate"      // "mild" | "moderate" | "severe"
    }
]
```

### 4.8 patients.current_medications (目前用藥)

```jsonc
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

### 4.9 red_flag_alerts.llm_analysis (LLM 語意分析)

```jsonc
{
    // 分析模型與版本
    "model": "claude-sonnet-4-20250514",
    "model_version": "2026-03",

    // 分析結果
    "risk_level": "high",
    "confidence": 0.92,

    // 分析推理
    "reasoning": "病患描述嚴重血尿伴隨腰部劇烈疼痛，可能為腎結石併發或腎臟出血，需緊急處置。",

    // 偵測到的危險訊號
    "detected_signals": [
        {
            "signal": "大量血尿",
            "source_text": "尿液全部都是血，馬桶整個是紅的",
            "clinical_significance": "可能為泌尿道出血"
        },
        {
            "signal": "急性腰痛",
            "source_text": "腰部突然痛到無法站立",
            "clinical_significance": "腎絞痛或腎臟急症"
        }
    ],

    // 建議處置
    "suggested_actions": [
        "立即通知值班醫師",
        "安排急診評估",
        "準備 CT 無顯影劑掃描"
    ],

    // 處理時間戳
    "analyzed_at": "2026-04-10T14:30:00+08:00",
    "processing_time_ms": 1250
}
```

### 4.10 conversations.metadata (對話中繼資料)

```jsonc
{
    // STT 相關
    "stt_engine": "google-chirp-v2",
    "stt_language": "zh-TW",
    "stt_processing_time_ms": 850,
    "stt_alternatives": [
        {
            "text": "我最近尿尿會痛",
            "confidence": 0.95
        },
        {
            "text": "我最近尿尿很痛",
            "confidence": 0.88
        }
    ],

    // TTS 相關 (assistant 角色時)
    "tts_engine": "google-neural2",
    "tts_voice": "cmn-TW-Wavenet-A",
    "tts_processing_time_ms": 320,

    // LLM 相關 (assistant 角色時)
    "llm_model": "claude-sonnet-4-20250514",
    "llm_tokens_used": 256,
    "llm_processing_time_ms": 2100,

    // 紅旗偵測
    "red_flag_scan": {
        "scanned": true,
        "rule_matches": [],
        "semantic_score": 0.12,
        "is_flagged": false
    },

    // 音訊品質
    "audio_quality": {
        "sample_rate": 16000,
        "channels": 1,
        "format": "wav",
        "noise_level": "low",
        "file_size_bytes": 128000
    }
}
```

### 4.11 notifications.data (通知附加資料)

```jsonc
// red_flag 類型
{
    "session_id": "uuid-here",
    "alert_id": "uuid-here",
    "patient_name": "王大明",
    "severity": "critical",
    "trigger_reason": "病患描述大量血尿伴隨劇烈腰痛"
}

// session_complete 類型
{
    "session_id": "uuid-here",
    "patient_name": "李小華",
    "chief_complaint": "頻尿",
    "duration_seconds": 420,
    "has_red_flag": false
}

// report_ready 類型
{
    "session_id": "uuid-here",
    "report_id": "uuid-here",
    "patient_name": "張三",
    "generated_at": "2026-04-10T15:00:00+08:00"
}

// system 類型
{
    "message_code": "SYSTEM_MAINTENANCE",
    "scheduled_at": "2026-04-15T02:00:00+08:00",
    "estimated_duration_minutes": 30
}
```

### 4.12 audit_logs.details (稽核詳情)

```jsonc
// create 操作
{
    "created_data": {
        "session_id": "uuid-here",
        "patient_id": "uuid-here",
        "chief_complaint": "血尿"
    }
}

// update 操作
{
    "before": {
        "status": "in_progress"
    },
    "after": {
        "status": "completed",
        "duration_seconds": 600
    },
    "changed_fields": ["status", "duration_seconds", "completed_at"]
}

// login 操作
{
    "login_method": "password",
    "mfa_used": true,
    "session_token_hash": "sha256:abc123..."
}

// export 操作
{
    "export_type": "soap_report",
    "format": "pdf",
    "resource_ids": ["uuid-1", "uuid-2"],
    "record_count": 2
}
```

---

## 5. Enum 類型定義

以下為所有 PostgreSQL 自定義 ENUM 類型的完整定義。

### 5.1 user_role (使用者角色)

```sql
CREATE TYPE user_role AS ENUM ('patient', 'doctor', 'admin');
```

| 值        | 說明                                       |
|-----------|--------------------------------------------|
| `patient` | 病患，可進行問診、查看自身報告             |
| `doctor`  | 醫師，可審核報告、處理紅旗、管理主訴       |
| `admin`   | 系統管理員，具備所有權限，可管理使用者與設定 |

### 5.2 session_status (問診場次狀態)

```sql
CREATE TYPE session_status AS ENUM (
    'waiting',
    'in_progress',
    'completed',
    'aborted_red_flag',
    'cancelled'
);
```

| 值                 | 說明                                               |
|--------------------|----------------------------------------------------|
| `waiting`          | 等待中，病患已選定主訴、等待問診開始               |
| `in_progress`      | 進行中，AI 問診對話正在進行                        |
| `completed`        | 已完成，問診正常結束並生成 SOAP 報告               |
| `aborted_red_flag` | 紅旗中止，因偵測到危急狀況而中止問診並通知醫師     |
| `cancelled`        | 已取消，病患或系統取消問診                         |

**狀態轉移規則**:
```
waiting --> in_progress --> completed
                       --> aborted_red_flag
waiting --> cancelled
in_progress --> cancelled
```

### 5.3 conversation_role (對話角色)

```sql
CREATE TYPE conversation_role AS ENUM ('patient', 'assistant', 'system');
```

| 值          | 說明                                       |
|-------------|--------------------------------------------|
| `patient`   | 病患發言 (語音轉文字)                      |
| `assistant` | AI 助手回覆 (含語音合成)                   |
| `system`    | 系統訊息 (如紅旗警告、場次狀態變更通知)    |

### 5.4 alert_type (紅旗警示類型)

```sql
CREATE TYPE alert_type AS ENUM ('rule_based', 'semantic', 'combined');
```

| 值           | 說明                                       |
|--------------|--------------------------------------------|
| `rule_based` | 規則式偵測，由關鍵字或正則表達式觸發       |
| `semantic`   | 語意式偵測，由 LLM 語意分析觸發            |
| `combined`   | 混合偵測，同時由規則與語意分析確認觸發     |

### 5.5 alert_severity (嚴重程度)

```sql
CREATE TYPE alert_severity AS ENUM ('critical', 'high', 'medium');
```

| 值         | 說明                                                     |
|------------|----------------------------------------------------------|
| `critical` | 緊急，需立即中止問診並通知醫師 (如大量血尿、急性尿滯留) |
| `high`     | 高度，需儘速通知醫師但可繼續收集資訊                     |
| `medium`   | 中度，標記提醒醫師注意，問診正常進行                     |

### 5.6 report_status (報告狀態)

```sql
CREATE TYPE report_status AS ENUM ('generating', 'generated', 'failed');
```

| 值           | 說明                                       |
|--------------|--------------------------------------------|
| `generating` | 生成中，AI 正在產生 SOAP 報告              |
| `generated`  | 已生成，報告產生完成可供審閱               |
| `failed`     | 失敗，報告生成過程發生錯誤                 |

### 5.7 review_status (審閱狀態)

```sql
CREATE TYPE review_status AS ENUM ('pending', 'approved', 'revision_needed');
```

| 值                | 說明                                       |
|-------------------|--------------------------------------------|
| `pending`         | 待審閱，報告尚未被醫師審閱                 |
| `approved`        | 已核准，醫師已確認報告內容正確             |
| `revision_needed` | 需修改，報告需要修正或補充                 |

### 5.8 notification_type (通知類型)

```sql
CREATE TYPE notification_type AS ENUM (
    'red_flag',
    'session_complete',
    'report_ready',
    'system'
);
```

| 值                | 說明                                       |
|-------------------|--------------------------------------------|
| `red_flag`        | 紅旗警示通知，危急情況需立即處理           |
| `session_complete`| 問診完成通知                               |
| `report_ready`    | SOAP 報告就緒通知                          |
| `system`          | 系統公告通知 (維護、更新等)                |

### 5.9 audit_action (稽核操作類型)

```sql
CREATE TYPE audit_action AS ENUM (
    'create',
    'read',
    'update',
    'delete',
    'login',
    'logout',
    'export',
    'review',
    'acknowledge',
    'session_start',
    'session_end'
);
```

| 值              | 說明                                       |
|-----------------|--------------------------------------------|
| `create`        | 新增資源                                   |
| `read`          | 讀取資源 (僅記錄敏感資料存取)              |
| `update`        | 更新資源                                   |
| `delete`        | 刪除資源                                   |
| `login`         | 使用者登入                                 |
| `logout`        | 使用者登出                                 |
| `export`        | 匯出資料 (PDF、CSV 等)                     |
| `review`        | 審核 SOAP 報告                             |
| `acknowledge`   | 確認紅旗警示                               |
| `session_start` | 問診場次開始                               |
| `session_end`   | 問診場次結束                               |

### 5.10 device_platform (裝置平台)

```sql
CREATE TYPE device_platform AS ENUM ('ios', 'android', 'web');
```

| 值        | 說明             |
|-----------|------------------|
| `ios`     | Apple iOS 裝置   |
| `android` | Android 裝置     |
| `web`     | 網頁瀏覽器 (PWA) |

### 5.11 gender_type (性別)

```sql
CREATE TYPE gender_type AS ENUM ('male', 'female', 'other');
```

| 值       | 說明   |
|----------|--------|
| `male`   | 男性   |
| `female` | 女性   |
| `other`  | 其他   |

---

## 6. Redis 快取策略 (Redis Cache Strategy)

### 6.1 Key 命名規範

所有 Redis key 遵循以下命名規則：

```
{service}:{entity}:{identifier}:{sub-resource}
```

- 使用冒號 (`:`) 作為層級分隔符
- entity 和 sub-resource 使用小寫蛇底線命名 (snake_case)
- identifier 使用實際 ID 值 (UUID 或整數)
- 範例：`gu:session:550e8400-e29b-41d4-a716-446655440000:context`

前綴統一為 `gu:` (代表 GU / Genitourinary)。

### 6.2 Key 定義與結構

#### 6.2.1 session:{id}:context -- 問診對話上下文

用於儲存進行中問診的 LLM 對話上下文，包含歷史訊息、當前主訴、已收集的症狀等。

```
Key:    gu:session:{session_id}:context
Type:   Hash
TTL:    3600 秒 (1 小時)，每次寫入重置
```

| Field                   | 說明                                       |
|-------------------------|--------------------------------------------|
| `chief_complaint`       | 主訴文字                                   |
| `patient_profile`       | JSON 字串 -- 病患基本資料與病史摘要        |
| `conversation_history`  | JSON 字串 -- 最近 N 輪對話 (陣列)          |
| `collected_symptoms`    | JSON 字串 -- 已收集的症狀清單              |
| `current_question_flow` | JSON 字串 -- 目前問診流程與分支狀態        |
| `red_flag_context`      | JSON 字串 -- 紅旗偵測累積上下文            |
| `turn_count`            | 對話輪數                                   |
| `last_updated`          | 最後更新的 ISO 8601 時間戳                 |

**使用場景**:
- LLM 生成下一個問題時讀取完整上下文
- 每輪對話結束後更新
- 問診結束或超時後自動失效

```python
# 寫入範例 (Python / redis-py)
pipe = redis.pipeline()
pipe.hset(f"gu:session:{session_id}:context", mapping={
    "chief_complaint": "頻尿",
    "conversation_history": json.dumps(messages),
    "collected_symptoms": json.dumps(symptoms),
    "turn_count": "5",
    "last_updated": datetime.utcnow().isoformat()
})
pipe.expire(f"gu:session:{session_id}:context", 3600)
pipe.execute()
```

#### 6.2.2 session:{id}:state -- 問診場次狀態快取

快取問診場次的核心狀態，避免頻繁查詢資料庫。

```
Key:    gu:session:{session_id}:state
Type:   Hash
TTL:    1800 秒 (30 分鐘)
```

| Field              | 說明                                       |
|--------------------|--------------------------------------------|
| `status`           | 場次狀態 (waiting/in_progress/...)         |
| `patient_id`       | 病患 UUID                                  |
| `doctor_id`        | 醫師 UUID                                  |
| `chief_complaint`  | 主訴名稱                                   |
| `red_flag`         | 是否觸發紅旗 (true/false)                  |
| `started_at`       | 開始時間                                   |
| `message_count`    | 對話訊息數                                 |

**使用場景**:
- 前端輪詢場次狀態
- WebSocket 連線時快速取得場次基本資訊
- 候診佇列顯示

#### 6.2.3 user:{id}:profile -- 使用者資料快取

快取使用者基本資料，減少 users/patients 表的查詢壓力。

```
Key:    gu:user:{user_id}:profile
Type:   Hash
TTL:    3600 秒 (1 小時)
```

```jsonc
{
    "id": "uuid",
    "email": "doctor@example.com",
    "name": "陳醫師",
    "role": "doctor",
    "department": "泌尿科",
    "is_active": true
}
```

**使用場景**:
- API 請求的身分驗證與授權檢查
- 顯示使用者名稱等常用資訊

**快取失效策略**:
- 使用者更新個人資料時主動刪除
- TTL 自動過期

#### 6.2.4 dashboard:stats:{doctor_id} -- 儀表板統計快取

快取醫師儀表板的統計數據，避免複雜聚合查詢。

```
Key:    gu:dashboard:stats:{doctor_id}
Type:   String (JSON)
TTL:    300 秒 (5 分鐘)
```

```jsonc
{
    "today": {
        "total_sessions": 12,
        "completed_sessions": 8,
        "in_progress_sessions": 2,
        "waiting_sessions": 2,
        "red_flag_count": 1,
        "avg_duration_seconds": 480
    },
    "week": {
        "total_sessions": 65,
        "completed_sessions": 60,
        "red_flag_count": 3
    },
    "pending_reviews": 5,
    "unacknowledged_alerts": 1,
    "generated_at": "2026-04-10T09:00:00+08:00"
}
```

**使用場景**:
- 醫師登入後的儀表板頁面
- 定時更新 (最多每 5 分鐘重新計算一次)

#### 6.2.5 alert:active:{doctor_id} -- 進行中紅旗警示

儲存醫師負責的所有未確認紅旗警示，用於即時通知。

```
Key:    gu:alert:active:{doctor_id}
Type:   Sorted Set
TTL:    不設定 (由應用邏輯管理)
Score:  Unix timestamp (建立時間)
Member: JSON 字串
```

```jsonc
// 每個 member 的 JSON 結構
{
    "alert_id": "uuid",
    "session_id": "uuid",
    "patient_name": "王大明",
    "severity": "critical",
    "trigger_reason": "大量血尿伴隨劇痛",
    "created_at": "2026-04-10T14:30:00+08:00"
}
```

**使用場景**:
- 醫師端即時顯示紅旗警示徽章與數量
- WebSocket 推播新警示
- 醫師確認警示後從 Sorted Set 中移除

**管理規則**:
- 新增紅旗警示時 ZADD
- 醫師確認警示時 ZREM
- 定期清理已確認或過期的項目

#### 6.2.6 queue:patients -- 病患候診佇列

管理等待中的病患佇列，支援優先度排序。

```
Key:    gu:queue:patients
Type:   Sorted Set
TTL:    不設定 (由應用邏輯管理)
Score:  優先度分數 (越低越優先，由掛號時間和緊急度計算)
Member: JSON 字串
```

Score 計算公式:
```
score = base_timestamp - (priority_boost * 1000)

其中:
- base_timestamp = 掛號的 Unix timestamp
- priority_boost = 0 (一般) / 60 (優先) / 300 (緊急)
```

```jsonc
// 每個 member 的 JSON 結構
{
    "session_id": "uuid",
    "patient_id": "uuid",
    "patient_name": "李小華",
    "chief_complaint": "急性尿滯留",
    "priority": "urgent",
    "queued_at": "2026-04-10T08:30:00+08:00"
}
```

**使用場景**:
- 護理站候診螢幕顯示
- 呼叫下一位病患
- 候診人數統計

#### 6.2.7 token_blacklist:{jti} -- Access Token 黑名單

儲存已撤銷的 Access Token JTI，用於登出或 Token 失效。

```
Key:    gu:token_blacklist:{jti}
Type:   String
TTL:    等同 Access Token 剩餘有效期
Value:  "1" (僅標記存在)
```

**使用場景**:
- 使用者登出時將 Access Token 加入黑名單
- 每次 API 請求驗證 Token 時檢查黑名單
- TTL 到期後自動清除（Token 本身也已過期）

#### 6.2.8 refresh_token:{jti} -- Refresh Token 管理

儲存有效的 Refresh Token 資訊，用於 Token 輪換與管理。

```
Key:    gu:refresh_token:{jti}
Type:   String
TTL:    604800 秒 (7 天，等同 Refresh Token 有效期)
Value:  JSON 字串
```

```jsonc
{
    "user_id": "uuid",
    "issued_at": "2026-04-10T08:00:00+08:00",
    "device_info": "iPhone 15 Pro"
}
```

**使用場景**:
- Refresh Token 輪換時驗證舊 Token 有效性
- 強制登出時可直接刪除對應 Key

#### 6.2.9 complaints:defaults -- 預設主訴清單快取

快取系統預設的主訴清單，減少資料庫查詢。

```
Key:    gu:complaints:defaults
Type:   String (JSON)
TTL:    3600 秒 (1 小時)
Value:  JSON 字串（完整的主訴分類與項目）
```

**使用場景**:
- 病患建立問診場次時載入主訴選項
- 主訴清單變更時主動失效

**快取失效策略**:
- 管理員新增/修改/刪除主訴時主動刪除此 Key

#### 6.2.10 notifications:unread:{user_id} -- 未讀通知計數快取

快取使用者的未讀通知數量，避免頻繁 COUNT 查詢。

```
Key:    gu:notifications:unread:{user_id}
Type:   String (int)
TTL:    300 秒 (5 分鐘)
Value:  未讀通知數量
```

**使用場景**:
- 前端 Header 區域的未讀通知徽章數字
- 新通知送出時遞增 (INCR)
- 標記已讀時遞減 (DECR) 或刪除重新計算

### 6.3 TTL 策略總覽

| Key Pattern                                | TTL        | 說明                               |
|--------------------------------------------|------------|------------------------------------|
| `gu:session:{id}:context`                  | 3600s      | 問診上下文，1 小時無活動即失效     |
| `gu:session:{id}:state`                    | 1800s      | 場次狀態，30 分鐘自動更新          |
| `gu:user:{id}:profile`                     | 3600s      | 使用者資料，1 小時更新              |
| `gu:dashboard:stats:{id}`                  | 300s       | 儀表板統計，5 分鐘更新              |
| `gu:alert:active:{id}`                     | 無 TTL     | 由確認操作主動清除                 |
| `gu:queue:patients`                        | 無 TTL     | 由候診流程主動管理                 |
| `gu:token_blacklist:{jti}`                 | Token 剩餘效期 | Access Token 過期後自動清除    |
| `gu:refresh_token:{jti}`                   | 604800s    | Refresh Token 有效期 (7 天)        |
| `gu:complaints:defaults`                   | 3600s      | 主訴清單，1 小時更新               |
| `gu:notifications:unread:{user_id}`        | 300s       | 未讀通知計數，5 分鐘更新           |

### 6.4 快取失效策略 (Cache Invalidation)

採用 **Write-Through + Event-Driven Invalidation** 策略：

**Write-Through (寫穿策略)**:
- 對話上下文 (`session:context`) 每輪對話結束後同步寫入 Redis 與 PostgreSQL
- 確保 Redis 與資料庫一致

**Event-Driven Invalidation (事件驅動失效)**:
- 使用者修改個人資料時：刪除 `gu:user:{id}:profile`
- 問診狀態變更時：更新 `gu:session:{id}:state`，失效 `gu:dashboard:stats:{doctor_id}`
- 紅旗警示確認時：ZREM `gu:alert:active:{doctor_id}` 對應項目
- 病患離開候診：ZREM `gu:queue:patients` 對應項目
- 主訴清單變更時：刪除 `gu:complaints:defaults`
- 新通知送出時：INCR `gu:notifications:unread:{user_id}`
- 使用者登出時：SET `gu:token_blacklist:{jti}`，DEL `gu:refresh_token:{jti}`

**防雪崩機制**:
- TTL 加入隨機偏移量 (jitter)，避免大量 key 同時失效
- 實作範例：`TTL = base_ttl + random(0, base_ttl * 0.1)`

**防穿透機制**:
- 對不存在的資源，快取空值 (null marker) 並設定短 TTL (60 秒)
- 避免持續查詢資料庫

---

## 7. 資料分割與保留策略 (Partitioning & Retention)

### 7.1 分割策略

#### 7.1.1 conversations 表 -- 按月份 Range Partitioning

由於對話紀錄為系統中資料量最大的表 (每場問診平均 20-50 筆對話)，採用按月份的 Range Partitioning。

**分割鍵**: `created_at` (TIMESTAMPTZ)

**分割區命名規則**: `conversations_y{YYYY}m{MM}`

**優點**:
- 查詢特定時間範圍的對話時，PostgreSQL 可自動裁剪 (prune) 不相關的分割區
- 可對舊分割區進行壓縮或遷移至冷儲存
- 刪除舊資料時只需卸載 (detach) 分割區，避免大量 DELETE 操作

#### 7.1.2 audit_logs 表 -- 按月份 Range Partitioning

稽核日誌為附加寫入 (append-only) 模式，資料量持續增長，同樣採用月份分割。

**分割鍵**: `created_at` (TIMESTAMPTZ)

**分割區命名規則**: `audit_logs_y{YYYY}m{MM}`

### 7.2 分割區自動管理

使用定期排程 (cron job 或 pg_cron) 自動建立未來分割區並清理過期分割區。

```sql
-- 安裝 pg_cron 擴充套件
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- 每月 1 號自動建立下個月的分割區
SELECT cron.schedule('create_partitions_monthly', '0 0 1 * *', $$
    DO $body$
    DECLARE
        next_month_start DATE;
        next_month_end DATE;
        partition_name_conv TEXT;
        partition_name_audit TEXT;
    BEGIN
        -- 計算下下個月的日期 (預先建立)
        next_month_start := date_trunc('month', NOW() + INTERVAL '2 months')::DATE;
        next_month_end := (next_month_start + INTERVAL '1 month')::DATE;

        partition_name_conv := 'conversations_y'
            || to_char(next_month_start, 'YYYY')
            || 'm'
            || to_char(next_month_start, 'MM');

        partition_name_audit := 'audit_logs_y'
            || to_char(next_month_start, 'YYYY')
            || 'm'
            || to_char(next_month_start, 'MM');

        -- 建立 conversations 分割區
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF conversations FOR VALUES FROM (%L) TO (%L)',
            partition_name_conv, next_month_start, next_month_end
        );

        -- 建立 audit_logs 分割區
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_logs FOR VALUES FROM (%L) TO (%L)',
            partition_name_audit, next_month_start, next_month_end
        );

        RAISE NOTICE 'Created partitions: %, %', partition_name_conv, partition_name_audit;
    END $body$;
$$);
```

### 7.3 資料保留策略

| 資料類型                     | 保留期限    | 處理方式                                       |
|------------------------------|-------------|------------------------------------------------|
| conversations (對話紀錄)     | 3 年        | 超過 3 年的分割區卸載並匯出至冷儲存 (S3 Glacier)|
| audit_logs (稽核日誌)        | 7 年        | 符合醫療法規要求，7 年後歸檔至冷儲存           |
| sessions (問診場次)          | 永久保留    | 核心業務資料，不主動刪除                       |
| soap_reports (SOAP 報告)     | 永久保留    | 病歷資料依法須長期保存                         |
| patients (病患資料)          | 永久保留    | 病患主檔，不主動刪除                           |
| red_flag_alerts (紅旗警示)   | 5 年        | 超過 5 年後歸檔                                |
| red_flag_rules (紅旗規則)    | 永久保留    | 規則設定，不主動刪除                           |
| notifications (通知)         | 1 年        | 超過 1 年後清除                                |
| fcm_devices (裝置 token)     | 即時管理    | 無效 token 於推播失敗時標記停用並定期清理      |
| S3 音檔                      | 3 年        | 與 conversations 同步管理                      |

### 7.4 分割區過期清理腳本

```sql
-- 清理超過保留期限的 conversations 分割區
-- 排程：每月 1 號執行
SELECT cron.schedule('cleanup_old_conversations', '0 2 1 * *', $$
    DO $body$
    DECLARE
        cutoff_date DATE;
        partition_record RECORD;
    BEGIN
        cutoff_date := (NOW() - INTERVAL '3 years')::DATE;

        FOR partition_record IN
            SELECT inhrelid::regclass::text AS partition_name
            FROM pg_inherits
            WHERE inhparent = 'conversations'::regclass
            AND inhrelid::regclass::text != 'conversations_default'
        LOOP
            -- 檢查分割區是否超過保留期限
            -- (實際實作需解析分割區名稱中的年月)
            -- 此處為示意，正式環境應使用 pg_partition_info 或自訂管理表
            RAISE NOTICE 'Checking partition: %', partition_record.partition_name;
        END LOOP;
    END $body$;
$$);
```

**正式清理流程**:

1. 確認分割區內所有關聯資料已匯出至冷儲存
2. 卸載分割區：`ALTER TABLE conversations DETACH PARTITION conversations_y2023m01`
3. 匯出分割區資料至 S3 (pg_dump 或 COPY)
4. 確認匯出完整後刪除分割區：`DROP TABLE conversations_y2023m01`
5. 記錄清理操作至 audit_logs

---

## 8. 遷移策略 (Migration Strategy)

### 8.1 Alembic 配置

#### alembic.ini 核心設定

```ini
[alembic]
script_location = alembic
file_template = %%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d_%%(rev)s_%%(slug)s
timezone = Asia/Taipei
sqlalchemy.url = driver://user:pass@localhost/dbname

[post_write_hooks]
hooks = ruff
ruff.type = exec
ruff.executable = ruff
ruff.options = format REVISION_SCRIPT_FILENAME
```

#### env.py 核心設定

```python
from alembic import context
from sqlalchemy import engine_from_config, pool
from app.models import Base  # 所有 SQLAlchemy Model 的 Base

target_metadata = Base.metadata

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
            # 支援 ENUM 類型的比對
            render_as_batch=False,
        )

        with context.begin_transaction():
            context.run_migrations()
```

### 8.2 遷移命名規範

**檔案命名格式**:
```
{YYYY}_{MM}_{DD}_{HH}{mm}_{revision_hash}_{description}.py
```

**範例**:
```
2026_04_10_0900_a1b2c3d4e5f6_create_users_table.py
2026_04_10_0905_b2c3d4e5f6a7_create_patients_table.py
2026_04_10_0910_c3d4e5f6a7b8_create_chief_complaints_table.py
2026_04_10_0915_d4e5f6a7b8c9_create_sessions_table.py
2026_04_10_0920_e5f6a7b8c9d0_create_conversations_partitioned.py
2026_04_10_0925_f6a7b8c9d0e1_create_soap_reports_table.py
2026_04_10_0930_a7b8c9d0e1f2_create_red_flag_rules_table.py
2026_04_10_0935_b8c9d0e1f2a3_create_red_flag_alerts_table.py
2026_04_10_0940_c9d0e1f2a3b4_create_notifications_table.py
2026_04_10_0945_d0e1f2a3b4c5_create_audit_logs_partitioned.py
2026_04_10_0950_e1f2a3b4c5d6_create_fcm_devices_table.py
2026_04_10_1000_f2a3b4c5d6e7_create_indexes.py
2026_04_10_1005_a3b4c5d6e7f8_seed_default_data.py
```

**Description 命名規則**:
- `create_{table_name}_table` -- 建立新表
- `add_{column}_to_{table}` -- 新增欄位
- `alter_{column}_in_{table}` -- 修改欄位
- `drop_{column}_from_{table}` -- 刪除欄位
- `create_indexes` -- 建立索引
- `seed_default_data` -- 初始化預設資料
- `add_{feature}_support` -- 功能擴充

### 8.3 遷移執行順序

由於表之間存在外鍵依賴關係，遷移必須嚴格按照以下順序執行：

```
1. ENUM 類型建立
2. users (無外鍵依賴)
3. patients (依賴 users)
4. chief_complaints (依賴 users)
5. sessions (依賴 patients, users, chief_complaints)
6. conversations (依賴 sessions) -- 含分割區建立
7. soap_reports (依賴 sessions, users)
8. red_flag_rules (依賴 users)
9. red_flag_alerts (依賴 sessions, red_flag_rules, users)
10. notifications (依賴 users)
11. audit_logs -- 含分割區建立 (依賴 users)
12. fcm_devices (依賴 users)
13. 索引建立
14. Trigger 函式建立
15. Seed 資料匯入
```

### 8.4 Seed Data (初始化資料)

#### 8.4.1 預設管理員帳號

```sql
INSERT INTO users (id, email, password_hash, name, role, is_active)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'admin@gu-ai.local',
    -- bcrypt hash of a secure initial password (需部署後立即修改)
    '$2b$12$LJ3m4ys5RRwZ5GpFqVV8qOJdHnOzLLCmjKqGplGblXgBMkX2KE/Ey',
    '系統管理員',
    'admin',
    TRUE
);
```

#### 8.4.2 預設泌尿科主訴清單

使用 shared_types.md 定義的 6 大分類：排尿症狀、血尿與異常、疼痛、腫塊與外觀、性功能障礙、其他。

```sql
INSERT INTO chief_complaints (id, name, name_en, description, category, is_default, display_order) VALUES
-- 排尿症狀類
(gen_random_uuid(), '頻尿', 'Frequent Urination', '排尿次數異常增加，日間超過 8 次或夜間超過 2 次', '排尿症狀', TRUE, 1),
(gen_random_uuid(), '急尿', 'Urinary Urgency', '突然強烈的排尿慾望，難以控制', '排尿症狀', TRUE, 2),
(gen_random_uuid(), '夜尿', 'Nocturia', '夜間需起床排尿 2 次以上', '排尿症狀', TRUE, 3),
(gen_random_uuid(), '排尿困難', 'Difficulty Urinating', '排尿時需用力，尿流變細或中斷', '排尿症狀', TRUE, 4),
(gen_random_uuid(), '尿滯留', 'Urinary Retention', '無法排空膀胱或完全無法排尿', '排尿症狀', TRUE, 5),
(gen_random_uuid(), '尿失禁', 'Urinary Incontinence', '不自主漏尿', '排尿症狀', TRUE, 6),
(gen_random_uuid(), '排尿疼痛', 'Dysuria', '排尿時有燒灼感或疼痛', '排尿症狀', TRUE, 7),

-- 血尿與異常類
(gen_random_uuid(), '血尿', 'Hematuria', '尿液中帶血，肉眼可見或檢驗發現', '血尿與異常', TRUE, 10),
(gen_random_uuid(), '尿液混濁', 'Cloudy Urine', '尿液呈現混濁或異常顏色', '血尿與異常', TRUE, 11),
(gen_random_uuid(), '泡沫尿', 'Foamy Urine', '尿液表面泡沫持續不消', '血尿與異常', TRUE, 12),

-- 疼痛類
(gen_random_uuid(), '腰痛', 'Flank Pain', '單側或雙側腰部疼痛', '疼痛', TRUE, 20),
(gen_random_uuid(), '下腹痛', 'Lower Abdominal Pain', '恥骨上方或下腹部疼痛', '疼痛', TRUE, 21),
(gen_random_uuid(), '陰囊疼痛', 'Scrotal Pain', '單側或雙側陰囊疼痛或腫脹', '疼痛', TRUE, 22),
(gen_random_uuid(), '會陰部疼痛', 'Perineal Pain', '會陰區域不適或疼痛', '疼痛', TRUE, 23),

-- 腫塊與外觀類
(gen_random_uuid(), '陰囊腫塊', 'Scrotal Mass', '陰囊內觸摸到異常腫塊', '腫塊與外觀', TRUE, 30),
(gen_random_uuid(), '腹股溝腫塊', 'Inguinal Mass', '腹股溝區域有腫塊', '腫塊與外觀', TRUE, 31),
(gen_random_uuid(), '包皮問題', 'Foreskin Issue', '包皮過長、嵌頓或其他異常', '腫塊與外觀', TRUE, 32),

-- 性功能障礙類
(gen_random_uuid(), '勃起功能障礙', 'Erectile Dysfunction', '無法達到或維持足夠硬度的勃起', '性功能障礙', TRUE, 40),
(gen_random_uuid(), '早洩', 'Premature Ejaculation', '射精發生在期望之前', '性功能障礙', TRUE, 41),
(gen_random_uuid(), '血精', 'Hematospermia', '精液中帶血', '性功能障礙', TRUE, 42),

-- 其他
(gen_random_uuid(), '腎結石追蹤', 'Kidney Stone Follow-up', '已知腎結石需追蹤評估', '其他', TRUE, 50),
(gen_random_uuid(), 'PSA 異常', 'Abnormal PSA', '攝護腺特異抗原指數異常', '其他', TRUE, 51),
(gen_random_uuid(), '其他泌尿科問題', 'Other Urological Issue', '未列於上述項目的泌尿科相關問題', '其他', TRUE, 99);
```

#### 8.4.3 預設紅旗規則

```sql
-- 需先建立一個系統管理員帳號作為 created_by
-- 使用上方建立的管理員 UUID

INSERT INTO red_flag_rules (id, name, description, category, keywords, regex_pattern, severity, is_active, suggested_action, suspected_diagnosis, created_by) VALUES
-- 泌尿道急症
(gen_random_uuid(),
 '急性尿滯留',
 '病患完全無法排尿，膀胱脹滿',
 '泌尿道急症',
 ARRAY['尿不出來', '完全無法排尿', '膀胱快爆了', '脹到受不了', '好幾個小時沒尿'],
 '(完全|都|整天).*(無法|不能|沒辦法).*排尿',
 'critical',
 TRUE,
 '立即安排導尿，通知值班泌尿科醫師',
 '急性尿滯留 (R33.9)',
 '00000000-0000-0000-0000-000000000001'),

(gen_random_uuid(),
 '大量血尿',
 '大量肉眼可見血尿，尿液呈鮮紅色',
 '泌尿道急症',
 ARRAY['整個都是血', '鮮紅色的尿', '血塊', '馬桶都是血', '大量出血', '血流不止'],
 '(大量|很多|全部|整個|滿).*血',
 'critical',
 TRUE,
 '立即安排急診評估，檢查凝血功能及影像學檢查',
 '血尿 (R31.0)',
 '00000000-0000-0000-0000-000000000001'),

(gen_random_uuid(),
 '急性陰囊痛',
 '突發性嚴重陰囊疼痛，疑似睪丸扭轉',
 '泌尿道急症',
 ARRAY['睪丸突然很痛', '陰囊劇痛', '蛋蛋腫起來', '突然腫痛'],
 '(睪丸|陰囊|蛋蛋).*(突然|劇|非常|超級).*(痛|腫)',
 'critical',
 TRUE,
 '疑似睪丸扭轉，需於 6 小時內手術探查，立即聯繫值班醫師',
 '睪丸扭轉 (N44.0)',
 '00000000-0000-0000-0000-000000000001'),

(gen_random_uuid(),
 '發燒合併泌尿道症狀',
 '發燒合併泌尿道感染症狀，疑似腎盂腎炎或敗血症',
 '感染急症',
 ARRAY['發高燒', '發燒', '畏寒', '全身發抖', '忽冷忽熱'],
 '(發燒|高燒|體溫).*(排尿|尿|腰痛)',
 'high',
 TRUE,
 '評估是否為腎盂腎炎或 urosepsis，安排血液培養、尿液培養',
 '急性腎盂腎炎 (N10) / 泌尿道敗血症',
 '00000000-0000-0000-0000-000000000001'),

(gen_random_uuid(),
 '腎絞痛',
 '突發性嚴重腰部疼痛，疑似腎結石',
 '疼痛急症',
 ARRAY['腰痛到打滾', '痛到冒冷汗', '劇烈腰痛', '痛到無法站', '痛到想吐'],
 '(腰|側腹).*(劇|極|非常|超).*(痛|不舒服)',
 'high',
 TRUE,
 '安排 CT 或超音波確認結石位置，給予止痛處置',
 '腎結石合併腎絞痛 (N20.0)',
 '00000000-0000-0000-0000-000000000001'),

(gen_random_uuid(),
 '可疑惡性腫瘤徵兆',
 '無痛性血尿、不明原因體重減輕等腫瘤警訊',
 '腫瘤警訊',
 ARRAY['體重減輕', '瘦了很多', '摸到硬塊', '不明原因消瘦', '腫塊越來越大'],
 '(體重|瘦).*(減輕|下降|掉).*(\d+).*公斤',
 'high',
 TRUE,
 '安排影像學檢查 (CT/MRI)，考慮轉介腫瘤科',
 '泌尿道惡性腫瘤待排除',
 '00000000-0000-0000-0000-000000000001'),

(gen_random_uuid(),
 '嵌頓性包莖',
 '包皮無法推回，造成龜頭水腫',
 '泌尿道急症',
 ARRAY['包皮卡住', '推不回去', '龜頭腫起來', '包皮腫'],
 '包皮.*(卡|推不|退不|縮不)',
 'critical',
 TRUE,
 '需緊急徒手復位或手術處置，避免組織壞死',
 '嵌頓性包莖 (N47.0)',
 '00000000-0000-0000-0000-000000000001'),

(gen_random_uuid(),
 '持續性勃起',
 '勃起持續超過 4 小時，為泌尿科急症',
 '泌尿道急症',
 ARRAY['勃起不消', '一直硬著', '硬了好幾個小時', '消不下去'],
 '(勃起|硬).*(不消|不退|好幾|超過).*(小時|個鐘頭)',
 'critical',
 TRUE,
 '為泌尿科急症，需於 4-6 小時內處置，避免永久性功能損傷',
 '持續性勃起 (N48.3)',
 '00000000-0000-0000-0000-000000000001');
```

### 8.5 Rollback 程序

#### 8.5.1 一般性 Rollback

```bash
# 回退一個版本
alembic downgrade -1

# 回退到特定版本
alembic downgrade a1b2c3d4e5f6

# 回退到初始狀態 (危險操作)
alembic downgrade base
```

#### 8.5.2 Rollback 安全規範

1. **執行前必須備份**：任何 rollback 前須先執行完整資料庫備份
2. **確認影響範圍**：使用 `alembic history` 確認回退路徑上的所有遷移
3. **測試 downgrade 腳本**：所有遷移必須撰寫 `downgrade()` 函式
4. **停機視窗**：涉及資料表結構變更的 rollback 應在停機視窗進行
5. **資料保全**：若 rollback 涉及欄位刪除，須先確認資料已備份

#### 8.5.3 Rollback 腳本範例

```python
def upgrade():
    op.add_column('sessions', sa.Column('priority', sa.Integer(), nullable=True))

def downgrade():
    # 先備份即將刪除的欄位資料
    op.execute("""
        CREATE TABLE IF NOT EXISTS _backup_sessions_priority AS
        SELECT id, priority FROM sessions WHERE priority IS NOT NULL
    """)
    op.drop_column('sessions', 'priority')
```

---

## 9. 備份與災難復原 (Backup & Recovery)

### 9.1 WAL Archiving 配置

#### postgresql.conf 設定

```ini
# WAL 基本設定
wal_level = replica
max_wal_senders = 5
wal_keep_size = 1GB

# WAL 歸檔設定
archive_mode = on
archive_command = 'aws s3 cp %p s3://gu-ai-wal-archive/%f --sse AES256'
archive_timeout = 300

# 效能相關
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9
max_wal_size = 2GB
min_wal_size = 512MB
```

#### WAL 歸檔腳本 (archive_command 進階版)

```bash
#!/bin/bash
# /opt/gu-ai/scripts/archive_wal.sh

WAL_FILE=$1
WAL_PATH=$2
S3_BUCKET="s3://gu-ai-wal-archive"
DATE_PREFIX=$(date +%Y/%m/%d)

# 壓縮 WAL 檔案
gzip -c "$WAL_PATH" > "/tmp/${WAL_FILE}.gz"

# 上傳至 S3
aws s3 cp "/tmp/${WAL_FILE}.gz" \
    "${S3_BUCKET}/${DATE_PREFIX}/${WAL_FILE}.gz" \
    --sse AES256 \
    --storage-class STANDARD_IA

# 清理暫存
rm -f "/tmp/${WAL_FILE}.gz"

# 記錄歸檔日誌
echo "$(date +%Y-%m-%dT%H:%M:%S) Archived: ${WAL_FILE}" >> /var/log/gu-ai/wal_archive.log

exit $?
```

### 9.2 備份排程

#### 9.2.1 完整備份 (Full Backup)

```bash
#!/bin/bash
# /opt/gu-ai/scripts/full_backup.sh
# 排程：每日 02:00 AM (透過 crontab)

BACKUP_DIR="/opt/gu-ai/backups"
S3_BUCKET="s3://gu-ai-db-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="gu_ai_full_${TIMESTAMP}"

# 使用 pg_basebackup 進行實體備份
pg_basebackup \
    -h localhost \
    -U replication_user \
    -D "${BACKUP_DIR}/${BACKUP_NAME}" \
    --format=tar \
    --gzip \
    --checkpoint=fast \
    --wal-method=stream \
    --label="${BACKUP_NAME}"

# 上傳至 S3
aws s3 sync "${BACKUP_DIR}/${BACKUP_NAME}" \
    "${S3_BUCKET}/full/${TIMESTAMP}/" \
    --sse AES256

# 清理本地備份 (保留最近 3 天)
find "${BACKUP_DIR}" -name "gu_ai_full_*" -mtime +3 -exec rm -rf {} +

# 通知
echo "Full backup completed: ${BACKUP_NAME}" | \
    mail -s "[GU-AI] Database Backup Success" dba@hospital.local
```

#### 9.2.2 邏輯備份 (Logical Backup)

```bash
#!/bin/bash
# /opt/gu-ai/scripts/logical_backup.sh
# 排程：每日 03:00 AM

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
S3_BUCKET="s3://gu-ai-db-backups"

# 邏輯備份 (custom format，支援平行還原)
pg_dump \
    -h localhost \
    -U backup_user \
    -d gu_ai_production \
    --format=custom \
    --compress=9 \
    --jobs=4 \
    --file="/tmp/gu_ai_logical_${TIMESTAMP}.dump"

# 上傳至 S3
aws s3 cp "/tmp/gu_ai_logical_${TIMESTAMP}.dump" \
    "${S3_BUCKET}/logical/gu_ai_logical_${TIMESTAMP}.dump" \
    --sse AES256

rm -f "/tmp/gu_ai_logical_${TIMESTAMP}.dump"
```

#### 9.2.3 備份排程總覽

| 備份類型     | 頻率             | 保留期限 | 儲存位置               |
|--------------|------------------|----------|------------------------|
| WAL 歸檔     | 持續 (每 5 分鐘) | 30 天    | S3 Standard-IA         |
| 完整實體備份 | 每日 02:00       | 30 天    | S3 Standard            |
| 邏輯備份     | 每日 03:00       | 90 天    | S3 Standard            |
| 每週完整備份 | 每週日 01:00     | 1 年     | S3 Glacier             |
| 每月歸檔     | 每月 1 日        | 7 年     | S3 Glacier Deep Archive|

### 9.3 Point-in-Time Recovery (PITR) 程序

#### 9.3.1 還原步驟

```bash
#!/bin/bash
# Point-in-Time Recovery 程序
# 適用情境：資料誤刪、資料損毀等需回復到特定時間點的情況

# 步驟 1: 停止 PostgreSQL 服務
sudo systemctl stop postgresql

# 步驟 2: 備份目前的資料目錄 (安全起見)
sudo mv /var/lib/postgresql/15/main /var/lib/postgresql/15/main_corrupted_$(date +%Y%m%d)

# 步驟 3: 從最近的完整備份還原
LATEST_BACKUP=$(aws s3 ls s3://gu-ai-db-backups/full/ --recursive | sort | tail -1 | awk '{print $4}')
aws s3 sync "s3://gu-ai-db-backups/full/${LATEST_BACKUP}" /var/lib/postgresql/15/main/

# 步驟 4: 從 S3 下載 WAL 歸檔
# 建立 WAL 還原目錄
mkdir -p /var/lib/postgresql/15/wal_restore

# 步驟 5: 設定還原配置
cat > /var/lib/postgresql/15/main/postgresql.auto.conf << 'RECOVERY_CONF'
# PITR 還原設定
restore_command = 'aws s3 cp s3://gu-ai-wal-archive/%f.gz /tmp/%f.gz && gunzip -c /tmp/%f.gz > %p && rm /tmp/%f.gz'
recovery_target_time = '2026-04-10 14:30:00+08'
recovery_target_action = 'pause'
RECOVERY_CONF

# 步驟 6: 建立還原信號檔
touch /var/lib/postgresql/15/main/recovery.signal

# 步驟 7: 修正權限
sudo chown -R postgres:postgres /var/lib/postgresql/15/main

# 步驟 8: 啟動 PostgreSQL (進入還原模式)
sudo systemctl start postgresql

# 步驟 9: 驗證還原結果
# 連線至資料庫確認資料完整性
psql -U postgres -d gu_ai_production -c "SELECT COUNT(*) FROM sessions;"
psql -U postgres -d gu_ai_production -c "SELECT MAX(created_at) FROM conversations;"

# 步驟 10: 確認無誤後結束還原模式
psql -U postgres -c "SELECT pg_wal_replay_resume();"
```

#### 9.3.2 還原驗證檢查清單

```sql
-- 1. 確認所有表存在且資料完整
SELECT schemaname, tablename, n_live_tup
FROM pg_stat_user_tables
ORDER BY tablename;

-- 2. 確認最新資料時間點
SELECT 'sessions' AS table_name, MAX(created_at) AS latest_record FROM sessions
UNION ALL
SELECT 'conversations', MAX(created_at) FROM conversations
UNION ALL
SELECT 'soap_reports', MAX(created_at) FROM soap_reports
UNION ALL
SELECT 'red_flag_alerts', MAX(created_at) FROM red_flag_alerts;

-- 3. 確認外鍵完整性
SELECT conname, conrelid::regclass, confrelid::regclass
FROM pg_constraint
WHERE contype = 'f'
  AND NOT convalidated;

-- 4. 確認序列值正確
SELECT sequencename, last_value
FROM pg_sequences
WHERE schemaname = 'public';

-- 5. 確認分割區完整性
SELECT parent.relname AS parent_table,
       child.relname AS partition_name
FROM pg_inherits
JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
JOIN pg_class child ON pg_inherits.inhrelid = child.oid
WHERE parent.relname IN ('conversations', 'audit_logs')
ORDER BY parent.relname, child.relname;
```

### 9.4 RTO / RPO 目標

| 指標                          | 目標值   | 說明                                        |
|-------------------------------|----------|---------------------------------------------|
| **RPO** (Recovery Point Objective) | 5 分鐘   | 最多可接受遺失最近 5 分鐘的資料 (WAL 歸檔間隔) |
| **RTO** (Recovery Time Objective)  | 1 小時   | 從災難發生到系統完全恢復的最大時間           |
| 完整備份還原時間              | 30 分鐘  | 從 S3 下載並還原完整備份                     |
| WAL 重播時間                  | 15 分鐘  | 重播 WAL 至目標時間點                        |
| 驗證與切換時間                | 15 分鐘  | 還原後驗證資料完整性與服務切換               |

### 9.5 災難復原演練

建議每季 (每 3 個月) 進行一次災難復原演練，確保：

1. **備份可用性**：確認 S3 上的備份檔案完整且可下載
2. **還原流程正確**：在獨立環境中執行完整 PITR 流程
3. **RPO 達標**：確認 WAL 歸檔的連續性，無遺失
4. **RTO 達標**：記錄實際還原所需時間，確認在目標範圍內
5. **團隊能力**：確保至少 2 名團隊成員具備獨立執行還原的能力

**演練紀錄表**:

| 項目                 | 紀錄內容                     |
|----------------------|------------------------------|
| 演練日期             | YYYY-MM-DD                   |
| 執行人員             | 姓名                         |
| 使用備份時間點       | YYYY-MM-DD HH:MM:SS         |
| 還原環境             | staging / 獨立測試環境       |
| 實際還原時間 (分鐘)  | __                           |
| 資料完整性驗證結果   | PASS / FAIL                  |
| 發現的問題           | 描述                         |
| 改善措施             | 描述                         |

---

## 附錄 A: SQLAlchemy Model 範例 (供開發參考)

以下為部分核心 Model 的 SQLAlchemy 2.0 實作範例：

```python
"""
app/models/base.py
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

```python
"""
app/models/user.py
"""
import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, String, Enum, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid4] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", create_type=False),
        nullable=False,
        default=UserRole.PATIENT,
    )
    phone: Mapped[str | None] = mapped_column(String(20))
    department: Mapped[str | None] = mapped_column(String(100))
    license_number: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Relationships
    patient: Mapped["Patient"] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    fcm_devices: Mapped[list["FCMDevice"]] = relationship(back_populates="user")
```

```python
"""
app/models/session.py
"""
import enum
from uuid import uuid4
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, ForeignKey, Enum, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class SessionStatus(str, enum.Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED_RED_FLAG = "aborted_red_flag"
    CANCELLED = "cancelled"


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[uuid4] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    patient_id: Mapped[uuid4] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False
    )
    doctor_id: Mapped[uuid4 | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    chief_complaint_id: Mapped[uuid4] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chief_complaints.id"), nullable=False
    )
    chief_complaint_text: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status", create_type=False),
        nullable=False,
        default=SessionStatus.WAITING,
    )
    red_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    red_flag_reason: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="zh-TW"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    patient: Mapped["Patient"] = relationship(back_populates="sessions")
    doctor: Mapped["User | None"] = relationship(foreign_keys=[doctor_id])
    chief_complaint: Mapped["ChiefComplaint"] = relationship()
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="session")
    soap_report: Mapped["SOAPReport | None"] = relationship(back_populates="session")
    red_flag_alerts: Mapped[list["RedFlagAlert"]] = relationship(back_populates="session")
```

---

## 附錄 B: 建表執行順序快速參考

```bash
# 1. 建立 ENUM 類型
psql -f 00_create_enums.sql

# 2. 建立共用函式 (updated_at trigger)
psql -f 01_create_functions.sql

# 3. 依序建立資料表
psql -f 02_create_users.sql
psql -f 03_create_patients.sql
psql -f 04_create_chief_complaints.sql
psql -f 05_create_sessions.sql
psql -f 06_create_conversations.sql    # 含分割區
psql -f 07_create_soap_reports.sql
psql -f 08_create_red_flag_rules.sql
psql -f 09_create_red_flag_alerts.sql
psql -f 10_create_notifications.sql
psql -f 11_create_audit_logs.sql       # 含分割區
psql -f 12_create_fcm_devices.sql

# 4. 建立索引
psql -f 13_create_indexes.sql

# 5. 匯入初始資料
psql -f 14_seed_data.sql
```

---

*文件結束*
