#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Gu Voice — iOS TestFlight 打包腳本
#
# 產出一顆已簽章的 .ipa，供人工上傳到 App Store Connect 做「內部測試」。
#
# 用法（在 repo 任何位置都可以跑，腳本會自己 cd 到 flutter_app/）：
#     tool/build_ios_testflight.sh
#     tool/build_ios_testflight.sh --skip-checks          # 略過 analyze/test
#     tool/build_ios_testflight.sh --build-number=202608211930
#     BUILD_NUMBER=202608211930 tool/build_ios_testflight.sh
#     API_BASE=... WS_BASE=... tool/build_ios_testflight.sh
#
#     # 只跑第 6 關的產物驗證，跳過簽章檢查與整個 build：
#     tool/build_ios_testflight.sh --verify-only=build/ios/ipa/xxx.ipa
#     tool/build_ios_testflight.sh --verify-only=path/to/Runner.app
#
# 這支腳本刻意不做的事：不 commit、不改 pbxproj、不改 Runner.entitlements、
# 不上傳（上傳一律由人確認過產物驗證結果之後手動執行）。
#
# 帳號／憑證／App Store Connect 那一側的設定總表（Team ID、App ID、APNs 金鑰、
# ASC App 記錄、已上傳過的 build、剩下沒做的事）在：docs/ios_release_settings.md
#
# ⚠️ 第一次在這台機器跑真簽章打包時，第 5 關【必然會失敗一次】——macOS 會跳鑰匙圈
#    授權對話框，而錯誤訊息會誤導你。細節見第 5 關前的說明與失敗時的提示。
# ============================================================================

# --- 路徑與常數 -------------------------------------------------------------

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(cd "${app_dir}/.." && pwd)"
export_options="${app_dir}/ios/ExportOptions.plist"
icon_check_python="${repo_dir}/backend/venv/bin/python"
icon_check_pip="${repo_dir}/backend/venv/bin/pip"
ipa_dir="${app_dir}/build/ios/ipa"
dump_dir="${ipa_dir}/verify-dump"
required_flutter="3.41.3"
team_id="K593X99M7G"

# 生產後端。變數名是 API_BASE / WS_BASE（不是 *_BASE_URL），值含 path 後綴。
# 注意：`api-` 開頭的域名是死的，不要用。
readonly PROD_API_BASE="https://gu-voice-app-production.up.railway.app/api/v1"
readonly PROD_WS_BASE="wss://gu-voice-app-production.up.railway.app/api/v1/ws"

die() {
  printf '\n[錯誤] %s\n' "$1" >&2
  shift
  for line in "$@"; do
    printf '        %s\n' "${line}" >&2
  done
  printf '\n' >&2
  exit 1
}

step() { printf '\n==> %s\n' "$1"; }

# --- 資料風險警語（開頭就印，不讓人在不知情下把包發出去）--------------------
#
# 這段刻意【不寫 file:line】。行號在 banner、docs/TODO.md、deployment_guide.md、
# CLAUDE.md、skill 五個地方重複過，最容易腐爛：2026-08-21 就抓到 banner 引到
# `i18n_messages.py:587` / `notify_session_complete`，而那一條的 docstring 明寫
# 「刻意不 fan-out」、呼叫端也只在有 doctor_id 時呼叫（DB 內 doctor_id 全為
# NULL）＝根本不會發出去。照舊 banner 去補去識別化只會改到不會發的那條，
# 真正打到手機的通道原封不動。唯一權威改成 docs/TODO.md §V8。

print_data_risk_banner() {
  cat <<'BANNER'

┌──────────────────────────────────────────────────────────────────────────┐
│  ⚠  這顆包連的是「生產後端」，沒有 staging 環境。送測前務必知道：        │
│                                                                          │
│  1. 推播 body 帶真實病患姓名，而且是明文 fan-out 給全體在職醫師。測試者  │
│     一登入註冊 FCM token，全院病患的姓名就會出現在他的鎖定畫面上。       │
│                                                                          │
│  2. iOS 端沒擋破壞性 API：刪病患、停用帳號、重設密碼在醫師端都可達。     │
│                                                                          │
│  3. 紅旗推播的 body 是 LLM 生成的臨床描述。它目前休眠，但「開始指派醫    │
│     師」那天會自動解封。                                                 │
│                                                                          │
│  已拍板：第一版只裝「你自己一台」，用途純粹是驗證這條打包管道。          │
│  加第 2 個測試人員前的前置條件、以及上面三條的逐條佐證（含 file:line）， │
│  一律以 docs/TODO.md 的 §V8 為準（行號不寫在這裡，避免五處各腐爛一份）。 │
└──────────────────────────────────────────────────────────────────────────┘

BANNER
}

# --- 參數處理 ---------------------------------------------------------------

skip_checks=0
verify_only=""
build_number="${BUILD_NUMBER:-}"
# 只記錄「明確用 --build-number= 指定」的值，供 --verify-only 判斷該不該斷言。
verify_expect_build=""

for arg in "$@"; do
  case "${arg}" in
    --skip-checks)     skip_checks=1 ;;
    # ⚠️ 這兩個 case 的 `*` 也會吃空字串。不擋的話：
    #   --verify-only=  →  verify_only="" → 底下 `-n` 判斷為假 → 靜默落進【完整真 build】，
    #                      而且第 5 關前有 rm -rf "${ipa_dir}"，會把你正想驗的那顆 .ipa 先刪掉。
    #   --build-number= →  靜默【跳過】6e 的 build number 斷言，你以為驗了其實沒驗。
    # 這兩種都是 `--verify-only="$IPA"` 而 IPA 忘了設 這類手滑的形狀，要當場擋。
    --build-number=*)
      build_number="${arg#--build-number=}"
      [[ -n "${build_number}" ]] || die "--build-number= 後面是空的。" \
        "要嘛給值（最多三段句點分隔的非負整數），要嘛整個參數不要帶（會自動用 UTC 時間戳）。"
      verify_expect_build="${build_number}"
      ;;
    --verify-only=*)
      verify_only="${arg#--verify-only=}"
      [[ -n "${verify_only}" ]] || die "--verify-only= 後面是空的（變數沒展開？）。" \
        "這種寫法會靜默跑成完整 build，並且刪掉 build/ios/ipa/ 底下現有的 .ipa。" \
        "正確用法：--verify-only=<path/to/.ipa 或 .app>"
      ;;
    --verify-only)
      die "--verify-only 需要帶路徑：--verify-only=<path/to/.ipa 或 .app>"
      ;;
    -h|--help)
      # 用標記行取範圍，不要寫死行號（行號會隨檔案改動腐爛）。
      # 只取【第一組】 # ==== 之間的內容——本檔後面還有其他 # ==== 分隔線。
      awk '/^# ={10,}$/ { n++; if (n >= 2) exit; next } n == 1' "${BASH_SOURCE[0]}" \
        | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      die "不認得的參數：${arg}" \
          "可用參數：--skip-checks、--build-number=<數字>、--verify-only=<路徑>、--help"
      ;;
  esac
done

print_data_risk_banner

cd "${app_dir}"

# ============================================================================
# 產物驗證（第 6 關）—— 抽成函式，讓 --verify-only 可以單獨跑這一段。
#
# 為什麼要能單獨跑：第 5、6 關在拿到 Distribution 憑證之前【零覆蓋】——
# 第 1e 關（簽章身分）會先擋下，整個 build 根本不會發生。等憑證到手那天才第一次執行
# 這幾十行，等於把最需要正確的那段留到最緊張的時刻才驗。
# --verify-only 讓你今天就能拿現有的 Runner.xcarchive 內的 Runner.app
# （development 簽章，預期會在 6a 的 aps-environment 那一步失敗）把這段邏輯的
# 控制流實際走一遍。
#
# 現況（2026-08-21）：憑證已到手，第 5、6 關都已用真簽章實跑過，並產出 build
# 202608211213 成功上傳 App Store Connect ——這兩關已不再是零覆蓋。
# --verify-only 保留下來的用途改成：驗一顆舊產物／別人的包，或改動這段邏輯後回歸。
# ============================================================================

work_dir=""
cleanup() { [[ -n "${work_dir}" ]] && rm -rf "${work_dir}"; return 0; }
trap cleanup EXIT

# 把驗證用的 plist 留在 mktemp 目錄之外。
# 沒有這一段的話，任何一關 die 之後 trap cleanup 會把 mktemp 目錄整個刪掉，
# 使用者想親眼看 entitlements 裡到底簽了什麼，只能整包重跑一次。
dump_evidence() {
  # 每次 verify_artifact 開頭會先清空（見 reset_dump），否則跑第二顆產物時，
  # 若這一顆在存下 entitlements 之前就 die，dump_dir 裡留的會是**上一顆**的
  # entitlements，而多條 die 訊息都叫使用者去看那個路徑——拿錯證據做判斷。
  mkdir -p "${dump_dir}" || return 0
  if [[ -f "${work_dir}/entitlements.plist" ]]; then
    cp "${work_dir}/entitlements.plist" "${dump_dir}/entitlements.plist" 2>/dev/null || true
  fi
  if [[ -n "${info_plist:-}" && -f "${info_plist}" ]]; then
    cp "${info_plist}" "${dump_dir}/Info.plist" 2>/dev/null || true
  fi
  return 0
}

reset_dump() { rm -rf "${dump_dir}" 2>/dev/null || true; }

plist_get() { plutil -extract "$1" raw -o - "$2" 2>/dev/null || true; }

verify_artifact() {
  local artifact="$1"
  local expect_build="${2:-}"

  reset_dump
  work_dir="$(mktemp -d)"

  # shell 的 tab 補完會在目錄後面自動補一個斜線，而 `*.app` 這個 glob 對
  # `…/Runner.app/` 不成立——不剝掉的話會掉進最後的 else，把「格式沒接受」
  # 誤報成「找不到產物」。本輪要消滅的就是這類誤診。
  artifact="${artifact%/}"

  local app_bundle=""
  if [[ -d "${artifact}" && "${artifact}" == *.app ]]; then
    app_bundle="${artifact}"
    printf '    輸入：.app bundle（未經 .ipa 封裝）%s\n' "${app_bundle}"
  elif [[ -f "${artifact}" ]]; then
    printf '    .ipa：%s\n' "${artifact}"
    printf '    大小：%s\n' "$(du -h "${artifact}" | cut -f1)"
    unzip -q "${artifact}" -d "${work_dir}" || die \
      "解不開 ${artifact}（unzip 失敗）——它可能不是一個 .ipa。"
    while IFS= read -r candidate; do
      app_bundle="${candidate}"
      break
    done < <(find "${work_dir}/Payload" -maxdepth 1 -name '*.app' -type d 2>/dev/null | sort)
    [[ -n "${app_bundle}" ]] || die ".ipa 內找不到 Payload/*.app，檔案結構不對。"
  else
    die "找不到要驗證的產物：${artifact}" \
        "--verify-only 接受一顆 .ipa，或一個 .app 目錄" \
        "（例：build/ios/archive/Runner.xcarchive/Products/Applications/Runner.app）。"
  fi

  info_plist="${app_bundle}/Info.plist"
  dump_evidence

  # -- 6a. 簽章 entitlements —— 這裡是唯一能在本機證明「推播真的會通」的地方。
  local ent_plist="${work_dir}/entitlements.plist"
  codesign -d --entitlements :- "${app_bundle}" >"${ent_plist}" 2>/dev/null || die \
    "產物內的 app 沒有簽章，或 codesign 讀不到 entitlements。" \
    "（--verify-only 指向一顆完全未簽章的 .app 時，這裡失敗是預期結果。" \
    "  注意 .xcarchive 內那顆【是】有簽章的——development 簽章，會過這一關，" \
    "  改在下一關以 aps-environment=development 失敗。）"
  dump_evidence

  # 先分出「簽章時根本沒帶 entitlements」這一種：codesign 會離開碼 0 但吐 0 bytes。
  # 這不是解析失敗，是可行動的事實（例如被 `codesign -f -s -` 這種不帶 entitlements 的
  # ad-hoc 簽章蓋過），要跟下面的解析失敗分開報，否則會叫人去 cat 一個空檔案。
  if [[ ! -s "${ent_plist}" ]]; then
    die "這顆 app 簽章時**沒有帶任何 entitlements**（codesign 成功但輸出是空的）。" \
        "推播需要 aps-environment，沒有 entitlements 就一定收不到。" \
        "常見成因：用 ad-hoc（codesign -s -）或不帶 --entitlements 的方式重簽過。" \
        "請確認這顆產物是由 flutter build ipa + ExportOptions.plist 正常出的包。"
  fi

  # codesign 的輸出格式不保證：可能是 xml1、可能是緊湊排版、某些 macOS 版本
  # 還會在 plist 前面吐一行雜訊。先正規化成 xml1，正規化不了就【誠實報解析失敗】，
  # 不要把解析失敗誤報成「Apple 後台沒勾 Push」——那會把人送去改一個沒壞的東西。
  local ent_norm="${work_dir}/entitlements.normalized.plist"
  local ent_parse_ok=1
  cp "${ent_plist}" "${ent_norm}"
  if ! plutil -convert xml1 "${ent_norm}" >/dev/null 2>&1; then
    sed -n '/<?xml/,$p' "${ent_plist}" >"${ent_norm}" 2>/dev/null || true
    if [[ ! -s "${ent_norm}" ]] || ! plutil -convert xml1 "${ent_norm}" >/dev/null 2>&1; then
      ent_parse_ok=0
    fi
  fi

  if [[ "${ent_parse_ok}" -ne 1 ]]; then
    die "讀不懂 codesign 吐出來的 entitlements —— 這是【解析失敗】，不是 Apple 後台的問題。" \
        "在查明之前不要去動 App ID 的 capability，也不要改 Runner.entitlements。" \
        "" \
        "原始輸出已留在：${dump_dir}/entitlements.plist" \
        "先自己看一眼：cat '${dump_dir}/entitlements.plist'" \
        "以及：codesign -d --entitlements :- '${app_bundle}'"
  fi

  local aps_env
  aps_env="$(plist_get 'aps-environment' "${ent_norm}")"
  if [[ -z "${aps_env}" ]]; then
    # 只有在正規化成 xml1 之後，「<key> 一行、<string> 下一行」這個假設才成立。
    aps_env="$(sed -n '/<key>aps-environment<\/key>/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "${ent_norm}" 2>/dev/null || true)"
  fi

  if [[ "${aps_env}" != "production" ]]; then
    die "簽進去的 aps-environment 是「${aps_env:-完全沒有這個 key}」，不是 production。" \
        "" \
        "⚠️ 先確認你在驗哪一顆：如果這是 --verify-only 指向 .xcarchive 內的 Runner.app，" \
        "  讀到 development 是【預期結果，不是缺陷】——archive 階段那顆是 development" \
        "  簽章（實測 aps-environment=development、get-task-allow=true），要等" \
        "  exportArchive 用 distribution profile 重簽之後才會變 production。" \
        "  真正要驗的是 build/ios/ipa/*.ipa 那一顆。以下只適用於 .ipa：" \
        "" \
        "因果關係（不要只當成 entitlement 打錯字）：" \
        "  aps-environment 的值不是由 ios/Runner/Runner.entitlements 決定的（那份檔案裡" \
        "  躺著 development 是所有 Flutter 專案的正常狀態，Apple TN2265 有寫），而是由" \
        "  簽章時套用的 provisioning profile 決定。distribution profile 的 allowlist" \
        "  一律是 production。" \
        "  → 現在拿到非 production，代表 Apple Developer 後台的 App ID" \
        "    com.guvoice.guVoice【沒有勾選 Push Notifications capability】，" \
        "    所以 Xcode 產出的 distribution profile 裡根本沒有 aps-environment。" \
        "  → 就這樣上傳會吃 ITMS-90078，就算勉強上去了，線上也永遠收不到推播。" \
        "" \
        "先看證據再動手（entitlements 已存檔，不會被 trap 清掉）：" \
        "  ${dump_dir}/entitlements.plist" \
        "" \
        "怎麼修：developer.apple.com → Certificates, IDs & Profiles → Identifiers →" \
        "  com.guvoice.guVoice → 勾 Push Notifications → Save，然後重跑本腳本" \
        "  （Xcode 會自動重新產生 profile）。" \
        "" \
        "不要去改 ios/Runner/Runner.entitlements，改了沒有用。"
  fi
  printf '    aps-environment = production ✓\n'

  # -- 6b. get-task-allow。三態，不要把「讀不到」印成「= false ✓」。
  #    distribution profile 通常【根本沒有】這個 key，development 才會有且為 true。
  local get_task_allow
  get_task_allow="$(plist_get 'get-task-allow' "${ent_norm}")"
  case "${get_task_allow}" in
    true)
      die "簽進去的 get-task-allow = true，這是 development profile 的特徵。" \
          "distribution 簽章必須是 false（或根本沒有這個 key）。" \
          "請確認 Xcode 帳號裡有 Apple Distribution 憑證，" \
          "且 ExportOptions.plist 的 method 是 app-store-connect。" \
          "" \
          "entitlements 已存檔：${dump_dir}/entitlements.plist"
      ;;
    false)
      printf '    get-task-allow = false ✓\n'
      ;;
    "")
      printf '    get-task-allow：entitlements 內沒有這個 key（distribution 簽章的正常狀態）✓\n'
      ;;
    *)
      die "get-task-allow 讀到非預期的值「${get_task_allow}」（預期 true / false / 不存在）。" \
          "這比較像解析出了問題，先看：${dump_dir}/entitlements.plist"
      ;;
  esac

  # -- 6c. 圖示資產。
  [[ -f "${app_bundle}/Assets.car" ]] || die \
    "bundle 內沒有 Assets.car —— actool 沒有編出資產目錄。" \
    "先跑 ${icon_check_python} tool/gen_app_icons.py 補齊圖示，再重跑本腳本。"
  printf '    Assets.car = %s bytes ✓\n' "$(stat -f%z "${app_bundle}/Assets.car")"

  # CFBundleIconName 的位置：實測 Xcode 26.6 的 actool 產生的 partial plist
  # （assetcatalog_generated_info.plist）只把 CFBundleIconName 放在
  # CFBundleIcons.CFBundlePrimaryIcon 底下，【沒有】頂層那一份。
  # 所以這裡先查巢狀路徑，再退回查頂層，兩者有一即可。
  local icon_name
  icon_name="$(plist_get 'CFBundleIcons.CFBundlePrimaryIcon.CFBundleIconName' "${info_plist}")"
  [[ -n "${icon_name}" ]] || icon_name="$(plist_get 'CFBundleIconName' "${info_plist}")"
  [[ -n "${icon_name}" ]] || die \
    "Info.plist 內找不到 CFBundleIconName（巢狀與頂層都沒有）。" \
    "代表 actool 沒有把 AppIcon 編進去，上傳會吃 ITMS-90713。" \
    "Info.plist 已存檔：${dump_dir}/Info.plist"
  printf '    CFBundleIconName = %s ✓\n' "${icon_name}"

  # -- 6d. 出口合規。少了這個 key，build 會卡在 App Store Connect 的
  #    "Missing Compliance"，內部測試也一樣發不出去。
  local encryption
  encryption="$(plist_get 'ITSAppUsesNonExemptEncryption' "${info_plist}")"
  [[ "${encryption}" == "false" ]] || die \
    "Info.plist 的 ITSAppUsesNonExemptEncryption ＝「${encryption:-沒有這個 key}」，預期 false。" \
    "少了它，build 會卡在 App Store Connect 的 Missing Compliance，連內部測試都發不出去。" \
    "檢查 ios/Runner/Info.plist 是否還有這個 key。" \
    "Info.plist 已存檔：${dump_dir}/Info.plist"
  printf '    ITSAppUsesNonExemptEncryption = false ✓\n'

  # -- 6e. 版本資訊。
  bundle_id="$(plist_get 'CFBundleIdentifier' "${info_plist}")"
  short_version="$(plist_get 'CFBundleShortVersionString' "${info_plist}")"
  bundle_version="$(plist_get 'CFBundleVersion' "${info_plist}")"

  [[ "${bundle_id}" == "com.guvoice.guVoice" ]] || die \
    "bundle id 是 ${bundle_id}，預期 com.guvoice.guVoice。"

  if [[ -n "${expect_build}" && "${bundle_version}" != "${expect_build}" ]]; then
    die "CFBundleVersion 是 ${bundle_version}，但我們指定的是 ${expect_build}。" \
        "代表有東西覆寫了 build number；檢查 ExportOptions.plist 的" \
        "manageAppVersionAndBuildNumber 是否為 false。"
  fi
  printf '    CFBundleIdentifier = %s ✓\n' "${bundle_id}"
  printf '    CFBundleShortVersionString = %s / CFBundleVersion = %s\n' \
    "${short_version}" "${bundle_version}"

  # -- 6f. 這一關【驗不到】的東西，明講出來，不要讓人以為驗過了。
  #    ExportOptions.plist 的 testFlightInternalTestingOnly 是給 xcodebuild 的
  #    匯出指示，不會在 bundle 或 entitlements 裡留下任何可檢查的痕跡。
  #    ⚠️ 「本機驗不到」≠「沒生效」：2026-08-21 已證實它會傳達到 App Store Connect
  #    （build 202608211213 以 destination=export ＋ altool 上傳，ASC 上顯示「內部」標記）。
  printf '    ⓘ testFlightInternalTestingOnly：本機 bundle 內看不到任何痕跡，這一關驗不到；\n'
  printf '      但它【已證實會傳達到 App Store Connect】——2026-08-21 的 build 202608211213\n'
  printf '      走的就是 destination=export ＋ altool 上傳，ASC 上該 build 標著「內部」。\n'
  printf '      上傳後順手到 TestFlight 清單瞄一眼那個標記即可（確認這顆包也帶到了）。\n'
  printf '      ⚠️ 它擋的是「散佈」不是「資料」：擋 external TestFlight／App Store，\n'
  printf '      擋不了被加進內部群組的人 —— 它不是 PHI 護欄，加人前仍要看 docs/TODO.md §V8。\n'
}

# ============================================================================
# --verify-only：跳過第 1e 關（簽章身分）與整個 build，只跑產物驗證。
# ============================================================================

if [[ -n "${verify_only}" ]]; then
  step "產物驗證（--verify-only，已跳過簽章檢查與 build）"
  # 刻意**不**把 build_number 傳進去：--verify-only 常拿來驗一顆舊產物或別人的包，
  # 而 BUILD_NUMBER 只要 export 過就會留在環境裡（--help 自己就列了那種用法），
  # 繼承下去會對舊產物報「有東西覆寫了 build number」——完全錯誤的歸因。
  # 要驗 build number 就明確指定：--verify-only=<x> --build-number=<y>。
  verify_artifact "${verify_only}" "${verify_expect_build}"
  printf '\n產物驗證跑完了。注意：--verify-only 只證明【這一段邏輯】會動，\n'
  printf '不代表這顆產物可以上傳（沒跑 analyze/test，也沒重新 build）。\n\n'
  exit 0
fi

# --- 1. 前置檢查 ------------------------------------------------------------

step "1/6 前置檢查"

# 1a. 必須有完整的 Xcode（不是只有 Command Line Tools）。
#     沒有這一關的話，第 5 關 xcodebuild 才會爆，而那時 analyze+test 已經跑完了。
xcodebuild -version >/dev/null 2>&1 || die \
  "xcodebuild 跑不起來 —— xcode-select 沒指到完整的 Xcode（多半只裝了 Command Line Tools）。" \
  "檢查：xcode-select -p    （要指到 /Applications/Xcode.app/Contents/Developer）" \
  "修法：sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" \
  "      並先開一次 Xcode 接受授權（sudo xcodebuild -license accept）。"
printf '    %s（%s）OK\n' \
  "$(xcodebuild -version 2>/dev/null | sed -n '1p' || true)" \
  "$(xcode-select -p 2>/dev/null || true)"

# 1b. 必須有 fvm，且解析出來的 Flutter 必須是 .fvmrc 釘的 3.41.3。
#     PATH 上的裸 flutter 是 homebrew 版（實測 3.47.0）；3.47 的 SPM 預設開，
#     會把 .flutter-plugins-dependencies 翻成 swift_package_manager_enabled=true，
#     連帶動到 ios/Podfile.lock。iOS build 一律走 `fvm flutter`。
if ! command -v fvm >/dev/null 2>&1; then
  die "找不到 fvm。" \
      "iOS build 必須用 .fvmrc 釘住的 Flutter ${required_flutter}，不能用 PATH 上的裸 flutter。" \
      "安裝：dart pub global activate fvm  （或 brew tap leoafarias/fvm && brew install fvm）"
fi

flutter_cmd=(fvm flutter)
# 這一行如果本機還沒有 .fvmrc 指定的那顆 SDK，fvm 會【自己下載約 205MB】，
# 而下面的 2>/dev/null 會把它的進度條整個吞掉——終端機會停在這裡好幾分鐘，
# 看起來跟當掉一模一樣。先講一聲。
printf '    偵測 Flutter 版本中…（若本機還沒有 %s，fvm 會先下載約 205MB SDK，\n' "${required_flutter}"
printf '     進度被吞掉了，這裡可能安靜停數分鐘，不是當掉）\n'
# ⚠️ 結尾的 `|| true` 是必要的，不是贅字：set -e 之下 `x="$(cmd | ...)"` 這種
#    「整行只有一個賦值」的語句會直接繼承指令的離開碼。fvm 那端一旦非 0
#    （沒裝 SDK、fvm 壞掉、不在 fvm 專案裡），整個賦值失敗 → 腳本【當場 exit 1】，
#    底下寫得很用心的 die 訊息永遠印不出來，使用者只會看到 banner 加一行
#    「==> 1/6 前置檢查」然後什麼都沒有。加了 `|| true` 才會落到
#    ${installed_flutter:-偵測不到} 那個分支，把真正的修法印出來。
installed_flutter="$("${flutter_cmd[@]}" --version 2>/dev/null | sed -n '1s/^Flutter \([^ ]*\).*/\1/p')" || true
if [[ "${installed_flutter:-}" != "${required_flutter}" ]]; then
  extra=""
  case "${installed_flutter:-}" in
    3.4[4-9].*|3.[5-9]*.*|4.*)
      extra="看起來你用到 homebrew／PATH 上的那顆 flutter 了（實測是 3.47.0）。"
      ;;
    "")
      extra='fvm flutter --version 完全沒有輸出或非 0 離開——先單獨跑一次看它說什麼。'
      ;;
  esac
  die "Flutter 版本不對：預期 ${required_flutter}，實際 ${installed_flutter:-偵測不到}。" \
      "${extra}" \
      "確認 ${app_dir}/.fvmrc 釘的版本，並執行：fvm install ${required_flutter}" \
      "所有指令都要加 fvm 前綴（fvm flutter ...），不要直接打 flutter。"
fi
printf '    Flutter %s（fvm）OK\n' "${installed_flutter}"

# 1c. ExportOptions.plist 必須存在且語法正確。
[[ -f "${export_options}" ]] || die "找不到 ${export_options}" \
  "這支腳本靠它決定 method=app-store-connect / signingStyle=automatic / teamID。"
plutil -lint "${export_options}" >/dev/null || die "${export_options} 語法有問題（plutil -lint 不過）。"
printf '    ExportOptions.plist OK\n'

# 1d. App Icon / LaunchImage 資產齊全（少一張，actool 就不會產 Assets.car，
#     上傳後 App Store Connect 會以缺圖示退件）。
if [[ ! -x "${icon_check_python}" ]]; then
  die "找不到 ${icon_check_python}" \
      "圖示檢查需要 backend 的 venv。請先建立：" \
      "  cd ${repo_dir}/backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt" \
      "  ${icon_check_pip} install Pillow      # ⚠️ requirements.txt 沒有列 Pillow，要另外裝"
fi
# ⚠️ 先探測 Pillow 再跑 --check。gen_app_icons.py 是在 module 頂層 `from PIL import Image`，
#    venv 缺 Pillow 時它會以 ModuleNotFoundError exit 1 —— 跟「圖示缺檔」同樣是 exit 1，
#    分不出來。而 backend/requirements.txt 【沒有】列 Pillow（自己 grep 可證），
#    所以任何一次重建 venv 之後都必然缺。不分開探測的話，診斷會是「圖示資產不齊全」，
#    照著去跑 gen_app_icons.py 又會以同一個原因再爆一次，把人關進死路。
#    （這裡刻意不去改 requirements.txt：Pillow 是打包工具的相依，不是後端執行期相依。）
if ! "${icon_check_python}" -c 'import PIL' >/dev/null 2>&1; then
  die "backend 的 venv 裡沒有 Pillow，圖示檢查根本跑不起來（這不是圖示壞掉）。" \
      "backend/requirements.txt 【沒有】列 Pillow，重建 venv 之後一定會缺。" \
      "修法：${icon_check_pip} install Pillow" \
      "（不要改 requirements.txt —— Pillow 是這支打包工具的相依，不是後端執行期相依。）"
fi
"${icon_check_python}" tool/gen_app_icons.py --check || die \
  "App Icon 資產不齊全（或 1024 marketing icon 帶了 alpha 通道）。" \
  "（Pillow 已在上一步確認過，所以這次是真的缺圖或圖不合規。）" \
  "修法：cd ${app_dir} && ${icon_check_python} tool/gen_app_icons.py"
printf '    App Icon 資產 OK\n'

# 1e. 簽章身分。這是最常擋人的一關，訊息要能直接照做。
#     ⚠️ 必須連 Team ID 一起比對：只比對「有沒有 Apple Distribution」的話，
#     使用者若在別的 team 也有 distribution 憑證就會被放行，然後白跑
#     analyze + test + archive，最後才在 exportArchive 那一步爆掉。
identities="$(security find-identity -v -p codesigning 2>/dev/null || true)"
if ! grep -qE "\"(Apple Distribution|iPhone Distribution):[^\"]*\\(${team_id}\\)\"" <<<"${identities}"; then
  found_dev=0
  found_dist_other_team=0
  grep -qE '"(Apple Development|iPhone Developer):' <<<"${identities}" && found_dev=1
  grep -qE '"(Apple Distribution|iPhone Distribution):' <<<"${identities}" && found_dist_other_team=1

  hint="鑰匙圈裡一個 codesigning 身分都沒有。"
  [[ "${found_dev}" -eq 1 ]] && hint="鑰匙圈裡只有 Development 憑證，沒有 Distribution 憑證。"
  [[ "${found_dist_other_team}" -eq 1 ]] && hint="鑰匙圈裡有 Distribution 憑證，但【不屬於 team ${team_id}】——那顆簽不出這個 App。"

  die "找不到屬於 team ${team_id} 的 Apple Distribution／iPhone Distribution 簽章身分，無法產出可上傳的 .ipa。" \
      "${hint}" \
      "" \
      "怎麼修：" \
      "  1) 打開 Xcode → Settings… → Accounts → 左下角 ＋ → Apple ID，登入。" \
      "  2) 選到帳號後，右側 team 清單要看到 Team ID ${team_id}，" \
      "     而且該 team 名稱後面【不能】標 (Personal Team)。" \
      "     標了 (Personal Team) 表示是免費帳號 —— 免費帳號永遠拿不到 Distribution" \
      "     憑證，也上不了 TestFlight，必須加入付費的 Apple Developer Program。" \
      "  3) 按該 team 的 Manage Certificates… → ＋ → Apple Distribution。" \
      "  4) 回來重跑本腳本；驗證指令：security find-identity -v -p codesigning" \
      "" \
      "（想先驗第 6 關的產物驗證邏輯而不等憑證，可以跑：" \
      "  tool/build_ios_testflight.sh --verify-only=build/ios/archive/Runner.xcarchive/Products/Applications/Runner.app" \
      "  archive 內那顆是 development 簽章，會在 aps-environment 那一關以" \
      "  「development 不是 production」失敗，那是預期的；重點是控制流會被實際走過一遍。）" \
      "" \
      "目前 security find-identity -v -p codesigning 的輸出：" \
      "${identities:-（空）}"
fi
printf '    簽章身分 OK（team %s）：\n%s\n' "${team_id}" "$(sed 's/^/      /' <<<"${identities}")"

# --- 2. Build number --------------------------------------------------------

step "2/6 決定 build number"

# TestFlight 要求：在同一個 CFBundleShortVersionString 底下，CFBundleVersion
# 必須單調遞增，重複的 build number 會被 App Store Connect 直接拒收。
#
# 為什麼不用 pubspec.yaml 的 `version: 1.0.0+1`？
#   那個 +1 是寫死的常數，本專案沒有任何遞增機制。用它的話第二次上傳一定被拒，
#   而且失敗會發生在「上傳完、處理中」的階段，浪費一輪來回。
#
# 為什麼用 UTC 時間戳？
#   單調、免狀態檔、免讀 App Store Connect API。用 UTC 而不是本地時間，
#   是為了避免夏令時間或跨時區作業時 build number 倒退（倒退＝被拒）。
if [[ -z "${build_number}" ]]; then
  build_number="$(date -u +%Y%m%d%H%M)"
fi

# CFBundleVersion 只能是「最多三段、句點分隔的非負整數」。
if [[ ! "${build_number}" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]]; then
  die "build number «${build_number}» 不合法。" \
      "CFBundleVersion 只能是最多三段、句點分隔的非負整數（例：202608211930 或 2026.0821.1930）。"
fi
printf '    build number = %s（UTC 時間戳）\n' "${build_number}"

# 備援：萬一 App Store Connect 嫌 12 位數整數太大而退件，改用
#   --build-number="$(date -u +%Y.%m%d.%H%M)"  → 2026.0821.1930
# 同樣單調遞增，但每一段都是小整數。
#
# ⚠️⚠️ 兩種格式【不可混用】。CFBundleVersion 是【逐段】比較的，不是當成一個數字比：
#   `2026.0821.1930` 的首段是 2026，而 `202608211930` 只有一段、值 202608211930。
#   2026 < 202608211930 → 從 12 位數格式換成三段格式，會被判定為【倒退】而拒收，
#   而且是永久的（同一個 CFBundleShortVersionString 下沒有辦法「往回填」）。
#   換格式之前必須先確認：這個版本號底下【尚未用另一種格式上傳過任何一版】。
#   已經傳過的話，唯一的出路是把 pubspec.yaml 的 version 往上帶
#   （＝換一個 CFBundleShortVersionString，重新開一條 build number 序列）。

# --- 3. dart-define 與安全斷言 ----------------------------------------------

step "3/6 檢查後端位址"

# 沒帶 dart-define 的包，程式碼裡的預設值是 http://localhost:8000/api/v1 —
# 裝到手機上不但連不到後端，還會被 iOS 的 ATS（App Transport Security）直接擋掉
# 明文 http，症狀是「畫面轉圈然後什麼都沒有」，非常難從現場除錯。
api_base="${API_BASE:-${PROD_API_BASE}}"
ws_base="${WS_BASE:-${PROD_WS_BASE}}"

# ⚠️ 這裡刻意【不用子字串 glob】。舊版用 *localhost* / *"http://"* 比對整個 URL，
#    兩邊都會誤判：
#      https://localhost-staging.example.com  → 被當成本機（其實是正常的遠端主機）
#      https://x/?redirect=http://y           → 被當成明文（其實 scheme 是 https）
#    正確做法是先把 scheme 剝掉、取出 host，再對 host 做精確比對；
#    scheme 一律用【前綴】比對。
assert_remote_url() {
  local name="$1" raw="$2" scheme="$3"

  # trim 前後空白：`API_BASE=" "` 在舊版能通過 -n 檢查，然後把一個空白字串
  # 當成 URL 一路帶進 dart-define。
  local value="${raw#"${raw%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  [[ -n "${value}" ]] || die "${name} 是空的（或只有空白字元）。"

  local rest
  case "${value}" in
    "${scheme}://"*)
      rest="${value#"${scheme}://"}"
      ;;
    http://*|ws://*)
      die "${name} 用了明文協定（${value}）。" \
          "iOS ATS 會擋掉明文 http/ws；只允許 https:// 與 wss://。"
      ;;
    *://*)
      die "${name} 必須以 ${scheme}:// 開頭，實際是：${value}"
      ;;
    *)
      die "${name} 不是一個絕對 URL（沒有 scheme）：${value}" \
          "預期形如 ${scheme}://host/path。"
      ;;
  esac

  # 從 authority 取出 host：剝掉 path / query / fragment / userinfo，
  # 再處理 [IPv6] 字面量與 :port。
  local authority="${rest%%/*}"
  authority="${authority%%\?*}"
  authority="${authority%%#*}"
  authority="${authority##*@}"

  local host
  case "${authority}" in
    \[*\]*)
      host="${authority#\[}"
      host="${host%%\]*}"
      ;;
    *)
      host="${authority%%:*}"
      ;;
  esac

  [[ -n "${host}" ]] || die "${name} 解析不出 host：${value}"

  # DNS 主機名大小寫不敏感（LOCALHOST 一樣解析到 127.0.0.1），先轉小寫再比。
  # bash 3.2 沒有 ${x,,}，用 tr。
  local host_lc
  host_lc="$(printf '%s' "${host}" | tr '[:upper:]' '[:lower:]')"

  case "${host_lc}" in
    localhost|*.localhost|127.*|0.0.0.0|0177.*|::1|::|::ffff:127.*)
      die "${name} 的 host 指向本機（host = ${host}）。" \
          "裝到 iPhone 上的包不可能連得到你的 localhost；請用生產後端位址。"
      ;;
  esac
}

assert_remote_url "API_BASE" "${api_base}" "https"
assert_remote_url "WS_BASE"  "${ws_base}"  "wss"
printf '    API_BASE = %s\n    WS_BASE  = %s\n' "${api_base}" "${ws_base}"

# --- 4. 靜態檢查與測試 ------------------------------------------------------

step "4/6 analyze 與 test"

"${flutter_cmd[@]}" pub get --enforce-lockfile

if [[ "${skip_checks}" -eq 1 ]]; then
  printf '    已指定 --skip-checks，略過 analyze 與 test（僅供除錯打包管道時使用）。\n'
else
  # 專案慣例：analyze 連 info 級訊息都算失敗（flutter analyze 本身就是這個行為）。
  "${flutter_cmd[@]}" analyze --no-pub
  "${flutter_cmd[@]}" test --no-pub
fi

# --- 5. 打包 ----------------------------------------------------------------

step "5/6 flutter build ipa"

# ⚠️ 已知坑（2026-08-21 實測）：在這台機器【第一次】用某把新建的 Distribution 私鑰
#    簽章時，macOS 會跳一個鑰匙圈授權對話框問「是否允許 codesign 使用這把私鑰」。
#    腳本是非互動情境，對話框沒被按到，codesign 就直接失敗 → export 失敗。
#    而且 flutter build ipa 只會轉述被截斷的訊息（見下面找不到 .ipa 時的提示），
#    真正的原因不會出現在畫面上。看到 export 失敗先看螢幕上有沒有那個對話框。
printf '    ⓘ 若螢幕上跳出鑰匙圈授權對話框（要求允許 codesign 使用私鑰），\n'
printf '      請按「一律允許」/「允許」——沒按到的話 export 會失敗，而錯誤訊息會誤導。\n'

rm -rf "${ipa_dir}"
"${flutter_cmd[@]}" build ipa \
  --release \
  --no-pub \
  --build-number="${build_number}" \
  --export-options-plist="${export_options}" \
  --dart-define="API_BASE=${api_base}" \
  --dart-define="WS_BASE=${ws_base}"

# --- 6. 產物驗證 ------------------------------------------------------------
#
# 這一段是整支腳本的重點：上傳一次要等 App Store Connect 處理好幾分鐘，
# 能在本機測出來的問題就不要拿去讓 Apple 退件。

step "6/6 產物驗證"

ipa_path=""
while IFS= read -r candidate; do
  ipa_path="${candidate}"
  break
done < <(find "${ipa_dir}" -maxdepth 1 -name '*.ipa' -type f 2>/dev/null | sort)

[[ -n "${ipa_path}" ]] || die "打包結束了，但 ${ipa_dir} 底下找不到 .ipa。" \
  "通常代表 xcodebuild -exportArchive 失敗；往上翻 build 輸出找 'Export' 段落的錯誤。" \
  "⚠️ 注意 flutter build ipa 在 export 失敗時【仍然回傳 exit 0】——" \
  "   「.ipa 存不存在」是唯一的判準，所以這一關才用 find 而不是看離開碼。" \
  "" \
  "＝＝ 第一次在這台機器打真簽章包，最可能是這個原因（2026-08-21 實測）＝＝" \
  "  codesign 第一次使用剛建好的 Distribution 私鑰時，macOS 會跳鑰匙圈授權對話框；" \
  "  腳本是非互動情境，沒人按 → codesign 當場失敗 → export 失敗。" \
  "  而 flutter 轉述的錯誤只有：" \
  "    exportArchive codesign command failed (... Flutter.framework: replacing existing signature" \
  "  ⚠️ 「replacing existing signature」是 codesign 的【正常訊息，不是失敗原因】，" \
  "     真正的原因被 Flutter 截掉了 —— 不要照著這句去查 framework 簽章。" \
  "  修法：把對話框按「允許」（或到「鑰匙圈存取」把該私鑰的存取控制設成一律允許），" \
  "  然後【不用整包重跑】，直接對已經產好的 archive 補做 export：" \
  "    cd ${app_dir} && xcodebuild -exportArchive -allowProvisioningUpdates \\" \
  "      -archivePath build/ios/archive/Runner.xcarchive \\" \
  "      -exportOptionsPlist ios/ExportOptions.plist \\" \
  "      -exportPath build/ios/ipa" \
  "  （若 xcodebuild 抱怨 export path 已存在，先 rm -rf build/ios/ipa 再跑；" \
  "    那個目錄此刻只有失敗留下的 log，沒有 .ipa —— 上面這一關就是這樣判定的。）" \
  "  export 成功後再跑：tool/build_ios_testflight.sh --verify-only=build/ios/ipa/<那顆>.ipa" \
  "  （要一併驗 build number 就加 --build-number=${build_number}）"

verify_artifact "${ipa_path}" "${build_number}"

# --- 收尾：接下來要做什麼 ---------------------------------------------------

cat <<EOF

────────────────────────────────────────────────────────────────────────────
 打包完成

   .ipa                          ${ipa_path}
   Bundle ID                     ${bundle_id}
   CFBundleShortVersionString    ${short_version}
   CFBundleVersion               ${bundle_version}
   API_BASE                      ${api_base}
   WS_BASE                       ${ws_base}
────────────────────────────────────────────────────────────────────────────

接下來：上傳到 App Store Connect

  A) xcrun altool（2026-08-21 已用這條實際傳成功，建議走這條）
     App Store Connect API key 已建好（.p8 在 ~/.appstoreconnect/private_keys/，
     Key ID／Issuer ID 刻意不寫進這個公開 repo，取得位置見
     docs/ios_release_settings.md）。先驗再傳：

       export ASC_API_KEY_ID=<Key ID>          # ＝ .p8 檔名 AuthKey_<這一段>.p8
       export ASC_API_ISSUER_ID=<Issuer ID>    # ASC → 使用者與存取權限 → 整合
       xcrun altool --validate-app -f "${ipa_path}" -t ios \\
         --api-key "\$ASC_API_KEY_ID" --api-issuer "\$ASC_API_ISSUER_ID"
       xcrun altool --upload-app -f "${ipa_path}" -t ios \\
         --api-key "\$ASC_API_KEY_ID" --api-issuer "\$ASC_API_ISSUER_ID"

     --validate-app 回 "VERIFY SUCCEEDED with no errors" 之後再 --upload-app。
     成功會回一組 Delivery UUID；傳完幾分鐘內 ASC 會跑完自動處理。
     （notarytool 是 macOS 公證用的，跟 iOS 上架無關，不要拿來傳 .ipa。）
     （不要重用 ../firebase-secrets/ 底下那把 APNs .p8（在 repo 之外） —— 那是推播金鑰，
       不是 App Store Connect API key，用途與權限都不同。）

  B) Transporter.app（API key 不能用時的備援）
     Mac App Store 免費下載 → 開啟 → 用 Apple ID 登入 →
     把上面那顆 .ipa 拖進去 → Deliver。
     它傳的就是本腳本剛剛驗過的那一顆位元組。

  C) Xcode Organizer（不建議）
     Xcode → Window → Organizer → Archives → 選今天這包 → Distribute App。
     ⚠️ Organizer 會【自己重新 export 一次】，不會用本腳本驗過的那顆 .ipa，
        整份 ExportOptions.plist（含 testFlightInternalTestingOnly、
        manageAppVersionAndBuildNumber）一起被繞過，而且沒有任何機制會發現
        —— 你會拿到一顆沒經過第 6 關、設定也可能不同的包。
        A、B 兩條都不能用的時候才走這條，且走了就要到
        App Store Connect 上逐項核對 build number 與「內部」標示。

上傳之後

  1. build 仍要通過 App Store Connect 的自動處理（簽章、entitlements、
     圖示、出口合規），通常數分鐘。實測：2026-08-21 的 build 202608211213
     傳完後順利跑完自動處理，狀態變成「準備測試」。
  2. 出口合規：Info.plist 已帶 ITSAppUsesNonExemptEncryption=false（第 6d 關會擋），
     實測【不會】出現 "Missing Compliance"，不必再到網頁回答出口合規問卷。
  3. 內部測試（internal testing）不需要 Beta App Review；外部測試才需要。
  4. 內部測試員必須先是 App Store Connect 的使用者：先寄「使用者邀請」信、
     對方建帳號並完成 2FA，這與 TestFlight 那封邀請信是兩回事。
  5. ExportOptions.plist 的 testFlightInternalTestingOnly=true
     【2026-08-21 已證實生效】：build 202608211213 走的就是 destination=export
     ＋ altool 上傳，ASC 的 TestFlight 建置版本清單上該列標著「內部」。
     （本腳本第 6 關仍然檢查不到它——bundle 裡沒有痕跡——所以上傳後順手
       到 TestFlight 清單瞄一眼那個標記，確認這一顆也帶到了。）
     ⚠️ 但它擋的是【散佈】不是【資料】，【不是 PHI 護欄】：
       - 它擋 external TestFlight 與 App Store，
         擋不了任何一個被你加進「內部」測試群組的人；
       - 上面的路徑 C（Organizer）會整份繞過它。
     → 旗標有效 ≠ PHI 有護欄。加第 2 個測試人員前仍必須先走完
       docs/TODO.md §V8 的前置條件，這一條完全沒有因為證實而放寬。
  6. TestFlight build 90 天到期且無法延長。內測要持續的話，
     請排「每 90 天至少重傳一版」。
  7. TestFlight App 本身要求 iOS 16+，但本專案 IPHONEOS_DEPLOYMENT_TARGET = 15.0
     → iOS 15 的裝置永遠裝不到測試包（是測試者裝置門檻，不是上架門檻）。

EOF

print_data_risk_banner
