"""
UpdateProfileRequest 驗證 preferred_language 欄位：
- 只接受 SUPPORTED_LANGUAGES 白名單
- 大小寫 / region 前後綴自動正規化（zh-tw → zh-TW）
- 空字串或 None → 清除偏好
- 非白名單值 → raise ValidationError
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import UpdateProfileRequest


def test_accepts_supported_language():
    req = UpdateProfileRequest(preferred_language="en-US")
    assert req.preferred_language == "en-US"


def test_normalizes_case():
    """zh-tw / EN-us → canonical form。"""
    assert UpdateProfileRequest(preferred_language="zh-tw").preferred_language == "zh-TW"
    assert UpdateProfileRequest(preferred_language="EN-us").preferred_language == "en-US"


def test_empty_string_resets_to_none():
    """空字串代表「清除偏好」，回到 accept-language 推斷。"""
    req = UpdateProfileRequest(preferred_language="")
    assert req.preferred_language is None


def test_none_is_allowed():
    req = UpdateProfileRequest(preferred_language=None)
    assert req.preferred_language is None


def test_unsupported_language_rejected():
    with pytest.raises(ValidationError):
        UpdateProfileRequest(preferred_language="fr-FR")


def test_garbage_rejected():
    with pytest.raises(ValidationError):
        UpdateProfileRequest(preferred_language="not-a-lang")


def test_partial_update_without_language():
    """單純改名時 preferred_language 不需要帶。"""
    req = UpdateProfileRequest(name="新名字")
    assert req.name == "新名字"
    assert req.preferred_language is None
