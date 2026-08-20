"""2026-08-20 LLM 稽核輪：紅旗偵測六個缺陷的雙向回歸表。

涵蓋的缺陷（編號沿用稽核報告）
────────────────────────────────────────
RF-1 [P0 漏報] `detect()` 的否定幻覺後過濾把**規則層**命中整筆刪掉。
     根因：判準 `_CANONICAL_KEYWORDS` 只讀 triggers / triggers_by_lang，
     **不認識共現組**。病患否認一個書面 trigger（高燒／尿滯留／會陰麻木…）
     卻用口語描述同一個急症時，規則層 critical 命中會被這個過濾殺掉。
RF-2 [P0 漏報] critical 的否定作用範圍實質無上限：`_NEG_LIST_SEPARATORS`
     讓散文預算在每個頓號／逗號歸零，於是「否認一串病史 ＋ 真急症」
     ——門診第一句話最常見的形狀——在五種語言全數漏報。
RF-3 [誤報] 不要求泌尿軸的裸 critical trigger（血塊／혈전／血の塊／
     高燒／高熱／고열／high fever／sốt cao／意識不清）。
RF-4 [誤報] 短字面在全語言聯集比對（不變式 #25）下的誤配：
     裸「塊」「できない」「體溫／体温／temperature」「떨리／震え／shaking」、
     ja 段的「下腹」。
D-6  [latent] DB 規則路徑：regex 命中繞過否定守衛；canonical_id 為 NULL 時
     靜默退回 rule.name → 共現組／severity floor／否定後過濾三層一起失效。
D-7  LLM 自創紅旗的去重身份未正規化 → 同一個紅旗換個大小寫就變兩筆。

測試設計（voice-pipeline-invariants「改偵測邏輯時的測試設計」四點）
────────────────────────────────────────
1. **雙向對稱**：每一節都同時有 MUST_FIRE 與 MUST_NOT_FIRE。RF-2 尤其重要
   ——只加「否認前綴不得抹掉真急症」會直接開出「明確否認也命中」的擺盪。
2. **措辭避開 persona 台詞**：語料另寫，並由
   `test_corpus_is_independent_of_personas_and_existing_tests` 結構性守住
   （比對 e2e 逐字稿 ＋ 既有 6 個紅旗測試檔）。
3. **獨立 oracle**：期望值是人工臨床標註（每筆都有 why 欄），不是偵測器輸出；
   結構性測試比對的是**詞表內容**與**行為**，不是重寫一份比對邏輯。
4. **注入式回歸**：§7 把每一個修復故意改壞，斷言本檔會有測試轉紅。
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipelines import alert_dedup
from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.prompts.shared import URO_RED_FLAGS, normalize_canonical_id
from app.pipelines.red_flag_detector import RedFlagDetector

LANGUAGES = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")

RETENTION = "urinary_retention"
HEMATURIA_HEAVY = "gross_hematuria_heavy"
TORSION = "testicular_pain_severe"
UROSEPSIS = "urosepsis"
CAUDA = "cauda_equina_suspected"


# ── detector 腳手架（空表 → fallback 內建 catalogue，與正式路徑同一條）──


class _FakeScalars:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list[Any]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeDB:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows

    async def execute(self, _stmt) -> _FakeResult:
        return _FakeResult(self._rows)


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
    settings.RED_FLAG_NEGATION_GUARD = True
    return settings


def _make_detector(
    monkeypatch: pytest.MonkeyPatch, rows: list[Any] | None = None
) -> RedFlagDetector:
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    det = RedFlagDetector(_settings(), _FakeDB(rows))
    asyncio.run(det._load_rules())
    return det


@pytest.fixture
def detector(monkeypatch: pytest.MonkeyPatch) -> RedFlagDetector:
    return _make_detector(monkeypatch)


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


def _detect(
    det: RedFlagDetector,
    text: str,
    language: str,
    semantic: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """跑完整的 `detect()`（含 merge ＋ 否定幻覺後過濾），語意層以參數注入。"""

    async def _fake_semantic(_text, _ctx, _language=None):
        return list(semantic or [])

    det._semantic_detect = _fake_semantic  # type: ignore[method-assign]
    return asyncio.run(
        det.detect(text, {"session_id": "audit", "language": language})
    )


def _detect_critical_ids(
    det: RedFlagDetector,
    text: str,
    language: str,
    semantic: list[dict[str, Any]] | None = None,
) -> list[str]:
    return [
        a["canonical_id"]
        for a in _detect(det, text, language, semantic)
        if a.get("severity") == "critical"
    ]


# ══════════════════════════════════════════════════════════════
# §1 RF-1：規則層命中不得被否定幻覺後過濾刪掉
# ══════════════════════════════════════════════════════════════
# 形狀：病患**否認一個書面 trigger**、同一句用口語描述**同一個急症**。
# 規則層靠共現組命中（那才是真人語序），但 `_CANONICAL_KEYWORDS` 看不到共現組，
# 只看到「那個書面詞被否認了」→ 整筆 alert 被刪 → critical 漏報。
# 每個 critical canonical 各一筆（稽核實證語料）。

RF1_RULE_HIT_MUST_SURVIVE: list[tuple[str, str, str, str]] = [
    (
        UROSEPSIS, "zh-TW", "我沒有寒顫，可是我燒到三十九度而且小便會痛",
        "否認書面詞『寒顫』，但『燒到三十九度＋小便痛』就是尿路敗血症的兩個軸",
    ),
    (
        RETENTION, "zh-TW", "我沒有尿滯留，但是我膀胱脹到快爆一滴都尿不出",
        "否認書面詞『尿滯留』，但『膀胱脹到快爆＋一滴都尿不出』就是急性尿滯留",
    ),
    (
        CAUDA, "zh-TW", "我沒有會陰麻木，可是我兩隻腳沒力而且開始漏尿",
        "否認書面詞『會陰麻木』，但『下肢無力＋新發漏尿』就是馬尾症候群的定義",
    ),
    (
        HEMATURIA_HEAVY, "zh-TW", "我沒有大量血尿，可是馬桶裡都是血還有一坨一坨的",
        "否認書面詞『大量血尿』，但『馬桶都是血』就是量的判準",
    ),
    (
        TORSION, "zh-TW", "我沒有睪丸劇痛的老毛病，可是今天早上蛋蛋忽然痛到站不直",
        "否認書面詞『睪丸劇痛』，但『蛋蛋忽然痛到站不直』就是急性扭轉的描述",
    ),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    RF1_RULE_HIT_MUST_SURVIVE,
    ids=[f"{cid}" for cid, _l, _t, _w in RF1_RULE_HIT_MUST_SURVIVE],
)
def test_rule_layer_hit_survives_denial_post_filter(
    detector, canonical_id, language, text, why
):
    """規則層已經命中的 critical，不得被否定幻覺後過濾刪掉（RF-1）。"""
    # 前置條件：這一句真的踩到後過濾（否則本測試是空跑）
    assert rfd_module._canonical_denied_in_text(canonical_id, text.lower()), (
        f"語料選得不對：{canonical_id} 的 canonical 關鍵字沒有『出現且全被否定』，"
        f"這筆測不到 RF-1。\n  {text!r}"
    )
    assert _fired(detector, canonical_id, text, language), (
        f"規則層自己就沒命中，這筆測不到 RF-1（可能是 RF-2 的問題）：{text!r}"
    )
    assert canonical_id in _detect_critical_ids(detector, text, language), (
        f"RF-1 回歸：規則層命中的 critical 被否定幻覺後過濾刪掉（{why}）\n  {text!r}"
    )


# ── 反方向：後過濾原本要解的問題必須完好 ──────────────────
# 語意層對「病患明確否認的症狀」幻覺出紅旗 → 仍必須抑制。


def _semantic_alert(canonical_id: str, severity: str = "critical") -> dict[str, Any]:
    return {
        "canonical_id": canonical_id,
        "severity": severity,
        "title": canonical_id,
        "description": "",
        "trigger_reason": "LLM 幻覺",
        "alert_type": "semantic",
        "trigger_keywords": None,
        "llm_analysis": {"model": "gpt-4o-mini"},
        "confidence": "semantic_only",
        "suggested_actions": [],
        "matched_rule_id": None,
    }


SEMANTIC_HALLUCINATION_MUST_BE_SUPPRESSED: list[tuple[str, str, str, str]] = [
    ("gross_hematuria", "zh-TW", "我這陣子都沒有血尿", "病患明確否認，LLM 仍幻覺出血尿"),
    ("gross_hematuria", "ja-JP", "血尿は一度もありません", "後置否定的明確否認"),
    (
        "gross_hematuria", "en-US",
        "the patient denies hematuria and denies blood in the urine",
        "denies × 2 的明確否認",
    ),
    (TORSION, "zh-TW", "這輩子都沒有睪丸劇痛過", "critical 的明確否認也要抑制"),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    SEMANTIC_HALLUCINATION_MUST_BE_SUPPRESSED,
    ids=[f"{lg}-{i}" for i, (_c, lg, _t, _w) in enumerate(
        SEMANTIC_HALLUCINATION_MUST_BE_SUPPRESSED)],
)
def test_semantic_hallucination_on_denied_symptom_still_suppressed(
    detector, canonical_id, language, text, why
):
    """RF-1 的修法**只**縮到語意層，不得把後過濾整個關掉（雙向對稱）。"""
    alerts = _detect(detector, text, language, [_semantic_alert(canonical_id)])
    assert canonical_id not in [a["canonical_id"] for a in alerts], (
        f"否定幻覺後過濾對語意層失效了（{why}）：{language} {text!r}\n  {alerts}"
    )


def test_combined_alert_is_not_dropped_by_the_denial_post_filter(detector):
    """combined（兩層都命中）＝規則層那一半仍是有效證據，不得刪。"""
    text = "我沒有尿滯留，但是我膀胱脹到快爆一滴都尿不出"
    alerts = _detect(detector, text, "zh-TW", [_semantic_alert(RETENTION)])
    hit = [a for a in alerts if a["canonical_id"] == RETENTION]
    assert hit, f"combined alert 被後過濾刪掉：{alerts}"
    assert hit[0]["alert_type"] == "combined", hit[0]


# ══════════════════════════════════════════════════════════════
# §2 RF-2：「否認病史前綴 ＋ 真急症」五語 MUST_FIRE
# ══════════════════════════════════════════════════════════════
# kiosk 現場最常見的第一句話：病患先把慢性病史一口氣否認掉，接著才講今天的急症。
# 舊行為（實測 0/5 命中）：前面那串「沒有」構得到後面的關鍵字，整句被抹掉。
# 每語 ≥2 筆，且刻意用**不同的**否認詞與不同的急症。

RF2_HISTORY_DENIAL_MUST_FIRE: list[tuple[str, str, str, str]] = [
    # ── zh-TW ──
    (
        TORSION, "zh-TW",
        "我沒有糖尿病、沒有高血壓、沒有心臟病、沒有開過刀，昨晚睪丸突然劇痛痛到吐",
        "[稽核實證] 四段病史否認 ＋ 昨晚急性睪丸劇痛合併嘔吐",
    ),
    (
        RETENTION, "zh-TW",
        "我沒有慢性病也沒有在吃藥，今天早上開始膀胱脹得受不了，一滴都解不出",
        "病史否認 ＋ 今晨急性尿滯留",
    ),
    # ── en-US ──
    (
        TORSION, "en-US",
        "no diabetes, no high blood pressure, no heart disease, no surgeries, "
        "last night my testicle suddenly started hurting so much i threw up",
        "[稽核實證] 並列逗號否認 ＋ 昨夜急性扭轉（英文無 but 連接）",
    ),
    (
        UROSEPSIS, "en-US",
        "no allergies, no regular medications, this morning i am running a "
        "temperature and it stings badly every time i pee",
        "並列逗號否認 ＋ 今晨發燒合併排尿刺痛",
    ),
    # ── ja-JP ──
    (
        TORSION, "ja-JP",
        "糖尿病はありません、高血圧もありません、昨夜から精巣が急に激しく痛みます",
        "[稽核實證] 既往歴の否認を並べたあと、昨夜からの急性精巣痛",
    ),
    (
        RETENTION, "ja-JP",
        "持病はありません、手術歴もありません、今朝から尿が一滴も出なくて膀胱が張っています",
        "既往歴否認 ＋ 今朝からの急性尿閉",
    ),
    # ── ko-KR ──
    (
        TORSION, "ko-KR",
        "당뇨는 없고 고혈압도 없는데 어젯밤부터 고환이 갑자기 심하게 아파요",
        "[稽核實證] 連接語尾 ~는데 で既往否認をつないだあとの急性고환통",
    ),
    (
        CAUDA, "ko-KR",
        "허리 디스크는 없는데 오늘 아침부터 다리에 힘이 빠지고 소변이 새요",
        "~는데 で否認、そのあと今朝からの下肢脱力＋尿失禁",
    ),
    # ── vi-VN ──
    (
        TORSION, "vi-VN",
        "tôi không bị tiểu đường, không bị cao huyết áp, tối qua tinh hoàn đau dữ dội",
        "[稽核實證] Phủ định tiền sử rồi mới kể cơn đau tinh hoàn tối qua",
    ),
    (
        UROSEPSIS, "vi-VN",
        "tôi không dị ứng thuốc, không mổ bao giờ, sáng nay tôi sốt và tiểu rất buốt",
        "Phủ định tiền sử ＋ sáng nay sốt kèm tiểu buốt",
    ),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    RF2_HISTORY_DENIAL_MUST_FIRE,
    ids=[f"{lg}-{i}" for i, (_c, lg, _t, _w) in enumerate(
        RF2_HISTORY_DENIAL_MUST_FIRE)],
)
def test_history_denial_prefix_does_not_swallow_the_real_emergency(
    detector, canonical_id, language, text, why
):
    """否認一串病史之後才講的真急症，規則層必須接住（RF-2）。"""
    assert _fired(detector, canonical_id, text, language), (
        f"RF-2 回歸：病史否認前綴把真急症抹掉了（{why}）\n"
        f"  {language} {text!r}\n  本輪命中：{_critical_hits(detector, text, language)}"
    )


def test_rf2_covers_every_language_with_at_least_two_wordings():
    """五語各 ≥2 筆——少一語就代表那一語的規則層 fallback 仍是死的。"""
    for lang in LANGUAGES:
        n = sum(1 for _c, lg, _t, _w in RF2_HISTORY_DENIAL_MUST_FIRE if lg == lang)
        assert n >= 2, f"{lang} 只有 {n} 筆 RF-2 正例（要求 ≥2）"


# ── 反方向：真否認仍必須抑制（防擺盪）────────────────────
# RF-2 的修法是「放寬否定範圍」，最危險的失敗方向就是把**明確否認**也放行。

RF2_REAL_DENIAL_MUST_NOT_FIRE: list[tuple[str, str]] = [
    ("zh-TW", "我沒有睪丸疼痛，只是來拿藥"),
    ("zh-TW", "我沒有血尿、沒有發燒，也沒有尿不出來"),
    ("zh-TW", "我今天早上沒有血尿、沒有發燒、也沒有尿不出來"),
    ("zh-TW", "我沒有血尿，今天早上也沒有尿不出來"),
    ("en-US", "i have no testicle pain at all, i only came to pick up a prescription"),
    ("en-US", "no blood in the urine, no fever, and no trouble passing urine today"),
    ("ja-JP", "精巣の痛みはありません、薬をもらいに来ただけです"),
    ("ja-JP", "今朝は血尿もありませんし、尿閉もありません"),
    ("ko-KR", "고환 통증은 없어요, 약만 받으러 왔습니다"),
    ("ko-KR", "오늘 아침에 혈뇨도 없었고 요폐도 없었어요"),
    ("vi-VN", "tôi không bị đau tinh hoàn, chỉ đến lấy thuốc thôi"),
    ("vi-VN", "sáng nay không tiểu ra máu, không sốt, không bí tiểu"),
]


@pytest.mark.parametrize(
    "language,text",
    RF2_REAL_DENIAL_MUST_NOT_FIRE,
    ids=[f"{lg}-{i}" for i, (lg, _t) in enumerate(RF2_REAL_DENIAL_MUST_NOT_FIRE)],
)
def test_real_denial_is_still_suppressed(detector, language, text):
    """明確否認（含帶時間錨點的否認）不得因 RF-2 的放寬而命中 critical。"""
    hits = _critical_hits(detector, text, language)
    assert hits == [], (
        f"RF-2 修法擺盪成 over-trigger：明確否認被判 critical\n"
        f"  {language} {text!r}\n  命中：{hits}"
    )


def test_rf2_negative_table_covers_every_language():
    """雙向對稱的結構性保證。"""
    for lang in LANGUAGES:
        n = sum(1 for lg, _t in RF2_REAL_DENIAL_MUST_NOT_FIRE if lg == lang)
        assert n >= 2, f"{lang} 只有 {n} 筆 RF-2 反例（要求 ≥2）"


# ══════════════════════════════════════════════════════════════
# §3 RF-3／RF-4：被移除字面的逐條舉證 ＋ 雙向行為釘子
# ══════════════════════════════════════════════════════════════
# #22 舉證責任：每一個被移除／收窄的字面都要能說出「為什麼它不會造成漏報」，
# 而且要有**反向**的 MUST_FIRE 把「真的臨床情境仍命中」釘住。

REMOVED_LITERAL_JUSTIFICATION: dict[str, str] = {
    # ── RF-5（2026-08-21）：RF-3 漏掉的英語版 ──
    "blood clots（gross_hematuria_heavy.triggers_by_lang['en-US']）": (
        "RF-3 的臨床拍板是對『血塊這個臨床實體必須伴隨泌尿軸』這個**概念**下的，"
        "但實作只落到 zh/ja/ko 三語，英語的裸 `blood clots` 原封不動留著 → "
        "『i have blood clots in my leg』仍判 gross_hematuria_heavy(critical) 中止問診，"
        "與已修掉的『다리에 혈전이 생겼대요』（下肢 DVT）完全同型。這是實作漏一語，"
        "不是新的臨床決定。為什麼不會造成漏報：共現組 acuity_terms 裡原本就有 "
        "`blood clot` / `clots` / `clotting`，只要同一或相鄰子句有尿液詞就命中；"
        "實測『i went to pee this morning, and there were blood clots』"
        "『there were blood clots in my urine』都仍命中 critical。"
        "自帶泌尿軸的 `clot in urine` 保留不動。"
    ),
    # ── RF-3：不要求泌尿軸的裸 critical trigger ──
    "血塊 / 血の塊 / 혈전（gross_hematuria_heavy.triggers）": (
        "三者原封不動留在 urine_x_heavy_blood 共現組的 acuity_terms 裡，"
        "只是多要求同句/相鄰子句有尿液詞（尿／小便／馬桶／おしっこ／トイレ／"
        "소변／urine／pee／tiểu…，全語言聯集）。真正的大量血尿病患不可能不提到尿；"
        "不提尿的『血塊』根本不是本紅旗（腳上瘀血塊、下肢深部靜脈血栓 혈전）。"
        "實測『尿裡有血塊』『おしっこに血の塊が混じっています』"
        "『소변에 혈전이 섞여 나와요』三語都仍命中 critical。"
    ),
    "高燒 / 高熱 / 고열 / high fever / sốt cao（urosepsis.triggers）": (
        "五個字面全部原封不動留在 urinary_x_systemic_infection 的 acuity_terms"
        "（英文由前緣詞邊界的 fever 涵蓋 high fever，越南文由 sốt 涵蓋 sốt cao），"
        "只是多要求同句或**相鄰**子句（本組 cross_clause=True）有泌尿詞。"
        "本紅旗的臨床定義就是『尿路感染 ＋ 全身性感染徵象』兩個軸，"
        "單獨一個發燒詞判 critical 是把流感/一般感冒判成尿路敗血症。"
        "實測『我發高燒而且小便會痛』五語都仍命中 critical。"
    ),
    "意識不清（urosepsis.triggers）": (
        "它也在 acuity_terms 裡，加上泌尿詞照樣命中。沒有任何泌尿描述的意識改變"
        "不是尿路敗血症（那是另一條臨床路徑），規則層硬判 urosepsis 只會誤中止；"
        "語意層對意識改變仍獨立判斷，是後備。"
        "⚠️ 其餘四語的意識改變詞（altered consciousness／意識がもうろう／"
        "의식이 흐려짐／rối loạn ý thức）**不在** acuity_terms，共現組接不住，"
        "移除會造成真漏報 → 依 #22 保留。"
    ),
    # ── RF-4：短字面的全語言聯集誤配（#25） ──
    "塊（gross_hematuria_heavy 共現組 acuity）": (
        "1 個 CJK 字元是聯集比對下風險最高的字面：『尿路結石の塊』"
        "『我尿完之後石頭一塊一塊排出來』都會配上尿語詞判 critical。"
        "血塊的所有真人講法（血の塊／血のかたまり／かたまり／血塊／血凝塊／凝血塊）"
        "都個別收錄著，含單獨的『かたまり』——3 モーラ的假名列不會出現在中文/韓文句子裡，"
        "結構上不會被聯集巻き添え。"
    ),
    "できない / できません / できていません（urinary_retention 共現組 acuity）": (
        "臨床**反義**：『トイレを我慢できないくらい尿意が強い』＝尿意切迫（蓄尿症狀），"
        "被判成急性尿滯留。而且『我慢できない』同時是 detector 的 "
        "`_POST_CUE_FALSE_FRIENDS`（否定守衛刻意放行的強調語氣），"
        "所以否定守衛結構上不可能擋下這個誤報。"
        "真正的尿閉『できない』形一定有排尿語在前，已改收為相鄰片語 triggers"
        "（排尿できない／排尿ができません／おしっこができない／小便ができない…）；"
        "副詞插入形（全く／全然／一滴も＋出ません）由既有的 acuity 詞接住。"
        "實測『朝から一滴も排尿できていません』仍命中。"
    ),
    "體溫 / 体温 / temperature（urosepsis 共現組 acuity）": (
        "三者都是**度量名詞**不是發燒的訴說：『護理師剛剛幫我量體溫』"
        "『毎朝体温を記録しています』『my temperature was normal』"
        "『体温は平熱でした』全部被判 critical——病患講的是正常值也照樣中止問診。"
        "唯一以它為足場的真人語序一定伴隨**發熱域的實測度數**"
        "（體溫三十八度九／体温を測ったら三十八度五分），所以改收度數本身"
        "（三十八度／三十九度／四十度／38度…，平熱的三十六・三十七度刻意不收），"
        "英文改收慣用句 running a temperature／high temperature／temperature of。"
        "實測四筆既有 MUST_FIRE 語料全部維持命中。"
    ),
    "떨리 / 震え / ふるえ / shaking（urosepsis 共現組 acuity）": (
        "振顫的常見成因是咖啡因／焦慮／藥物／本態性顫抖，不是全身性感染徵象："
        "『커피 때문에 손이 떨리는데 소변 검사 받으러 왔어요』"
        "『緊張して手が震えます』『my hands keep shaking from the medication』"
        "都被判 critical。悪寒戰慄的真人講法一定帶寒冷語（오한／한기／덜덜／"
        "悪寒／寒気／chill／shiver／rigor），全部保留，另補"
        "『오슬오슬』『ぞくぞく』『がたがた震え』『shaking chills』。"
        "實測既有 MUST_FIRE『몸이 계속 떨리고 오한이…』『寒気がして体が震える…』"
        "『発熱と震えがあって…』三筆都靠寒冷語/発熱側維持命中。"
    ),
    "下腹（urinary_retention 共現組 site，原掛 ja-JP 段）": (
        "聯集比對下直接命中中文的『下腹』＝下腹部一般（生理痛、腸胃脹氣）："
        "『我這兩天下腹脹得很難受，應該是吃壞肚子』『生理期下腹很脹很痛』"
        "都被判急性尿滯留 critical。日文的尿閉訴說一定伴隨尿語或膀胱"
        "（尿／おしっこ／小水／尿意／膀胱），既有三筆 ja MUST_FIRE 實測都由別的足場命中。"
        "『只講下腹』而完全沒有尿語的形狀，結構上與腸胃脹氣無法區分，"
        "本來就不該由規則層判 critical（語意層仍是後備）。"
    ),
}

# 依 #22 **保留**的同類字面（＋為什麼不移除）。
# 寫出來是為了讓「為什麼只改這幾個」有紀錄，不是留白給下一輪的人猜。
KEPT_LITERALS: dict[str, str] = {
    "寒顫 / chills / 悪寒 / 오한 / ớn lạnh（urosepsis.triggers）": (
        "與被移除的高燒同屬『單軸即 critical』，共現組也接得住（都在 acuity_terms），"
        "但**不在本輪臨床拍板的清單內**。收窄 critical 是臨床決定不是工程決定，"
        "依 #22 不擅自動；下一輪要動請帶臨床覆核。"
    ),
    "整個都是血 / 一大堆血 / heavy bleeding / lots of blood"
    "（gross_hematuria_heavy.triggers）": (
        "同樣沒有泌尿軸（『我手上整個都是血』『heavy bleeding from the cut』會誤報），"
        "但不在本輪拍板清單內。四者都在共現組 acuity（都是血／一大堆血／"
        "lots of blood）裡，若日後拍板可比照 RF-3／RF-5 移除。"
        "⚠️ 2026-08-21 RF-5 只動了 `blood clots`——它是已拍板字面『血塊』的英語版，"
        "屬於補齊實作漏洞；量詞型的這四條是**另一個**臨床問題，依 #22 不擅自擴大。"
    ),
    "かたまり / 덩어리（gross_hematuria_heavy 共現組 acuity）": (
        "與被移除的裸『塊』同一族，但字面長度 ≥3 個音節/字母，"
        "不會成為其他四語常見句子的子字串（#25 的判準），實測 0 誤配 → 保留。"
    ),
    "平熱（『熱で』誤配，urosepsis）": (
        "『体温は平熱でしたが…』仍會因為 acuity 的『熱で』命中（平熱**でした**）。"
        "這是 2026-08-18 那輪為了接住『熱で困っています』收的字面，"
        "本輪不動它——比對引擎沒有否定前綴排除語法，硬擋要嘛加抑制守衛"
        "（#22 舉證過不了），要嘛把『熱で』整條丟掉（日文發燒側損失）。"
        "依偏誤報政策留在誤報側，記在此處供下一輪處理。"
    ),
}


def test_every_removed_literal_has_a_no_miss_argument():
    """#22 舉證責任：每一個被移除的字面都要能說出「為什麼不會造成漏報」。"""
    assert len(REMOVED_LITERAL_JUSTIFICATION) >= 7
    for literal, why in REMOVED_LITERAL_JUSTIFICATION.items():
        assert why and len(why) >= 80, f"{literal} 沒有實質的無漏報論證"


def test_every_kept_literal_of_the_same_class_has_a_reason():
    """對稱：同類但**保留**的字面也要寫明為什麼不動（否則下一輪的人只能猜）。"""
    assert KEPT_LITERALS
    for literal, why in KEPT_LITERALS.items():
        assert why and len(why) >= 60, f"{literal} 沒有保留理由"


# ── 詞表層：被移除的字面不得回到原位 ──────────────────────


def _flag(canonical_id: str) -> dict[str, Any]:
    return next(f for f in URO_RED_FLAGS if f["canonical_id"] == canonical_id)


def _groups(canonical_id: str) -> list[dict[str, Any]]:
    return list(_flag(canonical_id).get("trigger_cooccurrence") or [])


def _all_triggers(canonical_id: str) -> set[str]:
    flag = _flag(canonical_id)
    out = set(flag.get("triggers") or [])
    for kws in (flag.get("triggers_by_lang") or {}).values():
        out.update(kws)
    return out


def _terms(canonical_id: str, key: str) -> set[str]:
    return {t for g in _groups(canonical_id) for t in g.get(key, [])}


RF3_BARE_TRIGGERS_REMOVED: tuple[tuple[str, str], ...] = (
    (HEMATURIA_HEAVY, "血塊"),
    (HEMATURIA_HEAVY, "血の塊"),
    (HEMATURIA_HEAVY, "혈전"),
    (HEMATURIA_HEAVY, "blood clots"),  # RF-5：RF-3 漏掉的第四語
    (UROSEPSIS, "高燒"),
    (UROSEPSIS, "高熱"),
    (UROSEPSIS, "고열"),
    (UROSEPSIS, "high fever"),
    (UROSEPSIS, "sốt cao"),
    (UROSEPSIS, "意識不清"),
)


@pytest.mark.parametrize("canonical_id,literal", RF3_BARE_TRIGGERS_REMOVED)
def test_bare_trigger_without_urinary_axis_stays_removed(canonical_id, literal):
    """RF-3：這些字面不得回到 triggers（回去＝單一個詞就中止問診）。"""
    assert literal not in _all_triggers(canonical_id), (
        f"{literal!r} 回到 {canonical_id} 的裸 triggers。"
        f"要改需臨床重新拍板（前次 2026-08-20）；"
        f"理由見 REMOVED_LITERAL_JUSTIFICATION。"
    )


@pytest.mark.parametrize("canonical_id,literal", RF3_BARE_TRIGGERS_REMOVED)
def test_removed_bare_trigger_is_still_reachable_via_cooccurrence(
    canonical_id, literal
):
    """對稱：移除的前提是共現組接得住——這裡把「接得住」變成斷言，不是讀碼推論。

    英文/越南文由前緣詞邊界涵蓋（fever ⊂ high fever、sốt ⊂ sốt cao），
    所以判準是「acuity 裡有某個詞是這個字面的子字串或等於它」。
    """
    acuities = _terms(canonical_id, "acuity_terms")
    assert any(a in literal for a in acuities), (
        f"{literal!r} 被移出 triggers，但共現組的 acuity_terms 接不住它 → 真漏報"
    )


RF4_SHORT_LITERALS_REMOVED: tuple[tuple[str, str, str], ...] = (
    (HEMATURIA_HEAVY, "acuity_terms", "塊"),
    (RETENTION, "acuity_terms", "できない"),
    (RETENTION, "acuity_terms", "できません"),
    (RETENTION, "acuity_terms", "できていません"),
    (RETENTION, "site_terms", "下腹"),
    (UROSEPSIS, "acuity_terms", "體溫"),
    (UROSEPSIS, "acuity_terms", "体温"),
    (UROSEPSIS, "acuity_terms", "temperature"),
    (UROSEPSIS, "acuity_terms", "떨리"),
    (UROSEPSIS, "acuity_terms", "震え"),
    (UROSEPSIS, "acuity_terms", "ふるえ"),
    (UROSEPSIS, "acuity_terms", "shaking"),
)


@pytest.mark.parametrize("canonical_id,key,literal", RF4_SHORT_LITERALS_REMOVED)
def test_cross_language_misfiring_short_literal_stays_removed(
    canonical_id, key, literal
):
    """RF-4：這些短字面不得回到共現詞表（不變式 #25）。"""
    assert literal not in _terms(canonical_id, key), (
        f"{literal!r} 回到 {canonical_id}.{key}。理由見 REMOVED_LITERAL_JUSTIFICATION；"
        f"全語言聯集比對下它會誤配其他語言的常見句子。"
    )


# ── 行為層：MUST_NOT_FIRE（RF-3/RF-4 的誤報句）─────────────

RF34_MUST_NOT_FIRE: list[tuple[str, str, str]] = [
    # RF-3：不含泌尿軸的血塊 / 發燒
    ("zh-TW", "我腳上有一塊血塊瘀青", "外傷造成的瘀血塊，與泌尿完全無關"),
    ("ja-JP", "足に血の塊ができました", "下腿の血腫、泌尿器と無関係"),
    ("ko-KR", "다리에 혈전이 생겼대요", "下肢深部靜脈血栓＝別的疾病"),
    ("en-US", "i have blood clots in my leg",
     "[RF-5] 下肢深部靜脈血栓的英語版——RF-3 漏掉的第四語"),
    ("en-US", "my son had a high fever last night",
     "[RF-5] 兒子的發燒，第三人稱且句中無任何泌尿描述"),
    ("ja-JP", "体温は平熱でした",
     "[RF-5] 病患報的是**平熱**（正常體溫），句中無泌尿詞"),
    ("ja-JP", "おしっこを我慢できない",
     "[RF-5] 尿意切迫＝急性尿滯留的臨床反義（#25 的最惡性誤配）"),
    ("zh-TW", "大便不通，下腹脹",
     "[RF-5] 便祕造成的下腹脹，跨子句也不得配成急性尿滯留"),
    ("zh-TW", "我上個月因為流感發高燒", "流感造成的發燒，句中無任何泌尿描述"),
    ("en-US", "i had a high fever last week from the flu", "流感造成的發燒，句中無任何泌尿描述"),
    ("vi-VN", "tuần trước tôi bị sốt cao vì cúm", "流感造成的發燒，句中無任何泌尿描述"),
    ("ja-JP", "去年インフルエンザで高熱が出ました", "去年のインフル、泌尿器と無関係"),
    ("ko-KR", "작년에 독감으로 고열이 났었어요", "去年流感造成的發燒，早已痊癒"),
    # RF-4：短字面誤配
    ("ja-JP", "尿路結石の塊が出ました", "結石の塊＝別疾患。裸「塊」の誤配"),
    ("zh-TW", "我尿完之後石頭一塊一塊排出來", "中文量詞「一塊」被裸「塊」誤配"),
    ("ja-JP", "トイレを我慢できないくらい尿意が強いです", "尿意切迫＝尿滯留的臨床反義"),
    ("zh-TW", "護理師剛剛幫我量體溫，我主要是想講排尿的問題", "體溫是度量名詞，護理師量體溫不是發燒"),
    ("ja-JP", "毎朝体温を記録しています、おしっこの回数が多いだけです", "体温は計測名詞"),
    ("en-US", "my temperature was normal, i just have some urinary frequency",
     "病患講的是體溫正常，卻被判成發燒"),
    ("en-US", "the nurse took my temperature at the desk, i am here about my urine flow",
     "護理師在櫃檯量體溫，不是發燒的訴說"),
    ("ko-KR", "커피 때문에 손이 떨리는데 소변 검사 받으러 왔어요", "咖啡因造成的手抖，不是悪寒戰慄"),
    ("ja-JP", "緊張して手が震えます、おしっこの回数だけ気になります", "緊張造成的手部振顫，不是悪寒戰慄"),
    ("en-US", "my hands keep shaking from the medication and i pee often",
     "藥物引起的手抖，不是悪寒戰慄"),
    ("zh-TW", "我這兩天下腹脹得很難受，應該是吃壞肚子", "腸胃脹氣造成的下腹脹，不是尿滯留"),
    ("zh-TW", "生理期下腹很脹很痛", "生理期經痛造成的下腹脹，不是尿滯留"),
    ("vi-VN", "tay tôi run vì uống nhiều cà phê, tôi đi tiểu bình thường",
     "咖啡因手抖 ＋ 排尿正常，不是悪寒"),
]


@pytest.mark.parametrize(
    "language,text,why",
    RF34_MUST_NOT_FIRE,
    ids=[f"{lg}-{i}" for i, (lg, _t, _w) in enumerate(RF34_MUST_NOT_FIRE)],
)
def test_removed_literals_no_longer_over_trigger(detector, language, text, why):
    """RF-3／RF-4 的誤報句一律不得命中任何 critical（命中＝中止整場問診）。"""
    hits = _critical_hits(detector, text, language)
    assert hits == [], f"仍誤報 critical（{why}）：{language} {text!r}\n  命中：{hits}"


# ── 行為層：MUST_FIRE（真臨床情境仍命中）──────────────────

RF34_MUST_FIRE: list[tuple[str, str, str, str]] = [
    # RF-3 的反向釘子：加上泌尿軸就必須命中
    (HEMATURIA_HEAVY, "zh-TW", "這兩天尿裡有血塊掉出來", "血塊 ＋ 尿 ＝ 真的大量血尿"),
    (HEMATURIA_HEAVY, "ja-JP", "おしっこに血の塊が混じっています", "血の塊 ＋ 尿（真の大量血尿）"),
    (HEMATURIA_HEAVY, "ko-KR", "소변에 혈전이 섞여 나와요", "혈전 ＋ 소변（真の大量血尿）"),
    (UROSEPSIS, "zh-TW", "我發高燒而且解小便的時候很痛", "高燒 ＋ 排尿痛（真的尿路感染）"),
    (UROSEPSIS, "en-US", "i have a high fever and it burns every time i pass urine",
     "high fever ＋ dysuria"),
    (UROSEPSIS, "vi-VN", "tôi sốt cao và tiểu buốt suốt hai ngày nay", "sốt cao ＋ tiểu buốt"),
    (UROSEPSIS, "ja-JP", "高熱が出ていて、排尿するたびに痛みます", "高熱 ＋ 排尿時痛（真の尿路感染）"),
    (UROSEPSIS, "ko-KR", "고열이 나고 소변볼 때 아파요", "고열 ＋ 배뇨통（真の尿路感染）"),
    (UROSEPSIS, "zh-TW", "我這兩天意識不清，解尿又痛又渾濁", "意識不清 ＋ 泌尿症狀"),
    (UROSEPSIS, "vi-VN", "tôi bị rét run cả đêm và tiểu ra nước tiểu đục",
     "ớn lạnh run rẩy ＋ 混濁尿"),
    # RF-4 的反向釘子：真的發燒/悪寒/尿閉/血塊講法仍命中
    (UROSEPSIS, "zh-TW", "我量起來體溫三十九度二，而且解小便會刺痛", "病患報發熱域的體溫度數"),
    (UROSEPSIS, "ja-JP", "体温を測ったら三十九度あって、排尿のときにしみます", "体温の実測値が発熱域（書面語を使わない語序）"),
    (UROSEPSIS, "en-US", "i have been running a temperature and my urine is cloudy",
     "running a temperature ＝ 發燒慣用句"),
    (UROSEPSIS, "ko-KR", "오슬오슬 춥고 오한이 나면서 소변이 뿌옇습니다", "悪寒戦慄 ＋ 混濁尿（真の尿路感染）"),
    (UROSEPSIS, "ja-JP", "ぞくぞくして寒気がするし、おしっこが濁っています", "悪寒戦慄 ＋ 混濁尿（真の尿路感染）"),
    (UROSEPSIS, "en-US", "i get shaking chills at night and burning when i urinate",
     "shaking chills ＋ dysuria"),
    (RETENTION, "ja-JP", "朝から排尿ができません、膀胱が張って苦しいです",
     "排尿ができない ＝ 真の尿閉（できない の相隣句収録）"),
    (RETENTION, "ja-JP", "夕方から小便ができなくて、下腹部がパンパンです",
     "小便ができない ＝ 真の尿閉"),
    (HEMATURIA_HEAVY, "ja-JP", "尿に血のかたまりがいくつも出ました", "かたまり 是刻意保留的字面（見 KEPT_LITERALS）"),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    RF34_MUST_FIRE,
    ids=[f"{cid}-{i}" for i, (cid, _l, _t, _w) in enumerate(RF34_MUST_FIRE)],
)
def test_real_clinical_wording_still_fires_after_literal_removal(
    detector, canonical_id, language, text, why
):
    """收窄詞表之後，真的臨床情境**一定**還要命中（否則就是換來一個漏報）。"""
    assert _fired(detector, canonical_id, text, language), (
        f"收窄過頭 → {canonical_id} 漏報（{why}）\n"
        f"  {language} {text!r}\n  本輪命中：{_critical_hits(detector, text, language)}"
    )


def test_rf34_tables_are_both_populated_per_language():
    """雙向對稱的結構性保證（RF-3/RF-4 段）。"""
    for lang in LANGUAGES:
        pos = sum(1 for _c, lg, _t, _w in RF34_MUST_FIRE if lg == lang)
        neg = sum(1 for lg, _t, _w in RF34_MUST_NOT_FIRE if lg == lang)
        assert pos >= 2 and neg >= 2, f"{lang}: 正例 {pos} / 反例 {neg}（各要 ≥2）"


def test_fever_axis_still_has_a_systemic_term_in_all_five_languages():
    """收窄不得把任一語言的發燒/悪寒側整個收光（那就是漏報）。"""
    acuities = _terms(UROSEPSIS, "acuity_terms")
    per_language = {
        "zh-TW": ("發燒", "高燒", "發熱", "寒顫"),
        "ja-JP": ("発熱", "高熱", "微熱", "悪寒", "寒気"),
        "ko-KR": ("열이", "발열", "고열", "오한"),
        "en-US": ("fever", "febrile", "chill", "shiver"),
        "vi-VN": ("sốt", "ớn lạnh", "rét"),
    }
    for language, probes in per_language.items():
        assert any(p in acuities for p in probes), (
            f"{language} 的全身性感染徵象軸被收光 → 該語言的規則層 fallback 死掉"
        )


def test_normal_body_temperature_degrees_are_not_fever_terms():
    """只收**發熱域**度數：平熱（三十六／三十七度台）不得進表，否則量體溫就 critical。"""
    acuities = _terms(UROSEPSIS, "acuity_terms")
    normal = ("三十六度", "三十七度", "36度", "37度", "36도", "37도")
    offenders = [t for t in acuities if t in normal]
    assert offenders == [], f"平熱域度數進了發燒軸：{offenders}"


# ══════════════════════════════════════════════════════════════
# §3b RF-5：同一句話、**跨子句**的 site × acuity 共現（P0 漏報）
# ══════════════════════════════════════════════════════════════
# 2026-08-21。RF-3/RF-4 把裸字面移進共現組之後，這些 canonical 只剩「同一子句」
# 一條路。但病患的自然語序是**同一句話、跨子句**：一個軸在前半句、另一個軸在
# 逗號後面（「我今天小便，然後有很多血塊」）。實測 5 語 15/15 把逗號拿掉就命中
# ＝ 純粹是子句邊界造成的漏報，不是詞表缺口。
#
# 修法：`gross_hematuria_heavy.urine_x_heavy_blood` 補上 `cross_clause: True`
# （urosepsis / urinary_retention / cauda_equina 三組本來就有）。走的是
# `_pairing_scope_ok` 既有分支：只允許**相鄰**子句（中間不得夾完整子句），
# 距離仍受 `_COOCCURRENCE_WINDOW_UNITS`（24 語素當量）約束。
#
# 為什麼不會把 RF-3/RF-4 修掉的誤報放回來（#22 舉證，見下方
# `test_rf5_widening_cannot_resurrect_single_axis_false_positives`
# 把這個論證變成**可執行的斷言**而不是註解）：
#   放寬子句邊界只改「兩個軸可以落在哪裡」，**不減少任何一個軸**。
#   6fc51e3 修掉的每一筆誤報都是**單軸**的——腳上的血塊沒有尿液詞、流感高燒沒有
#   泌尿詞、量體溫是度量名詞、我慢できない是臨床反義、下腹脹沒有尿語——
#   子句邊界放不放寬，第二個軸都配不出來。

RF5_CROSS_CLAUSE_MUST_FIRE: list[tuple[str, str, str, str]] = [
    # ── zh-TW：血塊（RF-3 移除的字面）──
    (
        HEMATURIA_HEAVY, "zh-TW", "我今天小便，然後有很多血塊",
        "[稽核實證] 逗號＋『然後』把尿與血塊切成兩個子句——clot retention 典型主訴",
    ),
    (
        HEMATURIA_HEAVY, "zh-TW", "小便有血，還有一坨一坨的血塊",
        "[稽核實證] 修前只剩 gross_hematuria(high)＝severity 被降級",
    ),
    (
        HEMATURIA_HEAVY, "zh-TW", "我這兩天血尿，而且有血塊",
        "[稽核實證] 逗號＋『而且』；血尿併血塊本身就是 heavy 的臨床判準",
    ),
    (
        HEMATURIA_HEAVY, "zh-TW", "剛剛上廁所小便，裡面都是血塊",
        "逗號直接接續，沒有連接詞——連接詞白名單接不住這一型",
    ),
    # ── ja-JP ──
    (
        HEMATURIA_HEAVY, "ja-JP", "おしっこをしたら、血の塊がたくさん出ました",
        "読点で切れた「〜したら」条件節。尿と血の塊が別子句",
    ),
    (
        HEMATURIA_HEAVY, "ja-JP", "尿をしましたが、血の塊が混じっていました",
        "逆接「が」＋読点。尿が前子句、血の塊が後子句",
    ),
    (
        HEMATURIA_HEAVY, "ja-JP", "今朝トイレに行って、血のかたまりがいくつも出ました",
        "て形＋読点。トイレ（site）と血のかたまり（acuity）が別子句",
    ),
    # ── ko-KR ──
    (
        HEMATURIA_HEAVY, "ko-KR", "소변을 봤는데, 피떡이 많이 나왔어요",
        "연결어미 ~는데 ＋ 쉼표로 소변과 피떡이 갈라진 형태",
    ),
    (
        HEMATURIA_HEAVY, "ko-KR", "오늘 오줌을 눴어요, 그리고 핏덩어리가 나왔어요",
        "쉼표 ＋ 접속사 그리고. 오줌과 핏덩어리가 다른 절",
    ),
    (
        HEMATURIA_HEAVY, "ko-KR", "소변을 보러 갔는데, 덩어리진 피가 나왔습니다",
        "~는데 ＋ 쉼표. 덩어리와 피를 분けて言う自然な語序",
    ),
    # ── en-US ──
    (
        HEMATURIA_HEAVY, "en-US", "i went to pee this morning, and there were blood clots",
        "[RF-5] comma + and；裸 blood clots 移除後只能靠跨子句共現接住",
    ),
    (
        HEMATURIA_HEAVY, "en-US", "i passed some urine, then i saw a lot of blood",
        "comma + then；urine 與 lot of blood 分屬兩個子句",
    ),
    (
        HEMATURIA_HEAVY, "en-US", "i urinated a little while ago, and it was full of blood",
        "comma + and；urinated 與 full of blood 分屬兩個子句",
    ),
    # ── vi-VN ──
    (
        HEMATURIA_HEAVY, "vi-VN", "sáng nay tôi đi tiểu, rồi thấy nhiều máu cục",
        "dấu phẩy + rồi；tiểu ở mệnh đề trước, máu cục ở mệnh đề sau",
    ),
    (
        HEMATURIA_HEAVY, "vi-VN", "tôi vừa đi tiểu xong, và có cục máu đông",
        "dấu phẩy + và；cục máu đông tách khỏi mệnh đề có tiểu",
    ),
    (
        HEMATURIA_HEAVY, "vi-VN", "tôi đi tiểu, nước tiểu ra rất nhiều máu",
        "dấu phẩy nối hai mệnh đề cùng một câu",
    ),
    # ── 其餘被移除字面的跨子句形（本來就由既有 cross_clause 接住，
    #     列進來是為了防止有人把那三組的 cross_clause 一併關掉）──
    (
        UROSEPSIS, "zh-TW", "我從昨天就開始發高燒，然後小便的時候會刺痛",
        "高燒（RF-3 移除）跨子句配泌尿詞",
    ),
    (
        UROSEPSIS, "ja-JP", "高熱が出ています、それから排尿のときに痛みます",
        "高熱（RF-3 移除）が読点越しに排尿と共現",
    ),
    (
        UROSEPSIS, "ko-KR", "고열이 있고요, 배뇨할 때 통증이 있습니다",
        "고열（RF-3 移除）이 쉼표 건너 배뇨와 공기",
    ),
    (
        UROSEPSIS, "vi-VN", "tôi bị sốt cao, rồi tiểu rất buốt",
        "sốt cao（RF-3 移除）qua dấu phẩy vẫn ghép với tiểu buốt",
    ),
    (
        UROSEPSIS, "en-US",
        "i have had a high fever since yesterday, and it burns when i pass water",
        "[RF-5] high fever（RF-3 移除）＋ pass water——RF-3 只用一句 en 驗過，"
        "漏了英式最常用的泌尿詞，移除後這句零紅旗（實測）",
    ),
    (
        UROSEPSIS, "zh-TW", "我今天有點意識不清，而且小便很混濁",
        "意識不清（RF-3 移除）跨子句配泌尿詞",
    ),
    (
        UROSEPSIS, "zh-TW", "我量體溫三十九度，然後小便的時候很痛",
        "體溫（RF-4 移除）改收的發熱域度數，跨子句仍要命中",
    ),
    (
        UROSEPSIS, "ko-KR", "오슬오슬 춥고 오한이 나는데, 소변이 뿌옇습니다",
        "떨리（RF-4 移除）改收的오슬오슬/오한，跨子句仍要命中",
    ),
    (
        RETENTION, "ja-JP", "何度も試しました、でも小便ができません",
        "できない系（RF-4 移除）改收的相鄰片語，跨子句仍要命中",
    ),
    (
        RETENTION, "ja-JP", "昨日の夜から全然おしっこが出ません、下腹が張って痛いです",
        "下腹（RF-4 移除）之後靠おしっこ這一足場，跨子句仍要命中",
    ),
]


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    RF5_CROSS_CLAUSE_MUST_FIRE,
    ids=[f"{cid}-{lg}-{i}" for i, (cid, lg, _t, _w) in enumerate(
        RF5_CROSS_CLAUSE_MUST_FIRE)],
)
def test_same_sentence_cross_clause_cooccurrence_fires(
    detector, canonical_id, language, text, why
):
    """同一句話、跨子句的兩軸共現必須命中 critical（RF-5）。"""
    assert canonical_id in [
        cid for cid, _kw in _critical_hits(detector, text, language)
    ], (
        f"RF-5 回歸：跨子句共現漏報（{why}）\n"
        f"  {language} {text!r}\n  本輪命中：{_critical_hits(detector, text, language)}"
    )


def test_rf5_covers_every_language_with_at_least_three_wordings():
    """五語各 ≥3 種跨子句講法——少一語就代表那一語的跨子句路徑沒被量過。"""
    for lang in LANGUAGES:
        n = sum(1 for _c, lg, _t, _w in RF5_CROSS_CLAUSE_MUST_FIRE if lg == lang)
        assert n >= 3, f"{lang} 只有 {n} 筆 RF-5 跨子句正例（要求 ≥3）"


# ── 反方向：放寬子句邊界不得把 6fc51e3 修掉的誤報放回來 ──────────

RF5_CROSS_CLAUSE_MUST_NOT_FIRE: list[tuple[str, str, str]] = [
    # 單軸：整句沒有第二個軸，跨子句也配不出來（RF-5 論證的核心）
    ("zh-TW", "我腳上有一塊瘀青，裡面好像有血塊",
     "兩個子句講的都是腳，全句零泌尿詞——放寬邊界也不該命中"),
    ("ja-JP", "足をぶつけました、血の塊ができています",
     "打撲と血腫、二つの子句とも泌尿器と無関係"),
    ("ko-KR", "다리가 부었는데, 혈전이 생겼다고 합니다",
     "~는데 로 이어진 두 절 모두 하지 정맥 이야기"),
    ("en-US", "i bumped my leg, and now there are blood clots under the skin",
     "comma + and，兩個子句都在講腿部血腫"),
    ("vi-VN", "chân tôi bị bầm, và có cục máu đông ở đó",
     "hai mệnh đề đều nói về chân, không có từ tiết niệu nào"),
    ("vi-VN", "tôi đi tiểu nhiều lần trong ngày, và ban đêm cũng vậy",
     "頻尿主訴的越南語版；量詞不帶血就不得配成大量血尿"),
    # 血塊型的唯一危險誤報面：量詞不帶血（頻尿主訴），跨子句也不得命中
    ("zh-TW", "我最近小便次數很多，一天要跑十幾次廁所",
     "頻尿是門診第一大主訴；acuity 必須自帶血語意，量詞不算"),
    ("en-US", "i have been peeing a lot lately, and it happens all night",
     "頻尿主訴的英語版，跨子句也不得配成大量血尿"),
    ("ja-JP", "おしっこの回数が多いです、夜も何回も起きます",
     "頻尿の訴え。読点越しでも血語がないので命中してはいけない"),
    # 明確否認：跨子句放寬不得繞過否定守衛
    ("zh-TW", "我小便看起來正常，沒有血塊也沒有血",
     "病患明確否認血塊，兩個軸都在但後子句是否認"),
    ("en-US", "my urine looks clear, and there are no blood clots at all",
     "明確否認的英語版"),
    ("ko-KR", "소변은 깨끗한데, 피떡 같은 건 전혀 없어요",
     "~는데 로 이어진 명확한 부인"),
    # RF-4 的反義／度量名詞：跨子句也不得復活
    ("ja-JP", "尿意はありますが、我慢できないほどではありません",
     "尿意切迫の否定形。できない系は acuity から外れているので命中しない"),
    ("en-US", "the nurse checked my temperature, and then asked about my urine",
     "度量名詞＋泌尿詞跨子句——temperature 已不在 acuity"),
    ("zh-TW", "我大便解不出來，下腹很脹",
     "便祕的兩子句形；下腹已不是 site，解不出配不到泌尿詞"),
]


@pytest.mark.parametrize(
    "language,text,why",
    RF5_CROSS_CLAUSE_MUST_NOT_FIRE,
    ids=[f"{lg}-{i}" for i, (lg, _t, _w) in enumerate(
        RF5_CROSS_CLAUSE_MUST_NOT_FIRE)],
)
def test_cross_clause_widening_does_not_over_trigger(detector, language, text, why):
    """RF-5 的放寬最危險的失敗方向：把單軸誤報跨子句配起來。"""
    hits = _critical_hits(detector, text, language)
    assert hits == [], (
        f"RF-5 擺盪成 over-trigger（{why}）：{language} {text!r}\n  命中：{hits}"
    )


def test_rf5_negative_table_covers_every_language():
    """雙向對稱的結構性保證（RF-5 段）。"""
    for lang in LANGUAGES:
        n = sum(1 for lg, _t, _w in RF5_CROSS_CLAUSE_MUST_NOT_FIRE if lg == lang)
        assert n >= 2, f"{lang} 只有 {n} 筆 RF-5 反例（要求 ≥2）"


def test_rf5_residual_over_trigger_is_recorded_not_hidden(detector):
    """RF-5 換來的**新誤報面**，寫成正向斷言而不是藏在註解裡。

    放寬子句邊界之後，「兩個不同臨床事件剛好講在相鄰子句」會配起來：
    病患先講腳上的瘀血塊、下一個子句才轉到小便。這是 RF-5 的代價，不是缺陷——
    依 2026-07-27 臨床拍板（#22 偏誤報：誤中止＝護理師走一趟，可逆；
    漏報＝clot retention 病患繼續坐著等，不可逆）取這一側。
    形狀與 urosepsis 早就記載的殘餘（「上週發燒」＋「今天頻尿」）同型。

    ⚠️ 要把它改成不觸發需要**新的臨床拍板**。工程上唯一的修法是加抑制守衛，
    而距離與標點都分不出「兩個事件」與「同一件事講成兩句」——後者正是
    RF5_CROSS_CLAUSE_MUST_FIRE 那 16 句。有人加守衛擋掉它時，這條會當場變紅。
    """
    for language, text in (
        ("zh-TW", "我上個月腳上有血塊，今天想問小便的問題"),
        ("en-US", "i have blood clots in my leg, and i also want to ask about my urine"),
    ):
        assert HEMATURIA_HEAVY in [
            cid for cid, _kw in _critical_hits(detector, text, language)
        ], (
            f"殘餘誤報被擋掉了（{language} {text!r}）——若是刻意的，"
            "請先證明它不會把 RF5_CROSS_CLAUSE_MUST_FIRE 的真急症一起擋掉。"
        )


def test_rf5_residual_is_bounded_by_the_parenthetical_rule(detector):
    """對照組：界定上面那個殘餘的**範圍**，證明放寬不是「整句話串起來」。

    ⚠️ 2026-08-21 敵意複驗訂正：本測試的前一版 docstring 寫「中間只要夾了**一個
    完整子句**就不配對」——**那句話是假的**，而且它選的三句填充語剛好都沒有時間錨點，
    所以測試通過測到的不是它宣稱的那件事。真正的邊界是 `_pairing_scope_ok` 的
    **插入語分支**（`middles` 非空時走這裡，`cross_clause` 只是多開了 `middles` 為空
    的那條捷徑）：中間夾的每一個完整子句都必須

        ① `_span_units(p) <= _PARENTHETICAL_MAX_UNITS`（14 語素當量）**且**
        ② `_has_current_episode_evidence(p)`（時間錨點或急性伴隨症狀），
        ③ 且完整子句最多 `_PARENTHETICAL_MAX_SEGMENTS`（2）個。

    三個條件任一不成立才不配對。下面每一筆各壞掉其中一個條件（`why` 註明是哪個），
    含時間錨點的那一型另見
    `test_rf5_time_anchored_middle_clause_still_pairs_which_is_the_real_residual`。
    """
    bounded = [
        (
            "我上個月腳上有血塊，前陣子去看了骨科，今天想問小便的問題",
            "壞條件②：『前陣子』不是當前發作證據（_has_current_episode_evidence=False）",
        ),
        (
            "我腳上有血塊，骨科說是撞到的沒關係，那個已經好了，今天想問小便",
            "壞條件②：兩個填充子句都沒有時間錨點",
        ),
        (
            "我腳上有一塊血塊瘀青，那是撞到桌角造成的已經在消了，今天主要是想問排尿的問題",
            "壞條件②＋距離：填充子句無錨點，且兩軸相距超過 24 語素當量",
        ),
        (
            "我上個月腳上有血塊，昨天早上很早就去看了骨科而且等很久，今天想問小便的問題",
            "壞條件①：填充子句含時間錨點但 17 語素當量 > 14",
        ),
        (
            "我上個月腳上有血塊，昨天去看骨科，今天早上又去拿藥，剛剛才回來，等一下想問小便",
            "壞條件③：中間夾了 3 個完整子句 > 2（每一個都自帶時間錨點）",
        ),
        (
            "我上個月腳上有血塊，昨天去看了骨科，醫生說沒事要我多休息不要亂動，今天想問小便的問題",
            "壞條件②：兩個填充子句中的第二個沒有當前發作證據——要求的是『每一個都要有』",
        ),
    ]
    for text, why in bounded:
        assert _critical_hits(detector, text, "zh-TW") == [], (
            f"相鄰子句的放寬外溢（{why}）：{text!r}"
        )


def test_rf5_time_anchored_middle_clause_still_pairs_which_is_the_real_residual(
    detector,
):
    """把上一條訂正出來的**真實殘餘**寫成正向斷言，而不是留在錯誤的 docstring 裡。

    中間子句只要**短且自帶時間錨點**就照配——真人敘事充滿時間詞，所以殘餘的範圍
    比前一版文件所述寬。五語同型（複驗實測 zh/en/ko 三語，這裡各留一筆）。

    ⚠️ 為什麼**不**收緊實作（#22 的漏報舉證，這是本輪的判斷）：
    插入語分支不是 RF-5 加的，它是 2026-07-27 第四輪 Gate 為了**真急症**放寬的——
    `test_rf5_parenthetical_branch_is_load_bearing_for_real_emergencies` 那兩句
    （clot retention 與 torsion）走的就是同一條分支。要擋掉本測試的三句，只能拿掉
    「短＋時間錨點的插入語仍算同一件事」這條規則，而那會同時切掉那兩句真急症 ＝
    用一個可逆的誤報換一個不可逆的漏報，方向錯。

    要改成不觸發需要**新的臨床拍板**（與 `test_rf5_residual_over_trigger_is_recorded_not_hidden`
    同一個決策）。有人加守衛擋掉它時，這條會當場變紅。
    """
    for language, text, why in (
        (
            "zh-TW",
            "我上個月腳上有血塊，昨天去看了骨科，今天想問小便的問題",
            "[複驗實證] 中間子句『昨天去看了骨科』＝7 語素當量＋時間錨點",
        ),
        (
            "zh-TW",
            "我上個月腳上有血塊，剛剛去看了骨科，今天想問小便的問題",
            "[複驗實證] 同型，錨點換成『剛剛』",
        ),
        (
            "en-US",
            "i peed today, i fell down this morning, my leg has a blood clot",
            "[複驗實證] 英語同型：this morning 是錨點",
        ),
        (
            "ko-KR",
            "소변을 봤어요, 어제 넘어졌어요, 다리에 혈전이 있어요",
            "[複驗實證] 韓語同型：어제 是錨點",
        ),
    ):
        assert HEMATURIA_HEAVY in [
            cid for cid, _kw in _critical_hits(detector, text, language)
        ], (
            f"真實殘餘被擋掉了（{why}）：{language} {text!r}——若是刻意的，"
            "請先證明它不會把下一條的真急症一起擋掉。"
        )


def test_rf5_parenthetical_branch_is_load_bearing_for_real_emergencies(detector):
    """承重釘：上一條的殘餘與這兩句真急症**共用同一條插入語分支**。

    有人為了擋掉殘餘而收緊 `_PARENTHETICAL_*` 或關掉插入語分支時，這條會同時變紅，
    讓「這是一個取捨不是一個 bug」在測試層面看得見。
    """
    for language, text, why in (
        (
            "zh-TW",
            "我今天小便，剛剛看了一下，有很多血塊",
            "clot retention：插入語『剛剛看了一下』把尿與血塊隔開，語意上是同一件事",
        ),
        (
            "zh-TW",
            "我的睪丸，就是剛剛在停車場的時候，忽然痛到冒冷汗",
            "torsion：2026-07-27 第四輪 Gate 放寬到 14 語素當量的原始理由句",
        ),
    ):
        assert _critical_hits(detector, text, language), (
            f"插入語分支被收緊 → 真急症漏報（{why}）：{text!r}"
        )


def test_rf5_widening_cannot_resurrect_single_axis_false_positives(detector):
    """把 #22 的舉證變成可執行的斷言，而不是註解裡的一句話。

    論證：`cross_clause` 只放寬「兩個軸可以落在哪裡」，不減少任何一個軸；
    6fc51e3 修掉的誤報全部是**單軸**的，所以結構上不可能因為放寬邊界而回來。
    這裡把論證的前提（單軸）與結論（不命中）**兩件事都測**：
      前提——把該紅旗的另一個軸整組拿掉之後，那些句子本來就不會命中；
      結論——現行詞表下它們仍然不命中。
    前提若不成立（句子其實兩軸都有），這筆語料對本論證沒有承重，測試會明講。
    """
    single_axis = [
        (HEMATURIA_HEAVY, "site_terms", "zh-TW", "我腳上有一塊血塊瘀青"),
        (HEMATURIA_HEAVY, "site_terms", "ja-JP", "足に血の塊ができました"),
        (HEMATURIA_HEAVY, "site_terms", "ko-KR", "다리에 혈전이 생겼대요"),
        (HEMATURIA_HEAVY, "site_terms", "en-US", "i have blood clots in my leg"),
        (UROSEPSIS, "site_terms", "zh-TW", "我上個月因為流感發高燒"),
        (UROSEPSIS, "site_terms", "en-US", "my son had a high fever last night"),
        (UROSEPSIS, "site_terms", "vi-VN", "tuần trước tôi bị sốt cao vì cúm"),
        (UROSEPSIS, "site_terms", "ja-JP", "去年インフルエンザで高熱が出ました"),
        (UROSEPSIS, "site_terms", "ko-KR", "작년에 독감으로 고열이 났었어요"),
        # ⚠️ 「体温は平熱でした」缺的是 **site** 軸不是 acuity——它其實會命中
        # acuity 的「熱で」（平熱**でした**，見 KEPT_LITERALS 的已知殘餘誤報），
        # 安全性來自整句沒有任何泌尿詞。標錯軸的話這筆就變成空跑。
        (UROSEPSIS, "site_terms", "ja-JP", "体温は平熱でした"),
        (RETENTION, "acuity_terms", "ja-JP", "おしっこを我慢できない"),
        (RETENTION, "site_terms", "zh-TW", "大便不通，下腹脹"),
    ]
    for canonical_id, missing_axis, language, text in single_axis:
        group = _groups(canonical_id)[0]
        present_axis = (
            "acuity_terms" if missing_axis == "site_terms" else "site_terms"
        )
        # 前提：這句話在**另一個軸**上確實找不到任何詞（＝真的是單軸）
        hits_on_missing = [
            t for t in group[missing_axis] if t.lower() in text.lower()
        ]
        assert hits_on_missing == [], (
            f"這筆語料其實兩軸都有（{missing_axis} 命中 {hits_on_missing}），"
            f"對『放寬邊界不會放回單軸誤報』這個論證沒有承重：{text!r}"
        )
        assert group[present_axis], present_axis
        # 結論：現行詞表下不得命中 critical
        assert _critical_hits(detector, text, language) == [], (
            f"單軸誤報回來了：{language} {text!r}"
        )


# ══════════════════════════════════════════════════════════════
# §3c RF-6：越南文 `tiểu` 的詞義假朋友（2026-08-21 敵意複驗）
# ══════════════════════════════════════════════════════════════
# 缺陷：`tiểu` 的泌尿義是「排尿」，但它同時是漢越詞「小」的構詞成分，而越南文以
# **音節分寫**（複合詞中間有空白）→ `tiểu đường`(糖尿病)／`tiểu cầu`(血小板)／
# `tiểu sử`(病史)／`tiểu học`(小學) 裡的 `tiểu` 兩側都是合法詞界，**詞邊界救不了**。
# RF-5 打開 `cross_clause` 之後，只要相鄰子句出現任何血塊詞就配成 critical：
#   「tôi bị tiểu đường, và chân tôi có cục máu đông」→ gross_hematuria_heavy(critical)
# 糖尿病是泌尿科 intake 的第一常見共病，這不是邊緣情況；而且它會把「大量血尿」寫進
# SOAP 紅旗區塊 ＝ 病歷裡出現病患從未主訴的臨床發現。
#
# 修法是 `red_flag_detector._TERM_FALSE_FRIENDS`（詞義假朋友排除），**不是**把
# site_terms 的裸 `tiểu` 換成 `đi tiểu`／`nước tiểu`／`tiểu buốt`／`tiểu ra` 片語——
# 下面 `RF6_VI_URINARY_MUST_STILL_FIRE` 的「khi tiểu…」「tôi tiểu ra…」正是**動詞裸用**
# 的語序，改收片語會直接開出漏報（#22）。

RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE: list[tuple[str, str]] = [
    (
        "tôi bị tiểu đường, và chân tôi có cục máu đông",
        "[複驗實證] 糖尿病＋下肢 DVT：兩個子句都與泌尿無關",
    ),
    (
        "tôi bị tiểu đường và cao huyết áp, và tôi có máu đông ở chân",
        "[複驗實證] intake 併發症標準答句（糖尿病＋高血壓）",
    ),
    (
        "mẹ tôi bị tiểu đường, và bà ấy có cục máu đông",
        "[複驗實證] 家族史＝別人的病，卻被判成本人 critical",
    ),
    (
        "bác sĩ hỏi tiểu sử bệnh, tôi có cục máu đông ở chân",
        "tiểu sử＝病史；問診情境的高頻字",
    ),
    (
        "tôi vừa làm tiểu phẫu, sau đó chảy rất nhiều máu",
        "tiểu phẫu＝小手術；術後出血不是血尿",
    ),
    (
        "con tôi đang học tiểu học, cháu bị chảy nhiều máu ở chân",
        "tiểu học＝小學",
    ),
    (
        "tôi bị giảm tiểu cầu, và tôi có cục máu đông ở chân",
        "tiểu cầu＝血小板；血小板低下與出血/血栓同句是臨床常態",
    ),
    # ↓ 2026-08-21 複驗第二輪補收的五條（前四條是病患轉述影像／病理報告時的用詞）
    (
        "bác sĩ nói tôi có phình tiểu động mạch, và chân tôi có cục máu đông",
        "tiểu động mạch＝細動脈；報告用詞與下肢血栓同句是常態",
    ),
    (
        "kết quả siêu âm thấy giãn tiểu tĩnh mạch, chân tôi có cục máu đông",
        "tiểu tĩnh mạch＝小靜脈",
    ),
    (
        "phim chụp có tổn thương ở tiểu khung, tôi bị sốt cao mấy hôm nay",
        "tiểu khung＝小骨盆腔；骨盆影像報告高頻詞",
    ),
    (
        "sinh thiết thấy viêm ở tiểu thùy, tôi vẫn còn sốt cao",
        "tiểu thùy＝小葉；病理報告高頻詞",
    ),
    (
        "tôi đang đọc tiểu thuyết thì thấy chảy rất nhiều máu ở mũi",
        "tiểu thuyết＝小說；複驗實測誤報 critical 的日常詞",
    ),
]

# 開放尾巴：**沒有**收進 `_TERM_FALSE_FRIENDS`、實測仍會誤報的「小」義複合詞。
# 這不是待辦清單而是**規格**——漢越詞「小」的構詞沒有上限，這張排除表結構上不可能
# 完備。釘住它是為了讓「收到 vi 誤中止回報」的下一個人第一個假設就對：
# 先查是不是又一個沒收錄的複合詞，而不是以為這條路已經封死。
RF6_VI_KNOWN_OPEN_TAIL: tuple[str, ...] = (
    "tiểu thương",  # 小商販
    "tiểu bang",  # 州
    "tiểu thư",  # 小姐
)

RF6_VI_URINARY_MUST_STILL_FIRE: list[tuple[str, str, str]] = [
    (
        HEMATURIA_HEAVY, "khi tiểu tôi thấy nhiều máu cục",
        "動詞裸用（khi tiểu）：改收片語就會漏掉這一型",
    ),
    (
        HEMATURIA_HEAVY, "tôi tiểu ra máu cục rất nhiều",
        "動詞裸用（tiểu ra）",
    ),
    (
        HEMATURIA_HEAVY, "nước tiểu của tôi toàn máu cục",
        "名詞用法（nước tiểu）",
    ),
    (
        HEMATURIA_HEAVY, "tôi bị tiểu đường, và khi đi tiểu ra rất nhiều máu cục",
        "★ 同一句同時有假朋友與真泌尿義——排除只吃假朋友那一處",
    ),
    (
        HEMATURIA_HEAVY, "tôi bị giảm tiểu cầu và đi tiểu ra nhiều máu cục",
        "★ 血小板低下＋真血尿：假朋友不得把後半句一起吃掉",
    ),
    (
        UROSEPSIS, "tôi bị tiểu đường và tiểu buốt, sốt cao",
        "★ 糖尿病＋排尿灼痛＋高燒＝真 urosepsis（糖尿病本身就是危險因子）",
    ),
    (
        RETENTION, "tôi bị bí tiểu sử dụng thuốc gì được không",
        "已知殘餘的對照：`tiểu sử` 遮住裸 tiểu，但 `bí tiểu` 跨過遮罩起點仍命中",
    ),
]


@pytest.mark.parametrize(
    "text,why",
    RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE,
    ids=[f"ff-{i}" for i, _ in enumerate(RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE)],
)
def test_rf6_vi_term_false_friends_do_not_fire_the_urinary_axis(detector, text, why):
    """`tiểu` 落在漢越複合詞裡時不是「排尿」，不得配出泌尿軸 critical。"""
    hits = _critical_hits(detector, text, "vi-VN")
    assert hits == [], f"詞義假朋友誤報（{why}）：{text!r}\n  命中：{hits}"


@pytest.mark.parametrize(
    "canonical_id,text,why",
    RF6_VI_URINARY_MUST_STILL_FIRE,
    ids=[f"real-{i}" for i, _ in enumerate(RF6_VI_URINARY_MUST_STILL_FIRE)],
)
def test_rf6_vi_real_urinary_wordings_still_fire(detector, canonical_id, text, why):
    """反方向：排除表不得吃掉任何一種泌尿義的語序（#22 的漏報舉證）。"""
    hits = _critical_hits(detector, text, "vi-VN")
    assert canonical_id in [cid for cid, _kw in hits], (
        f"詞義假朋友排除開出漏報（{why}）：{text!r}\n  命中：{hits}"
    )


def test_rf6_false_friend_table_only_contains_non_urinary_compounds(detector):
    """把收錄判準變成可執行的斷言：泌尿義的 `tiểu` 複合詞不得被收進排除表。

    `tiểu đêm`(夜尿)／`tiểu tiện`／`tiểu buốt`／`tiểu rắt`／`tiểu són`／`tiểu ra`
    任何一條被加進去，都是**直接把泌尿主訴關掉**。
    """
    urinary_compounds = (
        "tiểu đêm", "tiểu tiện", "tiểu buốt", "tiểu rắt", "tiểu són",
        "tiểu ra", "tiểu máu", "tiểu khó", "tiểu nhiều", "tiểu dắt",
    )
    for friend in rfd_module._TERM_FALSE_FRIENDS:
        assert friend not in urinary_compounds, (
            f"排除表收進了泌尿義的複合詞 {friend!r} → 那是漏報不是語意修正"
        )
        assert " " in friend, (
            f"排除表只收空白分隔的複合詞（單音節會把整個詞義關掉）：{friend!r}"
        )


@pytest.mark.parametrize("compound", RF6_VI_KNOWN_OPEN_TAIL)
def test_rf6_false_friend_table_is_an_open_ended_list_not_a_closed_set(
    detector, compound
):
    """把「這張表列不完」釘成可執行的事實，而不是只寫在註解裡。

    這些「小」義複合詞**沒有**收進 `_TERM_FALSE_FRIENDS`，所以裸 `tiểu` 照樣供給
    泌尿軸、相鄰子句有血塊詞就配成 critical。這條測試斷言那件事**還在發生**——
    它紅掉代表有人把某一條收進表裡了，那是好事，請把它從 `RF6_VI_KNOWN_OPEN_TAIL`
    移到 `RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE`，並確認碼內註解那句「開放式列舉」還在。

    為什麼要留下這種「斷言誤報仍存在」的測試（沿用 `test_known_residual_…` 的慣例）：
    否則下一個收到 vi 誤中止回報的人，會因為看到一張表就以為這條路已經封死，
    去別的地方找根因。
    """
    text = f"tôi có {compound}, và chân tôi có cục máu đông"
    assert _critical_hits(detector, text, "vi-VN"), (
        f"{compound!r} 已經不再誤報了——請把它從 RF6_VI_KNOWN_OPEN_TAIL 移進 "
        "RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE（並保留「開放式列舉」那段註解）"
    )
    assert compound not in rfd_module._TERM_FALSE_FRIENDS, (
        f"{compound!r} 同時出現在排除表與開放尾巴清單，兩者必須互斥"
    )


def test_rf6_injection_removing_the_false_friend_table_turns_red(detector, monkeypatch):
    """注入式回歸：把排除表清空 → 上面的誤報必須整批回來。

    沒有這條，`RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE` 可能因為別的原因剛好是綠的。
    """
    monkeypatch.setattr(rfd_module, "_TERM_FALSE_FRIENDS", ())
    resurrected = [
        text
        for text, _why in RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE
        if _critical_hits(detector, text, "vi-VN")
    ]
    assert len(resurrected) == len(RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE), (
        "清空排除表之後只有 "
        f"{len(resurrected)}/{len(RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE)} 筆誤報回來 → "
        "其餘語料對本修復沒有承重（它們是靠別的機制不命中的），請換語料。\n"
        f"  承重的：{resurrected}"
    )


# ══════════════════════════════════════════════════════════════
# §4 D-6：DB 規則路徑（regex 守衛 ＋ canonical_id NULL）
# ══════════════════════════════════════════════════════════════


class _FakeRule:
    """模擬 `app.models.red_flag_rule.RedFlagRule` 的最小面。"""

    def __init__(
        self,
        name: str,
        *,
        canonical_id: str | None = None,
        keywords: list[str] | None = None,
        regex_pattern: str | None = None,
        severity: str = "critical",
    ) -> None:
        self.id = f"rule-{name}"
        self.canonical_id = canonical_id
        self.name = name
        self.display_title_by_lang = {}
        self.severity = severity
        self.category = name
        self.keywords = keywords or []
        self.regex_pattern = regex_pattern
        self.description = "db rule"
        self.suggested_actions = []
        self.is_active = True


def test_db_regex_path_respects_the_negation_guard(monkeypatch):
    """D-6：regex 命中也要過否定守衛，否則守衛對 DB 規則靜默失效。"""
    rule = _FakeRule(
        "大量血尿",
        canonical_id=HEMATURIA_HEAVY,
        keywords=[],
        regex_pattern=r"血塊",
    )
    det = _make_detector(monkeypatch, [rule])
    assert det._rule_based_detect("我今天尿裡有血塊", "zh-TW"), "肯定陳述應命中"
    assert det._rule_based_detect("我完全沒有血塊", "zh-TW") == [], (
        "D-6 回歸：regex 路徑繞過否定守衛 → 明確否認也判 critical"
    )


def test_db_regex_path_picks_the_first_non_negated_occurrence(monkeypatch):
    """一處否認、一處肯定 → 仍要命中（fail-open，與關鍵字路徑一致）。"""
    rule = _FakeRule(
        "大量血尿",
        canonical_id=HEMATURIA_HEAVY,
        keywords=[],
        regex_pattern=r"血塊",
    )
    det = _make_detector(monkeypatch, [rule])
    assert det._rule_based_detect("上週沒有血塊，今天尿裡有血塊", "zh-TW"), (
        "regex 守衛把 fail-open 也一起關掉了"
    )


def test_db_regex_guard_is_disabled_together_with_the_kill_switch(monkeypatch):
    """kill-switch 關閉 → regex 退回裸比對（與關鍵字路徑同一個開關）。"""
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    settings = _settings()
    settings.RED_FLAG_NEGATION_GUARD = False
    rule = _FakeRule(
        "大量血尿", canonical_id=HEMATURIA_HEAVY, keywords=[], regex_pattern=r"血塊"
    )
    det = RedFlagDetector(settings, _FakeDB([rule]))
    asyncio.run(det._load_rules())
    assert det._rule_based_detect("我完全沒有血塊", "zh-TW"), (
        "kill-switch 關閉時 regex 應退回裸比對"
    )


def test_db_rule_with_null_canonical_id_is_recovered_from_name(monkeypatch, caplog):
    """D-6：canonical_id 為 NULL 時用 name 反查目錄救回，並留 warning。

    救不回來的話，共現組（以 canonical_id 查表）對該規則整層失效——
    那正是 2026-07-27 量到 60/61 漏報的形狀，而且完全沒有訊號。
    """
    rule = _FakeRule("急性尿滯留", canonical_id=None, keywords=["尿滯留"])
    with caplog.at_level("WARNING"):
        det = _make_detector(monkeypatch, [rule])
    assert det._rules[0]["canonical_id"] == RETENTION
    assert any("canonical_id" in r.message for r in caplog.records), (
        "canonical_id 為空時沒有留下任何可觀測訊號"
    )
    # 救回之後共現組要真的活著（口語語序、沒有任何裸 trigger 相鄰）
    assert _fired(det, RETENTION, "從今天早上開始膀胱脹到快爆，一滴都解不出", "zh-TW"), (
        "canonical_id 救回了，但共現組沒有跟著生效"
    )


def test_db_rule_with_unrecoverable_canonical_id_logs_and_falls_back(
    monkeypatch, caplog
):
    """救不回來 → 保留 name 當身份（dedup 仍需要身份），但要 log warning。"""
    rule = _FakeRule("院內自訂規則 X", canonical_id=None, keywords=["自訂關鍵字"])
    with caplog.at_level("WARNING"):
        det = _make_detector(monkeypatch, [rule])
    assert det._rules[0]["canonical_id"] == "院內自訂規則 X"
    assert any("backfill" in r.message for r in caplog.records), (
        "無法救回時沒有 log 出「共現組不會生效」這件事"
    )


# ══════════════════════════════════════════════════════════════
# §5 D-7：LLM 自創紅旗的去重身份正規化
# ══════════════════════════════════════════════════════════════

_SAME_FLAG_DIFFERENT_SPELLINGS = (
    "Testicular Torsion Suspected",
    "testicular torsion suspected",
    "  Testicular  Torsion   Suspected  ",
    "TESTICULAR TORSION SUSPECTED",
)


def test_normalize_canonical_id_collapses_case_and_whitespace():
    keys = {normalize_canonical_id(s) for s in _SAME_FLAG_DIFFERENT_SPELLINGS}
    assert len(keys) == 1, f"同一個紅旗的四種寫法沒有收斂成同一個身份：{keys}"


def test_normalize_canonical_id_is_identity_for_catalogue_ids():
    """對內建目錄的 snake_case id 必須是恆等變換（否則所有既有身份都會漂移）。"""
    for flag in URO_RED_FLAGS:
        cid = flag["canonical_id"]
        assert normalize_canonical_id(cid) == cid, cid


def test_llm_invented_flag_gets_a_normalized_canonical_id(monkeypatch):
    """語意層對目錄外的紅旗，canonical_id 必須是正規化後的字串（D-7）。"""
    det = _make_detector(monkeypatch)

    class _Msg:
        content = json.dumps(
            {
                "alerts": [
                    {
                        "title": "  Priapism   Suspected ",
                        "severity": "critical",
                        "description": "d",
                        "trigger_reason": "r",
                        "suggested_actions": [],
                    }
                ]
            }
        )

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    async def _fake_call(fn):
        return _Resp()

    monkeypatch.setattr(rfd_module, "call_with_retry", _fake_call)
    alerts = asyncio.run(det._semantic_detect("x", {"session_id": "s"}, "en-US"))
    assert alerts[0]["canonical_id"] == "priapism suspected", alerts[0]
    # 顯示用的 title 仍是 LLM 原文（護理站看到的文字不變）
    assert alerts[0]["title"] == "  Priapism   Suspected "


def test_merge_dedups_the_same_llm_flag_written_differently():
    """同一輪語意層用兩種寫法回同一個自創紅旗 → 只能是一筆（D-7）。"""
    alerts = [
        {
            "canonical_id": normalize_canonical_id(s),
            "severity": "high",
            "title": s,
            "description": "",
            "trigger_reason": s,
            "alert_type": "semantic",
            "trigger_keywords": None,
            "llm_analysis": None,
            "confidence": "semantic_only",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
        for s in _SAME_FLAG_DIFFERENT_SPELLINGS
    ]
    merged = RedFlagDetector._merge_and_deduplicate([], alerts, "en-US")
    assert len(merged) == 1, f"「換句話說的同一個紅旗」沒有合併：{merged}"


def test_merge_dedups_even_when_canonical_id_itself_is_unnormalized():
    """防禦上游：canonical_id 欄位本身帶大小寫/空白時也要合併。"""
    alerts = [
        {
            "canonical_id": s,
            "severity": "high",
            "title": s,
            "description": "",
            "trigger_reason": s,
            "alert_type": "semantic",
            "trigger_keywords": None,
            "llm_analysis": None,
            "confidence": "semantic_only",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
        for s in _SAME_FLAG_DIFFERENT_SPELLINGS
    ]
    merged = RedFlagDetector._merge_and_deduplicate([], alerts, "en-US")
    assert len(merged) == 1, f"_dedup_key 沒有正規化 canonical_id：{merged}"


def test_cross_turn_dedup_identity_is_normalized():
    """跨輪去重身份（Redis hash 欄位）也要收斂成同一個字串（D-7）。"""
    identities = {
        alert_dedup.alert_dedup_identity({"canonical_id": s, "title": s})
        for s in _SAME_FLAG_DIFFERENT_SPELLINGS
    }
    assert identities == {"testicular torsion suspected"}, identities


def test_dedup_identity_still_fails_open_when_identity_is_unknown():
    """對稱：沒有身份就是不去重（fail-open，寧重複不可漏急症）。"""
    assert alert_dedup.alert_dedup_identity({}) is None
    assert alert_dedup.alert_dedup_identity({"canonical_id": "   ", "title": ""}) is None


def test_dedup_identity_is_unchanged_for_catalogue_alerts():
    """既有目錄紅旗的身份字串不得漂移（漂移＝所有在飛的 session 去重重來一次）。"""
    for flag in URO_RED_FLAGS:
        cid = flag["canonical_id"]
        assert alert_dedup.alert_dedup_identity({"canonical_id": cid}) == cid


# ══════════════════════════════════════════════════════════════
# §6 語料獨立性（測試設計第 2、3 點）
# ══════════════════════════════════════════════════════════════

_RESULTS_GLOB = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "scripts", "e2e_realopenai", "results", "*.json",
)


def _all_corpus_texts() -> list[str]:
    return (
        [t for _c, _l, t, _w in RF1_RULE_HIT_MUST_SURVIVE]
        + [t for _c, _l, t, _w in SEMANTIC_HALLUCINATION_MUST_BE_SUPPRESSED]
        + [t for _c, _l, t, _w in RF2_HISTORY_DENIAL_MUST_FIRE]
        + [t for _l, t in RF2_REAL_DENIAL_MUST_NOT_FIRE]
        + [t for _l, t, _w in RF34_MUST_NOT_FIRE]
        + [t for _c, _l, t, _w in RF34_MUST_FIRE]
        + [t for _c, _l, t, _w in RF5_CROSS_CLAUSE_MUST_FIRE]
        + [t for _l, t, _w in RF5_CROSS_CLAUSE_MUST_NOT_FIRE]
        + [t for t, _w in RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE]
        + [t for _c, t, _w in RF6_VI_URINARY_MUST_STILL_FIRE]
    )


def test_corpus_is_independent_of_personas_and_existing_tests():
    """語料不得抄 e2e persona 台詞，也不得與既有紅旗測試檔的語料重複。

    第三輪的教訓：情境台詞與關鍵字互相配適時，測到的是實作不是行為。
    """
    sources: list[tuple[str, str]] = []
    for path in glob.glob(_RESULTS_GLOB):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for turn in data.get("transcript") or []:
            if isinstance(turn, dict) and turn.get("role") == "patient":
                content = (turn.get("content") or "").strip()
                if content:
                    sources.append((os.path.basename(path), content))
    here = Path(__file__)
    for name in (
        "test_red_flag_over_trigger.py",
        "test_red_flag_cooccurrence.py",
        "test_red_flag_cooccurrence_coverage.py",
        "test_red_flag_gate3_bidirectional_probe.py",
        "test_red_flag_gate4_bidirectional.py",
        "test_red_flag_suppression_policy.py",
        "test_red_flag_urosepsis_fever_semantics.py",
        "test_red_flag_negation_false_friends.py",
        "test_red_flag_negation_guard_e11.py",
    ):
        sibling = here.with_name(name)
        if sibling.exists():
            sources.append((name, re.sub(r"\s+", " ", sibling.read_text("utf-8"))))
    assert sources, "找不到任何比對來源，這條結構性測試會變成空跑"

    overlaps = [
        (name, text)
        for text in _all_corpus_texts()
        for name, blob in sources
        if re.sub(r"\s+", " ", text).strip() in blob
    ]
    assert overlaps == [], f"語料與既有來源重複（＝拿實作配適測試）：{overlaps}"


def test_every_case_carries_a_human_clinical_annotation():
    """oracle 獨立性：期望值是人工臨床標註，不是偵測器輸出。"""
    annotated = (
        [(t, w) for _c, _l, t, w in RF1_RULE_HIT_MUST_SURVIVE]
        + [(t, w) for _c, _l, t, w in RF2_HISTORY_DENIAL_MUST_FIRE]
        + [(t, w) for _l, t, w in RF34_MUST_NOT_FIRE]
        + [(t, w) for _c, _l, t, w in RF34_MUST_FIRE]
        + [(t, w) for _c, _l, t, w in RF5_CROSS_CLAUSE_MUST_FIRE]
        + [(t, w) for _l, t, w in RF5_CROSS_CLAUSE_MUST_NOT_FIRE]
        + list(RF6_VI_FALSE_FRIEND_MUST_NOT_FIRE)
        + [(t, w) for _c, t, w in RF6_VI_URINARY_MUST_STILL_FIRE]
    )
    for text, why in annotated:
        assert why and len(why) >= 6, f"缺臨床標註：{text!r}"


# ══════════════════════════════════════════════════════════════
# §7 注入式回歸（把修復故意改壞，確認本檔會紅）
# ══════════════════════════════════════════════════════════════
# voice-pipeline-invariants「測試設計四點」第 4 點。沒有這一節，上面的斷言
# 可能因為別的原因剛好是綠的（假保護）。


def test_injection_rf1_post_filter_applied_to_rule_alerts_turns_red(
    detector, monkeypatch
):
    """RF-1 注入：把否定幻覺後過濾改回「套在所有 alert 上」→ §1 必須整批轉紅。"""
    original = rfd_module._canonical_denied_in_text
    regressed = []
    for cid, lang, text, _why in RF1_RULE_HIT_MUST_SURVIVE:
        # 模擬舊行為：不看 alert_type，只要 canonical 被否認就刪
        merged = detector._rule_based_detect(text, lang)
        if any(
            a["canonical_id"] == cid and original(cid, text.lower()) for a in merged
        ):
            regressed.append((cid, text))
    assert len(regressed) == len(RF1_RULE_HIT_MUST_SURVIVE), (
        "§1 的語料裡有一筆不會被舊行為刪掉 → 那一筆對 RF-1 沒有承重，請換語料。\n"
        f"  承重的只有：{[c for c, _t in regressed]}"
    )


# RF-2 注入的**逐筆預期**：關掉「新發作陳述切斷否定範圍」之後必須轉紅的語料。
# 沒有列進來的（ko 的兩筆、ja/vi 的第二筆）靠的是別的機制：
#   ko ×2  → `_CONTRAST_MARKERS` 的連接語尾 ~는데（另一條注入測試負責）
#   ja 第二筆 → 「一滴も」的位置讓最近的否定線索構不到（散文預算本來就擋住）
#   vi 第二筆 → "không mổ bao giờ" 的 cue 與關鍵字之間夾了足夠的詞
# 一筆一筆列出來，而不是寫「大部分會轉紅」——後者等於沒有斷言。
RF2_EPISODE_BREAK_LOAD_BEARING: tuple[str, ...] = (
    "我沒有糖尿病、沒有高血壓、沒有心臟病、沒有開過刀，昨晚睪丸突然劇痛痛到吐",
    "我沒有慢性病也沒有在吃藥，今天早上開始膀胱脹得受不了，一滴都解不出",
    "no diabetes, no high blood pressure, no heart disease, no surgeries, "
    "last night my testicle suddenly started hurting so much i threw up",
    "no allergies, no regular medications, this morning i am running a "
    "temperature and it stings badly every time i pee",
    "糖尿病はありません、高血圧もありません、昨夜から精巣が急に激しく痛みます",
    "tôi không bị tiểu đường, không bị cao huyết áp, tối qua tinh hoàn đau dữ dội",
)


def test_injection_rf2_removing_the_episode_break_turns_red(detector, monkeypatch):
    """RF-2 注入：把「新發作陳述切斷否定範圍」關掉 → 承重的語料必須逐筆轉紅。"""
    known = {t for _c, _l, t, _w in RF2_HISTORY_DENIAL_MUST_FIRE}
    assert set(RF2_EPISODE_BREAK_LOAD_BEARING) <= known, "承重清單與語料表漂移了"
    monkeypatch.setattr(rfd_module, "_has_time_anchor", lambda _segment: False)
    still_green = [
        text
        for cid, lang, text, _why in RF2_HISTORY_DENIAL_MUST_FIRE
        if text in RF2_EPISODE_BREAK_LOAD_BEARING and _fired(detector, cid, text, lang)
    ]
    assert still_green == [], (
        "關掉「新發作切斷」之後這些語料仍然命中 → 它們對 RF-2 這條修法沒有承重，"
        f"請從 RF2_EPISODE_BREAK_LOAD_BEARING 移除或換語料：{still_green}"
    )
    # 至少要有五語裡的四語承重，否則這條修法只是對某一語有效
    langs = {
        lg
        for _c, lg, t, _w in RF2_HISTORY_DENIAL_MUST_FIRE
        if t in RF2_EPISODE_BREAK_LOAD_BEARING
    }
    assert len(langs) >= 4, f"承重語言只有 {langs}"


def test_injection_rf2_removing_the_korean_connective_turns_red(detector, monkeypatch):
    """RF-2 注入：把 ko 的 ~는데 從轉折詞表拿掉 → ko 正例必須轉紅。"""
    patched = tuple(
        m for m in rfd_module._CONTRAST_MARKERS if m not in ("는데", "은데", "인데")
    )
    monkeypatch.setattr(rfd_module, "_CONTRAST_MARKERS", patched)
    ko_cases = [
        (cid, lang, text)
        for cid, lang, text, _w in RF2_HISTORY_DENIAL_MUST_FIRE
        if lang == "ko-KR"
    ]
    assert ko_cases
    for cid, lang, text in ko_cases:
        assert not _fired(detector, cid, text, lang), (
            f"拿掉 ~는데 之後 {text!r} 還是命中 → ko 的正例不是被這個修法保護的"
        )


# RF-3 注入的**逐筆預期**：把某個裸 trigger 加回去之後，哪幾筆反例會轉紅。
# 逐筆列出（而不是用「語料含這個字面」去推）——後者會把 RF-4 的反例算進來，
# 那些句子缺的是泌尿軸不是這個字面，加回裸 trigger 也不該讓它們紅。
RF3_INJECTION_EXPECTED: dict[str, tuple[str, ...]] = {
    "血塊": ("我腳上有一塊血塊瘀青",),
    "血の塊": ("足に血の塊ができました",),
    "혈전": ("다리에 혈전이 생겼대요",),
    "blood clots": ("i have blood clots in my leg",),
    "高燒": ("我上個月因為流感發高燒",),
    "high fever": ("i had a high fever last week from the flu",),
    "sốt cao": ("tuần trước tôi bị sốt cao vì cúm",),
    "高熱": ("去年インフルエンザで高熱が出ました",),
    "고열": ("작년에 독감으로 고열이 났었어요",),
    "意識不清": (),  # 反例語料在 MUST_FIRE 那側（意識不清＋泌尿仍要命中）
}


@pytest.mark.parametrize("canonical_id,literal", RF3_BARE_TRIGGERS_REMOVED)
def test_injection_rf3_restoring_a_bare_trigger_turns_red(
    detector, canonical_id, literal
):
    """RF-3 注入：把裸 trigger 加回去 → 對應的反例必須逐筆轉紅。"""
    expected_texts = RF3_INJECTION_EXPECTED[literal]
    if not expected_texts:
        pytest.skip(f"{literal!r} 的行為保護在 MUST_FIRE 側（無單軸誤報語料）")
    rules = [r for r in detector._rules if r["canonical_id"] == canonical_id]
    assert rules
    rule = rules[0]
    original = list(rule["keywords"])
    try:
        rule["keywords"] = original + [literal]
        regressed = tuple(
            t
            for lg, t, _w in RF34_MUST_NOT_FIRE
            if t in expected_texts and _critical_hits(detector, t, lg)
        )
        assert regressed == expected_texts, (
            f"把 {literal!r} 加回裸 trigger 之後，反例沒有轉紅 → "
            f"那些斷言不是被 RF-3 保護的。\n"
            f"  預期轉紅：{expected_texts}\n  實際：{regressed}"
        )
    finally:
        rule["keywords"] = original


# RF-4 注入的**逐筆預期**（同 RF-3：逐筆列出，不用字面推導）。
RF4_INJECTION_EXPECTED: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        HEMATURIA_HEAVY, "acuity_terms", "塊",
        ("尿路結石の塊が出ました", "我尿完之後石頭一塊一塊排出來"),
    ),
    (
        RETENTION, "acuity_terms", "できない",
        ("トイレを我慢できないくらい尿意が強いです",),
    ),
    (
        RETENTION, "site_terms", "下腹",
        ("我這兩天下腹脹得很難受，應該是吃壞肚子", "生理期下腹很脹很痛"),
    ),
    (
        UROSEPSIS, "acuity_terms", "體溫",
        ("護理師剛剛幫我量體溫，我主要是想講排尿的問題",),
    ),
    (
        UROSEPSIS, "acuity_terms", "体温",
        ("毎朝体温を記録しています、おしっこの回数が多いだけです",),
    ),
    (
        UROSEPSIS, "acuity_terms", "temperature",
        (
            "my temperature was normal, i just have some urinary frequency",
            "the nurse took my temperature at the desk, i am here about my urine flow",
        ),
    ),
    (
        UROSEPSIS, "acuity_terms", "떨리",
        ("커피 때문에 손이 떨리는데 소변 검사 받으러 왔어요",),
    ),
    (
        UROSEPSIS, "acuity_terms", "震え",
        ("緊張して手が震えます、おしっこの回数だけ気になります",),
    ),
    (
        UROSEPSIS, "acuity_terms", "shaking",
        ("my hands keep shaking from the medication and i pee often",),
    ),
)


@pytest.mark.parametrize(
    "canonical_id,key,literal,expected_texts",
    RF4_INJECTION_EXPECTED,
    ids=[lit for _c, _k, lit, _e in RF4_INJECTION_EXPECTED],
)
def test_injection_rf4_restoring_a_short_literal_turns_red(
    detector, canonical_id, key, literal, expected_texts
):
    """RF-4 注入：把短字面加回共現詞表 → 對應的反例必須逐筆轉紅。"""
    known = {t for _l, t, _w in RF34_MUST_NOT_FIRE}
    assert set(expected_texts) <= known, "承重清單與 MUST_NOT_FIRE 表漂移了"
    group = _groups(canonical_id)[0]
    original = list(group[key])
    try:
        group[key] = original + [literal]
        regressed = tuple(
            t
            for lg, t, _w in RF34_MUST_NOT_FIRE
            if t in expected_texts and _critical_hits(detector, t, lg)
        )
        assert regressed == expected_texts, (
            f"把 {literal!r} 加回 {canonical_id}.{key} 之後反例沒有轉紅。\n"
            f"  預期轉紅：{expected_texts}\n  實際：{regressed}"
        )
    finally:
        group[key] = original


# RF-5 注入的**逐筆預期**：把 `cross_clause` 從 gross_hematuria_heavy 的共現組
# 拿掉之後必須轉紅的語料。沒列進來的那一筆（vi「tôi đi tiểu, nước tiểu ra rất
# nhiều máu」）兩個軸都落在**後一個**子句裡，本來就不需要跨子句配對——列出來
# 而不是寫「大部分會轉紅」，否則等於沒有斷言。
RF5_HEMATURIA_CROSS_CLAUSE_LOAD_BEARING: tuple[str, ...] = (
    "我今天小便，然後有很多血塊",
    "小便有血，還有一坨一坨的血塊",
    "我這兩天血尿，而且有血塊",
    "剛剛上廁所小便，裡面都是血塊",
    "おしっこをしたら、血の塊がたくさん出ました",
    "尿をしましたが、血の塊が混じっていました",
    "今朝トイレに行って、血のかたまりがいくつも出ました",
    "소변을 봤는데, 피떡이 많이 나왔어요",
    "오늘 오줌을 눴어요, 그리고 핏덩어리가 나왔어요",
    "소변을 보러 갔는데, 덩어리진 피가 나왔습니다",
    "i went to pee this morning, and there were blood clots",
    "i passed some urine, then i saw a lot of blood",
    "i urinated a little while ago, and it was full of blood",
    "sáng nay tôi đi tiểu, rồi thấy nhiều máu cục",
    "tôi vừa đi tiểu xong, và có cục máu đông",
)


def test_injection_rf5_removing_cross_clause_turns_red(detector):
    """RF-5 注入：把 gross_hematuria_heavy 的 `cross_clause` 拿掉 → 逐筆轉紅。"""
    known = {t for _c, _l, t, _w in RF5_CROSS_CLAUSE_MUST_FIRE}
    assert set(RF5_HEMATURIA_CROSS_CLAUSE_LOAD_BEARING) <= known, "承重清單與語料表漂移了"
    group = _groups(HEMATURIA_HEAVY)[0]
    original = group.get("cross_clause")
    try:
        group.pop("cross_clause", None)
        still_green = [
            text
            for cid, lang, text, _why in RF5_CROSS_CLAUSE_MUST_FIRE
            if text in RF5_HEMATURIA_CROSS_CLAUSE_LOAD_BEARING
            and cid in [c for c, _kw in _critical_hits(detector, text, lang)]
        ]
    finally:
        if original is not None:
            group["cross_clause"] = original
    assert still_green == [], (
        "拿掉 cross_clause 之後這些語料仍然命中 → 它們對 RF-5 沒有承重，"
        f"請從承重清單移除或換語料：{still_green}"
    )
    langs = {
        lg
        for _c, lg, t, _w in RF5_CROSS_CLAUSE_MUST_FIRE
        if t in RF5_HEMATURIA_CROSS_CLAUSE_LOAD_BEARING
    }
    assert langs == set(LANGUAGES), f"承重語言只有 {langs}（RF-5 是五語通病）"


# 其餘三組（urosepsis / urinary_retention / cauda_equina）的 cross_clause 是
# 2026-07-27 就有的，本輪不得被順手關掉——這幾筆語料靠的就是它。
RF5_OTHER_GROUPS_CROSS_CLAUSE_LOAD_BEARING: tuple[str, ...] = (
    "我從昨天就開始發高燒，然後小便的時候會刺痛",
    "高熱が出ています、それから排尿のときに痛みます",
    "고열이 있고요, 배뇨할 때 통증이 있습니다",
    "tôi bị sốt cao, rồi tiểu rất buốt",
    "i have had a high fever since yesterday, and it burns when i pass water",
    "我今天有點意識不清，而且小便很混濁",
    "我量體溫三十九度，然後小便的時候很痛",
)


def test_injection_rf5_removing_cross_clause_from_the_other_groups_turns_red(detector):
    """注入：把既有三組的 `cross_clause` 一併關掉 → 被移除字面的跨子句形轉紅。

    RF-3 的無漏報論證（「高燒/高熱/고열/high fever/sốt cao/意識不清 都在
    acuity_terms 裡，只是多要求同一或**相鄰**子句有泌尿詞」）整個掛在
    `cross_clause` 上。這條注入把那個依賴變成可觀測的。
    """
    known = {t for _c, _l, t, _w in RF5_CROSS_CLAUSE_MUST_FIRE}
    assert set(RF5_OTHER_GROUPS_CROSS_CLAUSE_LOAD_BEARING) <= known, "承重清單漂移了"
    touched: list[dict[str, Any]] = []
    try:
        for canonical_id in (UROSEPSIS, RETENTION, CAUDA):
            for group in _groups(canonical_id):
                if group.pop("cross_clause", None) is not None:
                    touched.append(group)
        still_green = [
            text
            for cid, lang, text, _why in RF5_CROSS_CLAUSE_MUST_FIRE
            if text in RF5_OTHER_GROUPS_CROSS_CLAUSE_LOAD_BEARING
            and cid in [c for c, _kw in _critical_hits(detector, text, lang)]
        ]
    finally:
        for group in touched:
            group["cross_clause"] = True
    assert still_green == [], (
        f"這些語料不是被既有 cross_clause 保護的，承重清單要更新：{still_green}"
    )


def test_injection_rf5_removing_pass_water_turns_red(detector):
    """RF-5 注入：把 `pass water` 從 urosepsis 的 site_terms 拿掉 → 該句轉紅。

    這一條在意的不是字面本身，而是 RF-3 的舉證方法：當時只用一句英文
    （"…every time i pass urine"）就宣告「英文由 acuity 的 fever 涵蓋」，
    於是英式最常用的泌尿詞整個沒被量到，移除裸 `high fever` 之後那句零紅旗。
    """
    text = "i have had a high fever since yesterday, and it burns when i pass water"
    assert (text, "en-US") in {
        (t, lg) for _c, lg, t, _w in RF5_CROSS_CLAUSE_MUST_FIRE
    }, "語料表漂移了"
    group = _groups(UROSEPSIS)[0]
    original = list(group["site_terms"])
    try:
        group["site_terms"] = [
            t for t in original if not t.startswith(("pass water", "passing water",
                                                     "passed water"))
        ]
        assert UROSEPSIS not in [
            c for c, _kw in _critical_hits(detector, text, "en-US")
        ], "拿掉 pass water 之後仍命中 → 這筆語料不是被它保護的"
    finally:
        group["site_terms"] = original


def test_injection_d6_regex_bypassing_the_guard_turns_red(monkeypatch):
    """D-6 注入：讓 regex 路徑回到「不過守衛」→ §4 的斷言必須轉紅。"""
    rule = _FakeRule(
        "大量血尿", canonical_id=HEMATURIA_HEAVY, keywords=[], regex_pattern=r"血塊"
    )
    det = _make_detector(monkeypatch, [rule])
    # 模擬舊行為：直接 re.search，不過 `_occurrence_negated`
    assert re.search(r"血塊", "我完全沒有血塊", re.IGNORECASE), (
        "舊行為的 regex 對這句是命中的 → 現行為必須靠守衛擋下（§4 的承重點）"
    )
    assert det._rule_based_detect("我完全沒有血塊", "zh-TW") == []


def test_injection_d7_unnormalized_identity_turns_red():
    """D-7 注入：把正規化拿掉（＝直接 str）→ 身份必須分裂成四個。"""
    naive = {str(s) for s in _SAME_FLAG_DIFFERENT_SPELLINGS}
    assert len(naive) == 4, "語料本身沒有涵蓋大小寫/空白差異 → D-7 的斷言沒有承重"
    normalized = {normalize_canonical_id(s) for s in _SAME_FLAG_DIFFERENT_SPELLINGS}
    assert len(normalized) == 1


# ══════════════════════════════════════════════════════════════
# §8 政策不變式：本輪不得動到既有的「刻意接受的誤報」
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "canonical_id,language,text,why",
    [
        (RETENTION, "zh-TW", "我室友前天尿不出來去掛急診",
         "第三人稱轉述——2026-07-27 拍板刻意保留的誤報"),
        (UROSEPSIS, "en-US", "my brother ran a fever and had a urine infection in june",
         "第三人稱轉述——同上"),
    ],
    ids=["third-person-zh", "third-person-en"],
)
def test_accepted_over_triggers_are_not_silently_narrowed(
    detector, canonical_id, language, text, why
):
    """本輪只收窄**臨床拍板過**的字面，不得順手把政策接受的誤報也擋掉。

    若本測試變紅，代表有人加了新的抑制邏輯——請先證明它不會造成漏報。
    """
    assert _fired(detector, canonical_id, text, language), (
        f"政策接受的誤報被擋掉了（{why}）：{language} {text!r}"
    )
