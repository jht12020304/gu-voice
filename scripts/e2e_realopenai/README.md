# 真 OpenAI 本機 E2E 問診測試工具

對 GU_0410 backend 跑「真 OpenAI」文字問診 E2E：病患模擬器（gpt-4o-mini）經
WebSocket 全程用 `text_message` 與 backend 對話，逐輪撈 Redis supervisor_guidance、
結束後撈 DB 斷言。不修改 repo（含 worktree）任何檔案。

受測 backend 可切換：預設原 repo `/Users/chun/Desktop/GU_0410/backend`
（分支 fix/api-audit-remediation @ aa72d38）；§E 驗收時用
`E2E_BACKEND_DIR=<worktree>/backend`（分支 fix/e2e-audit-egroup）。

## 檔案

| 檔案 | 用途 |
|---|---|
| `compose.override.yml` | 疊在 repo docker-compose.yml 上，postgres→55432、redis→56379（本機 5432/6379 被原生服務佔用） |
| `local.env` | uvicorn / alembic / driver 的環境覆寫（本機 DB/Redis、`REDIS_KEY_PREFIX=gu:` 必須） |
| `driver.py` | 主 driver：註冊→建場次→WS 對話→模擬器→guidance 輪詢→DB 斷言→JSON；`reanalyze <scenario>` 離線重算斷言（不重跑、不花額度） |
| `run_scenario.sh` | 一鍵跑單一情境（吃 `E2E_BACKEND_DIR`） |
| `start_backend.sh` | 啟動受測 backend（前景執行；吃 `E2E_BACKEND_DIR`，venv 共用主 repo） |
| `results/*.json` | 逐字稿 + 事件 + guidance timeline（附時間戳）+ DB 快照（含 SOAP 全文 S/O/A/P/summary/icd10）+ 斷言結果 |
| `uvicorn.log` | backend 日誌 |

## 啟動基礎設施

```bash
E2E=/private/tmp/claude-501/-Users-chun-Desktop-GU-0410/1337bb7a-da86-4a4c-b956-6e2350c1f83f/scratchpad/e2e

# 1. docker postgres + redis（project 名 gu_0410，沿用既有 volume）
docker compose -p gu_0410 \
  -f /Users/chun/Desktop/GU_0410/docker-compose.yml \
  -f $E2E/compose.override.yml up -d postgres redis

# 2. migrate（local.env 讓 alembic env.py 不啟用 Supabase SSL）
#    §E 驗收時 cd 到 worktree 的 backend（新 migration 才會套上），venv 共用主 repo：
cd /Users/chun/Desktop/GU_0410/backend        # 或 <worktree>/backend
set -a; source $E2E/local.env; set +a
/Users/chun/Desktop/GU_0410/backend/venv/bin/alembic upgrade head

# 3. 起受測 backend（背景跑）
nohup $E2E/start_backend.sh > $E2E/uvicorn.log 2>&1 &                     # 原 repo
# E2E_BACKEND_DIR=<worktree>/backend nohup $E2E/start_backend.sh > $E2E/uvicorn.log 2>&1 &  # §E worktree
curl -s http://127.0.0.1:8000/api/v1/healthz/deep   # 應回 {"status":"ok",...}

# 4. 起 celery worker（2026-07-19 起必要：SOAP 生成走 Celery 單一路徑，
#    沒起 worker 的話報告會停在 GENERATING、SOAP 斷言必失敗）
cd /Users/chun/Desktop/GU_0410/backend   # 或 <worktree>/backend
nohup venv/bin/celery -A app.tasks worker --loglevel=info --concurrency=1 \
  > $E2E/celery_worker.log 2>&1 &
```

## 跑情境

```bash
$E2E/run_scenario.sh dontknow_zh          # 已跑：驗收 #2「不知道不再換句話重問」（40c2f42）
$E2E/run_scenario.sh hematuria_coop_en    # 已跑：D1 基線（對照組，勿覆蓋 results JSON）

# §E 修復後驗收（等通知才跑；跑之前先用 worktree 起 backend）：
export E2E_BACKEND_DIR=<worktree>/backend
$E2E/run_scenario.sh torsion_critical_zh
$E2E/run_scenario.sh hematuria_coop_en_fixed
$E2E/run_scenario.sh ed_zh

# 2026-07-27 第三輪新增（尚未真跑；先跑不花錢的 preflight + ruleprobe 再決定要不要燒額度）：
$E2E/run_scenario.sh torsion_wordorder_zh   # 同臨床情境、真人語序（時間詞插中間）
$E2E/run_scenario.sh torsion_critical_en    # 第一個非 zh-TW 的紅旗 gating 情境
```

離線、不花額度的檢查（改完 triggers／守衛先跑這個）：

```bash
cd /Users/chun/Desktop/GU_0410/backend
venv/bin/python ../scripts/e2e_realopenai/driver.py preflight <scenario>  # 燒額度前的體檢
venv/bin/python ../scripts/e2e_realopenai/driver.py ruleprobe
venv/bin/python ../scripts/e2e_realopenai/driver.py reanalyze <scenario>
```

### `driver.py preflight <scenario>`（2026-07-27 第四輪新增）

跑一場之前的離線體檢，**不連 WS、不花額度、不碰受測伺服器狀態**。專治
「宣告了情境但從沒真跑過，跑下去才發現一定紅」。查：

| 檢查 | 紅了會怎樣 |
|---|---|
| `ANALYZERS` / `SCENARIO_RED_FLAG_SPEC` 有沒有登記這場 | main 直接 KeyError／紅旗期待未宣告 |
| `chief_complaint_id` 在不在 DB 且 `is_active` | 建場次就 4xx，整場白跑 |
| 這場語言有沒有 `ws.session_terminated_aborted_notice*` 模板 | 純診斷（2026-08-20 起 `t5` 只有在**真的收到** post-abort 文字時才需要模板；見下方「t5 判準改版」） |
| persona 硬性規定的第一句，規則層**現在**會不會命中 | `t9`（規則層 fallback 必須命中）一定 FAIL |
| `backend/.env` 的 `OPENAI_API_KEY` | 跑到一半才死 |
| `server_provenance`（診斷，不 blocking） | 白箱斷言的證據力 |

那句「persona 第一句」存在情境的 `expected_first_patient_line`，**只給 preflight 用、
不參與任何 pass/fail 判定**（它是 persona 硬性規則的逐字複本，不是斷言）。
exit code：0 綠 / 1 有 blocking / 2 情境名不存在。
⚠️ preflight 全綠**不代表這場會 PASS**，只代表「跑得起來、且沒有已知的結構性必紅」。

結果寫到 `results/{scenario}.json`。每情境會註冊一個新病患帳號
（register rate limit 5/hour/IP，短時間重跑多次會 429）。

## 斷言狀態：pass / fail / not_applicable / precondition_not_met / stale

每條斷言都是 `{"status": ..., "pass": bool|None, ...}`，在 `analysis.result_summary`
分五類列出，`analysis.overall_status` 為 `PASS` / `FAIL` / `INCOMPLETE`。

| status | 意思 | 算 pass？ | 影響 overall？ |
|---|---|---|---|
| `pass` | 驗到且通過 | ✅ | — |
| `fail` | 驗到且不通過 | ❌ | `FAIL` |
| `not_applicable` | **本情境依設計就不適用** | ❌（也不算 fail） | **不影響** |
| `precondition_not_met` | **前提意外沒觸發＝沒驗到，要人看** | ❌ | `INCOMPLETE` |
| `stale` | **這條依賴當前產品碼的行為，但現在證明不了** | ❌ | `INCOMPLETE` |

`overall_pass` 需同時 0 fail、0 `precondition_not_met`、0 `stale`。舊結果檔裡的
`skipped` 一律當 `precondition_not_met` 讀。

**`stale` 是 2026-07-27 第三輪加的（`reanalyze` 對產品碼 revert 結構性失明）：**
覆核實測——把 `shared.py` 整份 revert 回 HEAD 後跑 `reanalyze torsion_critical_zh`，
規則層斷言 `t9` **仍然 PASS**，因為 `reanalyze` 只讀結果檔裡已經記錄的 DB 狀態，
不會重新跑偵測。結果檔記的是「跑那場當下那份碼的行為」，拿它當「現在這份碼的行為」
的證據就是失明。現在 `reanalyze` 會**離線重跑規則層**（見下一節）；重跑不到時標
`stale`，不得靜靜 pass。

**第四輪（2026-07-27）把同一條原則補到白箱探針那一側。** `reanalyze` 現在對
「依賴當前產品碼行為」的斷言一律要重跑才可以維持 pass：

| 斷言族 | reanalyze 時怎麼重新證明 | 重跑不到 |
|---|---|---|
| 規則層 gate `t9` / 語料 `t10` | `_replay_rule_layer_over_transcript`（import 磁碟上的 detector 重跑逐字稿） | `stale` |
| 白箱探針 `i1`–`i4` | `_replay_intake_probe`（用磁碟碼重組 system prompt / supervisor 背景字串，再與結果檔比對） | `stale` |

`i1`–`i4` 的比對規則與規則層那套對稱：紀錄與重跑**不一致 → `fail`**（產品碼相對於
這份結果檔已變，或結果檔已過期），一致才照常 pass/fail。真跑當下沒有 replay 欄位，
行為完全不變。實測反向驗證：把重跑出來的 `patient_section` 換成不含年齡／intake 病史的
版本 → `i1`/`i3`/`i4` 由 `pass` 變 `fail`；模擬 session 列被清庫 → 三條變 `stale`。

⚠️ **這條原則的邊界（別誤以為 reanalyze 什麼都能重驗）：** 措辭鐵律
（`_patient_facing_wording_check`）掃的是結果檔裡**已經被後端消毒過**的輸出，
判準本身在 driver 這邊。所以它能證明「這場的病患端文字合規」，**不能**證明
「後端的消毒層現在還在」——後者由 `backend/tests/unit/pipelines/test_soap_patient_facing_wording.py`
守。把消毒層 revert 掉再 `reanalyze` 仍會綠，那不是破口，是兩層分工。

**為什麼要拆（2026-07-27 第二輪對抗式覆核）：** 原本只有一種 `skipped`，把
「cooperative persona 結構上不可能有 `red_flag_alert`」（`ed_3b_zh` 的 `r7`）與
「AI 全場沒問過病史所以拒答規則沒觸發」（`dontknow_zh` 的 `a3`）混為一談。
前者永遠 skipped → **那場結構上不可能得到 PASS** → 長期會訓練覆核者忽略
INCOMPLETE，等於把整個 INCOMPLETE 訊號廢掉。

新增斷言時的判準：**只有「這條在這個情境不可能觸發、而且那不是缺陷」才可以用
`_na()`；其他一律 `_pnm()`。** 不確定就用 `_pnm()`（讓人看，不要靜靜放行）。

**第四輪把 `dontknow_zh` 的 `a3` 重新分類（不是放寬斷言，是把前提分類正確）。**
`a3_no_history_reask_after_dontknow` 的前提是「AI 先問過病史 → 病患拒答」。實測那場
AI 全程沒問過去病史 → 前提沒觸發 → 整場永遠 INCOMPLETE。但**過去病史根本不是必問
欄位**：`llm_conversation.py:786-793` 把它放在「## 次要補問（HPI 完整度較高後才進入）」
並明文「請視對話狀況補問…且只在與主訴相關時才問」，driver 自己的
`FIELD_HPI_IDS["history"]` 也是空 tuple。AI 沒問它是**合規行為**，記成「要人看的
未驗到」會訓練覆核者忽略 INCOMPLETE。現在 `_reask_check()` 三分：

| 情況 | status |
|---|---|
| AI 從未問過該欄 **且** 該欄是次要補問（`history`） | `not_applicable`（不影響 overall） |
| AI 從未問過該欄 **且** 該欄是 HPI 十欄必問（`onset` / `duration`） | `precondition_not_met`（AI 漏問必問欄，要人看） |
| AI 問過但病患沒說「不知道」 | `precondition_not_met`（persona 沒遵守硬性規則，要人看） |
| AI 問過、病患拒答、AI 又重問（含換句話） | **`fail`（判準完全沒動）** |

第二段是**新增的**嚴格度：舊碼把「AI 漏問必問 HPI 欄」和「AI 合規地沒問選配欄」
混成同一句話，看不出差別。

## 受測碼的 provenance（結果檔怎麼證明「跑的是哪一版碼」）

結果檔頂層三個欄位一起看才有意義：

- `backend_head` — committed HEAD。**單看它會誤導**：修復期的碼全在工作區未 commit，
  只讀 head 的覆核者會看到「修復前的 commit」而結論「修復根本沒在跑」。
- `backend_git` — `{dirty, dirty_file_count, backend_dirty, dirty_files[]}`。
  `dirty=true` 代表受測碼是工作區版本、`head` 只是它的 base commit。
- `server_provenance` — **受測 uvicorn 進程是不是當前磁碟碼**：
  比對「**受測**進程的啟動時間」與「`backend/app/**/*.py` 的最新 mtime」。
  `verified=true` ＝ 進程啟動晚於所有原始碼異動 → 伺服器必然載入當前磁碟碼；
  `false` ＝ 有原始碼比進程新（伺服器可能是舊碼，`sources_newer_than_server`
  會列出是哪幾個檔）；`null` ＝ 歸屬不到受測進程／非本機 → **降級為診斷，不 FAIL**。

  ⚠️ **「受測進程」的判準（第四輪修的 bug）：** 只看指令列指向 `BACKEND_DIR` 或
  `app.main` 的那個 listener（`cmd_points_at_backend_dir`），**不是 port 上的所有
  listener**。舊碼要求 `:8000` 上每一個 listener 都比原始碼新，而本機同時有別的
  專案的 Docker port-forwarder（`com.docker.backend services --autostart`，開機就在跑）
  綁著同一個 port → 它永遠比原始碼舊 → `verified` 恆為 `false` →
  `intake_wiring_zh` 的 `i0` **永遠 FAIL**。方向最壞：害人去追一個不存在的
  「伺服器跑舊碼」問題。歸屬到的 listener 記在 `attribution.owned_pids`，
  被忽略的記在 `attribution.foreign_pids_ignored`（列出來，只是不參與判斷）。

  分析端一律用 `_provenance_verdict()` **重算** verdict（只吃紀錄裡已存的
  `listeners` 明細，不重新量測伺服器），所以舊結果檔也會拿到修正後的判定。
  重算規則只會變嚴或變準：歸屬不到時回 `None`（比舊版「拿全部 listener 一起判」
  更保守——舊版在「只有一個外來 listener 且它剛好夠新」時會回 `true`，那是假背書）。

**為什麼非有不可：** 白箱探針（`probe_intake_wiring`）是在 **driver 自己的進程**裡
`sys.path.insert` 後 import **磁碟上的模組**重新計算 prompt，跟 :8000 那個 uvicorn
進程載入的碼**沒有任何綁定**。伺服器跑舊碼時，探針照樣用新碼算出漂亮結果 →
`i1`–`i4` 全綠卻零證據力。`i0_probe_server_code_provenance` 就是這道證明：
`verified=false` → FAIL；`verified=null`（歸屬不到受測進程）或沒有 run-time 紀錄
（舊結果檔）→ `precondition_not_met`（要人看，但**不是** FAIL），
且 `i1`–`i4` 各自帶 `server_code_provenance: "已驗證伺服器為當前磁碟碼" / "伺服器可能載入舊碼" / "無法驗證"`。

`reanalyze` **只認跑那一場當下記下的** `server_provenance`；reanalyze 當下量到的
伺服器狀態另記在 `reanalysis_context.server_provenance_now`，純資訊、不參與判定。

## 規則層離線重跑與措辭變體語料（`driver.py ruleprobe`）

```bash
cd /Users/chun/Desktop/GU_0410/backend
venv/bin/python ../scripts/e2e_realopenai/driver.py ruleprobe   # exit 1 ＝有 under/over trigger
```

**不連 WS、不花 OpenAI 額度、不碰受測伺服器。** 改動 `shared.py` 的 triggers 或
`red_flag_detector` 的否定／語境守衛之後**先跑這個**，再決定要不要燒額度跑整場情境。

### 為什麼要有這兩樣（本輪最深的一個假象）

`torsion_critical_zh` 的 persona 第一句是「大約兩小時前左邊睪丸突然劇烈疼痛…」，
剛好讓關鍵字 `睪丸突然` **相鄰**命中 → DB 實證 `trigger_keywords={睪丸突然}` →
規則層斷言 `t9` 全綠。但真人語序常把時間詞插在部位與修飾詞中間
（「睪丸兩個鐘頭前突然劇痛」），2026-07-27 實測 4/5 語言**完全不命中**。
**驗收套件證明的是「這句台詞會命中」，不是「這個臨床情境會命中」——台詞與實作
互相配適，測的是實作而不是行為。**

### 兩個機制

1. **離線重跑（`_replay_rule_layer*`）**：在 driver 進程裡 import **磁碟上的**
   `red_flag_detector`，用它自己的 `_keyword_present_non_negated` /
   `_prose_lookback_for_severity` / `_get_fallback_rules` 對逐字稿裡**每一則病患
   原話**重跑關鍵字比對（伺服器就是逐輪 `detect(text, …)`）。
   結果與結果檔記錄的 `confidence=rule_hit` 交叉比對：

   | DB 實證 | 離線重跑 | 判定 |
   |---|---|---|
   | rule_hit | 命中 | `pass` |
   | rule_hit | **不命中** | `fail`（產品碼退化，或結果檔已過期） |
   | 無 rule_hit | 命中 | `fail`（那場真的是語意層獨撐，結果檔比產品碼舊） |
   | 任一 | **重跑不可用** | `stale` |

   「重跑不可用」＝ import 失敗／舊結果檔沒逐字稿／`red_flag_rules` 表有 active 列
   （那代表伺服器吃的是 DB 規則、不是內建 catalogue，離線重跑不對等）。
   ⚠️ 重跑證明的是「**磁碟上的**規則層現在會怎麼判」，不是「跑那場的伺服器怎麼判」
   ——後者由 `server_provenance` 負責。兩者合起來才是完整證據鏈。

2. **措辭變體語料（`RULE_LAYER_WORDING_CORPUS`）**：同一個臨床情境（急性發作＋
   劇痛＋睪丸/陰囊）的**不同語序、五種語言**都必須命中；措辭相近但臨床良性的句子
   都**不可**命中。語料是**雙向且對稱**的：

   - `must_hit`：時間詞插在部位與修飾詞之間、書面語、無標點 STT、
     以及本批 triggers 修復**已經涵蓋**的語序（讓語料對 revert 也敏感）
   - `must_miss`：慢性輕微不適、複誦主訴標籤（`睪丸疼痛` / `testicular pain` /
     `睾丸痛` / `고환 통증` / `đau tinh hoàn`）、行政詢問（掛哪一科）、
     時態否定（以前有、已痊癒）、後置否認、詞尾同形（eyeball / ball hurt）

   **政策鎖（2026-07-27 第四輪）：** 使用者已拍板「規則層**偏誤報**——寧可多中止
   幾場；第三人稱轉述、別部位誤配這類殘餘誤報就留著，誤中止的代價是病患白等、
   護理師走一趟，可逆」。所以語料裡有四條刻意的 `expect=hit`：

   | id | 文字 | 為什麼是 `hit` |
   |---|---|---|
   | `zh_third_person_policy_accepted_fp` | 我朋友之前睪丸突然劇痛 | 臨床上是誤報，**政策接受**；寫成正向斷言是為了讓「有人加抑制守衛擋掉它」立刻變紅 |
   | `ja_third_person_policy_accepted_fp` | 家族が睾丸の激痛で運ばれた | 同上 |
   | `ko_other_site_policy_accepted_fp` | 고환은 괜찮은데 …배가 심하게 아파요 | 別部位誤配；要擋它得做分句層級部位×程度綁定，那是最容易誤殺真陽性的改法 |
   | `zh_bujiu_onset_narrative` | 今天早上開始痛，沒多久睪丸就腫起來痛到吐 | **真漏報**（曾被裸「沒」當否定整句抹掉），政策不允許 |

   ⚠️ 要改這四條的期待值需要新的臨床拍板，不是實作層可以自行決定的取捨。
   **每一條抑制守衛都是潛在漏報**：新增抑制前先讓這四條保持綠，說不出「為什麼
   這條抑制不會造成漏報」就不要加。

   語料**刻意不抄 persona 台詞**——台詞與關鍵字互相配適正是這條要防的東西。
   掛在 `torsion_*` 情境的 `t10_rule_layer_wording_variants`，`reanalyze` 也會跑。

   `must_miss` 命中**任何** critical（不限 `testicular_pain_severe`）都算誤觸，
   因為那一樣會第 1 輪 `aborted_red_flag`、讓病患白跑一趟。

## 斷言強度守則（別再寫出恆真斷言）

這份工具跑一次要燒真 OpenAI 額度，恆真斷言比沒有斷言更糟——它會給出「驗過了」的
假象。以下是已經踩過的坑，新增斷言前先對一遍：

1. **「DB 有 row」≠「東西生成好了」。** 場次結束當下 backend 就會 INSERT 一列
   `soap_reports.status=GENERATING`、S/O/A/P 全空的**佔位列**，Celery 之後才回填。
   舊版 `fetch_db_state` 一抓到 row 就 break → 永遠拍到空殼快照，
   `soap_report is not None` 系列斷言全打在空殼上，**「SOAP 全卡 GENERATING」這種
   生產真的出過的事故在 e2e 上恆 pass**。
   現在改為輪詢等 `status IN ('generated','failed')` 或逾時，逾時就如實記錄
   （`db_state.soap_poll.timed_out=true`、`final_status='generating'`）並讓斷言 FAIL。
   SOAP 一律用 `_soap_generated_check()`：status='generated' + `generated_at` 非空 +
   S/O/A/P 內容非空，三者齊備才算數。
2. **有 DB `server_default` 的欄位不能單獨比對。** `soap_reports.language` 的
   server_default 就是 `'zh-TW'`，只斷 `language == 'zh-TW'` 的話 generator 完全沒寫
   也會過。要和「真的生成了」的實證綁在一起。
   （※ `SOAP_REPORT_LANGUAGE` 固定 zh-TW 是 2026-07-19 的產品決策，
   `report_queue.py:4` 有註解 → **「en-US 場次的 SOAP 是中文」是預期行為，不是 bug**。）
3. **結構上不可能失敗的比較要拿掉或標 N/A。** `FIELD_HPI_IDS["history"]` 是空 tuple
   （過去病史不在 HPI 十欄內），`any(m in ())` 永遠 False；混在 missing_hpi 檢查裡
   等於白佔一條。現在只檢查「有 HPI 欄位 id 且病患真的拒答過」的欄位，其餘列進
   `not_applicable_fields` / `skipped`。
4. **對 n=1 的集合做一致性檢查是恆真的。** `len(set(notice_texts)) == 1` 在只收到
   一則提示時必定成立（而 server 規格就是「回一次提示後關 WS」）。改成拿實收文字
   比對 backend i18n 模板字面量（`ast` 讀 `MESSAGES`，不 import backend、不需 settings）。
5. **關鍵字比對要限縮在「問句」裡，並排除 AI 複述病患用詞。**
   `"family" in ai_text` 連 "Does anyone in your family have diabetes?" 都算「問到泌尿癌
   家族史」；`"smok"` 連 AI 複述病患的 "you smoke" 都中。現在統一走
   `_ai_question_sentences()` + `_asked_in_question()`：只掃**以 `?` / `？` 結尾的句子**，
   命中詞若**全部**出現在前一輪病患原話裡就歸為 `restatement_excluded` 不算發問；
   家族史另要求同句同時出現癌症／泌尿器官詞（`also_any_of`）。
6. **字面比對務必列全異寫，並盡量另加語意層。** intake 重問偵測原本寫
   「阿斯匹靈／抗凝血」，LLM 實際講的是「阿司匹靈／會影響凝血」，一字之差把兩次
   真實重問判成 pass。除了補齊異寫，另加 persona sentinel 偵測
   （`_scan_intake_reask_by_persona`）：病患回「這些我剛剛在表單上都填過了」＝上一則
   AI 確實在重問 intake，這是情境自帶的 ground truth，不吃用詞。
   ⚠️ **但「列全異寫」不等於「可以收裸的泛用詞」**：`medications` 曾收裸子字串
   「藥物」，於是 AI 的假性血尿鑑別問句「最近有沒有吃到容易讓尿變紅的食物或**藥物**？」
   被判成重問 intake（`i5` 假性 FAIL）——那是合法的 HPI 誘因提問。現在泛用詞
   （藥物／用藥／服用／medication…）**必須**與「你目前有沒有在服用」這類語境詞
   （`_CURRENT_MED_USE_FRAMES`）同句才算命中；具名藥物與藥理類別（aspirin／抗凝／
   凝血…）本身就是 intake 內容，維持單詞命中。**gating 本身沒有移除。**
7. **不要把已知失敗降級成註記。** `i5` 原本把 `family_history` 明文排除在 pass 條件外
   （只當診斷輸出），家族史同樣是 intake 已填欄位 → 已納入 pass 條件。
8. **命中詞要確認來源。** `i7` 原本只掃「SOAP 全文有沒有出現 intake 詞」，唯一命中的
   「膀胱癌」其實來自鑑別診斷鏈而非 intake。現在改成直接比對 SOAP `subjective` 的
   `past_medical_history / medications / allergies / family_history` 四個欄位，
   期望值由情境的 `intake` 設定推出（`_intake_expected_soap_fields`，附異寫別名表），
   且「未提供／null」等佔位字樣一律判 fail。
9. **子字串比對的「先躲過黑名單再命中白名單」陷阱。** `i7` 的 allergies 檢查裡
   「無過敏資料」（＝沒記錄）不含 `無資料` 三連字 → 躲過 placeholder 判定，
   接著命中白名單的「無過敏」→ 判 pass。修法：把「無X資料／無X記錄」逐一列進
   `SOAP_NOT_PROVIDED_TERMS`，並讓「明確填無」走 `SOAP_NO_ALLERGY_EXACT` **整格
   精確比對**（`無` / `否` / `沒有` / `nkda`…）。
   `SOAP_NO_ALLERGY_EXACT` 刻意**不收** `none` / `no` / `-`——那三個同時是「欄位被
   序列化成空值」的樣態，收進來會把「沒資料」誤放行成「明確填無過敏」，
   那是往寬的誤傷，比假性 fail 危險。
   （順帶：`patient_context.py:111` 對 `no_known_allergies=True` 寫進 prompt 的就是
   **裸「無」**，SOAP 照抄成 `allergies="無"` 是正確行為；舊清單沒收裸「無」→
   `intake_wiring_zh` 唯一那個 fail 是**假的**。）
10. **重問偵測的 pattern 要去讀 backend prompt 自己列舉的重問形式。**
    `llm_conversation.py:337-343` 的硬性規定明文列出換句話重問長什麼樣：
    「已問過 Onset 卻改問『是突然還是漸進發生的』」「已問過 Duration 卻改問
    『間歇性還是持續性』」。舊 pattern 清單一條都沒收 → 病患拒答 duration 後
    AI 問「這個頻尿是一直都這樣，還是只有某些時候才比較明顯呢？」，
    逐字稿裡白紙黑字的違規，斷言卻報 PASS。
    現在 `FIELD_PARAPHRASE_PAIRS` 收這類**二選一句式**，且**只認同一句同時出現兩端**
    （「一直/持續」×「間歇/偶爾/某些時候」、「突然」×「漸進/逐漸」）——單邊關鍵字
    在正常問診裡另有合法用途（修飾因子、加重因子提問），單邊命中只進
    `paraphrase_single_sided_for_review`，不 gating。
    另有 `weak_signal_questions_for_review`（拒答後仍提到該欄位語彙的問句，
    例如拒答 onset 後問「是最近有什麼事件之後開始的嗎」）——算不算變相重問是
    臨床/產品判斷，driver 不替人做結論，但一定要讓它現形。
11. **白箱探針不會自動證明伺服器在跑同一份碼。** 見「受測碼的 provenance」一節：
    探針在 driver 進程裡 import 磁碟模組重算，與受測 uvicorn 進程無綁定。
    任何白箱斷言都要附 provenance，不然「伺服器是舊碼」時它一樣全綠。
12. **情境台詞不可以與實作互相配適。** `torsion_critical_zh` 的 persona 講
    「睪丸突然劇烈疼痛」剛好讓關鍵字 `睪丸突然` 相鄰命中，於是規則層斷言全綠——
    但真人語序（時間詞插在中間）4/5 語言完全不命中。**新增偵測類斷言時，
    情境台詞與偵測規則必須由不同的人／不同的來源產生**，並另外用
    `RULE_LAYER_WORDING_CORPUS` 這種**與台詞無關**的語料驗同一件事。
13. **偵測邏輯的測試表必須雙向且對稱。** 前兩輪連續踩同一個坑：第一輪只加
    「必須命中」→ 改出 over-trigger；第二輪只加「不該命中」→ 改出 under-trigger。
    `ruleprobe` 的語料同時列 `must_hit` 與 `must_miss`，而且**反例的措辭要與既有
    e2e 台詞不同**，否則就是拿實作去配適測試。
14. **`reanalyze` 只讀結果檔＝對產品碼變動失明。** 任何「依賴當前產品碼行為」的
    斷言，`reanalyze` 時要嘛真的重跑（規則層是純字串運算，離線可行），要嘛標
    `stale`。**不可以拿舊紀錄靜靜回 pass。**
16. **不要把「其中一種合格樣態」寫死成唯一樣態。** `t5` 舊判準要求 abort 後一定要
    收到固定終止提示；EM-1（116282d）之後，critical 由 inline 判定時主迴圈當場
    break、WS 立刻關閉，**收不到任何提示**——同一份碼會依「inline vs 背景 drain
    誰先解析出 critical」而落在兩種樣態，於是同一份碼可以一場紅一場綠。判準要寫
    在**不變的實質**上（這裡是「終止後不得有 LLM 產物」），把各樣態列成合法分支，
    並記在 `post_abort_shape` 這種欄位裡讓覆核者看得見走了哪條。
15. **恆真的「空值即通過」。** `_wrapup_has_no_question` 舊寫法是
    `"?" not in last_ai_text`，最後一則 AI 訊息為空／不存在時**恆真** →
    整場沒有 AI 收尾訊息也照樣綠。凡是「某文字不含 X」型斷言，都要先確認
    那段文字**存在**，不存在時回 `precondition_not_met`。

## 情境與斷言

已跑（2026-07-03，baseline @ aa72d38）：

- **dontknow_zh**（zh-TW、頻尿 c2）：病患對 onset/duration 與過去病史一律「我真的不知道」。
  斷言：(a) 說不知道後 AI 不再問同欄位（逐欄位關鍵字掃描 + 人工判讀）；
  (b) guidance missing_hpi 丟棄已拒答欄位、next_focus 不指向、hpi 能到 80+；
  (c) ≤10 回合自動結束 + SOAP。結果：7/8 PASS（唯一 FAIL 是第一輪無指導時
  conversation LLM 換句話重問 onset 一次）。
- **hematuria_coop_en**（en-US、血尿 c1）：合作病患，第 12 回合後每輪道別。
  D1 主症狀未重現（10 回合硬上限收尾、有 SOAP），但 deferral 機制（第 9 輪道別被
  high alert 擋掉）與 alerts 不冪等（同 title 6 筆）都入鏡 → 為 §E 修復對照基線。

§E 修復後驗收（**先不要跑，等通知**）：

- **torsion_critical_zh**（zh-TW、陰囊腫脹 c7，上限 4 回合）：第一輪即典型睪丸扭轉描述。
  斷言：t1 第 1 輪 `aborted_red_flag`；t2 critical alert 入庫；t3 有 SOAP；
  **t4 `sessions.red_flag=true` 且 `red_flag_reason` 非空（A4；修復前 false/空）**；
  **t5 abort 後零 LLM 產物（判準 2026-08-20 改版，見下節）**、t6 時間戳、t7 中止場次也要有 generated SOAP、
  **t8 病患端措辭鐵律（四類來源）**、**t9 規則層必須命中 `testicular_pain_severe`
  的 critical（`confidence=rule_hit` + `trigger_keywords` 非空 + 離線重跑複驗）**、
  **t10 措辭變體語料雙向通過**。
- **torsion_wordorder_zh**（zh-TW、陰囊腫脹 c7，上限 4 回合，**2026-07-27 新增**）：
  臨床情境與 `torsion_critical_zh` **完全相同**，只有講法不同——把時間片語插在
  「睪丸」與「突然」之間（「我右邊睪丸大概三個鐘頭前突然痛起來」）。
  斷言與 `torsion_critical_zh` 一字不差（共用 `analyze_torsion`）。
  **這場紅、`torsion_critical_zh` 綠 ＝ 規則層只認得那一句台詞的語序，不認得臨床情境。**
- **torsion_critical_en**（en-US、Scrotal swelling c7，上限 4 回合，**2026-07-27 新增**）：
  第一個**非 zh-TW** 的紅旗 gating 情境。en 的 triggers 是完全不同的一組關鍵字
  （`testicle suddenly` / `pain in my testicle` …），端到端從未驗過——原本 7 個情境
  裡只有一場宣告 `rule_layer_gate`，規則層 fallback 的迴歸偵測全押在一場 zh-TW。
  `t5` 的終止提示比對改成依情境語言取 backend i18n 模板（以前寫死中文子字串）。

### `t5` 判準改版（2026-08-20，EM-1 / commit 116282d）

舊斷言 `t5_post_abort_terminated_notice` 要求 abort 後**每一則** probe 都收到固定
終止提示；新斷言 `t5_post_abort_ws_closed_no_llm` 守的是同一個實質——
**終止後不得有任何 LLM 產物**——但接受兩種都合法的樣態：

| 樣態 | 什麼時候發生 | 病患端看到 |
|---|---|---|
| **A：立即關閉** | critical 在 `_handle_text_message` 內 inline 判定 → EM-1 的
  `return True` 讓主迴圈當場 break | 終態事件 + 紅旗感謝頁，WS close 1000 |
| **B：固定提示後關閉** | critical 由背景 `_drain_late_red_flags` 判定 → 本輪 handler
  正常返回、主迴圈續跑 → 下一則訊息被 `_terminated` 守衛接住 | 固定 i18n 終止提示（非 LLM），之後 close 1000 |

同一份碼、同一個情境兩場真跑各中一次（`uvicorn.log` 可見「遲到的 critical 紅旗，
中止場次」＝路徑 B）。**把任一種寫成唯一合格樣態都會製造抽樣性假紅。**

pass 需要：`probes_sent>=1`、server 主動乾淨關閉（1000/1001）、收到的 AI 文字
（若有）逐字等於該場語言的 backend i18n 終止提示模板、無紅旗重跑／abort 事件重發、
且**重連被 4009 拒絕**（新增觀測欄位 `post_terminal_reconnect`；舊結果檔沒有時
記 `unavailable` 且不 gating）。讀不到 i18n 模板卻收到文字 → `precondition_not_met`
（證明不了那是確定性提示而不是 LLM 續答），不是 pass 也不是 fail。

主控 2026-08-20 裁決接受 EM-1 帶來的行為變更（方案 a）：病患端在關閉前已收到
`aborted_red_flag` 終態事件與紅旗版感謝頁，重連由 `conversation_handler.py:530-536`
的 4009 守衛擋住，主動關閉還省掉一次無意義的 LLM/TTS 呼叫。

⚠️ **這兩場到第四輪為止仍是「宣告了但沒真跑」**——「語序變體已驗」只有離線 replay
撐著。第四輪對它們做了離線體檢（`driver.py preflight`），三場 torsion 都綠：
主訴 c7 在 DB 且 active、analyzer/紅旗 spec 都登記了、zh-TW 與 en-US 的終止提示模板
都在、persona 硬性規定的第一句規則層都命中
（zh 原始 `睪丸突然/睪丸/突然`、zh 語序變體 `睪丸/突然`、en `testicle/really bad`）。
**preflight 綠 ≠ 這兩場會 PASS**：真跑才會驗到 abort 時機、SOAP、終止提示實收文字。
- **hematuria_coop_en_fixed**（同 baseline 情境、換驗收斷言）：
  h1 ≤ HARD_CAP(10)+MAX_HARD_CAP_DRAIN_DEFERS(2)=12 回合 `completed`（E1/E3）；
  h2 恰好 1 份 SOAP；**h3 `red_flag_alerts` 同 canonical_id 僅 1 筆（A5）**；
  **h4 `soap_reports.language='en-US'`（B3）**；h5 收尾輪 AI fullText 非空（A1，
  baseline 上是空字串）。上限值可用 `E2E_HARD_CAP` / `E2E_DRAIN_DEFERS` 覆寫。
- **ed_zh**（zh-TW、勃起功能障礙 c8，上限 12 回合）：配合病患，預期 8-10 輪自動結束。
  斷言：e1 completed；e2 有 SOAP；**e3 `icd10_codes` 含 N52 開頭（B1）**；
  **e4 `icd10_verified=true`（B2）**。

DB 欄位（`soap_reports.language/icd10_codes/icd10_verified`、`sessions.red_flag`、
`red_flag_alerts.canonical_id`）都做了存在性偵測，worktree schema 變動不會炸 driver。

### 全情境共用的斷言（2026-07-27 第二輪加固）

- **`*_patient_facing_wording_compliant`**（torsion `t8` / hematuria_3b `r7` /
  ed_3b `r7` / ed `e5` / intake `i8` / dontknow `c3` / hematuria_fixed `h8`）：
  **一道檢查掃四類病患端文字**——
  1. `red_flag_alert` WS payload 全部字串葉節點（含 `suggestedActions`）
  2. **AI 逐字稿全文**（病患整場真正聽到的東西）
  3. 場次終結後的**終止提示**（`post_terminal_probes` 的每一則文字）
  4. **SOAP 病患端可見欄位**：`PATIENT_FACING_SOAP_FIELDS` ＝ `summary`、
     `plan.patient_education` 兩欄，**不含 `review_notes`**
     （來源：`PatientSessionDetailPage.tsx:63/111`、
     `flutter_app/lib/features/patient/patient_session_detail_page.dart:80,122-125`）

  **判準＝「有沒有指示病患自行離場求醫」（`SELF_REFERRAL_RULES`），不是
  「有沒有出現某個詞」。** 依 CLAUDE.md 鐵律：部署情境＝院內候診 kiosk，病患已在
  現場，措辭應為「請稍候等看診」「請告知現場醫護」。

  違規樣態（五語言，各自獨立 regex）：急迫副詞＋求醫動作（「立即就醫」）、
  祈使／急迫＋移動動詞＋醫療場所（「請自行到附近的醫院掛號」「建議您盡快前往其他
  醫院」）、`seek immediate medical attention` / `go to the ER` /
  `get checked at a hospital` / `すぐに救急外来を受診` / `응급실로 가세요` /
  `đến khoa cấp cứu ngay`、叫救護車／119／911。

  ⚠️ **2026-07-27 第三輪把固定片語黑名單換掉了**，因為它兩個方向都錯：
  - 太寬：裸「急診評估」「急診室」一律禁 → `torsion_critical_zh` 的 SOAP summary
    寫「需立即進行超音波檢查和泌尿科**急診評估**」被判違規。那句在說要做什麼檢查，
    **沒有**叫病患離開現場；「醫師會為您安排急診評估」對候診病患完全合規。
  - 太窄：黑名單只認固定字面，「請自行到附近的醫院掛號」
    「You should get checked at a hospital as soon as possible」一個字都沒命中。

  放寬的部分不會失去可見度：舊黑名單那類詞另外記在
  `watchlist_hits_not_gating`（純觀測、不 gating）。

  與後端出口消毒層（`soap_generator` 的 `_LEAVE_SITE_HARD` / `_ON_SITE_EXEMPT` /
  `_LEAVE_SITE_SOFT` ＋ 在地化替換文案 `_PATIENT_FACING_CLAUSE`，同批改動；
  舊名 `_PATIENT_FACING_REWRITES` / `_PATIENT_FACING_RESIDUAL` 已不存在）
  **判準對齊但實作獨立**——後端只消毒 SOAP 的 `summary` /
  `plan.patient_education`；driver 還掃 AI 逐字稿、`red_flag_alert` payload、
  終止提示（那三類後端沒有出口消毒層）。
  已知的**刻意不一致**：後端 SOFT 收裸 `emergency room` / `ER` / `응급실` /
  `救急外来`（那是它對自己輸出的保守選擇，且有施事者豁免當安全網），
  driver **不收裸名詞**，否則「已通知急診室」這種合規句會被判違規。

  ⚠️ **只掃 `summary` 與 `plan.patient_education` 兩個 SOAP 欄位**，不掃
  `plan.follow_up` / `diagnostic_reasoning` / `recommended_tests` / `review_notes`
  —— 那些是醫師端文件，臨床上本來就會寫「立即至急診」，掃它們是誤傷。
  `review_notes` 於 2026-07-27 從清單移除：兩份前端已把它從病患端 fallback 拿掉
  （醫師的審閱備註），後端消毒層也明文不掃它（`soap_generator.py`
  `_sanitize_patient_facing_fields` 只動 `summary` 與 `plan.patient_education`），
  三處判準對齊。要改這個邊界，先確認前端到底渲染了哪些欄位給病患。

  ⚠️ **第四輪修的實作漂移：** 常數 `PATIENT_FACING_SOAP_FIELDS` 第三輪就正確地
  拿掉了 `review_notes`，但 `_patient_facing_texts()` 底下**還硬編著**
  `"review_notes": soap.get("review_notes")` 照掃不誤——常數與實際掃描範圍是兩份，
  必然漂移。現在掃描範圍一律從常數推導。目前結果檔的 `review_notes` 全是 `None`
  所以還沒炸；醫師一旦寫「已安排立即至急診進行手術探查」就是假 FAIL，
  而且會逼人去改**醫師看的**欄位。（實測：那段文字丟進 `review_notes` → `pass`；
  丟進 `summary` → `fail`／`zh_go_to_facility`。）

  舊版只掃 `red_flag_alert` 一種來源 → 真跑兩場的 `plan.patient_education`
  白紙黑字寫著「立即就醫」卻報 pass；`analyze_intake_wiring` 更是五個 analyzer 裡
  唯一沒掛措辭檢查的（那場有發 high 紅旗給病患端，合規純屬運氣）。

- **`*_red_flag_rule_layer`**（torsion `t9` gating／其餘情境 `not_applicable`）：
  **規則層 fallback 有沒有真的參與**（不變式 #9）。語意層（LLM）與規則層（關鍵字
  catalogue）都能單獨產出 critical alert，兩者在 DB 裡除了 `confidence` /
  `trigger_keywords` 之外**長得一模一樣** → 只斷「有 critical alert 存在」證明不了
  規則層有命中。已覆核實測：把 `shared.py` 的新關鍵字全部 revert，語意層照樣產出
  critical → 舊的 `t1`~`t7` 全綠。

  斷言內容：指定 `canonical_id` + `severity` 的 alert 至少要有一則
  `confidence == "rule_hit"`（`semantic_only` / `uncovered_locale` 都代表規則層漏接；
  combined 會被 backend 升級成 `rule_hit`）**且** `trigger_keywords` 非空，
  **且**磁碟上的規則層離線重跑對同一段病患原話仍然命中（見「規則層離線重跑」一節）。

  哪些情境 gating 由 `SCENARIO_RED_FLAG_SPEC` 宣告。三個 `torsion_*` 情境
  （`torsion_critical_zh` / `torsion_wordorder_zh` / `torsion_critical_en`）gating；
  血尿等情境是 `not_applicable`——病患講的是「整泡尿是紅色的」而不是「血尿」，
  語意層獨力命中屬合理，gating 會誤傷。confidence / trigger_keywords
  一律另記在 `analysis.diagnostics.red_flag_layers` 供覆核。

  **`expects_red_flag` 以前是死參數（2026-07-27 第三輪修）：** 宣告
  `expects_red_flag=True` 但 `rule_layer_gate=None` 的情境，就算整場 0 則紅旗，
  這條仍回 `not_applicable`（不影響 overall）→ 那個宣告等於沒作用。現在
  `expects_red_flag=True` ＋ 0 則 alert → **FAIL**；有 alert 但沒宣告 gate 才是
  `not_applicable`。

  DB 明細（`confidence` / `trigger_keywords` / `alert_type` / `matched_rule_id`）
  現在存進 `db_state.red_flag_alert_rows`；舊結果檔沒有這欄時 `reanalyze` 會用
  `session_id` 回 DB 補撈（標 `red_flag_alert_rows_source=backfilled_at_reanalyze`），
  補撈不到就 `precondition_not_met`，**不得**當成 pass。

- **`analysis.diagnostics`（所有情境，不 gating）**：
  - `icd10`：`icd10_codes` / `icd10_verified` / `malignancy_codes` /
    `in_situ_codes` / `uncertain_behaviour_codes` /
    `patient_cancer_terms_in_transcript` / `flags`。
    出現惡性腫瘤碼（C00–C97）但病患逐字稿沒有任何癌症病史陳述時，
    `flags` 會列出 `malignancy_code_without_patient_cancer_history`。
    **刻意做成 diagnostics 而不是 gate**：惡性腫瘤碼可能是合理的鑑別診斷編碼
    （`hematuria_3b_en` 上一輪出 C67.9、這輪只出 R31.0，是抽樣差異），
    這是**臨床拍板項不是 bug**——但一定要讓它現形。
  - `red_flag_layers`：每則 alert 的 confidence / trigger_keywords / alert_type。
  - `server_code_provenance`：見上一節。

- **`r5_wrapup_no_new_question`**（hematuria_3b / ed_3b）：收尾輪不得發問。
  判定對象是**逐字稿**——那就是病患實際收到的東西，所以能區分
  「LLM 想發問但被後端的確定性 backstop 攔下」（合格）與
  「懸空問句真的送到病患」（不合格）。三態：
  - 沒有非空的 AI 收尾訊息／場次沒 `completed` → `precondition_not_met`
    （舊版是 `"?" not in ""` ＝**恆真 pass**，可被結構性繞過）
  - 收尾訊息含以 `?`／`？` 結尾的句子 → `fail`，附上那幾句
  - 其餘 → `pass`，並記 `wrapup_source`：`deterministic_template:<i18n key>`
    （收尾文字與 backend i18n 模板**逐字**相同 ＝ backstop 產出）
    或 `llm_authored`。`ed_3b_zh` 的 `r5` 曾同一份碼 run1 紅 run2 綠，
    這個欄位讓「修好了」與「抽樣運氣」在結果檔上分得出來。

- **`t7_aborted_session_has_generated_soap`**：`sessions.status='aborted_red_flag'`
  的場次必須有 `status='generated'` 的 SOAP（醫師端要看得到報告）。
- **`i7_soap_fields_reflect_intake`**：SOAP `subjective` 的四個欄位
  （`past_medical_history` / `medications` / `allergies` / `family_history`）
  要與 intake 一致；逐欄回報 `missing_expected` 與 `placeholder_or_empty`。
- SOAP 全文（`subjective` / `objective` / `assessment` / `plan` / `summary` /
  `icd10_codes` / `review_notes`）現在原樣進 `db_state.soap_report`，覆核者可直接評
  報告品質；`subjective_head` / `full_text` 由這些欄位就地衍生（向後相容舊 analyzer）。
  舊結果檔沒存 S/O/A/P 時，`_soap_subjective()` 會從 `full_text` 還原第一個 JSON 物件。

## 注意

- OPENAI_API_KEY 是真 key：情境照上表跑、不要加跑；torsion 上限 4 回合、ed 12 回合。
- `REDIS_KEY_PREFIX` 一定要是 `gu:`：conversation_handler 讀 guidance 時
  hardcode `gu:session:{id}:supervisor_guidance`，supervisor 寫入卻用
  settings.REDIS_KEY_PREFIX；prefix 不是 `gu:` 時 guidance 迴路整條斷掉。
- WS 路徑是 `/api/v1/ws/sessions/{session_id}/stream`（`?token=` legacy 認證仍可用）。
- 建場次一定要帶 `chiefComplaintText`（前端行為）；不帶會踩
  `_validate_session` fallback 到 ORM 物件的 TypeError，WS 直接斷線。
- 收尾：`pkill -f "uvicorn app.main:app"`；docker compose 服務留著重用。
- **SOAP 斷言硬依賴 celery worker。** 沒起 worker（或 worker 卡住）時報告會停在
  `GENERATING`，`db_state.soap_poll.timed_out` 會是 `true`、SOAP 斷言 FAIL——
  這是正確行為，不要為了讓它變綠而放寬斷言，先去看 `celery_worker.log`。
  `SOAP_POLL_TIMEOUT`（預設 150s）是等 Celery 的上限。
- `reanalyze <scenario>` 會用**當前** driver.py 的斷言重算舊結果檔並就地覆寫
  `analysis` 區塊（逐字稿／events 不動；`db_state` 只會被**補上**
  `red_flag_alert_rows`，且需要 docker postgres 還活著、session 還在）。
  改完斷言後拿既有結果檔 reanalyze 一輪，是驗「斷言是否真的抓得到 bug」最省額度的方法。
- **改完斷言一定要證明它「抓得到」，不是只證明它「跑得動」。** 標準做法：拿一筆
  **已知有問題**的真實資料餵給新斷言，看它是不是 FAIL。例：規則層斷言用修復前那場
  torsion 的 session（DB 裡 `confidence=semantic_only`）驗證會 FAIL、用修復後那場驗證
  會 PASS，才算證明它不是恆真：

  ```python
  # cd backend && venv/bin/python
  import sys, psycopg2; sys.path.insert(0, "../scripts/e2e_realopenai")
  import driver as D
  conn = psycopg2.connect(D.PG_DSN); cur = conn.cursor()
  q = lambda sql, a=(): (cur.execute(sql, a), cur.fetchall())[1]
  cols = {r[0] for r in q("select column_name from information_schema.columns "
                          "where table_name='red_flag_alerts'")}
  rows = D._query_alert_rows(q, cols, "<某個舊 session_id>")
  print(D._rule_layer_check({"red_flag_alert_rows": rows},
        D.SCENARIO_RED_FLAG_SPEC["torsion_critical_zh"]["rule_layer_gate"], True)["status"])
  ```
