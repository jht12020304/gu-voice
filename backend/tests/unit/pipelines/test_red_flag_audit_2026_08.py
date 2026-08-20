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
    "整個都是血 / 一大堆血（gross_hematuria_heavy.triggers）": (
        "同樣沒有泌尿軸（『我手上整個都是血』會誤報），但不在本輪拍板清單內。"
        "兩者都在共現組 acuity（都是血／一大堆血）裡，若日後拍板可比照 RF-3 移除。"
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
