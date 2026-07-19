"""
PDF 匯出安全守護：

- _build_report_html：LLM 生成／醫師自由文字欄位（summary、clinical_impression、
  chief_complaint、review_notes、objective/plan JSON dump）一律 HTML 逃逸，
  注入的 <img src> / & 不得以原始形式出現在輸出 HTML。
- _forbid_url_fetch：WeasyPrint url_fetcher 一律拒絕（SSRF／本地檔讀取防護），
  且 fetch 失敗不影響 write_pdf 產出。
"""

from types import SimpleNamespace

import pytest

from app.services.report_service import (
    _build_report_html,
    _forbid_url_fetch,
    _format_dict,
)

# 模擬 prompt injection：外部 img、file:// 讀取、未逃逸 ampersand
PAYLOAD = '<img src="http://attacker.example/x.png"> AT&T <link href="file:///etc/passwd">'


def _make_report(**overrides):
    base = dict(
        id="00000000-0000-0000-0000-000000000001",
        generated_at=None,
        review_status=None,
        review_notes=None,
        subjective={},
        objective={},
        assessment={},
        plan={},
        raw_transcript=None,
        summary=None,
        icd10_codes=[],
        ai_confidence_score=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestBuildReportHtmlEscaping:
    def test_free_text_fields_are_escaped(self):
        report = _make_report(
            summary=PAYLOAD,
            subjective={"chief_complaint": PAYLOAD},
            assessment={"clinical_impression": PAYLOAD},
            review_notes=PAYLOAD,
        )
        html = _build_report_html(report, language="zh-TW")

        # 原始注入標記不得存在（模板本身沒有 <img>/<link>）
        assert "<img" not in html
        assert "<link" not in html
        # 逃逸後的形式必須存在
        assert "&lt;img" in html
        assert "AT&amp;T" in html

    def test_objective_and_plan_json_dumps_are_escaped(self):
        report = _make_report(
            objective={"physical_exam": PAYLOAD},
            plan={"advice": PAYLOAD},
        )
        html = _build_report_html(report, language="en-US")

        assert "<img" not in html
        assert "<link" not in html
        assert "&lt;img" in html

    def test_format_dict_escapes_values(self):
        out = _format_dict({"note": PAYLOAD})
        assert "<img" not in out
        assert "&lt;img" in out


class TestForbidUrlFetch:
    @pytest.mark.parametrize(
        "url",
        [
            "http://attacker.example/x.png",
            "https://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ],
    )
    def test_rejects_all_urls(self, url):
        with pytest.raises(ValueError):
            _forbid_url_fetch(url)

    def test_write_pdf_survives_rejected_resource(self):
        """fetch 被拒僅略過該資源，PDF 仍成功產出（不 crash、不外連）。"""
        from weasyprint import HTML

        pdf = HTML(
            string='<p>ok</p><img src="http://attacker.example/x.png">',
            url_fetcher=_forbid_url_fetch,
        ).write_pdf()
        assert pdf.startswith(b"%PDF")
