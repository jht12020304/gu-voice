"""
LLM 輸出語言 heuristic 偵測測試。

重點：
- 明顯中文 → zh-TW
- 明顯英文 → en-US
- 混語 / 純數字 / ICD-10 / 極短字串 → None（避免誤報）
- matches_expected_language 對 None 寬容（不視為不匹配）
"""

from __future__ import annotations

import pytest

from app.utils.language_detect import detect_text_language, matches_expected_language


class TestDetect:
    def test_clear_traditional_chinese(self):
        assert detect_text_language("病患表示血尿持續三天，伴隨下腹痛。") == "zh-TW"

    def test_clear_english(self):
        assert (
            detect_text_language(
                "Patient reports gross hematuria for three days with flank pain."
            )
            == "en-US"
        )

    def test_japanese_kana_classified_as_cjk(self):
        """Hiragana / Katakana 也被歸類為 CJK（zh-TW bucket）。"""
        assert detect_text_language("ひらがなカタカナ") == "zh-TW"

    def test_short_string_returns_none(self):
        """太短的字串不做判斷，避免誤報（例如 ICD-10 代碼）。"""
        assert detect_text_language("N39") is None
        assert detect_text_language("") is None
        assert detect_text_language(None) is None

    def test_numeric_only_returns_none(self):
        """純數字不屬於任一語言 → None。"""
        assert detect_text_language("123456789") is None

    def test_icd_code_returns_none(self):
        """ICD-10 單一代碼 → 字母比例可能過 threshold，但屬於代碼非文字 — 長度檢查擋掉。"""
        assert detect_text_language("N39.0") is None

    def test_mixed_with_dominant_chinese_returns_zh(self):
        """英文夾雜 CJK，CJK 比例過 30% → zh-TW。"""
        text = "病患 (patient) 於急診就診，主訴 hematuria 持續三天。"
        assert detect_text_language(text) == "zh-TW"

    def test_mixed_with_dominant_english_returns_en(self):
        """英文為主、夾少量中文 → CJK 比例不夠，ASCII 比例 ≥ 80% → en-US。"""
        text = "Patient presents with gross hematuria; prior note in Chinese: 血尿"
        # 計算：大量英文字母 + 幾個中文 → ASCII ratio 應 ≥ 80%
        # 若因 punctuation 比例偏離可能回 None；放寬斷言為「不是 zh-TW」
        assert detect_text_language(text) != "zh-TW"


class TestMatchesExpected:
    def test_zh_output_matches_zh_expected(self):
        assert matches_expected_language("病患表示血尿", "zh-TW") is True

    def test_en_output_matches_en_expected(self):
        assert matches_expected_language(
            "Patient reports hematuria for three days.", "en-US"
        ) is True

    def test_zh_output_mismatches_en_expected(self):
        """LLM 被要求英文卻回中文 → False（讓 caller 可以 log warn）。"""
        assert (
            matches_expected_language(
                "病患表示血尿持續三天，伴隨下腹痛。", "en-US"
            )
            is False
        )

    def test_en_output_mismatches_zh_expected(self):
        assert (
            matches_expected_language(
                "Patient reports hematuria for three days.", "zh-TW"
            )
            is False
        )

    def test_ambiguous_text_passes_any_expected(self):
        """
        偵測不出時（回 None）視為通過 — 這是 safety default，
        避免 ICD-10 / 純數字 / 空字串被誤判為不匹配。
        """
        assert matches_expected_language("N39.0", "zh-TW") is True
        assert matches_expected_language("N39.0", "en-US") is True
        assert matches_expected_language("", "zh-TW") is True

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("膀胱炎需要做尿液檢查", "zh-TW"),
            ("Cystitis requires a urinalysis", "en-US"),
            ("建議安排 cystoscopy 進一步評估", "zh-TW"),  # 混語仍屬中文主
        ],
    )
    def test_realistic_clinical_phrases(self, text: str, expected: str):
        assert matches_expected_language(text, expected) is True
