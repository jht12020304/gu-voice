"""
應用程式配置 — 使用 pydantic-settings 載入環境變數
"""

from pathlib import Path
from urllib.parse import quote
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中管理所有環境變數，分區段組織"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── APP ─────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_WORKERS: int = 4
    APP_LOG_LEVEL: str = "info"
    APP_SECRET_KEY: str = "change-me-in-production"

    # ── DATABASE ────────────────────────────────────────
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
        pwd = quote(self.DB_PASSWORD, safe="")
        user = quote(self.DB_USER, safe=".")
        return (
            f"postgresql://{user}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """非同步資料庫 URL (asyncpg 驅動)"""
        pwd = quote(self.DB_PASSWORD, safe="")
        user = quote(self.DB_USER, safe=".")
        return (
            f"postgresql+asyncpg://{user}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── REDIS ───────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_KEY_PREFIX: str = "gu:"

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ── JWT ──────────────────────────────────────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_SECRET_KEY: str = ""  # HS256 用
    JWT_PRIVATE_KEY_PATH: str = "keys/private.pem"
    JWT_PUBLIC_KEY_PATH: str = "keys/public.pem"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @property
    def JWT_PRIVATE_KEY(self) -> str:
        """簽名金鑰：HS256 用 secret，RS256 用 PEM 私鑰"""
        if self.JWT_ALGORITHM == "HS256":
            return self.JWT_SECRET_KEY
        path = Path(self.JWT_PRIVATE_KEY_PATH)
        if path.exists():
            return path.read_text()
        return ""

    @property
    def JWT_PUBLIC_KEY(self) -> str:
        """驗證金鑰：HS256 用 secret，RS256 用 PEM 公鑰"""
        if self.JWT_ALGORITHM == "HS256":
            return self.JWT_SECRET_KEY
        path = Path(self.JWT_PUBLIC_KEY_PATH)
        if path.exists():
            return path.read_text()
        return ""

    # ── OPENAI ──────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL_CONVERSATION: str = "gpt-5.4-mini"
    OPENAI_MODEL_SUPERVISOR: str = "gpt-5.4"
    OPENAI_MODEL_SOAP: str = "gpt-4o"
    OPENAI_MODEL_RED_FLAG: str = "gpt-4o-mini"
    OPENAI_TEMPERATURE_CONVERSATION: float = 0.7
    OPENAI_TEMPERATURE_SOAP: float = 0.3
    OPENAI_TEMPERATURE_RED_FLAG: float = 0.2
    OPENAI_MAX_TOKENS_CONVERSATION: int = 2048
    OPENAI_MAX_TOKENS_SOAP: int = 4096
    # gpt-5.4-mini reasoning 控制：
    #   none  → 不做 chain-of-thought，延遲最低，且允許 temperature/top_p
    #   low/medium/high/xhigh → 啟用推理；此時 temperature 會被 API 拒絕
    # 對話每輪只產 1-3 句 HPI 追問，且深度推理交由 Supervisor pipeline 處理，
    # 預設 "none" 以保留 temperature 並降低延遲。
    OPENAI_REASONING_EFFORT_CONVERSATION: str = "none"
    # Supervisor 是背景任務,不影響對話延遲,值得花 medium reasoning 做真正的
    # 臨床推理(HPI 缺漏分析 + 下一步追問策略)。Supervisor 的 temperature 在
    # reasoning_effort != "none" 時會被 API 拒絕,所以走 reasoning 路徑不帶 temp。
    OPENAI_REASONING_EFFORT_SUPERVISOR: str = "medium"

    # ── STT (OpenAI Whisper) ─────────────────────────────
    OPENAI_STT_MODEL: str = "whisper-1"
    OPENAI_STT_LANGUAGE: str = "zh"      # ISO-639-1，zh = 中文（繁/簡皆可）

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

    # ── SENTRY ──────────────────────────────────────────
    SENTRY_DSN: Optional[str] = None

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


settings = Settings()
