"""
既然布局已经确认（行正序、高4位=左像素、反相），这里直接统计
"BMP 灰度值 -> logo[] 里的半字节" 的对应关系，把量化规则精确挖出来。
"""
import re
from collections import defaultdict, Counter
from pathlib import Path

from PIL import Image

FONT_C = Path(r"E:\Works\NTP_PRO_II\font.c")
BMP = Path(r"E:\Works\LTMCU\res\xaut_logo.bmp")
W, H = 64, 48


def extract_logo_bytes():
    text = FONT_C.read_text(encoding="utf-8")
    m = re.search(r"const\s+static\s+uint8_t\s+logo\s*\[\s*\]\s*=\s*\{(.*?)\n\};", text, re.S)
    body = re.sub(r"//[^\r\n]*", "", m.group(1))
    return [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", body)]


ref = extract_logo_bytes()
im = Image.open(BMP).convert("L")
gray = [[im.getpixel((x, y)) for x in range(W)] for y in range(H)]

# 参考：行正序、高4位=左像素
ref_nib = [[0] * W for _ in range(H)]
nbr = W // 2
for y in range(H):
    for i in range(nbr):
        b = ref[y * nbr + i]
        ref_nib[y][i * 2] = (b >> 4) & 0xF
        ref_nib[y][i * 2 + 1] = b & 0xF

table = defaultdict(Counter)
mismatch_invert = 0
for y in range(H):
    for x in range(W):
        g = gray[y][x]
        table[g][ref_nib[y][x]] += 1
        if ref_nib[y][x] != (15 - (g >> 4)):
            mismatch_invert += 1

print(f"'15 - (g>>4)' 与参考不符的像素: {mismatch_invert} / {W*H}\n")

print("灰度值 -> 参考半字节 的映射（只列出现过的灰度）:")
for g in sorted(table):
    dist = table[g]
    total = sum(dist.values())
    s = "  ".join(f"{k}:{v}" for k, v in sorted(dist.items()))
    flag = "" if len(dist) == 1 else "   <== 同一灰度对应多个半字节!"
    print(f"  灰度 {g:3d} (0x{g:02X})  共 {total:5d} 次 -> {s}{flag}")

# 看看差异像素都落在哪里
print("\n与 '15-(g>>4)' 不符的像素（最多列 40 个）:")
cnt = 0
for y in range(H):
    for x in range(W):
        g = gray[y][x]
        if ref_nib[y][x] != (15 - (g >> 4)):
            print(f"  ({x, y}) 灰度={g:3d}  参考半字节={ref_nib[y][x]:2d}  15-(g>>4)={15-(g>>4)}")
            cnt += 1
            if cnt >= 40:
                break
    if cnt >= 40:
        break
