#!/usr/bin/env bash
#
# make_demo_video.sh
#
# 把 iOS 模擬器錄下來的原始 .mov 剪成約 60 秒、1080x1920 直式、
# H.264 MP4 的產品介紹影片，並疊上中文字卡。
#
# ============================================================
# 為什麼不用 ffmpeg 的 drawtext / subtitles / ass？
# ------------------------------------------------------------
# 這台機器裝的 ffmpeg（9.0.1，Homebrew）編譯時**沒有帶 libfreetype
# / libass**，所以 drawtext、subtitles、ass 這三個濾鏡完全用不了
# （filter not found，直接 fail）。
# 因此中文字卡改成兩階段做：
#   1) demo_captions.py 用 Pillow 把每張字卡（半透明圓角底＋標題＋
#      副標）預先渲染成跟畫面等大、四周透明的 PNG。
#   2) 這支腳本只用 ffmpeg 的 `overlay` 濾鏡把 PNG 疊到影片上，
#      用 enable='between(t,a,b)' 控制出現的時間區間。
# 全程只用這些「有裝」的濾鏡：overlay、zoompan、xfade、scale、fps、
# format、trim、setpts、concat、fade。下一個人要加字卡效果，也請
# 走這條路，不要再試 drawtext。
#
# ------------------------------------------------------------
# 字卡為什麼綁「階段標記」而不是設定檔裡寫死的秒數？
# ------------------------------------------------------------
# walkthrough 每次跑的長度會變（LLM 快慢，實測 2:14 vs 2:21），這支
# 腳本又會把來源影片變速壓成固定的 --target-seconds → 變速倍率
# （下面算的 SPEED_FACTOR）跟著每次不同 → 同一組寫死秒數的字卡，
# 换一次錄影就對到不同畫面。
#
# 解法：record_demo.sh 會把 Dart 端印的 `DEMO_MARK_STAGE <id> <epoch>`
# 換算成「相對 DEMO_MARK_START 的秒數偏移」寫成 --stages 那份
# stages.tsv（一行 `stage-id<TAB>offset`）。設定檔裡的字卡若寫
# `"stage": "<id>"`（而不是 `"start"/"end"`），這支腳本就用
#     final_t = stage_offset / SPEED_FACTOR
# 換算成成品影片裡的秒數——因為 --trim-start 已經把來源影片的原點
# 移到 DEMO_MARK_START，offset 直接除以變速倍率就是成品時間。結束時間
# 取「下一個有字卡的 stage 的 final_t」跟「自己的 final_t + duration
# （設定檔給，預設 5 秒）」兩者較小值，並且不超過影片總長。
#
# 品牌卡（片頭/片尾）沒有對應的 UI 階段，仍然用舊式的固定
# "start"/"end" 秒數——兩種寫法可以在同一份設定檔裡混用。字卡引用
# 了 --stages 裡不存在的 stage id 會直接 die（並印出目前有哪些
# 可用的 id），故意不安靜跳過，因為安靜跳過＝字卡默默消失，正是要
# 防的問題。
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 產字卡用的 Python：優先用 backend 的 venv（已確認裝了 Pillow 12.3.0），
# 找不到就退回系統 python3。
DEFAULT_PYTHON="/Users/chun/Desktop/chatgu/gu-voice/backend/venv/bin/python"
if [[ -x "${DEFAULT_PYTHON}" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-${DEFAULT_PYTHON}}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

die() {
  echo "[make_demo_video] 錯誤: $*" >&2
  exit 1
}

log() {
  echo "[make_demo_video] $*"
}

usage() {
  cat <<EOF
用法:
  $(basename "$0") --input <raw.mov> --config <captions.json> --output <demo.mp4> \\
                    [--target-seconds 60] [--trim-start SEC] [--trim-duration SEC] \\
                    [--stages stages.tsv] [--work-dir DIR]

參數:
  --input          模擬器錄下來的原始影片 (.mov)
  --config         字卡時間軸設定 (JSON)，格式參考 demo_captions.example.json
  --output         輸出的 MP4 路徑
  --target-seconds 目標長度（秒），預設 60
  --trim-start     可選，若原片太長，先從第幾秒開始擷取
  --trim-duration  可選，配合 --trim-start，擷取幾秒
  --stages         可選，record_demo.sh 產生的 stages.tsv（stage-id<TAB>offset，
                    offset 是相對 DEMO_MARK_START 的秒數）。設定檔裡用
                    "stage" 綁定的字卡要靠這份檔案換算成成品秒數；沒給、
                    但設定檔裡有字卡用了 "stage"，會直接失敗。
  --work-dir       可選，暫存字卡 PNG 的目錄；預設用 mktemp 建立臨時目錄
EOF
}

# ---------------------------------------------------------------
# 參數解析
# ---------------------------------------------------------------
INPUT=""
CONFIG=""
OUTPUT=""
TARGET_SECONDS="60"
TRIM_START=""
TRIM_DURATION=""
WORK_DIR=""
STAGES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) INPUT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --target-seconds) TARGET_SECONDS="$2"; shift 2 ;;
    --trim-start) TRIM_START="$2"; shift 2 ;;
    --trim-duration) TRIM_DURATION="$2"; shift 2 ;;
    --stages) STAGES="$2"; shift 2 ;;
    --work-dir) WORK_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知參數: $1（用 --help 看用法）" ;;
  esac
done

[[ -n "$INPUT" ]] || { usage; die "缺少 --input"; }
[[ -n "$CONFIG" ]] || { usage; die "缺少 --config"; }
[[ -n "$OUTPUT" ]] || { usage; die "缺少 --output"; }
[[ -f "$INPUT" ]] || die "找不到輸入檔: $INPUT"
[[ -f "$CONFIG" ]] || die "找不到設定檔: $CONFIG"
[[ -z "$STAGES" || -f "$STAGES" ]] || die "找不到 --stages 檔案: $STAGES"

command -v ffmpeg >/dev/null 2>&1 || die "找不到 ffmpeg"
command -v ffprobe >/dev/null 2>&1 || die "找不到 ffprobe"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "找不到 python: $PYTHON_BIN（可用 PYTHON_BIN 環境變數指定）"

WIDTH=1080
HEIGHT=1920

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d /tmp/demo_video.XXXXXX)"
  CLEANUP_WORK_DIR=1
else
  mkdir -p "$WORK_DIR"
  CLEANUP_WORK_DIR=0
fi
log "工作目錄: $WORK_DIR"

cleanup() {
  if [[ "${CLEANUP_WORK_DIR:-0}" == "1" && -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------
# 1) 探測輸入長度
# ---------------------------------------------------------------
RAW_DURATION="$(ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 "$INPUT")" \
  || die "ffprobe 讀取輸入長度失敗: $INPUT"

[[ -n "$RAW_DURATION" ]] || die "ffprobe 沒有回傳長度，輸入檔可能壞掉: $INPUT"
log "原始影片長度: ${RAW_DURATION}s"

INPUT_SS_ARGS=()
SOURCE_DURATION="$RAW_DURATION"
if [[ -n "$TRIM_START" || -n "$TRIM_DURATION" ]]; then
  [[ -n "$TRIM_START" && -n "$TRIM_DURATION" ]] \
    || die "--trim-start 跟 --trim-duration 要一起給"
  INPUT_SS_ARGS=(-ss "$TRIM_START" -t "$TRIM_DURATION")
  SOURCE_DURATION="$TRIM_DURATION"
  log "已指定 trim 區段: 從 ${TRIM_START}s 開始，取 ${TRIM_DURATION}s"
fi

# ---------------------------------------------------------------
# 2) 依 target-seconds 算變速倍率（setpts 用）
# ---------------------------------------------------------------
# 用 python 做浮點運算，避免 bash 只能整數運算的問題。
SPEED_FACTOR="$("$PYTHON_BIN" -c "print(${SOURCE_DURATION} / ${TARGET_SECONDS})")"
MAX_SPEED_FACTOR="2.5"

OVER_LIMIT="$("$PYTHON_BIN" -c "print(1 if ${SPEED_FACTOR} > ${MAX_SPEED_FACTOR} else 0)")"
if [[ "$OVER_LIMIT" == "1" ]]; then
  die "原片（${SOURCE_DURATION}s）要壓縮到 ${TARGET_SECONDS}s 需要 ${SPEED_FACTOR}x 變速，超過上限 ${MAX_SPEED_FACTOR}x（太快會看不懂）。請重錄短一點，或用 --trim-start/--trim-duration 先擷取一段再處理。"
fi

log "變速倍率 (setpts 用): ${SPEED_FACTOR}x（來源 ${SOURCE_DURATION}s → 目標 ${TARGET_SECONDS}s）"

# ---------------------------------------------------------------
# 2.5) 若字卡設定裡有用 "stage" 綁定的項目，換算成這次成品影片的實際秒數
#      （固定 "start"/"end" 的項目原封不動通過，兩種寫法混用沒問題）
# ---------------------------------------------------------------
RESOLVE_SCRIPT="$WORK_DIR/resolve_stage_captions.py"
cat > "$RESOLVE_SCRIPT" <<'PYEOF'
import json
import sys

config_path, stages_path, speed_factor_s, target_seconds_s, out_path = sys.argv[1:6]
speed_factor = float(speed_factor_s)
target_seconds = float(target_seconds_s)

with open(config_path, encoding="utf-8") as f:
    cfg = json.load(f)

captions = cfg.get("captions", [])

stage_offsets = {}
if stages_path:
    with open(stages_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            stage_id, offset_s = parts
            try:
                stage_offsets[stage_id] = float(offset_s)
            except ValueError:
                continue

stage_captions = [c for c in captions if "stage" in c]

if stage_captions and not stage_offsets:
    ids = sorted({c["stage"] for c in stage_captions})
    print(
        "設定檔裡有用 \"stage\" 綁定的字卡（" + ", ".join(ids) + "），"
        "但沒有提供 --stages（或該檔案是空的），無法換算成秒數。"
        "請先讓 walkthrough 印出 DEMO_MARK_STAGE 再用 record_demo.sh 產生 "
        "stages.tsv，或把這幾張字卡改回固定 start/end。",
        file=sys.stderr,
    )
    sys.exit(2)

unknown = sorted({c["stage"] for c in stage_captions if c["stage"] not in stage_offsets})
if unknown:
    available = ", ".join(sorted(stage_offsets.keys())) or "(空)"
    print(
        "字卡設定引用了不存在的 stage id：" + ", ".join(unknown) + "。"
        "--stages 檔案裡目前可用的 id 有：" + available,
        file=sys.stderr,
    )
    sys.exit(3)

# 把每個 stage 綁定的字卡換算出「成品影片裡的開始秒數」，按時間排序，
# 用來找「下一個有字卡的 stage」當結束時間的上限。
resolved = []
for c in stage_captions:
    start = stage_offsets[c["stage"]] / speed_factor
    resolved.append((start, c))
resolved.sort(key=lambda pair: pair[0])

for i, (start, c) in enumerate(resolved):
    duration = float(c.get("duration", 5.0))
    end = start + duration
    if i + 1 < len(resolved):
        end = min(end, resolved[i + 1][0])
    end = min(end, target_seconds)
    if end <= start:
        end = min(start + 0.1, target_seconds)
    c["start"] = round(start, 3)
    c["end"] = round(end, 3)
    print(
        f"[resolve_stage_captions] stage={c['stage']!r} "
        f"offset={stage_offsets[c['stage']]}s -> start={c['start']}s end={c['end']}s",
        file=sys.stderr,
    )

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
PYEOF

RESOLVED_CONFIG="$WORK_DIR/resolved_captions.json"
"$PYTHON_BIN" "$RESOLVE_SCRIPT" "$CONFIG" "${STAGES}" "$SPEED_FACTOR" "$TARGET_SECONDS" "$RESOLVED_CONFIG" \
  || die "字卡的 stage 綁定換算失敗（看上面的錯誤訊息）"
EFFECTIVE_CONFIG="$RESOLVED_CONFIG"

# ---------------------------------------------------------------
# 3) 用 demo_captions.py 產字卡 PNG + manifest
# ---------------------------------------------------------------
CAPTIONS_DIR="$WORK_DIR/captions"
mkdir -p "$CAPTIONS_DIR"

"$PYTHON_BIN" "$SCRIPT_DIR/demo_captions.py" \
  --config "$EFFECTIVE_CONFIG" \
  --out-dir "$CAPTIONS_DIR" \
  --width "$WIDTH" \
  --height "$HEIGHT" \
  || die "demo_captions.py 產字卡失敗"

MANIFEST="$CAPTIONS_DIR/manifest.tsv"
[[ -f "$MANIFEST" ]] || die "沒有產出 manifest.tsv: $MANIFEST"

# ---------------------------------------------------------------
# 4) 組 ffmpeg filter_complex：scale/crop → setpts 變速 → 逐張 overlay 字卡
#    → 整體 fade in/out
# ---------------------------------------------------------------
# 這裡用 ${ARR[@]+"${ARR[@]}"} 這個寫法，是因為 macOS 內建的 bash 是
# 3.2（很舊），在 set -u 之下展開「空陣列」的 "${ARR[@]}" 會直接報
# unbound variable，這個寫法可以在陣列是空的時候安全跳過。
FFMPEG_INPUT_ARGS=(${INPUT_SS_ARGS[@]+"${INPUT_SS_ARGS[@]}"} -i "$INPUT")

FILTER_FILE="$WORK_DIR/filter_complex.txt"

CAPTION_COUNT=0
CAPTION_INDEXES=()
CAPTION_FILES=()
CAPTION_STARTS=()
CAPTION_ENDS=()
while IFS=$'\t' read -r idx file start end; do
  [[ -z "$idx" ]] && continue
  CAPTION_INDEXES+=("$idx")
  CAPTION_FILES+=("$CAPTIONS_DIR/$file")
  CAPTION_STARTS+=("$start")
  CAPTION_ENDS+=("$end")
  CAPTION_COUNT=$((CAPTION_COUNT + 1))
done < "$MANIFEST"

[[ "$CAPTION_COUNT" -gt 0 ]] || die "manifest.tsv 是空的，沒有字卡可疊"
log "讀到 ${CAPTION_COUNT} 張字卡"

# 每張字卡的圖片輸入都要 loop，且長度要蓋過整支影片，overlay 才不會提早消失。
for f in "${CAPTION_FILES[@]}"; do
  [[ -f "$f" ]] || die "字卡檔案不存在: $f"
  FFMPEG_INPUT_ARGS+=(-loop 1 -t "$TARGET_SECONDS" -i "$f")
done

{
  echo "[0:v]fps=30,scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=increase,crop=${WIDTH}:${HEIGHT},setpts=PTS/${SPEED_FACTOR},format=yuv420p[base];"

  PREV_LABEL="base"
  for i in $(seq 0 $((CAPTION_COUNT - 1))); do
    IN_IDX=$((i + 1))  # 輸入 0 是影片本身，字卡從 1 開始
    START="${CAPTION_STARTS[$i]}"
    END="${CAPTION_ENDS[$i]}"
    FADE_D="0.3"
    FADE_OUT_ST="$("$PYTHON_BIN" -c "print(max(${START}, ${END} - ${FADE_D}))")"

    echo "[${IN_IDX}:v]format=rgba,fade=t=in:st=${START}:d=${FADE_D}:alpha=1,fade=t=out:st=${FADE_OUT_ST}:d=${FADE_D}:alpha=1[cap${i}];"

    OUT_LABEL="ov${i}"
    echo "[${PREV_LABEL}][cap${i}]overlay=0:0:enable='between(t,${START},${END})'[${OUT_LABEL}];"
    PREV_LABEL="$OUT_LABEL"
  done

  FADE_OUT_START="$("$PYTHON_BIN" -c "print(max(0, ${TARGET_SECONDS} - 0.4))")"
  echo "[${PREV_LABEL}]fade=t=in:st=0:d=0.4,fade=t=out:st=${FADE_OUT_START}:d=0.4,format=yuv420p[vout]"
} > "$FILTER_FILE"

log "filter_complex 已寫到: $FILTER_FILE"

# ---------------------------------------------------------------
# 5) 真的跑 ffmpeg
# ---------------------------------------------------------------
mkdir -p "$(dirname "$OUTPUT")"

log "開始編碼..."
# 注意：這台機器的 ffmpeg 9.0.1 沒有 -filter_complex_script 這個選項
# （只有 -filter_complex_threads），所以改用 -filter_complex 直接吃
# 檔案內容（用 "$(cat ...)"），而不是傳檔名。
if ! ffmpeg -y \
  "${FFMPEG_INPUT_ARGS[@]}" \
  -filter_complex "$(cat "$FILTER_FILE")" \
  -map "[vout]" \
  -an \
  -r 30 \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart \
  -t "$TARGET_SECONDS" \
  "$OUTPUT" 2> "$WORK_DIR/ffmpeg.log"; then
  echo "---- ffmpeg 錯誤輸出 (tail -n 60) ----" >&2
  tail -n 60 "$WORK_DIR/ffmpeg.log" >&2
  die "ffmpeg 編碼失敗，完整 log 在 $WORK_DIR/ffmpeg.log"
fi

[[ -f "$OUTPUT" ]] || die "ffmpeg 回傳成功但找不到輸出檔: $OUTPUT"

# ---------------------------------------------------------------
# 6) 驗成品：長度、解析度、codec
# ---------------------------------------------------------------
log "驗證輸出檔: $OUTPUT"
PROBE_OUTPUT="$(ffprobe -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height,pix_fmt,r_frame_rate \
  -show_entries format=duration \
  -of default=noprint_wrappers=0 \
  "$OUTPUT")" || die "ffprobe 驗證輸出檔失敗"

echo "---- ffprobe 輸出 ----"
echo "$PROBE_OUTPUT"
echo "----------------------"

OUT_WIDTH="$(echo "$PROBE_OUTPUT" | grep '^width=' | cut -d= -f2)"
OUT_HEIGHT="$(echo "$PROBE_OUTPUT" | grep '^height=' | cut -d= -f2)"
OUT_CODEC="$(echo "$PROBE_OUTPUT" | grep '^codec_name=' | cut -d= -f2)"
OUT_DURATION="$(echo "$PROBE_OUTPUT" | grep '^duration=' | cut -d= -f2)"

[[ "$OUT_WIDTH" == "$WIDTH" ]] || die "輸出解析度寬度不對: 期望 $WIDTH，實際 $OUT_WIDTH"
[[ "$OUT_HEIGHT" == "$HEIGHT" ]] || die "輸出解析度高度不對: 期望 $HEIGHT，實際 $OUT_HEIGHT"
[[ "$OUT_CODEC" == "h264" ]] || die "輸出 codec 不是 h264: $OUT_CODEC"

log "解析度: ${OUT_WIDTH}x${OUT_HEIGHT}  codec: ${OUT_CODEC}  長度: ${OUT_DURATION}s"
log "完成: $OUTPUT"
