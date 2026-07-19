---
name: research-analytics
description: /research 研究分析頁與 /api/v1/research/analytics 的開發守則（期刊級圖表規格、Wilson CI 分子⊆分母鐵律、seed 陷阱、WS 即時更新）。Use when 修改 research 分析頁、analytics API、新增指標或圖表、或建立 demo/seed 資料時。
---

# 研究分析頁開發守則

## Overview

/research 頁是期刊級統計儀表板（箱形圖、Wilson 95% CI、森林圖、Table 1、SVG 匯出），指標對齊 DECIDE-AI / AMIE / triage / PDQI-9 / SAMPL 規範，由 WebSocket 驅動即時更新。完整規格在 [docs/research_analytics.md](../../../docs/research_analytics.md)，問診全流程對照 [docs/consultation_flow.md](../../../docs/consultation_flow.md)。

## When to Use

- 改 `/research` 前端頁或 `/api/v1/research/analytics` API
- 新增統計指標、圖表、匯出格式
- 建 demo / seed 資料
- NOT for：一般 dashboard（醫師端）改動

## 鐵律

1. **比例指標的分子必須是分母的子集**。違反時 Wilson CI 會對負數開根號 → API 500。新增任何 proportion 指標前先確認母體定義。
2. 圖表規格對齊期刊要求（SAMPL 統計報告、DECIDE-AI 等），別用「隨手 bar chart」替代既有的箱形圖/森林圖設計。
3. 即時更新走 WS 事件驅動，別加輪詢。
4. **Seed 分區表陷阱**：seed 資料時注意 session 相關表的分區設計（詳見 docs/research_analytics.md 的 E2E 驗證章節），直接 INSERT 錯分區會讓分析頁看不到資料。

## 驗證方法

- 基準：2026-07-06 已用 40 場 × 5 語言真 OpenAI 問診端到端驗證過整頁（方法見 `e2e-real-openai` skill 的批次法）。大改後用同法回歸。
- 小改：本機 seed 幾場資料 → 開 /research 核對每個圖表非空且數字對得上 DB query。

## Verification

- [ ] 所有 proportion 指標分子⊆分母（新指標附母體定義）
- [ ] /research 每個區塊在有資料與零資料兩種狀態下都不報錯
- [ ] WS 推新場次後頁面即時反映
