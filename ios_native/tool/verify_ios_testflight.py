"""Verify native-only release settings in the signed IPA."""

import os
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parents[1]
LOCALES = ("en-US", "ja", "ko", "vi", "zh-Hant")
PRODUCTION_ENDPOINTS = {
    "API_BASE": "https://gu.zymomed.com/api/v1",
    "WS_BASE": "wss://gu.zymomed.com/api/v1/ws",
    "WEB_BASE": "https://gu.zymomed.com",
}
BUNDLE_ID = "com.guvoice.guVoice"
IDENTITY_KEYS = (
    "application-identifier",
    "com.apple.developer.team-identifier",
    "keychain-access-groups",
    "aps-environment",
    "com.apple.developer.usernotifications.time-sensitive",
)
LOOPBACK = rb"(?:localhost\.?(?![a-z0-9.-])|127(?:\.[0-9]{1,3}){3}|\[::1\])"
LOOPBACK_TEXT = re.compile(rb"(?<![a-z0-9.-])" + LOOPBACK, re.IGNORECASE)
TEST_CREDENTIAL = re.compile(
    rb"@example\.com|Kiosk-fixture9!|"
    rb"GUVOICE_KIOSK_TEST_FIXTURE|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
KEY_SUFFIXES = {".p8", ".p12", ".pfx", ".pem", ".key", ".cer", ".certsigningrequest"}


def require(condition, message):
    if not condition:
        sys.exit(f"原生 IPA 驗證失敗：{message}")


def plist(path):
    return plistlib.loads(path.read_bytes())


def extract_app(ipa, destination):
    subprocess.run(["unzip", "-q", ipa, "-d", destination], check=True)
    apps = list((destination / "Payload").glob("*.app"))
    require(len(apps) == 1 and apps[0].is_dir(), f"{ipa} 應含一個 Payload/*.app")
    return apps[0]


def signature(app):
    subprocess.run(["codesign", "--verify", "--deep", "--strict", app], check=True)
    return plistlib.loads(subprocess.check_output(["codesign", "-d", "--entitlements", "-", "--xml", app]))


def scan_bundle(root):
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        require(
            not any(part.endswith(".xctest") or part == "TestsSupport" for part in relative.parts),
            f"包含測試目錄：{relative}",
        )
        if not path.is_file() or path.is_symlink():
            continue
        require(path.suffix.lower() not in KEY_SUFFIXES, f"包含憑證檔案：{relative}")
        data = path.read_bytes()
        if data.startswith(b"bplist00"):
            data = plistlib.dumps(plistlib.loads(data))
        elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
            data = data.decode("utf-16").encode()
        require(not TEST_CREDENTIAL.search(data), f"包含測試憑證或測試設定：{relative}")
        require(not LOOPBACK_TEXT.search(data), f"包含 localhost 或 loopback 位址：{relative}")
    print("包內檔案掃描通過，未發現測試目錄、憑證檔案或可辨識的 fixture 和 loopback 字面值。")
    print("執行檔未發現 GUVOICE_KIOSK_TEST_FIXTURE。位元組掃描無法辨識 Swift 編進指令的短字串。")


def verify(ipa, expected_build, version, team_id, reference):
    build_dir = NATIVE_DIR / "build"
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build_dir) as work:
        unpacked = Path(work) / "native"
        app = extract_app(ipa, unpacked)
        entitlements = signature(app)
        signing = subprocess.run(
            ["codesign", "-dv", "--verbose=4", app], capture_output=True, text=True, check=True
        ).stderr.splitlines()
        require(f"TeamIdentifier={team_id}" in signing, "簽章 TeamIdentifier 錯誤")
        require(
            any(line.startswith("Authority=Apple Distribution:") for line in signing),
            "簽章憑證不是 Apple Distribution",
        )
        for key, expected in {
            "application-identifier": f"{team_id}.{BUNDLE_ID}",
            "com.apple.developer.team-identifier": team_id,
            "aps-environment": "production",
        }.items():
            require(entitlements.get(key) == expected, f"簽章 {key} 預期 {expected}")
            print(f"{key} = {expected}")
        require(entitlements.get("get-task-allow", False) is False, "簽章允許除錯（get-task-allow）")
        require(
            entitlements.get("com.apple.developer.usernotifications.time-sensitive") is True,
            "缺少 Time Sensitive Notifications 簽章權限",
        )
        print("get-task-allow = false 或未簽入，Time Sensitive Notifications = true")
        print(f"codesign --verify 通過，Apple Distribution，TeamIdentifier={team_id}")

        info = plist(app / "Info.plist")
        expected = {
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": expected_build,
            "KIOSK_IDLE_TIMEOUT_SECONDS": "180",
            **PRODUCTION_ENDPOINTS,
        }
        for key, value in expected.items():
            require(info.get(key) == value, f"{key} 預期 {value}，實際 {info.get(key)!r}")
            print(f"{key} = {value}")
        require("NSAppTransportSecurity" not in info, "Release 帶有 ATS 覆寫")
        require("remote-notification" in info.get("UIBackgroundModes", []), "缺少 remote-notification")
        mic = info.get("NSMicrophoneUsageDescription", "")
        require(isinstance(mic, str) and mic.strip(), "缺少麥克風用途說明")
        require((app / "Assets.car").is_file(), "缺少 Assets.car")
        icon = info.get("CFBundleIcons", {}).get("CFBundlePrimaryIcon", {}).get("CFBundleIconName")
        require(icon == "AppIcon", "缺少 CFBundleIcons.CFBundlePrimaryIcon.CFBundleIconName = AppIcon")
        for locale in LOCALES:
            for resource in ("InfoPlist.strings", "Kiosk.strings", "Localizable.strings"):
                require((app / f"{locale}.lproj" / resource).is_file(), f"缺少 {locale} 的 {resource}")
        print("五語皆包含 App、kiosk 與 Info.plist 的翻譯。")
        require(info.get("ITSAppUsesNonExemptEncryption") is False, "出口合規旗標應為布林 false")
        require(info.get("TFInternalTestingOnly") is True, "缺少 TFInternalTestingOnly = true")
        print(f"UIBackgroundModes 含 remote-notification，麥克風用途說明：{mic}")
        print("巢狀 CFBundleIconName = AppIcon，ITSAppUsesNonExemptEncryption = false")
        print("原生驗證直接從已簽 Info.plist 確認 TFInternalTestingOnly = true")
        print(f"MinimumOSVersion = {info.get('MinimumOSVersion')}")

        firebase = plist(app / "GoogleService-Info.plist")
        require(firebase.get("BUNDLE_ID") == BUNDLE_ID, "Firebase Bundle ID 錯誤")
        require(firebase == plist(NATIVE_DIR / "Config/GoogleService-Info.plist"), "Firebase 設定與來源不同")
        print("GoogleService-Info.plist 與原生專案來源內容相同。")
        scan_bundle(unpacked)

        if not reference:
            return
        old_app = extract_app(reference, Path(work) / "reference")
        old_info = plist(old_app / "Info.plist")
        require(old_info.get("CFBundleIdentifier") == BUNDLE_ID, "Flutter 參考 IPA 的 Bundle ID 錯誤")
        old = signature(old_app)
        require(firebase == plist(old_app / "GoogleService-Info.plist"), "Firebase 設定與參考 IPA 不同")
        for key in IDENTITY_KEYS:
            require(old.get(key) == entitlements.get(key), f"與參考 IPA 的 {key} 不一致")
            print(f"與參考 IPA 相同：{key} = {entitlements.get(key)!r}")
        print(f"參考 build = {old_info['CFBundleVersion']}，GoogleService-Info.plist 內容相同。")
        differences = sorted(key for key in old.keys() | entitlements.keys() if old.get(key) != entitlements.get(key))
        for key in differences:
            print(f"Entitlement 差異 {key}：參考 {old.get(key)!r}，原生 {entitlements.get(key)!r}")
        if not differences:
            print("參考 IPA 與候選 IPA 的已簽 entitlements 完全相同。")


if __name__ == "__main__":
    os.environ["LC_ALL"] = "C"
    verify(*sys.argv[1:])
