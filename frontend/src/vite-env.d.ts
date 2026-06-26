/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_WS_BASE_URL: string;
  // L-24：VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY 為死設定（原始碼未讀取），已移除型別宣告。
  readonly VITE_SENTRY_DSN: string;
  readonly VITE_APP_ENV: string;
  readonly VITE_ENABLE_MOCK: string;
  // #1 pre-roll 連續擷取 feature flag（預設關；需真實麥克風驗 STT 後才逐平台開啟）
  readonly VITE_VAD_PREROLL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
