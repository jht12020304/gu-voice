"""
Unit tests for audio_service Supabase 設定鍵正確性。

守護 config-key mismatch 回歸：

audio_service 之前呼叫 create_client(SUPABASE_URL, SUPABASE_KEY)，
但 Settings 只定義 SUPABASE_SERVICE_ROLE_KEY（沒有 SUPABASE_KEY），
hasattr 守門會靜默傳空字串，導致上傳 / 簽名 URL 全部失敗。

此測試純讀原始碼，不碰真 DB / 真 Supabase，確保：
- 模組引用 SUPABASE_SERVICE_ROLE_KEY
- 模組不再引用不存在的 SUPABASE_KEY
- Settings 確實有 SUPABASE_SERVICE_ROLE_KEY 而無 SUPABASE_KEY
"""

from __future__ import annotations

import inspect

from app.core.config import settings
from app.services import audio_service


def test_audio_service_uses_service_role_key():
    """audio_service 原始碼應引用 SUPABASE_SERVICE_ROLE_KEY。"""
    source = inspect.getsource(audio_service)
    assert "SUPABASE_SERVICE_ROLE_KEY" in source


def test_audio_service_does_not_reference_nonexistent_supabase_key():
    """audio_service 不應再引用不存在的 SUPABASE_KEY 屬性。"""
    source = inspect.getsource(audio_service)
    # SUPABASE_SERVICE_ROLE_KEY 含 KEY，故比對完整的 settings.SUPABASE_KEY 取用
    assert "SUPABASE_KEY" not in source
    assert "settings.SUPABASE_KEY" not in source


def test_settings_defines_service_role_key_not_supabase_key():
    """Settings 應有 SUPABASE_SERVICE_ROLE_KEY，且無 SUPABASE_KEY。"""
    assert hasattr(settings, "SUPABASE_SERVICE_ROLE_KEY")
    assert not hasattr(settings, "SUPABASE_KEY")
