"""
紅旗症狀偵測器 — 雙層偵測（規則比對 + 語意分析）

提供即時紅旗症狀偵測功能，結合關鍵字規則比對與 LLM 語意分析，
確保不遺漏任何可能需要緊急處理的危險症狀。
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.metrics import (
    record_red_flag_rule_layer_coverage,
    record_red_flag_triggers,
)
from app.core.openai_client import (
    cache_kwargs,
    call_with_retry,
    get_openai_client,
    sampling_kwargs,
)
from app.pipelines.prompts.shared import (
    RED_FLAG_SUPERSEDES,
    URO_RED_FLAGS,
    get_display_title,
    has_locale_coverage,
    normalize_canonical_id,
    render_red_flag_titles_for_prompt,
    render_red_flags_by_severity,
)
from app.utils.i18n_messages import get_message

logger = logging.getLogger(__name__)


# ── 規則層否定偵測（fail-open 安全設計）──────────────────────
# 問題：規則層原本用裸 substring `keyword in text`，「血尿」在「沒有血尿」裡也命中
# → 否定句誤觸紅旗（灌水 red_flag_rate、對護理站發不必要警示）。
# 修法：關鍵字只在「有任一非否定出現」時才觸發；若每個出現位置都被否定則不觸發。
# 安全性：只抑制「全部出現都被否定」的關鍵字——真正的紅旗提及一定有非否定出現，
# 不會被抑制，故不破壞 fail-open（寧可誤報不可漏急症）；語意層仍獨立運作為第二層。
# 整組守衛受 `RED_FLAG_NEGATION_GUARD` kill-switch 控制（預設開，關掉＝退回裸
# substring）；critical 另有更緊的散文視窗，見 `_NEG_CRITICAL_PROSE_LOOKBACK`。
_NEGATION_CUES: tuple[str, ...] = (
    # zh-TW
    "沒有", "沒", "無", "未", "否認", "並無", "不會", "不曾", "不是", "非",
    # en-US（含尾空格避免誤配 nose/nothing）
    "no ", "not ", "without", "denies", "denied", "deny", "negative for",
    "no evidence of", "absence of", "absent", "free of", "ruled out",
    # ja-JP
    "ない", "ません", "なし", "無い", "陰性",
    # ko-KR
    "없", "아니",
    # vi-VN
    "không", "chưa",
)
# 否定詞的「假朋友」：字面含否定詞子字串、語意其實是肯定陳述的詞。不排除就會讓
# 病患**自己講出來的症狀**變成否定線索 → 漏報（違反「守衛只能減少誤報」的鐵律）：
#   「我無法排尿也睪丸劇痛」→「無法排尿」本身是 critical trigger，卻被當成「無」否定
#     後面的睪丸劇痛；
#   「我覺得下肢無力，也有會陰麻木」→「無力」是馬尾症候群的症狀，卻否定了會陰麻木；
#   「我睪丸非常痛，尿不出來」→「非常」被當成「非」。
# 只收「肯定語意」的詞；真要否認時病患仍會講沒有/無/否認等，不受影響。
#
# 2026-07-27 第四輪：本表原本只有 zh 的六個詞 ＋ 事後補的兩三個個案（沒記錯／毫無
# 預警）。跨 5 個 critical 紅旗 × 5 語言的探針實測 **28 句真症狀陳述中 26 句被整句
# 抹掉**（漏報），因為每種語言的否定詞都有一整族「字面帶否定、語意是敘事／加強語氣／
# 症狀本身」的固定搭配。逐個案補是補不完的（前兩輪各補兩個詞就收手，於是同一個坑
# 換個詞就再踩一次），所以改成**按族系統性展開**，見下方各語言區塊。
_ZH_NON_NEGATION_STEMS: tuple[str, ...] = (
    # (a) 時間敘事：「沒多久就…」＝「過了一小段時間之後」，是**發作經過**不是否認。
    #     漏報實例：「今天早上開始痛，沒多久睪丸就腫起來痛到吐」→ 規則層 0 命中。
    "多久", "過多久", "隔多久", "多會", "一會", "一下子", "兩下",
    "兩秒", "幾秒", "半分鐘", "兩分鐘", "幾分鐘", "兩天", "幾天",
    "兩個小時", "幾個小時", "多長時間", "多少時間",
    # (b) 轉折／意外：「沒想到今天血尿很多」
    # ⚠️ 刻意**不**收「注意到」：「沒有注意到體重減輕」是 TODO-E11 點名的**明確
    #    否認**（病患在說自己沒有這個症狀），沒有任何症狀讀法。收了就是把一條
    #    既有的、正確的抑制拆掉——那不是「偏誤報」政策要的方向（政策要的是不
    #    抑制**非否認**語境，不是連明確否認都不抑制）。
    "想到", "料到", "預料到", "預警", "徵兆",
    # (c) 確認語：「沒記錯」「沒錯」（第三輪已補，改由本表統一展開）
    "記錯", "錯",
    # (d) 能力喪失＝**症狀本身**（「沒辦法排尿」＝急性尿滯留，是 critical 主訴），
    #     或程度加強（「痛到沒力氣」）。與既有的「無法／無力」同一個道理。
    "辦法", "法子", "力氣", "力", "知覺", "感覺", "意識",
    # (e) 持續／程度加強：「痛得沒完沒了」「血尿沒停過」「從來沒有這麼痛」
    # ⚠️ 刻意**不**收裸「完」：ff「沒有完」會把「沒有完全尿不出來」這種**部分否認**
    #    也放行。收「完沒了」即可涵蓋「沒完沒了」。
    "完沒了", "日沒夜", "命", "停", "斷",
    "這麼痛", "這樣痛", "那麼痛", "這麼嚴重", "這麼難受", "像這樣", "像今天",
)
_ZH_NEG_PREFIXES: tuple[str, ...] = ("沒", "沒有")
_CUE_FALSE_FRIENDS: tuple[str, ...] = tuple(
    prefix + stem for prefix in _ZH_NEG_PREFIXES for stem in _ZH_NON_NEGATION_STEMS
) + (
    # zh-TW：「無 / 非 / 未」族
    "無力", "無法", "無論", "無數", "無比", "無意識", "無感覺", "無知覺",
    "無時無刻", "無以復加", "無故",
    "非常", "非但", "非得",
    "未免",
    # 2026-07-27 第三輪 Gate：「睪丸大概一個鐘頭以前毫無預警地劇痛起來」被整句抹掉
    # ——「毫無預警」是**急性發作**的描述（加強語氣），卻被裸「無」當成否定線索。
    "毫無預警", "無預警", "毫無徵兆", "無緣無故",
    # ── en-US ────────────────────────────────────────────────
    # 「cannot / not able」＝能力喪失，本身就是主訴（cannot urinate ＝ critical）；
    # 「no warning / without warning」＝ 毫無預警的英文對應；
    # 「no idea / not sure」＝ 病患在 hedge，後面接的才是症狀。
    # ⚠️ 刻意**不**收 "do not" / "did not" / "no history of"：那些是明確否認。
    "cannot", "can not", "not able", "not even able", "no longer able",
    "not stop", "not stopping", "not sleep", "not sleeping", "not walk",
    "not sure", "not certain", "not only", "not just",
    "no warning", "without warning", "without any warning",
    "no idea", "no clue", "no reason", "no relief", "no let up", "no letup",
    "no sleep", "no words", "not long after",
    # 2026-07-27 第四輪 Gate 雙向探針：以下四族是**病患用否定句陳述症狀本身**，
    # 舊表漏掉，於是整句被當成否認抹掉（全部是 critical 漏報，實測）：
    #   "i have **not been able** to pee since last night…" → urinary_retention MISS
    #     （表內只有 "not able"，接不到助動詞插在中間的 "not been able"）
    #   "…because **no urine** will come out"                → urinary_retention MISS
    #   "there is **no feeling** in the saddle area…"        → cauda_equina MISS
    #   "i have **no control** over my bladder…"             → cauda_equina MISS
    # 四者的共同形狀：否定詞後面接的是「能力／感覺／尿液的缺失」＝主訴本身。
    # ⚠️ 刻意**不**收 "no blood" / "no pain" / "no fever"：那些是明確否認。
    "not been able", "have not been able", "has not been able",
    "no urine", "no feeling", "no sensation", "no control",
    "no urine will", "no urine comes", "no urine came",
    "without stopping", "without relief", "without any relief",
    "without being able", "without warning at all",
    # ── ja-JP ────────────────────────────────────────────────
    # 可能形否定（歩けない／我慢できない…）由 `_POST_CUE_FALSE_FRIENDS` 展開後
    # 一併併入（見 `_PRE_CUE_FALSE_FRIENDS`）；這裡是其餘的固定搭配。
    "仕方ない", "しかたない", "しょうがない", "しようがない", "やむを得ない",
    "信じられない", "たまらない", "とんでもない", "間違いない", "違いない",
    "今までにない", "これまでにない", "かつてない",
    "ないほど", "ないくらい", "ないぐらい",
    # ── ko-KR ────────────────────────────────────────────────
    # 「참을 수 없이 아파요」類由 `_POST_CUE_FALSE_FRIENDS` 併入；這裡補其餘搭配。
    "어쩔 수 없", "하는 수 없", "쉴 새 없", "끝없", "정신없", "말도 안 되",
    "아니나 다를까",
    # 2026-07-27 第四輪 Gate：「감각이 없」＝**鞍區感覺喪失**，是馬尾症候群的紅旗
    # 症狀本身（它同時就是 cauda_equina 共現組的急性詞），卻被裸「없」當成否定線索
    # 把同一子句的「소변이 새요」抹掉 → critical 漏報（實測）。
    # 「힘이 없／기운이 없」同理（下肢無力／全身虛弱）。
    "감각이 없", "느낌이 없", "힘이 없", "기운이 없", "숨을 쉴 수 없",
    # ── vi-VN ────────────────────────────────────────────────
    # 「không thể / không chịu nổi」＝能力喪失或加強語氣（không thể đi tiểu ＝
    # critical 主訴本身）。⚠️ 刻意**不**收裸 "chưa bao giờ"：「chưa bao giờ bị đau
    # tinh hoàn」是明確否認；只收「chưa bao giờ đau như」這種**比較級**的加強語氣。
    "không thể", "không chịu", "không nổi", "không tài nào", "không ngờ",
    "không lâu sau", "không bao lâu", "không dứt", "không ngừng",
    "không đi tiểu được", "không tiểu được", "không đái được",
    "không ngủ", "không đứng", "không đi lại", "không nói nên lời",
    # 2026-07-27 第四輪 Gate：越南文的尿滯留／馬尾症候群主訴同樣是否定句形狀
    #（rặn mãi mà **không ra được** giọt nước tiểu nào ＝ 怎麼用力都尿不出來；
    # **không nhịn được** tiểu ＝ 憋不住尿；**không có cảm giác** ＝ 沒有感覺）。
    "không ra được", "không ra giọt", "không nhịn được", "không giữ được",
    "không có cảm giác", "không cầm được", "không cử động được",
    "chưa bao giờ đau như", "chưa từng đau như", "chưa bao giờ bị đau như",
    # 註：曾列過「不舒服／不適／不對勁／不明／不停／不斷／不止／不良」，但
    # `_NEGATION_CUES` 並無裸「不」（只有 不會／不曾／不是），那些條目永遠命中不到
    # ——是死碼，且會讓人誤以為裸「不」也被守護。2026-07-26 移除。
    # 若日後把裸「不」加進 cue 列表，這些必須一併加回來。
)
# 否定範圍切斷：句尾/子句標點。list 分隔（、，,）不切斷，讓「沒有血尿、發燒、腰痛」整串被否定。
_NEG_SCOPE_BREAKS: str = "。！？!?\n．;；:："
# 轉折/接續詞：其後語義重置。避免「沒有發燒但有血尿」「沒力氣然後睪丸劇痛」
# 把後段關鍵字誤當否定（保守：寧可少抑制→過度警示 over-triage 安全，也不過度
# 抑制→漏報 under-triage 危險）。
# 重置詞＝轉折(但/可是)＋接續(然後/接著)＋追加子句(而且/並且)＋肯定轉承(就是/只是)。
# 這些引入「新謂語」，其後的關鍵字不受前面否定涵蓋；「就是/只是」尤其是門診口語裡
# 「否認一串之後點出真正症狀」的標記（「我沒有什麼特別的問題，就是尿不出來」——沒有
# 這個重置，critical 的尿滯留會被前半句的「沒有」吃掉，那是 under-triage）。
# **刻意不含 list 連接詞（、，,以及/及/和/與/或/還有）**，因為它們只是把同一否定下
# 的並列項串起來（「沒有血尿、發燒以及腰痛」三者皆否定）。
# ⚠️ 方向性（安全關鍵）：重置詞只會讓否定範圍**變短** → 抑制變少 → 紅旗**更容易**命中。
# 所以這個列表寧可過寬也不可過窄；過寬的代價是 over-triage（護理師多走一趟，可逆），
# 過窄的代價是 under-triage（真急症漏掉，不可逆）。
#
# ja/ko/vi/en 原本缺席，導致「否認某症狀＋轉折＋真的有 critical 症狀」在那四種語言
# 全數漏報（2026-07-26 對抗式驗證實測）：
#   「熱はないですが尿閉になりました」→ urinary_retention(critical) MISS
#   「열은 없지만 요폐가 생겼어요」→ urinary_retention(critical) MISS
#   「denies fever, however he has testicular pain」→ MISS（"however" 不在列表）
# 規則層是語意層漏判時的 fallback（不變式 #9），那條 fallback 在這些語言對 critical
# 等於失效。中文對照組（「沒有發燒，但是尿不出來」）一直是正常的，所以肉眼難察覺。
#
# 日文的「が」刻意收錄：它同時是主格助詞，當轉折用時無法純字面區分。但依上面的方向性，
# 誤判成重置只會多命中、不會漏掉，故取寬。
_CONTRAST_MARKERS: tuple[str, ...] = (
    # zh-TW
    "但", "可是", "不過", "然而", "但是", "反而",
    "然後", "接著", "後來", "之後", "而且", "並且",
    "就是", "只是",
    # en-US（前後留白避免命中 "although" 之類的子字串誤切；however/though 直接收）
    " but ", "however", "though", "although", " yet ",
    # ja-JP（ですが/けど/けれど/しかし/でも；「が」見上方註解）
    # 「ではなく／じゃなくて」＝同上的日文對應（不是 X 而是 Y）。
    "ですが", "けれど", "けど", "しかし", "でも", "が", "ではなく", "じゃなくて",
    # ko-KR。「아니고 / 아니라」＝「不是 X 而是 Y」，後段才是真正的主訴，必須重置——
    # 否則「열은 아니고 극심한 고환 통증이 있어요」（不是發燒，是睪丸劇痛）會被前面的
    # `아니` cue 整句吃掉（2026-07-26 對抗式驗證實測 critical MISS）。
    # 不收裸「고」：那是泛用連接詞，到處都是，收了等於關掉守衛。
    "지만", "하지만", "그런데", "그러나", "아니고", "아니라",
    # 2026-08-20 稽核 RF-2：韓文最常見的「否認病史 ＋ 真急症」接法**沒有標點**，
    # 靠連接語尾「~는데／~은데／~인데」串起來：
    #   「당뇨는 없고 고혈압도 없는데 어젯밤부터 고환이 갑자기 심하게 아파요」
    # 舊表只有終結形的「지만／그런데」，接不到語尾形 →「없」把整句吃掉、
    # critical 漏報（五語探針裡韓文唯一的漏法）。
    # ⚠️ 這幾個語尾也用在非轉折的「背景說明」語境（「소변이 안 나오는데 어떡하죠」），
    #   但依本表的方向性註記，重置只會讓否定範圍**變短** → 抑制變少 → 更容易命中，
    #   是安全的一側。真正的否認（「고환 통증은 없어요」）不含這些語尾，不受影響。
    # 註：「아픈데」這種 ㄴ 已併入音節的形（아프＋ㄴ데）字面上抓不到，
    #   本表只收獨立成音節的三種；那不影響本輪修的形狀（없는데／괜찮은데／아닌데）。
    "는데", "은데", "인데",
    # vi-VN
    "nhưng", "mà",
)
# 往前回看上限（字元）：放寬到涵蓋長症狀否定列舉（「沒有血尿、發燒、畏寒、噁心、嘔吐、
# 食慾不振、體重減輕、排尿疼痛…、尿滯留」整串在同一個「沒有」下）。安全考量：規則層
# 有語意層並行當後備（LLM 懂否定），故規則層可較積極抑制否定誤觸以減少誤 abort；list
# 分隔不切斷、只有句尾標點與上面的重置詞切斷。120 為 runaway 上限（超長 run-on 才觸及）。
_NEG_MAX_LOOKBACK = 120

# ── critical 專屬：較緊的「散文」否定視窗（E11 取捨）──────────────
# 為什麼 critical 要跟 high/medium 不同：critical 一命中就 abort 問診（見
# conversation_handler 的 has_critical 分支），**兩個方向的誤判成本都高**——
#   誤報 → 誤中止問診、SOAP 資料不全、白叫護理師；
#   漏報 → 真扭轉/尿滯留的病患繼續坐著等，且無第二次機會。
# 取捨：在 kiosk 情境下這兩者仍不對稱。病患已經在現場，誤 abort 的代價是護理師
# 走過來一趟（可逆、幾分鐘）；漏報的代價不可逆。所以 critical 選「更不願意抑制」，
# 但**不是完全不抑制**——直接否認（「沒有睪丸劇痛」「denies testicular pain」）
# 仍必須抑制，否則 E11 點名的誤 abort 又回來了。
#
# 具體做法：critical 的否定線索必須「離關鍵字很近」才算，其中「近」只計算**散文**
# 字元——list 分隔符（、，,）會把預算歸零。理由：緊接在否認之後的並列症狀列舉
# （「沒有血尿、發燒、…、尿滯留」）語意上明確是同一個否認，長度多長都該抑制；
# 中間夾了一長段散文的「沒有…（16 字以上敘述）…尿不出來」則不可信，寧可命中。
# 這對 STT 逐字稿特別重要：口語辨識常常整段沒有標點，舊的 120 字視窗會讓一個
# 「沒有」吃掉後面整段話裡的 critical 關鍵字。
# 安全性（單向性，重要）：本視窗只會讓 critical **更容易命中**，不可能更難命中
# ——它是在既有 120 字視窗內再加一層限制，抑制條件只會變嚴、不會變鬆。
_NEG_CRITICAL_PROSE_LOOKBACK = 16
# list 分隔符（散文預算歸零點）。刻意只放標點：中文頓號/逗號與半形逗號。
_NEG_LIST_SEPARATORS: str = "、，,"

# ── critical：不被 list 分隔符重置的**總**回看上限（2026-08-20 稽核 RF-2）──
# 上面的散文預算在每一個 、／，ˍ處歸零，所以「否定的作用範圍」實質只受
# `_NEG_MAX_LOOKBACK`（120 字元）約束：一句
#   「我沒有糖尿病、沒有高血壓、沒有心臟病、沒有腎結石、沒有開過刀、睪丸突然劇痛」
# 裡最前面那個「沒有」照樣構得到最後的關鍵字。120 字元對 CJK ≒ 120 個語素，
# 那不是「同一個否認下的並列列舉」該有的長度，是 runaway。
# 這裡加一個**不歸零**的總預算當硬牆。
# 為什麼是 48 而不是更緊：E11 明文要保護的最長合法形狀是
#   `test_negated_enumeration_still_suppressed` 那句對抗性 e2e 語料——單一「沒有」
#   帶 12 個並列症狀，從尾端的 critical 關鍵字「完全排不出」回看到「沒有」實測是
#   **39 個語素當量**。收到 40 以下就會讓那句翻面（實測會紅）。48 留約兩成餘裕，
#   同時把 CJK 的回看距離砍成原本 120 字元上限的四成。
# ⚠️ 這條只是 runaway 的硬牆，**不是** RF-2 的修法：RF-2 那類「否認病史 ＋ 逗號 ＋
#   真急症」的最近否定詞只隔 5–7 個語素當量，任何長度上限都攔不住它，
#   真正承重的是下面 (b) 的「新發作陳述」切斷。
# 方向性：上限只會讓否定範圍**變短** → 抑制變少 → critical 更容易命中（安全側）。
_NEG_CRITICAL_TOTAL_LOOKBACK_UNITS = 48


# ── 語素當量計數（**同一個 bug 同時造成兩個方向的錯**，2026-07-27 第三輪 Gate）──
# 這個模組有兩處用「字元數」當距離預算：上面的 critical 散文否定視窗（16），
# 以及下面共現組的配對距離（CJK 24 ∕ 拉丁 30）。字元在不同書寫系統代表的資訊量
# 差 2–4 倍，於是同一個常數在兩個方向同時出錯，實測（Gate 雙向探針）：
#
#   [漏報｜視窗太小] 拉丁/越南文的正常語序被距離切掉
#     "my testicle, about ninety minutes ago, became excruciating"（35 字元 > 30）
#     "tinh hoàn bên phải của tôi từ lúc nửa đêm bỗng nhiên đau dữ dội"（48 > 30）
#   [誤報｜視窗太小] 否定線索構不到關鍵字 → 該抑制的沒抑制
#     "tinh hoàn không hề đau dữ dội đột ngột" 的 "đột ngột" 距 "không" 15 字元散文
#     ——差 1 個字元就被 16 字預算截掉，於是「明確否認」照樣觸發 critical。
#
# 修法：兩處都改用「語素當量」而不是裸字元。CJK（含假名/諺文）一個字元 ≈ 一個語素，
# 計 1；拉丁/越南文以**空白分隔的詞**為單位（詞內字母不計費）。這正是本檔原本就寫在
# 註解裡的理由（「兩檔的實際語素容量相當」），只是先前用字元硬編兩檔去近似它。
# 方向性：CJK 的計數與改動前**完全相同**（CJK 字元本來就 1 字 1 單位、極少空白），
# 所以所有既有的中日韓驗收行為不變；改變的只有拉丁/越南文，且兩個方向都變正確。
_CJK_RANGES: tuple[tuple[str, str], ...] = (
    ("぀", "ヿ"),  # 平假名 / 片假名
    ("㐀", "䶿"),  # CJK 擴充 A
    ("一", "鿿"),  # CJK 統一表意
    ("가", "힯"),  # 諺文音節
    ("豈", "﫿"),  # CJK 相容表意
)


def _is_cjk_char(ch: str) -> bool:
    return any(lo <= ch <= hi for lo, hi in _CJK_RANGES)


def _char_units(ch: str) -> int:
    """單一字元的語素當量成本。

    CJK 字元 → 1（字≈語素）。空白 → 1（拉丁/越南文的詞界，一個空白≈一個詞）。
    其餘（拉丁字母、變音符號、數字、詞內標點）→ 0，因為它們是**詞內**的字元，
    計費會讓 "excruciating" 這種長單字自己把預算吃光。
    """
    if _is_cjk_char(ch):
        return 1
    if ch.isspace():
        return 1
    return 0


def _span_units(text: str) -> int:
    """一段文字的語素當量長度（見 `_char_units`）。"""
    return sum(_char_units(c) for c in text)

# 後置否定（ja/ko 為 SOV，否定接在名詞之後：「血尿はありません」「혈뇨는 없어요」）。
# 這些線索出現在關鍵字「之後」的短視窗內才算。⚠️ ja/ko 語言特定，上線前建議母語者覆核。
_POST_NEGATION_CUES: tuple[str, ...] = (
    # ja-JP（含否定連用形「なく」：体重減少はなく）
    "ありません", "ません", "ない", "なく", "無く", "なし", "無い", "見られません", "陰性",
    # ko-KR
    "없", "아니",
)
# 後置否定的「假朋友」——與 `_CUE_FALSE_FRIENDS` 同一個道理，但作用在關鍵字**之後**。
# ja/ko 的「不能～」可能形否定與「忍不住～」句式，字面帶 ない／없 卻是**加強語氣**，
# 是病患在描述症狀有多嚴重，不是在否認症狀。不排除就會把最典型的急症句抹掉
# （2026-07-27 第三輪 Gate 雙向探針實測，全部是漏報方向）：
#   「精巣がさっきトイレに行った後で急に耐えられない痛みになりました」→ 抑制（漏報）
#   「고환이 저녁 먹고 나서 갑작스럽게 참을 수 없이 아파요」            → 抑制（漏報）
# 注意「我慢できない」本身就是共現組的**急性詞**，不排除等於它永遠自我否定。
# 方向性：白名單只會讓紅旗**更容易**命中（fail-open），不可能製造新的誤抑制。
# ⚠️ 常體與敬體都要列（2026-07-27 第三輪 Gate 實測踩到）：只列「歩けない」會漏掉
#   「左の精巣の痛みがひどくて歩けません」——那是既有測試裡的教科書級扭轉描述，
#   漏了就是把一個誤報換成一個漏報。故用「可能形語幹 × 否定語尾」展開，不逐條手寫。
_JA_POTENTIAL_NEG_STEMS: tuple[str, ...] = (
    "耐えられ", "たえられ", "我慢でき", "がまんでき", "こらえられ", "辛抱でき",
    "歩け", "あるけ", "立て", "たて", "眠れ", "ねむれ", "動け", "うごけ",
    "座れ", "すわれ", "寝られ", "じっとしていられ",
)
_JA_NEG_SUFFIXES: tuple[str, ...] = (
    "ない", "ないです", "ません", "なかった", "ませんでした", "ず",
    # 2026-08-20 稽核 RF-4 の副産物：**連用形否定**「なく／なくて」が抜けていた。
    # `_POST_NEGATION_CUES` には「なく」が入っているので、
    #   「尿が全く出なくて下腹がパンパンです」
    #   「昨日の夜から全然おしっこが出なくて下腹が張って痛いです」
    # の尿語が「否認された」と判定されていた（＝症状陳述を否認と読む、
    # `_JA_SYMPTOM_NEG_STEMS` がまさに潰そうとしていた穴の活用形違い）。
    # これまでは同じ文の「下腹」側が命中を救っていたので露見しなかったが、
    # RF-4 で「下腹」を外した時点で critical 漏報として表面化した。
    # 方向性：假朋友は抑制を**減らす**だけ（fail-open 側）。
    "なく", "なくて",
)
# 2026-07-27 第四輪 Gate：日文的**急性尿閉本身就是一個否定述語**（「尿が出ません」
# ＝尿出不來），感覚脱失／脱力也是（「感覚がない」「力が入らない」）。這些不是可能形
# 否定，但踩的是同一個坑：守衛把「症狀陳述」讀成「否認」，於是
#   「トイレに行っても、力んでも、尿が一滴も出ません」→ 規則層 0 命中（critical 漏報）
# 實測連教科書句「尿が出ない」單獨一句都不命中——**改動前就存在**的缺陷，
# 由 test_red_flag_cooccurrence_coverage.py 的 strict xfail 釘住（本輪修掉）。
# ⚠️ 代價（政策上接受的方向）：「血尿は出ません」這種**用同一形狀講的否認**也會
#   跟著放行 → 誤報。依 2026-07-27 臨床拍板（偏誤報：誤中止可逆、漏報不可逆）取此側；
#   而真正常見的否認講法（「血尿はありません」「熱は出ていません」）不含這些字面，
#   仍然照常被抑制。
_JA_SYMPTOM_NEG_STEMS: tuple[str, ...] = (
    "出", "尿が出", "おしっこが出", "小便が出", "感覚が", "力が入ら", "動かせ",
    # 2026-08-20 稽核 RF-4：可能形「排尿できない／排尿ができません」も同じ族。
    # `_clause_final_denial`（子句尾述語否定）が「朝から排尿ができません」を
    # **否認**と読んでいたため、急性尿閉の最も教科書的な日本語文が
    # 規則層 0 命中だった（RF-4 で共現組の裸「できない」を外した時点で表面化）。
    # 「排尿ができない」に否認の読みは存在しない（＝症状そのもの）ので安全。
    "排尿でき", "排尿ができ", "おしっこでき", "おしっこができ",
    "小便でき", "小便ができ", "尿ができ",
)
_POST_CUE_FALSE_FRIENDS: tuple[str, ...] = tuple(
    stem + suffix
    for stem in (*_JA_POTENTIAL_NEG_STEMS, *_JA_SYMPTOM_NEG_STEMS)
    for suffix in _JA_NEG_SUFFIXES
) + (
    # ja-JP：其他加強語氣
    "言葉にできない", "言葉になりません",
    # ko-KR：「참을 수 없이 아파요」＝痛到無法忍受（前綴比對，涵蓋各種語尾）
    "참을 수 없", "견딜 수 없", "말할 수 없", "걷지 못", "걸을 수 없", "서 있을 수 없",
    "잠을 잘 수 없", "가만히 있을 수 없", "참기 힘들", "견디기 힘들",
)


def _has_post_negation_cue(after: str) -> bool:
    """關鍵字之後的短視窗內是否有「真的」後置否定線索（排除加強語氣的假朋友）。"""
    for cue in _POST_NEGATION_CUES:
        pos = after.find(cue)
        while pos != -1:
            # 命中的否定詞若落在某個假朋友的字面範圍內 → 那是加強語氣，不算否定。
            if not any(
                ff in after and after.find(ff) <= pos < after.find(ff) + len(ff)
                for ff in _POST_CUE_FALSE_FRIENDS
            ):
                return True
            pos = after.find(cue, pos + 1)
    return False
# 後置否定前掃停止字元：句尾/子句標點、list 分隔、ja 接續助詞 て/で（引入新謂語）。
# 短視窗＋停止字元避免把遠處（別的子句）的否定誤套到本關鍵字（保守，避免過度抑制）。
_POST_NEG_STOPS: str = "。！？!?\n．;；:：、，,てで"
_POST_NEG_MAX_AHEAD = 10


# ══════════════════════════════════════════════════════════════════
# 詞邊界比對（拉丁字母關鍵字）——**不受 kill-switch 控制**
# ══════════════════════════════════════════════════════════════════
# 這不是否定守衛的一部分，是「比對精度」的修正：規則層原本用裸 substring，
# 「ball hurt」會命中「my eyeball hurts a lot」→ testicular_pain_severe(critical)
# → 第 1 輪 aborted_red_flag（2026-07-27 對抗式覆核實測）。
#
# 只檢查**前緣**，刻意不檢查後緣：英文病患會講 hurt / hurts / hurting、
# 越南文也有黏著變化，加了後緣邊界會把「my ball hurts」變成漏報——那是把一個
# 誤報換成一個漏報，方向錯。前緣邊界足以擋掉 eyeball / football 這類詞尾同形。
#
# 只對「開頭是 ASCII 英數」的關鍵字生效：中日韓沒有空白詞界，若對 CJK 也要求
# 前一字元非文字，「我想問睪丸很痛」的「睪丸很痛」前面是「問」→ 會整組失效。
# 越南文多數 trigger（tinh hoàn…／bìu…／xoắn…）開頭本來就是 ASCII 字母，
# 開頭帶變音符號的（đau…）維持原本的 substring 行為，與加此規則前一致。
def _is_ascii_word_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "_")


# ── 詞義假朋友：關鍵字落在一個語意完全不同的複合詞裡 ──────────────
# ⚠️ 與本檔下方的 `_CUE_FALSE_FRIENDS`／`_PRE_CUE_FALSE_FRIENDS` 是**兩件不同的事**：
# 那組是「否定線索的假朋友」（讓否定守衛**少**抑制，方向是 fail-open）；這組是
# 「關鍵字本身的假朋友」（讓關鍵字**不算命中**，方向是收斂），兩者不共用表也不互相
# 影響。命名前綴 `_TERM_` 對應「詞義」，`_CUE_` 對應「否定線索」。
# 這**不是抑制守衛**（#22）而是**語意修正**（與 R22 的裸「熱」同一類）：被排除的字面
# 在那個位置根本不是該關鍵字的意思,不是「有這個症狀但我們選擇不報」。
#
# 缺陷（2026-08-21 敵意複驗，五語實測）：越南文 `tiểu` 一詞多義——泌尿義是「排尿」,
# 但它同時是漢越詞「小」的常用構詞成分,而越南文以**音節分寫**,複合詞中間有空白:
#     tiểu đường ＝ 糖尿病        tiểu cầu ＝ 血小板       tiểu phẫu ＝ 小手術
#     tiểu sử   ＝ 病史/生平      tiểu học ＝ 小學         tiểu não ＝ 小腦
# 於是**詞邊界救不了**（`tiểu` 在 `tiểu đường` 裡兩側都是合法詞界）,實測:
#     「tôi bị tiểu đường, và chân tôi có cục máu đông」（糖尿病＋下肢 DVT）
#     「mẹ tôi bị tiểu đường, và bà ấy có cục máu đông」（家族史＝別人的病）
#     「bác sĩ hỏi tiểu sử bệnh, tôi có cục máu đông ở chân」
#   → 全部命中 `gross_hematuria_heavy`(critical) ＝ 中止問診,並把「大量血尿」寫進
#     SOAP 紅旗區塊。糖尿病是泌尿科 intake 的**第一常見共病**,這不是邊緣情況。
#
# 為什麼不改成只收 `đi tiểu`／`nước tiểu`／`tiểu buốt`／`tiểu ra` 這些明確片語
# （#22 的漏報舉證）：實測「khi tiểu tôi thấy nhiều máu cục」「tôi tiểu ra máu cục
# rất nhiều」這類**動詞裸用**的語序靠的就是裸 `tiểu`,改收片語會直接開出漏報;
# 排除法只拿掉「`tiểu` 在該處不是排尿」的那些位置,泌尿義的每一種語序原樣保留。
#
# 收錄判準（要能說出「為什麼它不會漏報」）：只收**contiguous 且語意上與泌尿無關**的
# 漢越複合詞。刻意**不收** `tiểu đêm`(夜尿)／`tiểu tiện`／`tiểu buốt`／`tiểu rắt`／
# `tiểu són`——那些是泌尿義。已知殘餘：病患把兩個子句黏在一起打（「bí tiểu sử dụng
# thuốc gì」）時 `tiểu` 會被 `tiểu sử` 遮住,但 `bí tiểu` 這個關鍵字本身跨過遮罩起點、
# 不受影響,retention 仍命中（有測試釘住）。
#
# ⚠️⚠️ **這張表是開放式列舉,不是完備集合**（2026-08-21 敵意複驗第二輪釘死）：
# 漢越詞「小」的構詞能力沒有上限,未列進來的「小」義複合詞**仍然會供給泌尿軸**,
# 只要相鄰子句有血塊/發燒詞就配成 critical。已知仍在外面的尾巴（實測會誤報,
# 但都不是問診情境的高頻詞）：`tiểu thương`(小商販)／`tiểu bang`(州)／`tiểu thư`(小姐)
# ／`tiểu đội`(小隊)／`tiểu ban`(小組)…。所以**收到誤中止回報時的第一個假設應該是
# 「又一個沒收錄的『小』義複合詞」,而不是「這條路已經封死了」**。
# 收錄順序依「在泌尿科問診裡真的講得出來」排：intake 共病 → 臨床報告用詞 → 日常詞。
_TERM_FALSE_FRIENDS: tuple[str, ...] = (
    "tiểu đường",  # 糖尿病（泌尿科 intake 最常見共病）
    "tiểu cầu",  # 血小板（「giảm tiểu cầu」＝血小板低下,常與出血同句）
    "tiểu phẫu",  # 小手術
    "tiểu sử",  # 病史／生平（「tiểu sử bệnh」＝病史）
    "tiểu học",  # 小學
    "tiểu não",  # 小腦
    # ↓ 2026-08-21 複驗第二輪補：前四條是**臨床報告用詞**,病患轉述影像／病理報告時
    #   會逐字唸出來（「動脈瘤ở tiểu động mạch」「tổn thương ở tiểu thùy」）,
    #   而報告內容常與出血／發燒同句 → 誤中止機率高於日常詞。
    "tiểu động mạch",  # 細動脈（arteriole）
    "tiểu tĩnh mạch",  # 小靜脈（venule）
    "tiểu khung",  # 小骨盆腔（pelvis minor；骨盆影像報告高頻）
    "tiểu thùy",  # 小葉（lobule；病理報告高頻）
    "tiểu thuyết",  # 小說（日常閒聊,複驗實測誤報 critical）
)


def _shadowed_by_term_false_friend(text_lower: str, start: int, end: int) -> bool:
    """[start, end) 這個關鍵字出現位置是否**整個**落在某個詞義假朋友裡面。

    只在關鍵字已通過詞邊界檢查後才呼叫（命中很稀疏,常態路徑不付成本）。
    要求**完全包含**：`nước tiểu` 這種比假朋友長、或起點在假朋友之前的關鍵字不受影響。
    """
    for friend in _TERM_FALSE_FRIENDS:
        i = text_lower.find(friend)
        while i != -1:
            if i <= start and end <= i + len(friend):
                return True
            i = text_lower.find(friend, i + 1)
    return False


def _iter_keyword_occurrences(
    keyword_lower: str, text_lower: str, both_edges: bool = False
):
    """逐一產出通過詞邊界檢查的出現位置（起始索引）。

    both_edges=True 時**後緣**也要求詞邊界。只給共現組的**部位詞**用（見
    `_cooccurrence_matches`）：部位詞的單複數是分別列舉的（testicle/testicles、
    ball/balls），不需要靠「不檢查後緣」來容忍字尾變化，而後緣邊界可以擋掉
    「ballpark / ballroom」這種前緣合法、字尾才分歧的詞。
    一般關鍵字與共現組的**急性/嚴重度詞**維持只檢查前緣——那邊要讓
    hurt/hurts/hurting、sudden/suddenly、severe/severely 都命中。
    """
    if not keyword_lower:
        return
    needs_leading = _is_ascii_word_char(keyword_lower[0])
    needs_trailing = both_edges and _is_ascii_word_char(keyword_lower[-1])
    end_of_text = len(text_lower)
    idx = text_lower.find(keyword_lower)
    while idx != -1:
        end = idx + len(keyword_lower)
        leading_ok = (
            not needs_leading or idx == 0 or not _is_ascii_word_char(text_lower[idx - 1])
        )
        trailing_ok = (
            not needs_trailing
            or end == end_of_text
            or not _is_ascii_word_char(text_lower[end])
        )
        if (
            leading_ok
            and trailing_ok
            and not _shadowed_by_term_false_friend(text_lower, idx, end)
        ):
            yield idx
        idx = text_lower.find(keyword_lower, idx + 1)


def _keyword_in_text(keyword: str, text_lower: str) -> bool:
    """關鍵字是否（在詞邊界意義下）出現在文中；不看否定。"""
    kw = (keyword or "").lower()
    return any(True for _ in _iter_keyword_occurrences(kw, text_lower))


# ══════════════════════════════════════════════════════════════════
# 語境守衛（E11 否定守衛的擴充，同一個 kill-switch）
# ══════════════════════════════════════════════════════════════════
# 背景：E11 的守衛只擋「關鍵字**前面**有否定詞」（zh/en/vi）與 ja/ko 的後置否定。
# 2026-07-27 對抗式覆核發現三種語境同樣是「病患沒有這個症狀 / 沒有現在這個症狀」，
# 卻一律命中 critical → 誤中止問診（病患白跑一趟，且比漏偵測更容易被感知）：
#
#   後置否定  「小便會痛，睪丸痛倒是沒有」「睪丸很痛的情形沒有」
#   時態否定  「以前睪丸痛過，但現在完全好了」
#   詢問假設  「我想問睪丸痛要看哪一科」「如果睪丸突然很痛要怎麼辦」
#
# 三者都刻意設計成**必須兩個獨立訊號同時成立**才抑制，因為單一訊號的假朋友太多：
#   - 「睪丸痛到沒有辦法走路」含「沒有」，但那是加強語氣 → 只有**子句尾**的否認算。
#   - 「之前睪丸很痛，吃藥好了，今天又痛起來」含過去詞＋「好了」，但也含復發詞
#     → 復發詞一出現就不抑制。
#   - 「請問我睪丸很痛怎麼辦」是真的在求助 → 只有「詢問語氣 ＋ 掛號/科別問句」
#     同時出現才算行政詢問；單純問「怎麼辦」不算。
# 方向性：以上每一條都會**減少**規則層命中 → 只可能製造漏報。所以每個詞表都取窄，
# 而語意層（LLM 本來就懂否定與假設語氣）仍獨立跑，是這些抑制的後備。


# ── (1) 後置否定：子句尾的否認（zh/en/vi；ja/ko 沿用 _POST_NEGATION_CUES）──
# 只在「關鍵字之後、同一子句（見 _POST_NEG_STOPS）」整段**就是一句否認**時才算。
# 因此「痛到沒有辦法走路」不會被誤判（尾巴是「辦法走路」不是否認）。
_POST_DENIAL_TAIL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # zh-TW：「（倒是／的情形／完全…）沒有／並無（的／了）」結尾。
    # 中間允許的 filler 刻意只收兩類：(a) 否認連接語（倒是/的情形/完全…）、
    # (b) 症狀詞的**續字**（痛/疼痛/腫…）。(b) 是必要的：關鍵字「睪丸突然」比
    # 病患實際講的「睪丸突然痛」短，殘留的「痛」會擋在否認前面
    #（「睪丸突然痛倒是沒有」→ 尾巴是「痛倒是沒有」）。
    # 反面：filler 不收「到／得／完全沒辦法」那類程度補語，所以
    #「睪丸突然痛得沒有力氣」「睪丸痛到沒有辦法走路」不會被誤判成否認。
    #
    # 2026-07-27 第四輪曾增列方向補語 filler（出來／來／出去／去），第四輪 Gate **已還原**：
    # 它是為了 urinary_retention 共現組的 acuity 詞「尿不出」殘留一個「來」而加的，
    # 但那個詞條在同一輪就被移除了（完整的「尿不出來」本來就是裸 trigger），
    # 實測有／無 filler 對 10 筆雙向案例**行為完全相同**（「尿不出來倒是沒有」照樣抑制）。
    # 依 2026-07-27 臨床拍板（偏誤報，抑制的舉證責任在保留方）：不承重的抑制一律移除。
    # ⚠️ 刻意**不**收「尿／小便」當 filler：「小便倒是沒有」語意是**完全沒有尿**
    #   （＝尿滯留本身，是症狀不是否認），收了就是規則層自己製造漏報。
    re.compile(
        r"^(?:痛|疼痛|疼|腫脹|腫|不適|的症狀|症狀|"
        r"倒是|的情形|的狀況|的問題|的感覺|這個|那個|部分|方面|是|則|都|完全|並|\s)*"
        r"(?:沒有|沒|並無|無)(?:有)?(?:的|了|啦|喔|吧|呢)?$"
    ),
    # zh-TW：「（那個部位）沒事／沒問題」＝把該部位排除掉的**子句尾**陳述。
    # 需要它的原因（2026-07-27 第三輪對抗式覆核，共現組新增的誤報面）：
    #   「我今天早上肚子突然很痛睪丸沒事」（STT 未補標點 → 整段是同一子句）
    #   共現組會把前半句屬於**肚子**的「突然」配到後半句的「睪丸」上 → critical。
    # ⚠️ 這一條刻意**不**允許 吧/嗎/呢 收尾（上一條的 `(?:的|了|啦|喔|吧|呢)?` 有允許）：
    #   「睪丸突然很痛沒事吧」是病患在**問**自己嚴不嚴重，是真症狀陳述，
    #   若被當成否認就是規則層自己製造漏報 —— 這是加這條 pattern 唯一的危險方向。
    re.compile(
        r"^(?:痛|疼痛|疼|腫脹|腫|不適|的症狀|症狀|"
        r"倒是|的情形|的狀況|的問題|的感覺|這個|那個|部分|方面|是|則|都|完全|並|\s)*"
        r"(?:沒事|沒問題|沒怎樣|沒異常|沒毛病)(?:的|了|啦)?$"
    ),
    # en-US：「: none」「is absent」「— negative」等收尾
    re.compile(r"^[\s:—–\-]*(?:is|was|are|were)?\s*(?:not present|absent|negative|none|no)[.\s]*$"),
    # vi-VN：「thì không (có)」收尾
    re.compile(r"^[\s,:]*(?:thì|là)?\s*(?:không|chưa)(?:\s+có)?[.\s]*$"),
    # ── 「（這個部位）是正常的」＝把該部位排除掉的子句尾陳述 ──────────
    # 2026-07-27 第四輪 Gate：zh 早就有這一條（上面的「沒事／沒問題／沒異常」），
    # en/ja/ko/vi **完全沒有對應**，同一個語意在那四種語言一律不被抑制。
    # 跨症狀組合紅旗改成可以配對相鄰子句之後，這個缺口立刻變成系統性誤報：
    #   "my left leg feels a bit numb, my bladder is fine"  → cauda_equina(critical)
    #   "部屋が熱くて眠れませんでした、排尿は普通です"          → urosepsis(critical)
    # 兩句都是**病患明確講出那個部位沒問題**——正是政策唯一允許抑制的情況
    #（不是第三人稱、不是別部位誤配，那兩類本輪刻意保留）。
    # ⚠️ 不會造成漏報的理由（與 zh 那兩條同一套）：pattern 要求關鍵字之後的整段
    #   同一子句就是「(filler)* 正常/fine $」，帶任何症狀續字都不符 `$` 收尾
    #   （"is fine but it hurts"、「普通ですが痛いです」一律放行）；`_clause_after`
    #   的視窗只有 10 字，構不到別的子句；filler 不含 not/아니/không，所以
    #   「is not fine」「정상이 아니에요」也不會被當成否認。
    # ⚠️ en-US 的對應 pattern **刻意不存在**（2026-07-27 主 agent 移除）。
    # 曾經加過 `(?:is|feels|…)\s*(?:fine|normal|ok|…)$`，實測製造真漏報：
    #   "normally i pee fine, but since last night nothing comes out"        → 0 critical
    #   "usually my urine is normal, but today i cannot pass any urine at all" → 0 critical
    # 兩句都是教科書級尿滯留。根因是英文習慣把「平常是好的」放在**前一個子句**，
    # 部位詞（pee / urine）只出現在那個子句裡，一旦該出現位置被抑制，
    # 後面真正的主訴子句就沒有部位詞可以配對共現組 → 整句漏掉。
    # zh/ja/ko/vi 的同類 pattern 沒有這個問題（部位詞會在主訴子句再出現一次），
    # 所以保留。代價是 "my left leg feels numb, my bladder is fine" 仍會誤報
    # cauda_equina——依 2026-07-27 臨床拍板的「偏誤報」政策，這是可接受的一側。
    # 要加回來之前，先讓上面那兩句在測試裡通過。
    # ja-JP：「は普通です／は正常です／は大丈夫です」
    re.compile(r"^[はがもをに\s]*(?:特に\s*)?(?:普通|正常|大丈夫)(?:です|でした|だ)?[。\s]*$"),
    # ko-KR：「은 정상이에요／는 괜찮아요／는 문제없어요」
    re.compile(
        r"^[은는이가을를\s]*(?:정상|괜찮|문제\s?없|이상\s?없)"
        r"(?:이에요|이예요|입니다|아요|어요|습니다|해요|다)?[.\s]*$"
    ),
    # vi-VN：「thì bình thường／vẫn ổn」
    re.compile(r"^[\s,:]*(?:thì|là|vẫn)?\s*(?:bình thường|ổn|ổn định)[.\s]*$"),
)


# ── (1b) ja/ko 子句**句尾述語**否定 ────────────────────────
# 為什麼上面的 `_POST_NEGATION_CUES` 短視窗（10 字）不夠：ja/ko 是 SOV，極性由
# **句尾述語**決定，而述語可以離關鍵字很遠。2026-07-27 第三輪 Gate 雙向探針實測：
#   「排尿時にしみますが、睾丸が急に激しく痛むことはありません」→ critical（誤報）
#     ——「急に」到「ありません」隔了 10 字，短視窗差一點構不到。
#   「소변볼 때 따갑지만 고환이 갑자기 심하게 아프지는 않습니다」  → critical（誤報）
#     ——「아프지는 않습니다」插了主題助詞 는，字面比對接不上。
# 修法：另外檢查關鍵字**所在子句的結尾**是不是一個否定述語。子句邊界（含逗號）
# 已經把「別的子句的否定」隔開，所以這裡不需要距離上限。
#
# ⚠️ 危險方向（唯一的）：ja/ko 的可能形否定是**加強語氣**（痛くて歩けない／
#   참을 수 없이 아파요），把它當成否認就是規則層自己製造漏報。所以先用
#   `_POST_CUE_FALSE_FRIENDS` 擋一次，命中假朋友就整條放行。
_JA_CLAUSE_FINAL_DENIAL: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:あり|し)?ませ(?:ん|ぬ)(?:でした)?$"),
    re.compile(r"(?:こと|症状|訴え)?は?(?:あり|し)?ま?せん$"),
    re.compile(r"な(?:い|かった)(?:です|ん?です)?$"),
    re.compile(r"(?:無|な)し$"),
)
_KO_CLAUSE_FINAL_DENIAL: tuple[re.Pattern[str], ...] = (
    re.compile(r"않(?:습니다|아요|았어요|았습니다|아|았다|다)$"),
    re.compile(r"없(?:습니다|어요|었어요|었습니다|어|다|음)$"),
    re.compile(r"아니(?:에요|예요|야|다|었어요)$"),
)
# 只看子句尾這麼多字元就夠判斷述語（ja/ko 的否定述語都很短）；放太長會把子句中段
# 出現的 ない／없 也當成句尾述語。
_CLAUSE_FINAL_TAIL_CHARS = 14


def _clause_final_denial(text_lower: str, kw_start: int, kw_end: int) -> bool:
    """關鍵字所在子句是否以 ja/ko 的否定述語收尾（＝該關鍵字被否認）。

    ⚠️ 兩道防線都是為了「守衛不可以自己製造漏報」（實測踩過，見下）：

    (1) **述語範圍**：日文的 て/で 是接續形，會引入**新的述語**，其後的否定不屬於
        關鍵字。沒有這道檢查，「血尿があって心配ない」（有血尿、不擔心）會被判成
        「沒有血尿」——`_POST_NEG_STOPS` 早就為同一個理由收了て/で，這裡沿用。
    (2) **可能形否定假朋友**：「痛くて歩けません」「참을 수 없이 아파요」是**加強
        語氣**，不是否認（見 `_POST_CUE_FALSE_FRIENDS`）。
    """
    clause_start, clause_end = _clause_bounds(text_lower, kw_start)
    clause = text_lower[clause_start:clause_end].rstrip()
    if not clause:
        return False
    # (1) 關鍵字與句尾否定之間若隔著 て/で → 是另一個述語的否定，與本關鍵字無關。
    if any(ch in text_lower[kw_end:clause_end] for ch in "てで"):
        return False
    # (2) 加強語氣的可能形否定不算否認。
    if any(ff in clause for ff in _POST_CUE_FALSE_FRIENDS):
        return False
    tail = clause[-_CLAUSE_FINAL_TAIL_CHARS:]
    return any(
        p.search(tail) for p in (*_JA_CLAUSE_FINAL_DENIAL, *_KO_CLAUSE_FINAL_DENIAL)
    )


# ── (2) 時態否定：過去有過、現在已經好了 ──────────────────
# 必須同時滿足：關鍵字前的**同一子句**有過去時間詞，且其後的同一句話有痊癒詞，
# 且沒有復發詞。三個條件缺一不可。
# ⚠️ 詞表刻意排除裸「前 / ago / trước / 전에 / 前に」——真實扭轉病患講的正是
#    「兩小時前」「two hours ago」「二時間前に」「두 시간 전에」「hai tiếng trước」，
#    收了就會把最典型的急症句子當成過去式抹掉（不可逆的 under-triage）。
_PAST_MARKERS: tuple[str, ...] = (
    # zh-TW
    "以前", "之前", "從前", "過去", "以往", "小時候", "上次", "上個月", "上禮拜",
    "上星期", "去年", "前年", "幾年前", "多年前",
    # 2026-07-27 第三輪 Gate：「十年前睪丸曾經急性劇痛，開完刀之後就再也沒發作」
    # 誤觸發 critical。「年前／個月前」是**具體數字＋年月**的過去錨點，與必須保留
    # 命中的「兩小時前／五分鐘前」不衝突（那是急症的典型時間詞，刻意不收）。
    "年前", "個月前", "曾經", "當年",
    # en-US
    "used to", "in the past", "years ago", "months ago", "last year", "previously",
    "a long time ago",
    # ja-JP（「以前」「昔」；「前に」は二時間前に等と衝突するため不採用）
    # 「子供のころ／小さいころ」はひらがな表記も実測で出る（漢字だけでは取りこぼす）。
    "以前", "昔", "子供の頃", "子供のころ", "小さい頃", "小さいころ",
    "若い頃", "若いころ", "去年", "数年前", "年前", "ヶ月前", "か月前",
    # ko-KR（「예전」；「전에」は두 시간 전에と衝突するため不採用）
    "예전", "작년", "어렸을 때", "오래전", "몇 년 전", "년 전", "개월 전",
    # vi-VN（「trước đây / hồi trước」；裸 trước は hai tiếng trước と衝突）
    "trước đây", "hồi trước", "hồi xưa", "lúc trước", "năm ngoái",
    "năm trước", "tháng trước",
)
_RESOLVED_MARKERS: tuple[str, ...] = (
    # zh-TW（「已經好」不收——「已經好幾天了」會誤中）
    "好了", "痊癒", "沒事了", "不痛了", "恢復了", "治好", "緩解了", "消失了", "康復",
    # 2026-07-27 第三輪 Gate：「開完刀之後就再也沒發作」是最自然的「已解決」講法，
    # 卻不在表內。刻意收**完整片語**而不是裸「再也沒」——「痛到再也沒辦法走路」
    # 不可以被當成已解決（那是漏報方向）。
    "再也沒發作", "沒再發作", "不再發作", "再也沒有發作", "沒有再發作", "再也沒痛",
    # en-US（"no longer" 不收——"no longer bearable" 會誤中）
    "went away", "resolved", "cleared up", "got better", "all better", "fine now",
    "healed", "recovered", "stopped hurting", "not anymore",
    # ja-JP
    "治りました", "治った", "治って", "良くなりました", "よくなりました", "完治",
    # ko-KR
    "나았", "괜찮아졌", "좋아졌", "없어졌",
    # vi-VN
    "đã khỏi", "khỏi hẳn", "hết rồi", "đỡ hẳn", "không còn",
)
# 復發／持續：一出現就**不**抑制（fail-open：寧可誤報也不可把還在痛的病患抹掉）
_RECURRENCE_MARKERS: tuple[str, ...] = (
    "又", "再次", "再度", "復發", "這次", "現在還", "現在又", "還是很痛", "一直",
    "again", "came back", "this time", "still", "now it",
    "また", "再発", "今また",
    "다시", "또", "지금도", "아직",
    "lại", "vẫn còn", "tái phát",
)
_PAST_MARKER_LOOKBACK = 24
_RESOLVED_LOOKAHEAD = 40


# ── (3) 詢問／假設語氣 ────────────────────────────────
# (3a) 條件句：關鍵字前的同一子句有條件詞（五語言的條件詞都在子句開頭）。
#      en 刻意不收裸「if」——「I don't know if my testicle hurts is normal」是真的
#      在描述症狀；只收明確的假設框架。
_CONDITIONAL_MARKERS: tuple[str, ...] = (
    "如果", "假如", "萬一", "倘若", "假設", "假使",  # zh-TW（不收「要是」：「主要是」會誤中）
    "what if", "in case", "suppose", "hypothetically", "if i were", "if i had",
    "もし", "仮に",
    "만약", "만일",
    "nếu", "giả sử",
)
# (3b) 行政詢問：必須「詢問框架」與「掛號/科別問句」**同時**出現在同一句話裡。
#      ja/ko 是 SOV、詢問動詞在句尾，所以兩者都在整句範圍內找，不限前後。
#      單獨問「怎麼辦 / what should I do」**不算**——那是真的在求助。
_INQUIRY_FRAMES: tuple[str, ...] = (
    "想問", "請問", "請教", "問一下", "詢問", "想知道", "想了解",
    "want to ask", "wanted to ask", "like to ask", "just asking", "wondering about",
    # 2026-07-27 第三輪 Gate：「which clinic should i book if a testicle suddenly
    # becomes severely painful」誤觸發 critical。英文的行政詢問常常沒有「I want to
    # ask」這種前綴，而是直接用「should I book / where should I」開場——那正是
    # zh 的「請問…掛號」在英文裡的對應形狀。反向閘門（同句有當前發作證據就不抑制）
    # 仍然套用，所以真的在痛又順便問科別的病患不會被抹掉。
    "should i book", "should i register", "should i make an appointment",
    "do i need to book", "where should i", "who do i see", "who should i book",

    "聞きたい", "質問", "相談したい", "教えてください",
    "물어보", "질문", "궁금",
    "muốn hỏi", "cho hỏi",
)
_ADMIN_INQUIRY_TAILS: tuple[str, ...] = (
    "哪一科", "哪科", "什麼科", "哪個科", "掛號", "掛哪",
    "which doctor", "which department", "what specialist", "which clinic",
    "who should i see",
    "何科", "どの科", "どこの科",
    "무슨 과", "어느 과", "어떤 과", "과에 가",
    "khoa nào", "bác sĩ nào", "khám ở đâu",
)
# (3b-2) 「該怎麼辦／要去哪」式的**求助提問**標記。
#
# 2026-07-27 第四輪 Gate（對抗式探針，8 句真症狀中 7 句被抹掉）：條件詞單獨成立就
# 抑制是錯的——「X 的時候就會痛」是病患描述**真症狀**最常見的講法之一，而且「壓下去
# 會痛／走路會痛」正是睪丸扭轉的理學檢查發現：
#   "if i press on my testicle it hurts so much i almost pass out" → 抑制（漏報）
#   "if i walk my testicle is in severe pain"                      → 抑制（漏報）
#   「假如我一動睪丸就突然劇痛」「もし歩くと睾丸が激しく痛みます」                → 抑制（漏報）
#   「만약 걸으면 고환이 갑자기 심하게 아파요」「nếu tôi đi lại thì tinh hoàn đau dữ dội」→ 抑制
# 英文的 if 尤其糟：它同時是「假設」與「每當」，字面完全分不出來。
#
# 修法（**收窄**抑制）：條件句要抑制，必須同時是一個**在問該怎麼辦/去哪裡**的句子。
# 純假設提問全部帶這種標記（「要怎麼辦」「should i」「どうすれば」「어떻게 하나요」
# 「phải làm sao」），而「壓下去就會痛」這種症狀陳述一個都沒有。
# 依政策，剩下的殘餘誤報（真的在痛又順口問「這樣要怎麼辦」）留給急性伴隨症狀閘門，
# 接不住就讓它誤報——那是可逆的一側。
_ADVICE_QUESTION_MARKERS: tuple[str, ...] = (
    # zh-TW
    "怎麼辦", "該怎麼", "要怎麼", "如何處理", "打哪", "要打", "去哪", "找誰", "該不該",
    # en-US（"what if" 本身就是提問形式，同時也是條件詞）
    "what if", "what do i do", "what should i do", "what happens if",
    "should i", "do i need to", "where do i", "where should i", "who do i",
    # ja-JP
    "どうすれ", "どうしたら", "どうすべき", "どこに行け", "どこへ行け", "何科",
    # ko-KR
    "어떻게 하", "어떻게 해야", "어디로 가", "어디에 가", "어떡", "해야 하나요",
    # vi-VN
    "phải làm", "nên làm", "làm sao", "đi đâu", "khám ở đâu",
)
_SENTENCE_BREAKS: str = "。！？!?\n"
# (3c) 「當前發作證據」——語境守衛的**反向**閘門（2026-07-27 第三輪對抗式覆核）。
#
# 問題：行政詢問守衛（3b）與時態否定守衛（2）都只看「有沒有詢問/過去的形狀」，
# 不看「病患是不是**同時**在描述現在正在發生的事」。而 STT 逐字稿常常整段沒有
# 標點，`_sentence_around` 兩側各 80 字、逗號不切句 → 一句話裡的「請問」和
# 「哪一科」會把中間真正講出來的急症整段抹掉。實測（規則層直接跑）：
#   「請問我睪丸兩小時前突然劇痛還吐了，這要看哪一科」          → 抑制（漏報）
#   「醫生請問一下我今天早上睪丸突然很痛痛到吐我不知道要掛哪一科」→ 抑制（漏報）
# 病患**一邊描述症狀一邊問要掛哪一科**是院內 kiosk 最常見的真實情境，被守衛
# 吃掉是守衛自己製造 under-triage，最危險的方向。
#
# 修法：同一句裡若有「當前發作證據」，3b/2 一律不得抑制。
# 證據刻意只收兩類**具體**訊號，不收裸的急性/嚴重度詞：
#   (a) 時間錨點：今天早上／兩小時前／this morning／さっき／방금／sáng nay…
#   (b) 急性伴隨症狀：吐／噁心／走不動／冒冷汗／vomit／걷기 힘들…
# 為什麼不收急性/嚴重度詞（如「很痛」「severe」）：那會讓
# 「我想問睪丸很痛要看哪一科」「고환 통증이 심한 건 무슨 과에…」這類**純**行政
# 詢問重新變成 critical → 第 1 輪 aborted_red_flag（第二輪剛修好的 over-trigger
# 會整批回來）。時間錨點與伴隨症狀才是「這件事現在正在我身上發生」的證據。
# ⚠️ 鐵律：本表與**任何 critical trigger 關鍵字**必須字面互斥，否則
#   「我想問{trigger}要看哪一科」這種生成式反例會因為 trigger 自帶證據詞而失效。
#   由 test_red_flag_cooccurrence.py 的
#   `test_current_episode_markers_disjoint_from_critical_triggers` 結構性守住。
#
# 2026-07-27 第四輪：(a) 與 (b) 拆成兩個子表（`_CURRENT_EPISODE_MARKERS` 仍是兩者
# 的串接，內容與順序完全不變，結構性守衛與既有引用不受影響）。
# 理由：**條件句**（如果／もし／nếu…）裡的時間錨點很可能是**假設的時間**
# （「もし夜中に睾丸が激しく痛くなったら」＝如果半夜痛起來），拿它當「現在正在發生」
# 的證據會把純假設句放行；但 (b) 的急性伴隨症狀是病患**陳述出來的具體事實**
# （痛到吐／走不動），在條件句框架下仍然是「這件事現在正在我身上發生」的訊號。
# 所以行政詢問/時態否定用 (a)+(b)，條件句只用 (b)。見 `_hypothetical_or_admin_inquiry`。
_CURRENT_EPISODE_TIME_ANCHORS: tuple[str, ...] = (
    # ── (a) 時間錨點 ──
    # zh-TW（「小時前」涵蓋 兩小時前／兩個小時前；「分鐘前」同理）
    "小時前", "分鐘前", "今天", "今早", "今晚", "昨天", "昨晚", "昨夜",
    "剛剛", "剛才", "半夜", "凌晨", "早上", "傍晚", "這兩天", "這幾天",
    # 2026-07-27 第四輪 Gate：病患報「持續多久」而不是「幾點開始」——
    #「膀胱那邊，大概七八個小時了吧，脹到快要爆掉」的插入語不含任何既有錨點，
    # 於是 `_pairing_scope_ok` 判定它不是時間插入語 → urinary_retention 漏報。
    "個小時", "小時了", "個鐘頭", "鐘頭了",
    # en-US
    "hours ago", "hour ago", "minutes ago", "this morning", "this afternoon",
    "this evening", "tonight", "last night", "yesterday", "today", "just now",
    "midnight", "since this",
    # ja-JP（「今は」と衝突しないよう裸「今」は不採用）
    "時間前", "分前", "今朝", "今日", "昨日", "昨夜", "さっき", "夜中", "明け方",
    # ko-KR（「지금은 다 나았어요」と衝突しないよう裸「지금」は不採用）
    "시간 전", "분 전", "오늘", "어젯밤", "어제", "방금", "새벽", "아침",
    # vi-VN（「bây giờ」＝現在，與痊癒句衝突，故不採用）
    "tiếng trước", "phút trước", "sáng nay", "hôm nay", "hôm qua", "tối qua",
    "vừa nãy", "nửa đêm",
)
_CURRENT_EPISODE_ACUTE_COMPANIONS: tuple[str, ...] = (
    # ── (b) 急性伴隨症狀 ──
    # zh-TW（不收「腫」「發燒」「血尿」「尿不出」——它們本身就是 critical trigger 的
    #        子字串，收了會讓生成式反例失效，見上方鐵律）
    "吐", "噁心", "想吐", "走不動", "站不直", "冒冷汗", "昏倒", "暈倒",
    # en-US（2026-07-27 第四輪 Gate：原本只收過去式/進行式，接不到最自然的
    #  現在式原形「i throw up」「i almost pass out」——那是反向閘門，收得越全
    #  抑制越少，方向安全）
    "vomit", "throwing up", "threw up", "throw up", "throws up",
    "nausea", "nauseous",
    "can't walk", "cannot walk", "passed out", "pass out", "fainted",
    "cold sweat",
    # ja-JP
    "吐き気", "嘔吐", "吐い", "歩けません", "歩けない", "冷や汗",
    # ko-KR
    "토했", "구토", "메스꺼", "걷기 힘들", "못 걸", "식은땀",
    # vi-VN（「ói」は不採用：trigger「đau nhói / đau nhói ở tinh hoàn」の部分文字列に
    #  なり、生成式反例「trước đây {trigger} nhưng bây giờ đã khỏi hẳn」が
    #  「当該エピソードは現在進行中」と誤判定される。上の鉄則の実例。）
    "buồn nôn", "nôn", "ngất xỉu", "đổ mồ hôi lạnh",
)
# 對外維持單一名稱與相同內容/順序（結構性守衛 `test_current_episode_markers_
# disjoint_from_critical_triggers` 與其他引用都指向這個名字）。
_CURRENT_EPISODE_MARKERS: tuple[str, ...] = (
    _CURRENT_EPISODE_TIME_ANCHORS + _CURRENT_EPISODE_ACUTE_COMPANIONS
)


def _has_current_episode_evidence(sentence: str) -> bool:
    """句中是否有「這件事現在正在我身上發生」的具體證據（時間錨點/伴隨症狀）。"""
    return any(m in sentence for m in _CURRENT_EPISODE_MARKERS)


def _has_time_anchor(segment: str) -> bool:
    """段落中是否有**時間錨點**（今天早上／兩小時前／last night／昨夜／어젯밤／tối qua）。

    比 `_has_current_episode_evidence` 窄：不含急性伴隨症狀。給 `_clause_before` 的
    「否認列舉之後已經開始講這次發作」判定用——見該函式 (b) 的說明。
    """
    return any(m in segment for m in _CURRENT_EPISODE_TIME_ANCHORS)


def _has_acute_companion_evidence(sentence: str) -> bool:
    """句中是否有**急性伴隨症狀**（吐／走不動／vomit…）——條件句專用的較嚴證據。

    條件句裡的時間錨點可能是假設的時間（「もし夜中に…痛くなったら」），
    但「痛到吐」這種伴隨症狀是病患陳述出來的事實，假設框架下仍算現在正在發生。
    """
    return any(m in sentence for m in _CURRENT_EPISODE_ACUTE_COMPANIONS)

# 「整句」掃描的硬上限（見 `_sentence_around`）：STT 常整段無標點，不設限會讓
# 遠處的詢問詞湊成假的行政詢問 → 守衛製造漏報。
_SENTENCE_SCAN_CAP = 80
# 條件詞/過去詞的前掃停止字元：**含逗號**。理由：「如果我沒記錯，是兩小時前睪丸
# 突然劇痛」的「如果」屬於前一個子句，若不在逗號處停下就會把真急症抹掉。
_STRICT_CLAUSE_BREAKS: str = "。！？!?\n．;；:：、，,"


# ── 語意層的對話歷史（跨輪累積型 critical 的唯一來源）────────────
# 規則層只看「本輪這句話」，跨輪累積的 critical（前輪發燒 ＋ 本輪腰痛＝urosepsis）
# 天生偵測不到；那條路只有語意層走得通，而語意層要看得到歷史才行。
# `session_context["conversation_summary"]` 由 conversation_handler 寫入（最近 N 輪的
# 「病患：…／AI：…」多行字串）。本模組是消費端，必須對三種情況都安全：
#   (a) key 不存在 / None / 空字串 → 不加「對話摘要」段（既有行為，不可炸）；
#   (b) 上游哪天改寫成 list[dict] 之類的非字串 → 轉字串而不是 TypeError
#       （紅旗偵測炸掉＝整輪沒有紅旗，是不可逆的漏報，絕不能為了格式潔癖冒這個險）；
#   (c) 內容過長 → 截斷。截**頭**保尾：多輪摘要越後面越新，跨輪累積判斷靠的是
#       「前面提過什麼 ＋ 最新這句」，尾端資訊價值最高；頭部截斷處補省略記號讓 LLM
#       知道前面還有內容。
_MAX_CONVERSATION_SUMMARY_CHARS = 4000
_SUMMARY_TRUNCATION_MARK = "…（更早的對話已省略）\n"


def _format_conversation_summary(value: Any) -> str:
    """把 session_context["conversation_summary"] 正規化成可餵給 LLM 的字串。

    回傳空字串代表「沒有可用歷史」→ 呼叫端不加該段落。
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:  # noqa: BLE001 — 任何 __str__ 例外都不可炸掉紅旗偵測
            return ""
    text = value.strip()
    if not text:
        return ""
    if len(text) > _MAX_CONVERSATION_SUMMARY_CHARS:
        text = _SUMMARY_TRUNCATION_MARK + text[-_MAX_CONVERSATION_SUMMARY_CHARS:]
    return text


def _prose_lookback_for_severity(severity: str | None) -> int | None:
    """critical → 緊的散文視窗；其餘 → None（沿用既有 120 字行為，不改已驗收的邏輯）。"""
    if (severity or "").lower() == "critical":
        return _NEG_CRITICAL_PROSE_LOOKBACK
    return None


def _clause_before(
    text_lower: str, start: int, prose_lookback: int | None = None
) -> str:
    """取關鍵字出現位置 start 前、同一子句範圍的文字（供前置否定判定）。

    prose_lookback 不為 None 時（critical），額外限制「距離最近 list 分隔符以來的
    散文字元數」不得超過該預算，超過就截斷 → 遠處的否定線索構不到這個關鍵字。

    critical 另有兩道 2026-08-20 稽核 RF-2 補上的邊界（都只會讓否定範圍變短
    → 抑制變少 → 紅旗更容易命中，是安全的一側）：

    (a) **不歸零的總預算** `_NEG_CRITICAL_TOTAL_LOOKBACK_UNITS`——散文預算在每個
        頓號/逗號歸零，等於「否定作用範圍」實質無上限（只剩 120 字元的 runaway 上限）。

    (b) **list 分隔符後若已經是新的一次發作陳述，就切斷**。這是本輪真正承重的一條：
        「否認一串病史 ＋ 逗號 ＋ 真急症」是門診第一句話最常見的形狀，五種語言都是
          「我沒有糖尿病、沒有高血壓、沒有心臟病、沒有開過刀，昨晚睪丸突然劇痛痛到吐」
          "no diabetes, no high blood pressure, …, last night my testicle suddenly …"
          「糖尿病はありません、高血圧もありません、昨夜から精巣が急に激しく痛みます」
          「tôi không bị tiểu đường, không bị cao huyết áp, tối qua tinh hoàn đau dữ dội」
        而 (a) 那種**純長度**的上限對它完全無效——實測最近的那個否定詞只隔 5–7 個
        語素當量，任何合理的長度上限都攔不住（把上限收到 7 以下會把「沒有睪丸劇痛」
        這種真否認也放行，方向反了）。真正能分開兩者的不是距離而是**語意**：
        並列列舉的每一項都是裸症狀名詞，而「，昨晚睪丸突然劇痛」是一個帶**時間錨點**
        的新發作陳述。本檔早就有這個判準（`_CURRENT_EPISODE_TIME_ANCHORS`，
        3b/時態否定守衛的反向閘門），這裡沿用同一份表。
        ⚠️ 只用 (a) 時間錨點、**不用** (b) 急性伴隨症狀：後者含「吐」，而「嘔吐」
        正是並列否認列舉裡最常見的項目之一
        （`test_negated_enumeration_still_suppressed` 的語料就有），
        拿它當「新發作」的證據會把一整句「我都排除了」變成多個 critical 誤中止。
        時間錨點沒有這個同形問題：沒有人會在症狀列舉中間插「昨晚／last night」。
        為什麼不會把真否認變成誤報：切斷只丟掉**分隔符之前**的線索，分隔符與關鍵字
        之間的否定詞照樣搜得到——「我沒有血尿，今天早上也沒有尿不出來」切斷後的
        clause 是「今天早上也沒有」，仍含 cue，仍抑制。而「我沒有睪丸疼痛，只是來拿藥」
        的關鍵字在分隔符**之前**，這條規則根本碰不到它。
    """
    i = start - 1
    n = 0
    prose_run = 0
    total_units = 0
    while i >= 0 and n < _NEG_MAX_LOOKBACK and text_lower[i] not in _NEG_SCOPE_BREAKS:
        if prose_lookback is not None:
            if text_lower[i] in _NEG_LIST_SEPARATORS:
                # (b) 分隔符之後到關鍵字之間若已經是「這次發作」的陳述
                #     （時間錨點）→ 前面那串否認管不到它。
                if _has_time_anchor(text_lower[i + 1 : start]):
                    break
                prose_run = 0  # 並列列舉不吃預算（同一個否認下的多個症狀）
            else:
                # 語素當量計費：CJK 每字 1、拉丁/越南文每個空白（＝詞界）1、
                # 詞內字母 0。CJK 的計數與改用單位前完全相同，見 `_char_units`。
                prose_run += _char_units(text_lower[i])
                if prose_run > prose_lookback:
                    break
            # (a) 總預算（分隔符也計費，不歸零）
            total_units += _char_units(text_lower[i])
            if total_units > _NEG_CRITICAL_TOTAL_LOOKBACK_UNITS:
                break
        i -= 1
        n += 1
    clause = text_lower[i + 1 : start]
    # 轉折詞後重置：只看最靠近關鍵字的轉折詞之後那段
    for marker in _CONTRAST_MARKERS:
        pos = clause.rfind(marker)
        if pos != -1:
            clause = clause[pos + len(marker) :]
    return clause


def _clause_after(text_lower: str, end: int) -> str:
    """取關鍵字結束位置 end 後、同一子句短視窗的文字（供 ja/ko 後置否定判定）。"""
    j = end
    n = 0
    while j < len(text_lower) and n < _POST_NEG_MAX_AHEAD and text_lower[j] not in _POST_NEG_STOPS:
        j += 1
        n += 1
    return text_lower[end:j]


# 前置否定的假朋友總表 ＝ `_CUE_FALSE_FRIENDS`（各語言固定搭配）
# ∪ `_POST_CUE_FALSE_FRIENDS`（ja/ko 可能形否定的加強語氣，原本只用在**後置**檢查）。
#
# 為什麼要併入後者（2026-07-27 第四輪，實測漏報）：可能形否定在 ja/ko 是 SOV 語言最
# 常見的「痛到不能～」加強語氣，它可以出現在關鍵字的**任一側**：
#   「我慢できないほど痛くて、睾丸が急に腫れて痛みます」→ 前置 → 舊碼整句抹掉（漏報）
#   「左の精巣の痛みがひどくて歩けません」            → 後置 → 第三輪已擋
# 只在後置擋、前置不擋，等於同一個語意現象修了一半。
_PRE_CUE_FALSE_FRIENDS: tuple[str, ...] = tuple(
    dict.fromkeys(_CUE_FALSE_FRIENDS + _POST_CUE_FALSE_FRIENDS)
)


def _false_friend_spans(text: str, friends: tuple[str, ...]) -> list[tuple[int, int]]:
    """text 中所有假朋友的字面範圍 [start, end)。"""
    spans: list[tuple[int, int]] = []
    for ff in friends:
        i = text.find(ff)
        while i != -1:
            spans.append((i, i + len(ff)))
            i = text.find(ff, i + 1)
    return spans


# 假朋友可以**跨過關鍵字邊界**，所以比對假朋友時要多看關鍵字之後這麼多字元。
# 見 `_has_negation_cue` 的 tail 參數說明。
_FF_TAIL_LOOKAHEAD = 24
# 只有**不含 CJK/諺文**的假朋友（拉丁、越南文）可以跨過關鍵字邊界比對。
# 為什麼要這個限制（2026-07-27 第四輪 Gate 實測踩到）：中日韓沒有詞界，假朋友很容易
# 變成「否認句的前綴」——「沒有意識」是假朋友（＝失去意識，症狀本身），但
# 「我沒有意識不清」是**明確否認** urosepsis 的 trigger「意識不清」。允許它跨界比對就
# 會把這個否認整條放行 → 守衛在「明確否認」這唯一該抑制的情況下失效。
# 拉丁/越南文沒有這個問題：那裡的否定詞後面接的是**空白分隔的獨立詞**
# （no urine／not been able／không ra được），假朋友必然跨過關鍵字起點才比得到。
_STRADDLING_FALSE_FRIENDS: tuple[str, ...] = tuple(
    ff for ff in _PRE_CUE_FALSE_FRIENDS if not any(_is_cjk_char(c) for c in ff)
)


def _has_negation_cue(clause: str, tail: str = "") -> bool:
    """clause 內是否有「真的」否定線索——落在假朋友字面範圍內的命中不算。

    `tail`＝關鍵字**本身及其後**的一小段文字，只參與假朋友比對、不參與 cue 搜尋。
    沒有它就會有一整族假朋友結構上永遠比對不到（2026-07-27 第四輪 Gate 實測漏報）：
    `_clause_before` 回傳的是關鍵字**之前**的文字，於是像 "no urine"（cue "no " 在
    clause 尾端、"urine" 已經是關鍵字本身）這種**橫跨關鍵字邊界**的假朋友永遠落在
    clause 之外 →「my lower belly is rock hard because no urine will come out」
    被當成否認整句抹掉（urinary_retention critical 漏報）。
    方向性不變：假朋友只會讓守衛**少**抑制。

    ⚠️ 判準從「假朋友**開頭**等於命中位置」放寬成「命中位置**落在**假朋友範圍內」
    （與 `_has_post_negation_cue` 一致）。理由：否定詞不見得是固定搭配的第一個字元
    ——英文 "cannot walk" 的 cue 是 `not `（第 3 字元起）、日文「我慢できない」的
    cue 是「ない」（第 5 字元起）、韓文「참을 수 없이」的 cue 是「없」（第 6 字元起）。
    舊的 startswith 判準對這三種語言的假朋友**結構上永遠命中不到**，於是那三語的
    加強語氣句一律被當成否認整句抹掉（漏報）。

    方向性（安全關鍵）：假朋友只會讓否定守衛**少抑制** → 紅旗**更容易**命中。
    所以放寬判準的唯一風險是誤報，而依 2026-07-27 臨床拍板（紅旗規則層偏誤報：
    誤中止可逆、漏報不可逆），誤報是可接受的一側。
    """
    spans: list[tuple[int, int]] | None = None
    for cue in _NEGATION_CUES:
        pos = clause.find(cue)
        while pos != -1:
            if spans is None:  # 有 cue 才付掃描成本
                # 子句內的假朋友：全表比對。
                spans = _false_friend_spans(clause, _PRE_CUE_FALSE_FRIENDS)
                if tail:
                    # 跨關鍵字邊界的假朋友：只認拉丁/越南文，且必須真的跨過邊界
                    # （span 尾端超出 clause）。兩者共用同一組索引。
                    spans += [
                        (s, e)
                        for s, e in _false_friend_spans(
                            clause + tail, _STRADDLING_FALSE_FRIENDS
                        )
                        if e > len(clause)
                    ]
            if not any(s <= pos < e for s, e in spans):
                return True
            pos = clause.find(cue, pos + 1)
    return False


def _strict_clause_before(text_lower: str, start: int, limit: int) -> str:
    """關鍵字前、**含逗號也切斷**的短子句（供條件詞/過去時間詞判定）。"""
    i = start - 1
    n = 0
    while i >= 0 and n < limit and text_lower[i] not in _STRICT_CLAUSE_BREAKS:
        i -= 1
        n += 1
    return text_lower[i + 1 : start]


def _sentence_after(text_lower: str, end: int, limit: int) -> str:
    """關鍵字後、同一**句**（只在句末標點切斷，逗號不切）的文字。"""
    j = end
    n = 0
    while j < len(text_lower) and n < limit and text_lower[j] not in _SENTENCE_BREAKS:
        j += 1
        n += 1
    return text_lower[end:j]


def _sentence_around(text_lower: str, start: int, end: int) -> str:
    """關鍵字所在的整句（供 SOV 語言的句尾詢問動詞判定）。

    兩側都加硬上限 `_SENTENCE_SCAN_CAP`：STT 逐字稿常常整段沒有標點，不設限的話
    一句超長 run-on 裡遠處的「想問」和「哪一科」會被湊成行政詢問，把中間真正講出來
    的症狀抹掉（那是守衛自己製造漏報，最危險的方向）。
    """
    i = start
    limit_i = max(0, start - _SENTENCE_SCAN_CAP)
    while i > limit_i and text_lower[i - 1] not in _SENTENCE_BREAKS:
        i -= 1
    j = end
    limit_j = min(len(text_lower), end + _SENTENCE_SCAN_CAP)
    while j < limit_j and text_lower[j] not in _SENTENCE_BREAKS:
        j += 1
    return text_lower[i:j]


def _post_denial_tail(text_lower: str, end: int) -> bool:
    """關鍵字之後的同一子句整段就是一句否認（「…倒是沒有」「: none」「thì không」）。"""
    after = _clause_after(text_lower, end)
    if not after.strip():
        return False
    return any(p.match(after) for p in _POST_DENIAL_TAIL_PATTERNS)


def _past_resolved(text_lower: str, start: int, end: int) -> bool:
    """時態否定：過去有過 ＋ 已經好了 ＋ 沒有復發詞 → 視為否定。"""
    before = _strict_clause_before(text_lower, start, _PAST_MARKER_LOOKBACK)
    if not any(m in before for m in _PAST_MARKERS):
        return False
    after = _sentence_after(text_lower, end, _RESOLVED_LOOKAHEAD)
    if any(m in after for m in _RECURRENCE_MARKERS):
        return False  # 復發／仍在痛 → 絕不抑制
    if not any(m in after for m in _RESOLVED_MARKERS):
        return False
    # 同句還有「當前發作證據」（今天早上／剛剛／吐…）→ 不是純過去式敘述，不得抑制。
    # 「以前…現在完全好了」不含這類詞（「現在/今は/지금은/bây giờ」刻意不在表內），
    # 故既有的時態否定抑制完全不受影響，見 `_CURRENT_EPISODE_MARKERS` 註解。
    return not _has_current_episode_evidence(_sentence_around(text_lower, start, end))


def _hypothetical_or_admin_inquiry(text_lower: str, start: int, end: int) -> bool:
    """詢問／假設語氣：條件句，或「詢問框架 ＋ 掛號科別問句」同時成立。

    ⚠️ 2026-07-27 第四輪收窄（臨床拍板「紅旗規則層偏誤報」）：
    **條件句分支現在也套用反向閘門**，先前只有行政詢問分支有。舊行為是條件詞一
    出現就整句抹掉，於是「醫生如果我今天早上睪丸突然劇痛痛到吐要怎麼辦」這種
    「**已經在發作** ＋ 用假設語氣包裝」的 STT 逐字稿（kiosk 現場很常見）被規則層
    自己抹成漏報。

    條件句用的是**較嚴**的證據（只算急性伴隨症狀，不算時間錨點）：條件句裡的
    時間可能本身就是假設的（「もし夜中に睾丸が激しく痛くなったら」＝如果半夜痛
    起來），拿它當現在發作的證據會把純假設句整批放行；而「痛到吐／走不動」是
    病患陳述出來的具體事實，即使包在假設框架裡也代表事情正在發生。
    """
    sentence = _sentence_around(text_lower, start, end)
    before = _strict_clause_before(text_lower, start, _PAST_MARKER_LOOKBACK)
    asks_for_advice = any(
        m in sentence
        for m in (
            *_ADVICE_QUESTION_MARKERS,
            *_ADMIN_INQUIRY_TAILS,
            *_INQUIRY_FRAMES,
        )
    )
    if any(m in before for m in _CONDITIONAL_MARKERS):
        # 條件詞**單獨**不足以抑制（見 `_ADVICE_QUESTION_MARKERS`）：
        # 必須同時是一個在問「該怎麼辦／要去哪」的句子，才算純假設。
        return asks_for_advice and not _has_acute_companion_evidence(sentence)
    # 英文的裸「if」：只有**子句開頭**的 if 才是條件句的從屬連接詞。
    # 2026-07-27 第三輪 Gate：「if my testicle ever hurts acutely, should i call
    # the clinic first」是純假設提問，卻因為表內刻意不收裸 if 而觸發 critical。
    # 而註解裡擔心的反例（"I don't know **if** my testicle hurts"、"wondering if…"）
    # 的 if 一律出現在**子句中段**（前面有 know / wonder / see 等動詞），
    # 用「子句開頭」這個位置條件就能精準分開，不必整個放棄裸 if。
    if before.lstrip().startswith("if "):
        return asks_for_advice and not _has_acute_companion_evidence(sentence)
    if not (
        any(f in sentence for f in _INQUIRY_FRAMES)
        and any(t in sentence for t in _ADMIN_INQUIRY_TAILS)
    ):
        return False
    # 「請問我睪丸兩小時前突然劇痛還吐了，這要看哪一科」＝一邊描述當前症狀一邊
    # 問掛號科別，是院內 kiosk 最常見的真實情境，**不是**純行政詢問 → 不得抑制。
    return not _has_current_episode_evidence(sentence)


def _occurrence_negated(
    text_lower: str, start: int, kw_len: int, prose_lookback: int | None = None
) -> bool:
    """單一關鍵字出現位置是否「不是病患現在的症狀陳述」。

    涵蓋：前置否定（zh/en/vi）、後置否定（ja/ko 詞表 + zh/en/vi 子句尾否認）、
    時態否定（以前有、現在好了）、詢問/假設語氣（如果…／我想問…要看哪一科）。
    """
    end = start + kw_len
    before = _clause_before(text_lower, start, prose_lookback)
    if _has_negation_cue(before, text_lower[start : start + _FF_TAIL_LOOKAHEAD]):
        return True
    after = _clause_after(text_lower, end)
    if _has_post_negation_cue(after):
        return True
    if _post_denial_tail(text_lower, end):
        return True
    if _clause_final_denial(text_lower, start, end):
        return True
    if _past_resolved(text_lower, start, end):
        return True
    return _hypothetical_or_admin_inquiry(text_lower, start, end)


def _keyword_present_non_negated(
    keyword: str, text_lower: str, prose_lookback: int | None = None
) -> bool:
    """關鍵字是否有「非否定」出現。全部出現都被否定 → False（抑制誤觸）。"""
    kw = (keyword or "").lower()
    for idx in _iter_keyword_occurrences(kw, text_lower):
        if not _occurrence_negated(text_lower, idx, len(kw), prose_lookback):
            return True  # 有一個非否定出現即觸發（保留 fail-open）
    return False  # 沒出現，或每個出現都被否定


# ══════════════════════════════════════════════════════════════════
# 共現組比對（部位詞 × 急性/嚴重度詞）
# ══════════════════════════════════════════════════════════════════
# 為什麼需要這一層（2026-07-27 第三輪對抗式覆核，詳見 shared.py 該旗標註解 (C)）：
# 單詞 trigger 只能是「相鄰子字串」，但 zh/ja/ko/vi 的真實語序會在部位詞與修飾詞
# 之間插入時間、方位、程度——「睪丸**兩個小時前**突然劇痛」裡的「睪丸突然」根本
# 不相鄰，規則層 0 命中。而 e2e persona 台詞剛好是相鄰語序，所以測試一直是綠的：
# **情境台詞與關鍵字互相配適，測到的是實作不是行為。**
#
# 共現組不看相鄰，只看「同一子句內共現 ＋ 距離上限」，因此同時解掉兩個方向：
#   under-trigger：語序與插入語不再影響命中；
#   over-trigger：兩張表都不含裸「痛」，慢性主訴（有部位、無急性/嚴重度詞）仍不命中。
#
# 子句（而非整句）為配對範圍的理由：逗號也切。整句配對會讓
# 「我眼睛突然很痛，睪丸沒事」把前半句的「突然/很痛」配到後半句的「睪丸」上
# ——跨子句配對是這個結構唯一的新誤報面，用子句邊界直接關掉。
# 代價是「睪丸從昨天開始不舒服，今天早上突然劇痛」這種跨子句敘述規則層不接，
# 由語意層承接（規則層本來就是 fallback，不是唯一防線）。
#
# 否定/時態/假設/行政詢問守衛的套用方式：**部位詞出現位置、急性詞出現位置、
# 以及兩者涵蓋的整段跨度**三者都必須非否定，任一被判否定就不算命中。
# 跨度那一項是必要的——「睪丸劇痛倒是沒有」的否認尾巴接在**急性詞之後**，
# 只檢查部位詞的話（其後緊接的是「劇痛倒是沒有」，不符子句尾否認的形狀）會漏擋。
def _clause_bounds(text_lower: str, pos: int) -> tuple[int, int]:
    """pos 所在子句的 [start, end)（`_STRICT_CLAUSE_BREAKS`：句末標點與逗號都切）。"""
    i = pos
    while i > 0 and text_lower[i - 1] not in _STRICT_CLAUSE_BREAKS:
        i -= 1
    j = pos
    n = len(text_lower)
    while j < n and text_lower[j] not in _STRICT_CLAUSE_BREAKS:
        j += 1
    return i, j


# 配對距離上限——單位是**語素當量**（見 `_span_units`），不是裸字元。
# 中日韓一個字元約等於一個語素（「兩個小時前」＝5 字＝5 單位），拉丁/越南文一個詞
# 才等於一個語素（"since two hours ago" ＝19 字元，但只有 4 單位）。
#
# 為什麼不是「依書寫系統分兩檔字元數」（2026-07-27 第三輪 Gate 推翻的前一版做法）：
# 兩檔（CJK 24 字 / 拉丁 30 字元）是拿字元去近似語素，近似得不夠，實測直接漏報——
#   "my testicle, about ninety minutes ago, became excruciating"（35 字元 > 30）
#   "tinh hoàn bên phải của tôi từ lúc nửa đêm bỗng nhiên đau dữ dội"（48 > 30）
#   "bìu bên trái khoảng một tiếng trước sưng lên và đau đột ngột"（49 > 30）
# 越南文尤其嚴重：它以**音節**分寫，一個語意單位動輒 2–3 個空白分隔的音節，
# 用字元計費等於對越南文病患系統性地收緊到只剩 3–4 個詞的視窗。
# 改用語素當量之後，同一個常數對五種語言代表同一件事，也不必再維護兩檔的比例。
#
# ⚠️ 為什麼是 24 而不是更緊（明文記下這個取捨，別再有人來收緊）：
# 收到 16 確實能擋掉下面那句韓文殘餘誤報（相距 17 單位），但同時會切掉語意完全正確的
#   「예전에 고환이 아팠다가 나았는데 오늘 아침부터 갑자기 심하게 아파요」
#   （舊病史 ＋ 今天復發）——那是**漏報**。
# 距離本身分不出「隔著別的部位」與「隔著病史敘述」，兩者在長度上是同一件事；
# 要分開只能引進通用部位詞表，而那張表反過來會把「睪丸和肚子都突然很痛」抹掉
# （部位詞夾在中間）——又是一個漏報。
# 依本檔既有的 critical 取捨（見 `_NEG_CRITICAL_PROSE_LOOKBACK`）：kiosk 情境下
# 誤報＝護理師走一趟（可逆），漏報＝真扭轉繼續坐著等（不可逆）→ 取寬。
# 殘餘誤報（「고환은 괜찮은데 오늘 아침부터 배가 심하게 아파요」＝別的部位急性痛
# ＋ 同一子句 ＋ 無標點）記在 test_red_flag_cooccurrence.py 的
# `test_known_residual_...`，語意層仍獨立把關。
_COOCCURRENCE_WINDOW_UNITS = 24

# ── 插入語子句（唯一允許跨子句配對的例外）────────────────────
# 預設的配對範圍是「同一子句」（逗號也切），那條規則擋掉的是真正的跨子句誤配
# 「我眼睛突然很痛，睪丸沒事」。但它同時把**插入語**切斷了，而插入語兩側講的
# 其實是同一件事（2026-07-27 第三輪 Gate 雙向探針，五語言通病、不是英文特例）：
#   "my testicle, about ninety minutes ago, became excruciating"
#   「睪丸痛，今天早上開始的，很嚴重」
# 例外條件刻意收得很窄——site 與 acuity 之間夾的**每一個完整子句**都必須是
# 「短且自帶當前發作證據」（時間錨點或急性伴隨症狀）的片語，且最多兩個。
# 為什麼這樣就安全：`_clause_bounds` 要擋的那類誤配（「我眼睛突然很痛，睪丸沒事」）
# 兩個詞落在**相鄰**子句，中間夾著 0 個完整子句 → 不符合「至少一個插入語」→ 仍被擋。
# 2026-07-27 第四輪 Gate：上限從 8 放寬到 14 語素當量。8 是憑感覺定的，實測把真人
# 最常見的插入語切掉 → critical 漏報（雙向探針）：
#   「我的睪丸，就是剛剛在停車場的時候，忽然痛到冒冷汗」（插入語 11 單位）
#   「陰嚢のあたりが、さっきトイレに行ったあとで、急にひどく痛くなりました」（13 單位）
# 兩句的插入語都自帶當前發作證據（剛剛／さっき），語意上明確是同一件事。
# 放寬只影響「插入語**必須自帶當前發作證據**」這條仍然成立的前提下的長度，
# 誤配風險沒有質變（要誤配得先有一個 14 字內、又剛好含時間錨點的插入語）。
_PARENTHETICAL_MAX_UNITS = 14
_PARENTHETICAL_MAX_SEGMENTS = 2


def _pairing_scope_ok(
    text_lower: str,
    s0: int,
    s1: int,
    a0: int,
    a1: int,
    cross_clause: bool = False,
) -> bool:
    """site 與 acuity 是否在同一配對範圍內（同一子句，或只隔著時間插入語）。

    `cross_clause=True`（由共現組自行宣告）額外允許**相鄰子句**（`middles` 為空）
    配對。中間夾了完整子句時**不會**因為 `cross_clause` 而放行——那一路仍然要過下方
    的插入語條件（≤14 語素當量 ＋ 自帶當前發作證據，最多 2 段）。

    ⚠️ **「哪些組開了」的權威是 `prompts/shared.py` 共現組定義裡的 `cross_clause`
    這個 key 本身，不是這段 docstring**——這裡只記判準，實際開關要去查資料。
    2026-08-21 現況（會變）：`urinary_x_systemic_infection`(urosepsis)／
    `bladder_dysfunction_x_neuro_deficit`(cauda_equina)／`void_x_obstruction`
    (urinary_retention，2026-07-27 為英文語序開的)／`urine_x_heavy_blood`
    (gross_hematuria_heavy，2026-08-21 RF-5 開的) **四組開**；
    `site_x_acuity`(testicular_pain_severe) 與 `urine_x_blood_present`
    (gross_hematuria high) **沒開**。

    判準是「**這兩個軸是不是兩個不同的觀察**」，不是紅旗的臨床分類名稱：
      - 兩個不同的觀察 → 病患本來就會講成相鄰兩句，開。
          「我發燒到三十九度，而且小便的時候很痛」（全身感染 ＋ 泌尿症狀）
          「腰痛得很厲害，兩隻腳越來越沒力，昨天開始尿失禁」（神經缺損 ＋ 膀胱功能）
          「我今天小便，然後有很多血塊」（排尿這件事 ＋ 尿裡有血塊）
        ——實測有標點版全漏、去掉標點才命中（前兩句 2026-07-27 第四輪 Gate 雙向探針，
        第三句是 2026-08-21 RF-5 的 P0 漏報）。
      - **同一個部位 × 那個部位的嚴重度** → 不開：跨子句會把「我眼睛突然很痛，
        睪丸沒事」配起來。`site_x_acuity` 是唯一純粹這一型的組。
    ⚠️ 本段**前一版**寫的是「site×acuity 型紅旗（睪丸扭轉／尿滯留／血尿）維持不開」
    ——那個敘述在寫下時就已經與資料互斥（`void_x_obstruction` 早於它三週就開了），
    別再拿紅旗屬於哪一類去推它開沒開。
    """
    lo_end, hi_start = (s1, a0) if a0 >= s1 else (a1, s0)
    between = text_lower[lo_end:hi_start]
    if not any(ch in _STRICT_CLAUSE_BREAKS for ch in between):
        return True  # 同一子句（最常見的情況）
    # 頭尾兩片是 site / acuity 各自子句的殘段；中間的才是完整的插入語子句。
    pieces = re.split(f"[{re.escape(_STRICT_CLAUSE_BREAKS)}]", between)
    middles = [p.strip() for p in pieces[1:-1]]
    middles = [p for p in middles if p]
    if cross_clause and not middles:
        # 相鄰子句（中間沒有夾任何完整子句）→ 跨症狀組合紅旗允許配對。
        # 距離仍受共現組的 window 上限約束（呼叫端已檢查），所以不會把整段話串起來。
        return True
    if not middles or len(middles) > _PARENTHETICAL_MAX_SEGMENTS:
        return False
    return all(
        _span_units(p) <= _PARENTHETICAL_MAX_UNITS
        and _has_current_episode_evidence(p)
        for p in middles
    )


def _cooccurrence_matches(
    group: dict[str, Any],
    text_lower: str,
    prose_lookback: int | None = None,
    guard_on: bool = True,
) -> tuple[str, str] | None:
    """共現組是否命中；回傳 (部位詞, 急性詞) 原文，未命中回 None。

    guard_on=False（kill-switch 關閉）→ 只做共現與距離判定，不套否定守衛，
    與單詞 trigger 在 kill-switch 下的行為一致（詞邊界仍生效）。
    """
    sites: list[str] = [t for t in group.get("site_terms", []) if t]
    acuities: list[str] = [t for t in group.get("acuity_terms", []) if t]
    if not sites or not acuities:
        return None
    # group 若明示 window 就用它（覆寫預設），否則用語素當量的統一上限。
    window = int(group.get("window") or _COOCCURRENCE_WINDOW_UNITS)
    # 跨症狀組合型紅旗才允許相鄰子句配對（見 `_pairing_scope_ok`）。
    cross_clause = bool(group.get("cross_clause"))

    # 先把急性詞的出現位置一次算完（部位詞通常較少，內圈掃描成本較低）
    acuity_hits: list[tuple[int, int, str]] = []
    for term in acuities:
        low = term.lower()
        for idx in _iter_keyword_occurrences(low, text_lower):
            acuity_hits.append((idx, idx + len(low), term))
    if not acuity_hits:
        return None

    for site in sites:
        site_low = site.lower()
        for s0 in _iter_keyword_occurrences(site_low, text_lower, both_edges=True):
            s1 = s0 + len(site_low)
            clause_start, clause_end = _clause_bounds(text_lower, s0)
            if guard_on and _occurrence_negated(
                text_lower, s0, s1 - s0, prose_lookback
            ):
                continue
            for a0, a1, acuity in acuity_hits:
                if (a0 < clause_start or a1 > clause_end) and not _pairing_scope_ok(
                    text_lower, s0, s1, a0, a1, cross_clause
                ):
                    continue  # 跨子句且不是時間插入語 → 不配對
                # 距離以「兩詞之間那段文字的語素當量」衡量（見 `_span_units`）：
                # CJK 每字 1、拉丁/越南文每個空白分隔的詞 1。這樣同一個上限對
                # 五種語言代表同一件事，不必再依書寫系統分檔調參。
                between = (
                    text_lower[s1:a0] if a0 >= s1 else text_lower[a1:s0]
                )
                if _span_units(between) > window:
                    continue
                if guard_on:
                    if _occurrence_negated(text_lower, a0, a1 - a0, prose_lookback):
                        continue
                    span_start = min(s0, a0)
                    span_end = max(s1, a1)
                    if _occurrence_negated(
                        text_lower, span_start, span_end - span_start, prose_lookback
                    ):
                        continue
                return site, acuity
    return None


def _keyword_negated_only(
    keyword: str, text_lower: str, prose_lookback: int | None = None
) -> bool:
    """關鍵字有出現、但每個出現都被否定 → True（供語意層否定幻覺後過濾）。"""
    if not _keyword_in_text(keyword, text_lower):
        return False
    return not _keyword_present_non_negated(keyword, text_lower, prose_lookback)


# ── 目錄 severity floor（防語意層把 critical 自評降級）──────────
# 問題：語意層(LLM)自評 severity 可能低於內建目錄定義（實測 testicular_pain_severe
# 目錄=critical 卻被語意層評 high → 未達 abort 門檻 → 真正 under-triage）。
# 修法：命中內建 catalogue 的紅旗，severity 取 max(LLM 自評, 目錄定義)（只升不降）。
# 安全性：目錄 severity 是該紅旗的臨床嚴重度下限，flooring 是 fail-open 方向。
_SEVERITY_RANK: dict[str, int] = {"medium": 1, "high": 2, "critical": 3}
_CANONICAL_CATALOG_SEVERITY: dict[str, str] = {
    flag["canonical_id"]: flag["severity"] for flag in URO_RED_FLAGS
}

# 共現組以 canonical_id 查表（而不是塞進 rule dict）：DB 的 red_flag_rules 沒有
# 對應欄位，若只從 `_get_fallback_rules` 帶出來，一旦生產環境哪天 seed 了規則表，
# 規則層就會退回「只有相鄰複合詞」的舊行為——那正是本輪要修掉的漏報。
# 用 canonical_id 查表則兩條路徑（DB rule / 內建 fallback）行為一致，
# 與 `_floor_severity_to_catalog` 同樣是「目錄定義的臨床下限，只加強不削弱」。
_CANONICAL_COOCCURRENCE: dict[str, list[dict[str, Any]]] = {
    flag["canonical_id"]: list(flag.get("trigger_cooccurrence") or [])
    for flag in URO_RED_FLAGS
    if flag.get("trigger_cooccurrence")
}


def _floor_severity_to_catalog(canonical_id: str, llm_severity: str) -> str:
    """命中目錄的紅旗，severity 不得低於目錄定義（只升不降）。"""
    catalog = _CANONICAL_CATALOG_SEVERITY.get(canonical_id)
    llm = (llm_severity or "medium").lower()
    if catalog and _SEVERITY_RANK.get(catalog, 0) > _SEVERITY_RANK.get(llm, 0):
        return catalog
    return llm


# ── 否定幻覺後過濾（涵蓋語意層，A1 只修規則層的延伸）────────────
# 問題：規則層 A1 已否定感知，但語意層(LLM)仍會對「病患明確否認的症狀」幻覺紅旗
# （沒有血尿 → gross_hematuria、血尿はありません → 肉眼的血尿），且 merge 不會用否定
# 邏輯反向抑制語意層。修法：merge 後，若某 alert 的 canonical 關鍵字在文中「出現但全被
# 否定、且無任一非否定出現」→ 該 alert 是否定幻覺 → 抑制。
# 安全性（fail-open）：(a) 規則層真命中一定有非否定出現 → 不被抑制；(b) 語意層純情境推論
# （關鍵字根本不在文中，如描述睪丸扭轉未說「扭轉」）→ 關鍵字不在文中 → 不被抑制；
# 只殺「病患把該症狀名講出來、但每次都在否定句裡」的幻覺。
def _canonical_keywords(flag: dict[str, Any]) -> list[str]:
    kws: list[str] = [kw for kw in flag.get("triggers", []) if kw]
    for lang_kws in (flag.get("triggers_by_lang") or {}).values():
        kws.extend(kw for kw in lang_kws if kw)
    return kws


_CANONICAL_KEYWORDS: dict[str, list[str]] = {
    flag["canonical_id"]: _canonical_keywords(flag) for flag in URO_RED_FLAGS
}


# 目錄 title（含各語言 display title）→ canonical_id 反查表。
# 兩個用途：
#   (1) 語意層把 LLM 回的 title 解回 canonical_id（`_semantic_detect`）；
#   (2) DB 規則的 `canonical_id` 為 NULL 時，用 rule.name 把它救回來（`_load_rules`，
#       2026-08-20 稽核 D-6）。沒有 (2) 的話，canonical_id 會 fallback 成 rule.name，
#       而共現組是以 canonical_id 查表的 → 整個共現層對那條規則靜默失效，
#       規則層退回「只有相鄰複合詞」的舊行為（那正是 2026-07-27 量到 60/61 漏報的形狀）。
def _build_title_to_canonical() -> dict[str, str]:
    table: dict[str, str] = {}
    for flag in URO_RED_FLAGS:
        cid = flag["canonical_id"]
        table[normalize_canonical_id(flag["title"])] = cid
        for display in (flag.get("display_title_by_lang") or {}).values():
            table[normalize_canonical_id(display)] = cid
    return table


_TITLE_TO_CANONICAL: dict[str, str] = _build_title_to_canonical()


def _canonical_denied_in_text(canonical_id: str, text_lower: str) -> bool:
    """canonical 的關鍵字在文中出現但全被否定（且無任一非否定出現）→ 是否定幻覺。

    critical canonical 沿用與規則層同一組緊散文視窗（見
    `_NEG_CRITICAL_PROSE_LOOKBACK`）：抑制門檻在兩層一致，才不會出現「規則層認為
    病患有講、語意層的後過濾卻把它殺掉」這種層間不一致。
    """
    kws = _CANONICAL_KEYWORDS.get(canonical_id) or []
    if not kws:
        return False
    prose = _prose_lookback_for_severity(_CANONICAL_CATALOG_SEVERITY.get(canonical_id))
    if any(_keyword_present_non_negated(k, text_lower, prose) for k in kws):
        return False  # 有非否定出現 → 症狀被肯定 → 不抑制
    return any(_keyword_negated_only(k, text_lower, prose) for k in kws)


# ── 語意分析系統提示詞 ───────────────────────────────────
# NOTE: Critical/High/Medium 情境清單與 title 對齊段落都從 shared.URO_RED_FLAGS 動態渲染,
# 避免語意層 prompt 與 _get_fallback_rules 及 DB 規則漂移(P2-E 修復)。
_SEMANTIC_SYSTEM_PROMPT = f"""你是具急診與泌尿科分流經驗的臨床安全偵測助理，任務是從病患對話中辨識需要高度警覺的紅旗症狀，協助數位問診系統提早提醒醫護優先處理。

## 你的角色
- 你是紅旗偵測器，不是最終診斷醫師。
- 目標是辨識「可能需要優先處理、急診評估、或立即提醒醫師」的訊號。
- 不可憑空推測未被對話支持的紅旗。
- 若資訊不足但高度可疑,請仍輸出該紅旗,但嚴重度降一階並在 description 中註明資訊不足。
- 若沒有足夠證據,寧可回 {{"alerts": []}},也不要誤報。

## 需重點辨識的泌尿科高風險情境（系統內建目錄）
{render_red_flags_by_severity()}

### 其他 Critical 情境（不限於上方內建目錄）
- 敗血症/嚴重感染：發燒合併寒顫、發燒合併側腹痛/腰痛、意識改變或虛弱低血壓描述
- 急性尿路阻塞：完全尿不出來、明顯脹痛且無法排尿、已知攝護腺問題急遽惡化
- 神經學警訊：會陰麻木、下肢無力合併新發尿失禁或背痛（疑馬尾症候群/脊髓壓迫）

### 其他 High 情境
- 排尿困難合併腰痛發燒
- 劇烈側腹痛放射至鼠蹊/下腹、合併噁心嘔吐（疑腎結石併感染或阻塞）
- 骨頭疼痛（可能骨轉移）
- 持續嘔吐無法進食喝水、明顯虛弱
- 高齡、吸菸史或泌尿癌症病史合併上述任一症狀（僅在對話有提及時）

### Medium（中等，需補問與人工複核）
- 反覆尿路感染
- 持續性排尿困難逐漸惡化
- 年長男性下泌尿道症狀急遽變化
- PSA 指數異常升高（若有提及）

## 判斷原則
1. 只依據對話內容判斷，不可外推至未被病人明確陳述的症狀。
2. 若症狀為病人明確陳述，可視為證據；模糊描述（「有點不舒服」）不足以直接判為高風險，除非有其他佐證。
3. 若同時出現多個中度警訊，整體風險可上修一階。
4. 若為高度可疑但資訊不足，降一階處理為 medium，並在 description 中註明需補問。
5. 寧可過度警示真正的危急情境，也不要遺漏；但不可把普通下泌尿道症狀一律判為紅旗。
6. 不可因單一模糊詞就升到 critical。

## title 命名對齊（重要，影響系統去重）
本系統的規則比對層會先偵測以下內建紅旗；若你的語意判斷落在同一類情境，**請使用完全相同的 title 名稱**，讓系統可以把規則層與語意層的命中合併為一筆：
{render_red_flag_titles_for_prompt()}

若屬於上述清單以外的新紅旗類型，請自行命名但保持簡潔明確（例如「急性副睪炎可能」）。

## 輸出格式
嚴格以下列 JSON 回覆，禁止輸出 markdown、程式碼區塊、或 JSON 以外任何文字。若未偵測到紅旗，請回 {{"alerts": []}}。

{{
  "alerts": [
    {{
      "severity": "critical|high|medium",
      "title": "簡短標題（同類情境請對齊上方內建名稱）",
      "description": "詳細說明為何判定為紅旗，包含臨床推理",
      "trigger_reason": "直接引用病患原文作為觸發根據",
      "suggested_actions": ["建議處置1", "建議處置2"]
    }}
  ]
}}

## 欄位硬性限制
- severity **只能是 "critical"、"high"、"medium"** 三者之一；禁用 "low"、"none"、"possible"、"warning"、"info" 等字串（會被系統排到最後或無法顯示）。
- title 為單一字串；若與內建規則同類情境請完全使用上方列出的名稱（影響去重合併）。
- description 為單一字串，說明臨床推理與嚴重度判定依據。
- trigger_reason 為**單一字串**，必須直接引用病患對話原文（可加引號），不可留空、不可寫「未提供」、不可寫成陣列。
- suggested_actions 為**字串陣列 list[string]**，每項為一個具體可行的建議動作；不得為單一字串或物件陣列（會觸發後端合併錯誤）。
- alerts 為陣列，即使只有一筆也必須放入陣列；若無紅旗請回空陣列 []。
- **不可輸出** alert_type、matched_rule_id、risk_level、has_red_flag、triage_recommendation、evidence、reasoning、recommended_action、label 等額外欄位；這些會被系統端忽略或覆寫，只會浪費 tokens 並可能觸發解析錯誤。
"""


class RedFlagDetector:
    """
    雙層紅旗症狀偵測器

    同時執行規則比對（快速、確定性高）與語意分析（彈性、覆蓋面廣），
    合併去重後回傳紅旗警示列表。
    """

    def __init__(self, settings: Settings, db_session: AsyncSession) -> None:
        """
        初始化偵測器，載入資料庫中的啟用規則

        Args:
            settings: 應用程式設定實例
            db_session: 非同步資料庫 session
        """
        self._settings = settings
        self._db = db_session
        self._client = get_openai_client()
        self._model = settings.OPENAI_MODEL_RED_FLAG  # gpt-4o-mini
        self._temperature = settings.OPENAI_TEMPERATURE_RED_FLAG  # 0.2
        self._rules: list[dict[str, Any]] = []
        self._rules_loaded = False

        logger.info(
            "RedFlagDetector 初始化 | model=%s, temperature=%.1f",
            self._model,
            self._temperature,
        )

    def _negation_guard_enabled(self) -> bool:
        """否定守衛 kill-switch（預設開）。

        關閉時規則層退回裸 substring 比對、語意層的否定幻覺後過濾也一併停用——
        兩者是同一個機制（同一組否定詞/視窗），只關一半會讓兩層的抑制門檻不一致，
        維運要「退回加守衛前的行為」時反而更難推理。
        """
        return bool(getattr(self._settings, "RED_FLAG_NEGATION_GUARD", True))

    async def _load_rules(self) -> None:
        """從資料庫載入啟用中的紅旗規則

        W1：查詢成功但回傳 0 筆時的處理——red_flag_rules 表在生產環境從無
        seed，「0 筆」語意上等同「規則層從未被配置過」，而非管理者刻意清空
        規則。若規則層在此情境下維持恆為 [],偵測就完全仰賴語意層、失去
        雙層備援,違反 fail-open 精神(寧可重複/誤報也不可漏急症)。因此
        RED_FLAG_BUILTIN_RULES_FALLBACK 開啟時(預設 True),0 筆會 fallback
        到內建 catalogue(shared.URO_RED_FLAGS)。只要 DB 已有任何一筆規則
        (即使只有 1 筆),就視為「已配置過」,尊重 DB 內容、不與內建規則
        混用,避免管理者刻意精簡規則卻被內建規則蓋掉。
        """
        if self._rules_loaded:
            return

        try:
            # 延遲匯入避免循環依賴
            from app.models.red_flag_rule import RedFlagRule

            stmt = select(RedFlagRule).where(RedFlagRule.is_active.is_(True))
            result = await self._db.execute(stmt)
            db_rules = result.scalars().all()

            if not db_rules and self._settings.RED_FLAG_BUILTIN_RULES_FALLBACK:
                self._rules = self._get_fallback_rules()
                self._rules_loaded = True
                logger.warning(
                    "紅旗規則表查無啟用中規則(0 筆)→ fallback 至內建 catalogue | "
                    "rules_count=%d",
                    len(self._rules),
                )
                return

            self._rules = []
            for rule in db_rules:
                self._rules.append(
                    {
                        "id": str(rule.id),
                        # E8-4（原 TODO-E6）：canonical_id 為跨語言穩定標識符;
                        # dedup 以此為 key。若 DB 既有 rule 尚未 backfill
                        # canonical_id,先試著用 name 反查目錄救回（D-6），
                        # 救不回才 fallback 回 name（見 `_resolve_db_canonical_id`）。
                        "canonical_id": self._resolve_db_canonical_id(rule),
                        "name": rule.name,
                        "display_title_by_lang": (
                            getattr(rule, "display_title_by_lang", None) or {}
                        ),
                        "severity": rule.severity,
                        "category": rule.category,
                        "keywords": rule.keywords if rule.keywords else [],
                        "regex_pattern": rule.regex_pattern,
                        "description": rule.description,
                        "suggested_actions": (
                            rule.suggested_actions if rule.suggested_actions else []
                        ),
                    }
                )

            self._rules_loaded = True
            logger.info("已載入 %d 條紅旗規則", len(self._rules))

        except Exception as exc:
            logger.error("載入紅旗規則失敗 | error=%s", str(exc), exc_info=True)
            # 載入失敗時使用內建規則作為備援
            self._rules = self._get_fallback_rules()
            self._rules_loaded = True

    @staticmethod
    def _resolve_db_canonical_id(rule: Any) -> str:
        """DB 規則的 canonical_id；NULL 時盡量救回目錄 id，救不回才退回 rule.name。

        2026-08-20 稽核 D-6（latent）：舊行為是 `canonical_id or rule.name`。
        `canonical_id` 是共現組（`_CANONICAL_COOCCURRENCE`）、severity floor
        （`_CANONICAL_CATALOG_SEVERITY`）、否定幻覺後過濾（`_CANONICAL_KEYWORDS`）
        三張表的查表鍵，全部以目錄 id 為鍵。退回 rule.name 等於這三層對該規則
        **靜默失效**——最嚴重的是共現組，那條規則會退回「只有相鄰複合詞」的舊行為，
        也就是 2026-07-27 量到 60/61 漏報的那個形狀，而且完全沒有訊號。

        保守處理：
          1. 用 rule.name 反查目錄 title / 各語言 display title（DB 的 name 歷史上
             就是目錄 title，見 `_get_fallback_rules` 的 `"name": flag["title"]`）。
             救得回 → 三張表都正常運作。
          2. 救不回 → 保留舊的 name fallback（不可回 None：dedup 需要一個身份），
             但 **log warning**，讓「規則表被 seed 但沒 backfill canonical_id」
             這件事在生產可觀測，而不是靜默降級。
        """
        canonical_id = getattr(rule, "canonical_id", None)
        if canonical_id:
            return str(canonical_id)
        name = getattr(rule, "name", "") or ""
        recovered = _TITLE_TO_CANONICAL.get(normalize_canonical_id(name))
        if recovered:
            logger.warning(
                "DB 紅旗規則的 canonical_id 為空，已用 name 反查目錄救回 | "
                "rule_id=%s name=%s → canonical_id=%s（請 backfill DB 欄位）",
                getattr(rule, "id", None),
                name,
                recovered,
            )
            return recovered
        logger.warning(
            "DB 紅旗規則的 canonical_id 為空且無法從 name 反查目錄 | "
            "rule_id=%s name=%s → 退回以 name 當身份；"
            "此規則的共現組／severity floor／否定幻覺後過濾**都不會生效**，"
            "請 backfill red_flag_rules.canonical_id",
            getattr(rule, "id", None),
            name,
        )
        return str(name)

    @staticmethod
    def _collect_all_language_keywords(flag: dict[str, Any]) -> list[str]:
        """
        聚合單一紅旗在所有語言的 trigger keywords,做為規則比對的關鍵字集合。

        W1 設計理由(聯集比對,而非依 session.language 篩選):
        場次語言只決定「UI 顯示語言」,不代表病患打字/口說用詞只會落在該
        語言——日文場次的病患可能直接混用英文說「blood in urine」、或中英
        夾雜。這裡收錄的醫療紅旗關鍵字都是特異性高的臨床片語(如「尿滯留」
        「testicular pain」「urosepsis」),跨語言聯集比對帶來的誤報風險可
        忽略不計;但若只比對當次 session.language 對應的 keywords,漏報
        風險才是真正該防的——這違反紅旗偵測 fail-open 的核心精神(寧可
        重複/誤報,也不可漏掉一句用其他語言講出的危險症狀)。因此規則比對
        一律採「頂層 triggers ∪ triggers_by_lang 全語言」聯集,不因場次
        語言篩選;DB 規則與此處內建 fallback 規則共用同一套
        `_rule_based_detect` 比對邏輯,行為一致。
        """
        keywords: list[str] = []
        seen: set[str] = set()
        for kw in flag.get("triggers", []):
            if kw not in seen:
                seen.add(kw)
                keywords.append(kw)
        for lang_keywords in (flag.get("triggers_by_lang") or {}).values():
            for kw in lang_keywords:
                if kw not in seen:
                    seen.add(kw)
                    keywords.append(kw)
        return keywords

    @staticmethod
    def _get_fallback_rules() -> list[dict[str, Any]]:
        """
        內建備援紅旗規則（當資料庫不可用,或 DB 規則表為空時使用）

        直接從 shared.URO_RED_FLAGS 產生,保持與語意層 prompt 的知識庫
        完全一致,避免兩邊漂移(P2-E)。這裡不帶 regex_pattern,因為 shared
        catalogue 是純關鍵字;如需 regex 匹配仍應由 DB 規則主導。

        E8-4（原 TODO-E6）:攜帶 canonical_id + display_title_by_lang,讓
        rule-based 層可以在寫入 RedFlagAlert 時 snapshot canonical_id、
        依場次語言渲染 title(見 `_rule_based_detect`)。

        W1:keywords 改用 `_collect_all_language_keywords` 產生所有語言
        triggers 的聯集,而非僅 zh-TW 頂層 triggers(見該函式 docstring
        的設計理由)。
        """
        return [
            {
                "id": None,
                "canonical_id": flag["canonical_id"],
                "name": flag["title"],
                "display_title_by_lang": dict(flag.get("display_title_by_lang", {})),
                "severity": flag["severity"],
                "category": flag["title"],  # 暫用 title 當 category
                "keywords": RedFlagDetector._collect_all_language_keywords(flag),
                "regex_pattern": None,
                "description": flag["description"],
                "suggested_actions": list(flag["suggested_actions"]),
            }
            for flag in URO_RED_FLAGS
        ]

    def _rule_based_detect(
        self, text: str, language: str | None = None
    ) -> list[dict[str, Any]]:
        """
        規則比對層 — 使用關鍵字與正則表達式偵測紅旗症狀

        Args:
            text: 病患描述文字
            language: session BCP-47 語言碼（用於本地化 trigger_reason 等文字欄位）

        Returns:
            比對到的紅旗警示列表
        """
        alerts: list[dict[str, Any]] = []
        text_lower = text.lower()
        unknown_title = get_message("alert.unknown_title", language)
        guard_on = self._negation_guard_enabled()

        for rule in self._rules:
            matched = False
            trigger_reason = ""
            # 命中的關鍵字原文（→ RedFlagAlert.trigger_keywords）。原本規則層只把
            # 命中詞塞進**在地化字串** trigger_reason（「關鍵字比對：「尿滯留」」），
            # DB 的 trigger_keywords 欄永遠 NULL，事後誤報分析得反解多語字串才知道
            # 是哪個詞觸發的。這裡直接把原文留下（跨語言、可 GROUP BY）。
            matched_keywords: list[str] = []
            # critical 用較緊的散文否定視窗（見 _NEG_CRITICAL_PROSE_LOOKBACK 的取捨說明）
            prose_lookback = _prose_lookback_for_severity(rule.get("severity"))

            # 關鍵字比對
            # W1：keyword 也需 lower() 才能保證大小寫不敏感——text_lower 已
            # 轉小寫,但 DB/內建規則的 keyword 本身若帶大寫(如 "Hematuria")
            # 會導致 substring 比對失敗;英文/越南文等有大小寫的語言都靠
            # 這裡統一 normalize。
            for keyword in rule.get("keywords", []):
                if not keyword:
                    continue
                # 否定感知比對：關鍵字若每個出現都被否定（如「血尿」只在「沒有血尿」）
                # 則不觸發；有任一非否定出現才觸發（保留 fail-open）。
                # guard 關閉（kill-switch）→ 退回裸 substring，行為與加守衛前一模一樣。
                if guard_on:
                    hit = _keyword_present_non_negated(
                        keyword, text_lower, prose_lookback
                    )
                    if (
                        not hit
                        and prose_lookback is not None
                        and _keyword_in_text(keyword, text_lower)
                    ):
                        # critical 關鍵字在文中出現、但每個出現都被否定守衛判為否定。
                        # 留下痕跡供生產觀察誤報/漏報率（E11 的驗收方式就是看生產
                        # 資料）；只記 critical，避免病患每次否認症狀都刷 log。
                        logger.info(
                            "critical 紅旗關鍵字出現但被否定守衛抑制 | "
                            "canonical=%s keyword=%s",
                            rule.get("canonical_id") or rule.get("name"),
                            keyword,
                        )
                else:
                    # kill-switch 關閉 → 退回「不看否定」的比對；但**詞邊界仍生效**
                    # （eyeball 那個誤命中是比對精度 bug，不是否定守衛的一部分，
                    #   不該隨守衛一起被關掉）。
                    hit = _keyword_in_text(keyword, text_lower)
                if hit:
                    matched_keywords.append(keyword)
                    if not matched:
                        matched = True
                        # trigger_reason 沿用「第一個命中的關鍵字」（既有行為/既有測試）
                        trigger_reason = get_message(
                            "alert.rule_match_reason", language, keyword=keyword
                        )

            # 共現組比對（部位詞 × 急性/嚴重度詞，語序與插入語不拘）
            # 即使關鍵字已命中也照跑：命中詞要完整落進 trigger_keywords，事後誤報
            # 分析才看得出「是哪一種形狀觸發的」。
            for group in _CANONICAL_COOCCURRENCE.get(
                rule.get("canonical_id") or "", []
            ):
                pair = _cooccurrence_matches(
                    group, text_lower, prose_lookback, guard_on
                )
                if not pair:
                    continue
                site, acuity = pair
                # 兩個詞分別入列（都是原文子字串，供 DB GROUP BY 與人工覆核）
                for term in (site, acuity):
                    if term not in matched_keywords:
                        matched_keywords.append(term)
                if not matched:
                    matched = True
                    trigger_reason = get_message(
                        "alert.rule_match_reason",
                        language,
                        keyword=f"{site}＋{acuity}",
                    )

            # 正則表達式比對（關鍵字未命中時）
            #
            # ⚠️ 2026-08-20 稽核 D-6：這條路徑**只有 DB 規則會走**（內建 catalogue 的
            # regex_pattern 恆為 None），而 red_flag_rules 表在生產從未 seed，所以它
            # 一直是 latent 的。缺陷：regex 命中直接 `matched = True`，完全繞過
            # `_occurrence_negated`——同一句「我沒有血尿」，關鍵字路徑會被否定守衛
            # 抑制，regex 路徑卻照樣 critical。哪天有人 seed 了規則表（那正是
            # `_load_rules` 的設計情境），整組否定守衛就對那些規則靜默失效。
            # 修法：regex 的**命中位置**也要過同一組守衛，逐一 match 找第一個非否定的。
            # guard 關掉（kill-switch）時退回原本的「第一個 match 就算」行為，與關鍵字
            # 路徑一致。
            if not matched and rule.get("regex_pattern"):
                try:
                    match = None
                    # 在 text_lower 上搜尋（而非 text）：守衛的所有索引都是
                    # text_lower 的索引，兩者必須同一個座標系。pattern 帶
                    # re.IGNORECASE，所以換成小寫 haystack 不改變命中集合。
                    for candidate in re.finditer(
                        rule["regex_pattern"], text_lower, re.IGNORECASE
                    ):
                        if not guard_on or not _occurrence_negated(
                            text_lower,
                            candidate.start(),
                            candidate.end() - candidate.start(),
                            prose_lookback,
                        ):
                            match = candidate
                            break
                        logger.info(
                            "regex 紅旗命中但被否定守衛抑制 | canonical=%s pattern=%s",
                            rule.get("canonical_id") or rule.get("name"),
                            rule.get("regex_pattern"),
                        )
                    if match:
                        matched = True
                        trigger_reason = get_message(
                            "alert.regex_match_reason",
                            language,
                            # 顯示用回到原文大小寫（索引同座標系）
                            match=text[match.start() : match.end()],
                        )
                except re.error as exc:
                    logger.warning(
                        "正則表達式無效 | rule=%s, pattern=%s, error=%s",
                        rule.get("name"),
                        rule.get("regex_pattern"),
                        str(exc),
                    )

            if matched:
                # E8-4（原 TODO-E6）：依 session.language 從 display_title_by_lang
                # 取 title。DB rule 若無此欄位,fallback 至 rule.name / shared
                # catalogue 查表。
                canonical_id = rule.get("canonical_id") or rule.get("name")
                display_map = rule.get("display_title_by_lang") or {}
                # Fallback 順序: session lang → en-US → catalogue(含 en-US / zh-TW)
                # → 規則 name → unknown_title。先試 en-US 再退到 zh-TW,避免
                # 日/韓/越場次因 DB rule 缺該語言翻譯直接收到中文標題。
                localized_title = (
                    (display_map.get(language) if language else None)
                    or display_map.get("en-US")
                    or get_display_title(canonical_id, language)
                    or display_map.get("zh-TW")
                    or rule.get("name", unknown_title)
                )
                alerts.append(
                    {
                        "canonical_id": canonical_id,
                        "severity": rule.get("severity", "medium"),
                        "title": localized_title,
                        "description": rule.get("description", ""),
                        "trigger_reason": trigger_reason,
                        # 命中詞原文（regex-only 命中時為 None，欄位語意＝「關鍵字」）
                        "trigger_keywords": matched_keywords or None,
                        # 規則層沒有 LLM 判斷；顯式帶 None 讓兩層的 payload 形狀一致，
                        # merge 時才好判斷「這欄該不該從語意層搬過來」。
                        "llm_analysis": None,
                        "alert_type": "rule_based",
                        # TODO-M8：規則層命中 → confidence=rule_hit(最高信心)。
                        "confidence": "rule_hit",
                        "suggested_actions": rule.get("suggested_actions", []),
                        "matched_rule_id": rule.get("id"),
                    }
                )

        return alerts

    async def _semantic_detect(
        self,
        text: str,
        session_context: dict[str, Any],
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        語意分析層 — 使用 LLM 進行深層紅旗症狀偵測

        Args:
            text: 病患描述文字
            session_context: 場次上下文（主訴、病史等）
            language: session BCP-47 語言碼，決定 LLM 輸出語言

        Returns:
            LLM 偵測到的紅旗警示列表
        """
        session_id = session_context.get("session_id", "unknown")

        # 組合上下文資訊
        context_parts: list[str] = []
        if session_context.get("chief_complaint"):
            context_parts.append(f"主訴：{session_context['chief_complaint']}")
        # 跨輪累積型 critical（前輪發燒 ＋ 本輪腰痛＝urosepsis）只有這條路看得到歷史；
        # 正規化 / 截斷邏輯見 `_format_conversation_summary`。
        conversation_summary = _format_conversation_summary(
            session_context.get("conversation_summary")
        )
        if conversation_summary:
            context_parts.append(f"先前對話（依時間排序）：\n{conversation_summary}")

        context_text = "\n".join(context_parts) if context_parts else ""

        user_message = f"""## 病患背景
{context_text}

## 病患最新描述
{text}

請分析以上內容是否包含紅旗症狀，並以指定 JSON 格式回覆。
注意：紅旗可能要把先前對話與最新描述**合併**才成立（跨輪累積的症狀組合），
請把兩者視為同一位病患的同一次問診一起判斷；但 trigger_reason 仍須引用病患講過的原文。"""

        # 組 system prompt：catalogue prompt（固定中文，作為臨床知識本體）
        # + 本地化輸出語言指示（依 session language 切換 title/description 語言）
        system_prompt = _SEMANTIC_SYSTEM_PROMPT + get_message(
            "llm.red_flag_language_instruction", language
        )
        default_semantic_title = get_message("alert.semantic_default_title", language)

        try:
            response = await call_with_retry(
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    **sampling_kwargs(self._model, effort=getattr(self._settings, "OPENAI_REASONING_EFFORT_RED_FLAG", "none"), temperature=self._temperature),
                    # 每輪重送同一靜態 catalogue 前綴 → 按場次路由快取
                    **cache_kwargs(session_id),
                    max_completion_tokens=1024,
                    response_format={"type": "json_object"},
                )
            )

            raw_content = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_content)
            raw_alerts = parsed.get("alerts", [])

            # title → canonical_id 反查表(所有語言的 display title 都會指向同一 canonical_id),
            # 讓 LLM 回「Hematuria」、「肉眼血尿」、「Gross Hematuria」都能對到 canonical_id=gross_hematuria。
            # 模組層已建好（`_TITLE_TO_CANONICAL`，同時給 D-6 的 DB canonical_id 救援用）。
            title_to_canonical = _TITLE_TO_CANONICAL

            alerts: list[dict[str, Any]] = []
            for alert in raw_alerts:
                raw_title = alert.get("title", default_semantic_title)
                normalized_title = normalize_canonical_id(raw_title)
                is_catalogue_match = normalized_title in title_to_canonical
                canonical_id = title_to_canonical.get(
                    normalized_title,
                    # 新型紅旗(LLM 自創命名)→ 無對應 canonical_id,以 title 當 fallback。
                    # ⚠️ 2026-08-20 稽核 D-7：這裡**必須用正規化後的字串**。用 raw_title
                    # 會讓 LLM 同一個紅旗換個大小寫/空白就變成不同身份 →
                    # 同輪 merge 合不起來、跨輪 Redis 去重失效（每輪重複 emit）。
                    # 見 `shared.normalize_canonical_id`。顯示用的 title 仍是 raw_title,
                    # 所以護理站看到的文字不變。
                    normalized_title,
                )
                # E8-4：system prompt 的「title 命名對齊」段落固定列出 zh-TW 範例
                # 名稱,要求 LLM「使用完全相同的 title」以利跨層合併——這會讓
                # LLM 即使被要求以 en-US/ja-JP/... 輸出,仍逐字沿用中文範例
                # 當 title,導致非 zh-TW 場次的 alert 顯示中文標題(en 場次仍見
                # 「肉眼血尿」)。只要 title 命中內建 catalogue、能解出
                # canonical_id,一律不信任 LLM 原文 title 的語言,改用
                # get_display_title 依 session.language 重新解析;只有全新
                # (LLM 自創、catalogue 沒有對應項目)的紅旗才保留 raw_title 原樣。
                resolved_title = (
                    get_display_title(canonical_id, language)
                    if is_catalogue_match
                    else raw_title
                )
                # 目錄 severity floor：命中內建 catalogue 的紅旗，語意層自評不得
                # 低於目錄定義（防 critical 被 LLM 降級為 high 而躲過 abort 門檻）。
                llm_severity = alert.get("severity", "medium")
                floored_severity = (
                    _floor_severity_to_catalog(canonical_id, llm_severity)
                    if is_catalogue_match
                    else llm_severity
                )
                if is_catalogue_match and floored_severity != llm_severity:
                    logger.warning(
                        "語意層 severity 低於目錄，floor 升級 | session=%s canonical=%s llm=%s → catalog=%s",
                        session_id,
                        canonical_id,
                        llm_severity,
                        floored_severity,
                    )
                alerts.append(
                    {
                        "canonical_id": canonical_id,
                        "severity": floored_severity,
                        "title": resolved_title,
                        "description": alert.get("description", ""),
                        "trigger_reason": alert.get("trigger_reason", ""),
                        "alert_type": "semantic",
                        # 語意層沒有規則關鍵字；顯式帶 None 讓兩層 payload 形狀一致。
                        "trigger_keywords": None,
                        # RedFlagAlert.llm_analysis（JSONB）的內容：留下語意層的
                        # **原始**判斷,讓事後誤報分析知道 severity floor / title
                        # 重解析之前 LLM 到底說了什麼。
                        # ⚠️ 這一欄要真的落庫需要三段接力：本層產出 → merge 搬運
                        #   （見 `_merge_and_deduplicate`,combined 路徑漏搬過一次）
                        #   → conversation_handler 的 AlertService.create payload。
                        "llm_analysis": {
                            "model": self._model,
                            "raw_title": raw_title,
                            "raw_severity": llm_severity,
                            "matched_catalogue": is_catalogue_match,
                            "description": alert.get("description", ""),
                        },
                        # TODO-M8：語意層命中 → 預設 semantic_only,後續 merge/escalation
                        # 可能改寫為 rule_hit(combined)或 uncovered_locale。
                        "confidence": "semantic_only",
                        "suggested_actions": alert.get("suggested_actions", []),
                        "matched_rule_id": None,
                    }
                )

            logger.info(
                "語意紅旗偵測完成 | session=%s, alerts_count=%d",
                session_id,
                len(alerts),
            )

            return alerts

        except json.JSONDecodeError as exc:
            logger.error(
                "語意偵測結果 JSON 解析失敗 | session=%s, error=%s",
                session_id,
                str(exc),
            )
            return []

        except Exception as exc:
            logger.error(
                "語意紅旗偵測失敗 | session=%s, error=%s",
                session_id,
                str(exc),
                exc_info=True,
            )
            return []

    async def detect(
        self, text: str, session_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        執行雙層紅旗偵測 — 同時運行規則比對與語意分析

        Args:
            text: 病患描述文字
            session_context: 場次上下文資訊（若有 `language` key，會影響
                trigger_reason 與 LLM 輸出語言；預設 zh-TW）

        Returns:
            去重合併後的紅旗警示列表，按嚴重度排序：
            [
                {
                    "severity": "critical|high|medium",
                    "title": str,
                    "description": str,
                    "trigger_reason": str,
                    "alert_type": "rule_based|semantic|combined",
                    "suggested_actions": list[str],
                    "matched_rule_id": uuid | None,
                }
            ]
        """
        session_id = session_context.get("session_id", "unknown")
        language = session_context.get("language")

        if not text or not text.strip():
            return []

        # 確保規則已載入
        await self._load_rules()

        # 並行執行雙層偵測
        rule_alerts, semantic_alerts = await asyncio.gather(
            asyncio.to_thread(self._rule_based_detect, text, language),
            self._semantic_detect(text, session_context, language),
            return_exceptions=True,
        )

        # 處理例外情況
        if isinstance(rule_alerts, BaseException):
            logger.error("規則比對層發生例外 | error=%s", str(rule_alerts))
            rule_alerts = []
        if isinstance(semantic_alerts, BaseException):
            logger.error("語意分析層發生例外 | error=%s", str(semantic_alerts))
            semantic_alerts = []

        # Observability（TODO-O2）：各層分開計數，combined 由 Prometheus sum 兩 label 得出
        try:
            record_red_flag_triggers(
                language=language,
                rule_count=len(rule_alerts),
                semantic_count=len(semantic_alerts),
            )
        except Exception:  # noqa: BLE001 — metrics 失敗不應影響紅旗偵測
            logger.debug("record_red_flag_triggers 失敗", exc_info=True)

        # 合併並去重
        merged = self._merge_and_deduplicate(rule_alerts, semantic_alerts, language)

        # 否定幻覺後過濾（**只涵蓋語意層**）：病患明確否認的症狀不應成為紅旗。
        #
        # ⚠️ 2026-08-20 稽核 RF-1（P0 漏報）：本過濾原本套在**所有** alert 上，
        # 但它的判準 `_CANONICAL_KEYWORDS` 只收 triggers / triggers_by_lang，
        # **不認識共現組**（`trigger_cooccurrence`）。於是規則層靠共現組命中的
        # critical 會被整筆丟掉：
        #   「我沒有高燒，但是我發燒到三十八度而且小便會痛」
        #     → 規則層 urosepsis critical（發燒 × 小便），但 canonical 關鍵字
        #       只有「高燒」出現且被否認 → 整筆被刪 → 漏報。
        # 同型的還有 urinary_retention（否認「尿滯留」但描述膀胱脹到尿不出）、
        # cauda_equina_suspected（否認「會陰麻木」但描述腳沒力＋漏尿）。
        #
        # 修法：只對 `alert_type == "semantic"` 生效。理由（不是為了讓測試變綠）：
        #   規則層**自己的**否定守衛更嚴謹——它對每一個關鍵字出現位置、以及共現組的
        #   部位詞／急性詞／整段跨度三處都跑過 `_occurrence_negated`。規則層能產出
        #   alert，就代表已經有一處證據是非否定的。再拿一份**看不到共現組**的關鍵字
        #   表去覆蓋那個判斷，只會刪掉規則層正確的命中，不可能發現規則層漏掉的否認。
        #   combined（兩層都命中）同理：規則層那一半仍是有效證據，不得刪。
        # 本過濾原本要解的問題（LLM 對病患明確否認的症狀幻覺紅旗）完全保留。
        if self._negation_guard_enabled():
            text_lower = text.lower()
            kept: list[dict[str, Any]] = []
            for alert in merged:
                cid = alert.get("canonical_id")
                if (
                    cid
                    and alert.get("alert_type") == "semantic"
                    and _canonical_denied_in_text(cid, text_lower)
                ):
                    logger.warning(
                        "紅旗否定幻覺抑制 | session=%s, canonical=%s, alert_type=%s, severity=%s",
                        session_id,
                        cid,
                        alert.get("alert_type"),
                        alert.get("severity"),
                    )
                    continue
                kept.append(alert)
            merged = kept

        # 父子紅旗折疊：同一臨床實體的高/低嚴重度雙胞胎（大量血尿 critical ⊃
        # 肉眼血尿 high）canonical_id 不同 → merge 不會合併 → 兩筆 DB 列 / 兩則 WS
        # 事件 / dashboard 兩條警示 / analytics 紅旗數灌水。父在場時折疊掉子，
        # 並把子的 suggested_actions 併進父（處置建議不掉字）。
        merged = self._collapse_superseded(merged, session_id)

        # TODO-M8:對仍為 semantic_only 的 alert,若 session.language 沒有
        # 該 canonical_id 的 trigger keywords 覆蓋 → 降級為 uncovered_locale
        # (fail-safe:代表本地化規則不足,應自動 escalate 為 physician review)。
        for alert in merged:
            if alert.get("confidence") != "semantic_only":
                continue
            cid = alert.get("canonical_id")
            if cid and not has_locale_coverage(cid, language):
                alert["confidence"] = "uncovered_locale"
                logger.warning(
                    "紅旗 locale 覆蓋不足 → 自動 escalate | "
                    "session=%s, canonical_id=%s, language=%s",
                    session_id,
                    cid,
                    language,
                )

        # TODO-O4:寫入 rule-layer coverage metric(每個 merged alert 一筆)。
        for alert in merged:
            record_red_flag_rule_layer_coverage(
                language=language,
                confidence=alert.get("confidence", "semantic_only"),
            )

        # 按嚴重度排序：critical > high > medium
        severity_order = {"critical": 0, "high": 1, "medium": 2}
        merged.sort(key=lambda a: severity_order.get(a["severity"], 99))

        if merged:
            logger.warning(
                "偵測到紅旗症狀 | session=%s, count=%d, severities=%s",
                session_id,
                len(merged),
                [a["severity"] for a in merged],
            )

        return merged

    @staticmethod
    def _collapse_superseded(
        alerts: list[dict[str, Any]], session_id: str = "unknown"
    ) -> list[dict[str, Any]]:
        """父紅旗在場 → 折疊掉它涵蓋的子紅旗（見 shared.RED_FLAG_SUPERSEDES）。

        安全性：只折疊「同一臨床實體、父嚴重度 ≥ 子」的組合,且父本身必定會被
        持久化+廣播,護理站看到的是處置更積極的那則;子的 suggested_actions 併入父,
        避免處置建議掉字。父不在場時一律不動（子仍是獨立紅旗）。
        """
        present = {a.get("canonical_id") for a in alerts if a.get("canonical_id")}
        suppressed: dict[str, str] = {}  # child_id → parent_id
        for parent_id, children in RED_FLAG_SUPERSEDES.items():
            if parent_id not in present:
                continue
            for child_id in children:
                if child_id in present:
                    suppressed[child_id] = parent_id
        if not suppressed:
            return alerts

        by_canonical = {a.get("canonical_id"): a for a in alerts}
        kept: list[dict[str, Any]] = []
        for alert in alerts:
            cid = alert.get("canonical_id")
            parent_id = suppressed.get(cid) if cid else None
            if parent_id is None:
                kept.append(alert)
                continue
            parent = by_canonical.get(parent_id)
            if parent is not None:
                actions = list(parent.get("suggested_actions") or [])
                for action in alert.get("suggested_actions") or []:
                    if action not in actions:
                        actions.append(action)
                parent["suggested_actions"] = actions
            logger.info(
                "紅旗父子折疊：父紅旗涵蓋子紅旗，抑制子 | session=%s, parent=%s, child=%s",
                session_id,
                parent_id,
                cid,
            )
        return kept

    @staticmethod
    def _merge_and_deduplicate(
        rule_alerts: list[dict[str, Any]],
        semantic_alerts: list[dict[str, Any]],
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        合併兩層偵測結果並去除重複項

        若同一 canonical_id 在兩層都有命中,合併為 combined 類型並保留較高嚴重度;
        合併後 confidence 升級為 rule_hit(規則層有命中代表高信心)。

        E8-4（原 TODO-E6）:dedup key 改用 canonical_id,讓 zh-TW 規則層(肉眼血尿)與
        en-US 語意層(Gross Hematuria)也能正確合併到同一 alert。

        Args:
            rule_alerts: 規則比對結果
            semantic_alerts: 語意分析結果
            language: 用於本地化 combined trigger_reason 的語言碼

        Returns:
            去重合併後的警示列表
        """
        merged: dict[str, dict[str, Any]] = {}
        severity_priority = {"critical": 0, "high": 1, "medium": 2}

        def _dedup_key(alert: dict[str, Any]) -> str:
            """優先用 canonical_id(跨語言穩定),fallback 用 title。

            兩者都走 `normalize_canonical_id`（lowercase＋strip＋空白摺疊，
            2026-08-20 稽核 D-7）：LLM 自創紅旗的 canonical_id 就是它自己回的 title，
            大小寫/空白每輪都可能不同，不正規化就會把「換句話說的同一個紅旗」
            當成兩筆。對目錄的 snake_case id 是恆等變換。
            """
            cid = alert.get("canonical_id")
            if cid:
                return f"cid:{normalize_canonical_id(cid)}"
            return f"title:{normalize_canonical_id(alert.get('title', ''))}"

        # 先加入規則比對結果
        rule_keys: set[str] = set()
        for alert in rule_alerts:
            key = _dedup_key(alert)
            merged[key] = alert.copy()
            rule_keys.add(key)

        # 合併語意分析結果
        for alert in semantic_alerts:
            key = _dedup_key(alert)

            if key in merged:
                existing = merged[key]
                # 只有「規則層也命中」才算 combined/rule_hit。語意層自己回了兩筆
                # 同 canonical 的 alert 時（LLM 用不同 title 描述同一件事）不得
                # 假裝規則層有命中——那會讓 confidence 灌水成最高信心。
                if key in rule_keys:
                    existing["alert_type"] = "combined"
                    # TODO-M8:combined 代表規則層也命中 → 升級為 rule_hit(最高信心)。
                    existing["confidence"] = "rule_hit"

                # 取較高嚴重度
                if severity_priority.get(
                    alert["severity"], 99
                ) < severity_priority.get(existing["severity"], 99):
                    existing["severity"] = alert["severity"]

                # 層別專屬欄位的搬運（缺一個就等於該欄在 combined 路徑永遠是 NULL）：
                #   llm_analysis      只有語意層有 → 規則層先進 merged 時是 None,
                #                     不搬就會讓「兩層都命中」的 alert 落庫成
                #                     llm_analysis=NULL（2026-07-27 真跑 DB 實測）。
                #   trigger_keywords  只有規則層有 → 既有值必須保留;只有在規則層
                #                     是 regex-only 命中（None）時才可能由語意層補。
                if existing.get("llm_analysis") is None and alert.get("llm_analysis"):
                    existing["llm_analysis"] = alert["llm_analysis"]
                if not existing.get("trigger_keywords") and alert.get(
                    "trigger_keywords"
                ):
                    existing["trigger_keywords"] = alert["trigger_keywords"]

                # 合併觸發原因
                existing["trigger_reason"] = get_message(
                    "alert.combined_trigger_reason",
                    language,
                    rule_reason=existing["trigger_reason"],
                    semantic_reason=alert["trigger_reason"],
                )

                # 合併建議處置（去重）
                existing_actions = set(existing.get("suggested_actions", []))
                for action in alert.get("suggested_actions", []):
                    existing_actions.add(action)
                existing["suggested_actions"] = list(existing_actions)

            else:
                merged[key] = alert.copy()

        return list(merged.values())
