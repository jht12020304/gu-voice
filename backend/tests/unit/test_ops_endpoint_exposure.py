"""運維端點的曝光控制（2026-08-22）。

`/metrics`、`/docs`、`/redoc`、`/openapi.json` 在這天之前**四支全部是公開的**。
裡面沒有 PHI，但合起來是一份完整的偵查資料：整個 API 介面與所有欄位名稱、每支端點
的流量與錯誤率、紅旗觸發次數、精確的 Python 版本（好對 CVE），以及「什麼時段沒有人
在用」。

這份測試釘住三件會安靜壞掉的事：

1. **正式環境沒設 token 要當成「關閉」而不是「放行」。** fail-open 的預設值在這種端點
   上等於沒鎖——而且沒有任何跡象看得出來。
2. **未授權要回 404 而不是 401。** 401 等於告訴掃描的人「這裡有東西，只是你沒鑰匙」。
3. **`Instrumentator` 不得再呼叫 `.expose()`。** 那個方法會掛一條無條件公開的
   `/metrics`，把上面兩條整個繞過去。這條用靜態檢查守，因為它只有在有人「順手改回
   官方範例寫法」時才會回來，而那時候測試不會紅。
"""

import pathlib

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import _ops_token_ok, app

TOKEN = "test-metrics-token-0123456789"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def prod(monkeypatch):
    """把 settings 推成正式環境的樣子（gate 是在呼叫當下讀 settings 的）。"""
    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(settings, "METRICS_TOKEN", None, raising=False)


class TestFailClosed:
    def test_production_without_token_is_closed(self, client, prod):
        """沒設 METRICS_TOKEN 的正式環境 = 關閉。這是整份測試最重要的一條。"""
        assert client.get("/metrics").status_code == 404

    def test_development_without_token_stays_open(self, client, monkeypatch):
        """本機開發不必為了看指標先生一組 token。"""
        monkeypatch.setattr(settings, "APP_ENV", "development", raising=False)
        monkeypatch.setattr(settings, "METRICS_TOKEN", None, raising=False)
        assert client.get("/metrics").status_code == 200


class TestTokenGate:
    def test_correct_bearer_is_let_through(self, client, prod, monkeypatch):
        monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN, raising=False)
        r = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        assert "http_requests_total" in r.text

    @pytest.mark.parametrize(
        "header",
        [
            None,
            "",
            "Bearer",
            "Bearer ",
            f"Basic {TOKEN}",
            f"Token {TOKEN}",
            "Bearer wrong-token",
            f"Bearer {TOKEN}x",
            f"Bearer {TOKEN[:-1]}",
        ],
        ids=[
            "no-header", "empty", "scheme-only", "scheme-and-space",
            "basic-scheme", "wrong-scheme", "wrong-token",
            "token-with-suffix", "token-truncated",
        ],
    )
    def test_everything_else_is_404(self, client, prod, monkeypatch, header):
        monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN, raising=False)
        headers = {} if header is None else {"Authorization": header}
        assert client.get("/metrics", headers=headers).status_code == 404

    def test_scheme_match_is_case_insensitive(self, client, prod, monkeypatch):
        """Prometheus 與各種 client 對 scheme 大小寫的寫法不一致。"""
        monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN, raising=False)
        assert client.get(
            "/metrics", headers={"Authorization": f"bearer {TOKEN}"}
        ).status_code == 200

    def test_unauthorised_looks_like_a_missing_route(self, client, prod, monkeypatch):
        """404 的形狀要跟「這條路徑不存在」一樣，不能自己招認端點存在。"""
        monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN, raising=False)
        denied = client.get("/metrics")
        genuinely_absent = client.get("/this-route-does-not-exist")
        assert denied.status_code == genuinely_absent.status_code == 404
        assert denied.json() == genuinely_absent.json()


class TestPureGate:
    """直接測判斷式本身——路由層之外還有 openapi 也共用它。"""

    class _Req:
        def __init__(self, auth=None):
            self.headers = {} if auth is None else {"authorization": auth}

    def test_no_token_configured_defers_to_environment(self, monkeypatch):
        monkeypatch.setattr(settings, "METRICS_TOKEN", None, raising=False)
        monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
        assert _ops_token_ok(self._Req()) is False
        monkeypatch.setattr(settings, "APP_ENV", "development", raising=False)
        assert _ops_token_ok(self._Req()) is True

    def test_configured_token_ignores_environment(self, monkeypatch):
        """設了 token 之後，連 development 也要帶對才過——避免本機習慣帶壞正式環境。"""
        monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN, raising=False)
        monkeypatch.setattr(settings, "APP_ENV", "development", raising=False)
        assert _ops_token_ok(self._Req()) is False
        assert _ops_token_ok(self._Req(f"Bearer {TOKEN}")) is True


class TestDocsExposure:
    def test_docs_follow_app_env_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "DOCS_ENABLED", None, raising=False)
        monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
        assert settings.docs_exposed is False
        monkeypatch.setattr(settings, "APP_ENV", "development", raising=False)
        assert settings.docs_exposed is True

    def test_explicit_setting_wins_both_ways(self, monkeypatch):
        """正式環境臨時要開 Swagger 要能開；本機要關也要能關。"""
        monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
        monkeypatch.setattr(settings, "DOCS_ENABLED", True, raising=False)
        assert settings.docs_exposed is True
        monkeypatch.setattr(settings, "APP_ENV", "development", raising=False)
        monkeypatch.setattr(settings, "DOCS_ENABLED", False, raising=False)
        assert settings.docs_exposed is False


class TestWiring:
    """靜態守衛：這些改法不會讓上面任何一條測試變紅，但會把鎖整個拿掉。"""

    SOURCE = pathlib.Path(__file__).resolve().parents[2] / "app" / "main.py"

    @staticmethod
    def _code_only(text: str) -> str:
        """去掉註解行——本檔的說明文字自己就提到這些名字，會誤判成違規。"""
        return "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )

    def test_instrumentator_never_calls_expose(self):
        code = self._code_only(self.SOURCE.read_text())
        assert ".expose(" not in code, (
            "`Instrumentator().expose()` 會掛一條無條件公開的 /metrics，"
            "把 token 閘門整個繞過去。middleware 用 .instrument(app)，路由自己掛。"
        )
        assert "Instrumentator().instrument(app)" in code, "middleware 還是要裝，否則沒有指標可看"

    def test_the_dead_switch_does_not_come_back(self):
        """`PROMETHEUS_METRICS_ENABLED` 在 Settings 裡不存在，加上 `extra="ignore"`，
        設了也沒用——一個看起來能關、其實關不掉的假開關。只准出現在說明它的註解裡。"""
        code = self._code_only(self.SOURCE.read_text())
        assert "PROMETHEUS_METRICS_ENABLED" not in code
        assert "settings.METRICS_ENABLED" in code

    def test_openapi_is_not_left_wide_open_in_production(self):
        code = self._code_only(self.SOURCE.read_text())
        assert 'openapi_url="/openapi.json" if _docs else None' in code, (
            "正式環境不得掛公開的 openapi.json —— 那是完整的 API schema"
        )
        assert 'docs_url="/docs" if _docs else None' in code
        assert 'redoc_url="/redoc" if _docs else None' in code
