"""2026-07-27 病患端真跑（fix/e2e-flow-gaps）找到的三個紅旗缺陷的回歸測試。

守護的不變式：

1. **規則層必須接得住教科書級睪丸扭轉描述**（HIGH）。
   真跑 `torsion_critical_zh` 時病患第一句就是典型描述「大約兩小時前左邊睪丸突然
   劇烈疼痛，陰囊腫起來，痛到想吐，走路都有困難」，規則層卻 0 命中（DB alert
   落成 confidence=semantic_only、trigger_keywords 空）→ 6 小時黃金窗的 critical
   全靠 LLM 語意層獨撐，沒有 fallback（違反不變式 #9）。

2. **語意層必須看得到對話歷史**（MEDIUM）。
   `session_context["conversation_summary"]` 過去是死 key（從沒人寫）；現在由
   conversation_handler 寫入。消費端要能：真的餵進 prompt、拿到 None 不炸、
   過長要截斷（截頭保尾）。跨輪累積型 critical（前輪發燒＋本輪腰痛＝urosepsis）
   只有這條路偵得到。

3. **重複紅旗的抑制**：跨輪去重的 Redis TTL 要覆蓋合理問診時長；同一臨床實體的
   父子紅旗（大量血尿 critical ⊃ 肉眼血尿 high）要折疊成一筆。

⚠️ 本檔的斷言幾乎全是「這句話**必須**命中」的方向。2026-07-27 的對抗式覆核證明
只有這個方向是不夠的——為了讓這裡變綠而補的裸關鍵字，讓「my eyeball hurts a lot」
「我想問睪丸痛要看哪一科」都變成 critical、直接中止問診。
**反方向的防線在 `test_red_flag_over_trigger.py`，動這裡的關鍵字前必須一起看。**
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.alert_dedup import _EMITTED_TTL, record_emitted_alert
from app.pipelines.prompts.shared import RED_FLAG_SUPERSEDES, URO_RED_FLAGS
from app.pipelines.red_flag_detector import (
    _MAX_CONVERSATION_SUMMARY_CHARS,
    RedFlagDetector,
    _format_conversation_summary,
)


def _run(coro):
    return asyncio.run(coro)


# ── detector 腳手架（空表 → fallback 內建 catalogue）───────────────


class _FakeScalars:
    def all(self) -> list[Any]:
        return []


class _FakeResult:
    def scalars(self) -> _FakeScalars:
        return _FakeScalars()


class _FakeDB:
    async def execute(self, _stmt) -> _FakeResult:
        return _FakeResult()


def _make_detector(monkeypatch: pytest.MonkeyPatch) -> RedFlagDetector:
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
    settings.RED_FLAG_NEGATION_GUARD = True
    detector = RedFlagDetector(settings, _FakeDB())
    _run(detector._load_rules())
    return detector


def _canonicals(detector: RedFlagDetector, text: str, language: str) -> set[str]:
    return {a["canonical_id"] for a in detector._rule_based_detect(text, language)}


# ══════════════════════════════════════════════════════════════
# 1. 睪丸扭轉：規則層 fallback
# ══════════════════════════════════════════════════════════════

# 真跑 scripts/e2e_realopenai/results/torsion_critical_zh.json 的病患第 1 輪逐字稿。
E2E_TORSION_FIRST_TURN = (
    "大約兩小時前左邊睪丸突然劇烈疼痛，陰囊腫起來，痛到想吐，走路都有困難。"
)


class TestTorsionRuleLayerCoverage:
    def test_e2e_transcript_hits_rule_layer(self, monkeypatch):
        """真跑逐字稿原句 → 規則層必須命中（原本 0 命中，只有語意層擋著）。"""
        detector = _make_detector(monkeypatch)
        alerts = detector._rule_based_detect(E2E_TORSION_FIRST_TURN, "zh-TW")
        ids = {a["canonical_id"] for a in alerts}
        assert "testicular_pain_severe" in ids, (
            f"規則層漏掉教科書級睪丸扭轉描述：{E2E_TORSION_FIRST_TURN!r}，實得 {sorted(ids)}"
        )

    def test_e2e_transcript_alert_carries_trigger_keywords(self, monkeypatch):
        """規則層命中要把命中詞原文帶出來（DB trigger_keywords 原本永遠 NULL）。"""
        detector = _make_detector(monkeypatch)
        alert = next(
            a
            for a in detector._rule_based_detect(E2E_TORSION_FIRST_TURN, "zh-TW")
            if a["canonical_id"] == "testicular_pain_severe"
        )
        assert alert["trigger_keywords"], "trigger_keywords 不可為空"
        assert all(kw in E2E_TORSION_FIRST_TURN for kw in alert["trigger_keywords"])
        # trigger_reason 仍是在地化字串（既有行為不變）
        assert alert["trigger_reason"]

    @pytest.mark.parametrize(
        "language,text",
        [
            # 五語言的「教科書級扭轉」口語描述（病患真的會這樣講）
            ("zh-TW", "兩個小時前左邊睪丸突然很痛，痛到想吐"),
            ("zh-TW", "我蛋蛋突然痛起來，腫得很大"),
            ("zh-TW", "陰囊突然腫起來而且痛到走不動"),
            ("zh-TW", "醫生說可能是睪丸扭轉"),
            ("en-US", "two hours ago my left testicle suddenly started to hurt badly"),
            ("en-US", "my balls hurt so much I want to vomit"),
            ("en-US", "sudden severe scrotal pain and swollen testicle"),
            ("ja-JP", "二時間前に急に睾丸が痛くなりました"),
            ("ja-JP", "左の精巣の痛みがひどくて歩けません"),
            ("ja-JP", "陰嚢が腫れて痛みがひどいです"),
            ("ko-KR", "두 시간 전에 갑자기 고환이 아파요"),
            ("ko-KR", "음낭이 부어오르고 고환 통증이 심해요"),
            ("vi-VN", "hai tiếng trước tinh hoàn bên trái đau dữ dội"),
            ("vi-VN", "bìu sưng đau và tôi buồn nôn"),
        ],
    )
    def test_five_language_torsion_descriptions_fire(self, monkeypatch, language, text):
        detector = _make_detector(monkeypatch)
        ids = _canonicals(detector, text, language)
        assert "testicular_pain_severe" in ids, (
            f"{language} 扭轉描述漏報：{text!r}，實得 {sorted(ids)}"
        )

    def test_torsion_triggers_cover_all_five_languages(self):
        """5 語 triggers 都不得為空（缺語言＝該語言規則層 fallback 失效）。"""
        flag = next(
            f for f in URO_RED_FLAGS if f["canonical_id"] == "testicular_pain_severe"
        )
        for lang in ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"):
            assert flag["triggers_by_lang"].get(lang), lang


class TestTorsionNegationStillGuarded:
    """新關鍵字不得把否定守衛換掉——直接否認仍必須抑制（E11 的誤 abort 不可回來）。

    ⚠️ 每一筆的症狀詞都必須是**現存的** trigger，否則測試會在關鍵字被移除後
    變成永遠 trivially pass 的空殼（2026-07-27 收緊關鍵字時就踩過：原本用
    「睪丸痛 / testicular pain / 고환 통증 / đau tinh hoàn」，那四個字串同時是
    主訴選單標籤、已移出 catalogue）。
    """

    @pytest.mark.parametrize(
        "language,text",
        [
            ("zh-TW", "我沒有睪丸很痛的情形"),
            ("zh-TW", "沒有睪丸劇痛也沒有陰囊腫脹"),
            ("en-US", "denies testicle pain"),
            ("en-US", "no severe scrotal pain"),
            ("ja-JP", "睾丸の痛みはありません"),
            ("ko-KR", "고환이 아파요는 없어요"),
            ("vi-VN", "không có tinh hoàn đau"),
        ],
    )
    def test_plain_denial_still_suppressed(self, monkeypatch, language, text):
        detector = _make_detector(monkeypatch)
        ids = _canonicals(detector, text, language)
        assert "testicular_pain_severe" not in ids, f"{text!r} 不該命中，實得 {sorted(ids)}"

    def test_denial_then_contrast_still_fires(self, monkeypatch):
        """否認 A、轉折、真的有 B → B 必須命中（規則層是語意層的 fallback）。"""
        detector = _make_detector(monkeypatch)
        ids = _canonicals(detector, "我沒有發燒，但是睪丸很痛", "zh-TW")
        assert "testicular_pain_severe" in ids


# ══════════════════════════════════════════════════════════════
# 2. 語意層看得到對話歷史
# ══════════════════════════════════════════════════════════════


def _stub_llm(monkeypatch, detector, alerts_for):
    """把 OpenAI 換成本地假 LLM。

    alerts_for: (user_message) -> list[alert dict]；同時回傳 captured 供斷言 prompt。
    """
    captured: dict[str, Any] = {}

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        user_message = kwargs["messages"][1]["content"]
        captured["user_message"] = user_message
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = json.dumps(
            {"alerts": alerts_for(user_message)}, ensure_ascii=False
        )
        return response

    monkeypatch.setattr(rfd_module, "call_with_retry", fake_call_with_retry)
    detector._client.chat.completions.create = AsyncMock(side_effect=fake_create)
    return captured


class TestConversationSummaryNormalization:
    def test_none_and_blank_yield_empty(self):
        assert _format_conversation_summary(None) == ""
        assert _format_conversation_summary("") == ""
        assert _format_conversation_summary("   \n ") == ""

    def test_non_string_is_coerced_not_raised(self):
        """上游若改寫成 list[dict]，紅旗偵測不可炸（炸掉＝整輪漏報）。"""
        out = _format_conversation_summary([{"role": "patient", "content": "發燒"}])
        assert "發燒" in out

    def test_overlong_summary_is_truncated_keeping_tail(self):
        head = "病患：很久以前的閒聊。\n" * 500
        tail = "病患：昨天開始發高燒。\nAI：了解。"
        out = _format_conversation_summary(head + tail)
        assert len(out) <= _MAX_CONVERSATION_SUMMARY_CHARS + 40
        assert out.endswith(tail), "截斷必須截頭保尾（最新幾輪資訊價值最高）"
        assert out.startswith("…"), "頭部截斷處要留省略記號讓 LLM 知道前面還有內容"


class TestSemanticLayerSeesHistory:
    def test_summary_reaches_prompt(self, monkeypatch):
        detector = _make_detector(monkeypatch)
        captured = _stub_llm(monkeypatch, detector, lambda _msg: [])
        _run(
            detector._semantic_detect(
                text="今天右邊腰很痛",
                session_context={
                    "session_id": "s1",
                    "chief_complaint": "腰痛",
                    "conversation_summary": "病患：前天開始發燒到 39 度\nAI：了解，還有其他症狀嗎？",
                },
                language="zh-TW",
            )
        )
        assert "發燒到 39 度" in captured["user_message"]
        assert "今天右邊腰很痛" in captured["user_message"]

    def test_missing_summary_does_not_crash_and_adds_no_section(self, monkeypatch):
        detector = _make_detector(monkeypatch)
        captured = _stub_llm(monkeypatch, detector, lambda _msg: [])
        alerts = _run(
            detector._semantic_detect(
                text="今天右邊腰很痛",
                session_context={"session_id": "s1", "chief_complaint": "腰痛"},
                language="zh-TW",
            )
        )
        assert alerts == []
        assert "先前對話（依時間排序）" not in captured["user_message"]

    def test_none_summary_does_not_crash(self, monkeypatch):
        detector = _make_detector(monkeypatch)
        captured = _stub_llm(monkeypatch, detector, lambda _msg: [])
        _run(
            detector._semantic_detect(
                text="今天右邊腰很痛",
                session_context={
                    "session_id": "s1",
                    "conversation_summary": None,
                },
                language="zh-TW",
            )
        )
        assert "先前對話（依時間排序）" not in captured["user_message"]

    def test_overlong_summary_truncated_in_prompt(self, monkeypatch):
        detector = _make_detector(monkeypatch)
        captured = _stub_llm(monkeypatch, detector, lambda _msg: [])
        summary = "病患：閒聊內容。\n" * 2000 + "病患：昨天開始發高燒。"
        _run(
            detector._semantic_detect(
                text="今天右邊腰很痛",
                session_context={
                    "session_id": "s1",
                    "conversation_summary": summary,
                },
                language="zh-TW",
            )
        )
        user_message = captured["user_message"]
        assert len(user_message) < len(summary)
        assert "昨天開始發高燒" in user_message


class TestCrossTurnAccumulatedCritical:
    """跨輪累積：前輪發燒 ＋ 本輪腰痛 = urosepsis(critical)。

    規則層只看本輪（兩者分開都不是 critical），所以這條路只有語意層走得通，
    而語意層必須看得到 conversation_summary 才判得出來——正是死 key 的代價。
    """

    CURRENT_TURN = "這兩天右邊腰很痛，痛到站不直"
    HISTORY = "病患：前天開始發燒到 39 度，一直冒冷汗\nAI：了解，還有其他不舒服嗎？"

    @staticmethod
    def _alerts_for(user_message: str) -> list[dict[str, Any]]:
        """假 LLM 的臨床規則：同時看到前輪的發燒與本輪的腰痛才判 urosepsis。

        刻意用只在歷史/本輪出現的字串當標記（「39 度」「站不直」），避免 prompt
        模板自身的字眼讓對照組假陽性。
        """
        if "39 度" in user_message and "站不直" in user_message:
            return [
                {
                    "severity": "critical",
                    "title": "尿路敗血症",
                    "description": "發燒合併腰痛，疑似尿路感染上行造成敗血症",
                    "trigger_reason": "病患前天開始發燒到 39 度，今天出現腰痛",
                    "suggested_actions": ["立即通知醫師"],
                }
            ]
        return []

    def test_cross_turn_urosepsis_detected_with_history(self, monkeypatch):
        detector = _make_detector(monkeypatch)
        _stub_llm(monkeypatch, detector, self._alerts_for)
        merged = _run(
            detector.detect(
                self.CURRENT_TURN,
                {
                    "session_id": "s1",
                    "language": "zh-TW",
                    "chief_complaint": "腰痛",
                    "conversation_summary": self.HISTORY,
                },
            )
        )
        by_id = {a["canonical_id"]: a for a in merged}
        assert "urosepsis" in by_id, f"跨輪累積 critical 漏報，實得 {sorted(by_id)}"
        assert by_id["urosepsis"]["severity"] == "critical"

    def test_without_history_same_turn_is_not_critical(self, monkeypatch):
        """對照組：沒有歷史 → 同一句話判不出 urosepsis（證明上面那筆真的來自歷史）。"""
        detector = _make_detector(monkeypatch)
        _stub_llm(monkeypatch, detector, self._alerts_for)
        merged = _run(
            detector.detect(
                self.CURRENT_TURN,
                {"session_id": "s1", "language": "zh-TW", "chief_complaint": "腰痛"},
            )
        )
        assert "urosepsis" not in {a["canonical_id"] for a in merged}

    def test_semantic_alert_carries_llm_analysis(self, monkeypatch):
        """語意層要把 LLM 原始判斷留在 llm_analysis（DB 該欄原本永遠 NULL）。"""
        detector = _make_detector(monkeypatch)
        _stub_llm(monkeypatch, detector, self._alerts_for)
        merged = _run(
            detector.detect(
                self.CURRENT_TURN,
                {
                    "session_id": "s1",
                    "language": "zh-TW",
                    "conversation_summary": self.HISTORY,
                },
            )
        )
        alert = next(a for a in merged if a["canonical_id"] == "urosepsis")
        assert alert["llm_analysis"]["raw_title"] == "尿路敗血症"
        assert alert["llm_analysis"]["raw_severity"] == "critical"
        assert alert["llm_analysis"]["matched_catalogue"] is True


class TestMergeCarriesLayerSpecificFields:
    """`_merge_and_deduplicate` 的欄位搬運（2026-07-27 真跑 DB 實測 llm_analysis=NULL）。

    語意層產出的 `llm_analysis` 只存在於**語意層**那筆 alert；merge 時規則層那筆
    先進 dict，若不把 llm_analysis 搬過去，`alert_type=combined` 的 alert 落庫就
    永遠是 NULL。而規則層關鍵字收得越好，combined 就從例外變成常態——換句話說，
    紅旗偵測越準，這個欄位反而越沒機會被寫進去。
    """

    RULE_ALERT = {
        "canonical_id": "testicular_pain_severe",
        "severity": "critical",
        "title": "睪丸劇痛",
        "description": "目錄描述",
        "trigger_reason": "關鍵字比對：「睪丸突然」",
        "trigger_keywords": ["睪丸突然"],
        "llm_analysis": None,
        "alert_type": "rule_based",
        "confidence": "rule_hit",
        "suggested_actions": ["立即通知泌尿科醫師"],
        "matched_rule_id": None,
    }
    SEMANTIC_ALERT = {
        "canonical_id": "testicular_pain_severe",
        "severity": "critical",
        "title": "睪丸劇痛",
        "description": "語意層描述",
        "trigger_reason": "病患自述兩小時前突然劇痛",
        "trigger_keywords": None,
        "llm_analysis": {
            "model": "gpt-4o-mini",
            "raw_title": "睪丸扭轉可能",
            "raw_severity": "high",
            "matched_catalogue": True,
            "description": "語意層描述",
        },
        "alert_type": "semantic",
        "confidence": "semantic_only",
        "suggested_actions": ["安排緊急超音波"],
        "matched_rule_id": None,
    }

    def _merge(self):
        return RedFlagDetector._merge_and_deduplicate(
            [dict(self.RULE_ALERT)], [dict(self.SEMANTIC_ALERT)], "zh-TW"
        )

    def test_combined_keeps_llm_analysis(self):
        merged = self._merge()
        assert len(merged) == 1
        alert = merged[0]
        assert alert["alert_type"] == "combined"
        assert alert["llm_analysis"] is not None, (
            "combined 路徑掉了 llm_analysis → red_flag_alerts.llm_analysis 永遠 NULL"
        )
        assert alert["llm_analysis"]["raw_severity"] == "high", (
            "要保留 severity floor **之前**的 LLM 原始自評，事後誤報覆核才有依據"
        )

    def test_combined_keeps_rule_trigger_keywords(self):
        """反方向：規則層才有的 trigger_keywords 不得被語意層的 None 蓋掉。"""
        alert = self._merge()[0]
        assert alert["trigger_keywords"] == ["睪丸突然"]

    def test_two_semantic_alerts_do_not_fake_a_rule_hit(self):
        """語意層自己回兩筆同 canonical → 不得謊報成 combined/rule_hit（信心灌水）。"""
        second = dict(self.SEMANTIC_ALERT)
        second["trigger_reason"] = "另一種說法"
        merged = RedFlagDetector._merge_and_deduplicate(
            [], [dict(self.SEMANTIC_ALERT), second], "zh-TW"
        )
        assert len(merged) == 1
        assert merged[0]["alert_type"] == "semantic"
        assert merged[0]["confidence"] == "semantic_only"


# ══════════════════════════════════════════════════════════════
# 3. 重複紅旗抑制（父子折疊 + 去重 TTL）
# ══════════════════════════════════════════════════════════════


class TestParentChildCollapse:
    def test_heavy_hematuria_suppresses_base_hematuria(self, monkeypatch):
        """「大量血尿」同時命中 critical/high 雙胞胎 → 只留 critical 那筆。"""
        detector = _make_detector(monkeypatch)
        _stub_llm(monkeypatch, detector, lambda _msg: [])
        merged = _run(
            detector.detect(
                "這兩天大量血尿，還有血塊",
                {"session_id": "s1", "language": "zh-TW"},
            )
        )
        ids = [a["canonical_id"] for a in merged]
        assert "gross_hematuria_heavy" in ids
        assert "gross_hematuria" not in ids, f"父子紅旗未折疊：{ids}"

    def test_child_alone_still_fires(self, monkeypatch):
        """父不在場 → 子仍是獨立紅旗（折疊不可製造漏報）。"""
        detector = _make_detector(monkeypatch)
        _stub_llm(monkeypatch, detector, lambda _msg: [])
        merged = _run(
            detector.detect("我這兩天有血尿", {"session_id": "s1", "language": "zh-TW"})
        )
        assert "gross_hematuria" in {a["canonical_id"] for a in merged}

    def test_collapse_merges_child_suggested_actions_into_parent(self):
        alerts = [
            {
                "canonical_id": "gross_hematuria_heavy",
                "severity": "critical",
                "suggested_actions": ["立即通知醫師"],
            },
            {
                "canonical_id": "gross_hematuria",
                "severity": "high",
                "suggested_actions": ["安排尿液檢查"],
            },
        ]
        kept = RedFlagDetector._collapse_superseded(alerts)
        assert len(kept) == 1
        assert kept[0]["canonical_id"] == "gross_hematuria_heavy"
        assert "安排尿液檢查" in kept[0]["suggested_actions"], "子紅旗的處置建議不可掉字"

    def test_supersedes_map_only_contains_known_canonical_ids(self):
        known = {f["canonical_id"] for f in URO_RED_FLAGS}
        severity = {f["canonical_id"]: f["severity"] for f in URO_RED_FLAGS}
        rank = {"medium": 1, "high": 2, "critical": 3}
        for parent, children in RED_FLAG_SUPERSEDES.items():
            assert parent in known, parent
            for child in children:
                assert child in known, child
                # 父嚴重度不得低於子——否則折疊會把高嚴重度的那筆吃掉
                assert rank[severity[parent]] >= rank[severity[child]]


class TestDedupTTL:
    class _FakeRedis:
        def __init__(self) -> None:
            self.hashes: dict[str, dict[str, str]] = {}
            self.expires: dict[str, int] = {}

        async def hset(self, key: str, field: str, value: str) -> None:
            self.hashes.setdefault(key, {})[field] = value

        async def expire(self, key: str, ttl: int) -> bool:
            self.expires[key] = ttl
            return True

    def test_ttl_covers_a_paused_kiosk_session(self):
        """1 小時太短：場次被暫停超過 TTL → 同一紅旗重複寫進 DB、灌水 analytics。"""
        assert _EMITTED_TTL >= 6 * 3600

    def test_record_applies_the_ttl(self):
        redis = self._FakeRedis()
        _run(
            record_emitted_alert(
                redis,
                "sess-1",
                {"canonical_id": "urosepsis", "severity": "critical"},
            )
        )
        assert list(redis.expires.values()) == [_EMITTED_TTL]
