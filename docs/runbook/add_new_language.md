# Runbook: 新增語言 (Add a new locale)

> 目的：把一個全新的 locale（例如 `th-TH`、`id-ID`、`es-ES`）從零推進 UroSense，走完 enum、config、翻譯、字體、LLM prompt、紅旗 triggers、觀測、canary rollout、clinical sign-off，直到可升為 `status=active`。
>
> 適用範圍：Phase A9 之後，i18n 骨架已完成（zh-TW / en-US active；ja-JP / ko-KR / vi-VN beta）的 UroSense repo。
>
> 相關 runbook：
> - Canary rollout 流程：[`docs/runbook/i18n_rollout.md`](./i18n_rollout.md)
> - 紅旗 coverage 監控：[`docs/observability/red_flag_coverage_alert.md`](../observability/red_flag_coverage_alert.md)
> - Sentry 語系 alert：[`docs/observability/sentry_lang_alerting.md`](../observability/sentry_lang_alerting.md)
>
> 預計時程：從 PR 開啟到 `status=active` ≈ 4–8 週（臨床 sign-off 是瓶頸，非工程）。

---

## 前置確認（Pre-flight）

在開 PR 之前先把以下答案寫進 ticket 描述，否則不要動 code。

- [ ] **臨床合作**：該語言是否有至少一位持證泌尿科主治醫師可做 clinical sign-off（SOAP 用詞、紅旗 keyword、urgency 等級翻譯）？
  - 沒有就停——光翻譯不 sign-off，上線會踩醫療建議責任。
- [ ] **律師 / Legal**：consent form、免責聲明、PDPA/GDPR 條款的該語言版本是否有律師簽名？
- [ ] **Whisper 支援**：該 locale 的 base language code 是否在 OpenAI Whisper 支援列表？（<https://platform.openai.com/docs/guides/speech-to-text/supported-languages>）
  - Whisper 只吃 ISO-639-1（兩位碼，`zh`, `en`, `ja`, `ko`, `vi`, `th`, `id`, `es`, `pt`…），不吃 region variant。
  - Region variant（`zh-HK`, `pt-BR`）若 recall 不夠，要 fallback 到不帶 region 的 base code。
- [ ] **TTS 聲線**：OpenAI TTS 的 `nova` / `shimmer` / `alloy` 是多語通用的，先挑一個做 smoke；如該語言需要本地聲線再換。
- [ ] **書寫系統 / 字體**：該 locale 屬於 Latin / CJK / Arabic / Devanagari / Thai / …？需要額外 `@font-face` 與 `unicode-range`。
- [ ] **RTL**：是否右到左（Arabic、Hebrew）？若是，前端 layout 需額外處理 `dir="rtl"`（本 runbook 不涵蓋 RTL 細節，需另開 ticket）。
- [ ] **目標使用者 / 診所**：新 locale 的第一批 beta clinic 在哪裡？canary stage 2 需要。
- [ ] **新 locale code**：採用 BCP 47 `<lang>-<REGION>`，例如 `th-TH`、`es-ES`、`pt-BR`。以下稱 `<CODE>`（enum 大寫底線）與 `<code>`（lowercase hyphen）。

全部打勾再繼續。

---

## Step 1 — Enum + Config（後端 & 前端同步）

後端與前端都要認得這個 locale，否則 API 會拒收、前端路由會被 normalize 掉。

- [ ] 後端 enum：`backend/app/models/enums.py` 的 `SupportedLanguage` 加上 `<CODE> = "<code>"`，並確認 enum 值跟 DB `supported_language` 型別 migration 一致。
- [ ] 後端 `LANGUAGE_MAP`：`backend/app/core/config.py` 的 `LANGUAGE_MAP[<code>]` 新增條目，至少包含：
  - `whisper`：ISO-639-1 2 位碼（`th`、`id`、`es`…）
  - `tts_voice`：先填 `"nova"` 或 `"shimmer"`
  - `display`：英文顯示名（e.g. `"Thai"`）
  - `native`：母語顯示名（e.g. `"ไทย"`）
  - `status`：**先設 `"beta"`**，等全部 sign-off 後才改 `"active"`
- [ ] 確認 `LANGUAGE_MAP` dict 的 key 全小寫 hyphen（`th-th` 不是 `th-TH`），resolve_language util 是照此正規化比對的。
- [ ] 前端 `frontend/src/i18n/index.ts`：
  - `SUPPORTED_LANGUAGES` 陣列加 `<code>`
  - `BETA_LANGUAGES` 加 `<code>`（beta 階段要顯示 beta badge）
  - `resources` 掛 8 個 ns（見 Step 2）
- [ ] 前端 `frontend/src/components/common/LanguageSwitcher.tsx` 的 `SHORT_LABELS` 補 `<code>`（通常是 2–3 字縮寫，如 `TH`、`ID`、`ES`）。
- [ ] 前端 `frontend/src/i18n/paths.ts` 的 `normalizeLanguage` 加 `<code>` 分支，並處理 region fallback（`th` → `th-TH`、`pt-BR` → `pt-BR`、`pt` → `pt-BR`）。
- [ ] 前端路由 `frontend/src/navigation/RootNavigator.tsx` + `components/layout/LanguageLayout.tsx`：確認 `<lng>` path param 可接受新 code（通常 `SUPPORTED_LANGUAGES` 驅動，但檢查一次）。
- [ ] 跑一次 `cd frontend && npm run type-check`，enum / literal union type 應該逼你把其他 switch-case 也補齊（若沒有，代表類型覆蓋不足，另開 ticket）。

**Smoke**：`curl -H "Accept-Language: <code>" $BACKEND/api/v1/healthz` 應該回 200，且 response 不帶 `X-Fallback-Language` header。

---

## Step 2 — Locale JSON 骨架（8 ns）

把 zh-TW 當 base 全複製，讓翻譯負責人逐檔改。**不要直接送英文給翻譯**——中文是本專案醫療語境的 source of truth。

目前 `frontend/src/i18n/locales/zh-TW/` 有 3 個 ns（`common.json` / `conversation.json` / `ws.json`），A4 拆分後預計會長到 8 個：`common`、`conversation`、`ws`、`patient`、`doctor`、`medical`、`errors`、`status`。

- [ ] `mkdir -p frontend/src/i18n/locales/<code>/`
- [ ] 複製所有 ns：
  ```bash
  cp frontend/src/i18n/locales/zh-TW/*.json frontend/src/i18n/locales/<code>/
  ```
- [ ] 在 `frontend/src/i18n/index.ts` 的 `resources` 區把 8 個 ns 都 import 進來（若 A4 尚未 land，先掛現有 ns，A4 時一次補）。
- [ ] 交付翻譯：附上 glossary（泌尿科術語中英對照）、screenshot（至少 5 張：患者 onboarding、對話中、SOAP 結果、紅旗警示、醫師 dashboard）、tone guide（formal / honorific / patient-facing vs doctor-facing）。
- [ ] 翻譯回稿後，跑 `npm run i18n:lint`（若有）或手動 grep 檢查：
  - 所有 zh-TW key 都在 `<code>` 檔出現（沒有漏 key）
  - JSON parse OK、沒有中途斷掉的 `{{variable}}`
  - Interpolation 變數名沒被翻譯（`{{patientName}}` 不能變 `{{病人姓名}}`）
- [ ] 把翻譯稿進 code review，由懂該語言的團隊成員 + 臨床人員雙簽。

---

## Step 3 — 字體 / CSS

只加字沒加字體，畫面會 fallback 成系統預設，看起來會很醜或出現 tofu（□）。

- [ ] 在 `frontend/src/styles/fonts.css`（或同等位置）新增 `@font-face`：
  ```css
  @font-face {
    font-family: "UroSenseBody";
    src: url("/fonts/NotoSansThai-Regular.woff2") format("woff2");
    unicode-range: U+0E00-0E7F; /* Thai */
    font-display: swap;
  }
  ```
- [ ] **務必切 `unicode-range`**，否則瀏覽器會每次 render 都下載所有腳本的字體（單次首屏從 120KB 漲到 1.5MB+）。
- [ ] 字體授權：Google Noto 系列 OFL / Apache 2.0 可商用；其他字體要確認授權並把 license 放 `frontend/public/fonts/LICENSE.txt`。
- [ ] CJK（中日韓）字體即使 Regular 也常 2–4MB，要 subset：只保留 A1（常用字）+ 標點，其他走 system fallback。
- [ ] 在 Playwright 測試中加一張 visual regression screenshot，確認該 locale 首頁沒有 tofu。

---

## Step 4 — LLM Prompts（by locale）

UroSense 的 SOAP / red-flag / supervisor prompt 都是 locale-specific，不能靠 LLM 自己 detect。

- [ ] `cp -r backend/app/pipelines/prompts/en-US backend/app/pipelines/prompts/<code>`
- [ ] 逐檔翻譯 / 改寫（不是直譯，是 localize）：
  - `soap_prompt.txt`（或同等）：SOAP 四段結構、urgency 等級用詞、醫療格式
  - `red_flag_prompt.txt`：紅旗語意規則、keyword list
  - `supervisor_prompt.txt`：supervisor agent 的判斷標準
  - 其他如 `followup_question_prompt.txt` 等
- [ ] `backend/app/pipelines/prompts/shared.py` 的共用 template 若有語言分支，補 `<code>` case。
- [ ] **雙語臨床覆核**：由懂該語言 + 懂英文的 urologist 對照 en-US 版本審 prompt，確認臨床語意一致；簽名放 `docs/sign_offs/prompts_<code>_v1.pdf`（見 Step 12）。
- [ ] 用 offline eval set（backend/tests/fixtures/eval_<code>/）跑 SOAP quality 回歸，至少 10 個 case 過 80 分。

---

## Step 5 — 紅旗 triggers（臨床 sign-off required）

`backend/app/pipelines/red_flag_detector.py` 的 `URO_RED_FLAGS` 每條規則有 `display_title_by_lang` 與 `triggers_by_lang` 兩個 dict，**每一筆都要補 `<code>` key**，不然 detector 在該 locale 會整條 silently skip。

- [ ] 對 `URO_RED_FLAGS` 每個 entry 補：
  - `display_title_by_lang[<code>]`：前端顯示用的警示標題
  - `triggers_by_lang[<code>]`：keyword list（list[str]），會做 substring match
- [ ] **Keyword list 必須由當地 urologist sign-off**：
  - 包含該語言的口語 + 書面說法（例："血尿" vs "尿裡有血" vs "pee blood" vs "血が混じる"）
  - 含常見俗稱、縮寫、誤拼
  - 不含過度寬鬆的詞（"pain" 單獨不行，會每條都中）
- [ ] 跑 `backend/tests/pipelines/test_red_flag_detector.py`，為新 locale 加至少 3 個 positive case + 3 個 negative case。
- [ ] 檢查 Prometheus metric `urosense_red_flag_triggers_total{language="<code>"}` 在 staging 有值（需先跑幾次對話）。
- [ ] **Coverage alert**：引用 [`docs/observability/red_flag_coverage_alert.md`](../observability/red_flag_coverage_alert.md)，確認新 locale 有被 alert rule 覆蓋到，否則漏紅旗不會被通知。

---

## Step 6 — SOAP urgency 4 字串（臨床 sign-off required）

`backend/app/utils/i18n_messages.py` 的 `MESSAGES` dict 下有 4 個 urgency key，這 4 字會直接出現在醫師 dashboard 的卡片上，措辭錯了會影響臨床判斷。

- [ ] 補齊：
  - `soap.urgency.er_now`：立即就醫（例："Go to ER now" / "ทันที ไปโรงพยาบาล"）
  - `soap.urgency.24h`：24 小時內
  - `soap.urgency.this_week`：本週內
  - `soap.urgency.routine`：常規追蹤
- [ ] 臨床人員（Step 0 講好的那位 urologist）對這 4 字 sign-off，簽名併入 `docs/sign_offs/urgency_<code>_v1.pdf`。
- [ ] 在 `backend/tests/utils/test_i18n_messages.py` 加 assert：`<code>` 的這 4 key 都存在且非空字串。

---

## Step 7 — 資料 seed（`by_lang` JSONB）

Phase A2 把 `chief_complaints`、`medication_catalog` 等字典表的 name / description 從單欄改成 `JSONB` 的 `by_lang` 欄位，`{"zh-TW": "...", "en-US": "...", ...}`。新 locale 若不 backfill，API 會回 `None` 或掉回 default。

- [ ] 在 `backend/alembic/versions/` 開一個新 migration（例如 `xxxx_seed_<code>_by_lang.py`），對以下表做 backfill：
  - `chief_complaints.name_by_lang` / `.description_by_lang`
  - `medication_catalog.name_by_lang`
  - 其他使用 `by_lang` 模式的表（`grep -rn "by_lang" backend/app/models/` 確認全找到）
- [ ] Backfill 內容由臨床人員提供對照表（至少 chief complaints top 50 + 最常用 drug top 100）。
- [ ] Migration 裡同時 update `multilang_coverage` tracking table（如果有），標記 `<code>` 進度 = `partial` or `complete`。
- [ ] 跑 `alembic upgrade head` 在 staging，驗 `SELECT name_by_lang->>'<code>' FROM chief_complaints LIMIT 10;` 有值。
- [ ] Downgrade 測試：`alembic downgrade -1` 能乾淨回退。

---

## Step 8 — Whisper / TTS smoke

STT / TTS 管道是否對新 locale 真的能跑，在這一步驗。

- [ ] 確認 `LANGUAGE_MAP[<code>].whisper` 是 Whisper 支援的 ISO-639-1（前置確認已做，這裡再確認 code 在 production config 正確）。
- [ ] 對 `backend/app/services/stt_service.py`（或同等）的 Whisper 呼叫處，確認它有把 `language=LANGUAGE_MAP[<code>].whisper` 傳進 OpenAI API（不傳會退化成 autodetect，medical vocab 會更差）。
- [ ] 錄 3 段 15 秒的該語言泌尿科問診音檔（包含常見症狀詞彙），丟 STT 驗 WER < 25%。
- [ ] 對 `backend/app/services/tts_service.py` 的 TTS 呼叫處，送 10 個 SOAP 常用句（含 urgency 4 字）進 TTS，人工聽是否自然、發音對、不走音。
- [ ] 若 `nova` / `shimmer` 發音怪，換 `alloy` / `echo` / `fable` 試，挑最自然的寫回 `LANGUAGE_MAP[<code>].tts_voice`。
- [ ] 把 3 段 STT + 10 段 TTS audio + 評分記錄放 `docs/sign_offs/stt_tts_<code>_smoke.md`。

---

## Step 9 — 觀測 / 監控

新 locale 出問題沒被看見 = 沒上線。

- [ ] **Sentry**：
  - `backend/app/core/sentry.py` 的 `set_language_scope` 是用 enum value，理論上新 locale 自動進，但 **Sentry alert rule** 的 allowlist 要手動加。
  - 到 Sentry UI → Alerts → i18n Error Rate Rule，把 `<code>` 加進 `tags.session.language` filter。
- [ ] **Prometheus / Grafana**：
  - `backend/app/core/metrics.py` 的 label `language` 是動態值，不用改 code。
  - 但 `docs/observability/grafana_i18n_overview.json` 的 panel query（若有 hard-coded locale filter）要更新。
  - 在 Grafana 為 `<code>` 開一個 per-lang panel（複製 en-US 的 panel，把 label filter 改 `<code>`），至少含：SOAP latency p95、STT error rate、red flag trigger rate、session count。
- [ ] **Coverage metric**：`urosense_multilang_coverage{language="<code>"}` 在 Prometheus 有值（取自 Step 7 的 `multilang_coverage` table 或同等）。
- [ ] **Dashboard 連結**：把新 panel 的 URL 加到 ticket，canary rollout 每日監控會用到。

---

## Step 10 — Feature flag / Kill switch

新 locale 即使 code merge 了，還是要能隨時關掉。

- [ ] 確認 production env 的 `MULTILANG_DISABLED_LANGUAGES` **不含** `<code>`（若含，使用者會被擋）。
- [ ] 若想先灰度，在 staging 設：
  ```
  MULTILANG_GLOBAL_ENABLED=True
  MULTILANG_ROLLOUT_PERCENT=10        # 10% 用戶看得到新 locale
  MULTILANG_DISABLED_LANGUAGES=       # 空
  DEFAULT_LANGUAGE=zh-TW
  ```
- [ ] Kill switch 演練：把 `<code>` 加進 `MULTILANG_DISABLED_LANGUAGES`、restart service、驗 `/api/v1/i18n/available` 不回 `<code>`、前端 LanguageSwitcher 不顯示該選項。演練完記得移除。
- [ ] 在 `docs/runbook/i18n_rollout.md` 的 Stage 1 allowlist 加入該 locale 的內部測試人員 user id。

---

## Step 11 — 測試 / Regression

- [ ] **Backend pytest 全綠**：`cd backend && pytest -q`。重點看：
  - `tests/utils/test_resolve_language.py`
  - `tests/utils/test_i18n_messages.py`
  - `tests/pipelines/test_red_flag_detector.py`
  - `tests/api/test_i18n_endpoints.py`
- [ ] **Frontend type-check + lint 全綠**：`cd frontend && npm run type-check && npm run lint`。
- [ ] **Playwright e2e**：訪 `/<code>/onboarding`、`/<code>/conversation`、`/<code>/soap/:id`，驗：
  - 頁面沒有 raw i18next key（`common.continue` 不能裸漏出來）
  - 沒有中文殘留（除 proper noun、疾病學名、藥名）
  - `<html lang>` attribute == `<code>`
  - 截圖 diff 對上 baseline（visual regression）
- [ ] **手動 smoke**：
  - LanguageSwitcher 切過去、刷新、URL 是 `/<code>/...`
  - STT：開麥克風講一句該語言，verbatim 顯示對
  - TTS：讓系統念一段 SOAP 摘要，發音可理解
  - 紅旗：講一句 trigger keyword 句子，驗前端亮紅旗 banner
- [ ] **A11y**：screen reader（VoiceOver）讀 `<html lang="<code>">` 的頁面，口音對。

---

## Step 12 — Clinical / Legal sign-off

這是上線瓶頸，別在 Step 14 才想起來。

- [ ] **TODO-M1 主治醫師 sign-off** 該 locale 的：
  - SOAP prompt 臨床語意（Step 4）
  - 紅旗 keyword list（Step 5）
  - SOAP urgency 4 字串（Step 6）
  - Chief complaint / medication seed（Step 7）
  - 簽名 PDF 放 `docs/sign_offs/clinical_<code>_v1.pdf`
- [ ] **TODO-M4 律師 sign-off** 該 locale 的：
  - Consent form
  - Terms of Service / Privacy Policy
  - 免責聲明（disclaimer）
  - 簽名 PDF 放 `docs/sign_offs/legal_<code>_v1.pdf`
- [ ] PR 描述引用兩份 sign-off 的 PDF 連結，reviewer 才能 approve。

---

## Step 13 — Canary rollout

全部 sign-off 到位後，走正式 4-stage canary。細節看 [`docs/runbook/i18n_rollout.md`](./i18n_rollout.md)，本 runbook 只列對應關係。

- [ ] **Stage 1 — Internal**：`MULTILANG_ROLLOUT_PERCENT=0` + 內部 10 位工程師 / QA 的 `preferred_language=<code>` hard-code。48h 觀察。
- [ ] **Stage 2 — Beta clinic**：`MULTILANG_ROLLOUT_PERCENT=0` + 該 locale 對應的 beta clinic allowlist（前置確認講好的那家）。2 週觀察。
- [ ] **Stage 3 — 10% 全用戶**：`MULTILANG_ROLLOUT_PERCENT=10`。1 週觀察。
- [ ] **Stage 4 — 100%**：`MULTILANG_ROLLOUT_PERCENT=100`。正式全量。
- [ ] 每 stage 的 entry / exit 指標看 `i18n_rollout.md`；任何指標未達門檻，倒回上一 stage 或回到 kill switch。

---

## Step 14 — 升 status=active

所有 sign-off 到位、canary 跑完 Stage 4、連續 2 週無 P0/P1 incident：

- [ ] `backend/app/core/config.py` 的 `LANGUAGE_MAP[<code>].status` 由 `"beta"` 改 `"active"`。
- [ ] `frontend/src/i18n/index.ts` 的 `BETA_LANGUAGES` 陣列移除 `<code>`（beta badge 不再顯示）。
- [ ] PR 描述附：
  - Step 12 的 clinical + legal sign-off PDF 連結
  - Step 13 canary 每 stage 的 exit metric 截圖
  - Grafana 最近 2 週的 per-lang dashboard 截圖
- [ ] Merge、deploy、在 release note / changelog 標註「`<code>` 升為 active」。
- [ ] 更新 `docs/i18n_plan.md` 的 locale 狀態表。

---

## 常見坑（Pitfalls）

寫在這，踩了請回來補。

- **i18next fallbackLng chain 設定錯 → 整頁 raw key**：`frontend/src/i18n/index.ts` 的 `fallbackLng` 必須指到一個真的載入的 locale（通常是 `zh-TW`）。若設了 `<code>` 自己做 fallback，會無限回圈然後整頁顯示 `common.onboarding.title` 這種 key。
- **Whisper region variant recall 掉**：`zh-HK`、`pt-BR`、`es-MX` 這種 region variant，Whisper 表現會比 base `zh` / `pt` / `es` 差。必要時 `LANGUAGE_MAP[<code>].whisper` 只填 base code（兩位）。
- **CJK 字體未切 unicode-range → 重複下載**：Noto Sans CJK 單檔 4MB+。若只放一個 `@font-face` 不切 range，瀏覽器會對每個 render cycle 都重下，首屏 TTFB 爆表。務必按 Unicode block 切（U+4E00–9FFF CJK Unified、U+3040–309F Hiragana、U+AC00–D7AF Hangul、U+0E00–0E7F Thai…）。
- **Alembic by_lang backfill 漏 key → API fallback 洞**：Step 7 migration 若漏了某張表，API 取 `name_by_lang->>'<code>'` 會回 `NULL`，前端顯示 `""` 或整張卡片空白。`grep -rn "by_lang" backend/app/models/` 全找一次，一張都別漏。
- **`<html lang>` 沒跟 i18next.language 同步 → screen reader 用錯口音**：`LanguageLayout.tsx` 應該有一個 `useEffect` 同步 `document.documentElement.lang = i18n.language`。若漏，VoiceOver 會用系統語言口音念泰文，完全不對。
- **Enum 大小寫不一致**：`SupportedLanguage.TH_TH = "th-TH"`（enum value 大寫 region）但 `LANGUAGE_MAP["th-th"]`（dict key 全小寫）會 KeyError。專案慣例是 **enum value 保留大寫 region**、**dict key 全小寫 hyphen**，resolve util 會 `.lower()` 正規化。新增時對照現有 zh-TW / en-US 別寫反。
- **前端 `BETA_LANGUAGES` 忘了加 → beta badge 沒顯示**：使用者以為是 GA 版，臨床投訴會進來。Step 1 一起做。
- **Playwright snapshot 沒更新 → CI 紅**：新 locale 的首頁截圖 baseline 第一次跑一定沒有，記得 `playwright test --update-snapshots` 並 commit 新 baseline。
- **LLM prompt 忘了 locale switch → 全部用 en-US prompt**：`pipelines/supervisor_agent.py` / `soap_agent.py` 載入 prompt 的地方，檢查 `load_prompt(language=<code>)` 真的走到新目錄，別硬編 `en-US`。

---

## PR Checklist Template

開 PR 時把這段複製進描述，reviewer 逐項打勾。

```markdown
## Add locale: `<code>` (<Display Name>)

### Pre-flight
- [ ] Clinical sign-off partner confirmed: <urologist name, license>
- [ ] Legal sign-off partner confirmed: <lawyer name / firm>
- [ ] Whisper ISO-639-1 code verified: `<xx>`
- [ ] First beta clinic confirmed: <clinic name>

### Step 1 — Enum + Config
- [ ] `SupportedLanguage.<CODE>` added
- [ ] `LANGUAGE_MAP[<code>]` added (whisper / tts_voice / display / native / status=beta)
- [ ] Frontend `SUPPORTED_LANGUAGES` + `BETA_LANGUAGES` + `SHORT_LABELS` + `normalizeLanguage` updated
- [ ] `type-check` green

### Step 2 — Locale JSON
- [ ] 8 namespaces created under `frontend/src/i18n/locales/<code>/`
- [ ] Translation reviewed by native speaker
- [ ] No missing keys vs zh-TW baseline
- [ ] Interpolation variables not translated

### Step 3 — Fonts
- [ ] `@font-face` added with `unicode-range`
- [ ] Font license verified + committed

### Step 4 — LLM Prompts
- [ ] `backend/app/pipelines/prompts/<code>/` populated
- [ ] Bilingual clinical review PDF: `docs/sign_offs/prompts_<code>_v1.pdf`
- [ ] Offline eval ≥ 80 on 10 cases

### Step 5 — Red flag triggers
- [ ] Every `URO_RED_FLAGS` entry has `display_title_by_lang[<code>]` + `triggers_by_lang[<code>]`
- [ ] Clinical sign-off on keyword list
- [ ] +3 positive / +3 negative test cases

### Step 6 — SOAP urgency
- [ ] `soap.urgency.er_now / 24h / this_week / routine` filled
- [ ] Clinical sign-off PDF: `docs/sign_offs/urgency_<code>_v1.pdf`

### Step 7 — Data seed
- [ ] Alembic migration for `by_lang` backfill
- [ ] `alembic upgrade head` + `downgrade -1` tested
- [ ] `multilang_coverage` updated

### Step 8 — Whisper / TTS
- [ ] STT smoke 3 clips, WER < 25%
- [ ] TTS smoke 10 phrases, voice confirmed
- [ ] Smoke record: `docs/sign_offs/stt_tts_<code>_smoke.md`

### Step 9 — Observability
- [ ] Sentry alert rule allowlist updated
- [ ] Grafana per-lang panel added
- [ ] `urosense_multilang_coverage{language="<code>"}` has value

### Step 10 — Feature flag
- [ ] `MULTILANG_DISABLED_LANGUAGES` does NOT contain `<code>` in prod
- [ ] Kill switch rehearsal done

### Step 11 — Tests
- [ ] Backend pytest green
- [ ] Frontend type-check + lint green
- [ ] Playwright e2e green (incl. new visual baselines)
- [ ] Manual smoke (LanguageSwitcher / STT / TTS / red flag / a11y)

### Step 12 — Sign-offs
- [ ] Clinical: `docs/sign_offs/clinical_<code>_v1.pdf`
- [ ] Legal: `docs/sign_offs/legal_<code>_v1.pdf`

### Step 13 — Canary
- [ ] Stage 1 (Internal) passed
- [ ] Stage 2 (Beta clinic) passed
- [ ] Stage 3 (10%) passed
- [ ] Stage 4 (100%) passed

### Step 14 — Promote to active (separate PR after 2 weeks green)
- [ ] `LANGUAGE_MAP[<code>].status = "active"`
- [ ] Removed from `BETA_LANGUAGES`
- [ ] `docs/i18n_plan.md` updated
- [ ] Release note published
```

---

**維護者**：i18n working group
**最後更新**：2026-04-18（Phase A9）
**對應 runbook**：`i18n_rollout.md`、`red_flag_coverage_alert.md`、`sentry_lang_alerting.md`
