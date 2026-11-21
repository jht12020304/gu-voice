"""The native release entry point identifies its production data boundary."""

from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[2] / "ios_native/tool/build_ios_testflight.sh"


def test_build_banner_identifies_production_and_requires_synthetic_data(monkeypatch):
    monkeypatch.setenv("API_BASE", "https://staging.example.com/api/v1")
    output = subprocess.check_output(["bash", SCRIPT, "--help"], text=True)
    assert "生產後端" in output and "PHI" in output and "合成資料" in output
    assert "staging.example.com" not in output


def test_verify_only_requires_a_real_ipa_and_build_number():
    result = subprocess.run(
        ["bash", SCRIPT, "--verify-only", "/missing.ipa", "invalid"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "需要已存在的 IPA 與 12 位預期 build 號" in result.stderr
