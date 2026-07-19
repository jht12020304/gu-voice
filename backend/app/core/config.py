"""
應用程式配置 — 使用 pydantic-settings 載入環境變數

設計原則：
- 顯式 URL（DATABASE_URL / REDIS_URL）優先於元件（DB_* / REDIS_*），讓 Railway /
  Supabase 等平台注入的連線字串可直接使用，本機開發則退回元件組合。
- JWT 金鑰支援 PEM 內容或檔案路徑：偵測到 "BEGIN" 就當 PEM 內容，否則當路徑。
  Railway env vars 常以字面 `\\n` 傳入 PEM，這裡會自動還原成真換行。
"""

import json
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse
from typing import Annotated, Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _to_sync_db_url(url: str) -> str:
    """標準化為同步 psycopg2 可讀的 URL（Alembic 用）。"""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://"):]
    if url.startswith("postgres://"):  # Railway/Heroku 舊格式
        return "postgresql://" + url[len("postgres://"):]
    return url


def _to_async_db_url(url: str) -> str:
    """標準化為 asyncpg 可讀的 URL（FastAPI runtime 用）。"""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    return url


class Settings(BaseSettings):
    """集中管理所有環境變數，分區段組織"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ── APP ─────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_WORKERS: int = 4
    # 單一日誌等級欄位，對齊 start.sh / docker-compose / .env.example 的 LOG_LEVEL
    LOG_LEVEL: str = "info"
    APP_SECRET_KEY: str = "change-me-in-production"

    # ── DATABASE ────────────────────────────────────────
    # 顯式 URL（Railway/Supabase 插件常自動注入）。若未設則從 DB_* 元件組。
    DATABASE_URL_EXPLICIT: Optional[str] = Field(default=None, validation_alias="DATABASE_URL")
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "gu_voice"
    DB_USER: str = "gu_app"
    DB_PASSWORD: str = ""
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    @property
    def DATABASE_URL(self) -> str:
        """同步資料庫 URL (用於 Alembic 等工具)"""
        if self.DATABASE_URL_EXPLICIT:
            return _to_sync_db_url(self.DATABASE_URL_EXPLICIT)
        pwd = quote(self.DB_PASSWORD, safe="")
        user = quote(self.DB_USER, safe=".")
        return (
            f"postgresql://{user}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """非同步資料庫 URL (asyncpg 驅動)"""
        if self.DATABASE_URL_EXPLICIT:
            return _to_async_db_url(self.DATABASE_URL_EXPLICIT)
        pwd = quote(self.DB_PASSWORD, safe="")
        user = quote(self.DB_USER, safe=".")
        return (
            f"postgresql+asyncpg://{user}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── REDIS ───────────────────────────────────────────
    # 顯式 URL（Railway Redis / Upstash 注入）。若未設則從 REDIS_* 元件組。
    REDIS_URL_EXPLICIT: Optional[str] = Field(default=None, validation_alias="REDIS_URL")
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_KEY_PREFIX: str = "gu:"

    # P3 #29：cache / celery broker / celery result 各走獨立 DB index，
    # 避免 FLUSHDB on cache 誤清掉正在排隊的 Celery 任務。
    REDIS_DB_CACHE: int = 0
    REDIS_DB_CELERY_BROKER: int = 1
    REDIS_DB_CELERY_RESULT: int = 2

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_URL_EXPLICIT:
            return self.REDIS_URL_EXPLICIT
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    def _redis_url_with_db(self, db: int) -> str:
        """
        把 base REDIS_URL 的尾端 `/N` 替換成指定的 db index。

        支援三種 base 格式：
          - `redis://host:6379/0`（已有 db）→ 替換
          - `redis://host:6379`（沒 db）→ 直接追加
          - `rediss://user:pass@host:6380/5`（tls + auth + 任意 db）→ 保留 auth 與 tls scheme
        """
        base = self.REDIS_URL
        parsed = urlparse(base)
        # urlparse 在 scheme=redis(s) 時 path 會從 "/" 開始，等於原本的 "/N"；
        # 沒有 db 的情況 path == "" 或 "/"
        new_path = f"/{db}"
        return urlunparse(parsed._replace(path=new_path))

    @property
    def REDIS_URL_CACHE(self) -> str:
        return self._redis_url_with_db(self.REDIS_DB_CACHE)

    @property
    def REDIS_URL_CELERY_BROKER(self) -> str:
        return self._redis_url_with_db(self.REDIS_DB_CELERY_BROKER)

    @property
    def REDIS_URL_CELERY_RESULT(self) -> str:
        return self._redis_url_with_db(self.REDIS_DB_CELERY_RESULT)

    # ── JWT ──────────────────────────────────────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_SECRET_KEY: str = ""  # HS256 用
    # 顯式 PEM 內容或路徑（Railway 無檔案系統，env var 直接貼 PEM 最常見）。
    # 未設時退回 *_PATH。支援 \\n 字面 → 真換行自動還原。
    JWT_PRIVATE_KEY_EXPLICIT: Optional[str] = Field(default=None, validation_alias="JWT_PRIVATE_KEY")
    JWT_PUBLIC_KEY_EXPLICIT: Optional[str] = Field(default=None, validation_alias="JWT_PUBLIC_KEY")
    JWT_PRIVATE_KEY_PATH: str = "keys/private.pem"
    JWT_PUBLIC_KEY_PATH: str = "keys/public.pem"
    # .env / Railway 歷史上用過 JWT_ 前綴命名（JWT_ACCESS_TOKEN_EXPIRE_MINUTES），
    # extra="ignore" 會靜默忽略未知名稱 → token 效期悄悄退回預設而無人察覺。
    # AliasChoices 讓兩種名稱都生效；同時設定時無前綴（canonical）優先。
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15,
        validation_alias=AliasChoices(
            "ACCESS_TOKEN_EXPIRE_MINUTES", "JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
        ),
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        validation_alias=AliasChoices(
            "REFRESH_TOKEN_EXPIRE_DAYS", "JWT_REFRESH_TOKEN_EXPIRE_DAYS"
        ),
    )

    def _resolve_key(self, explicit: Optional[str], fallback_path: str) -> str:
        """
        HS256：用 JWT_SECRET_KEY（不看 PEM）。
        RS256：優先用顯式值——含 "BEGIN" 當 PEM 內容；否則當檔案路徑。
                都取不到時 fallback 到 *_PATH 檔。
        """
        if self.JWT_ALGORITHM == "HS256":
            return self.JWT_SECRET_KEY
        if explicit:
            # Railway 等平台常把多行 PEM 以字面 \n 塞進 env var
            candidate = explicit.replace("\\n", "\n") if "\\n" in explicit else explicit
            if "BEGIN" in candidate:
                return candidate
            path = Path(candidate)
            if path.exists():
                return path.read_text()
        path = Path(fallback_path)
        if path.exists():
            return path.read_text()
        return ""

    @property
    def JWT_PRIVATE_KEY(self) -> str:
        """簽名金鑰：HS256 用 secret，RS256 用 PEM 私鑰"""
        return self._resolve_key(self.JWT_PRIVATE_KEY_EXPLICIT, self.JWT_PRIVATE_KEY_PATH)

    @property
    def JWT_PUBLIC_KEY(self) -> str:
        """驗證金鑰：HS256 用 secret，RS256 用 PEM 公鑰"""
        return self._resolve_key(self.JWT_PUBLIC_KEY_EXPLICIT, self.JWT_PUBLIC_KEY_PATH)

    # ── OPENAI ──────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    # Default 對齊 production(Railway env vars,2026-04-15 升級):
    #   Conversation + Supervisor 走 gpt-5.4-mini(reasoning 模型家族,2026-03-17
    #     snapshot,400K context,knowledge cutoff 2025-08-31)
    #   Conversation 設 reasoning_effort=none → 走傳統 chat 路徑,送 temperature=0.7
    #     保留語音問診的口吻親和與低延遲
    #   Supervisor 設 reasoning_effort=medium → 啟用 CoT,拿到更精準的 next_focus
    #     督導指令;Supervisor 是背景任務,延遲影響低
    #   SOAP / Red flag 暫維持 gpt-4o / gpt-4o-mini(未來可再評估)
    OPENAI_MODEL_CONVERSATION: str = "gpt-5.4-mini"
    OPENAI_MODEL_SUPERVISOR: str = "gpt-5.4-mini"
    OPENAI_MODEL_SOAP: str = "gpt-4o"
    OPENAI_MODEL_RED_FLAG: str = "gpt-4o-mini"
    OPENAI_TEMPERATURE_CONVERSATION: float = 0.7
    OPENAI_TEMPERATURE_SOAP: float = 0.3
    OPENAI_TEMPERATURE_RED_FLAG: float = 0.2
    OPENAI_MAX_TOKENS_CONVERSATION: int = 2048
    OPENAI_MAX_TOKENS_SOAP: int = 4096
    # Supervisor 走 reasoning 模型時要留足夠 token 給 CoT + JSON 輸出,
    # 太低會導致 JSON 被截斷 → parse 失敗 → next_focus 永遠空。
    OPENAI_MAX_TOKENS_SUPERVISOR: int = 4096
    # reasoning_effort 控制(gpt-5.4 系列等 reasoning 模型支援):
    #   none                        → 不送 reasoning_effort 參數,改送 temperature
    #                                 (走傳統 chat 路徑,gpt-4o / gpt-4.1 也走這條)
    #   low / medium / high / xhigh → 啟用 chain-of-thought;API 會拒絕 temperature,
    #                                 程式端(llm_conversation.py / supervisor.py)
    #                                 會自動切換 create_kwargs 不送 temperature
    OPENAI_REASONING_EFFORT_CONVERSATION: str = "none"
    OPENAI_REASONING_EFFORT_SUPERVISOR: str = "medium"

    # ── STT (OpenAI Whisper) ─────────────────────────────
    OPENAI_STT_MODEL: str = "whisper-1"
    OPENAI_STT_LANGUAGE: str = "zh"      # ISO-639-1，zh = 中文（繁/簡皆可）
    # #3：STT 專用逾時。預設 client 為 60s，病患一口氣講很長 → 大檔 Whisper 轉錄常 >60s
    # 撞逾時又 tenacity 重試（~2x）造成「當機約一分鐘」。STT 拉長到 120s 避免誤判逾時重試。
    OPENAI_STT_TIMEOUT_SECONDS: float = 120.0

    # ── Multi-language (i18n) ────────────────────────────
    # 見 docs/archive/i18n_plan.md；SupportedLanguage enum (app/models/enums.py) 為 locale 清單的單一來源；
    # LANGUAGE_MAP 則負責把 BCP-47 → Whisper / TTS voice / 顯示名稱。
    #
    # status:
    #   active     前端切換可用、臨床內容已 sign-off（上線可收真實流量）
    #   beta       前端切換可用、臨床內容未 sign-off（僅內測 / 灰度）
    #
    # ja-JP / ko-KR / vi-VN 先以 beta 進入骨架階段，待 TODO-M1 / M2 / M13 sign-off 後升 active。
    DEFAULT_LANGUAGE: str = "zh-TW"
    LANGUAGE_MAP: dict[str, dict[str, str]] = {
        "zh-TW": {"whisper": "zh", "tts_voice": "nova",    "display": "繁體中文", "native": "繁體中文", "status": "active"},
        "en-US": {"whisper": "en", "tts_voice": "nova",    "display": "English",  "native": "English",  "status": "active"},
        "ja-JP": {"whisper": "ja", "tts_voice": "shimmer", "display": "Japanese", "native": "日本語",   "status": "beta"},
        "ko-KR": {"whisper": "ko", "tts_voice": "shimmer", "display": "Korean",   "native": "한국어",   "status": "beta"},
        "vi-VN": {"whisper": "vi", "tts_voice": "shimmer", "display": "Vietnamese","native": "Tiếng Việt","status": "beta"},
    }

    # SOAP 報告固定輸出語言（2026-07-19 產品決策）：問診可為五語言之一，
    # 但報告讀者是院內中文醫護，故 SOAP 生成/顯示一律 zh-TW，不跟 session 語言。
    # 覆寫此值即可恢復「報告跟問診語言」的舊行為。
    SOAP_REPORT_LANGUAGE: str = "zh-TW"

    # TODO-O1 feature flag 分層（上線後可用 env / Redis 動態覆寫）。
    # Phase 3 已完整驗收（pytest 283 / Alembic round-trip / E2E），
    # 預設採全量上線；需緊急降級時覆寫 env 為 False / 0 / "zh-TW,en-US"。
    MULTILANG_GLOBAL_ENABLED: bool = True
    MULTILANG_ROLLOUT_PERCENT: int = 100  # 0-100，user_id md5 % 100 決定 bucket
    # NoDecode：阻止 pydantic-settings 在 source 層對 env 值做 json.loads，
    # 改由下方 field_validator(mode="before") 接手解析逗號分隔字串。
    MULTILANG_DISABLED_LANGUAGES: Annotated[list[str], NoDecode] = []  # 緊急 kill-switch（逗號分隔）

    # TODO-M8：紅旗 semantic-only 比率閾值。
    # 一個 session 的紅旗命中若 semantic_only / total > threshold → report 將
    # 被後端視為 draft（非 zh-TW fail-safe 機制）。預設 0.3。
    RED_FLAG_SEMANTIC_ONLY_THRESHOLD: float = 0.3

    # W1：紅旗規則層 kill-switch。
    # red_flag_rules 表在生產環境從未被 seed，查詢「成功但 0 筆」在語意上
    # 等同「規則層從未被配置過」，而非管理者刻意清空。預設 True 時，
    # RedFlagDetector._load_rules() 遇到 0 筆會 fallback 到內建 catalogue
    # （shared.URO_RED_FLAGS），避免規則層恆為 [] 導致偵測全靠語意層、
    # 沒有雙層備援（違反 fail-open 精神）。若 DB 已有任何一筆規則，一律
    # 尊重 DB 配置、不與內建規則混用。設 False 可翻案回舊行為（0 筆就是
    # 空，不 fallback）；不影響「DB 查詢例外」時的 fallback（該路徑維持
    # 既有行為，不受此旗標控制）。
    RED_FLAG_BUILTIN_RULES_FALLBACK: bool = True

    # ── Rate limit（per-IP / per-user policy 旋鈕） ─────
    # 登入端點 per-IP sliding window（rate_limit.py 的 LOGIN_IP_LIMIT/WINDOW 預設
    # 與此對齊；新增 policy 一律從這裡讀，方便維運不改 code 就能調整）。
    LOGIN_IP_LIMIT: int = 10        # 每 IP 每 window 次數
    LOGIN_IP_WINDOW: int = 60       # window 秒數
    # 忘記密碼 / 重設密碼端點 per-IP sliding window。比登入保守得多：
    # 寄信 / 改密碼成本高且不該被高頻打，預設 5 次 / 15 分鐘。
    PASSWORD_RESET_IP_LIMIT: int = 5     # 每 IP 每 window 次數
    PASSWORD_RESET_IP_WINDOW: int = 900  # window 秒數（15 分鐘）

    # ── WebSocket / Session Stability (P2) ─────────────
    OPENAI_MODEL_SUMMARIZER: str = "gpt-4o-mini"           # 便宜的摘要模型
    CONVERSATION_HISTORY_MAX_TURNS: int = 50                # 最大保留的對話輪次數
    SUPERVISOR_TIMEOUT_SECONDS: int = 30                    # Supervisor 背景任務逾時
    SESSION_IDLE_TIMEOUT_SECONDS: int = 600                 # 10 分鐘閒置逾時
    SESSION_IDLE_CHECK_INTERVAL_SECONDS: int = 30           # 閒置檢查間隔
    AUDIO_MAX_DURATION_SECONDS: int = 600                   # 10 分鐘單段音訊上限
    AUDIO_SAMPLE_RATE_HZ: int = 16000                       # 16kHz mono（與前端一致）

    # ── 問診自動結束（避免無止盡發問，病患等不到結果） ───
    # 兩條獨立的收尾路徑，皆受 ENABLED 總開關控制（出事可一鍵關回純手動）：
    #   1) 軟門檻：Supervisor 判定 HPI 完整度 >= THRESHOLD 且已問滿最低題數 → 收尾。
    #   2) 硬上限 backstop：病患回合數 >= HARD_CAP 即強制收尾，「不依賴」Supervisor
    #      （Supervisor 逾時/降級寫 fallback hpi=0 時軟門檻永不觸發，硬上限才是保命線，
    #      也正是「測到第 15 題還沒結果」的真正修補）。
    # 「平衡」收尾節奏（約 8-10 題）：病患回報舊值（軟門檻 85 幾乎不觸發、硬上限 15 太長，
    # 等不到自動結束、覺得 AI 一直問）。下調為：軟門檻 80 讓問夠的對話約第 6-9 題即收尾，
    # 硬上限 10 保證最遲第 10 題結束（benign 對話走 in_progress→completed compare-and-set）。
    HPI_COMPLETION_TERMINATION_ENABLED: bool = True         # 自動結束總開關
    HPI_COMPLETION_TERMINATION_THRESHOLD: int = 80          # 0-100；HPI 完整度達此值即可收尾
    MIN_PATIENT_TURNS_BEFORE_AUTO_END: int = 5              # 軟門檻最低回合，防 Supervisor 過早判定
    MAX_PATIENT_TURNS_HARD_CAP: int = 10                    # 病患回合硬上限，無論 Supervisor 狀態都收尾
    # §3b：高風險主訴（血尿/PSA/ED）的硬上限「動態加成」。這些主訴把 K 個關鍵風險因子
    # 提升為與 HPI 十欄同級必問（見 shared.CRITICAL_RISK_FACTORS），但 base=10 連
    # opening(1)+HPI 十欄(10) 都塞不下，風險因子必被砍。故對有 K>0 風險因子的主訴，
    # effective cap = base + K + BUFFER（吸收 opening 與少量 margin）。K=0 的主訴 cap 不變。
    # 注意：這只抬「backstop 上限」；合作病患在風險因子問到後 Supervisor 完整度即達門檻、
    # 走軟門檻在 ~11 輪就收尾，cap 只在不合作（含糊/離題）時才咬住。
    RISK_FACTOR_HARD_CAP_BUFFER: int = 2

    # ── E2E 稽核修復 kill-switch（docs/archive/e2e_realopenai_audit_2026-06-28.md §三；無 migration）─
    # A1 [D5]：LLM 空回應時是否做單次重試（仍空則送 ws.ai_empty_retry_fallback 在地化訊息）。
    LLM_EMPTY_RESPONSE_RETRY: bool = True
    # A3 [D1]：硬上限收尾時，inline 等待遲到紅旗偵測結果的上限秒數（有界解析）。
    HARD_CAP_DRAIN_AWAIT_SECONDS: float = 5.0
    # A3 [D1]：紅旗偵測器真卡死時，硬上限收尾最多可被延後的輪數；超過即強制收尾出 SOAP
    # （絕對保命線；接受極罕見 late-critical race — E7 決策 2）。
    MAX_HARD_CAP_DRAIN_DEFERS: int = 2

    # ── TTS (OpenAI TTS) ─────────────────────────────────
    OPENAI_TTS_MODEL: str = "tts-1"      # tts-1（快速）或 tts-1-hd（高品質）
    OPENAI_TTS_VOICE: str = "nova"       # alloy / echo / fable / onyx / nova / shimmer
    OPENAI_TTS_SPEED: float = 0.9        # 0.25 ~ 4.0，< 1.0 稍慢較自然

    # ── SUPABASE ────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ── FIREBASE (FCM) ─────────────────────────────────
    # base64 編碼的 service account JSON（Railway 無法掛檔，只能用 env 傳）。
    # 未設時 lifespan 啟動只會 log warning，不阻擋本機開發。
    FCM_CREDENTIALS_JSON: Optional[str] = None

    # ── SENTRY ──────────────────────────────────────────
    SENTRY_DSN: Optional[str] = None

    # ── Email（P3 #31 forgot_password） ─────────────────
    # 前端 reset-password 頁面 base URL；email 模板會拼成
    # `{FRONTEND_BASE_URL}/reset-password?token=...`
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    # 寄信優先順序：SENDGRID_API_KEY > SMTP_HOST > 皆無時只 log（dev 模式）
    SENDGRID_API_KEY: Optional[str] = None
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_ADDRESS: str = "no-reply@gu-voice.local"
    SMTP_USE_TLS: bool = True

    # ── Proxy / Client IP ───────────────────────────────
    # 是否信任反向代理注入的 X-Forwarded-For。預設 False：直接用 socket peer
    # （request.client.host），避免客戶端偽造 XFF 繞過 per-IP rate limit / 污染 audit。
    # 部署在 Railway / Cloudflare 等可信代理後方時才設為 True。
    TRUST_PROXY_HEADERS: bool = False

    # ── Auth Cookies / CSRF（M-22） ─────────────────────
    # refresh token 從前端可讀儲存遷移到 httpOnly Secure cookie，搭配 double-submit
    # CSRF token（非 httpOnly，前端要能讀回填 X-CSRF-Token header）。
    #   - REFRESH_COOKIE_NAME：httpOnly + Secure + SameSite 的 refresh token cookie 名稱
    #   - CSRF_COOKIE_NAME：非 httpOnly 的 CSRF token cookie 名稱（double-submit 比對）
    #   - COOKIE_SECURE：cookie 是否帶 Secure flag（production 必為 True；本機 http 開發可關）
    #   - COOKIE_SAMESITE：lax / strict / none（none 必須搭配 Secure=True）
    #   - REFRESH_COOKIE_PATH：限縮 cookie scope，只在 auth 端點送出
    REFRESH_COOKIE_NAME: str = "gu_refresh_token"
    CSRF_COOKIE_NAME: str = "gu_csrf_token"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"
    REFRESH_COOKIE_PATH: str = "/api/v1/auth"

    # ── CORS ────────────────────────────────────────────
    # NoDecode：見 MULTILANG_DISABLED_LANGUAGES 說明。Railway 常以逗號分隔字串
    # 注入（如 "https://a.com,https://b.com"），若交給 source 層 json.loads 會
    # 直接 SettingsError 導致容器啟動即崩潰，故跳過解碼改由 validator 處理。
    CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5175",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        """支援逗號分隔字串或 JSON 陣列；兩種格式皆不會讓啟動崩潰。"""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):  # 容忍 JSON 陣列格式
                return json.loads(s)
            return [origin.strip() for origin in s.split(",") if origin.strip()]
        return v  # type: ignore[return-value]

    @field_validator("MULTILANG_DISABLED_LANGUAGES", mode="before")
    @classmethod
    def parse_disabled_languages(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v  # type: ignore[return-value]

    @property
    def SUPPORTED_LANGUAGES(self) -> list[str]:
        """來源於 LANGUAGE_MAP key；避免兩個地方維護。

        `resolve_language` 允許 fallback 至此清單內任一 locale（含 beta）。
        """
        return list(self.LANGUAGE_MAP.keys())

    @property
    def ACTIVE_LANGUAGES(self) -> list[str]:
        """LANGUAGE_MAP 中 status=='active' 的 locale；是後端 i18n 字串 parity 的強制範圍。

        Beta locale（ja-JP / ko-KR / vi-VN）可跳過此強制 — 後端 `get_message`
        查不到時 fallback 至 DEFAULT_LANGUAGE，不 raise。
        """
        return [code for code, info in self.LANGUAGE_MAP.items() if info.get("status") == "active"]


settings = Settings()
