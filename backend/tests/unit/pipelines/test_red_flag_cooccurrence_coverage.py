"""另外 4 個 critical 紅旗的共現組**雙向對稱**測試表（第四輪 Gate）。

為什麼要有這個檔案
────────────────────────────────────────
第三輪把「相鄰複合子字串」換成共現組，但**只換在 `testicular_pain_severe`
一個紅旗上**。另外 4 個 critical（urinary_retention / gross_hematuria_heavy /
urosepsis / cauda_equina_suspected）仍然是純相鄰比對，而且從來沒有人用真人語序
驗證過它們。

2026-07-27 第四輪 Gate 對這 4 個紅旗做 5 語 × ≥3 種真人語序的直接探針
（用 `_rule_based_detect` 真跑，不是重寫比對邏輯）：**61 句真急症描述裡 60 句
0 命中**，唯一命中的那句還只是因為病患剛好講了書面詞「오한」。也就是說在改動前，
規則層對這 4 個紅旗**在五種語言都等於不存在**——而規則層正是語意層漏判時的
fallback（不變式 #9）。

漏報的形狀與睪丸扭轉 (C) 完全相同：中日韓越會在兩個語意成分之間插入時間、方位、
量詞、程度詞，相鄰子字串一條都接不到；英文則是同一件事的語序自由。

  「小便**一滴都**出不來」            ←「尿不出來」不相鄰
  「尿が**全く**出ません」            ←「尿が出ない」不相鄰
  「소변이 **한 방울도** 안 나와」    ←「소변이 안 나와요」不相鄰
  「tiểu mà **không tiểu được**」     ←「không đi tiểu được」缺「đi」
  「我發燒**到三十九度而且**小便的時候很痛」←「發燒加排尿痛」不相鄰

本檔守護的事
────────────────────────────────────────
1. `MUST_FIRE`         ：4 個紅旗 × 5 語 × ≥3 種真人語序，全部要命中。
2. `MUST_NOT_FIRE`     ：慢性/良性、明確否認、時態否定、行政詢問、主訴標籤複誦、
                         單一維度、非症狀陳述，全部不得命中。**與 1. 對稱**。
3. `ACCEPTED_OVER_TRIGGER`：使用者已拍板「偏誤報」，第三人稱轉述這類殘餘誤報
                         **寫成正向測試**（斷言它就是會觸發），不用 xfail 掩蓋，
                         也不准有人事後偷加抑制守衛把它擋掉。
4. `KNOWN_RESIDUAL_MISS`：改不動的漏報（根因在 red_flag_detector，不在本輪
                         檔案所有權內），用 xfail(strict) 釘住，修好會自動變紅。
5. 結構不變式          ：共現詞表不得混入裸痛詞／裸量詞；血尿的量詞必須自帶血語意
                         （否則頻尿主訴會全變 critical）；語料不得抄 e2e persona 台詞。

⚠️ 加任何一條 `MUST_FIRE` 都必須同時想「這個新形狀會不會讓某句良性描述也命中」，
   並把那句良性描述加進 `MUST_NOT_FIRE`。單方向加測試已經害過這條管線三次。
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.prompts.shared import URO_RED_FLAGS
from app.pipelines.red_flag_detector import RedFlagDetector
from app.utils.complaint_fallback_i18n import NAME_FALLBACK_I18N

LANGUAGES = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")

RETENTION = "urinary_retention"
HEMATURIA_HEAVY = "gross_hematuria_heavy"
UROSEPSIS = "urosepsis"
CAUDA = "cauda_equina_suspected"
NEW_COOCCURRENCE_FLAGS = (RETENTION, HEMATURIA_HEAVY, UROSEPSIS, CAUDA)


# ── detector 腳手架（空表 → fallback 內建 catalogue，與正式路徑同一條）──


class _FakeScalars:
    def all(self) -> list[Any]:
        return []


class _FakeResult:
    def scalars(self) -> _FakeScalars:
        return _FakeScalars()


class _FakeDB:
    async def execute(self, _stmt) -> _FakeResult:
        return _FakeResult()


@pytest.fixture
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
    asyncio.run(det._load_rules())
    return det


def _fired(det: RedFlagDetector, canonical_id: str, text: str, language: str) -> bool:
    return any(
        a["canonical_id"] == canonical_id
        for a in det._rule_based_detect(text, language)
    )


def _critical_hits(det: RedFlagDetector, text: str, language: str) -> list[tuple]:
    return [
        (a["canonical_id"], a.get("trigger_keywords"))
        for a in det._rule_based_detect(text, language)
        if a.get("severity") == "critical"
    ]


# ══════════════════════════════════════════════════════════════
# 1. MUST_FIRE — 真急症的真人語序（4 紅旗 × 5 語 × ≥3 種語序）
# ══════════════════════════════════════════════════════════════
# 標 [P] 的是第四輪 Gate 直接探針裡實測 0 命中的那 60 句之一。
# 措辭刻意不抄 scripts/e2e_realopenai/results/*.json 的 persona 台詞
# （由 test_corpus_is_not_copied_from_real_transcripts 釘住）。

MUST_FIRE: list[tuple[str, str, str, str]] = [
    # ── urinary_retention ────────────────────────────────
    (RETENTION, "zh-TW", "我從今天早上開始就完全解不出來，膀胱脹到受不了",
     "[P] 解不出『來』≠『小便』；膀胱脹到"),
    (RETENTION, "zh-TW", "小便一滴都出不來，下腹脹得很痛",
     "[P] 動作詞與『出不來』間插入量詞"),
    (RETENTION, "zh-TW", "膀胱脹得像球一樣，想尿卻尿不出半滴",
     "[P] 『尿不出來』缺『來』"),
    (RETENTION, "zh-TW", "已經快十個小時沒辦法上小號了，肚子鼓鼓的很痛",
     "[P] 口語『上小號』＋否定詞開頭"),
    (RETENTION, "en-US",
     "I haven't been able to pee since last night and my lower belly is rock hard",
     "[P] unable to pee 不相鄰"),
    (RETENTION, "en-US",
     "nothing comes out at all when I try to urinate and it is agony",
     "[P] 修飾詞在動作詞之前"),
    (RETENTION, "en-US",
     "my bladder feels like it will burst but no urine will come out",
     "[P] 書面語序＋轉折句"),
    (RETENTION, "ja-JP", "昨日の夜から全然おしっこが出なくて下腹が張って痛いです",
     "[P] 口語『おしっこ』"),
    (RETENTION, "ja-JP", "トイレに行っても尿が全く出なくて膀胱がパンパンです",
     "[P] 『尿が出ない』の間に『全く』"),
    (RETENTION, "ja-JP", "朝から一滴も排尿できていません、下腹部が苦しいです",
     "[P] 『排尿できない』の活用違い"),
    (RETENTION, "ko-KR", "어젯밤부터 소변이 한 방울도 안 나와서 아랫배가 너무 아파요",
     "[P] 『소변이 안 나와요』사이 삽입"),
    (RETENTION, "ko-KR", "화장실에 가도 소변이 전혀 안 나옵니다",
     "[P] 종결어미 차이"),
    (RETENTION, "ko-KR", "아침부터 오줌을 못 누고 있어요 배가 빵빵합니다",
     "[P] 구어『오줌』＋무구두점"),
    (RETENTION, "vi-VN", "tôi mót tiểu mà không tiểu được, bụng dưới căng tức",
     "[P] 『không đi tiểu được』thiếu『đi』"),
    (RETENTION, "vi-VN", "nước tiểu không ra được chút nào, bàng quang căng đau",
     "[P] chủ ngữ là nước tiểu"),
    (RETENTION, "vi-VN",
     "từ sáng nay tôi rặn mãi mà không ra được giọt nước tiểu nào",
     "[P] trật tự đảo，動作詞『rặn』是唯一沒被否定詞蓋到的足場"),
    # ── gross_hematuria_heavy ────────────────────────────
    (HEMATURIA_HEAVY, "zh-TW", "今天早上尿出來整個馬桶都是血，還有一坨一坨的東西",
     "[P] 『整個都是血』不相鄰"),
    (HEMATURIA_HEAVY, "zh-TW", "小便裡面血很多，紅得跟葡萄酒一樣",
     "[P] 『血尿很多』不相鄰"),
    (HEMATURIA_HEAVY, "zh-TW", "我昨天晚上尿了好多血，衛生紙擦下去整片紅",
     "[P] 『一大堆血』的口語變體"),
    (HEMATURIA_HEAVY, "en-US",
     "there was a huge amount of blood in my urine this morning",
     "[P] lots of blood 不相鄰"),
    (HEMATURIA_HEAVY, "en-US",
     "my urine is completely red and there were clots the size of grapes",
     "[P] clots 單獨出現"),
    (HEMATURIA_HEAVY, "en-US", "I passed a lot of blood when I peed last night",
     "[P] 量詞在動作詞之前"),
    # ⚠️「尿の色が真っ赤で量もかなり多いです」曾在這裡（要求 heavy=critical）。
    # 2026-07-27 主 agent 移出：這句的 heavy 訊號只有「量も多い」，而裸量詞不能收
    #（見 test_hematuria_volume_terms_all_carry_a_blood_concept——「尿の量が多い」＝多尿，
    #  收了會讓頻尿主訴被判 critical 並第 1 輪 abort）。真っ赤 是顏色，已降到
    # gross_hematuria(high)。這句現在得到 high 警示但不中止問診，是刻意的：
    # 顏色＋尿量在結構上無法與多尿區分，而血塊／血量詞（血がたくさん／血の塊／かたまり）
    # 仍然照常判 critical——下一行與再下一行就是。
    (HEMATURIA_HEAVY, "ja-JP", "今朝トイレでおしっこに血がたくさん混じっていました",
     "[P] 口語部位＋量"),
    # 2026-07-27 主 agent 補：取代被移出的「真っ赤で量も多い」（顏色＋裸量詞，
    # 已降級到 high）。這句的 heavy 訊號是**血塊**，不是顏色，所以仍是 critical。
    (HEMATURIA_HEAVY, "ja-JP", "トイレに行くたびに血の混じったかたまりが出てきます",
     "[P] 部位詞在句頭、血塊詞在句尾（語序變體）"),
    (HEMATURIA_HEAVY, "ja-JP", "昨夜から小便に血の混じったかたまりが出ます",
     "[P] 『血の塊』不連続"),
    (HEMATURIA_HEAVY, "ko-KR", "오늘 아침 소변에 피가 아주 많이 섞여 나왔어요",
     "[P] 어순 차이"),
    (HEMATURIA_HEAVY, "ko-KR", "어젯밤부터 오줌이 새빨갛고 덩어리도 나옵니다",
     "[P] 『새빨간 소변』불연속"),
    (HEMATURIA_HEAVY, "ko-KR", "소변에 핏덩어리가 계속 나와서 무섭습니다",
     "[P] 구어『핏덩어리』"),
    (HEMATURIA_HEAVY, "vi-VN", "sáng nay tôi đi tiểu ra rất nhiều máu",
     "[P] chèn『rất』vào giữa"),
    (HEMATURIA_HEAVY, "vi-VN", "nước tiểu của tôi đỏ tươi và có cục máu đông",
     "[P] cục máu đông tách khỏi cụm"),
    (HEMATURIA_HEAVY, "vi-VN", "tối qua tôi tiểu ra máu nhiều lắm, kèm theo cục nhỏ",
     "[P] trật tự khác"),
    # ── urosepsis（跨症狀組合）───────────────────────────
    (UROSEPSIS, "zh-TW", "我發燒到三十九度而且小便的時候很痛",
     "[P] 病患報度數而非『高燒』"),
    (UROSEPSIS, "zh-TW", "這兩天一直發冷發抖小便又痛又急",
     "[P] 『寒顫』的口語＋無標點"),
    (UROSEPSIS, "zh-TW", "昨天晚上開始燒起來腰也痠痛小便混濁有味道",
     "[P] 腎盂腎炎語序"),
    (UROSEPSIS, "en-US",
     "I have had a fever of thirty nine since yesterday and burning when I pee",
     "[P] high fever 不相鄰"),
    (UROSEPSIS, "en-US",
     "I was shivering uncontrollably last night and my flank hurts when I urinate",
     "[P] chills 的自然說法"),
    (UROSEPSIS, "en-US", "running a temperature and my urine smells foul and cloudy",
     "[P] 口語 temperature"),
    (UROSEPSIS, "ja-JP", "昨夜から三十八度台の熱が続いていて排尿のときに痛みがあります",
     "[P] 『高熱』ではなく『熱』"),
    (UROSEPSIS, "ja-JP", "寒気がして体が震えるしおしっこも痛いです",
     "[P] 『悪寒』の口語（無句読点）"),
    (UROSEPSIS, "ja-JP", "熱っぽくて背中も痛くて尿が濁っています",
     "[P] 腎盂腎炎の語順"),
    (UROSEPSIS, "ko-KR", "어제부터 열이 삼십구도까지 오르고 소변볼 때 아파요",
     "[P] 『고열』이 아닌 『열이』"),
    (UROSEPSIS, "ko-KR", "몸이 계속 떨리고 오한이 나면서 소변이 탁해요",
     "오한＋배뇨증상（改動前唯一命中的對照組，不得倒退）"),
    (UROSEPSIS, "ko-KR", "열도 나고 옆구리가 아프면서 오줌 냄새가 심해요",
     "[P] 신우신염 어순"),
    (UROSEPSIS, "vi-VN", "từ tối qua tôi sốt gần bốn mươi độ và tiểu buốt",
     "[P] 『sốt cao』không liền"),
    (UROSEPSIS, "vi-VN", "tôi rét run cả người và nước tiểu đục có mùi hôi",
     "[P] ớn lạnh biến thể"),
    (UROSEPSIS, "vi-VN", "sốt và đau hông lưng khi đi tiểu từ hôm qua",
     "[P] trật tự khác"),
    # ── cauda_equina_suspected（跨症狀組合）──────────────
    (CAUDA, "zh-TW", "屁股跟大腿內側這兩天都麻麻的小便也開始會漏出來",
     "[P] 『會陰麻木』的口語（無標點）"),
    (CAUDA, "zh-TW", "腰痛得很厲害兩隻腳越來越沒力昨天開始尿失禁",
     "[P] 『下肢無力』→『腳沒力』"),
    (CAUDA, "zh-TW", "會陰部位整片麻掉了這兩天尿褲子好幾次",
     "[P] 『會陰麻木』插入『部位整片』"),
    (CAUDA, "en-US",
     "my inner thighs have gone numb and I have been leaking urine since yesterday",
     "[P] saddle anesthesia 的白話"),
    (CAUDA, "en-US", "both legs feel weak and I wet myself twice today",
     "[P] leg weakness 不相鄰"),
    (CAUDA, "en-US",
     "numbness around my groin and I cannot control my bladder anymore",
     "[P] 『cannot control』——否定詞開頭才躲得過否定守衛"),
    (CAUDA, "ja-JP", "お尻の周りがしびれていて昨日から尿を漏らすようになりました",
     "[P] 『会陰部のしびれ』の口語"),
    (CAUDA, "ja-JP", "両足に力が入らなくておしっこも漏れてしまいます",
     "[P] 『下肢の脱力』の言い換え（無句読点）"),
    (CAUDA, "ja-JP", "股のあたりの感覚が鈍くて尿失禁が出てきました",
     "[P] 語順違い"),
    (CAUDA, "ko-KR", "엉덩이랑 사타구니가 저리고 어제부터 소변이 새요",
     "[P] 『회음부 감각 이상』구어"),
    (CAUDA, "ko-KR", "다리에 힘이 빠지고 오늘 소변을 지렸어요",
     "[P] 『다리 힘 빠짐』불연속"),
    (CAUDA, "ko-KR", "회음부가 감각이 둔해지면서 요실금이 생겼습니다",
     "[P] 삽입어"),
    (CAUDA, "vi-VN", "vùng bẹn tê bì và từ hôm qua tôi bị són tiểu",
     "[P] 『tê vùng đáy chậu』biến thể"),
    (CAUDA, "vi-VN", "hai chân yếu hẳn đi và tôi không nhịn được tiểu",
     "[P] 『yếu chân』đảo trật tự"),
    (CAUDA, "vi-VN", "mất cảm giác vùng mông và rỉ nước tiểu liên tục",
     "[P] cách nói khác"),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    MUST_FIRE,
    ids=[f"{cid}-{lg}-{i}" for i, (cid, lg, _t, _w) in enumerate(MUST_FIRE)],
)
def test_real_emergency_wording_fires(detector, canonical_id, language, text, why):
    """真急症的真人語序必須命中規則層（改動前這 60 句 0 命中）。"""
    assert _fired(detector, canonical_id, text, language), (
        f"{canonical_id} 規則層漏報（{why}）：\n  {language} {text!r}\n"
        f"  本輪命中：{_critical_hits(detector, text, language)}"
    )


def test_every_new_flag_covers_five_languages_and_three_wordings():
    """每個新加共現組的紅旗，5 語各要有 ≥3 種語序——少一語＝該語規則層仍是死的。"""
    for cid in NEW_COOCCURRENCE_FLAGS:
        for lang in LANGUAGES:
            n = sum(1 for c, lg, _t, _w in MUST_FIRE if c == cid and lg == lang)
            assert n >= 3, f"{cid} / {lang} 只有 {n} 種語序（要求 ≥3）"


# ══════════════════════════════════════════════════════════════
# 2. MUST_NOT_FIRE — 與 1. 對稱的反方向
# ══════════════════════════════════════════════════════════════
# ⚠️ 這些句子**不得**與 MUST_FIRE 用同一套措辭去改寫；它們是獨立的臨床情境
#   （慢性 BPH／頻尿、明確否認、時態否定、行政詢問、複誦主訴標籤、只有單一維度、
#     根本不是症狀陳述）。政策雖然偏誤報，但「病患明確否認」仍必須被抑制。

MUST_NOT_FIRE: list[tuple[str, str, str]] = [
    # 慢性 BPH / 頻尿（本輪最危險的誤報面：頻尿是門診第一大主訴）
    ("zh-TW", "我最近小便次數變多，白天大概十次，晚上還要起來兩次", "頻尿"),
    ("zh-TW", "我尿流變細變慢，尿完還有殘尿感，這樣半年了", "慢性 BPH"),
    ("zh-TW", "小便要等一下才出得來，但最後都尿得完", "排尿猶豫但排得出"),
    ("en-US", "I go to the bathroom a lot, maybe twelve times a day for the past year",
     "頻尿"),
    ("en-US", "my urine stream is weak and slow but it always comes out eventually",
     "慢性 BPH"),
    ("ja-JP", "おしっこの回数が多くて、夜も二回起きます", "頻尿"),
    ("ja-JP", "尿の勢いが弱くなってきましたが、最後まで出ます", "慢性 BPH"),
    ("ko-KR", "소변을 자주 보고 밤에도 두 번 정도 일어납니다", "頻尿"),
    ("ko-KR", "소변 줄기가 약해졌지만 결국은 다 나옵니다", "慢性 BPH"),
    ("vi-VN", "tôi đi tiểu nhiều lần trong ngày, khoảng mười lần", "頻尿"),
    ("vi-VN", "dòng tiểu yếu và chậm nhưng cuối cùng vẫn ra hết", "慢性 BPH"),
    # 明確否認（政策偏誤報，但**明確否認必須抑制**）
    ("zh-TW", "我沒有尿不出來，也沒有血尿，沒有發燒", "前置否定列舉"),
    ("zh-TW", "沒有會陰麻木，沒有腳沒力，也沒有尿失禁", "前置否定列舉"),
    ("en-US", "no fever, no chills, and no trouble passing urine", "前置否定"),
    ("en-US", "patient denies gross hematuria, denies clots in the urine", "denies"),
    ("en-US", "no numbness and no incontinence at all", "前置否定"),
    ("ja-JP", "発熱はありません、血尿もありません", "後置否定"),
    ("ja-JP", "しびれはありませんし、尿失禁もありません", "後置否定"),
    ("ko-KR", "열은 없고 혈뇨도 없어요", "後置否定"),
    ("ko-KR", "저림도 없고 요실금도 없습니다", "後置否定"),
    ("vi-VN", "không sốt, không tiểu ra máu", "không"),
    ("vi-VN", "không tê, không són tiểu", "không"),
    # 時態否定（以前有、現在好了）
    ("zh-TW", "我十年前尿不出來住過院，開完刀之後就再也沒發作", "過去已解決"),
    ("en-US", "I used to have blood clots in my urine years ago but it went away",
     "過去已解決"),
    ("ja-JP", "昔は尿失禁がありましたが、今は治りました", "過去已解決"),
    ("ko-KR", "예전에 혈뇨가 있었지만 지금은 다 나았어요", "過去已解決"),
    ("vi-VN", "trước đây tôi bị bí tiểu nhưng bây giờ đã khỏi hẳn", "過去已解決"),
    # 行政詢問 / 假設語氣
    ("zh-TW", "我想問尿不出來要掛哪一科", "行政詢問"),
    ("zh-TW", "如果小便有血塊要怎麼辦", "假設"),
    ("en-US",
     "I just wanted to ask about blood clots in urine, which doctor should I see",
     "行政詢問"),
    ("en-US", "what if I get a fever with dysuria later", "假設"),
    ("ja-JP", "もし血尿が出たらどうすればいいですか", "假設"),
    ("ko-KR", "만약 요실금 있으면 어떻게 하나요", "假設"),
    ("vi-VN", "tôi muốn hỏi bí tiểu thì khám khoa nào", "行政詢問"),
    # 複誦主訴選單標籤（慢性、良性）
    ("zh-TW", "我這次是因為血尿來看診，之前檢查說是結石", "複誦主訴"),
    ("zh-TW", "我掛號的主訴是排尿困難，已經好幾年了", "複誦主訴"),
    ("en-US", "I am here for urinary incontinence, it has been three years", "複誦主訴"),
    ("en-US", "I came in for hematuria that my family doctor found on a urine test",
     "複誦主訴"),
    ("ja-JP", "尿失禁で受診しました、三年前からです", "複誦主訴"),
    ("ko-KR", "요실금 때문에 왔습니다, 삼 년 됐어요", "複誦主訴"),
    ("vi-VN", "tôi đến khám vì tiểu không tự chủ, đã ba năm rồi", "複誦主訴"),
    # 只有單一維度（組合型紅旗的另一半明確正常）
    ("zh-TW", "我這兩天有尿失禁，但腳完全正常沒有麻", "只有膀胱那一半"),
    ("zh-TW", "我腰痠背痛腳有點麻，排尿完全正常", "只有神經那一半"),
    ("en-US", "I have some leaking of urine but my legs feel completely normal",
     "只有膀胱那一半"),
    # （"my left leg feels a bit numb, my bladder is fine" 移到
    #   ACCEPTED_OVER_TRIGGERS——見該處說明）
    ("ja-JP", "尿失禁はありますが、足のしびれはありません", "只有膀胱那一半"),
    ("ko-KR", "요실금은 있지만 다리 저림은 없어요", "只有膀胱那一半"),
    ("vi-VN", "tôi bị són tiểu nhưng chân hoàn toàn bình thường", "只有膀胱那一半"),
    # 根本不是泌尿症狀陳述（抽血／血壓）
    ("zh-TW", "我今天早上有抽血，抽了三管，護理師說血管很細", "抽血 ≠ 血尿"),
    ("zh-TW", "我血壓有點高，最近吃降血壓的藥", "血壓 ≠ 血尿"),
    ("en-US", "I had my blood drawn this morning, three tubes", "抽血 ≠ 血尿"),
    ("en-US", "my blood pressure has been high lately", "血壓 ≠ 血尿"),
    ("ja-JP", "今朝、採血をしました", "抽血 ≠ 血尿"),
    ("ko-KR", "오늘 아침에 채혈을 했어요", "抽血 ≠ 血尿"),
    ("vi-VN", "sáng nay tôi đã lấy máu xét nghiệm", "抽血 ≠ 血尿"),
    # ── 新增詞的「假朋友」（每一條都是本輪新收詞彙的字面陷阱）──
    # 這一組是為了證明新詞不是靠寬鬆比對換命中率：詞邊界、部位配對、
    # 以及「量詞必須帶血」三個設計各自對應下面幾句。
    ("en-US", "my head feels like it will burst from this headache", "burst 但不是膀胱"),
    ("en-US", "I changed my clothes because they were wet from the rain", "wet 的假朋友"),
    ("en-US", "my hands have been shaking because I drank too much coffee",
     "shaking 但無泌尿症狀"),
    ("en-US", "I am on blood thinners for a clotting disorder, no urinary symptoms",
     "clotting 但不是尿裡"),
    ("en-US", "people in the waiting room said the clinic is busy",
     "people 不得被 pee 的詞邊界誤配"),
    ("en-US", "I avoid spicy food, and my urine is normal", "avoid 不得被 void 誤配"),
    # （"my football injury made my leg weak years ago, bladder is fine" 移到
    #   ACCEPTED_OVER_TRIGGERS——見該處說明）
    ("en-US", "the urinalysis showed microscopic blood but I cannot see any",
     "顯微血尿不是大量血尿"),
    ("vi-VN", "tên tôi là Nguyễn Văn A, tôi đi tiểu bình thường",
     "tên 不得被 tê 誤配"),
    ("vi-VN", "tôi bị sốt xuất huyết năm ngoái nhưng đã khỏi hẳn", "去年登革熱已痊癒"),
    ("ja-JP", "部屋が熱くて眠れませんでした、排尿は普通です", "『熱』是房間熱"),
    ("ja-JP", "トイレの掃除をしました", "トイレ 但無任何症狀"),
    ("ko-KR", "열쇠를 잃어버려서 소변 검사를 못 했어요", "열쇠 不得被『열』誤配"),
    ("ko-KR", "열심히 운동해서 소변 색이 진해졌어요", "열심히 不得被『열』誤配"),
    ("zh-TW", "我膀胱鏡檢查排程在下週，目前小便都正常", "膀胱但無脹痛"),
    ("zh-TW", "我最近工作很麻煩，尿倒是正常", "『麻煩』不得被麻木類誤配"),
    ("zh-TW", "我腰很痠是因為搬重物，沒有發燒", "腰痠但無發燒"),
    ("zh-TW", "我的血糖有點高，小便也沒什麼問題", "血糖 ≠ 血尿"),
    ("zh-TW", "我尿液檢查報告說有潛血，但肉眼看不出來", "潛血非肉眼大量血尿"),
    ("zh-TW", "護理師說我血管很細，抽血抽了三次", "血管/抽血 ≠ 血尿"),
]


@pytest.mark.parametrize(
    "language,text,why",
    MUST_NOT_FIRE,
    ids=[f"{lg}-{i}" for i, (lg, _t, _w) in enumerate(MUST_NOT_FIRE)],
)
def test_benign_and_denied_wording_does_not_fire_critical(detector, language, text, why):
    """慢性/否定/假設/複誦主訴/單一維度/非症狀陳述 → 不得判 critical（會中止問診）。"""
    hits = _critical_hits(detector, text, language)
    assert hits == [], (
        f"共現組誤觸發 critical（{why}）：\n  {language} {text!r}\n  命中：{hits}"
    )


def test_positive_and_negative_tables_are_both_populated_per_language():
    """雙向對稱的結構性保證：任何語言只要有正例就必須有反例，反之亦然。"""
    for lang in LANGUAGES:
        pos = sum(1 for _c, lg, _t, _w in MUST_FIRE if lg == lang)
        neg = sum(1 for lg, _t, _w in MUST_NOT_FIRE if lg == lang)
        assert pos >= 3 and neg >= 3, f"{lang}: 正例 {pos} / 反例 {neg}（各要 ≥3）"


# ══════════════════════════════════════════════════════════════
# 3. 政策上刻意接受的誤報（正向測試，不是 xfail）
# ══════════════════════════════════════════════════════════════
# 使用者 2026-07-27 拍板：「偏誤報：寧可多中止幾場。第三人稱轉述、別部位誤配
# 這類殘餘誤報就留著。誤中止的代價是病患白等、護理師走一趟，可逆。」
# 所以這些**斷言它們就是會觸發**——寫成正向測試是為了讓「有人事後偷加一條抑制
# 守衛把它擋掉」這件事當場變紅（每一條抑制都是潛在漏報）。

ACCEPTED_OVER_TRIGGER: list[tuple[str, str, str, str]] = [
    (RETENTION, "zh-TW", "我朋友上禮拜尿不出來送急診", "第三人稱轉述"),
    (CAUDA, "zh-TW", "我太太腳麻又漏尿，聽說是脊椎壓迫", "第三人稱轉述"),
    (UROSEPSIS, "en-US", "my father had a fever and a urinary infection last month",
     "第三人稱轉述"),
    # ⚠️ 這裡曾有兩條 "bright red blood in my urine" 的 heavy(critical) 接受條目。
    # 2026-07-27 主 agent 移除：顏色詞已降級到 gross_hematuria(high)，那兩句現在
    # 得到 high 警示而不中止問診。移除的理由不是「誤報不可接受」，而是
    # **血尿是選單上的主訴 c1**——病患一講出自己的主訴就被 abort，
    # 等於血尿問診路徑在英文下結構上永遠跑不完（實測 hematuria_3b_en 第 2 輪即 abort）。
    # 原本擔心的「拿掉會 0 命中」已由新增的 urine_x_blood_present(high) 共現組解決。
    (
        CAUDA, "en-US", "my left leg feels a bit numb, my bladder is fine",
        "英文的『(部位) is fine』子句尾抑制已移除——它會讓 "
        "\"normally i pee fine, but since last night nothing comes out\" 這種"
        "教科書級尿滯留 0 命中（英文把『平常是好的』放前一子句，部位詞只出現在那裡）。"
        "保住那個漏報的代價就是這句誤報 cauda_equina。依偏誤報政策接受。",
    ),
    (
        CAUDA, "en-US", "my football injury made my leg weak years ago, bladder is fine",
        "同上：移除英文『bladder is fine』抑制的已知代價。"
        "這句還帶過去式（years ago），但英文的時態否定守衛看的是關鍵字**之前**"
        "的同一子句，接不到後置的 bladder；依偏誤報政策不補（補了是擴大抑制）。",
    ),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    ACCEPTED_OVER_TRIGGER,
    ids=[f"{cid}-{i}" for i, (cid, _l, _t, _w) in enumerate(ACCEPTED_OVER_TRIGGER)],
)
def test_accepted_over_trigger_still_fires_by_policy(
    detector, canonical_id, language, text, why
):
    """政策選擇：這類殘餘誤報**刻意保留**，不得為了擋它而新增抑制守衛。

    若本測試變紅，代表有人加了新的抑制邏輯——請先證明那條抑制不會造成漏報，
    再連同本測試一起改；不可以只把測試刪掉。
    """
    assert _fired(detector, canonical_id, text, language), (
        f"{canonical_id} 的殘餘誤報被擋掉了（{why}）——政策上這應該仍然觸發。\n"
        f"  {language} {text!r}\n  若是刻意收窄，請說明為什麼不會造成漏報。"
    )


# ══════════════════════════════════════════════════════════════
# 4. 曾經的殘餘漏報 —— 2026-07-27 第四輪 Gate 已修，改成正向迴歸釘子
# ══════════════════════════════════════════════════════════════
# 這兩筆原本是 xfail(strict=True)（根因在 red_flag_detector，非本檔所有權）。
# 第四輪 Gate 在 detector 修掉根因之後 strict xfail 自動變紅 —— 那正是它的設計目的。
# 現在改成**正向斷言**留在原地當迴歸釘子：根因一旦被人改回去，這兩條會直接變紅。

FIXED_FORMER_RESIDUAL_MISS: list[tuple[str, str, str, str]] = [
    (
        RETENTION, "ja-JP", "トイレに行っても尿が全く出ません、膀胱がパンパンです",
        "日文的尿滯留在文法上就是否定述語（…が出ません）。修法：detector 的 "
        "`_JA_SYMPTOM_NEG_STEMS`（出／感覚が／力が入ら…）× `_JA_NEG_SUFFIXES` 展開成 "
        "`_POST_CUE_FALSE_FRIENDS`，前置檢查、後置檢查與 `_clause_final_denial` 三處"
        "共用同一份表，所以「用否定句陳述症狀」不再被讀成否認。",
    ),
    (
        CAUDA, "zh-TW", "屁股跟大腿內側這兩天都麻麻的，小便也開始會漏出來",
        "跨症狀紅旗最自然的講法就是「Ａ，Ｂ」兩個相鄰子句。修法：共現組可宣告 "
        "`cross_clause: True`（只給 urosepsis／cauda_equina 這兩個**跨症狀組合**型），"
        "`_pairing_scope_ok` 對它們允許相鄰子句配對；site×acuity 型（睪丸／尿滯留／"
        "血尿）維持不開，「我眼睛突然很痛，睪丸沒事」照樣擋掉。",
    ),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    FIXED_FORMER_RESIDUAL_MISS,
    ids=[f"{cid}-{i}" for i, (cid, _l, _t, _w) in enumerate(FIXED_FORMER_RESIDUAL_MISS)],
)
def test_former_residual_miss_stays_fixed(
    detector, canonical_id, language, text, why
):
    """曾經的 critical 漏報，修好之後不得回退。"""
    assert _fired(detector, canonical_id, text, language), why


# ══════════════════════════════════════════════════════════════
# 5. 結構不變式
# ══════════════════════════════════════════════════════════════


def _flag(canonical_id: str) -> dict[str, Any]:
    return next(f for f in URO_RED_FLAGS if f["canonical_id"] == canonical_id)


def _groups(canonical_id: str) -> list[dict[str, Any]]:
    return list(_flag(canonical_id).get("trigger_cooccurrence") or [])


@pytest.mark.parametrize("canonical_id", NEW_COOCCURRENCE_FLAGS)
def test_cooccurrence_group_is_declared_and_wired(canonical_id):
    """共現組要真的存在，而且 detector 要以 canonical_id 查得到。

    以 canonical_id 查表（而非塞進 rule dict）是刻意的：生產 DB 的 red_flag_rules
    沒有對應欄位，若只靠內建 fallback 帶出來，哪天規則表被 seed 就會靜默退回
    「只有相鄰複合詞」的舊行為 —— 那正是本輪量到的 60/61 漏報。
    """
    groups = _groups(canonical_id)
    assert groups, f"{canonical_id} 沒有共現組"
    assert rfd_module._CANONICAL_COOCCURRENCE.get(canonical_id) == groups


@pytest.mark.parametrize("canonical_id", NEW_COOCCURRENCE_FLAGS)
def test_no_bare_pain_word_in_any_dimension(canonical_id):
    """任何一張表都不得收裸痛詞——收了就等於「講到這個部位會痛」全變 critical。"""
    bare = {
        "痛", "疼", "疼痛", "pain", "hurt", "hurts", "ache", "痛み", "痛い",
        "아파", "아픔", "통증", "đau",
    }
    for group in _groups(canonical_id):
        for key in ("site_terms", "acuity_terms"):
            for term in group.get(key, []):
                assert term.lower().strip() not in bare, (
                    f"{canonical_id}.{key} 混入裸痛詞：{term!r}"
                )


@pytest.mark.parametrize("canonical_id", NEW_COOCCURRENCE_FLAGS)
def test_site_and_acuity_term_sets_are_disjoint(canonical_id):
    """同一個詞不得同時在兩張表，否則單獨一個詞就能自我配對成命中。"""
    for group in _groups(canonical_id):
        sites = {t.lower() for t in group.get("site_terms", [])}
        acuities = {t.lower() for t in group.get("acuity_terms", [])}
        assert sites.isdisjoint(acuities), f"{canonical_id}: {sites & acuities}"


def _complaint_labels() -> set[str]:
    return {
        text.lower().strip()
        for by_lang in NAME_FALLBACK_I18N.values()
        for text in by_lang.values()
    }


@pytest.mark.parametrize("canonical_id", NEW_COOCCURRENCE_FLAGS)
def test_at_least_one_dimension_is_free_of_chief_complaint_labels(canonical_id):
    """兩張表至少要有一張完全不含主訴選單標籤。

    為什麼不是「兩張都不准含」（testicular_pain_severe 用的是那條更嚴的規則）：
    cauda_equina_suspected 的膀胱維度**本來就是**主訴標籤（尿失禁／요실금／
    tiểu không tự chủ），那是這個紅旗的臨床定義的一半，拿掉等於這個紅旗不存在。
    真正要防的是「病患只複誦選單標籤就被 abort」——只要另一個維度（神經缺損）
    完全不在標籤裡，複誦選單就湊不齊兩個維度，abort 不可能發生。
    對應的行為證據在 MUST_NOT_FIRE 的「複誦主訴」那一組。
    """
    labels = _complaint_labels()
    for group in _groups(canonical_id):
        clean = [
            key
            for key in ("site_terms", "acuity_terms")
            if not any(t.lower().strip() in labels for t in group.get(key, []))
        ]
        assert clean, (
            f"{canonical_id}/{group.get('id')}：兩張表都含主訴標籤 → "
            f"病患複誦兩個選單標籤就會被 abort"
        )


# 血尿量詞的白名單（顏色/血塊類，已人工覆核）。除此之外的量詞都必須自帶血語意。
_BLOOD_TOKENS = ("血", "피", "핏", "혈", "máu", "blood", "bloody")
# 2026-07-27 主 agent：純顏色詞已從 heavy(critical) 降級到 gross_hematuria(high)，
# 所以這裡只剩**血塊**詞。血塊是 heavy 的臨床判準本身，不帶「血」字也成立
# （病患講「血の混じったかたまり」「새빨갛고 덩어리도」會把血與塊拆開，
#  複合詞「血の塊」接不到）。與 site 尿液詞共現才生效。
# ⚠️ 這張表**只放血塊**。量詞一律不得放進來——那正是本測試要擋的東西
#（「尿の量も多い」＝多尿，放進來會讓頻尿主訴被判 critical）。
_REVIEWED_COLOUR_OR_CLOT_TERMS = {
    "clots", "clotting", "máu đông", "かたまり", "塊", "덩어리",
}


def test_hematuria_volume_terms_all_carry_a_blood_concept():
    """大量血尿的量詞**必須自帶血語意**，不得是裸量詞。

    site 側是尿液詞。若量詞不帶血（「很多／많이／nhiều／たくさん」），
    「我最近小便次數很多，一天十幾次」這句**頻尿主訴**（門診第一大主訴）
    就會被判 critical、第 1 輪 abort。這是本紅旗唯一真正危險的誤報面，
    在此結構性關掉，不靠人工閱讀詞表。
    """
    offenders = []
    for group in _groups(HEMATURIA_HEAVY):
        for term in group.get("acuity_terms", []):
            low = term.lower().strip()
            if low in _REVIEWED_COLOUR_OR_CLOT_TERMS:
                continue
            if not any(tok in low for tok in _BLOOD_TOKENS):
                offenders.append(term)
    assert offenders == [], f"大量血尿的量詞缺少血語意：{offenders}"


def test_retention_terms_contain_no_frequency_word():
    """尿滯留的兩張表都不得收「次數/頻率」詞——那是頻尿，不是滯留。"""
    frequency = (
        "次數", "頻尿", "好幾次", "times", "frequency", "frequent", "often",
        "回数", "何回", "횟수", "자주", "빈뇨", "nhiều lần", "thường xuyên",
    )
    offenders = [
        term
        for group in _groups(RETENTION)
        for key in ("site_terms", "acuity_terms")
        for term in group.get(key, [])
        if any(f in term.lower() for f in frequency)
    ]
    assert offenders == [], f"尿滯留詞表混入頻率詞：{offenders}"


def test_urosepsis_is_documented_as_cross_symptom_combination():
    """urosepsis 的兩張表必須真的是「泌尿症狀 × 全身性感染徵象」兩個不同軸。

    這個紅旗最容易被寫成「發燒」單維度（現況就是：裸『高燒』一個詞即 critical）。
    共現組必須把泌尿那一軸帶進來，否則跨症狀組合的臨床語意消失。
    """
    groups = _groups(UROSEPSIS)
    assert groups, "urosepsis 沒有共現組"
    sites = {t for g in groups for t in g.get("site_terms", [])}
    acuities = {t for g in groups for t in g.get("acuity_terms", [])}
    # 泌尿軸：五語都要有代表詞
    for probe in ("小便", "urine", "尿", "소변", "tiểu"):
        assert probe in sites, f"urosepsis 泌尿軸缺 {probe!r}"
    # 全身性感染軸：五語都要有代表詞
    for probe in ("發燒", "fever", "熱", "오한", "sốt"):
        assert probe in acuities, f"urosepsis 感染徵象軸缺 {probe!r}"


@pytest.mark.parametrize("canonical_id", NEW_COOCCURRENCE_FLAGS)
def test_every_new_group_covers_five_languages(canonical_id):
    """共現組的兩張表都要五語齊備——少一語＝該語言的 fallback 仍然是死的。"""
    probes = {
        "zh-TW": ("尿", "小便", "血", "麻", "膀胱", "燒", "失禁", "漏", "脹", "解"),
        "en-US": (
            "urine", "pee", "blood", "numb", "bladder", "fever", "incontinence",
            "burst", "clots", "leaking", "weak", "chill", "nothing comes out",
        ),
        "ja-JP": ("尿", "おしっこ", "血", "しびれ", "熱", "漏", "出な", "パンパン",
                  "真っ赤", "力が入らな", "寒気", "膀胱", "トイレ", "感覚"),
        "ko-KR": ("소변", "오줌", "피", "저리", "열", "요실금", "안 나", "빵빵",
                  "핏덩", "힘이 빠", "오한", "방광", "새빨", "감각"),
        "vi-VN": ("tiểu", "máu", "tê", "sốt", "bàng quang", "són", "không ra được",
                  "căng tức", "yếu", "rét", "cục máu", "rặn", "đỏ", "rỉ"),
    }
    terms = [
        t.lower()
        for group in _groups(canonical_id)
        for key in ("site_terms", "acuity_terms")
        for t in group.get(key, [])
    ]
    for lang, needles in probes.items():
        assert any(n.lower() in t or t in n.lower() for t in terms for n in needles), (
            f"{canonical_id} 的共現詞表沒有任何 {lang} 詞彙"
        )


# ══════════════════════════════════════════════════════════════
# 6. 語料不得抄 e2e persona 台詞（第三輪就是栽在這裡）
# ══════════════════════════════════════════════════════════════
_RESULTS_GLOB = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "scripts", "e2e_realopenai", "results", "*.json",
)


def _real_transcript_lines() -> list[str]:
    lines: list[str] = []
    for path in glob.glob(_RESULTS_GLOB):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):  # 檔案缺席/損毀不該讓本檔紅
            continue
        for turn in data.get("transcript") or []:
            if isinstance(turn, dict) and turn.get("role") == "patient":
                content = (turn.get("content") or "").strip()
                if content:
                    lines.append(content)
    return lines


def test_corpus_is_not_copied_from_real_transcripts():
    """本檔語料不得等於（或包含於）真跑逐字稿的病患台詞。

    第三輪的教訓：e2e persona 台詞「大約兩小時前左邊睪丸突然劇烈疼痛」剛好讓
    「睪丸突然」相鄰，於是「相鄰子字串」這個壞實作在所有測試裡都是綠的。
    情境台詞與關鍵字互相配適時，測到的是實作不是行為。
    """
    real = _real_transcript_lines()
    if not real:
        pytest.skip("找不到 results/*.json（不在此 clone 內），跳過抄襲檢查")
    corpus = [t for _c, _l, t, _w in MUST_FIRE] + [t for _l, t, _w in MUST_NOT_FIRE]
    offenders = [
        (text, line)
        for text in corpus
        for line in real
        if text.strip() == line or text.strip() in line
    ]
    assert offenders == [], f"語料抄自真跑逐字稿：{offenders}"


# ── 真跑逐字稿上**唯一**允許判 critical 的句型（見下方測試的 docstring）──
# 每一條都要能說出「為什麼這句 critical 是對的」，不可以拿來當萬用白名單。
_TRANSCRIPT_CRITICAL_ALLOWLIST: tuple[tuple[str, str], ...] = (
    (
        "睪丸",
        "torsion_critical_zh 的 persona 第 1 句就是教科書級睪丸扭轉——這個 scenario "
        "的存在目的就是驗證它會 abort，本來就該 critical。",
    ),
    (
        "testicle",
        "torsion_critical_en 的 persona 第 1 句是同一個扭轉情境的英文語序變體"
        "（「my right testicle started hurting really badly about…」）。這個 "
        "scenario 的存在目的就是驗 en 語序也會被**規則層**接住並 abort，"
        "critical 是正確結果。",
    ),
)
# ⚠️ 這裡曾經有一條 "bright red blood" 的白名單，理由是共現組把
# 「bright red blood in my urine」升成 gross_hematuria_heavy(critical)。
# 2026-07-27 主 agent 移除該升級：heavy 的臨床定義是**量與血塊**不是顏色，
# 而「血尿」正是選單上的主訴 c1——用顏色詞判 critical 會讓血尿病患一講出
# 自己的主訴就被中止（實測 hematuria_3b_en 第 2 輪 aborted_red_flag，
# §3b 問診路徑在英文下結構上永遠跑不完）。顏色詞已降級到
# gross_hematuria(high) 的 urine_x_blood_present 共現組：仍會發警示、不中止，
# 所以不是漏報。要再把顏色升回 critical 之前，先想清楚血尿主訴要怎麼問完。


def test_real_transcripts_still_behave(detector):
    """對真跑逐字稿的每一句病患發話重跑，確認本輪沒有**未經記錄**的新誤報。

    2026-07-27 第四輪 Gate 實跑：6 個 scenario、64 句病患發話，
    命中變化 2 句（都是同一個 en 血尿情境，見 `_TRANSCRIPT_CRITICAL_ALLOWLIST`）。
    其餘 62 句（含大量「沒有發燒／沒有腰痛」否認、「白天排尿 10 到 12 次」頻尿、
    「尿流變細變弱」慢性 BPH）命中完全不變。
    """
    real_lines_by_file: list[tuple[str, str]] = []
    for path in glob.glob(_RESULTS_GLOB):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        lang = data.get("session_language") or "zh-TW"
        for turn in data.get("transcript") or []:
            if isinstance(turn, dict) and turn.get("role") == "patient":
                content = (turn.get("content") or "").strip()
                if content:
                    real_lines_by_file.append((lang, content))
    if not real_lines_by_file:
        pytest.skip("找不到 results/*.json（不在此 clone 內）")
    allowed = tuple(marker for marker, _why in _TRANSCRIPT_CRITICAL_ALLOWLIST)
    for lang, text in real_lines_by_file:
        hits = _critical_hits(detector, text, lang)
        if hits and not any(marker in text for marker in allowed):
            pytest.fail(
                f"真跑逐字稿出現**未記錄的**新 critical（會中止問診）：\n"
                f"  {lang} {text!r}\n  命中：{hits}\n"
                f"  若這是刻意的升級，請把句型與臨床理由寫進 "
                f"_TRANSCRIPT_CRITICAL_ALLOWLIST，不要只放寬這個測試。"
            )
