"""
converter.py 的单元测试 + 生成一张对照图。

跑法：
    python tools/test_converter.py
产出：
    tools/out/compare_xaut.png    （左：源图灰度化  右：按规则取模后在屏上的样子）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw                      # noqa: E402
import converter                                      # noqa: E402
from converter import Options, ConvertError           # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


print("1) 已知灰度 → 半字节（规则 15-(g>>4)）")
cases = [(0x00, 15), (0x0F, 15), (0x10, 14), (0x1F, 14), (0x20, 13),
         (0x50, 10), (0x9F, 6), (0xA0, 5), (0xAF, 5), (0xB0, 4),
         (0xF0, 0), (0xFF, 0)]
img = Image.new("L", (len(cases) * 4, 1), 0)
for i, (g, _) in enumerate(cases):
    for k in range(4):                       # 每个值重复 4 次 → 占满 4 个像素
        img.putpixel((i * 4 + k, 0), g)
rows = converter.to_nibbles(img, invert=True)
ok = all(rows[0][i * 4] == want for i, (_, want) in enumerate(cases))
check(ok, "12 个边界灰度值的半字节全部符合 15-(g>>4)")
for (g, want), got in zip(cases, [rows[0][i * 4] for i in range(len(cases))]):
    if got != want:
        print(f"       {g:#04x} -> 期望 {want} 实际 {got}")

print("\n2) 两像素拼一字节：高 4 位是左像素")
img2 = Image.new("L", (4, 1))
for x, g in enumerate([0xF0, 0x00, 0x00, 0xF0]):     # 亮 暗 暗 亮
    img2.putpixel((x, 0), g)
r2 = converter.to_nibbles(img2, invert=True)
check(r2[0] == [0, 15, 15, 0], f"半字节序列 {r2[0]} == [0,15,15,0]")
b2 = converter.nibbles_to_bytes(r2)
check(b2 == bytes([0x0F, 0xF0]), f"字节 {b2.hex().upper()} == 0FF0（左像素在高位）")

print("\n3) 彩色图自动转灰度")
color = Image.new("RGB", (8, 2))
for x in range(8):
    color.putpixel((x, 0), (255, 0, 0))              # 纯红 → 灰度约 76
    color.putpixel((x, 1), (0, 0, 255))              # 纯蓝 → 灰度约 29
res = converter.convert(color, Options(header=converter.HEADER_NONE))
check(res.width == 8 and res.height == 2, "尺寸保持 8x2")
check(len(res.data) == 8, f"数据 {len(res.data)} 字节 == 8*2/2")
gray = color.convert("L")
check(abs(gray.getpixel((0, 0)) - 76) < 3, f"纯红转灰度 = {gray.getpixel((0,0))}（约 76）")
check(abs(gray.getpixel((0, 1)) - 29) < 3, f"纯蓝转灰度 = {gray.getpixel((0,1))}（约 29）")

print("\n4) 头部格式")
r = converter.convert(color, Options(header=converter.HEADER_NONE))
check(r.payload == r.data, "无头部：不多一个字节")

r = converter.convert(color, Options(header=converter.HEADER_TAGGED))
check(r.payload[:4] == bytes([0x21, 8, 0, 2]),
      f"自描述头部 = 21 08 00 02（实际 {r.payload[:4].hex().upper()}）")
check(len(r.payload) == len(r.data) + converter.HEADER_SIZE,
      f"头部 {converter.HEADER_SIZE} 字节")
check(converter.HEADER_TAG == 0x21,
      f"描述符 = (宽 {converter.WIDTH_BYTES} 字节 << 4) | 高 "
      f"{converter.HEIGHT_BYTES} 字节 = 0x{converter.HEADER_TAG:02X}")
check((converter.HEADER_TAG >> 4) == converter.WIDTH_BYTES
      and (converter.HEADER_TAG & 0x0F) == converter.HEIGHT_BYTES,
      "描述符的高 4 位 / 低 4 位确实分别是宽、高的字节数")


def decode(payload: bytes):
    """按描述符去读 —— 固件端将来就是这么解的。"""
    tag = payload[0]
    wb, hb = tag >> 4, tag & 0x0F
    w = int.from_bytes(payload[1:1 + wb], "little")
    h = int.from_bytes(payload[1 + wb:1 + wb + hb], "little")
    return w, h


check(decode(r.payload) == (8, 2), "按描述符解码回 8x2")

print("\n4b) 宽度 256 —— 一个字节装不下的那种")
check(256 > 0xFF, "前提：256 装不进 uint8_t")
big = Image.new("L", (256, 64), 0)          # 屏的全宽全高
rt = converter.convert(big, Options(header=converter.HEADER_TAGGED))
check(rt.width == 256 and rt.height == 64, "尺寸 256x64")
check(rt.payload[:4] == bytes([0x21, 0x00, 0x01, 0x40]),
      f"256x64 → 21 00 01 40（实际 {rt.payload[:4].hex().upper()}）")
check(len(rt.data) == 256 * 64 // 2, f"像素数据 {len(rt.data)} 字节 == 256*64/2")
check(decode(rt.payload) == (256, 64), "按描述符解码回 256x64（宽确实读成 16 位）")

txt = converter.format_c_array(rt, Options(header=converter.HEADER_TAGGED))
check("0x21,0x00,0x01,0x40," in txt, "生成的头部行是 0x21,0x00,0x01,0x40,")
check("宽 256、高 64" in txt, "注释里写明了真实尺寸，不用去心算小端")

logo_bmp = r"E:\Works\LTMCU\res\xaut_logo.bmp"
if Path(logo_bmp).exists():
    rl = converter.convert(Image.open(logo_bmp), Options())
    check(decode(rl.payload) == (64, 48), "64x48 的 logo 解码回 64x48")
    check(rl.payload[:4] == bytes([0x21, 0x40, 0x00, 0x30]),
          f"64x48 → 21 40 00 30（实际 {rl.payload[:4].hex().upper()}）")

snip = converter.fontsize_snippet()
check("uint16_t" in snip, "fontSize 代码片段里提示了 uint16_t")
check("0x21" in snip, "fontSize 代码片段里给出了 0x21 这个 case")

print("\n5) 尺寸校验")
for w, h, should_raise, needle in [
    (63, 32, True,  "奇数"),
    (62, 32, False, "4 的倍数"),
    (64, 20, False, "8 的倍数"),
    (64, 72, False, "256x64"),
]:
    im = Image.new("L", (w, h), 0)
    try:
        r = converter.convert(im, Options())
        raised = False
        warns = " ".join(r.warnings)
    except ConvertError as e:
        raised = True
        warns = str(e)
    check(raised == should_raise, f"{w}x{h} 抛异常={raised}（期望 {should_raise}）")
    if needle:
        check(needle in warns, f"   提示里提到『{needle}』")

print("\n6) 反相关闭")
a = converter.convert(img2, Options(invert=True)).data
b = converter.convert(img2, Options(invert=False)).data
check(a != b, "开/关反相结果不同")
check(a == bytes([0x0F, 0xF0]) and b == bytes([0xF0, 0x0F]),
      f"反相={a.hex().upper()} == 0FF0，不反相={b.hex().upper()} == F00F")

print("\n7) 生成对照图")
src = Path(r"E:\Works\LTMCU\res\xaut_logo.bmp")
if src.exists():
    im = Image.open(src)
    r = converter.convert(im, Options(header=converter.HEADER_NONE))
    left = im.convert("L")
    right = converter.nibbles_to_image(r.nibbles)
    scale = 5
    W, H = left.size
    combo = Image.new("L", (W * 2 * scale + 20, H * scale + 30), 40)
    combo.paste(left.resize((W * scale, H * scale), Image.NEAREST), (0, 22))
    combo.paste(right.resize((W * scale, H * scale), Image.NEAREST), (W * scale + 20, 22))
    d = ImageDraw.Draw(combo)
    d.text((4, 4), "SOURCE (gray)", fill=255)
    d.text((W * scale + 24, 4), "SSD1322 4-bit (after invert)", fill=255)
    p = OUT / "compare_xaut.png"
    combo.save(p)
    print("  写出", p)
else:
    print("  跳过（找不到源图）")

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("全部通过 ✅")
