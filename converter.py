"""
图像 → SSD1322 4 位灰度数组的转换核心。

本模块**不依赖任何 GUI**，可以单独导入、单独测试。

取模规则（由 NTP_PRO_II/font.c 里现有的 logo[] 反推并逐字节验证，见 tools/）：
  * 半字节   = 15 - (灰度 >> 4)          —— 即"取反后取高 4 位"
  * 字节     = (左像素 << 4) | 右像素     —— 高 4 位是左边的像素
  * 排列     = 行正序（自上而下）、每行 width/2 字节、连续存放
  * 反相     = 源图的黑（0）→ 屏上最亮（15），源图的白（255）→ 屏上最暗（0）

为什么是"取反"：SSD1322 里 0 是最暗、15 是最亮，而位图习惯是"黑字白底"，
所以要把亮度反过来；这正是 LTMCU/util/conv.c 里那两行被注释掉的
`a = 0xFF - a;` 想做的事。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from PIL import Image

# 本驱动用的屏（oled.h 里的 OLED_WIDTH / OLED_HEIGHT）
OLED_WIDTH = 256
OLED_HEIGHT = 64

# 驱动对尺寸的硬性要求：oledAddr() 用 x/4 算列地址，所以宽度必须是 4 的倍数；
# 高度建议 8 的倍数（oledBinary 按 8 行一段处理；整幅位图用的是 oledTransfer，
# 不强制，但按 font.c 的说明统一要求更省心）。
WIDTH_MULTIPLE = 4
HEIGHT_MULTIPLE = 8


# ---------------------------------------------------------------- 数组头部
#
# 数组开头可以放一段头部记录宽高，这样 fontSize() 就不用把尺寸写死。
#
#   字节 0 : 尺寸描述符 —— 高 4 位 = 宽的字节数，低 4 位 = 高的字节数
#   字节 1+: 宽，小端
#   之后   : 高，小端
#
# 宽度最大等于屏宽 256，**一个字节装不下**，所以宽要 2 字节；高最大 64，
# 1 字节够。于是描述符 = (2 << 4) | 1 = **0x21**，整个头部 4 字节：
#
#   0x21, 0x00, 0x01, 0x40      // 宽 256、高 64
#   0x21, 0x40, 0x00, 0x30      // 宽  64、高 48
#
# 好处是自描述：将来换一块高也超过 255 的屏，描述符写成 0x22、高排 2 字节，
# 读取端只需多认一个 case，不用改数据格式的约定。
#
# ⚠️ fontSize() 现在收的是 uint8_t*，**就算头部存了 256 也传不出去**，
#    必须一起把它的 w/h 参数加宽成 uint16_t。
HEADER_NONE = "none"
HEADER_TAGGED = "tagged"

HEADER_FORMATS = (HEADER_NONE, HEADER_TAGGED)
HEADER_LABELS = {
    HEADER_NONE: "无头部（尺寸由 fontSize() 写死）",
    HEADER_TAGGED: "0x21 + 宽16位 + 高8位（4 字节，自描述）",
}

WIDTH_BYTES = 2
HEIGHT_BYTES = 1
HEADER_TAG = (WIDTH_BYTES << 4) | HEIGHT_BYTES          # 0x21
HEADER_SIZE = 1 + WIDTH_BYTES + HEIGHT_BYTES            # 4

WIDEN_WARNING = "fontSize() 的 w/h 参数要一起加宽成 uint16_t，否则 256 传不出去"

FONTSIZE_HINT = {
    HEADER_NONE: "",
    HEADER_TAGGED: "fontSize(): *w = font[1] | (font[2]<<8);  *h = font[3];"
                   "   ⚠ w/h 需为 uint16_t",
}
FONTSIZE_TOOLTIP = {
    HEADER_NONE: "",
    HEADER_TAGGED: (
        "数组头部 4 字节：\n"
        "    font[0] = 0x21  高4位=宽的字节数(2)，低4位=高的字节数(1)\n"
        "    font[1..2] = 宽，小端\n"
        "    font[3] = 高\n\n"
        "fontSize() 里改成:\n"
        "    switch (font[0]) {\n"
        "        case 0x21:\n"
        "            *w = (uint16_t) font[1] | ((uint16_t) font[2] << 8);\n"
        "            *h = font[3];\n"
        "            break;\n"
        "        default:\n"
        "            *w = 0; *h = 0;\n"
        "            break;\n"
        "    }\n\n" + WIDEN_WARNING + "。"
    ),
}


@dataclass
class Options:
    """取模与输出格式的全部选项。"""

    invert: bool = True                 # 上面的"取反"
    header: str = HEADER_TAGGED         # 头部格式，见上面的 HEADER_*
    name: str = "logo"                  # 数组名
    decl: str = "const static uint8_t"  # 声明前缀（要与 font.c 里一致）
    per_line: int = 16                  # 每行几个字节
    line_offset_comment: bool = False   # 每行末尾加字节偏移注释
    comment: str = ""                   # 数组上方的一行说明注释（可为空）
    header_comment: bool = True         # 头部后面加 "// 宽 xx、高 xx" 注释

    @property
    def with_header(self) -> bool:
        return self.header != HEADER_NONE

    def clone(self, **kw) -> "Options":
        d = dict(self.__dict__)
        d.update(kw)
        return Options(**d)


@dataclass
class Result:
    """一次转换的全部产物。"""

    width: int
    height: int
    nibbles: List[List[int]]            # 每像素 0..15（已经是屏上的亮度）
    data: bytes                         # 只有像素数据（不含头部）
    payload: bytes                      # 实际写进数组的内容（可能含头部）
    warnings: List[str] = field(default_factory=list)

    @property
    def byte_count(self) -> int:
        return len(self.payload)

    @property
    def screen_ascii(self) -> str:
        """把结果画成字符画，便于在没有屏的时候肉眼确认。"""
        ramp = " .:-=+*#%@"
        out = []
        for row in self.nibbles:
            out.append("".join(ramp[min(9, v * 10 // 16)] for v in row))
        return "\n".join(out)


class ConvertError(Exception):
    pass


def _check_size(w: int, h: int) -> List[str]:
    warns: List[str] = []
    if w % 2 != 0:
        raise ConvertError(
            f"宽度 {w} 是奇数，无法两像素拼一字节。\n"
            f"请把宽度改成 {WIDTH_MULTIPLE} 的倍数（驱动要求）。"
        )
    if w % WIDTH_MULTIPLE != 0:
        warns.append(
            f"宽度 {w} 不是 {WIDTH_MULTIPLE} 的倍数：oledAddr() 用 x/4 算列地址，"
            f"列对不齐会出现横向错位。建议改成 {WIDTH_MULTIPLE} 的倍数。"
        )
    if h % HEIGHT_MULTIPLE != 0:
        warns.append(
            f"高度 {h} 不是 {HEIGHT_MULTIPLE} 的倍数：按 font.c 的说明，"
            f"纵向应为 {HEIGHT_MULTIPLE} 的倍数。"
        )
    if w > OLED_WIDTH or h > OLED_HEIGHT:
        warns.append(
            f"尺寸 {w}x{h} 超过本屏的 {OLED_WIDTH}x{OLED_HEIGHT}，"
            f"整幅显示时会被截断。"
        )
    return warns


def check_header(w: int, h: int, fmt: str) -> None:
    """头部编码能否表示这个尺寸。"""
    if fmt == HEADER_TAGGED:
        if w >> (8 * WIDTH_BYTES) or h >> (8 * HEIGHT_BYTES):
            raise ConvertError(
                f"头部描述符 0x{HEADER_TAG:02X}（宽 {WIDTH_BYTES} 字节、"
                f"高 {HEIGHT_BYTES} 字节）装不下 {w}x{h}。"
            )
    elif fmt != HEADER_NONE:
        raise ConvertError(f"未知的头部格式: {fmt}")


def build_header(w: int, h: int, fmt: str) -> bytes:
    """生成头部字节。"""
    check_header(w, h, fmt)
    if fmt == HEADER_NONE:
        return b""
    # 描述符 + 宽（小端，WIDTH_BYTES 字节）+ 高（小端，HEIGHT_BYTES 字节）
    out = bytearray([HEADER_TAG])
    for i in range(WIDTH_BYTES):
        out.append((w >> (8 * i)) & 0xFF)
    for i in range(HEIGHT_BYTES):
        out.append((h >> (8 * i)) & 0xFF)
    assert len(out) == HEADER_SIZE
    return bytes(out)


def to_nibbles(img: Image.Image, invert: bool = True) -> List[List[int]]:
    """灰度化 → 每像素 0..15。"""
    g = img.convert("L")
    w, h = g.size
    px = g.load()
    rows: List[List[int]] = []
    for y in range(h):
        row = []
        for x in range(w):
            v = px[x, y] >> 4            # 取高 4 位：0..15
            row.append((15 - v) if invert else v)
        rows.append(row)
    return rows


def nibbles_to_bytes(rows: List[List[int]]) -> bytes:
    """两像素拼一字节，高 4 位放左边那个。"""
    out = bytearray()
    for row in rows:
        for i in range(0, len(row), 2):
            out.append(((row[i] & 0x0F) << 4) | (row[i + 1] & 0x0F))
    return bytes(out)


def nibbles_to_image(rows: List[List[int]]) -> Image.Image:
    """把半字节还原成灰度图（值 ×17），用来预览"屏上会是什么样"。"""
    h = len(rows)
    w = len(rows[0]) if h else 0
    im = Image.new("L", (w, h), 0)
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = rows[y][x] * 17
    return im


def convert(img: Image.Image, opt: Optional[Options] = None) -> Result:
    """主入口：PIL 图像 → Result。"""
    opt = opt or Options()
    g = img.convert("L")
    w, h = g.size
    warns = _check_size(w, h)
    check_header(w, h, opt.header)

    rows = to_nibbles(g, opt.invert)
    data = nibbles_to_bytes(rows)
    payload = build_header(w, h, opt.header) + data
    return Result(width=w, height=h, nibbles=rows, data=data,
                  payload=payload, warnings=warns)


def header_c_line(w: int, h: int, fmt: str, comment: bool = True) -> str:
    """头部那一行的 C 源码。"""
    if fmt == HEADER_NONE:
        return ""
    raw = build_header(w, h, fmt)
    text = "    " + ",".join(f"0x{b:02X}" for b in raw) + ","
    if comment:
        text += f"   // 宽 {w}、高 {h}（0x{HEADER_TAG:02X} = 宽 {WIDTH_BYTES} 字节 + 高 {HEIGHT_BYTES} 字节）"
    return text


def format_c_array(res: Result, opt: Optional[Options] = None) -> str:
    """按 font.c 的风格生成 C 数组定义。"""
    opt = opt or Options()
    lines: List[str] = []

    if opt.comment:
        for c in opt.comment.splitlines():
            lines.append(f"// {c}")

    lines.append(f"{opt.decl} {opt.name}[] = {{")

    body: List[str] = []
    head_line = header_c_line(res.width, res.height, opt.header, opt.header_comment)
    if head_line:
        body.append(head_line)

    per = max(1, opt.per_line)
    offset = len(res.payload) - len(res.data)      # 头部占的字节数
    for i in range(0, len(res.data), per):
        chunk = res.data[i:i + per]
        tail = f"   // {offset + i:4d}" if opt.line_offset_comment else ""
        body.append("    " + ",".join(f"0x{b:02X}" for b in chunk) + f",{tail}")

    lines.extend(body)
    lines.append("};")
    return "\n".join(lines)


def fontsize_snippet(name: str = "logo") -> str:
    """启用头部后，fontSize() 里对应的改法（含 uint16_t 加宽）。"""
    return (
        f"    }} else if (font == {name}) {{\n"
        f"        /* 头部 4 字节：font[0] 是尺寸描述符（高 4 位 = 宽的字节数，\n"
        f"           低 4 位 = 高的字节数），后面依次是宽、高，都是小端。\n"
        f"           取模工具当前写 0x{HEADER_TAG:02X} = 宽 {WIDTH_BYTES} 字节 + "
        f"高 {HEIGHT_BYTES} 字节。 */\n"
        f"        switch (font[0]) {{\n"
        f"            case 0x{HEADER_TAG:02X}:\n"
        f"                *w = (uint16_t) font[1] | ((uint16_t) font[2] << 8);\n"
        f"                *h = font[3];\n"
        f"                break;\n"
        f"            default:                    /* 认不出的格式，交回调用方判断 */\n"
        f"                *w = 0; *h = 0;\n"
        f"                break;\n"
        f"        }}\n"
        f"    }}"
    )
