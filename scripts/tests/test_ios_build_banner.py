"""The build banner must describe the selected backend, including staging."""

import os
from pathlib import Path
import re
import subprocess


def test_build_banner_preserves_production_warning_and_shows_custom_targets():
    script = (
        Path(__file__).resolve().parents[2]
        / "flutter_app/tool/build_ios_testflight.sh"
    ).read_text()
    constants = "\n".join(re.findall(r"^readonly PROD_.*$", script, re.MULTILINE))
    banner = script[script.index("print_data_risk_banner() {") :]
    banner = banner.split("# --- 參數處理", 1)[0]
    command = constants + "\n" + banner + "\nprint_data_risk_banner"
    env = {k: v for k, v in os.environ.items() if k not in {"API_BASE", "WS_BASE"}}
    production = subprocess.check_output(["bash", "-c", command], env=env, text=True)
    assert "生產後端" in production and "PHI" in production
    for targets in (
        {"API_BASE": "https://staging.example.com/api/v1", "WS_BASE": "wss://staging.example.com/api/v1/ws"},
        {"WS_BASE": "wss://staging.example.com/api/v1/ws"},
    ):
        output = subprocess.check_output(["bash", "-c", command], env=env | targets, text=True)
        assert "自訂後端建置" in output
        assert "這顆包連的是「生產後端」" not in output
        assert all(value in output for value in targets.values())
