"""4xx 錯誤文案的語言要和 LanguageMiddleware 解析出的 request.state.language 一致。

先前 `_resolve_request_language` 只看 Accept-Language／user，忽略 `?lng=`／`X-Language`
——同一請求 200 是英文、422 卻是中文。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.exceptions import _resolve_request_language


def _request(state: dict, accept_language: str | None):
    headers = {"accept-language": accept_language} if accept_language else {}
    return SimpleNamespace(state=SimpleNamespace(**state), headers=headers)


def test_middleware_resolution_wins_over_accept_language():
    req = _request({"language": "en-US"}, "zh-TW")
    assert _resolve_request_language(req) == "en-US"


def test_falls_back_to_accept_language_without_middleware_state():
    req = _request({}, "en-US")
    assert _resolve_request_language(req) == "en-US"
