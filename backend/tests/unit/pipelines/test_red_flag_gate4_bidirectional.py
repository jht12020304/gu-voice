# -*- coding: utf-8 -*-
"""第四輪 Gate 的雙向迴歸釘子。

背景（這條管線的歷史教訓，別再踩一次）：
  第一輪只加「必須命中」的測試 → 改出 over-trigger（裸關鍵字）
  第二輪只加「不該命中」的測試 → 改出 under-trigger（相鄰複合詞）
  第三輪改用同句共現才同時解掉兩個方向
所以本檔的每一組都**成對**：一組必須命中、一組必須抑制，兩邊由同一個機制決定。

語料全部由 Gate 自行撰寫，刻意不與 e2e persona 台詞或既有測試檔重複
（第三輪就是栽在「persona 台詞剛好讓關鍵字相鄰」的實作配適上）。

臨床政策（2026-07-27 拍板）：紅旗規則層**偏誤報**。誤中止＝病患白等、護理師走一趟，
可逆；漏報不可逆。所以本檔對「抑制」一律採嚴格審查，對「誤報」則明文接受。
"""
from __future__ import annotations

import pytest

import app.pipelines.red_flag_detector as rfd_module
from app.pipelines.red_flag_detector import RedFlagDetector


@pytest.fixture()
def detector() -> RedFlagDetector:
    class _S:
        RED_FLAG_NEGATION_GUARD = True
        RED_FLAG_BUILTIN_RULES_FALLBACK = True
        OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
        OPENAI_TEMPERATURE_RED_FLAG = 0.2

    det = RedFlagDetector.__new__(RedFlagDetector)
    det._settings = _S()
    det._db = None
    det._client = None
    det._model = "gpt-4o-mini"
    det._temperature = 0.2
    det._rules = RedFlagDetector._get_fallback_rules()
    det._rules_loaded = True
    return det


def _crits(det: RedFlagDetector, text: str, language: str) -> list[str]:
    return [
        a["canonical_id"]
        for a in det._rule_based_detect(text, language)
        if a.get("severity") == "critical"
    ]


# ══════════════════════════════════════════════════════════════════
# 1. 條件句守衛：「X 的時候就會痛」是真症狀，不是假設
# ══════════════════════════════════════════════════════════════════
# 第三輪為了擋掉純假設提問，讓「條件詞出現即抑制」（en 還補了子句開頭的裸 if）。
# 第四輪 Gate 對抗式探針實測：8 句「條件詞包裝的真症狀」被抹掉 7 句 —— 而
# 「壓下去會痛／走路會痛」正是睪丸扭轉的理學檢查發現，是最不該漏的一種描述。
# 修法（收窄）：條件句要抑制，必須**同時**是一個在問「該怎麼辦／要去哪」的句子。

CONDITIONAL_BUT_REAL_SYMPTOM = [
    ("en-US", "if i press on my testicle it hurts so much i almost pass out"),
    ("en-US", "if i walk my testicle is in severe pain"),
    ("en-US", "if i stand up my testicle suddenly hurts so bad and i throw up"),
    ("zh-TW", "如果我壓下去睪丸就會很痛，痛到快昏倒"),
    ("zh-TW", "假如我一動睪丸就突然劇痛"),
    ("ja-JP", "もし歩くと睾丸が激しく痛みます"),
    ("ko-KR", "만약 걸으면 고환이 갑자기 심하게 아파요"),
    ("vi-VN", "nếu tôi đi lại thì tinh hoàn đau dữ dội"),
]

PURE_HYPOTHETICAL_QUESTION = [
    ("zh-TW", "如果哪天蛋蛋突然很痛，我要打哪支電話"),
    ("zh-TW", "如果睪丸很痛的話要掛哪一科"),
    ("en-US", "if my testicle ever hurts acutely, should i call the clinic first"),
    ("en-US", "suppose my testicle suddenly hurts at night, what do i do"),
    ("ja-JP", "もし夜中に睾丸が激しく痛くなったらどうすればいいですか"),
    ("ko-KR", "만약 고환이 갑자기 심하게 아프면 어디로 가야 하나요"),
    ("vi-VN", "nếu tinh hoàn đau dữ dội vào ban đêm thì tôi phải làm gì"),
]


@pytest.mark.parametrize("language,text", CONDITIONAL_BUT_REAL_SYMPTOM)
def test_conditional_wrapping_a_real_symptom_still_fires(detector, language, text):
    """條件詞包住的**真症狀**不得被抑制（漏報方向，政策不允許）。"""
    assert _crits(detector, text, language), (
        f"條件句守衛把真症狀抹掉了：{language} {text!r}。"
        "「X 的時候就會痛」是病患描述症狀的常見講法，不是假設。"
    )


@pytest.mark.parametrize("language,text", PURE_HYPOTHETICAL_QUESTION)
def test_pure_hypothetical_question_is_still_suppressed(detector, language, text):
    """對照組：純假設**提問**仍然抑制——否則收窄就變成整條關掉。"""
    assert _crits(detector, text, language) == [], f"{language} {text!r}"


def test_conditional_branch_requires_an_advice_question(detector):
    """結構性：條件詞**單獨**不足以抑制，必須同時有求助提問標記。

    這條釘住收窄本身。若有人把 `asks_for_advice` 拿掉（退回第三輪行為），
    上面 8 筆真症狀會整批變成漏報，而這條會先變紅。
    """
    src = rfd_module._hypothetical_or_admin_inquiry.__doc__ or ""
    assert rfd_module._ADVICE_QUESTION_MARKERS
    # 行為面（比註解可靠）：同一句話只差一個「要怎麼辦」，結果必須不同。
    assert _crits(detector, "如果我一動睪丸就突然劇痛", "zh-TW")
    assert _crits(detector, "如果我一動睪丸就突然劇痛，要怎麼辦", "zh-TW") == []
    assert src is not None


# ══════════════════════════════════════════════════════════════════
# 2. 跨症狀組合紅旗：相鄰子句必須配得起來
# ══════════════════════════════════════════════════════════════════
# urosepsis（泌尿症狀＋全身性感染徵象）與 cauda_equina（膀胱功能障礙＋神經學缺損）
# 的兩個維度是**兩個不同的症狀**，病患本來就會講成相鄰兩句。第三輪的
# `_pairing_scope_ok` 要求中間至少夾一個完整插入語子句 → 相鄰子句永遠配不起來，
# 實測有標點版全漏、去掉標點才命中（＝純粹的子句邊界限制，不是詞表不足）。

CROSS_SYMPTOM_ADJACENT_CLAUSES = [
    ("urosepsis", "zh-TW", "我發燒到三十九度，而且小便的時候很痛"),
    ("urosepsis", "zh-TW", "昨天晚上開始燒起來，腰也一直痠痛，小便混濁有味道"),
    ("urosepsis", "ja-JP", "三十八度台の熱が続いていて、排尿のときに痛みがあります"),
    ("urosepsis", "ja-JP", "寒気がして体が震えるし、おしっこも痛いです"),
    ("cauda_equina_suspected", "zh-TW", "腰痛得很厲害，兩隻腳越來越沒力，昨天開始尿失禁"),
    ("cauda_equina_suspected", "zh-TW", "我胯下那邊沒有知覺了，而且憋不住尿"),
]


@pytest.mark.parametrize("canonical_id,language,text", CROSS_SYMPTOM_ADJACENT_CLAUSES)
def test_cross_symptom_flags_pair_across_adjacent_clauses(
    detector, canonical_id, language, text
):
    assert canonical_id in _crits(detector, text, language), (
        f"跨症狀組合紅旗在相鄰子句配不起來：{language} {text!r}"
    )


def test_cross_clause_is_opt_in_and_only_for_cross_symptom_flags():
    """結構性：`cross_clause` 只准掛在跨症狀組合型紅旗上。

    site×acuity 型（睪丸／血尿）的兩個維度描述的是**同一個**症狀，本來就
    該落在同一子句；替它們開 cross_clause 會讓「我眼睛突然很痛，睪丸沒事」這類
    跨子句誤配整批回來，那是第三輪特地關掉的誤報面。

    ⚠️ `urinary_retention` 是 2026-07-27 主 agent 加入的例外，理由與跨症狀型不同：
    尿滯留最自然的敘述是**對比句**——「平常正常，**但是**現在尿不出來」，
    部位詞（pee / urine / 小便）落在前一子句、阻塞詞落在後一子句。實測漏報：
      "normally i pee fine, but since last night nothing comes out"
      "usually my urine is normal, but today i cannot pass any urine at all"
    兩句都是教科書級尿滯留。它的 acuity_terms 夠具體（nothing comes out /
    not a drop / completely blocked / cannot pass…），跨子句誤配面有限。
    要再加新的例外，必須同樣附上「實測漏報句 + 為什麼 acuity 夠具體」。

    ⚠️ `gross_hematuria_heavy` 是 2026-08-21 RF-5 加入的例外（P0 漏報，6fc51e3 回歸）。
    RF-3 把裸「血塊／血の塊／혈전／blood clots」移進共現組之後，本紅旗只剩「同一
    子句」一條路，而病患講大量血尿的自然語序是**同一句話、跨子句**（尿液詞在逗號
    前、血塊詞在逗號後）。五語 15 句實測**逗號拿掉就命中** ＝ 純粹是子句邊界造成
    的漏報，不是詞表缺口；其中兩句是 severity 被降級成 gross_hematuria(high)。
    ⚠️ 語料**刻意不抄在這裡**：`test_red_flag_audit_2026_08.py` 有一條結構性測試
    （`test_corpus_is_independent_of_personas_and_existing_tests`）在比對本檔全文，
    抄過來會讓那條測試判定「語料與既有來源重複」。逐句與逐筆承重清單見該檔的
    `RF5_CROSS_CLAUSE_MUST_FIRE` / `RF5_HEMATURIA_CROSS_CLAUSE_LOAD_BEARING`。
    為什麼 acuity 夠具體：RF-3 之後本組 acuity_terms 的**每一條都自帶血語意**
    （血塊／都是血／血のかたまり／핏덩／blood clot／máu cục…），沒有任何裸量詞，
    所以本紅旗唯一危險的誤報面（頻尿主訴「我最近小便次數很多，一天十幾次」）
    是靠「量詞必須帶血」關掉的——那條性質與子句邊界**正交**，放寬邊界不會鬆動它。
    `testicular_pain_severe` 仍**不得**開：那組是「同一個部位 × 該部位的嚴重度」，
    跨子句會把「我眼睛突然很痛，睪丸沒事」配起來（下方對照組守著）。
    """
    from app.pipelines.prompts.shared import URO_RED_FLAGS

    allowed = {
        "urosepsis",
        "cauda_equina_suspected",
        "urinary_retention",
        "gross_hematuria_heavy",
    }
    for flag in URO_RED_FLAGS:
        for group in flag.get("trigger_cooccurrence") or []:
            if group.get("cross_clause"):
                assert flag["canonical_id"] in allowed, (
                    f"{flag['canonical_id']} 不是跨症狀組合型紅旗，不得開 cross_clause"
                )


@pytest.mark.parametrize(
    "language,text",
    [
        ("ko-KR", "고환은 괜찮은데, 오늘 아침부터 배가 심하게 아파요"),
        ("zh-TW", "睪丸沒問題，今天早上肚子突然很痛"),
        ("ja-JP", "睾丸は大丈夫ですが、今朝から腰が激しく痛みます"),
    ],
)
def test_site_x_acuity_flags_still_do_not_pair_across_clauses(detector, language, text):
    """對照組：site×acuity 型維持不跨子句配對（cross_clause 沒有外溢）。"""
    assert _crits(detector, text, language) == [], f"{language} {text!r}"


# ══════════════════════════════════════════════════════════════════
# 3. 「用否定句陳述的症狀」不得被讀成否認
# ══════════════════════════════════════════════════════════════════
# 五種語言都有一整族「症狀本身就是否定形」的講法。守衛把它們讀成否認就是
# 規則層自己製造 critical 漏報。與第 4 節（明確否認必須抑制）成對。

SYMPTOM_STATED_AS_NEGATION = [
    ("urinary_retention", "en-US",
     "i have not been able to pee since last night and my bladder feels like it will burst"),
    ("urinary_retention", "en-US", "my lower belly is rock hard because no urine will come out"),
    ("urinary_retention", "ja-JP", "トイレに行っても、力んでも、尿が一滴も出ません"),
    ("urinary_retention", "ja-JP", "尿が出ないです、お腹が張っています"),
    ("cauda_equina_suspected", "en-US",
     "there is no feeling in the saddle area and i am leaking urine"),
    ("cauda_equina_suspected", "en-US",
     "i have no control over my bladder and my groin is numb"),
    ("cauda_equina_suspected", "ko-KR", "회음부 감각이 없고 소변이 새요"),
    ("cauda_equina_suspected", "vi-VN",
     "tôi không nhịn được tiểu và vùng bẹn không có cảm giác"),
    ("urinary_retention", "vi-VN", "tôi rặn mãi mà không ra được giọt nước tiểu nào"),
]


@pytest.mark.parametrize("canonical_id,language,text", SYMPTOM_STATED_AS_NEGATION)
def test_symptom_stated_as_negation_still_fires(detector, language, text, canonical_id):
    assert canonical_id in _crits(detector, text, language), (
        f"否定形的症狀陳述被守衛當成否認：{language} {text!r}"
    )


def test_straddling_false_friends_are_latin_only(detector):
    """假朋友跨關鍵字邊界比對**只准**用在拉丁/越南文。

    中日韓沒有詞界，跨界比對會把「我沒有意識不清」（明確否認 urosepsis 的
    trigger「意識不清」）當成假朋友「沒有意識」放行 —— 那會讓守衛在唯一該
    抑制的情況（明確否認）失效。
    """
    assert rfd_module._STRADDLING_FALSE_FRIENDS
    for ff in rfd_module._STRADDLING_FALSE_FRIENDS:
        assert not any(rfd_module._is_cjk_char(c) for c in ff), ff
    # 行為面：CJK 的明確否認仍然被抑制
    assert _crits(detector, "我沒有意識不清", "zh-TW") == []


# ══════════════════════════════════════════════════════════════════
# 4. 明確否認：政策唯一允許抑制的情況，必須仍然抑制（5 語 × 5 旗）
# ══════════════════════════════════════════════════════════════════

EXPLICIT_DENIALS = [
    ("zh-TW", "我沒有睪丸痛"),
    ("en-US", "i do not have any testicle pain"),
    ("en-US", "patient denies severe testicular pain"),
    ("ja-JP", "睾丸の痛みはありません"),
    ("ko-KR", "고환 통증은 없어요"),
    ("vi-VN", "tôi không có đau tinh hoàn dữ dội"),
    ("zh-TW", "我沒有尿不出來的情形"),
    ("ja-JP", "尿閉はありません"),
    ("vi-VN", "tôi chưa bị bí tiểu bao giờ"),
    ("zh-TW", "我沒有大量血尿，也沒有血塊"),
    ("en-US", "patient denies gross hematuria and denies clots"),
    ("ja-JP", "血尿はありません"),
    ("ko-KR", "혈뇨는 없습니다"),
    ("zh-TW", "我沒有發燒也沒有畏寒，小便也不會痛"),
    ("en-US", "no fever, no chills, and no burning when i urinate"),
    ("ko-KR", "열도 없고 오한도 없어요"),
    ("vi-VN", "tôi không sốt và không ớn lạnh"),
    ("zh-TW", "我沒有尿失禁，腳也沒有麻"),
    ("en-US", "no incontinence and no numbness in the legs"),
    ("ja-JP", "尿失禁もしびれもありません"),
    ("ko-KR", "요실금도 없고 다리 저림도 없습니다"),
    ("vi-VN", "tôi không bị són tiểu và không bị tê chân"),
    ("zh-TW", "我沒有意識不清"),
]


@pytest.mark.parametrize("language,text", EXPLICIT_DENIALS)
def test_explicit_denial_is_still_suppressed(detector, language, text):
    """病患明確否認 → 必須抑制。這是政策唯一允許抑制的情況。"""
    assert _crits(detector, text, language) == [], f"{language} {text!r}"


# ── 4b. 「這個部位是正常的」＝明確否認的另一種說法（en/ja/ko/vi 補齊 zh 早有的） ──
# zh 一直有「睪丸沒事／沒問題」的子句尾否認，其他四種語言完全沒有對應。
# 跨症狀組合開放相鄰子句配對之後，這個缺口變成系統性誤報。

# ⚠️ en-US 的兩條已於 2026-07-27 由主 agent 移除：英文的 `(is|feels) fine|normal$`
# 子句尾抑制製造真漏報（"normally i pee fine, but since last night nothing comes out"、
# "usually my urine is normal, but today i cannot pass any urine at all" 兩句
# 教科書級尿滯留一律 0 命中）。根因是英文把「平常是好的」放在**前一個子句**，
# 部位詞只出現在那裡，一旦該出現位置被抑制，主訴子句就沒有部位詞可配對共現組。
# zh/ja/ko/vi 沒這個問題（部位詞會在主訴子句再出現），故保留。
# 代價：那兩句英文會誤報 cauda_equina——依「偏誤報」臨床拍板接受，
# 已移到 test_red_flag_cooccurrence_coverage 的 accepted-over-trigger 清單。
PART_IS_FINE_DENIALS = [
    ("ja-JP", "部屋が熱くて眠れませんでした、排尿は普通です"),
]

PART_IS_FINE_MUST_NOT_SWALLOW = [
    ("en-US", "my leg is fine but i cannot control my bladder and my groin is numb"),
    ("en-US", "everything is normal except i have not been able to pee since last night"),
    ("ja-JP", "熱は普通ですが、尿が全く出なくて下腹がパンパンです"),
    ("ko-KR", "다리는 괜찮은데 소변이 한 방울도 안 나와요"),
    ("vi-VN", "chân thì bình thường nhưng tôi không nhịn được tiểu và bẹn bị tê"),
]


@pytest.mark.parametrize("language,text", PART_IS_FINE_DENIALS)
def test_part_is_fine_is_treated_as_denial(detector, language, text):
    assert _crits(detector, text, language) == [], f"{language} {text!r}"


@pytest.mark.parametrize("language,text", PART_IS_FINE_MUST_NOT_SWALLOW)
def test_part_is_fine_pattern_does_not_swallow_the_real_complaint(
    detector, language, text
):
    """反向：同一句話裡「某部位正常」＋「另一個部位有 critical 症狀」必須命中。

    這是加上該 pattern **唯一**的危險方向，兩邊都釘住才算雙向對稱。
    """
    assert _crits(detector, text, language), f"{language} {text!r}"


# ══════════════════════════════════════════════════════════════════
# 5. 政策接受的誤報：必須**仍然觸發**
# ══════════════════════════════════════════════════════════════════
# 2026-07-27 臨床拍板：「第三人稱轉述、別部位誤配這類殘餘誤報就留著。」
# 寫成正向斷言（不是 xfail）——有人偷加抑制守衛擋掉它時會當場變紅。
# ⚠️ 要改這些期待值需要新的臨床拍板，不是工程可以自行決定。

POLICY_ACCEPTED_FALSE_POSITIVES = [
    ("zh-TW", "我朋友上禮拜尿不出來送急診", "第三人稱轉述"),
    ("zh-TW", "我兒子上個月睪丸很痛，後來開刀", "第三人稱轉述"),
    ("ja-JP", "家族が睾丸の激痛で運ばれたことがあります", "第三人稱轉述"),
    ("en-US", "my brother had sudden testicle pain last year", "第三人稱轉述"),
    ("en-US", "my father had a fever and a urinary infection last month", "第三人稱轉述"),
    ("ko-KR", "고환은 괜찮은데 오늘 아침부터 배가 심하게 아파요", "別部位誤配（無標點）"),
    ("zh-TW", "網路上說睪丸突然劇痛是扭轉，是真的嗎", "轉述網路說法"),
    ("zh-TW", "睪丸突然劇痛的情形我沒有", "否認但語序不符子句尾 pattern"),
]


@pytest.mark.parametrize("language,text,why", POLICY_ACCEPTED_FALSE_POSITIVES)
def test_policy_accepted_false_positive_still_fires(detector, language, text, why):
    """政策接受的誤報 —— 有人加抑制擋掉它就會變紅。"""
    assert _crits(detector, text, language), (
        f"{why}：{language} {text!r} 不再觸發。"
        "依 2026-07-27 臨床拍板（偏誤報），擋掉這類殘餘誤報＝製造漏報風險，"
        "要改期待值需要新的臨床拍板。"
    )


def test_policy_accepted_list_documents_every_entry():
    """每一筆政策接受的誤報都要寫明它是哪一類，防止『懶得修』偽裝成『政策決定』。"""
    for _lang, _text, why in POLICY_ACCEPTED_FALSE_POSITIVES:
        assert why and len(why) >= 5


# ══════════════════════════════════════════════════════════════════
# 6. 單向性：本輪所有改動都只能讓抑制**變少**
# ══════════════════════════════════════════════════════════════════


def test_acute_companion_table_is_a_subset_of_current_episode_markers():
    """急性伴隨症狀是「當前發作證據」的子集（條件句用較嚴的那一半）。"""
    assert set(rfd_module._CURRENT_EPISODE_ACUTE_COMPANIONS) <= set(
        rfd_module._CURRENT_EPISODE_MARKERS
    )
    assert rfd_module._CURRENT_EPISODE_MARKERS == (
        rfd_module._CURRENT_EPISODE_TIME_ANCHORS
        + rfd_module._CURRENT_EPISODE_ACUTE_COMPANIONS
    )


def test_current_episode_markers_stay_disjoint_from_critical_triggers():
    """反向閘門的詞表必須與 critical trigger 字面互斥。

    否則「我想問{trigger}要看哪一科」這種生成式反例會因為 trigger 自帶證據詞而失效。
    第四輪 Gate 新增了「個小時／小時了／個鐘頭」，這條保證它們沒有破壞互斥性。
    """
    from app.pipelines.prompts.shared import URO_RED_FLAGS

    triggers: list[str] = []
    for flag in URO_RED_FLAGS:
        if flag["severity"] != "critical":
            continue
        triggers.extend(flag.get("triggers") or [])
        for kws in (flag.get("triggers_by_lang") or {}).values():
            triggers.extend(kws)
    for marker in rfd_module._CURRENT_EPISODE_MARKERS:
        for trigger in triggers:
            assert marker not in trigger.lower(), (marker, trigger)
