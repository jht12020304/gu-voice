# Sentry — 語言維度告警規則（TODO-O3）

> i18n 上線後，英文版錯誤量不能被中文版的背景噪音蓋住。
> `app/core/sentry.py::set_language_scope()` 會在 session 建立時打上
> `session.language` tag，Sentry 告警 rule 用這個 tag 切片即可。

## Tag 產生時機（程式碼錨點）

| 時機 | 檔案 | 觸發動作 |
| --- | --- | --- |
| Session 建立成功 | `app/routers/sessions.py::create_session` | `set_language_scope(session.language)` |
| 未來：使用者登入 | （尚未接） | `set_language_scope(user.preferred_language)` |

> 注意：Sentry scope 是 request 維度的，web worker 處理下一個 request 前會被清空；
> 所以每個 request 路徑都必須自己 set 一次（不要靠 thread-local 快取）。

## Alert rule 樣板

以下為 Sentry 的 **Metric Alert**（非 Issue Alert）— 我們要的是錯誤率比率，不是單一 issue。

### Rule 1：英文版錯誤量暴衝
```
project: urovoice-backend
environment: production
when:
  count() of `event.type == "error"`
  where `tags[session.language]` equals "en-US"
  is above 10
  in the last 10 minutes
AND
  ratio of
    count(tags[session.language] == "en-US")
    /
    count(tags[session.language] == "zh-TW")
  is above 2x baseline (24h rolling)
action:
  → PagerDuty #urovoice-oncall (High)
  → Slack #urovoice-alerts
```

理由：若 en-US 絕對量低（< 10）即使比率高也可能是雜訊；要量 + 率同時滿足才告警。

### Rule 2：新語言 session 零建立（rollout 卡住）
```
when:
  count(transaction == "POST /api/v1/sessions"
        where tags[session.language] == "en-US"
        and response.status == 2xx)
  is below 1
  in the last 30 minutes
  (only between 09:00 and 21:00 Taipei time — 避開離峰假告警)
action:
  → Slack #urovoice-i18n-rollout (Low)
```

### Rule 3：forced_fallback 事件串接（跨 Sentry / Prometheus）
forced_fallback 事件不走 Sentry（不是錯誤），在 Grafana 的 `urovoice_forced_fallback_total` 面板看即可。
若 24h 某個 `from` label 累積 > 50，請人工對照 `MULTILANG_DISABLED_LANGUAGES` 是否應開放。

## 部署檢查清單

- [ ] Sentry 專案已切 `environment=production`
- [ ] Sentry SDK 版本 >= 2.19（已裝）
- [ ] `SENTRY_DSN` 已設於 Railway env
- [ ] 在 Sentry UI 建立上述三條 rule，且測試 `set_tag` 確實出現在 event 的 Tags 區塊
- [ ] 驗收方式：手動在 staging 發一個 500 error，檢查 Sentry event 頁 `Tags` 欄位是否有 `session.language: en-US`
