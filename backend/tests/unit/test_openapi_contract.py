"""API 契約快照：路由集合與 schema 形狀改變時紅燈。

重構期間最怕的是「不小心」改了對外介面。這支把 FastAPI 的 OpenAPI 壓成一份
穩定的摘要（method+path、每條路由的 query/path 參數與 required、每個 component
schema 的欄位名與 required 清單）存成 JSON；任何差異都會列出來。

刻意的介面變更：``UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/unit/test_openapi_contract.py``
重生快照，並在 commit message 說明為什麼。

需要與 CI 相同的測試環境變數（HS256 JWT 等），否則 app import 會失敗。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("openapi_contract_snapshot.json")


def _summarize(spec: dict) -> dict:
    routes: dict[str, dict] = {}
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            params = sorted(
                f"{p['in']}:{p['name']}{'*' if p.get('required') else ''}"
                for p in op.get("parameters", [])
            )
            body = op.get("requestBody", {})
            body_ref = None
            for media in body.get("content", {}).values():
                body_ref = media.get("schema", {}).get("$ref")
            resp = op.get("responses", {}).get("200") or op.get("responses", {}).get("201") or {}
            resp_ref = None
            for media in resp.get("content", {}).values():
                resp_ref = json.dumps(media.get("schema", {}), sort_keys=True)
            routes[f"{method.upper()} {path}"] = {
                "params": params,
                "request": body_ref,
                "response": resp_ref,
            }
    schemas: dict[str, dict] = {}
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        schemas[name] = {
            "properties": sorted(schema.get("properties", {}).keys()),
            "required": sorted(schema.get("required", [])),
        }
    return {"routes": routes, "schemas": schemas}


def _current() -> dict:
    from app.main import app

    return _summarize(app.openapi())


def test_openapi_contract_matches_snapshot():
    current = _current()
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1" or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    expected = json.loads(SNAPSHOT.read_text())

    diffs: list[str] = []
    for section in ("routes", "schemas"):
        cur, exp = current[section], expected[section]
        for key in sorted(set(cur) | set(exp)):
            if key not in cur:
                diffs.append(f"- {section}: {key} (removed)")
            elif key not in exp:
                diffs.append(f"+ {section}: {key} (added)")
            elif cur[key] != exp[key]:
                diffs.append(f"~ {section}: {key}\n    was {exp[key]}\n    now {cur[key]}")
    assert not diffs, "OpenAPI 契約與快照不符（刻意變更請用 UPDATE_OPENAPI_SNAPSHOT=1 重生）:\n" + "\n".join(diffs)
