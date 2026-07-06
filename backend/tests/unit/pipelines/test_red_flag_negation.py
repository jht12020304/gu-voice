"""
規則層否定感知比對測試（修「沒有血尿」誤觸紅旗）。

安全不變式：只抑制「每個出現都被否定」的關鍵字；有任一非否定出現仍觸發（fail-open）。
轉折詞（但/可是）與句尾標點會重置否定範圍。
"""

from app.pipelines.red_flag_detector import _keyword_present_non_negated as present


class TestZhNegation:
    def test_negated_keyword_suppressed(self):
        """「沒有血尿」→ 血尿 全為否定 → 不觸發。"""
        assert present("血尿", "我沒有血尿") is False

    def test_plain_mention_fires(self):
        """「有血尿」→ 觸發。"""
        assert present("血尿", "我這兩天有血尿") is True

    def test_contrast_marker_resets_negation(self):
        """「沒有發燒但有血尿」→ 轉折後的血尿為非否定 → 觸發。"""
        assert present("血尿", "沒有發燒但有血尿") is True

    def test_contrast_marker_keeps_negated_side(self):
        """同句「沒有發燒但有血尿」→ 發燒仍被否定 → 不觸發。"""
        assert present("發燒", "沒有發燒但有血尿") is False

    def test_negated_list_all_suppressed(self):
        """「沒有血尿、發燒、腰痛」→ list 分隔不切斷否定 → 三者皆抑制。"""
        text = "我沒有血尿、發燒、腰痛"
        assert present("血尿", text) is False
        assert present("發燒", text) is False
        assert present("腰痛", text) is False

    def test_one_non_negated_occurrence_fires(self):
        """一處否定、一處肯定 → 有非否定出現 → 觸發。"""
        assert present("血尿", "上週有血尿，這週沒有血尿") is True

    def test_sentence_break_isolates_negation(self):
        """句尾標點切斷否定範圍：「沒有發燒。血尿很嚴重」→ 血尿觸發。"""
        assert present("血尿", "沒有發燒。血尿很嚴重") is True

    def test_various_negation_cues(self):
        for neg in ("沒有血尿", "無血尿", "未見血尿", "否認血尿", "並無血尿"):
            assert present("血尿", neg) is False, neg

    def test_long_negated_list_suppressed(self):
        """長列舉否定句（單一「沒有」+ list 分隔）→ 列舉內關鍵字皆抑制（涵蓋 45 字內）。"""
        text = "我沒有血尿、發燒、腰痛、尿急、尿痛、畏寒、噁心"
        assert present("血尿", text) is False
        assert present("發燒", text) is False
        assert present("腰痛", text) is False

    def test_continuation_marker_resets_negation(self):
        """接續詞「然後」後語義重置：「沒有發燒然後開始血尿」→ 血尿觸發（避免跨子句誤抑制）。"""
        assert present("血尿", "沒有發燒然後開始血尿") is True

    def test_very_long_negated_list_suppressed(self):
        """極長單一否定列舉（對抗性電池的 P2 原句）→ 末端「尿滯留」仍被同一「沒有」抑制。"""
        text = (
            "我把我知道的都排除一下好了：沒有血尿、發燒、畏寒、噁心、嘔吐、食慾不振、"
            "體重減輕、排尿疼痛、腰部痠痛、下腹悶脹、頻尿急尿、尿滯留、完全排不出的情形，"
            "就是最近比較常跑廁所而已"
        )
        assert present("血尿", text) is False
        assert present("尿滯留", text) is False

    def test_additive_clause_marker_resets(self):
        """追加子句「而且」後重置：「沒有發燒而且有血尿」→ 血尿觸發。"""
        assert present("血尿", "沒有發燒而且有血尿") is True

    def test_list_connector_does_not_reset(self):
        """list 連接詞「以及/還有」不重置：「沒有血尿以及腰痛」→ 兩者皆抑制。"""
        assert present("血尿", "沒有血尿以及腰痛") is False
        assert present("腰痛", "沒有血尿以及腰痛") is False


class TestEnNegation:
    def test_no_hematuria_suppressed(self):
        assert present("hematuria", "no hematuria noted") is False

    def test_denies_suppressed(self):
        assert present("hematuria", "patient denies hematuria") is False

    def test_present_fires(self):
        assert present("hematuria", "gross hematuria present") is True

    def test_without_suppressed(self):
        assert present("fever", "without fever") is False


class TestViNegation:
    def test_khong_co_suppressed(self):
        assert present("tiểu ra máu", "không có tiểu ra máu") is False

    def test_plain_fires(self):
        assert present("tiểu ra máu", "tôi bị tiểu ra máu") is True


class TestSafetyFailOpen:
    def test_ambiguous_defaults_to_fire(self):
        """不確定/無否定線索 → 觸發（fail-open，寧可誤報不漏急症）。"""
        assert present("血尿", "醫生我想問血尿的事") is True

    def test_missing_keyword_returns_false(self):
        assert present("血尿", "我頭痛") is False
