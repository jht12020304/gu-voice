# Add a new language to UroSense（新增語言 Runbook）

> 目的：在 UroSense 前端 i18n 新增一個 locale（例：`ja-JP`、`ko-KR`、`vi-VN`）時，
> 需要同步更新的檔案、流程、以及 CI 強制的最低覆蓋率規則。

---

## 1. 前端目錄結構

所有 locale JSON 放在 `frontend/src/i18n/locales/<locale>/<namespace>.json`。

目前 namespace：

| Namespace | 用途 |
| --- | --- |
| `common` | 共用按鈕 / 錯誤 / header / login / settings |
| `conversation` | 對話 UI 文字 |
| `ws` | WebSocket 連線狀態訊息 |
| `intake` | 病史 / 主訴 intake flow（規劃中） |
| `soap` | SOAP 報告模板（規劃中） |
| `dashboard` | 醫師儀表板（規劃中） |
| `session` | 場次管理 UI（規劃中） |

`zh-TW` 是 source of truth，所有其他 locale 的 key 集合應為 `zh-TW` 的子集或
等於集合。i18next fallback chain 會自動把缺 key 退回 `en-US`，再退回 `zh-TW`。

---

## 2. 新增一個 locale 的最小步驟

1. 建立 `frontend/src/i18n/locales/<locale>/common.json`，至少把 `common.json`
   翻完（beta 語言只要求這一檔）。
2. 更新 `frontend/src/i18n/index.ts` 註冊新 locale。
3. 若該語言要進 CI staleness check 的 **beta 清單**，把它加進：
   - `scripts/check_translations.py` 的 `DEFAULT_BETA_LOCALES`
   - `.github/workflows/i18n_staleness.yml` 的 `THRESHOLD`（若需要不同閾值）
4. 在 `docs/runbook/i18n_rollout.md` 的 Stage 1/2 entry 條件增加對應 allowlist
   設定。
5. 本地跑一次 staleness check 確認無漏 key：
   ```bash
   python scripts/check_translations.py
   ```

---

## 3. Translation staleness CI

### 3.1 script 用法

路徑：`scripts/check_translations.py`（Python 3.12 標準庫，無外部依賴）。

```bash
# 人類可讀報告
python scripts/check_translations.py

# 指定閾值（預設 95）
python scripts/check_translations.py --threshold 90

# 機器可讀 JSON（供 CI 解析）
python scripts/check_translations.py --json > translations.json

# GitHub Actions Markdown summary（會被 workflow 丟進 $GITHUB_STEP_SUMMARY）
python scripts/check_translations.py --github-summary

# 自訂 beta locale 清單（這些只檢查 common.json）
python scripts/check_translations.py --beta-locales "ja-JP,ko-KR,vi-VN"

# 自訂 reference 語言（預設 zh-TW）
python scripts/check_translations.py --reference zh-TW
```

Exit code：

| Code | 意義 |
| --- | --- |
| `0` | 所有 **active**（非 beta）locale 覆蓋率 >= threshold |
| `1` | 有 active locale 低於 threshold |
| `2` | Reference 目錄/檔案不存在等設定錯誤 |

### 3.2 CI workflow

- 路徑：`.github/workflows/i18n_staleness.yml`
- 觸發：PR 有動到下列任一檔才跑
  - `frontend/src/i18n/locales/**`
  - `scripts/check_translations.py`
  - `scripts/tests/test_check_translations.py`
  - `.github/workflows/i18n_staleness.yml`
- 步驟摘要：
  1. checkout + setup Python 3.12
  2. 跑 `--json` 產生 `translations.json` artifact
  3. 跑 `--github-summary` 把表格寫入 `$GITHUB_STEP_SUMMARY`
  4. 透過 `actions/github-script@v7` upsert PR comment：
     - FAIL → 一定貼
     - PASS 但任一 locale 覆蓋率相對上一次報告變動 > 5% → 貼
     - 否則靜默（避免每次 PR push 都刷留言）
  5. 依 script exit code 決定 job 結果

### 3.3 調整閾值

在 `.github/workflows/i18n_staleness.yml` 的 `env.THRESHOLD` 改數字即可：

```yaml
env:
  THRESHOLD: "95"   # 想暫時降低就改這裡，例如緊急放寬到 "90"
```

改完連動測試：

```bash
python scripts/check_translations.py --threshold 90
echo "exit=$?"
```

### 3.4 beta / active 邊界調整

- 新語言剛上線通常掛 beta：在 `--beta-locales` 加入後，只檢查 `common.json`，
  其他 namespace 缺 key 走 fallback，不會讓 CI 紅燈。
- 當該語言其他 namespace 也補齊（通常 >= 90%）後，把它從 beta 拿掉，讓
  staleness CI 正式守該 locale 的閾值。

### 3.5 本地 unit test

```bash
pip install pytest   # 若專案還沒裝
python -m pytest scripts/tests/ -v
```

共 15 支測試，涵蓋巢狀 key、多餘 key、beta locale、JSON / Markdown 輸出、
exit code 等路徑。

---

## 4. Using i18next-parser（A7）

### 4.1 和 `check_translations.py` 的分工

| 工具 | 檢查方向 | 抓到什麼問題 |
| --- | --- | --- |
| `frontend/npm run i18n:extract:check` | Code → JSON | 工程師寫了 `t('foo.bar')` 但 `zh-TW/<ns>.json` 沒這把 key（caller side） |
| `scripts/check_translations.py` | zh-TW JSON → 其他 locale JSON | zh-TW 有 key 但 en-US / ja-JP / ko-KR / vi-VN 任一 locale 沒寫翻譯（translator side） |

兩者互補不重疊：parser 守「有沒有漏寫 key」，check_translations 守「有沒有漏翻」。

### 4.2 CLI 用法

```bash
cd frontend

# 掃 src/**/*.{ts,tsx}，把所有 t() 呼叫的 key 輸出到 /tmp/urosense-i18n-extract/
# —— 不會動 frontend/src/i18n/locales/ 底下任何 JSON
npm run i18n:extract

# CI 模式：比對 tmp 產物 vs zh-TW 既有 JSON，有缺 key 就 exit 1
# CI（.github/workflows/i18n_staleness.yml 的 extract-keys-check job）跑這個
npm run i18n:extract:check
```

設定檔：`frontend/i18next-parser.config.js`（`createOldCatalogs:false` +
`keepRemoved:true` + `pluralSeparator:false`；pluralSeparator 關掉是因為本專案
用 `{{count}}` interpolation 而非 `_one` / `_other` 變體）。

Check 腳本：`frontend/scripts/i18n-extract-check.mjs` — 獨立 Node 腳本，不用
`--fail-on-update` 是為了避免 parser 在 fail 前先寫入 source JSON。

### 4.3 加新 key 的標準流程

1. 工程師在 code 寫 `t('foo.bar')`
2. 本機跑 `npm run i18n:extract:check` → FAIL，列出 `foo.bar` 缺 key
3. 手動在 `frontend/src/i18n/locales/zh-TW/<ns>.json` 加：
   ```json
   "foo": { "bar": "我的中文翻譯" }
   ```
4. 再跑一次 `npm run i18n:extract:check` → PASS
5. 提 PR；`.github/workflows/i18n_staleness.yml` 會跑兩個 job：
   - `extract-keys-check`：parser 再 diff 一次，確定 zh-TW 齊全
   - `translation-coverage`：`check_translations.py` 檢查其他 locale 覆蓋率
6. 其他 locale（en-US / ja-JP / ko-KR / vi-VN）缺 key 由 translator 側在後續 PR 補上

### 4.4 已知的 Dynamic key（parser 會出 warning）

`i18next-parser` 對非字串字面量 key 會印 `Key is not a string literal` warning。
這類 dynamic key 在本專案是刻意設計，不會被視為錯誤：

- `frontend/src/components/medical/SOAPCard.tsx`：`t(\`fieldLabels.${key}\`)`、
  `t(\`objective.vitalSigns.labels.${key}\`)`、`t(\`section.${section}.title\`)` 等
- `frontend/src/screens/patient/SelectComplaintPage.tsx`：`t(\`selectComplaint.categories.${key}\`)`
- `frontend/src/screens/patient/MedicalInfoPage.tsx`：`t(\`medicalInfo.frequency.${k}\`)` 等
- `frontend/src/components/medical/TranscriptPanel.tsx`：`t(\`transcript.roles.${role}\`)`
- `frontend/src/components/common/LanguageSwitcher.tsx`：`t(\`language.names.${lng}\`)`
- `frontend/src/services/ws/useWsMessageRenderer.ts`：`t(payload.code, ...)` —
  ws namespace 整包走 runtime code，parser 無法靜態分析

這些 key 的「具體 static 子集」要手動維護在對應 JSON 裡；`keepRemoved:true`
保證 parser 不會把這些手動維護的 key 誤刪。
