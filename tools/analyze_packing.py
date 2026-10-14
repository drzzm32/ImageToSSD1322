"""
反推 xaut_logo.bmp -> font.c 里 logo[] 数组的取模规则。

做法：把候选的打包方式全部枚举一遍，逐一与 font.c 中真实的 logo[] 字节比对，
只有完全一致的那一种才算数（不靠猜）。
"""
import re
import sys
import itertools
from pathlib import Path

from PIL import Image

FONT_C = Path(r"E:\Works\NTP_PRO_II\font.c")
BMP = Path(r"E:\Works\LTMCU\res\xaut_logo.bmp")


def extract_logo_bytes(font_c: Path):
    text = font_c.read_text(encoding="utf-8")
    m = re.search(r"const\s+static\s+uint8_t\s+logo\s*\[\s*\]\s*=\s*\{(.*?)\n\};",
                  text, re.S)
    if not m:
        raise SystemExit("在 font.c 里找不到 logo[] 数组")
    body = re.sub(r"//[^\r\n]*", "", m.group(1))
    vals = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", body)]
    return vals


def load_gray(bmp: Path):
    im = Image.open(bmp).convert("L")
    w, h = im.size
    px = im.load()
    # 统一成 top-down 的二维表
    return w, h, [[px[x, y] for x in range(w)] for y in range(h)]


QUANT = {
    "v>>4":            lambda v: v >> 4,
    "round(v*15/255)": lambda v: int(round(v * 15 / 255)),
    "floor(v*15/255)": lambda v: (v * 15) // 255,
    "v>>4 ^ 0xF":      lambda v: (v >> 4) ^ 0xF,
}


def pack(gray, w, h, quant, hi_first, flip_rows, flip_cols, invert):
    q = QUANT[quant]
    rows = range(h - 1, -1, -1) if flip_rows else range(h)
    out = bytearray()
    for y in rows:
        row = gray[y]
        if invert:
            row = [255 - v for v in row]
        if flip_cols:
            row = row[::-1]
        n = [q(v) & 0xF for v in row]
        for x in range(0, w, 2):
            a, b = n[x], n[x + 1]              # a = 左像素, b = 右像素
            out.append(((a << 4) | b) if hi_first else ((b << 4) | a))
    return bytes(out)


def main():
    ref = extract_logo_bytes(FONT_C)
    w, h, gray = load_gray(BMP)
    print(f"BMP      : {w} x {h}  灰度")
    print(f"logo[]   : {len(ref)} 字节   (期望 {w * h // 2})")
    if len(ref) != w * h // 2:
        print("!! 长度不符，后续比对无意义")
        return
    print(f"参考前 16 字节: {' '.join(f'{b:02X}' for b in ref[:16])}\n")

    hits = []
    combos = itertools.product(QUANT, (True, False), (True, False), (True, False), (True, False))
    for quant, hi_first, flip_rows, flip_cols, invert in combos:
        got = pack(gray, w, h, quant, hi_first, flip_rows, flip_cols, invert)
        if got == ref:
            hits.append((quant, hi_first, flip_rows, flip_cols, invert))
            print("*** 完全匹配: "
                  f"灰度={quant}  高4位={'左像素' if hi_first else '右像素'}  "
                  f"行序={'倒序(自下而上)' if flip_rows else '正序'}  "
                  f"列序={'左右翻转' if flip_cols else '正常'}  "
                  f"{'取反' if invert else '不取反'}")

    if not hits:
        print("没有完全匹配的组合。给出最接近的 3 个：")
        scored = []
        for quant, hi_first, flip_rows, flip_cols, invert in combos:
            got = pack(gray, w, h, quant, hi_first, flip_rows, flip_cols, invert)
            diff = sum(1 for a, b in zip(got, ref) if a != b)
            scored.append((diff, quant, hi_first, flip_rows, flip_cols, invert))
        scored.sort()
        for diff, quant, hi_first, flip_rows, flip_cols, invert in scored[:3]:
            print(f"   差异 {diff:5d}/{len(ref)} 字节  灰度={quant} "
                  f"高4位={'左' if hi_first else '右'} "
                  f"行={'倒' if flip_rows else '正'} 列={'翻' if flip_cols else '正'} "
                  f"{'取反' if invert else ''}")


if __name__ == "__main__":
    main()
