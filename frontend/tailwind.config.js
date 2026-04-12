/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],

  // 深色模式：使用 class 策略，方便手動切換
  darkMode: 'class',

  theme: {
    extend: {
      /* ===== 醫療 UI 色彩系統 =====
       * 融合方案: Stripe (基底) + Intercom (對話) + Sentry (告警)
       */
      colors: {
        // 主色調 — 醫療專業藍 (Stripe 風格)
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },

        // 語義色 — 告警系統 (Intercom + Stripe 報告色板)
        alert: {
          critical: {
            DEFAULT: '#dc2626',
            bg: '#fef2f2',
            border: '#fecaca',
            text: '#991b1b',
          },
          high: {
            DEFAULT: '#ea580c',
            bg: '#fff7ed',
            border: '#fed7aa',
            text: '#9a3412',
          },
          medium: {
            DEFAULT: '#d97706',
            bg: '#fffbeb',
            border: '#fde68a',
            text: '#92400e',
          },
          success: {
            DEFAULT: '#16a34a',
            bg: '#f0fdf4',
            border: '#bbf7d0',
            text: '#166534',
          },
        },

        // 狀態色 — Session Status
        status: {
          waiting: { DEFAULT: '#64748b', bg: '#f1f5f9', border: '#e2e8f0' },
          'in-progress': { DEFAULT: '#2563eb', bg: '#dbeafe', border: '#bfdbfe' },
          completed: { DEFAULT: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0' },
          'red-flag': { DEFAULT: '#dc2626', bg: '#fef2f2', border: '#fecaca' },
          cancelled: { DEFAULT: '#6b7280', bg: '#f3f4f6', border: '#e5e7eb' },
        },

        // 對話區域 — Intercom 暖色調
        chat: {
          bg: '#faf9f6',
          patient: '#2563eb',
          'patient-bg': '#dbeafe',
          ai: '#ea580c',
          'ai-bg': '#fff7ed',
          system: '#64748b',
          'system-bg': '#f1f5f9',
          border: '#dedbd6',
        },

        // 表面色 — Stripe 風格
        surface: {
          primary: '#ffffff',
          secondary: '#f8f9fc',
          tertiary: '#f1f3f9',
          hover: '#eef1f8',
        },

        // 文字色 — Stripe 深海軍藍系統 (非純黑)
        ink: {
          heading: '#061b31',
          body: '#425466',
          secondary: '#64748d',
          muted: '#8898aa',
          placeholder: '#a3b1c6',
        },

        // 邊框 — Stripe 精緻邊框
        edge: {
          DEFAULT: '#e5edf5',
          hover: '#d0dae8',
          focus: '#2563eb',
        },

        // 暗色模式表面 — Linear luminance stacking
        dark: {
          bg: '#0f1117',
          surface: '#171b24',
          card: '#1e2330',
          hover: '#272d3d',
          border: 'rgba(255,255,255,0.08)',
        },
      },

      /* ===== 字型設定 ===== */
      fontFamily: {
        // 主字型 — Inter + Noto Sans TC 繁中支援
        sans: [
          '"Inter Variable"',
          '"Inter"',
          '"Noto Sans TC"',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
        ],
        // 等寬字型 — 數據、病歷號碼、診斷碼
        mono: [
          '"Source Code Pro"',
          '"JetBrains Mono"',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'monospace',
        ],
      },

      /* ===== 字型大小 — 醫療資料密集型比例 ===== */
      fontSize: {
        'display': ['2.25rem', { lineHeight: '1.2', letterSpacing: '-0.72px', fontWeight: '700' }],
        'h1': ['1.75rem', { lineHeight: '1.3', letterSpacing: '-0.56px', fontWeight: '700' }],
        'h2': ['1.375rem', { lineHeight: '1.35', letterSpacing: '-0.33px', fontWeight: '600' }],
        'h3': ['1.125rem', { lineHeight: '1.4', letterSpacing: '-0.18px', fontWeight: '600' }],
        'body-lg': ['1rem', { lineHeight: '1.6', fontWeight: '400' }],
        'body': ['0.875rem', { lineHeight: '1.5', fontWeight: '400' }],
        'caption': ['0.8125rem', { lineHeight: '1.45', fontWeight: '500' }],
        'small': ['0.75rem', { lineHeight: '1.4', letterSpacing: '0.1px', fontWeight: '400' }],
        'tiny': ['0.6875rem', { lineHeight: '1.35', letterSpacing: '0.3px', fontWeight: '500' }],
      },

      /* ===== 間距與尺寸 ===== */
      spacing: {
        sidebar: '15rem',
        'sidebar-collapsed': '4rem',
      },

      /* ===== 陰影 — Stripe 藍調系統 ===== */
      boxShadow: {
        'card': '0px 1px 2px rgba(50, 50, 93, 0.06), 0px 1px 2px rgba(0, 0, 0, 0.04)',
        'card-hover': '0px 4px 12px rgba(50, 50, 93, 0.08), 0px 2px 6px rgba(0, 0, 0, 0.04)',
        'elevated': '0px 15px 35px -5px rgba(50, 50, 93, 0.1), 0px 5px 15px -5px rgba(0, 0, 0, 0.07)',
        'overlay': '0px 30px 60px -12px rgba(50, 50, 93, 0.15), 0px 18px 36px -18px rgba(0, 0, 0, 0.1)',
        'alert-critical': '0px 0px 0px 3px rgba(220, 38, 38, 0.2)',
        'alert-high': '0px 0px 0px 3px rgba(234, 88, 12, 0.2)',
        'alert-medium': '0px 0px 0px 3px rgba(217, 119, 6, 0.2)',
        'focus-ring': '0px 0px 0px 3px rgba(37, 99, 235, 0.15)',
      },

      /* ===== 圓角 — Stripe 保守風格 ===== */
      borderRadius: {
        'btn': '4px',
        'input': '4px',
        'card': '8px',
        'panel': '12px',
        'bubble': '16px',
        'pill': '9999px',
      },

      /* ===== 動畫 — Linear/Stripe 微互動 ===== */
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-down': 'slideDown 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
        'scale-in': 'scaleIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-alert': 'pulseAlert 2s ease-in-out infinite',
        'recording': 'recording 1.5s ease-in-out infinite',
        'shimmer': 'shimmer 2s linear infinite',
        'stagger-1': 'slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1) 0.05s both',
        'stagger-2': 'slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1) 0.1s both',
        'stagger-3': 'slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1) 0.15s both',
        'stagger-4': 'slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1) 0.2s both',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-6px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        scaleIn: {
          '0%': { transform: 'scale(0.95)', opacity: '0' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        pulseAlert: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(220, 38, 38, 0.4)' },
          '50%': { boxShadow: '0 0 0 8px rgba(220, 38, 38, 0)' },
        },
        recording: {
          '0%, 100%': { transform: 'scale(1)', opacity: '1' },
          '50%': { transform: 'scale(1.1)', opacity: '0.8' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },

      /* ===== 最大寬度 ===== */
      maxWidth: {
        'content': '1280px',
      },

      /* ===== 過渡 — Stripe 精緻時序 ===== */
      transitionTimingFunction: {
        'spring': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      transitionDuration: {
        'fast': '150ms',
        'normal': '200ms',
        'slow': '350ms',
      },

      /* ===== 模糊 — Sentry 毛玻璃 ===== */
      backdropBlur: {
        'glass': '16px',
      },
    },
  },

  plugins: [],
};
