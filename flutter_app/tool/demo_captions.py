#!/usr/bin/env python3
"""demo_captions.py

用途：為 make_demo_video.sh 產生「字卡」PNG（含 alpha 透明背景）。

背景（重要，別重踩）：
    這台機器的 ffmpeg 9.0.1 沒有編譯 libfreetype / libass，所以
    `drawtext`、`subtitles`、`ass` 這三個濾鏡完全不能用（會直接失敗）。
    因此中文字卡改成：Python + Pillow 事先把整張字卡（半透明圓角底
    ＋標題＋副標）渲染成一張跟畫面等大（1080x1920）、四周透明的 PNG，
    之後 ffmpeg 只需要用 `overlay` 疊圖即可，不需要在 ffmpeg 內畫字。

用法：
    python3 demo_captions.py --config captions.json --out-dir /tmp/caps \
        [--width 1080] [--height 1920]

輸出：
    <out-dir>/cap_00.png, cap_01.png, ...  每張都是 width x height、
        RGBA、除了字卡本體其餘完全透明，可以直接疊在任何背景上。
    <out-dir>/manifest.tsv  一行一張字卡：index\tfilename\tstart\tend
        （start/end 單位秒，直接複製自 config，給 shell 腳本組
        ffmpeg overlay 的 enable='between(t,a,b)' 用，避免在 bash 裡
        重新解析 JSON）。

設定檔格式（captions.json）：
    {
      "width": 1080,             // 可省略，預設 1080
      "height": 1920,            // 可省略，預設 1920
      "captions": [
        {
          "start": 0.0,
          "end": 2.5,
          "title": "UroSense",
          "subtitle": "AI 語音問診系統",
          "style": "title"        // "title" | "normal"（預設 normal）
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"

# 品牌色（半透明深藍 / 亮青色點綴），只是預設值，之後要換色系很好改。
NORMAL_BOX_COLOR = (12, 16, 24, 178)
TITLE_BOX_COLOR = (8, 46, 58, 200)
ACCENT_COLOR = (58, 220, 200, 255)
TITLE_TEXT_COLOR = (255, 255, 255, 255)
SUBTITLE_TEXT_COLOR = (225, 235, 235, 235)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """載入 STHeiti，容錯處理 .ttc 的 face index。"""
    last_err: Exception | None = None
    for index in (0, 1, 2):
        try:
            return ImageFont.truetype(FONT_PATH, size=size, index=index)
        except Exception as exc:  # noqa: BLE001 - 字型載入的例外種類不固定
            last_err = exc
    raise RuntimeError(f"無法載入字型 {FONT_PATH}: {last_err}")


def tokenize(text: str) -> list[str]:
    """把文字拆成可換行的最小單位：
    - 連續的英數字（含 - '）視為一個不可拆的英文單字
    - 空白自成一個 token
    - 其餘（含所有中文字、標點）逐字元各自一個 token
    這樣中文可以逐字換行，英文單字不會被硬切開。
    """
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        elif ch.isascii() and (ch.isalnum() or ch in "'-"):
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
    if buf:
        tokens.append(buf)
    return tokens


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """依實際渲染寬度（而非字元數）把文字換行，讓中英混排也能對齊。"""
    if not text:
        return []
    tokens = tokenize(text)
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        if tok == " ":
            candidate = cur + " " if cur else cur
            if draw.textlength(candidate, font=font) <= max_width:
                cur = candidate
            else:
                if cur.strip():
                    lines.append(cur.rstrip())
                cur = ""
            continue
        candidate = cur + tok
        width = draw.textlength(candidate, font=font)
        if width <= max_width or not cur:
            cur = candidate
        else:
            lines.append(cur.rstrip())
            cur = tok
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def draw_multiline(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    center_x: int,
    top_y: int,
    line_height: int,
    fill: tuple[int, int, int, int],
) -> int:
    """把已換行好的文字逐行置中畫出，回傳畫完後佔用的總高度。"""
    y = top_y
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text((center_x - w / 2, y), line, font=font, fill=fill)
        y += line_height
    return y - top_y


def render_caption(
    width: int,
    height: int,
    title: str,
    subtitle: str,
    style: str,
) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    margin = int(width * 0.08)
    box_width = width - margin * 2
    inner_pad_x = 56
    inner_pad_y = 44
    max_text_width = box_width - inner_pad_x * 2

    if style == "title":
        title_font = load_font(92)
        subtitle_font = load_font(46)
        box_color = TITLE_BOX_COLOR
        title_line_h = 106
        subtitle_line_h = 58
        gap = 22
    else:
        title_font = load_font(60)
        subtitle_font = load_font(36)
        box_color = NORMAL_BOX_COLOR
        title_line_h = 74
        subtitle_line_h = 48
        gap = 16

    title_lines = wrap_text(draw, title, title_font, max_text_width)
    subtitle_lines = wrap_text(draw, subtitle, subtitle_font, max_text_width) if subtitle else []

    content_h = len(title_lines) * title_line_h
    if subtitle_lines:
        content_h += gap + len(subtitle_lines) * subtitle_line_h
    box_height = inner_pad_y * 2 + content_h

    box_x0 = margin
    box_x1 = width - margin
    if style == "title":
        box_center_y = int(height * 0.40)
        box_y0 = box_center_y - box_height // 2
    else:
        bottom_margin = 230
        box_y0 = height - bottom_margin - box_height
    box_y1 = box_y0 + box_height

    draw.rounded_rectangle(
        (box_x0, box_y0, box_x1, box_y1),
        radius=36,
        fill=box_color,
    )
    # 頂端一條細細的品牌強調線，讓字卡看起來不是純黑底。
    accent_h = 6
    draw.rounded_rectangle(
        (box_x0 + 24, box_y0 + 14, box_x0 + 24 + 96, box_y0 + 14 + accent_h),
        radius=accent_h // 2,
        fill=ACCENT_COLOR,
    )

    text_center_x = (box_x0 + box_x1) // 2
    cursor_y = box_y0 + inner_pad_y + (10 if style == "title" else 0)
    used = draw_multiline(draw, title_lines, title_font, text_center_x, cursor_y, title_line_h, TITLE_TEXT_COLOR)
    if subtitle_lines:
        cursor_y += used + gap
        draw_multiline(draw, subtitle_lines, subtitle_font, text_center_x, cursor_y, subtitle_line_h, SUBTITLE_TEXT_COLOR)

    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description="產生 demo 影片用的中文字卡 PNG")
    parser.add_argument("--config", required=True, help="captions.json 路徑")
    parser.add_argument("--out-dir", required=True, help="輸出目錄")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[demo_captions] 找不到設定檔: {config_path}", file=sys.stderr)
        return 1

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[demo_captions] 設定檔不是合法 JSON: {exc}", file=sys.stderr)
        return 1

    width = int(cfg.get("width", args.width))
    height = int(cfg.get("height", args.height))
    captions = cfg.get("captions", [])
    if not captions:
        print("[demo_captions] 設定檔裡沒有 captions 陣列", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_lines = []
    for idx, cap in enumerate(sorted(captions, key=lambda c: c.get("start", 0.0))):
        try:
            start = float(cap["start"])
            end = float(cap["end"])
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[demo_captions] 第 {idx} 筆字卡缺少合法的 start/end: {exc}", file=sys.stderr)
            return 1
        if end <= start:
            print(f"[demo_captions] 第 {idx} 筆字卡 end({end}) 必須大於 start({start})", file=sys.stderr)
            return 1
        title = str(cap.get("title", ""))
        subtitle = str(cap.get("subtitle", ""))
        style = str(cap.get("style", "normal"))
        if not title:
            print(f"[demo_captions] 第 {idx} 筆字卡缺少 title", file=sys.stderr)
            return 1

        img = render_caption(width, height, title, subtitle, style)
        filename = f"cap_{idx:02d}.png"
        img.save(out_dir / filename)
        manifest_lines.append(f"{idx}\t{filename}\t{start}\t{end}")
        print(f"[demo_captions] 產出 {filename}  ({start}s - {end}s)  style={style}  title={title!r}")

    manifest_path = out_dir / "manifest.tsv"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(f"[demo_captions] 共 {len(manifest_lines)} 張字卡，manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
