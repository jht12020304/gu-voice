#!/usr/bin/env python3
"""從品牌 logo 產生 iOS App Icon 與 LaunchImage 資產。

為什麼要有這支腳本：`ios/Runner/Assets.xcassets/AppIcon.appiconset/` 過去只有
`Contents.json`，它指名的 15 個 PNG 一張都不存在（repo 根 `.gitignore` 的 `*.png`
把它們擋在版控外，`find flutter_app -name '*.png'` 回零筆）。actool 對「宣告了但
檔案不在」不會 build error，Runner.app 只是安靜地生不出 `Assets.car`，一路要到
App Store Connect 上傳驗證才爆——所以資產必須可重生，不能靠某台機器的手工檔案。

用法（在 flutter_app/ 底下）：

    ../backend/venv/bin/python tool/gen_app_icons.py          # 產生
    ../backend/venv/bin/python tool/gen_app_icons.py --check  # 只驗證，缺檔回 exit 1

來源圖是 `frontend/public/logo.png`（1024x1024、無 alpha）。整張含底部 "UroSense"
文字，縮到 40px 會糊掉，所以腳本會自動偵測盾牌主體的 bounding box 只取那一塊。

Apple 對 App Icon 的硬性要求（照 Human Interface Guidelines）：正方形、**不得含
alpha channel**、不要自己畫圓角（系統會裁）。因此輸出一律 flatten 成 RGB。
LaunchImage 反而**保留**背景色即可，storyboard 的 contentMode 是 center。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "frontend" / "public" / "logo.png"
ICONSET = REPO_ROOT / "flutter_app" / "ios" / "Runner" / "Assets.xcassets" / "AppIcon.appiconset"
LAUNCHSET = REPO_ROOT / "flutter_app" / "ios" / "Runner" / "Assets.xcassets" / "LaunchImage.imageset"

# storyboard 宣告的 LaunchImage 尺寸是 168x185；我們用正方形，取 168 點。
LAUNCH_POINT_SIZE = 168

# 只取上半部找盾牌——下面約 25% 是 "UroSense" 文字，縮到 40px 不可讀，不要進 icon。
SHIELD_SEARCH_BOTTOM = 0.72
# 盾牌是深藍（實測亮度 37–51），底色是帶暈影的淺灰（實測 215–252）。
# 用「亮度門檻」抓深色前景，不要用「背景色相減」——底色橫跨 215–252 這麼寬的區間，
# 任何以四角取樣為基準的容差都會把大半個背景判成前景（第一版就是這樣壞的，
# 裁切框回傳整張 1024x1024）。
DARK_THRESHOLD = 150
# 盾牌四周留白，避免頂到 icon 邊緣（系統圓角會裁掉角落）。
PADDING_RATIO = 0.08


def _load_source() -> Image.Image:
    if not SOURCE.exists():
        sys.exit(f"找不到來源 logo：{SOURCE}")
    return Image.open(SOURCE).convert("RGB")


def _shield_box(img: Image.Image) -> tuple[int, int, int, int]:
    """找出上半部深色像素（＝盾牌）的 bounding box。不做任何擴張或位移。"""
    w, h = img.size
    search = img.convert("L").crop((0, 0, w, int(h * SHIELD_SEARCH_BOTTOM)))
    box = search.point(lambda v: 255 if v < DARK_THRESHOLD else 0).getbbox()
    if box is None:
        sys.exit("在來源圖上半部找不到深色像素——logo 換了？請檢查 DARK_THRESHOLD。")
    return box


def _edge_color(crop: Image.Image) -> tuple[int, int, int]:
    """取裁切區**自身**最外一圈像素的中位色當畫布底色。

    刻意不從原圖四角取樣：這張 logo 有暈影，四角是 rgb(213,216,213) 而盾牌旁邊是
    ~245，用四角的顏色填畫布，貼合處會出現一圈看得見的灰邊（實測 1024 那張明顯）。
    取裁切區自己的邊框像素，填色與貼上去的內容天生連續，接縫消失。
    """
    w, h = crop.size
    samples = [crop.getpixel((x, y)) for x in range(0, w, 4) for y in (0, h - 1)]
    samples += [crop.getpixel((x, y)) for y in range(0, h, 4) for x in (0, w - 1)]
    return tuple(sorted(c[i] for c in samples)[len(samples) // 2] for i in range(3))  # type: ignore[return-value]


def _compose_square(img: Image.Image) -> tuple[Image.Image, tuple[int, int, int]]:
    """精確裁出盾牌，貼到留白的正方形畫布置中。

    刻意**不**用「以盾牌為中心切一個正方形視窗、超出邊界就往內滑」的做法：盾牌在
    來源圖上偏上、幾乎貼到頂，視窗往下滑就會把底部 "UroSense" 文字的頂端切進來
    （第一版就是這樣，裁切框 bottom 落在 776，實測看得到文字）。改成把裁好的盾牌
    貼到自己的畫布上，位置完全由我們決定，文字不可能混進來。
    """
    w, h = img.size
    left, top, right, bottom = _shield_box(img)
    pad = int(max(right - left, bottom - top) * PADDING_RATIO)

    # 先在**來源圖上**向外擴留白，取到的是真實背景像素，不是合成色。
    # 下緣夾在文字帶之上（SHIELD_SEARCH_BOTTOM），"UroSense" 不可能被擴進來。
    crop = img.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(w, right + pad),
            min(int(h * SHIELD_SEARCH_BOTTOM), bottom + pad),
        )
    )
    bg = _edge_color(crop)

    side = max(crop.size)
    ox, oy = (side - crop.width) // 2, (side - crop.height) // 2
    canvas = Image.new("RGB", (side, side), bg)
    canvas.paste(crop, (ox, oy))

    # 補正方形剩下的那一點留白，用邊緣像素外推而不是純色填：底圖有暈影，單一填色
    # 會在貼合處留下看得見的矩形接縫。此時 crop 的最外一列已經是純背景（上面擴過
    # 了），外推不會像直接對 bbox 外推那樣把盾牌的深色像素抹出去。
    if ox:
        canvas.paste(crop.crop((0, 0, 1, crop.height)).resize((ox, crop.height)), (0, oy))
        canvas.paste(
            crop.crop((crop.width - 1, 0, crop.width, crop.height)).resize((side - ox - crop.width, crop.height)),
            (ox + crop.width, oy),
        )
    if oy:
        canvas.paste(canvas.crop((0, oy, side, oy + 1)).resize((side, oy)), (0, 0))
        canvas.paste(
            canvas.crop((0, oy + crop.height - 1, side, oy + crop.height)).resize((side, side - oy - crop.height)),
            (0, oy + crop.height),
        )
    return canvas, bg


# Contents.json 有 19 筆 entry，但只有 15 個唯一檔名（多個 idiom 共用同一張圖）。
# 讀 Contents.json 而不是寫死清單——改 asset catalog 時這裡自動跟上。
def _required_icons() -> dict[str, int]:
    contents = json.loads((ICONSET / "Contents.json").read_text())
    out: dict[str, int] = {}
    for entry in contents["images"]:
        filename = entry.get("filename")
        if not filename:
            continue
        size_pt = float(entry["size"].split("x")[0])
        scale = int(entry["scale"].rstrip("x"))
        px = round(size_pt * scale)
        if filename in out and out[filename] != px:
            sys.exit(f"Contents.json 自相矛盾：{filename} 同時要求 {out[filename]}px 與 {px}px")
        out[filename] = px
    return out


def _launch_images() -> dict[str, int]:
    contents = json.loads((LAUNCHSET / "Contents.json").read_text())
    out: dict[str, int] = {}
    for entry in contents["images"]:
        filename = entry.get("filename")
        if not filename:
            continue
        scale = int(entry["scale"].rstrip("x"))
        out[filename] = LAUNCH_POINT_SIZE * scale
    return out


def check() -> int:
    missing = [
        str(path / name)
        for path, names in ((ICONSET, _required_icons()), (LAUNCHSET, _launch_images()))
        for name in names
        if not (path / name).exists()
    ]
    if missing:
        print("缺少圖示資產（App Store Connect 上傳會被退）：", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print("\n跑 `python tool/gen_app_icons.py` 產生。", file=sys.stderr)
        return 1

    # 1024 那張若含 alpha，上傳會被退——順手驗。
    marketing = ICONSET / "Icon-App-1024x1024@1x.png"
    with Image.open(marketing) as img:
        if img.mode not in ("RGB", "L") or "A" in img.getbands():
            print(f"{marketing} 含 alpha channel，App Store 不接受。", file=sys.stderr)
            return 1
    print("圖示資產齊全，1024 marketing icon 無 alpha。")
    return 0


def generate() -> int:
    src = _load_source()
    shield, bg = _compose_square(src)
    print(f"來源 {SOURCE.name} {src.size} → 方形畫布 {shield.size}，底色 rgb{bg}")

    for name, px in sorted(_required_icons().items(), key=lambda kv: kv[1]):
        out = shield.resize((px, px), Image.LANCZOS).convert("RGB")
        out.save(ICONSET / name, "PNG", optimize=True)
        print(f"  icon  {name:<32} {px}x{px}")

    for name, px in sorted(_launch_images().items(), key=lambda kv: kv[1]):
        out = shield.resize((px, px), Image.LANCZOS).convert("RGB")
        out.save(LAUNCHSET / name, "PNG", optimize=True)
        print(f"  launch {name:<31} {px}x{px}")

    print(f"\n背景色供 LaunchScreen.storyboard 對齊用：rgb{bg} = #{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}")
    return check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只驗證資產是否齊全，不重新產生")
    args = parser.parse_args()
    sys.exit(check() if args.check else generate())
