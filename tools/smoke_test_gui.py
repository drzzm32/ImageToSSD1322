"""
GUI 冒烟测试（无需显示器）：
    set QT_QPA_PLATFORM=offscreen
    python tools/smoke_test_gui.py

做三件事：
  1. 真的把 MainWindow 建起来（会暴露导入/控件/信号连接的问题）
  2. 载入 xaut_logo.bmp，检查生成的数组头几行与字节数
  3. 切一遍各个选项，确认不会抛异常，并检查头部开关的效果
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt5.QtWidgets import QApplication      # noqa: E402
import main as app_main                       # noqa: E402
import converter                              # noqa: E402

BMP = Path(r"E:\Works\LTMCU\res\xaut_logo.bmp")

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


app = QApplication(sys.argv)
w = app_main.MainWindow()

print("1) 构造窗口")
check(w is not None, "MainWindow 构造成功")
check(w.txt.toPlainText().strip() != "", "未打开图片时也有提示文本")

print("\n2) 载入 xaut_logo.bmp")
ok = w.load_image(BMP)
check(ok, "load_image 返回成功")
check(w.result is not None, "生成了结果")
if w.result:
    check(w.result.width == 64 and w.result.height == 48,
          f"尺寸 64x48（实际 {w.result.width}x{w.result.height}）")
    check(len(w.result.data) == 1536, f"像素数据 1536 字节（实际 {len(w.result.data)}）")

text = w.txt.toPlainText()
print("\n--- 默认输出前 5 行 ---")
for line in text.splitlines()[:5]:
    print("   " + line)
check(text.startswith("const static uint8_t logo[] = {"), "数组声明行正确")
check("0x21,0x40,0x00,0x30," in text,
      "默认头部 = 0x21,0x40,0x00,0x30,（描述符 0x21 + 宽 64 小端 + 高 48）")
check("宽 64、高 48" in text, "头部注释写明了真实尺寸，不用心算小端")
check("0x09,0xB5" in text, "数据首两字节为 0x09,0xB5（与 font.c 的 logo[] 一致）")
check(w.result is not None and w.result.byte_count == 1536 + converter.HEADER_SIZE,
      f"含头部共 {1536 + converter.HEADER_SIZE} 字节"
      f"（实际 {w.result.byte_count if w.result else '-'}）")

print("\n3) 切换头部格式")
w.cb_header.setCurrentIndex(w.cb_header.findData(converter.HEADER_NONE))
check("0x21,0x40,0x00,0x30," not in w.txt.toPlainText(), "无头部：没有头部行")
check(w.result is not None and w.result.byte_count == 1536,
      f"无头部 1536 字节（实际 {w.result.byte_count if w.result else '-'}）")

w.cb_header.setCurrentIndex(w.cb_header.findData(converter.HEADER_TAGGED))
check("0x21,0x40,0x00,0x30," in w.txt.toPlainText(), "切回自描述头部正常")

print("\n4) 关掉反相")
w.ck_invert.setChecked(False)
check("0x09,0xB5" not in w.txt.toPlainText(), "不反相时数据确实变了")
w.ck_invert.setChecked(True)

print("\n5) 每行 8 字节 + 偏移注释")
w.sp_perline.setValue(8)
w.ck_offset.setChecked(True)
lines = w.txt.toPlainText().splitlines()
import re                                     # noqa: E402
off_lines = [ln for ln in lines if re.search(r"//\s+\d+\s*$", ln)]
check(len(off_lines) > 0, f"出现了偏移注释（{len(off_lines)} 行）")
if off_lines:
    print("     例:", off_lines[0].strip())
    print("     例:", off_lines[1].strip())
body = [ln for ln in lines if ln.strip().startswith("0x")]
# 计数只算注释之前的部分 —— 头部注释里本身也带 "0x21" 字样
hexcounts = [len(re.findall(r"0x[0-9A-F]{2}", ln.split("//")[0])) for ln in body]
check(hexcounts[0] == converter.HEADER_SIZE,
      f"头部行是 {converter.HEADER_SIZE} 字节（实际 {hexcounts[0]}）")
data_counts = hexcounts[1:]
check(data_counts and all(c == 8 for c in data_counts),
      f"所有数据行都是 8 字节（实际出现 {sorted(set(data_counts))}）")
w.sp_perline.setValue(16)
w.ck_offset.setChecked(False)

print("\n6) 改数组名 / 声明前缀")
w.ed_name.setText("my_logo")
w.cb_decl.setCurrentText("const uint8_t")
check(w.txt.toPlainText().startswith("const uint8_t my_logo[] = {"), "声明可自定义")
w.ed_name.setText("logo")
w.cb_decl.setCurrentText("const static uint8_t")

print("\n7) 打开缩放（改成 128x32）")
w.ck_resize.setChecked(True)
w.sp_w.setValue(128)
w.sp_h.setValue(32)
check(w.result is not None and w.result.width == 128 and w.result.height == 32,
      f"缩放生效（实际 {w.result.width}x{w.result.height}）")
check(w.result is not None and len(w.result.data) == 128 * 32 // 2,
      "缩放后字节数 = 宽*高/2")
w.ck_resize.setChecked(False)

print("\n8) 非法宽度（63）应给出错误而不是崩溃")
w.ck_resize.setChecked(True)
w.sp_w.setValue(63)
w.sp_h.setValue(32)
check(w.result is None, "奇数宽度被拒绝")
check("无法生成" in w.txt.toPlainText(), "文本框里给出了原因")
check("4 的倍数" in w.txt.toPlainText() or "奇数" in w.txt.toPlainText(),
      "错误信息提到了宽度要求")

print("\n9) 宽度 62（偶数但非 4 的倍数）应给警告但可生成")
w.sp_w.setValue(62)
w.sp_h.setValue(32)
check(w.result is not None, "仍能生成")
check(bool(w.result.warnings), "给出了警告")
if w.result:
    print("     警告:", " | ".join(w.result.warnings))
w.ck_resize.setChecked(False)

print("\n10) 复制到剪贴板")
w.on_copy()
cb = QApplication.clipboard().text()
check(cb.strip() != "", "剪贴板拿到了内容")
check(cb.startswith("const static uint8_t"), "剪贴板内容就是数组定义")

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("全部通过 ✅")
