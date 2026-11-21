#!/usr/bin/env bash
set -euo pipefail

native_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
flutter_dir="$native_dir/../flutter_app"
build_root="$native_dir/build/testflight"
team_id=K593X99M7G
version=1.0.0

die() { printf '錯誤：%s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
用法：
  build_ios_testflight.sh [最後一版 Flutter IPA]
  build_ios_testflight.sh --verify-only <原生 IPA> <預期 build 號> [最後一版 Flutter IPA]

建置前使用 ~/.appstoreconnect/asc_api.py 唯讀查詢 ASC。
可用 ASC_PYTHON 指定裝有 PyJWT 與 cryptography 的 Python。
輸出放在 ios_native/build/testflight/，由人驗收後手動上傳。
HELP
}

verify() {
  local ipa="$1" expected_build="$2" legacy="${3:-}"
  python3 -u "$native_dir/tool/verify_ios_testflight.py" \
    "$ipa" "$expected_build" "$version" "$team_id" "$legacy"
  shasum -a 256 "$ipa"
  printf '原生 IPA 本機驗證通過。\n'
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --verify-only)
    shift
    [[ $# -eq 2 || $# -eq 3 ]] || die "$(usage)"
    [[ -f "$1" && "$2" =~ ^[0-9]{12}$ ]] || die "需要已存在的 IPA 與 12 位預期 build 號。"
    [[ $# -eq 2 || -f "$3" ]] || die "找不到 Flutter IPA：$3"
    verify "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")" "$2" "${3:-}"
    exit
    ;;
esac
[[ $# -le 1 && "${1:-}" != -* ]] || die "$(usage)"
[[ $# -eq 0 || -f "$1" ]] || die "找不到 Flutter IPA：$1"
repo_dir="$native_dir/.."
source_sha="$(git -C "$repo_dir" rev-parse origin/main)"
git -C "$repo_dir" merge-base --is-ancestor 6e1bf55 "$source_sha" ||
  die "請先更新 origin/main 至含 #134（6e1bf55）的版本。"
app_inputs=(ios_native/App ios_native/Config ios_native/GUVoice.xcodeproj ios_native/project.yml
  flutter_app/ios/Runner/GoogleService-Info.plist flutter_app/ios/ExportOptions.plist
  flutter_app/tool/env.production.sh flutter_app/tool/build_ios_testflight.sh)
git -C "$repo_dir" diff --quiet "$source_sha" HEAD -- "${app_inputs[@]}" ||
  die "App 原始碼或共用發佈設定與 origin/main 不同。"
[[ -z "$(git -C "$repo_dir" status --porcelain --untracked-files=all -- "${app_inputs[@]}" ios_native/tool)" ]] ||
  die "App 原始碼或發佈腳本有未提交變更。"

asc_max="$("${ASC_PYTHON:-python3}" -BI - "$HOME/.appstoreconnect/asc_api.py" <<'PY'
import re
import runpy
import sys
from urllib.parse import urlsplit

asc = runpy.run_path(sys.argv[1])
path = "/v1/builds"
params = {"filter[app]": asc["APP_ID"], "fields[builds]": "version", "limit": "200"}
builds = []
while path:
    status, page = asc["call"]("GET", path, params)
    if status != 200:
        sys.exit(f"App Store Connect builds GET 失敗，HTTP {status}")
    builds.extend(row["attributes"]["version"] for row in page["data"])
    link = urlsplit(page["links"].get("next") or "")
    path = link.path + ("?" + link.query if link.query else "")
    params = None
if not builds or any(not re.fullmatch(r"[0-9]{12}", build) for build in builds):
    sys.exit("App Store Connect build 清單為空或有其他格式，請確認版本排序。")
print(max(builds))
PY
)"
build="$(date -u +%Y%m%d%H%M)"
[[ "$build" > "$asc_max" && "$build" > 202611141854 ]] ||
  die "UTC build $build 必須大於 ASC 最高號 $asc_max 與切換基線 202611141854。"

release_sha="$(git -C "$repo_dir" rev-parse HEAD)"
run_dir="$build_root/$build"
mkdir -p "$build_root"
mkdir "$run_dir" || die "已有此 build 的輸出目錄：$run_dir"
export_options="$run_dir/ExportOptions.plist"
cp "$flutter_dir/ios/ExportOptions.plist" "$export_options"
[[ "$(plutil -extract destination raw -o - "$export_options")" == export &&
   "$(plutil -extract method raw -o - "$export_options")" == app-store-connect &&
   "$(plutil -extract signingStyle raw -o - "$export_options")" == automatic &&
   "$(plutil -extract teamID raw -o - "$export_options")" == "$team_id" &&
   "$(plutil -extract manageAppVersionAndBuildNumber raw -o - "$export_options")" == false &&
   "$(plutil -extract testFlightInternalTestingOnly raw -o - "$export_options")" == true ]] ||
  die "ExportOptions.plist 不符合內部 TestFlight 的本機匯出設定。"
printf 'App source=%s\nRelease scripts=%s\nASC max=%s\nVersion=%s (%s)\n' \
  "$source_sha" "$release_sha" "$asc_max" "$version" "$build" |
  tee "$run_dir/build.txt"

archive="$run_dir/GUVoice.xcarchive"
xcodebuild -project "$native_dir/GUVoice.xcodeproj" -scheme GUVoice \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath "$run_dir/DerivedData" \
  -clonedSourcePackagesDirPath "$run_dir/SourcePackages" \
  -disableAutomaticPackageResolution -archivePath "$archive" \
  MARKETING_VERSION="$version" CURRENT_PROJECT_VERSION="$build" archive \
  2>&1 | tee "$run_dir/archive.log"

xcodebuild -exportArchive -archivePath "$archive" -exportPath "$run_dir/export" \
  -exportOptionsPlist "$export_options" 2>&1 | tee "$run_dir/export.log"

ipas=("$run_dir/export/"*.ipa)
[[ ${#ipas[@]} -eq 1 && -f "${ipas[0]}" ]] || die "匯出目錄應有一個 IPA：$run_dir/export"
verify "${ipas[0]}" "$build" "${1:-}" 2>&1 | tee "$run_dir/verify.log"
printf 'IPA=%s\n' "${ipas[0]}"
