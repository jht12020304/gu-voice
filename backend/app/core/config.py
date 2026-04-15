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
