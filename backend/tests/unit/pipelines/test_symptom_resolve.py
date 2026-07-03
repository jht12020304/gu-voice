"""
Unit tests for `icd10_symptom_map.resolve_symptom_id`（B2 [D6+D4]）。

resolve_symptom_id 是 Celery `report_queue._async_generate` 與 WS
`_generate_soap_report_async` 兩條 SOAP 生成路徑共用的 symptom slug 解析函式
（自 report_queue._resolve_symptom_id 抽出）。覆蓋：

- name_en 正常解析（大小寫 + 空白 + 連字號正規化）
- name_en 缺失時 fallback 到 name（中文會 miss 但不 raise）
- 各種缺資料情境 graceful 回 None
- 「其他」sentinel 主訴解析成 "other" 且刻意不在對映表（預期 unverified）
"""

from __future__ import annotations

from types import SimpleNamespace

from app.pipelines.icd10_symptom_map import SYMPTOM_TO_ICD10, resolve_symptom_id


def _session(name_en=None, name=None):
    """組出帶 chief_complaint 的假 session ORM 物件。"""
    return SimpleNamespace(
        chief_complaint=SimpleNamespace(name_en=name_en, name=name)
    )


# ── 正常解析（種子 name_en → map key）────────────────────────


def test_erectile_dysfunction_name_en_resolves_to_map_key():
    """種子「Erectile dysfunction」→ slug 與 SYMPTOM_TO_ICD10 key 精確吻合。"""
    slug = resolve_symptom_id(_session(name_en="Erectile dysfunction"))
    assert slug == "erectile_dysfunction"
    assert slug in SYMPTOM_TO_ICD10


def test_elevated_psa_name_en_resolves_to_map_key():
    """種子「Elevated PSA」→ 大小寫 + 空白正規化後命中 map key。"""
    slug = resolve_symptom_id(_session(name_en="Elevated PSA"))
    assert slug == "elevated_psa"
    assert slug in SYMPTOM_TO_ICD10


def test_hyphen_normalized_to_underscore():
    """連字號正規化："Flank-Pain" → "flank_pain"。"""
    assert resolve_symptom_id(_session(name_en="Flank-Pain")) == "flank_pain"


# ── fallback 與 graceful 行為 ───────────────────────────────


def test_fallback_to_name_when_name_en_missing():
    """name_en=None 時退回 name；中文 slug 會 miss 對映表，但不 raise。"""
    slug = resolve_symptom_id(_session(name_en=None, name="血尿"))
    assert slug == "血尿"
    assert slug not in SYMPTOM_TO_ICD10  # miss 但 graceful（unverified）


def test_no_chief_complaint_returns_none():
    assert resolve_symptom_id(SimpleNamespace(chief_complaint=None)) is None


def test_empty_name_en_and_none_name_returns_none():
    assert resolve_symptom_id(_session(name_en="", name=None)) is None


def test_none_session_returns_none():
    """傳入 None（WS 路徑查無 session）→ 安全回 None，不 raise。"""
    assert resolve_symptom_id(None) is None


# ── 「其他」sentinel 主訴 ──────────────────────────────────


def test_other_sentinel_resolves_but_not_in_map():
    """「其他」sentinel（name_en="Other"）解析成 "other"，且刻意不登記於
    SYMPTOM_TO_ICD10 → validator 會回 unverified（graceful），固化此預期。"""
    assert resolve_symptom_id(_session(name_en="Other")) == "other"
    assert "other" not in SYMPTOM_TO_ICD10
