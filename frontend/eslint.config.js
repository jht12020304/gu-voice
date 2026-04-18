// ESLint v9 flat config — 對齊 @typescript-eslint v8、react-hooks v5、react-refresh v0.4
// （舊版的 .eslintrc 已在 ESLint v9 廢止；flat config 走檔案 export default array）

import js from '@eslint/js';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default [
  {
    ignores: [
      'dist/**',
      'build/**',
      'node_modules/**',
      'coverage/**',
      'test-results/**',
      'playwright-report/**',
      '*.config.js',
      'vite.config.ts',
      'playwright.config.ts',
      // Node.js 輔助腳本（i18n extract check 等）—— 跑在 Node runtime，
      // 不走瀏覽器 global 規範，也不走 React rule，這裡直接排除。
      'scripts/**',
    ],
  },
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
      globals: {
        React: 'readonly',
        window: 'readonly',
        document: 'readonly',
        navigator: 'readonly',
        MediaDeviceInfo: 'readonly',
        AnalyserNode: 'readonly',
        AudioBufferSourceNode: 'readonly',
        BlobEvent: 'readonly',
        MessageEvent: 'readonly',
        CloseEvent: 'readonly',
        Node: 'readonly',
        localStorage: 'readonly',
        sessionStorage: 'readonly',
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
        fetch: 'readonly',
        URL: 'readonly',
        URLSearchParams: 'readonly',
        FormData: 'readonly',
        Blob: 'readonly',
        File: 'readonly',
        FileReader: 'readonly',
        WebSocket: 'readonly',
        AbortController: 'readonly',
        AbortSignal: 'readonly',
        atob: 'readonly',
        btoa: 'readonly',
        crypto: 'readonly',
        performance: 'readonly',
        HTMLElement: 'readonly',
        HTMLInputElement: 'readonly',
        HTMLTextAreaElement: 'readonly',
        HTMLButtonElement: 'readonly',
        HTMLDivElement: 'readonly',
        HTMLFormElement: 'readonly',
        MediaStream: 'readonly',
        MediaRecorder: 'readonly',
        AudioContext: 'readonly',
        MediaDevices: 'readonly',
        Event: 'readonly',
        CustomEvent: 'readonly',
        KeyboardEvent: 'readonly',
        MouseEvent: 'readonly',
        FocusEvent: 'readonly',
        ResizeObserver: 'readonly',
        IntersectionObserver: 'readonly',
        MutationObserver: 'readonly',
        matchMedia: 'readonly',
        alert: 'readonly',
        confirm: 'readonly',
        location: 'readonly',
        history: 'readonly',
        Notification: 'readonly',
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      // TS 基礎（避免過度嚴格，保留未來逐步加固空間）
      ...tsPlugin.configs.recommended.rules,
      // 由 TS 接管未使用偵測（支援 underscore prefix 豁免）
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // React hooks 正確性（rules-of-hooks + exhaustive-deps）
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Vite HMR friendliness
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Any 先放過，專案既有程式碼尚未零 any
      '@typescript-eslint/no-explicit-any': 'off',
      // FastAPI client 產生的程式會留空 interface，暫關
      '@typescript-eslint/no-empty-object-type': 'off',
      // 空 catch 僅在有保留 body 時才允許
      'no-empty': ['error', { allowEmptyCatch: true }],
      // TS enum 合併時 ESLint 會誤報；TS 本身能正確偵測 redeclare
      'no-redeclare': 'off',
      '@typescript-eslint/no-redeclare': 'off',
    },
  },
];
