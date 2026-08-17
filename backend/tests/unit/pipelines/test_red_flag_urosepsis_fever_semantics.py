"""urosepsis 共現組「全身感染徵象」軸的語意界線（2026-08-18 臨床拍板）。

═══════════════════════════════════════════════════════════════
臨床拍板（2026-08-18，使用者確認）
═══════════════════════════════════════════════════════════════
實證：session dda55701。病患講「排尿時有灼熱刺痛」這類 **dysuria（排尿局部
灼熱）** ——泌尿科最常見的主訴之一——規則層把它判成 critical **尿路敗血症**
並中止整場問診。

根因不是「誤報太多」而是**詞表寫錯了臨床語意**：urosepsis 的兩個軸是
「泌尿症狀 × **全身性**感染徵象」，而全身徵象軸收了裸「熱」。裸「熱」同時是
  - 全身：発熱／熱が続く／熱っぽい
  - 局部：熱い／熱く／灼熱感／熱熱的／熱辣辣
而 `_collect_all_language_keywords` 與共現組詞表都是**全語言和集合**（W1 設計），
所以日文那一條裸「熱」連中文的「灼熱／熱熱的」一起吃掉。

拍板方向：**「熱」只認全身性發燒語彙（發燒／發熱／體溫／畏寒…），
排除灼熱／刺熱等局部症狀描述。**

⚠️ 這是**語意修正**，不是 #22 意義下的「抑制守衛」——規則本意一直是
「泌尿症狀 ＋ 全身感染徵象」，局部灼熱從來就不屬於後者。但仍按 #22 的舉證
責任逐字面論證「為什麼不會造成漏報」，見 `REMOVED_LITERAL_JUSTIFICATION`。

═══════════════════════════════════════════════════════════════
本檔的設計（依 voice-pipeline-invariants「改偵測邏輯時的測試設計四點」）
═══════════════════════════════════════════════════════════════
1. **雙向對稱**：MUST_FIRE（真發燒＋泌尿）與 MUST_NOT_FIRE（排尿局部灼熱）
   每個受改語言各 ≥3 筆，未受改的三語也各留 ≥3 筆對照（改動不得外溢）。
2. **反例不抄台詞**：語料全部本輪新寫，既不抄 dda55701 逐字稿
   （「尿完刺刺熱熱」「解尿灼熱感」兩句刻意**不**出現在本檔），也不抄
   e2e persona 台詞——由 `test_corpus_is_an_independent_sample` 結構性守住。
3. **oracle 獨立**：期望值是人工臨床標註（每筆都附 `why`），不是拿偵測器
   自己的輸出當基準。
4. 注入式回歸：把裸「熱」加回詞表，MUST_NOT_FIRE 必須轉紅——由
   `test_restoring_the_bare_heat_literal_turns_must_not_fire_red` 就地驗證。

⚠️ 維護規則：修偵測邏輯時不得從這裡刪案例來讓測試變綠。要改期望值必須
   **臨床重新拍板**（前次 2026-08-18），並在另一個方向補對照。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.prompts.shared import URO_RED_FLAGS
from app.pipelines.red_flag_detector import RedFlagDetector

POLICY_DECIDED_ON = "2026-08-18"
UROSEPSIS = "urosepsis"

# 受本輪修改的語言（其餘三語為「審視後維持現狀」的對照組）
MODIFIED_LANGUAGES = ("zh-TW", "ja-JP")
UNMODIFIED_LANGUAGES = ("ko-KR", "en-US", "vi-VN")


def _run(coro):
    return asyncio.run(coro)


class _FakeScalars:
    def all(self) -> list[Any]:
        return []


class _FakeResult:
    def scalars(self) -> _FakeScalars:
        return _FakeScalars()


class _FakeDB:
    async def execute(self, _stmt) -> _FakeResult:
        return _FakeResult()


@pytest.fixture()
def detector(monkeypatch: pytest.MonkeyPatch) -> RedFlagDetector:
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
    settings.RED_FLAG_NEGATION_GUARD = True
    det = RedFlagDetector(settings, _FakeDB())
    _run(det._load_rules())
    return det


def _uro_fired(det: RedFlagDetector, text: str, language: str) -> bool:
    return any(
        alert.get("canonical_id") == UROSEPSIS
        for alert in det._rule_based_detect(text, language)
    )


def _critical_ids(det: RedFlagDetector, text: str, language: str) -> list[str]:
    return [
        alert.get("canonical_id")
        for alert in det._rule_based_detect(text, language)
        if alert.get("severity") == "critical"
    ]


# ══════════════════════════════════════════════════════════════
# §1 MUST_FIRE —— 真的是全身性發燒 ＋ 泌尿症狀
# ══════════════════════════════════════════════════════════════
# 收斂詞表最大的風險方向是把真發燒一起收掉。每個受改語言 ≥3 種發燒描述變體，
# 且刻意包含**不含「發燒／発熱」字面**的口語（報度數、報體溫、講身體很熱、
# 講「燒了幾天」），因為第四輪 Gate 的教訓就是真人不講書面詞。
FEVER_MUST_FIRE: tuple[tuple[str, str, str], ...] = (
    # ── zh-TW（受改語言）──────────────────────────────────
    (
        "zh-TW",
        "昨天下午開始整個人燒了快兩天，小便的次數也變多",
        "口語『燒了』報病程，完全不含『發燒』字面",
    ),
    (
        "zh-TW",
        "我量起來體溫三十八度九，而且解小便會刺痛",
        "報體溫度數（真人最常見的講法）",
    ),
    (
        "zh-TW",
        "身體很熱又一直發冷發抖，右邊腰整個痠痛",
        "全身主體錨點『身體很熱』＋畏寒，泌尿源在腰（腎盂腎炎）",
    ),
    (
        "zh-TW",
        "我從前天就發燒，尿起來很不舒服而且味道很重",
        "書面『發燒』＋泌尿症狀（基準線）",
    ),
    (
        "zh-TW",
        "額頭發燙人也很虛，這兩天小便一直混濁",
        "『額頭發燙』＝全身體溫上升的口語，非局部灼熱",
    ),
    # ── ja-JP（受改語言）──────────────────────────────────
    (
        "ja-JP",
        "一昨日から三十九度近い熱が下がらず、おしっこの回数も増えました",
        "『熱が』＝発熱用法（『熱い』は助詞が付かないので区別できる）",
    ),
    (
        "ja-JP",
        "微熱が続いていて背中の右側が重く痛みます",
        "『微熱』＝発熱専用語、泌尿源は腎区（背中）",
    ),
    (
        "ja-JP",
        "体温を測ったら三十八度五分あって、排尿のときにしみます",
        "体温の実測値（書面語『高熱』を使わない真人語序）",
    ),
    (
        "ja-JP",
        "昨晩から熱を出して寒気もひどく、尿が濁っています",
        "『熱を出す』＝発熱の慣用表現",
    ),
    (
        "ja-JP",
        "発熱と震えがあって、膀胱のあたりが張っています",
        "書面『発熱』（基準線）",
    ),
    # ── 未受改語言（對照組：改動不得外溢成漏報）─────────────
    (
        "ko-KR",
        "그저께부터 열이 삼십팔도가 넘고 소변 볼 때 시려요",
        "'열이' 조사형 = 발열 용법",
    ),
    (
        "ko-KR",
        "발열이랑 오한이 같이 오고 옆구리가 묵직하게 아파요",
        "'발열' + '오한' = 전형적 전신 감염 징후",
    ),
    (
        "ko-KR",
        "미열이 계속되면서 방광 쪽이 계속 불편해요",
        "'미열' = 발열 전용어",
    ),
    (
        "en-US",
        "i have been running a temperature since friday and my urine looks cloudy",
        "temperature（不含 fever 字面）",
    ),
    (
        "en-US",
        "shivering all night with a fever and my flank is really sore",
        "fever + shiver + flank（腎區）",
    ),
    (
        "en-US",
        "febrile since the weekend and it stings every time i pass urine",
        "febrile（書面）＋ dysuria 併存 → 仍必命中",
    ),
    (
        "vi-VN",
        "hai hôm nay tôi sốt liên tục và nước tiểu có mùi rất nặng",
        "sốt（越南文主要發燒詞）",
    ),
    (
        "vi-VN",
        "tôi bị ớn lạnh run người và đau vùng hông bên phải",
        "ớn lạnh（畏寒）＋ 腎區",
    ),
    (
        "vi-VN",
        "sốt kèm run lạnh, bàng quang căng tức khó chịu",
        "sốt + run lạnh + 膀胱",
    ),
)


# ══════════════════════════════════════════════════════════════
# §2 MUST_NOT_FIRE —— 排尿局部灼熱（dysuria），不是全身感染徵象
# ══════════════════════════════════════════════════════════════
# ⚠️ 措辭刻意**不**使用 dda55701 逐字稿的兩句（「尿完刺刺熱熱」「解尿灼熱感」）
#    也不抄任何 e2e persona 台詞——反例與實作／驗收語料同源就是第三輪的假象來源。
DYSURIA_MUST_NOT_FIRE: tuple[tuple[str, str, str], ...] = (
    # ── zh-TW（受改語言）──────────────────────────────────
    (
        "zh-TW",
        "這幾天解小便到最後會有一股燙燙刺刺的感覺",
        "局部灼熱＝dysuria 主訴本身，不是全身發燒",
    ),
    (
        "zh-TW",
        "尿道口那邊熱辣辣的，尤其排尿快結束的時候最明顯",
        "『熱辣辣』是部位形容詞，主體是尿道口不是身體",
    ),
    (
        "zh-TW",
        "小便的時候會有點灼熱刺痛，其他都還好",
        "教科書級 dysuria 描述，病患一講就被中止＝最不該發生的事",
    ),
    (
        "zh-TW",
        "上廁所時感覺尿道裡面熱熱的又有點痛",
        "『熱熱的』修飾尿道，非體溫",
    ),
    # ── ja-JP（受改語言）──────────────────────────────────
    (
        "ja-JP",
        "排尿の最後に尿道が熱くてヒリヒリします",
        "『熱くて』＝局所の灼熱感（形容詞、助詞が付かない）",
    ),
    (
        "ja-JP",
        "トイレに行くたびに尿道の灼熱感が強くなります",
        "『灼熱感』＝dysuria の医学的表現",
    ),
    (
        "ja-JP",
        "おしっこがいつもより熱く感じて少ししみます",
        "尿そのものが熱いという主観、全身徴候ではない",
    ),
    (
        "ja-JP",
        "昨日は部屋が熱すぎて汗をかきましたが、排尿の回数はいつも通りです",
        "『熱い』の主語が部屋＝環境温度（全言語和集合の巻き添えの典型）",
    ),
    # ── 未受改語言（對照組：本來就不誤報，釘住以防外溢）───────
    (
        "ko-KR",
        "소변을 다 보고 나면 요도가 쓰라리고 따가워요",
        "한국어 dysuria 표현은 따갑다/쓰라리다 → '열' 계열에 걸리지 않음",
    ),
    (
        "ko-KR",
        "오줌 눌 때마다 아래쪽이 화끈거리는 느낌이 있어요",
        "'화끈거리다' = 국소 작열감",
    ),
    (
        "ko-KR",
        "배뇨 끝날 무렵에 요도에 작열감만 조금 있습니다",
        "'작열감' 은 '열이/열나' 어느 것에도 해당하지 않음",
    ),
    (
        "en-US",
        "there is a hot stinging feeling at the tip whenever i finish peeing",
        "hot 不在感染徵象軸；stinging 是 dysuria",
    ),
    (
        "en-US",
        "passing urine gives me a scalding pain in the urethra",
        "scalding＝局部灼熱",
    ),
    (
        "en-US",
        "every time i urinate there is a burning sensation but nothing else",
        "burning sensation 是最典型的 dysuria 英文說法",
    ),
    (
        "vi-VN",
        "mỗi lần đi tiểu tôi thấy nóng rát ở cuối bãi",
        "nóng rát＝局部灼熱；裸 nóng 不在詞表",
    ),
    (
        "vi-VN",
        "niệu đạo có cảm giác bỏng rát khi tiểu xong",
        "bỏng rát＝灼傷感，局部",
    ),
    (
        "vi-VN",
        "tiểu hơi buốt và hơi nóng ở đầu, ngoài ra bình thường",
        "buốt/nóng 局部，無全身徵象",
    ),
)


# ══════════════════════════════════════════════════════════════
# §3 對稱硬條件 —— 同一句灼熱描述**另外**含真發燒詞就必須命中
# ══════════════════════════════════════════════════════════════
# 這一節是 §2 的承重對照：沒有它，把整個感染徵象軸刪掉也能讓 §2 全綠。
DYSURIA_PLUS_REAL_FEVER_MUST_FIRE: tuple[tuple[str, str, str], ...] = (
    (
        "zh-TW",
        "這幾天解小便到最後會有一股燙燙刺刺的感覺，而且我發燒到三十八度七",
        "§2 第 1 句 ＋ 真發燒 → 必須翻回命中",
    ),
    (
        "zh-TW",
        "尿道口那邊熱辣辣的，昨天晚上開始還一直發冷發抖",
        "§2 第 2 句 ＋ 畏寒",
    ),
    (
        "ja-JP",
        "排尿の最後に尿道が熱くてヒリヒリしますが、微熱も続いています",
        "§2 第 5 句 ＋ 微熱",
    ),
    (
        "ja-JP",
        "トイレに行くたびに尿道の灼熱感が強くなり、熱が三十八度あります",
        "§2 第 6 句 ＋『熱が』",
    ),
    (
        "ko-KR",
        "오줌 눌 때마다 아래쪽이 화끈거리는데 열이 삼십구도까지 올랐어요",
        "'화끈거리다' + '열이' → 필히 명중",
    ),
    (
        "en-US",
        "every time i urinate there is a burning sensation and i also have a fever",
        "burning sensation + fever → must still fire",
    ),
    (
        "vi-VN",
        "mỗi lần đi tiểu tôi thấy nóng rát ở cuối bãi và tôi đang sốt cao",
        "nóng rát + sốt → vẫn phải bắt",
    ),
)


@pytest.mark.parametrize(
    "language,text,why",
    FEVER_MUST_FIRE,
    ids=[f"{lg}-{t[:16]}" for lg, t, _w in FEVER_MUST_FIRE],
)
def test_systemic_fever_with_urinary_symptom_must_fire(detector, language, text, why):
    """全身性發燒 ＋ 泌尿症狀 → urosepsis 必須命中（漏報不可逆）。"""
    assert _uro_fired(detector, text, language), (
        f"urosepsis 漏報（under-triage，不可逆）：{language} {text!r}\n"
        f"  臨床標註：{why}\n"
        f"  收斂感染徵象軸時把真發燒語彙一起收掉了——這正是 2026-08-18 拍板"
        f"『只排除局部灼熱』所禁止的方向。"
    )


@pytest.mark.parametrize(
    "language,text,why",
    DYSURIA_MUST_NOT_FIRE,
    ids=[f"{lg}-{t[:16]}" for lg, t, _w in DYSURIA_MUST_NOT_FIRE],
)
def test_local_burning_on_urination_must_not_fire(detector, language, text, why):
    """排尿局部灼熱（dysuria）→ 不得判成 critical 尿路敗血症。

    2026-08-18 臨床拍板：dysuria 是泌尿科最常見主訴之一，病患一講出自己的
    主訴就被中止問診，與 #22 對 `gross_hematuria_heavy` 的判斷同型
    （判準要照臨床定義，不是照字面）。
    """
    assert not _uro_fired(detector, text, language), (
        f"dysuria 被判成尿路敗血症 → 病患講出主訴就被中止：{language} {text!r}\n"
        f"  臨床標註：{why}\n"
        f"  （臨床拍板日 {POLICY_DECIDED_ON}）"
    )


@pytest.mark.parametrize(
    "language,text,why",
    DYSURIA_PLUS_REAL_FEVER_MUST_FIRE,
    ids=[f"{lg}-{t[:16]}" for lg, t, _w in DYSURIA_PLUS_REAL_FEVER_MUST_FIRE],
)
def test_local_burning_plus_real_fever_still_fires(detector, language, text, why):
    """對稱硬條件：灼熱描述**另外**含真發燒詞 → 照樣命中。

    沒有這一節，把整個感染徵象軸刪光也能讓 MUST_NOT_FIRE 全綠。
    """
    assert _uro_fired(detector, text, language), (
        f"灼熱＋真發燒仍漏報 → 收斂收過頭了：{language} {text!r}\n  臨床標註：{why}"
    )


# ══════════════════════════════════════════════════════════════
# §4 跨輪累積（前輪發燒 ＋ 本輪腰痛）不得因本次改動失效
# ══════════════════════════════════════════════════════════════
# 規則層**只看本輪這句話**（見 red_flag_detector 的「語意層的對話歷史」段），
# 所以跨輪累積型 urosepsis 的唯一通路是語意層 + conversation_summary。
# 本次改的是共現組詞表（規則層），照設計不該碰到那條路——這兩條測試就是
# 把「不該碰到」變成會紅的斷言。


def test_cross_turn_fever_then_flank_pain_survives_semantic_path(monkeypatch):
    """前輪發燒、本輪只講腰痛 → 語意層判出的 urosepsis 必須活著出到 detect()。

    這條路徑會被殺掉的方式是否定幻覺後過濾（`_canonical_denied_in_text`）
    把它濾掉。該過濾讀的是 canonical `triggers`（高燒/寒顫/…），**不是**共現組
    詞表，所以本次改動不影響——但那是讀碼推論，這裡把它釘成行為斷言。
    """
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
    settings.RED_FLAG_NEGATION_GUARD = True
    det = RedFlagDetector(settings, _FakeDB())

    async def _fake_semantic(text, session_context, language=None):
        # 語意層看得到 conversation_summary 才推得出跨輪組合——先斷言它真的到得了。
        assert "發燒" in str(session_context.get("conversation_summary"))
        return [
            {
                "canonical_id": UROSEPSIS,
                "severity": "critical",
                "title": "尿路敗血症",
                "description": "前輪發燒 ＋ 本輪腰痛",
                "trigger_reason": "病患前一輪說有發燒，本輪說右腰痛",
                "alert_type": "semantic",
                "trigger_keywords": None,
                "llm_analysis": {"model": "gpt-4o-mini"},
                "confidence": "semantic_only",
                "suggested_actions": [],
                "matched_rule_id": None,
            }
        ]

    monkeypatch.setattr(det, "_semantic_detect", _fake_semantic)

    alerts = _run(
        det.detect(
            "今天右邊腰一直很痛",
            {
                "session_id": "t",
                "language": "zh-TW",
                "conversation_summary": "病患：我昨天開始發燒\nAI：還有其他不舒服嗎",
            },
        )
    )
    ids = [a.get("canonical_id") for a in alerts if a.get("severity") == "critical"]
    assert UROSEPSIS in ids, f"跨輪累積型 urosepsis 在語意層路徑上消失了：{alerts}"


def test_same_turn_fever_plus_flank_pain_still_fires_in_rule_layer(detector):
    """兩個症狀落在同一輪（有標點的相鄰子句）→ 規則層仍要接得住。

    這是 `cross_clause: True` 的承重點，也是跨輪案例在規則層唯一測得到的形狀。
    """
    assert _uro_fired(detector, "我昨天開始發燒，今天右邊腰一直很痛", "zh-TW")
    assert _uro_fired(detector, "昨日から熱が出ていて、今日は腰が痛いです", "ja-JP")


# ══════════════════════════════════════════════════════════════
# §5 注入式回歸（把修復故意改壞，確認會紅）
# ══════════════════════════════════════════════════════════════


def _uro_group() -> dict[str, Any]:
    for flag in URO_RED_FLAGS:
        if flag["canonical_id"] == UROSEPSIS:
            return (flag.get("trigger_cooccurrence") or [])[0]
    raise AssertionError("urosepsis 共現組不見了")


def test_restoring_the_bare_heat_literal_turns_must_not_fire_red(detector):
    """注入式回歸：把裸「熱」加回感染徵象軸 → MUST_NOT_FIRE 必須整批轉紅。

    voice-pipeline-invariants「測試設計四點」第 4 點：把修復故意改壞，確認
    有測試會紅，再還原。沒有這條，詞表被人還原時上面那批 MUST_NOT_FIRE
    可能因為別的原因（例如語料剛好都被否定守衛擋住）繼續全綠 ＝ 假保護。
    """
    group = _uro_group()
    original = list(group["acuity_terms"])
    # 期望：受改語言中**字面含「熱」**的 dysuria 語料，全部應該因裸「熱」重新誤報。
    # （「燙燙刺刺」那筆不含「熱」，它本來就靠別的字面差異倖免，不列入本條的期望，
    #   但仍留在 MUST_NOT_FIRE 裡當語料——那是臨床反例，不是這條的對照。）
    expected = [
        (lg, t)
        for lg, t, _w in DYSURIA_MUST_NOT_FIRE
        if lg in MODIFIED_LANGUAGES and "熱" in t
    ]
    assert len(expected) >= 6, "受改語言含「熱」字面的反例太少，注入回歸沒有承重"
    try:
        group["acuity_terms"] = original + ["熱"]
        regressed = [
            (lg, t)
            for lg, t, _w in DYSURIA_MUST_NOT_FIRE
            if (lg, t) in expected and _uro_fired(detector, t, lg)
        ]
        assert regressed == expected, (
            "把裸「熱」加回去之後，MUST_NOT_FIRE 沒有整批轉紅 → 那批斷言其實不是"
            "被本次詞表收斂保護的，是假保護。\n"
            f"  預期轉紅：{[t for _l, t in expected]}\n"
            f"  實際轉紅：{[t for _l, t in regressed]}"
        )
    finally:
        group["acuity_terms"] = original
    # 還原後必須回到綠的
    for lg, text, _why in DYSURIA_MUST_NOT_FIRE:
        assert not _uro_fired(detector, text, lg), f"還原失敗：{lg} {text!r}"


# ══════════════════════════════════════════════════════════════
# §6 結構性守衛
# ══════════════════════════════════════════════════════════════

# 被移除／收窄的字面 → 「為什麼不會造成漏報」的逐條舉證（#22）
REMOVED_LITERAL_JUSTIFICATION: dict[str, str] = {
    "熱（裸字，原掛在 ja-JP 段）": (
        "唯一被移除的字面。它的發燒用法在日文一律帶助詞或接尾（熱が／熱も／熱で／"
        "熱です／熱を出す／度の熱／微熱／発熱／高熱／熱っぽい），這些已逐一收錄，"
        "所以日文發燒側零損失；實測「三十八度台の熱が続いて」「熱を出して」"
        "「微熱が続いて」「体温を測ったら」四種真人語序都仍命中。"
        "它的中文側從來就不是有意收錄（zh 段本來就只有發燒/高燒/燒到/發熱/體溫），"
        "是全語言和集合的巻き添え；為補上中文口語缺口另外收了"
        "「燒了／在燒／身體很熱／全身很熱／渾身很熱／額頭發燙…」，"
        "這些都帶**全身性主體錨點**，只多不少。"
        "剩下唯一真的會漏的形狀是「熱」單獨成句且不帶助詞（日文『熱、あります』），"
        "但那不是自然口語，且語意層（LLM）獨立跑，仍是後備。"
    ),
}


def test_every_removed_literal_has_a_no_miss_argument():
    """#22 舉證責任：每一個被移除的字面都要能說出「為什麼不會造成漏報」。"""
    assert REMOVED_LITERAL_JUSTIFICATION
    for literal, why in REMOVED_LITERAL_JUSTIFICATION.items():
        assert why and len(why) >= 60, f"{literal} 沒有實質的無漏報論證"


def test_acuity_axis_contains_no_local_burning_literal():
    """感染徵象軸不得再收任何**局部灼熱**字面。

    這是詞表層的界線；行為層由 §2 釘住。兩層都要，因為有人可能改的是
    `_iter_keyword_occurrences` 而不是詞表。
    """
    acuities = {t for t in _uro_group()["acuity_terms"]}
    forbidden = (
        "熱",  # 裸字（日文形容詞「熱い」＋中文「灼熱」の巻き添え）
        "灼熱",
        "熱い",
        "熱く",
        "熱感",
        "화끈",
        "작열",
        "nóng rát",
        "bỏng rát",
        "burning sensation",
        "scalding",
    )
    offenders = [t for t in acuities if t in forbidden]
    assert offenders == [], (
        f"局部灼熱字面回到 urosepsis 感染徵象軸：{offenders}。"
        f"要改需臨床重新拍板（前次 {POLICY_DECIDED_ON}）。"
    )


def test_acuity_axis_still_has_a_fever_term_in_all_five_languages():
    """對照組：收斂不得把任一語言的發燒側整個收光（那就是漏報）。"""
    acuities = {t for t in _uro_group()["acuity_terms"]}
    per_language = {
        "zh-TW": ("發燒", "高燒", "發熱", "體溫"),
        "ja-JP": ("発熱", "高熱", "微熱", "熱が", "体温"),
        "ko-KR": ("열이", "발열", "고열", "미열"),
        "en-US": ("fever", "febrile", "temperature"),
        "vi-VN": ("sốt",),
    }
    for language, probes in per_language.items():
        assert any(p in acuities for p in probes), (
            f"{language} 的發燒側被收光 → 該語言的規則層 fallback 死掉"
        )


@pytest.mark.parametrize("language", MODIFIED_LANGUAGES + UNMODIFIED_LANGUAGES)
def test_every_language_is_covered_in_both_directions(language):
    """五語言在兩個方向都要有語料，否則這份表又退化成單向。"""
    fire = [t for lg, t, _w in FEVER_MUST_FIRE if lg == language]
    miss = [t for lg, t, _w in DYSURIA_MUST_NOT_FIRE if lg == language]
    assert len(fire) >= 3, f"{language} 的 MUST_FIRE 語料不足：{len(fire)}"
    assert len(miss) >= 3, f"{language} 的 MUST_NOT_FIRE 語料不足：{len(miss)}"


def test_every_case_has_a_human_clinical_annotation():
    """oracle 獨立性：期望值必須是人工臨床標註，不是偵測器輸出。"""
    for _lg, text, why in (
        FEVER_MUST_FIRE + DYSURIA_MUST_NOT_FIRE + DYSURIA_PLUS_REAL_FEVER_MUST_FIRE
    ):
        assert why and len(why) >= 8, f"缺臨床標註：{text!r}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def test_corpus_is_an_independent_sample():
    """語料不得與 e2e persona 台詞／既有紅旗測試語料重複。

    第三輪的假象就是「驗收套件證明的是這句台詞會命中，不是這個臨床情境會命中」。
    dda55701 逐字稿的兩句（「尿完刺刺熱熱」「解尿灼熱感」）也刻意不出現在本檔。
    """
    fresh = FEVER_MUST_FIRE + DYSURIA_MUST_NOT_FIRE + DYSURIA_PLUS_REAL_FEVER_MUST_FIRE
    sources = [
        _repo_root() / "scripts" / "e2e_realopenai" / "driver.py",
        Path(__file__).with_name("test_red_flag_over_trigger.py"),
        Path(__file__).with_name("test_red_flag_cooccurrence.py"),
        Path(__file__).with_name("test_red_flag_cooccurrence_coverage.py"),
        Path(__file__).with_name("test_red_flag_gate3_bidirectional_probe.py"),
        Path(__file__).with_name("test_red_flag_gate4_bidirectional.py"),
        Path(__file__).with_name("test_red_flag_suppression_policy.py"),
    ]
    blobs = []
    for path in sources:
        if path.exists():
            blobs.append((path.name, re.sub(r"\s+", " ", path.read_text("utf-8"))))
    assert blobs, "找不到任何比對來源，這條結構性測試會變成空跑"

    overlaps = []
    for _language, text, _why in fresh:
        needle = re.sub(r"\s+", " ", text).strip()
        for name, blob in blobs:
            if needle in blob:
                overlaps.append((name, text))
    assert not overlaps, f"語料與既有來源重複（＝拿實作配適測試）：{overlaps}"

    # dda55701 逐字稿原句不得被抄進**語料**（寫在說明段落裡是可以的）
    evidence_transcript_lines = ("尿完刺刺熱熱", "解尿灼熱感")
    for _language, text, _why in fresh:
        for line in evidence_transcript_lines:
            assert line not in text, (
                f"逐字稿原句 {line!r} 被抄進語料 → 反例與實證同源，"
                "等於拿實作配適測試"
            )


def test_bare_local_burning_does_not_fire_any_other_critical_flag(detector):
    """外溢守衛：dysuria 語料也不得命中**別的** critical 紅旗。

    只看 urosepsis 會漏掉「改完之後改由 renal_colic_with_fever 誤中止」這種
    橫向位移——一樣是誤中止整場問診。
    """
    for language, text, _why in DYSURIA_MUST_NOT_FIRE:
        assert _critical_ids(detector, text, language) == [], (
            f"dysuria 語料命中別的 critical → 仍會誤中止：{language} {text!r}"
        )
