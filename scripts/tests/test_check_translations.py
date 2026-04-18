"""Unit tests for scripts/check_translations.py.

以 tmp_path fixture 建臨時 locale 目錄,測各種 coverage 情境,確保:
- 完整覆蓋 → 100%
- 巢狀缺 key → 正確統計
- reference 不存在 → 明確錯誤
- target 有多餘 key → 不計入 missing 但列進 extra_keys
- beta locale → 只檢查 common.json
- JSON output schema 正確
- 低於閾值 → exit code 1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# 將 scripts/ 加進 sys.path,讓 test 可以 import check_translations
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_translations as ct  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_locale(root: Path, locale: str, namespaces: dict[str, dict]) -> None:
    locale_dir = root / locale
    locale_dir.mkdir(parents=True, exist_ok=True)
    for ns, data in namespaces.items():
        (locale_dir / f"{ns}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


@pytest.fixture()
def locales_root(tmp_path: Path) -> Path:
    return tmp_path / "locales"


# ---------------------------------------------------------------------------
# flatten_keys
# ---------------------------------------------------------------------------


def test_flatten_keys_nested():
    data = {"a": {"b": "x", "c": {"d": "y"}}, "e": "z"}
    assert ct.flatten_keys(data) == {"a.b", "a.c.d", "e"}


def test_flatten_keys_empty_dict_is_leaf():
    data = {"a": {}, "b": "x"}
    assert ct.flatten_keys(data) == {"a", "b"}


def test_flatten_keys_list_is_leaf():
    data = {"arr": [1, 2, 3], "s": "x"}
    assert ct.flatten_keys(data) == {"arr", "s"}


# ---------------------------------------------------------------------------
# Coverage — complete
# ---------------------------------------------------------------------------


def test_full_coverage_reports_100_percent(locales_root: Path):
    payload = {"a": "x", "b": {"c": "y", "d": "z"}}
    _write_locale(locales_root, "zh-TW", {"common": payload})
    _write_locale(locales_root, "en-US", {"common": payload})

    report = ct.check_translations(
        locales_dir=locales_root, reference="zh-TW", beta_locales=[]
    )
    report.threshold = 95.0

    en = next(loc for loc in report.locales if loc.locale == "en-US")
    assert en.coverage == 100.0
    assert en.total_missing == 0
    assert report.failed_locales() == []


# ---------------------------------------------------------------------------
# Coverage — nested missing
# ---------------------------------------------------------------------------


def test_nested_missing_key_counted(locales_root: Path):
    ref = {"a": {"b": "x", "c": "y"}, "d": "z"}
    tgt = {"a": {"b": "x"}, "d": "z"}  # missing a.c
    _write_locale(locales_root, "zh-TW", {"common": ref})
    _write_locale(locales_root, "en-US", {"common": tgt})

    report = ct.check_translations(
        locales_dir=locales_root, reference="zh-TW", beta_locales=[]
    )
    report.threshold = 95.0

    en = next(loc for loc in report.locales if loc.locale == "en-US")
    ns = en.namespaces[0]
    assert ns.missing_keys == ["a.c"]
    assert ns.reference_count == 3
    assert ns.coverage == round(2 * 100 / 3, 1)


# ---------------------------------------------------------------------------
# Reference missing → error
# ---------------------------------------------------------------------------


def test_reference_dir_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Reference locale directory"):
        ct.check_translations(
            locales_dir=tmp_path / "does-not-exist",
            reference="zh-TW",
            beta_locales=[],
        )


def test_reference_empty_raises(locales_root: Path):
    (locales_root / "zh-TW").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="No JSON namespaces"):
        ct.check_translations(
            locales_dir=locales_root, reference="zh-TW", beta_locales=[]
        )


# ---------------------------------------------------------------------------
# Extra keys warning but not counted as missing
# ---------------------------------------------------------------------------


def test_extra_keys_warn_but_not_missing(locales_root: Path):
    ref = {"a": "x"}
    tgt = {"a": "x", "typo": "extra"}
    _write_locale(locales_root, "zh-TW", {"common": ref})
    _write_locale(locales_root, "en-US", {"common": tgt})

    report = ct.check_translations(
        locales_dir=locales_root, reference="zh-TW", beta_locales=[]
    )
    report.threshold = 95.0
    en = next(loc for loc in report.locales if loc.locale == "en-US")
    ns = en.namespaces[0]
    assert ns.missing_keys == []
    assert ns.extra_keys == ["typo"]
    assert en.coverage == 100.0


# ---------------------------------------------------------------------------
# Beta locale — only common.json counted
# ---------------------------------------------------------------------------


def test_beta_locale_only_common_counted(locales_root: Path):
    ref_common = {"greet": "hi"}
    ref_soap = {"x.y": "z", "x.q": "q"}
    _write_locale(
        locales_root,
        "zh-TW",
        {"common": ref_common, "soap": ref_soap},
    )
    # ja-JP: complete common, no soap — should still pass (beta ignores non-common)
    _write_locale(locales_root, "ja-JP", {"common": ref_common})

    report = ct.check_translations(
        locales_dir=locales_root,
        reference="zh-TW",
        beta_locales=["ja-JP"],
    )
    report.threshold = 95.0

    ja = next(loc for loc in report.locales if loc.locale == "ja-JP")
    assert ja.is_beta is True
    assert ja.coverage == 100.0  # 只算 common

    soap_ns = next(ns for ns in ja.namespaces if ns.namespace == "soap")
    assert soap_ns.skipped is True

    # beta 不進 failed_locales,即使 soap 缺光
    assert report.failed_locales() == []


def test_beta_locale_with_bad_common_still_not_in_failed(locales_root: Path):
    # beta locale 即便 common 低於閾值,按設計也不 fail CI
    # (beta 只是不強制閾值;若要改策略可調整此測試)
    ref = {"a": "x", "b": "y", "c": "z"}
    bad = {"a": "x"}  # 33% coverage
    _write_locale(locales_root, "zh-TW", {"common": ref})
    _write_locale(locales_root, "ko-KR", {"common": bad})

    report = ct.check_translations(
        locales_dir=locales_root,
        reference="zh-TW",
        beta_locales=["ko-KR"],
    )
    report.threshold = 95.0

    assert report.failed_locales() == []


# ---------------------------------------------------------------------------
# Active locale below threshold → counted as failed
# ---------------------------------------------------------------------------


def test_active_locale_below_threshold_fails(locales_root: Path):
    ref = {f"k{i}": str(i) for i in range(100)}
    tgt = {f"k{i}": str(i) for i in range(90)}  # 90% coverage
    _write_locale(locales_root, "zh-TW", {"common": ref})
    _write_locale(locales_root, "en-US", {"common": tgt})

    report = ct.check_translations(
        locales_dir=locales_root, reference="zh-TW", beta_locales=[]
    )
    report.threshold = 95.0
    failed = report.failed_locales()
    assert [l.locale for l in failed] == ["en-US"]


# ---------------------------------------------------------------------------
# JSON output schema
# ---------------------------------------------------------------------------


def test_json_output_schema(locales_root: Path, capsys):
    ref = {"a": "x", "b": "y"}
    tgt = {"a": "x"}
    _write_locale(locales_root, "zh-TW", {"common": ref})
    _write_locale(locales_root, "en-US", {"common": tgt})

    exit_code = ct.main(
        [
            "--locales-dir",
            str(locales_root),
            "--reference",
            "zh-TW",
            "--threshold",
            "95",
            "--beta-locales",
            "",
            "--json",
        ]
    )
    assert exit_code == 1  # 50% < 95%
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is False
    assert data["reference"] == "zh-TW"
    assert data["threshold_pct"] == 95.0
    assert "en-US" in data["failed_locales"]
    locales = {l["locale"]: l for l in data["locales"]}
    assert "zh-TW" in locales and "en-US" in locales
    en = locales["en-US"]
    assert en["missing_total"] == 1
    assert en["namespaces"][0]["missing_keys"] == ["b"]


# ---------------------------------------------------------------------------
# GitHub summary output
# ---------------------------------------------------------------------------


def test_github_summary_has_table_and_result(locales_root: Path, capsys):
    ref = {"a": "x"}
    _write_locale(locales_root, "zh-TW", {"common": ref})
    _write_locale(locales_root, "en-US", {"common": ref})

    exit_code = ct.main(
        [
            "--locales-dir",
            str(locales_root),
            "--reference",
            "zh-TW",
            "--beta-locales",
            "",
            "--github-summary",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "## Translation staleness report" in out
    assert "| Locale | Type | Coverage |" in out
    assert "**Result: OK**" in out


# ---------------------------------------------------------------------------
# CLI missing reference → exit 2
# ---------------------------------------------------------------------------


def test_cli_missing_reference_dir_exits_2(tmp_path: Path, capsys):
    exit_code = ct.main(
        [
            "--locales-dir",
            str(tmp_path / "nope"),
            "--reference",
            "zh-TW",
        ]
    )
    assert exit_code == 2


# ---------------------------------------------------------------------------
# Target namespace file missing (not beta) → all keys counted missing
# ---------------------------------------------------------------------------


def test_missing_target_namespace_file_counts_all_missing(locales_root: Path):
    ref_common = {"a": "x"}
    ref_soap = {"b": "y", "c": "z"}
    _write_locale(
        locales_root,
        "zh-TW",
        {"common": ref_common, "soap": ref_soap},
    )
    # en-US has only common.json — soap.json missing entirely
    _write_locale(locales_root, "en-US", {"common": ref_common})

    report = ct.check_translations(
        locales_dir=locales_root, reference="zh-TW", beta_locales=[]
    )
    report.threshold = 95.0
    en = next(loc for loc in report.locales if loc.locale == "en-US")
    soap_ns = next(ns for ns in en.namespaces if ns.namespace == "soap")
    assert soap_ns.target_exists is False
    assert soap_ns.missing_keys == ["b", "c"]
