# 泌尿科 AI 語音問診助手 — 設計系統

> 融合方案: **Stripe (基底 60%)** + **Intercom (對話 25%)** + **Sentry (告警 15%)**

## 設計哲學

- **信任優先**: 深海軍藍標題 (`#061b31`) 而非純黑 — 醫療系統需要溫度
- **告警可辨識**: 四級告警色 + 圖標 + 文字，不僅依賴顏色（色盲友善）
- **夜班暗色**: luminance stacking 偏藍黑，降低夜間眼疲勞
- **數據精準**: 所有數值使用 `font-feature-settings: "tnum"` 確保表格對齊
- **對話清晰**: AI 暖橙 / 醫師沈穩藍 / 系統中性灰
- **可及性**: WCAG AA 以上對比度，明確焦點環

---

## 1. 色彩系統

### Light Mode（基底 — Stripe 風格）

| Token | Hex | 用途 |
|-------|-----|------|
| `--bg-primary` | `#ffffff` | 主背景 |
| `--bg-secondary` | `#f8f9fc` | 次要背景（側邊欄、交替行） |
| `--bg-tertiary` | `#f1f3f9` | 卡片懸停、輸入框背景 |
| `--text-heading` | `#061b31` | 標題（Stripe 深海軍藍） |
| `--text-body` | `#425466` | 正文 |
| `--text-secondary` | `#64748d` | 次要文字 |
| `--text-muted` | `#8898aa` | 輔助文字、placeholder |
| `--border-default` | `#e5edf5` | 預設邊框 |
| `--border-hover` | `#d0dae8` | 懸停邊框 |

### Dark Mode（Linear luminance stacking）

| Token | Hex | 用途 |
|-------|-----|------|
| `--dark-bg-primary` | `#0f1117` | 主背景（藍黑） |
| `--dark-bg-secondary` | `#171b24` | 面板背景 |
| `--dark-bg-surface` | `#1e2330` | 卡片表面 |
| `--dark-bg-hover` | `#272d3d` | 懸停 |
| `--dark-text-primary` | `#f7f8f8` | 主文字 |
| `--dark-text-secondary` | `#d0d6e0` | 次要文字 |
| `--dark-text-muted` | `#8a8f98` | 輔助文字 |
| `--dark-border` | `rgba(255,255,255,0.08)` | 邊框 |

### 品牌色

| Token | Hex | 用途 |
|-------|-----|------|
| `--brand-primary` | `#2563eb` | 主按鈕、連結 |
| `--brand-primary-hover` | `#1d4ed8` | 主按鈕懸停 |
| `--brand-light` | `#dbeafe` | 品牌淡色背景 |

### 對話區域（Intercom 暖色調）

| Token | Hex | 用途 |
|-------|-----|------|
| `--chat-bg` | `#faf9f6` | 對話背景（暖白） |
| `--chat-patient` | `#2563eb` | 病患訊息（藍） |
| `--chat-patient-bg` | `#dbeafe` | 病患氣泡背景 |
| `--chat-ai` | `#ea580c` | AI 助手標記（暖橙） |
| `--chat-ai-bg` | `#fff7ed` | AI 氣泡背景 |
| `--chat-system` | `#64748d` | 系統訊息 |
| `--chat-system-bg` | `#f1f5f9` | 系統訊息背景 |
| `--chat-border` | `#dedbd6` | 對話區域邊框 |

### 告警系統（Intercom + Stripe 語義色）

| Token | Hex | 用途 | 背景 |
|-------|-----|------|------|
| `--alert-critical` | `#dc2626` | 危急（紅） | `#fef2f2` |
| `--alert-critical-border` | `#fecaca` | 危急邊框 | |
| `--alert-high` | `#ea580c` | 高度（橙） | `#fff7ed` |
| `--alert-high-border` | `#fed7aa` | 高度邊框 | |
| `--alert-medium` | `#d97706` | 中度（琥珀） | `#fffbeb` |
| `--alert-medium-border` | `#fde68a` | 中度邊框 | |
| `--alert-success` | `#16a34a` | 正常/成功（綠） | `#f0fdf4` |
| `--alert-success-border` | `#bbf7d0` | 成功邊框 | |

### 狀態色（Session Status）

| 狀態 | 文字色 | 背景色 | 邊框色 |
|------|--------|--------|--------|
| `waiting` | `#64748d` | `#f1f5f9` | `#e2e8f0` |
| `in_progress` | `#2563eb` | `#dbeafe` | `#bfdbfe` |
| `completed` | `#16a34a` | `#f0fdf4` | `#bbf7d0` |
| `aborted_red_flag` | `#dc2626` | `#fef2f2` | `#fecaca` |
| `cancelled` | `#6b7280` | `#f3f4f6` | `#e5e7eb` |

---

## 2. 字型系統

```css
--font-sans: 'Inter Variable', 'Inter', system-ui, -apple-system, sans-serif;
--font-mono: 'Source Code Pro', 'JetBrains Mono', ui-monospace, monospace;
--font-display: 'Inter Variable', system-ui, sans-serif;
```

### 字型比例

| 級別 | 大小 | 行高 | 權重 | 字距 | 用途 |
|------|------|------|------|------|------|
| Display | 36px | 1.2 | 700 | -0.72px | 頁面大標題 |
| H1 | 28px | 1.3 | 700 | -0.56px | 區塊標題 |
| H2 | 22px | 1.35 | 600 | -0.33px | 卡片標題 |
| H3 | 18px | 1.4 | 600 | -0.18px | 小節標題 |
| Body-L | 16px | 1.6 | 400 | 0 | 正文（報告） |
| Body | 14px | 1.5 | 400 | 0 | 預設正文 |
| Caption | 13px | 1.45 | 500 | 0 | 標籤、徽章 |
| Small | 12px | 1.4 | 400 | 0.1px | 輔助文字 |
| Tiny | 11px | 1.35 | 500 | 0.3px | 時間戳、註腳 |

### 特殊用法

- **表格數字**: `font-feature-settings: "tnum"` — SOAP 數據、生命體徵
- **告警標籤**: `text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600`
- **等寬數據**: 病歷號碼、診斷碼使用 `--font-mono`

---

## 3. 元件規格

### 圓角（Stripe 保守風格）

| Token | 值 | 用途 |
|-------|------|------|
| `--radius-sm` | 4px | 按鈕、輸入框、徽章 |
| `--radius-md` | 6px | 下拉選單、Tooltip |
| `--radius-lg` | 8px | 卡片、面板 |
| `--radius-xl` | 12px | 大型容器、Modal |
| `--radius-2xl` | 16px | 對話氣泡 |
| `--radius-pill` | 9999px | 狀態標籤、告警等級 pill |

### 陰影（Stripe 藍調系統）

```css
--shadow-sm: 0px 1px 2px rgba(50, 50, 93, 0.06),
             0px 1px 2px rgba(0, 0, 0, 0.04);
--shadow-md: 0px 4px 12px rgba(50, 50, 93, 0.08),
             0px 2px 6px rgba(0, 0, 0, 0.04);
--shadow-lg: 0px 15px 35px -5px rgba(50, 50, 93, 0.1),
             0px 5px 15px -5px rgba(0, 0, 0, 0.07);
--shadow-xl: 0px 30px 60px -12px rgba(50, 50, 93, 0.15),
             0px 18px 36px -18px rgba(0, 0, 0, 0.1);
--shadow-alert: 0px 0px 0px 3px var(--alert-critical),
               0px 0px 20px rgba(220, 38, 38, 0.3);
```

### 間距系統

| Token | 值 | 用途 |
|-------|------|------|
| `--space-1` | 4px | 最小間距 |
| `--space-2` | 8px | 內元素間距 |
| `--space-3` | 12px | 元素間距 |
| `--space-4` | 16px | 卡片內距 |
| `--space-5` | 20px | 小區塊間距 |
| `--space-6` | 24px | 區塊間距 |
| `--space-8` | 32px | 大區塊間距 |
| `--space-10` | 40px | 頁面內距 |
| `--space-12` | 48px | 區域分隔 |

### 按鈕

| 類型 | 背景 | 文字 | 邊框 | 圓角 | padding |
|------|------|------|------|------|---------|
| Primary | `--brand-primary` | `#ffffff` | none | 4px | 8px 16px |
| Secondary | `#ffffff` | `--text-heading` | `--border-default` | 4px | 8px 16px |
| Danger | `--alert-critical` | `#ffffff` | none | 4px | 8px 16px |
| Ghost | transparent | `--text-body` | none | 4px | 8px 16px |
| Pill Badge | `--alert-*` 背景色 | `--alert-*` 文字色 | none | 9999px | 2px 10px |

### 卡片

```css
.card {
  background: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 20px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-hover);
}
```

### 輸入框

```css
.input {
  background: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 4px;
  padding: 8px 12px;
  font-size: 14px;
  color: var(--text-heading);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.input:focus {
  border-color: var(--brand-primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
  outline: none;
}
```

---

## 4. 佈局原則

### 頁面結構

```
┌─────────────────────────────────────────┐
│ Header (h: 56px, border-bottom)         │
├────────┬────────────────────────────────┤
│Sidebar │ Main Content                   │
│(w:240px│ (padding: 24px 32px)           │
│ fixed) │                                │
│        │                                │
└────────┴────────────────────────────────┘
```

- **Header**: 56px 高度，`box-shadow: var(--shadow-sm)`
- **Sidebar**: 240px 寬度（收合時 64px），`border-right: 1px solid var(--border-default)`
- **Main Content**: `max-width: 1280px`，`padding: 24px 32px`
- **Breakpoints**: sm:640px, md:768px, lg:1024px, xl:1280px

### 資訊密度指南

| 頁面 | 密度 | 說明 |
|------|------|------|
| Dashboard | 高 | 統計卡片+佇列+告警一目了然 |
| 患者列表 | 中高 | 表格行間距 compact (40px 行高) |
| SOAP 報告 | 中 | 充足留白，Body-L (16px) 字型 |
| 對話介面 | 低 | 大氣泡，充足間距，專注對話 |
| 告警詳情 | 中高 | 重要資訊突出，建議行動清晰 |

---

## 5. 各頁面設計來源對應

| 頁面 | 主要參考 | 關鍵採用 |
|------|---------|---------|
| 醫師儀表板 | Stripe + Linear | 藍調陰影卡片, tnum 數據 |
| 患者佇列 | Linear + Cal.com | 列表元件, 狀態 pill badge |
| 對話介面 | Intercom | 暖白背景, AI/病患色彩區分 |
| SOAP 報告 | Stripe | tnum 表格, 保守圓角, 精準間距 |
| 告警管理 | Sentry + Intercom | 監控思維, 四級色彩, uppercase 標籤 |
| 患者管理 | Stripe + Notion | 資料表格, 暖色交替行 |
| 管理後台 | Supabase + Stripe | 後台風格, border hierarchy |

---

## 6. Do's and Don'ts

### Do's
- 使用語義色而非品牌色傳達狀態
- 所有告警同時使用顏色+圖標+文字（色盲友善）
- 表格數值使用 `"tnum"` 確保對齊
- 保持 WCAG AA 以上對比度
- 對話區域使用暖色調降低焦慮感
- 暗色模式使用藍黑色而非純黑

### Don'ts
- 不要使用純黑 `#000000` 作為文字 — 用 `#061b31`
- 不要讓告警僅依賴顏色區分 — 必須搭配圖標或文字
- 不要在對話區域使用冷色調背景
- 不要使用超過 12px 的圓角用於按鈕（保守=專業）
- 不要在 SOAP 報告中使用比例數字 — 必須用表格數字
- 不要讓陰影過重 — 醫療介面需要輕盈精緻感

---

## 7. 動效與互動系統（Motion & Interaction System）

> 設計系統分析來源：**Raycast**（快速鍵盤互動）、**Framer**（動效優先設計）、**Cursor**（AI 串流 UI）、**Vercel**（精準極簡過渡）
>
> 融合原則：醫療 UI 動效必須在「專業沈穩」與「即時回饋」之間取得平衡 — 不能像遊戲那麼浮誇，也不能像靜態文件那麼遲鈍。

### 7.1 動效時間系統（Timing Tokens）

從四個設計系統中提取的時間模型，針對醫療場景校準：

| Token | 值 | 來源啟發 | 醫療 UI 用途 |
|-------|------|---------|-------------|
| `--duration-instant` | `100ms` | Raycast (opacity hover) | 按鈕 hover/active 回饋 |
| `--duration-fast` | `150ms` | Cursor (color transitions) | 文字色變、邊框色變、focus ring |
| `--duration-normal` | `200ms` | Vercel (shadow transitions) | 卡片陰影提升、面板展開 |
| `--duration-moderate` | `300ms` | Framer (scale animations) | 模態視窗、下拉選單、告警進場 |
| `--duration-slow` | `400ms` | Framer (page transitions) | 頁面切換、大面板過渡 |
| `--duration-deliberate` | `500ms` | 醫療校準 | 危急告警脈動、錄音指示器 |
| `--duration-streaming` | `30ms` | Cursor (token streaming) | AI 文字串流逐字出現 |

```css
:root {
  --duration-instant: 100ms;
  --duration-fast: 150ms;
  --duration-normal: 200ms;
  --duration-moderate: 300ms;
  --duration-slow: 400ms;
  --duration-deliberate: 500ms;
  --duration-streaming: 30ms;
}
```

### 7.2 緩動曲線（Easing Curves）

| Token | 值 | 來源啟發 | 用途 |
|-------|------|---------|------|
| `--ease-default` | `cubic-bezier(0.25, 0.1, 0.25, 1.0)` | Vercel 精準工程 | 通用預設 — 卡片、面板、輸入框 |
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Framer 動效優先 | 元素進場 — 告警滑入、通知出現 |
| `--ease-in` | `cubic-bezier(0.55, 0.055, 0.675, 0.19)` | Raycast 效率感 | 元素退場 — 通知消失、面板收合 |
| `--ease-in-out` | `cubic-bezier(0.45, 0, 0.55, 1)` | Vercel 對稱感 | 狀態切換 — 暗色模式、toggle |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Framer spring 物理 | 微互動 — 按鈕按壓回彈、toggle 切換 |
| `--ease-medical` | `cubic-bezier(0.22, 0.68, 0.36, 1.0)` | 醫療專用校準 | 告警卡片 — 快速到位但不驚嚇，尾端柔和 |

```css
:root {
  --ease-default: cubic-bezier(0.25, 0.1, 0.25, 1.0);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in: cubic-bezier(0.55, 0.055, 0.675, 0.19);
  --ease-in-out: cubic-bezier(0.45, 0, 0.55, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-medical: cubic-bezier(0.22, 0.68, 0.36, 1.0);
}
```

### 7.3 互動狀態（Interaction States）

#### 按鈕互動（參考 Raycast opacity 模式 + Vercel shadow-border 技法）

```css
/* Primary Button */
.btn-primary {
  background: var(--brand-primary);
  color: #ffffff;
  border-radius: 4px;
  padding: 8px 16px;
  transition:
    background-color var(--duration-fast) var(--ease-default),
    box-shadow var(--duration-fast) var(--ease-default),
    transform var(--duration-instant) var(--ease-spring);
}
.btn-primary:hover {
  background: var(--brand-primary-hover);
  box-shadow: 0px 2px 8px rgba(37, 99, 235, 0.25);
}
.btn-primary:active {
  transform: scale(0.97);
  box-shadow: 0px 1px 4px rgba(37, 99, 235, 0.2);
}
.btn-primary:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.15);
}

/* Danger Button — 告警行動按鈕 */
.btn-danger {
  background: var(--alert-critical);
  transition:
    background-color var(--duration-fast) var(--ease-default),
    box-shadow var(--duration-fast) var(--ease-default);
}
.btn-danger:hover {
  background: #b91c1c;
  box-shadow: 0px 2px 12px rgba(220, 38, 38, 0.3);
}
.btn-danger:focus-visible {
  box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.2);
}
```

#### 卡片互動（參考 Vercel 多層陰影堆疊 + Cursor 暖色邊框）

```css
/* Dashboard Card */
.card {
  background: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 20px;
  box-shadow: var(--shadow-sm);
  transition:
    box-shadow var(--duration-normal) var(--ease-default),
    border-color var(--duration-normal) var(--ease-default),
    transform var(--duration-normal) var(--ease-default);
}
.card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-hover);
  transform: translateY(-1px);
}
.card:active {
  transform: translateY(0px);
  box-shadow: var(--shadow-sm);
}
```

#### 輸入框 Focus（參考 Vercel focus-ring + Raycast blue glow）

```css
.input {
  transition:
    border-color var(--duration-fast) var(--ease-default),
    box-shadow var(--duration-fast) var(--ease-default);
}
.input:focus {
  border-color: var(--brand-primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
  outline: none;
}
/* 告警狀態輸入框 */
.input--error {
  border-color: var(--alert-critical);
}
.input--error:focus {
  box-shadow: 0 0 0 3px rgba(220, 38, 38, 0.15);
}
```

### 7.4 AI 串流 UI 系統（Streaming UI — 參考 Cursor）

Cursor 的 AI 串流介面使用逐 token 渲染 + 打字游標 + 程式碼區塊即時生成。
針對醫療問診 AI 助手，我們採用「逐詞塊」策略（word-chunk streaming）：

```css
/* AI 回應串流文字動效 */
@keyframes streamFadeIn {
  from {
    opacity: 0;
    transform: translateY(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ai-stream-chunk {
  display: inline;
  animation: streamFadeIn var(--duration-instant) var(--ease-out) both;
}

/* AI 回應打字游標（參考 Cursor blinking cursor） */
@keyframes cursorBlink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.ai-cursor {
  display: inline-block;
  width: 2px;
  height: 1.2em;
  background: var(--chat-ai);
  margin-left: 1px;
  vertical-align: text-bottom;
  animation: cursorBlink 800ms step-end infinite;
}

/* AI 串流氣泡容器 */
.ai-bubble-streaming {
  background: var(--chat-ai-bg);
  border: 1px solid #fed7aa;
  border-radius: 16px;
  padding: 12px 16px;
  min-height: 40px;
  transition: min-height var(--duration-normal) var(--ease-default);
}

/* 串流完成後的過渡 */
.ai-bubble-complete {
  animation: bubbleSettle var(--duration-moderate) var(--ease-default);
}

@keyframes bubbleSettle {
  from {
    box-shadow: 0 0 0 2px rgba(234, 88, 12, 0.1);
  }
  to {
    box-shadow: none;
  }
}
```

**串流策略說明**:
- **不用逐字元**：中文逐字元會造成視覺閃爍，且拆字會破壞語意
- **採用逐詞塊**（3-5 字一組）：每 `--duration-streaming`（30ms）追加一個 chunk，帶有微小的 `streamFadeIn` 動效
- **打字游標**：暖橙色 blinking cursor 在串流結束前持續顯示，與 `--chat-ai` 色相匹配
- **氣泡自適應**：高度跟隨內容增長，使用 CSS transition 平滑過渡

### 7.5 即時更新動效（Real-time WebSocket Updates）

#### 新患者進入佇列

```css
@keyframes slideInFromRight {
  from {
    opacity: 0;
    transform: translateX(20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.queue-item-enter {
  animation: slideInFromRight var(--duration-moderate) var(--ease-out);
}

/* 新項目高亮（短暫背景閃爍提示「有新東西」） */
@keyframes newItemHighlight {
  0% {
    background-color: rgba(37, 99, 235, 0.12);
  }
  100% {
    background-color: transparent;
  }
}

.queue-item-new {
  animation: newItemHighlight 1.5s var(--ease-default);
}
```

#### 狀態變更過渡

```css
/* 患者狀態 pill badge 切換（如 waiting → in_progress） */
.status-badge {
  transition:
    background-color var(--duration-normal) var(--ease-in-out),
    color var(--duration-normal) var(--ease-in-out),
    border-color var(--duration-normal) var(--ease-in-out);
}

/* 佇列排序重排動效 */
.queue-item {
  transition:
    transform var(--duration-slow) var(--ease-out),
    opacity var(--duration-moderate) var(--ease-default);
}

/* 項目移除 */
@keyframes slideOutLeft {
  to {
    opacity: 0;
    transform: translateX(-20px);
    height: 0;
    margin: 0;
    padding: 0;
  }
}

.queue-item-exit {
  animation: slideOutLeft var(--duration-moderate) var(--ease-in) forwards;
}
```

#### 數值即時更新（Dashboard 統計數字）

```css
/* 數字跳動效果（Vercel metric card 啟發） */
@keyframes counterPulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.05); color: var(--brand-primary); }
  100% { transform: scale(1); }
}

.stat-value-updated {
  animation: counterPulse var(--duration-moderate) var(--ease-spring);
  font-feature-settings: "tnum";
}
```

### 7.6 告警動效系統（Alert Animations）

#### 紅旗告警進場（必須引起注意但不造成恐慌）

```css
/* 告警通知進場 — 從上方滑入 + 微彈跳 */
@keyframes alertSlideIn {
  0% {
    opacity: 0;
    transform: translateY(-16px) scale(0.95);
  }
  70% {
    opacity: 1;
    transform: translateY(2px) scale(1.01);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.alert-enter {
  animation: alertSlideIn var(--duration-moderate) var(--ease-medical);
}

/* 危急告警持續脈動（Critical Red Flag）
   柔和的邊框呼吸效果 — 不用 scale 避免驚嚇 */
@keyframes criticalPulse {
  0%, 100% {
    box-shadow:
      0px 0px 0px 1px var(--alert-critical-border),
      0px 0px 0px 3px rgba(220, 38, 38, 0.08);
  }
  50% {
    box-shadow:
      0px 0px 0px 1px var(--alert-critical),
      0px 0px 0px 5px rgba(220, 38, 38, 0.15),
      0px 0px 20px rgba(220, 38, 38, 0.1);
  }
}

.alert-critical-active {
  animation: criticalPulse 2s var(--ease-in-out) infinite;
}

/* 高度告警（橙色，較輕微的脈動） */
@keyframes highAlertPulse {
  0%, 100% {
    border-color: var(--alert-high-border);
  }
  50% {
    border-color: var(--alert-high);
    box-shadow: 0px 0px 12px rgba(234, 88, 12, 0.12);
  }
}

.alert-high-active {
  animation: highAlertPulse 3s var(--ease-in-out) infinite;
}

/* 告警退場 */
@keyframes alertDismiss {
  to {
    opacity: 0;
    transform: translateX(30px) scale(0.95);
  }
}

.alert-dismiss {
  animation: alertDismiss var(--duration-moderate) var(--ease-in) forwards;
}
```

**告警動效設計原則**（醫療 UI 專用）:
- 危急（Critical）：2 秒脈動循環，使用邊框光暈而非整體縮放 — 持續提醒但不造成恐慌
- 高度（High）：3 秒脈動循環，僅邊框色變 — 柔和提示
- 中度（Medium）：靜態顯示，不脈動 — 減少視覺噪音
- 成功（Success）：不脈動 — 綠色靜態即可傳達「一切正常」

### 7.7 麥克風錄音按鈕動效

```css
/* 麥克風按鈕 — 待機狀態 */
.mic-button {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--brand-primary);
  color: #ffffff;
  border: none;
  cursor: pointer;
  position: relative;
  transition:
    background-color var(--duration-fast) var(--ease-default),
    transform var(--duration-instant) var(--ease-spring),
    box-shadow var(--duration-fast) var(--ease-default);
}

.mic-button:hover {
  background: var(--brand-primary-hover);
  box-shadow: 0px 4px 16px rgba(37, 99, 235, 0.3);
}

.mic-button:active {
  transform: scale(0.93);
}

/* 錄音中 — 呼吸脈動圈 */
@keyframes micPulseRing {
  0% {
    transform: scale(1);
    opacity: 0.4;
  }
  100% {
    transform: scale(1.8);
    opacity: 0;
  }
}

.mic-button--recording {
  background: var(--alert-critical);
}

.mic-button--recording::before,
.mic-button--recording::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: 50%;
  border: 2px solid var(--alert-critical);
  animation: micPulseRing 1.5s var(--ease-out) infinite;
}

.mic-button--recording::after {
  animation-delay: 0.5s;
}

/* 錄音中 — 音量指示器（環形進度） */
@keyframes volumeGlow {
  0%, 100% {
    box-shadow: 0 0 0 3px rgba(220, 38, 38, 0.2);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(220, 38, 38, 0.35);
  }
}

.mic-button--recording {
  animation: volumeGlow 0.8s var(--ease-in-out) infinite;
}

/* 錄音完成 — 收束確認 */
@keyframes micComplete {
  0% {
    transform: scale(1);
    background: var(--alert-critical);
  }
  50% {
    transform: scale(0.9);
    background: var(--alert-success);
  }
  100% {
    transform: scale(1);
    background: var(--brand-primary);
  }
}

.mic-button--complete {
  animation: micComplete var(--duration-deliberate) var(--ease-spring);
}
```

### 7.8 Loading Skeleton 系統（參考 Vercel 極簡骨架屏）

```css
/* 基礎骨架脈動 */
@keyframes skeletonShimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

.skeleton {
  background:
    linear-gradient(
      90deg,
      var(--bg-secondary) 0%,
      var(--bg-tertiary) 40%,
      var(--bg-secondary) 80%
    );
  background-size: 200% 100%;
  animation: skeletonShimmer 1.8s var(--ease-in-out) infinite;
  border-radius: 4px;
}

/* 暗色模式骨架 */
[data-theme="dark"] .skeleton {
  background:
    linear-gradient(
      90deg,
      var(--dark-bg-secondary) 0%,
      var(--dark-bg-surface) 40%,
      var(--dark-bg-secondary) 80%
    );
  background-size: 200% 100%;
}

/* 醫療數據卡片骨架 */
.skeleton-stat-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 20px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

.skeleton-stat-card .skeleton-label {
  width: 60%;
  height: 14px;
}

.skeleton-stat-card .skeleton-value {
  width: 40%;
  height: 32px;
}

.skeleton-stat-card .skeleton-trend {
  width: 80%;
  height: 10px;
}

/* 對話氣泡骨架 */
.skeleton-chat-bubble {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 16px;
  background: var(--chat-ai-bg);
  max-width: 70%;
}

.skeleton-chat-bubble .skeleton-line {
  height: 14px;
  border-radius: 3px;
}

.skeleton-chat-bubble .skeleton-line:nth-child(1) { width: 90%; }
.skeleton-chat-bubble .skeleton-line:nth-child(2) { width: 75%; }
.skeleton-chat-bubble .skeleton-line:nth-child(3) { width: 60%; }

/* 佇列列表骨架 */
.skeleton-queue-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-default);
}

.skeleton-queue-row .skeleton-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  flex-shrink: 0;
}

.skeleton-queue-row .skeleton-name {
  width: 120px;
  height: 14px;
}

.skeleton-queue-row .skeleton-status {
  width: 72px;
  height: 22px;
  border-radius: 9999px;
  margin-left: auto;
}
```

### 7.9 暗色模式轉場（Dark Mode Transition）

參考 Vercel 的極簡切換 + Raycast 的 macOS 原生感：

```css
/* 全局主題過渡（應用於 html 或 body） */
html {
  transition:
    background-color var(--duration-slow) var(--ease-in-out),
    color var(--duration-slow) var(--ease-in-out);
}

/* 所有受主題影響的元素使用統一過渡 */
html.theme-transitioning *,
html.theme-transitioning *::before,
html.theme-transitioning *::after {
  transition:
    background-color var(--duration-slow) var(--ease-in-out),
    border-color var(--duration-slow) var(--ease-in-out),
    color var(--duration-slow) var(--ease-in-out),
    box-shadow var(--duration-slow) var(--ease-in-out),
    fill var(--duration-slow) var(--ease-in-out),
    stroke var(--duration-slow) var(--ease-in-out) !important;
}
```

**使用方式**（JavaScript）:
```javascript
function toggleTheme() {
  document.documentElement.classList.add('theme-transitioning');
  document.documentElement.setAttribute('data-theme',
    document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'
  );
  setTimeout(() => {
    document.documentElement.classList.remove('theme-transitioning');
  }, 400); // 與 --duration-slow 匹配
}
```

### 7.10 微互動系統（Micro-interactions）

#### Toggle 切換（參考 Framer spring 物理 + Raycast 精準感）

```css
.toggle-track {
  width: 44px;
  height: 24px;
  border-radius: 12px;
  background: #d0dae8;
  padding: 2px;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-in-out);
}

.toggle-track[aria-checked="true"] {
  background: var(--brand-primary);
}

.toggle-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow:
    0px 1px 3px rgba(0, 0, 0, 0.15),
    0px 1px 1px rgba(0, 0, 0, 0.06);
  transition:
    transform var(--duration-normal) var(--ease-spring);
}

.toggle-track[aria-checked="true"] .toggle-thumb {
  transform: translateX(20px);
}
```

#### 通知進出場

```css
/* Toast 通知進場（Framer 風格 — 從底部彈入） */
@keyframes toastEnter {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* Toast 通知退場 */
@keyframes toastExit {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateY(-8px) scale(0.95);
  }
}

.toast-enter {
  animation: toastEnter var(--duration-moderate) var(--ease-out);
}

.toast-exit {
  animation: toastExit var(--duration-normal) var(--ease-in);
}
```

#### 下拉選單展開

```css
/* Dropdown 展開（Vercel 精準感 + Raycast 陰影深度） */
@keyframes dropdownOpen {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes dropdownClose {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateY(-4px) scale(0.98);
  }
}

.dropdown-open {
  animation: dropdownOpen var(--duration-normal) var(--ease-out);
}

.dropdown-close {
  animation: dropdownClose var(--duration-fast) var(--ease-in);
}
```

#### Tooltip 動效

```css
@keyframes tooltipFade {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.tooltip {
  animation: tooltipFade var(--duration-fast) var(--ease-out);
}
```

### 7.11 頁面與路由過渡

```css
/* 頁面進場 */
@keyframes pageEnter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 頁面退場 */
@keyframes pageExit {
  from {
    opacity: 1;
  }
  to {
    opacity: 0;
  }
}

.page-enter {
  animation: pageEnter var(--duration-moderate) var(--ease-out);
}

.page-exit {
  animation: pageExit var(--duration-normal) var(--ease-in);
}
```

### 7.12 無障礙動效控制

```css
/* 尊重使用者的減少動效偏好 */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }

  /* 保留關鍵告警的視覺提示，僅移除動態效果 */
  .alert-critical-active {
    animation: none;
    box-shadow:
      0px 0px 0px 2px var(--alert-critical),
      0px 0px 12px rgba(220, 38, 38, 0.2);
  }

  /* 麥克風錄音狀態用靜態紅色環替代脈動 */
  .mic-button--recording::before,
  .mic-button--recording::after {
    animation: none;
    border: 3px solid rgba(220, 38, 38, 0.3);
    transform: scale(1.3);
    opacity: 1;
  }

  /* AI 串流回退為即時顯示 */
  .ai-stream-chunk {
    animation: none;
    opacity: 1;
  }
}
```

---

## 8. 醫療互動動效優化建議（Medical UI Motion Guidelines）

> 以下建議基於 Raycast、Framer、Cursor、Vercel 四套設計系統的動效哲學，
> 結合泌尿科 AI 語音問診場景的特殊需求提煉而成。

### 8.1 最佳過渡時間

| 場景 | 建議時長 | 理由 |
|------|---------|------|
| 按鈕 hover/active | 100-150ms | Raycast 風格：即時回饋感，醫師操作需要「按下即反應」 |
| 卡片陰影/邊框變化 | 200ms | Vercel 風格：精準但不急躁，適合 Dashboard 瀏覽 |
| 告警通知進場 | 300ms | Framer `--ease-medical`：快速到位但尾端柔和，不驚嚇患者/醫師 |
| 模態視窗/大面板 | 300-400ms | 足夠感知到過渡，但不拖延醫師工作流 |
| 暗色模式切換 | 400ms | 太快會閃爍，太慢會覺得遲鈍 — 400ms 是視覺舒適甜蜜點 |
| 頁面路由切換 | 200-300ms | 醫師頻繁切換頁面，不能有延遲感 |
| AI 串流逐字 | 30ms/chunk | Cursor 啟發：快到像即時打字，慢到可以追讀 |

**核心原則**：醫療 UI 的動效甜蜜點在 **150-300ms** — 比消費級 App（400-600ms）快，比工程工具（50-100ms）慢。這是因為醫師需要「確認操作已生效」的視覺回饋，但不能等待裝飾性動畫。

### 8.2 紅旗告警動效策略

**進場動效**：使用 `--ease-medical`（`cubic-bezier(0.22, 0.68, 0.36, 1.0)`），讓告警在 300ms 內「堅定地到位」而非「彈跳式進場」。避免 bounce/spring easing — 醫療告警不應該看起來像遊戲通知。

**持續提醒**：
- Critical：2s 邊框光暈脈動（`criticalPulse`）— 持續但不刺激
- High：3s 邊框色循環 — 比 Critical 更柔和
- 絕對禁止：螢幕閃爍、全屏覆蓋、聲音抖動 — 這些會在醫療場景中引發不必要的恐慌

**退場動效**：被處理後的告警向右滑出（`alertDismiss`），300ms，`--ease-in` — 給醫師「我已處理此告警」的確認感。

### 8.3 Dashboard 卡片過渡最佳緩動曲線

推薦 `--ease-default`（`cubic-bezier(0.25, 0.1, 0.25, 1.0)`）搭配 200ms。

理由：Vercel 的精準工程哲學最適合醫療 Dashboard — 卡片狀態更新時不需要 spring bounce 或彈性效果，需要的是「狀態 A 平滑過渡到狀態 B」的確定感。Cursor 的大模糊陰影（28px, 70px blur）不適合高密度醫療 Dashboard — 我們保持 Stripe 風格的藍調輕陰影。

### 8.4 麥克風錄音動效策略

1. **待機 → 按下**：`scale(0.93)` + `--ease-spring` — Framer 風格的微回彈
2. **錄音中**：雙環脈動擴散（`micPulseRing`，1.5s）+ 音量光暈呼吸（`volumeGlow`，0.8s）
3. **錄音結束**：收束動效（`micComplete`，500ms）— 紅色 → 綠色 → 品牌藍，三段式狀態確認
4. **設計意圖**：錄音中的脈動圈借鑒自 Apple 的錄音 UI — 醫師和患者都能直覺理解「正在收音」

### 8.5 AI 串流文字顯示策略

**推薦：逐詞塊（word-chunk）方式**，每 30ms 追加 3-5 個中文字。

| 策略 | 效果 | 適用性 |
|------|------|--------|
| 逐字元 | 逐字閃爍，中文會被拆散 | 不適合醫療中文 |
| 逐詞 | 自然但速度不均勻 | 可用，需詞切分 |
| 逐詞塊（推薦） | 流暢，語義完整，速度穩定 | 最適合中文醫療文本 |
| 逐行/段 | 一次出現太多，失去串流感 | 不推薦 |

CSS 實作：每個 chunk 使用 `streamFadeIn`（100ms, `--ease-out`）— 不是硬性出現，而是帶有微小的位移淡入（translateY 2px），讓醫師感受到「AI 正在思考和組織回答」。

### 8.6 WebSocket 即時更新動效

| 事件 | 動效 | 時長 | 緩動 |
|------|------|------|------|
| 新患者入列 | `slideInFromRight` + `newItemHighlight` | 300ms + 1.5s | `--ease-out` |
| 狀態切換 | `status-badge` 背景/文字色過渡 | 200ms | `--ease-in-out` |
| 佇列重排 | 列表項位置 `transform` 過渡 | 400ms | `--ease-out` |
| 項目完成移除 | `slideOutLeft` | 300ms | `--ease-in` |
| 統計數字更新 | `counterPulse` 微縮放 + 品牌色閃現 | 300ms | `--ease-spring` |

**關鍵原則**：新項目進場用「背景高亮漸消」（`newItemHighlight`，1.5s）而非「持續閃爍」— 醫療佇列可能頻繁更新，持續閃爍會造成嚴重的視覺干擾。

### 8.7 Loading Skeleton 模式

**醫療數據卡片推薦 shimmer 模式**：
- 使用 `linear-gradient` 掃描（非 pulse 透明度循環），1.8s 循環
- 骨架形狀需匹配最終內容的比例（統計值大、標籤窄、趨勢線長）
- 暗色模式下骨架色從 `--dark-bg-secondary` 到 `--dark-bg-surface` — 保持藍黑色調

**禁止事項**：
- 不要讓骨架屏超過 3 秒 — 如果 API 超過 3 秒，顯示進度指示器替代
- 不要在 SOAP 報告中使用骨架屏 — 報告要麼載入完成要麼顯示全頁 spinner
- 對話介面的骨架屏用「打字指示器」（三點呼吸動畫）替代矩形骨架

---

## 9. 設計系統來源對照表（完整版）

| 頁面/元件 | 主要參考 | 關鍵採用 |
|----------|---------|---------|
| 醫師儀表板 | Stripe + Linear + **Vercel** | 藍調陰影卡片, tnum 數據, **shadow-as-border 技法** |
| 患者佇列 | Linear + Cal.com + **Framer** | 列表元件, 狀態 pill badge, **slideIn/Out 動效** |
| 對話介面 | Intercom + **Cursor** | 暖白背景, AI/病患色彩區分, **串流打字動效** |
| SOAP 報告 | Stripe + **Vercel** | tnum 表格, 保守圓角, **精準間距**, skeleton loading |
| 告警管理 | Sentry + Intercom + **Raycast** | 監控思維, 四級色彩, **脈動光暈動效** |
| 麥克風按鈕 | **Framer** + Apple | **spring 物理**, 脈動圈擴散, 狀態三色切換 |
| 暗色模式 | **Raycast** + Linear | 藍黑色調（非純黑），**400ms ease-in-out 全局過渡** |
| 通知/Toast | **Framer** + **Vercel** | 底部彈入, 頂部淡出, 精準時間控制 |
| Toggle/表單 | **Framer** + **Cursor** | spring 回彈, 暖色 focus ring |
