#!/usr/bin/env bash
# =============================================================================
# 一鍵產出產品介紹影片：boot 模擬器 → 開錄 → 跑 walkthrough → 停錄 → 剪成 60 秒
#
# 為什麼要「對齊時間軸」而不是直接把整段錄影丟去剪：
#   `flutter test integration_test/...` 會先 build＋install，那段時間模擬器停在
#   桌面，錄進去就是幾十秒的空畫面。所以這支會記錄三個時間點——
#     T0 = 開始錄影
#     T1 = walkthrough 真正開始（靠 Dart 端印出的 DEMO_MARK_START 那行）
#     T2 = walkthrough 結束
#   然後把 (T1-T0) 當 --trim-start、(T2-T1) 當 --trim-duration 交給 make_demo_video.sh。
#   Dart 那端若沒印 marker，退回「整段都要」並在最後提醒使用者自己給 --trim-start。
#
# 用法：
#   tool/record_demo.sh                          # 用預設模擬器與本機後端
#   tool/record_demo.sh --device <udid> --api http://127.0.0.1:8000/api/v1
#   tool/record_demo.sh --output ~/Desktop/demo.mp4   # 直接輸出到桌面
#   tool/record_demo.sh --keep-raw                    # 保留原始錄影不刪
# =============================================================================
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(cd "${app_dir}/.." && pwd)"
out_dir="${app_dir}/build/demo"
device=""; keep_raw=0; final_override=""
api_base="http://127.0.0.1:8000/api/v1"
ws_base="ws://127.0.0.1:8000/api/v1/ws"
target_seconds=60
test_target="integration_test/demo_walkthrough_test.dart"
# walkthrough 需要的帳號（本機 demo 專用，不是任何真實帳號）
kiosk_email="${KIOSK_EMAIL:-demo.patient@example.com}"
kiosk_password="${KIOSK_PASSWORD:-Demo1234}"
doctor_email="${DEMO_DOCTOR_EMAIL:-demo.doctor@example.com}"
doctor_password="${DEMO_DOCTOR_PASSWORD:-Demo1234}"
doctor_name="${DEMO_DOCTOR_NAME:-林醫師}"

die() { printf '\n[record_demo] 錯誤: %s\n' "$*" >&2; exit 1; }
say() { printf '[record_demo] %s\n' "$*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) device="$2"; shift 2 ;;
    --api) api_base="$2"; shift 2 ;;
    --ws) ws_base="$2"; shift 2 ;;
    --seconds) target_seconds="$2"; shift 2 ;;
    --target) test_target="$2"; shift 2 ;;
    --output) final_override="$2"; shift 2 ;;
    --keep-raw) keep_raw=1; shift ;;
    *) die "不認得的參數: $1" ;;
  esac
done

# ── 前置檢查 ────────────────────────────────────────────────────────────────
command -v xcrun   >/dev/null || die "找不到 xcrun（需要 Xcode command line tools）"
command -v ffmpeg  >/dev/null || die "找不到 ffmpeg（brew install ffmpeg）"
command -v fvm     >/dev/null || die "找不到 fvm——本專案一律用 fvm flutter，見 CLAUDE.md 鐵律"
[[ -f "${app_dir}/${test_target}" ]] || die "找不到 walkthrough：${test_target}"
[[ -x "${app_dir}/tool/make_demo_video.sh" ]] || die "找不到 tool/make_demo_video.sh"

# ⚠️ 只准打本機後端。這支會被重複執行，打正式環境等於每跑一次就建真場次、
#    對四支真手機發推播（2026-09-09 拍板）。
case "${api_base}" in
  *railway.app*|*https://*) die "API_BASE 指向遠端（${api_base}）。這支只准打本機後端。" ;;
esac

curl -sf --max-time 5 "${api_base}/health" >/dev/null \
  || die "本機後端沒有回應：${api_base}/health（先起 docker compose up -d postgres redis 與 uvicorn）"
say "本機後端 OK：${api_base}"
# report_ready 那則通知是 Celery 產生的；沒有 worker，快速開單頁那一段會等不到東西。
pgrep -f "celery -A app.tasks" >/dev/null \
  || die "Celery worker 沒在跑——快速開單那段會等不到 report_ready。請先起：backend/venv/bin/celery -A app.tasks.celery_app worker -l info"
say "Celery worker OK"

# ── 選模擬器 ────────────────────────────────────────────────────────────────
if [[ -z "${device}" ]]; then
  device="$(xcrun simctl list devices available -j \
    | "${repo_dir}/backend/venv/bin/python" -c '
import json,sys
d=json.load(sys.stdin)["devices"]
best=None
for runtime,devs in d.items():
    if "iOS" not in runtime: continue
    for x in devs:
        if not x.get("isAvailable"): continue
        if "iPhone" not in x["name"]: continue
        # 已 boot 的優先，其次挑名字最新的 iPhone
        score=(x["state"]=="Booted", x["name"])
        if best is None or score>best[0]: best=(score,x["udid"],x["name"])
print(best[1] if best else "")')"
  [[ -n "${device}" ]] || die "找不到可用的 iPhone 模擬器"
fi
name="$(xcrun simctl list devices -j | "${repo_dir}/backend/venv/bin/python" -c "
import json,sys
d=json.load(sys.stdin)['devices']
print(next((x['name'] for v in d.values() for x in v if x['udid']=='${device}'), '${device}'))")"
say "模擬器：${name}（${device}）"

# ⚠️ 一律先 shutdown 再 boot，不可以沿用已開著的模擬器。
#    實測（2026-09-09，重現兩次）：同一顆開著的模擬器連跑第二次，100% 卡在 openMic，
#    backend 連一次 WS 握手都收不到。這發生在 Dart 拿到控制權之前，測試碼裡救不了。
say "重開模擬器（沿用已開著的會卡在 openMic）…"
xcrun simctl shutdown "${device}" 2>/dev/null || true
sleep 2
xcrun simctl boot "${device}"
open -a Simulator --args -CurrentDeviceUDID "${device}" || true
xcrun simctl bootstatus "${device}" -b >/dev/null 2>&1 || true
# 預先授權麥克風，免得跑到問診頁才跳系統權限對話框擋住畫面
xcrun simctl privacy "${device}" grant microphone com.guvoice.guVoice 2>/dev/null || true
# 錄影前把狀態列固定成乾淨樣式（9:41、滿格訊號），避免每次錄出來的時間不一樣
xcrun simctl status_bar "${device}" override --time "9:41" --batteryState charged --batteryLevel 100 \
  --cellularMode active --cellularBars 4 --wifiMode active --wifiBars 3 2>/dev/null || true

mkdir -p "${out_dir}"
raw="${out_dir}/raw.mov"; log="${out_dir}/walkthrough.log"
# 預設丟在 build/demo/，可用 --output 指定（例如 ~/Desktop/UroSense_demo.mp4）
final="${final_override:-${out_dir}/demo.mp4}"
mkdir -p "$(dirname "${final}")"
rm -f "${raw}" "${log}" "${final}"

now() { "${repo_dir}/backend/venv/bin/python" -c 'import time;print(f"{time.time():.3f}")'; }

# ── 開錄 ────────────────────────────────────────────────────────────────────
say "開始錄影 → ${raw}"
xcrun simctl io "${device}" recordVideo --codec h264 --force "${raw}" &
rec_pid=$!
trap 'kill -INT ${rec_pid} 2>/dev/null || true' EXIT
sleep 2
t0="$(now)"

# ── 跑 walkthrough ──────────────────────────────────────────────────────────
say "執行 walkthrough：${test_target}"
set +e
( cd "${app_dir}" && fvm flutter test "${test_target}" -d "${device}" \
    --dart-define="API_BASE=${api_base}" --dart-define="WS_BASE=${ws_base}" \
    --dart-define="KIOSK_EMAIL=${kiosk_email}" --dart-define="KIOSK_PASSWORD=${kiosk_password}" \
    --dart-define="DEMO_DOCTOR_EMAIL=${doctor_email}" \
    --dart-define="DEMO_DOCTOR_PASSWORD=${doctor_password}" \
    --dart-define="DEMO_DOCTOR_NAME=${doctor_name}" ) 2>&1 | tee "${log}"
test_rc=${PIPESTATUS[0]}
set -e
t2="$(now)"

# ── 停錄 ────────────────────────────────────────────────────────────────────
say "停止錄影"
kill -INT "${rec_pid}" 2>/dev/null || true
wait "${rec_pid}" 2>/dev/null || true
trap - EXIT
xcrun simctl status_bar "${device}" clear 2>/dev/null || true

[[ -s "${raw}" ]] || die "錄影檔是空的：${raw}"
[[ ${test_rc} -eq 0 ]] || say "⚠️ walkthrough 回傳非 0（${test_rc}）——影片照剪，但內容可能不完整，看 ${log}"

# ── 對齊時間軸 ──────────────────────────────────────────────────────────────
# Dart 端若印了 DEMO_MARK_START，用它算出 walkthrough 真正開始的秒數。
mark_line="$(grep -n "DEMO_MARK_START" "${log}" | head -1 || true)"
trim_args=()
if [[ -n "${mark_line}" ]]; then
  # 用 log 檔的 mtime 推不準，改用「跑完的總長」與 marker 在 log 的相對位置估算不可靠——
  # 所以 Dart 端約定要印出 epoch 秒：`DEMO_MARK_START <epoch>`。
  mark_epoch="$(sed -E 's/.*DEMO_MARK_START[[:space:]]+([0-9.]+).*/\1/' <<<"${mark_line}")"
  if [[ "${mark_epoch}" =~ ^[0-9.]+$ ]]; then
    start_off="$("${repo_dir}/backend/venv/bin/python" -c "print(max(0.0, ${mark_epoch} - ${t0}))")"
    dur="$("${repo_dir}/backend/venv/bin/python" -c "print(max(1.0, ${t2} - ${mark_epoch}))")"
    trim_args=(--trim-start "${start_off}" --trim-duration "${dur}")
    say "對齊：build 花了 ${start_off}s，walkthrough 長 ${dur}s"
  fi
fi
if [[ ${#trim_args[@]} -eq 0 ]]; then
  say "⚠️ log 裡沒有 DEMO_MARK_START，整段錄影都會進剪輯（含 build 的空畫面）。"
  say "   若成品前面有一段桌面畫面，用 --trim-start 手動指定，或請 walkthrough 印出 marker。"
fi

# ── 剪成成品 ────────────────────────────────────────────────────────────────
say "後製 → ${final}"
"${app_dir}/tool/make_demo_video.sh" \
  --input "${raw}" \
  --config "${app_dir}/tool/demo_captions.example.json" \
  --output "${final}" \
  --target-seconds "${target_seconds}" \
  ${trim_args[@]+"${trim_args[@]}"}

[[ ${keep_raw} -eq 1 ]] || { rm -f "${raw}"; say "已刪除原始錄影（--keep-raw 可保留）"; }
say "完成：${final}"
