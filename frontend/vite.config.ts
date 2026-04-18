import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';

// 必要環境變數清單（啟動時驗證）
const REQUIRED_ENV_VARS = [
  'VITE_API_BASE_URL',
  'VITE_SUPABASE_URL',
  'VITE_SUPABASE_ANON_KEY',
];

// i18n locale JSON 的 source of truth 路徑（相對於 frontend/）
const I18N_SRC_DIR = path.resolve(__dirname, './src/i18n/locales');
// 同步目的地（public/ 下 → 交由 Vite static asset pipeline 服務）
const I18N_DEST_DIR = path.resolve(__dirname, './public/locales');

/**
 * 遞迴複製 src 下所有 .json 到 dest；保持相對結構，不刪除 dest 額外檔案。
 */
function syncLocales(src: string, dest: string) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      syncLocales(s, d);
    } else if (entry.isFile() && entry.name.endsWith('.json')) {
      fs.copyFileSync(s, d);
    }
  }
}

/**
 * 自訂 Vite plugin：把 src/i18n/locales/ 同步到 public/locales/。
 * - buildStart：dev / build 啟動時各跑一次，確保 public/ 有最新內容
 * - configureServer：dev 模式下 watch .json 變更即時重新複製
 * 好處：source of truth 只有一份（src/i18n/locales/），不需外部依賴。
 */
function i18nLocalesSync(): Plugin {
  return {
    name: 'urosense-i18n-locales-sync',
    // config hook 比 configureServer 更早執行，能確保 public/locales 在
    // Vite 初始化 static middleware 前就已存在（避免首次啟動 404）。
    config() {
      syncLocales(I18N_SRC_DIR, I18N_DEST_DIR);
    },
    buildStart() {
      syncLocales(I18N_SRC_DIR, I18N_DEST_DIR);
    },
    configureServer(server) {
      syncLocales(I18N_SRC_DIR, I18N_DEST_DIR);
      server.watcher.add(path.join(I18N_SRC_DIR, '**/*.json'));
      const handler = (file: string) => {
        if (!file.startsWith(I18N_SRC_DIR)) return;
        if (!file.endsWith('.json')) return;
        const rel = path.relative(I18N_SRC_DIR, file);
        const dest = path.join(I18N_DEST_DIR, rel);
        try {
          fs.mkdirSync(path.dirname(dest), { recursive: true });
          fs.copyFileSync(file, dest);
        } catch {
          // 忽略暫時性檔案系統錯誤（例如檔案剛被刪除）
        }
      };
      server.watcher.on('add', handler);
      server.watcher.on('change', handler);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  // 環境變數驗證（僅在 build 時強制檢查）
  if (mode === 'production') {
    const missing = REQUIRED_ENV_VARS.filter((key) => !env[key]);
    if (missing.length > 0) {
      throw new Error(
        `缺少必要環境變數: ${missing.join(', ')}\n` +
          '請確認 .env.local 或 Vercel 環境變數已正確設定。'
      );
    }
  }

  return {
    plugins: [i18nLocalesSync(), react()],

    // 路徑別名設定（對應 tsconfig.json 的 paths）
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@components': path.resolve(__dirname, './src/components'),
        '@hooks': path.resolve(__dirname, './src/hooks'),
        '@pages': path.resolve(__dirname, './src/pages'),
        '@stores': path.resolve(__dirname, './src/stores'),
        '@utils': path.resolve(__dirname, './src/utils'),
        '@types': path.resolve(__dirname, './src/types'),
        '@services': path.resolve(__dirname, './src/services'),
        '@assets': path.resolve(__dirname, './src/assets'),
      },
    },

    // 本地開發伺服器設定
    server: {
      host: '127.0.0.1',
      port: 5173,
      open: true,
      // 本地開發時代理 API 請求到後端
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          secure: false,
        },
        '/ws': {
          target: 'ws://localhost:8000',
          ws: true,
          changeOrigin: true,
        },
      },
    },

    // 預覽伺服器設定
    preview: {
      port: 4173,
    },

    // 建置最佳化
    build: {
      target: 'es2020',
      outDir: 'dist',
      sourcemap: mode !== 'production',
      // 分塊策略：將大型依賴拆分為獨立 chunk，提升快取效率
      rollupOptions: {
        output: {
          manualChunks: {
            // React 核心
            'vendor-react': ['react', 'react-dom', 'react-router-dom'],
            // 狀態管理
            'vendor-state': ['zustand'],
            // UI 元件庫
            'vendor-ui': ['@headlessui/react'],
            // HTTP 與工具
            'vendor-utils': ['axios'],
          },
        },
      },
      // 區塊大小警告閾值（KB）
      chunkSizeWarningLimit: 500,
    },

    // 定義全域常數
    define: {
      __APP_VERSION__: JSON.stringify(process.env.npm_package_version || '0.0.0'),
      // 生產環境強制關閉 mock 模式，避免 VITE_ENABLE_MOCK 意外洩漏造成醫師看到假資料。
      // Dev 模式（vite / preview 以外）仍由 .env / .env.local 決定，不覆寫。
      ...(mode === 'production'
        ? { 'import.meta.env.VITE_ENABLE_MOCK': JSON.stringify('false') }
        : {}),
    },
  };
});
