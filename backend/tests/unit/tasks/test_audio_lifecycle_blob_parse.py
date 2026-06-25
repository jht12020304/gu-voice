"""
守護 P3 #30 AUDIO-1：`_delete_audio_blob` 的 bucket / object path 解析純邏輯。

只測 `_parse_bucket_and_path`（純函式、無 DB、無網路），確認：
- Supabase signed / public / authenticated URL → 正確拆出 bucket 與 path（query 丟掉、
  percent-encoding 還原）
- audio_service.upload_audio 存的裸 path → 落在預設 audio-recordings bucket
- 空 / malformed / 非預期 URL → raise ValueError（呼叫端會記成 error、不清 DB → 下次重試）
"""

from __future__ import annotations

import pytest

from app.tasks import audio_lifecycle as al


def test_parse_signed_url_extracts_bucket_and_path():
    url = (
        "https://proj.supabase.co/storage/v1/object/sign/"
        "audio-recordings/sess-1/conv-1.wav?token=abc.def"
    )
    bucket, path = al._parse_bucket_and_path(url)
    assert bucket == "audio-recordings"
    assert path == "sess-1/conv-1.wav"


def test_parse_public_url_extracts_bucket_and_path():
    url = (
        "https://proj.supabase.co/storage/v1/object/public/"
        "tts-audio/sessions/sess-1/msg-9.mp3"
    )
    bucket, path = al._parse_bucket_and_path(url)
    assert bucket == "tts-audio"
    assert path == "sessions/sess-1/msg-9.mp3"


def test_parse_authenticated_url_and_percent_decoding():
    # 含空白被 percent-encode；解析後應還原
    url = (
        "https://proj.supabase.co/storage/v1/object/authenticated/"
        "audio-recordings/sess%201/conv%201.wav"
    )
    bucket, path = al._parse_bucket_and_path(url)
    assert bucket == "audio-recordings"
    assert path == "sess 1/conv 1.wav"


def test_parse_bare_path_uses_default_bucket():
    # audio_service.upload_audio 回傳的裸 path（不含 bucket 前綴）
    bucket, path = al._parse_bucket_and_path("sess-1/conv-1.wav")
    assert bucket == al._DEFAULT_AUDIO_BUCKET == "audio-recordings"
    assert path == "sess-1/conv-1.wav"


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_parse_empty_raises(bad):
    with pytest.raises(ValueError):
        al._parse_bucket_and_path(bad)  # type: ignore[arg-type]


def test_parse_unknown_http_url_raises():
    # 是 http(s) URL 但不是 Supabase Storage 結構 → 不亂刪，raise
    with pytest.raises(ValueError):
        al._parse_bucket_and_path("https://example.com/some/random/file.webm")


def test_parse_storage_url_missing_path_raises():
    # 只有 bucket 沒有 object path
    with pytest.raises(ValueError):
        al._parse_bucket_and_path(
            "https://proj.supabase.co/storage/v1/object/sign/audio-recordings"
        )


def test_delete_helper_exists_and_is_async():
    # router/celery task 仰賴這個 helper 存在且是 coroutine function
    import inspect

    assert inspect.iscoroutinefunction(al._delete_audio_blob)
