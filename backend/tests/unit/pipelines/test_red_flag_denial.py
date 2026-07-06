"""
否定幻覺後過濾測試（涵蓋語意層；A1 規則層修復的延伸）。

`_canonical_denied_in_text`：canonical 關鍵字在文中「出現但全被否定」→ True（抑制）。
安全不變式：
- 有非否定出現（症狀被肯定）→ False（不抑制）。
- 關鍵字根本不在文中（語意層純情境推論，如描述睪丸扭轉未說關鍵字）→ False（不抑制）。
"""

from app.pipelines.red_flag_detector import _canonical_denied_in_text as denied


class TestDeniedSuppression:
    def test_zh_denied_suppressed(self):
        assert denied("gross_hematuria", "沒有血尿") is True

    def test_zh_affirmed_not_suppressed(self):
        assert denied("gross_hematuria", "我這兩天有血尿") is False

    def test_ja_post_negation_denied_suppressed(self):
        assert denied("gross_hematuria", "血尿はありません") is True

    def test_en_denied_suppressed(self):
        assert denied("gross_hematuria", "patient denies hematuria, no blood in urine") is True

    def test_en_affirmed_not_suppressed(self):
        assert denied("gross_hematuria", "gross hematuria present for 3 days") is False

    def test_negated_list_denied_suppressed(self):
        assert denied("gross_hematuria", "我沒有血尿、發燒、腰痛") is True


class TestSemanticInferenceKept:
    def test_keyword_absent_not_suppressed(self):
        """語意層從情境推論睪丸扭轉但病患未說出關鍵字 → 關鍵字不在文中 → 不抑制。"""
        assert denied("testicular_pain_severe", "左邊那顆突然很不舒服、腫起來走不動") is False

    def test_mixed_affirmed_and_negated_not_suppressed(self):
        """一處否定一處肯定 → 有非否定出現 → 不抑制（fail-open）。"""
        assert denied("gross_hematuria", "上週有血尿，這週沒有血尿") is False


class TestUnknownCanonical:
    def test_unknown_canonical_not_suppressed(self):
        assert denied("some_llm_invented_flag", "沒有血尿") is False
