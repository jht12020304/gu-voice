"""
應用程式配置 — 使用 pydantic-settings 載入環境變數

設計原則：
- 顯式 URL（DATABASE_URL / REDIS_URL）優先於元件（DB_* / REDIS_*），讓 Railway /
  Supabase 等平台注入的連線字串可直接使用，本機開發則退回元件組合。
- JWT 金鑰支援 PEM 內容或檔案路徑：偵測到 "BEGIN" 就當 PEM 內容，否則當路徑。
  Railway env vars 常以字面 `\\n` 傳入 PEM，這裡會自動還原成真換行。
"""

from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

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

    # ── Multi-language (i18n) ────────────────────────────
    # 見 docs/i18n_plan.md；Phase 1 僅 zh-TW + en-US 上線，其餘 locale 待臨床 sign-off。
    # SupportedLanguage enum (app/models/enums.py) 是 locale 清單的單一來源；
    # LANGUAGE_MAP 則負責把 BCP-47 → Whisper / TTS voice / 顯示名稱。
    DEFAULT_LANGUAGE: str = "zh-TW"
    # Whisper 接 ISO-639-1 2 碼；TTS voice 先用 OpenAI 內建，後續可換 Azure / ElevenLabs。
    LANGUAGE_MAP: dict[str, dict[str, str]] = {
        "zh-TW": {"whisper": "zh", "tts_voice": "nova", "display": "繁體中文", "native": "繁體中文"},
        "en-US": {"whisper": "en", "tts_voice": "nova", "display": "English", "native": "English"},
    }

    # TODO-O1 feature flag 分層（上線後可用 env / Redis 動態覆寫）。
    # Phase 3 已完整驗收（pytest 283 / Alembic round-trip / E2E），
    # 預設採全量上線；需緊急降級時覆寫 env 為 False / 0 / "zh-TW,en-US"。
    MULTILANG_GLOBAL_ENABLED: bool = True
    MULTILANG_ROLLOUT_PERCENT: int = 100  # 0-100，user_id md5 % 100 決定 bucket
    MULTILANG_DISABLED_LANGUAGES: list[str] = []  # 緊急 kill-switch（逗號分隔）

    # ── WebSocket / Session Stability (P2) ─────────────
    OPENAI_MODEL_SUMMARIZER: str = "gpt-4o-mini"           # 便宜的摘要模型
    CONVERSATION_HISTORY_MAX_TURNS: int = 50                # 最大保留的對話輪次數
    SUPERVISOR_TIMEOUT_SECONDS: int = 30                    # Supervisor 背景任務逾時
    SESSION_IDLE_TIMEOUT_SECONDS: int = 600                 # 10 分鐘閒置逾時
    SESSION_IDLE_CHECK_INTERVAL_SECONDS: int = 30           # 閒置檢查間隔
    AUDIO_MAX_DURATION_SECONDS: int = 600                   # 10 分鐘單段音訊上限
    AUDIO_SAMPLE_RATE_HZ: int = 16000                       # 16kHz mono（與前端一致）

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

    # ── CORS ────────────────────────────────────────────
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        """支援逗號分隔字串或 JSON 陣列"""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v  # type: ignore[return-value]

    @field_validator("MULTILANG_DISABLED_LANGUAGES", mode="before")
    @classmethod
    def parse_disabled_languages(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v  # type: ignore[return-value]

    @property
    def SUPPORTED_LANGUAGES(self) -> list[str]:
        """來源於 LANGUAGE_MAP key；避免兩個地方維護。"""
        return list(self.LANGUAGE_MAP.keys())


settings = Settings()
