"""JWT 黑名單 Redis key 前綴只能有一個定義處。

``core/dependencies.py``（讀）與 ``services/auth_service.py``（寫）曾各自寫死
``"gu:token_blacklist:"`` 並靠註解「保持一致」——一旦漂移，登出的 token
會靜默地繼續有效。這支用 AST 斷言 auth_service 不再自己定義常數，
而是 import 讀取端那份；``websocket/auth.py`` 已經是 import 的。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.core import dependencies
from app.services import auth_service
from app.websocket import auth as ws_auth

_SERVICE_PATH = Path(auth_service.__file__)


def _assigned_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def test_auth_service_imports_prefix_instead_of_redefining():
    assert "BLACKLIST_KEY_PREFIX" not in _assigned_names(_SERVICE_PATH)
    assert auth_service.BLACKLIST_KEY_PREFIX == dependencies.BLACKLIST_KEY_PREFIX
    assert ws_auth.BLACKLIST_KEY_PREFIX == dependencies.BLACKLIST_KEY_PREFIX
