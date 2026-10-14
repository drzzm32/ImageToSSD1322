"""
把 font.c 里的 logo[] 数组直接渲染成图片，用来确认行序与半字节序。
同时把原始 BMP 也放大存一份做对照。
"""
import re
from pathlib import Path

from PIL import Image

FONT_C = Path(r"E:\Works\NTP_PRO_II\font.c")
BMP = Path(r"E:\Works\LTMCU\res\xaut_logo.bmp")
OUT = Path(r"E:\Works\ImageToSSD1322\tools\out")
OUT.mkdir(parents=True, exist_ok=True)

W, H = 64, 48
SCALE = 6


def extract_logo_bytes(font_c: Path):
    text = font_c.read_text(encoding="utf-8")
    m = re.search(r"const\s+static\s+uint8_t\s+logo\s*\[\s*\]\s*=\s*\{(.*?)\n\};", text, re.S)
    body = re.sub(r"//[^\r\n]*", "", m.group(1))
    return [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", body)]


def render(data, w, h, hi_first, flip_rows):
    im = Image.new("L", (w, h), 0)
    px = im.load()
    nbytes_row = w // 2
    rows = list(range(h))
    for y in rows:
        src_y = (h - 1 - y) if flip_rows else y
        for i in range(nbytes_row):
            b = data[src_y * nbytes_row + i]
            hi, lo = (b >> 4) & 0xF, b & 0xF
            a, c = (hi, lo) if hi_first else (lo, hi)
            px[i * 2, y] = a * 17
            px[i * 2 + 1, y] = c * 17
    return im.resize((w * SCALE, h * SCALE), Image.NEAREST)


ref = extract_logo_bytes(FONT_C)
print("logo[] 字节数 =", len(ref))

for hi_first in (True, False):
    for flip_rows in (True, False):
        tag = f"hi_{'left' if hi_first else 'right'}_rows_{'flip' if flip_rows else 'norm'}"
        render(ref, W, H, hi_first, flip_rows).save(OUT / f"logo_{tag}.png")
        print("写出", OUT / f"logo_{tag}.png")

Image.open(BMP).convert("L").resize((W * SCALE, H * SCALE), Image.NEAREST)\
    .save(OUT / "source_bmp.png")
print("写出", OUT / "source_bmp.png")
