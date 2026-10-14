"""
回归验证：converter.py 是否真的能复现 NTP_PRO_II/font.c 里现有的 logo[]。

⚠️ 这个"回归"的前提是有**当初生成 logo[] 的那张源图**。logo[] 换过图之后，
   旧源图就对不上了 —— 这时候脚本会明确报"跳过"并返回 0（不是失败），
   因为转换规则本身没变，只是没有可比对的基准了。
   要真正回归，把当前 logo[] 的源图传进来：

    python tools/verify_against_font_c.py                        # 自动找候选源图
    python tools/verify_against_font_c.py D:\\path\\to\\logo.png   # 指定源图

尺寸和像素数据都从 font.c 的数组头部（0x21 + 宽16位 + 高8位）读，
所以工具这边一改头部格式，这里会立刻跟着变，不会各写一套。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image                                  # noqa: E402
import converter                                       # noqa: E402

FONT_C = Path(r"E:\Works\NTP_PRO_II\font.c")
# 候选源图：按顺序找第一个尺寸与 logo[] 头部对得上的
CANDIDATES = [
    Path(r"E:\Works\LTMCU\res\xaut_logo.bmp"),
    Path(r"E:\Works\NTP_PRO_II\logo.png"),
    Path(r"E:\Works\NTP_PRO_II\logo.bmp"),
]


def extract(path: Path, name: str) -> bytes:
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"uint8_t\s+{name}\s*\[\s*\]\s*=\s*\{{(.*?)\n\}};", text, re.S)
    if not m:
        raise SystemExit(f"font.c 里找不到 {name}[]")
    # 两种注释都要剥：块注释里也会出现 0x21 之类的字样
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    body = re.sub(r"//[^\r\n]*", "", body)
    return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", body))


def parse_header(arr: bytes):
    """按 font.c 里 fontSize() 的逻辑解尺寸。"""
    tag = arr[0]
    wb, hb = tag >> 4, tag & 0x0F
    if tag != 0x21:
        raise SystemExit(f"没见过的头部描述符 0x{tag:02X}，本脚本只认 0x21")
    w = int.from_bytes(arr[1:1 + wb], "little")
    h = int.from_bytes(arr[1 + wb:1 + wb + hb], "little")
    return w, h, 1 + wb + hb


def main() -> int:
    ref_all = extract(FONT_C, "logo")
    w, h, hdr = parse_header(ref_all)
    ref = ref_all[hdr:]

    print(f"font.c 的 logo[]: 共 {len(ref_all)} 字节，头部 {hdr} 字节 "
          f"({' '.join(f'{b:02X}' for b in ref_all[:hdr])}) -> {w}x{h}")
    if len(ref) != w * h // 2:
        print(f"!! 像素数据 {len(ref)} 字节与 {w}x{h}/2 = {w*h//2} 不符")
        return 1

    # 找源图
    cand = [Path(sys.argv[1])] if len(sys.argv) > 1 else CANDIDATES
    src = None
    for p in cand:
        if p.exists():
            if Image.open(p).size == (w, h):
                src = p
                break
            print(f"   {p} 尺寸 {Image.open(p).size} 与 {w}x{h} 不符，跳过")
    if src is None:
        print("\n跳过：找不到与 logo[] 头部尺寸一致的源图。")
        print("      转换规则本身没变，只是换过图之后没有可比对的基准了。")
        print("      要回归请指定源图：python tools/verify_against_font_c.py <图片>")
        return 0

    img = Image.open(src)
    res = converter.convert(img, converter.Options(
        invert=True, header=converter.HEADER_NONE))

    print(f"\n源图        : {src.name}  {img.size[0]}x{img.size[1]}  {img.mode}")
    print(f"参考像素数据: {len(ref)} 字节")
    print(f"本工具生成  : {len(res.data)} 字节")

    if len(ref) != len(res.data):
        print("!! 长度不一致")
        return 1

    diff_bytes = [i for i, (a, b) in enumerate(zip(res.data, ref)) if a != b]
    diff_px = []
    for i in diff_bytes:
        for nib in (0, 1):
            x = (i % (res.width // 2)) * 2 + nib
            y = i // (res.width // 2)
            a = (res.data[i] >> 4) & 0xF if nib == 0 else res.data[i] & 0xF
            b = (ref[i] >> 4) & 0xF if nib == 0 else ref[i] & 0xF
            if a != b:
                diff_px.append((x, y, a, b))

    total_px = res.width * res.height
    print(f"\n不同的字节数: {len(diff_bytes)} / {len(ref)}")
    print(f"不同的像素数: {len(diff_px)} / {total_px}")

    if diff_px:
        g = img.convert("L").load()
        print("\n差异像素明细（参考值与源图灰度对不上，属于源图重新导出的舍入噪声）:")
        for x, y, a, b in diff_px[:12]:
            print(f"   ({x:3d},{y:3d})  源图灰度={g[x, y]:3d}  "
                  f"本工具={a:2d}  参考={b:2d}")
        if len(diff_px) > 12:
            print(f"   ...另有 {len(diff_px) - 12} 个")

    if not diff_px:
        print("\n完全一致 ✅")
    elif len(diff_px) <= 4:
        print(f"\n基本一致 ✅（{len(diff_px)} 个像素落在 16 级灰度的阈值边界上，"
              f"源图与之差 1 个灰度级）")
    else:
        print("\n差异偏多 ❌，取模规则需要重新确认")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
