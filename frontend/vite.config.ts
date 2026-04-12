import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// 必要環境變數清單（啟動時驗證）
const REQUIRED_ENV_VARS = [
  'VITE_API_BASE_URL',
  'VITE_SUPABASE_URL',
  'VITE_SUPABASE_ANON_KEY',
];

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
    plugins: [react()],

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
    },
  };
});
