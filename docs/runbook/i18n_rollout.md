# UroVoice i18n Canary Rollout Runbook（TODO-O6）

> 目的：把 `MULTILANG_GLOBAL_ENABLED` + 非 zh-TW 語言（先 en-US）從零推到 100%，
> 每階段有明確 entry / exit 指標，任何 exit 未達門檻就不進下一階段。
>
> 主要風險：
> 1. 語音 pipeline 對英文對話的醫療術語辨識退化 → SOAP 品質下降
> 2. Red flag semantic prompt 對英文口語未 ground truth → 漏紅旗（臨床風險）
> 3. Kill switch 操作失手 → 所有語言被關
>
> 所有指標 metric 均來自 TODO-O2 於 `/metrics` 暴露的 Prometheus 系列。
> Dashboard: `docs/observability/grafana_i18n_overview.json` → UroVoice i18n Overview

---

## 總覽

| Stage | 使用者範圍 | Rollout 設定 | 預期時長 |
| --- | --- | --- | --- |
| 1 | 內部 10 位工程師 / QA | `MULTILANG_ROLLOUT_PERCENT=0` + allowlist | 48h |
| 2 | 1 家 Beta 診所 | `MULTILANG_ROLLOUT_PERCENT=0` + clinic allowlist | 2 週 |
| 3 | 10% 全用戶 | `MULTILANG_ROLLOUT_PERCENT=10` | 1 週 |
| 4 | 100% 全用戶 | `MULTILANG_ROLLOUT_PERCENT=100` | 正式上線 |

所有階段都以 `MULTILANG_GLOBAL_ENABLED=True`、`DEFAULT_LANGUAGE=zh-TW` 為前提；
kill switch 一律改這兩個變數，不改 code、不改 migration。

---

## Stage 1 — Internal (10 users)

### Entry 條件（皆須打勾）

- [ ] CI 全綠：`backend/tests/`、`frontend/*/tests/` 連續 3 個 commit 都 pass
- [ ] Staging 部署通過：`/api/v1/healthz/deep` 回 200、`/metrics` 可拉到 `urovoice_` 前綴系列
- [ ] i18n 單元測試 pass：`tests/unit/utils/test_resolve_language.py`
- [ ] Sentry 已接：staging 環境手動丟一個 en-US session 錯誤，event Tags 區有 `session.language`
- [ ] Feature flag 默認：
  ```
  MULTILANG_GLOBAL_ENABLED=True
  MULTILANG_ROLLOUT_PERCENT=0
  MULTILANG_DISABLED_LANGUAGES=         # 空
  DEFAULT_LANGUAGE=zh-TW
  ```
  並在 Railway 對 10 位內部 user 的 `preferred_language=en-US` hard-code（DB 直改）

### 監控指標（每天人工看一次）

| 指標 | 面板 | 門檻 |
| --- | --- | --- |
| en-US session 建立量 | Sessions by language | >= 5 / 48h |
| STT/TTS p95 延遲 | STT / TTS p95 latency | en-US <= 2× zh-TW |
| Sentry error rate | Sentry Issues filter | 48h 零 PagerDuty |
| SOAP revision rate | SOAP metrics（M15 埋點） | < 20% |

### Exit 條件

- [ ] 連續 48h 零 PagerDuty High / Critical
- [ ] SOAP revision rate < 20%（由 app/services/report_service M15 的 metric 導出）
- [ ] 至少 3 個 en-US session 完成完整 SOAP 流程
- [ ] 工程師口頭 sign-off（寫在 `#urovoice-i18n-rollout` thread）

### Rollback

```bash
# 立即關掉所有非預設語言（en-US 會退回 zh-TW）
railway variables set MULTILANG_DISABLED_LANGUAGES="en-US"
railway redeploy
# 確認 /metrics 看 urovoice_forced_fallback_total{from="en-US",to="zh-TW"} 開始累積
```

### Oncall 聯絡

- 主：工程 oncall（PagerDuty Rotation: `urovoice-backend`）
- 副：產品 (PM) → Slack DM
- 臨床：只在有 red flag 漏報時才 escalate 到診所醫師 group

### 進下一階段的觸發條件

- 時間：Stage 1 開始後第 48h
- 指標：上述 exit 全勾

---

## Stage 2 — Beta Clinic (1 家診所)

### Entry 條件

- [ ] Stage 1 exit 全勾
- [ ] 法律 sign-off：確認該診所已簽 i18n 增項同意書（`legal/i18n_consent_addendum.pdf`）
- [ ] 臨床 sign-off：該診所主任在 `#clinical-review` 確認願承擔 Beta
- [ ] Allowlist：該診所 user 的 `preferred_language` 可設 en-US，其他用戶仍 `MULTILANG_ROLLOUT_PERCENT=0`
- [ ] Red flag 校正人力到位：每週 1 次臨床審核時間已排（共 2 週 × 1h）

### 監控指標

| 指標 | 面板 | 門檻 |
| --- | --- | --- |
| en-US session 量 | Sessions by language | 每週 >= 20 |
| Red flag precision | 臨床人工審核表 | >= 90%（2 週內） |
| NPS | 診所端問卷 | >= 7 |
| Forced fallback | Forced fallback trend | 穩定在 baseline ±30% |
| Sentry en-US error rate | Sentry Rule 1 | 不觸發 |

### Exit 條件

- [ ] 2 週週期紅旗 precision >= 90%（臨床審核結果寫入 `docs/clinical/red_flag_beta_review.md`）
- [ ] 該診所 NPS >= 7
- [ ] 零 PII 外洩事件（由 audit log review 確認）
- [ ] 主任簽名 sign-off

### Rollback

```bash
# 選項 A：只關 Beta 診所 en-US（改診所 user 的 preferred_language 回 zh-TW）
# 選項 B：全域 kill（適用於 red flag precision 崩盤時）
railway variables set MULTILANG_DISABLED_LANGUAGES="en-US"
railway redeploy
```

### Oncall 聯絡

- 主：工程 oncall（PagerDuty）
- 臨床：該診所主任直撥（電話已登記於 `#urovoice-i18n-rollout` pinned message）
- 產品：PM 主導 Beta 協議終止流程

### 進下一階段的觸發條件

- 時間：Stage 2 開始後 14 天
- 指標：上述 exit 全勾 + 臨床審核報告上傳

---

## Stage 3 — 10% Users

### Entry 條件

- [ ] Stage 2 exit 全勾
- [ ] Canary flag 調整：
  ```
  MULTILANG_ROLLOUT_PERCENT=10
  ```
- [ ] Grafana alert 建立：en-US error rate > 1.5× zh-TW 自動 PagerDuty（Prometheus rule 範本見下）

#### Prometheus 告警 rule（放入 Grafana Alerting）
```promql
(
  sum(rate(urovoice_sessions_total{language="en-US"}[5m]))
  > 0
)
and
(
  sum by () (rate(urovoice_red_flag_triggers_total{language="en-US"}[1h]))
  /
  sum by () (rate(urovoice_sessions_total{language="en-US"}[1h]))
) >
1.5 *
(
  sum by () (rate(urovoice_red_flag_triggers_total{language="zh-TW"}[1h]))
  /
  sum by () (rate(urovoice_sessions_total{language="zh-TW"}[1h]))
)
```

### 監控指標

| 指標 | 面板 | 門檻 |
| --- | --- | --- |
| en-US 占比 | Sessions by language | 接近 10%（±3%） |
| en-US 錯誤率 vs zh-TW | 自建 Grafana | <= 1.5× |
| STT/TTS p95 | STT / TTS p95 | en-US <= 1.5× zh-TW |
| SOAP 完成率 | Report metrics | en-US >= 95%（與 zh-TW 一致） |

### Exit 條件

- [ ] 連續 7 天 en-US 錯誤率相對 zh-TW <= 1.5×（以 O2 metric 1h rolling 量測）
- [ ] 零 Sentry Rule 1 觸發
- [ ] 0 次 manual kill switch 操作

### Rollback

```bash
# 降回 0%，但保留 Stage 1/2 allowlist（不影響內部 & Beta 診所）
railway variables set MULTILANG_ROLLOUT_PERCENT=0
railway redeploy
```

### Oncall 聯絡

- 主：PagerDuty `urovoice-backend` rotation
- 自動化：Prometheus rule 直接 page oncall，不需人工判讀

### 進下一階段的觸發條件

- 時間：Stage 3 開始後 7 天
- 指標：上述 exit 全勾 + `/metrics` 連續 7 天無缺樣本

---

## Stage 4 — 100% Users

### Entry 條件

- [ ] Stage 3 exit 全勾
- [ ] Rollout flag：
  ```
  MULTILANG_ROLLOUT_PERCENT=100
  ```
- [ ] 更新狀態頁（`status.urovoice.com`）公告「i18n now GA」

### 監控指標

| 指標 | 門檻 |
| --- | --- |
| en-US 實際覆蓋 | 與 user.preferred_language 分佈一致（抽樣 100 筆驗證） |
| Sentry Rule 1 / 2 | 連 14 天不觸發 |
| Customer support ticket 含「語言」關鍵字 | < 2 / 週 |

### Exit 條件

- [ ] 14 天穩定，正式寫入 `docs/専案開発進度.md` 為上線里程碑
- [ ] Runbook 歸檔（不再動）

### Rollback（緊急）

```bash
# 最後防線 — 全域 kill，所有語言退回 zh-TW（0.5s 生效）
railway variables set MULTILANG_GLOBAL_ENABLED=False
railway redeploy
# 或針對單一語言
railway variables set MULTILANG_DISABLED_LANGUAGES="en-US,ja-JP"
railway redeploy
```

### Oncall 聯絡

- 主：PagerDuty
- 升級：若 30min 內未收回正常範圍，CTO + 該班 oncall 共同決策是否全域 kill

---

## 附錄：kill switch 速查

| 緊急程度 | 指令 | 生效範圍 |
| --- | --- | --- |
| 最高（全停） | `railway variables set MULTILANG_GLOBAL_ENABLED=False` | 所有非 zh-TW 請求退回 zh-TW |
| 高（單語言） | `railway variables set MULTILANG_DISABLED_LANGUAGES="en-US"` | 只關 en-US |
| 中（降 rollout） | `railway variables set MULTILANG_ROLLOUT_PERCENT=0` | 新使用者不進，既有 allowlist 不受影響 |
| 低（特定診所） | DB UPDATE `users.preferred_language='zh-TW' where clinic_id=X` | 針對性回退 |

所有 kill switch 操作都須同步在 `#urovoice-i18n-rollout` 發 pre/post 兩則訊息，
並更新 `docs/runbook/i18n_rollout.md` 的「事件紀錄」表（Stage 4 之後再加這節）。
