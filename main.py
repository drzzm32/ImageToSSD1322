"""
ImageToSSD1322 —— SSD1322 单色灰度位图取模工具（PyQt5）

用法：
    pip install PyQt5 Pillow
    python main.py

打开任意图片（彩色会自动转灰度），工具会按 NTP_PRO_II / font.c 里 logo[]
的规则生成 C 数组，并给出宽高信息与可直接粘贴的定义。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import converter                                       # noqa: E402
from converter import ConvertError, Options, OLED_HEIGHT, OLED_WIDTH  # noqa: E402

PREVIEW_W, PREVIEW_H = 300, 160


def pil_to_pixmap(im: Image.Image) -> QPixmap:
    """PIL 灰度图 → QPixmap。QImage 不复制传入的缓冲，所以这里必须 copy()。"""
    if im.mode != "L":
        im = im.convert("L")
    w, h = im.size
    data = im.tobytes("raw", "L")
    qimg = QImage(data, w, h, w, QImage.Format_Grayscale8)
    return QPixmap.fromImage(qimg.copy())


class PreviewBox(QLabel):
    """固定大小的预览框，图按比例缩放居中。"""

    def __init__(self, title: str, smooth: bool):
        super().__init__()
        self._smooth = smooth
        self.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.setAlignment(Qt.AlignCenter)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("background:#101010; color:#888;")
        self.setText(f"（{title}）")
        self._pix: QPixmap | None = None

    def set_image(self, im: Image.Image | None):
        if im is None:
            self._pix = None
            self.setText("（无）")
            return
        self._pix = pil_to_pixmap(im)
        self._rescale()

    def _rescale(self):
        if self._pix is None:
            return
        mode = Qt.SmoothTransformation if self._smooth else Qt.FastTransformation
        self.setPixmap(self._pix.scaled(PREVIEW_W - 4, PREVIEW_H - 4,
                                        Qt.KeepAspectRatio, mode))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImageToSSD1322 —— SSD1322 灰度位图取模工具")
        self.resize(1060, 780)

        self.img: Image.Image | None = None      # 原始 PIL 图
        self.path: Path | None = None
        self.result: converter.Result | None = None

        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # --- 第一行：打开 / 信息
        top = QHBoxLayout()
        self.btn_open = QPushButton("打开图片…")
        self.btn_open.clicked.connect(self.on_open)
        top.addWidget(self.btn_open)

        self.lbl_file = QLabel("未打开图片")
        self.lbl_file.setStyleSheet("color:#444;")
        top.addWidget(self.lbl_file, 1)
        outer.addLayout(top)

        # --- 第二行：两个预览 + 选项
        mid = QHBoxLayout()
        mid.setSpacing(10)

        prev_box = QVBoxLayout()
        prev_box.addWidget(self._caption("原图（灰度）"))
        self.prev_src = PreviewBox("原图", smooth=True)
        prev_box.addWidget(self.prev_src)
        prev_box.addWidget(self._caption("转换后（屏上效果，1 像素 = 1 点）"))
        self.prev_out = PreviewBox("转换后", smooth=False)
        prev_box.addWidget(self.prev_out)
        prev_box.addStretch(1)
        mid.addLayout(prev_box)

        mid.addWidget(self._build_options(), 0)
        outer.addLayout(mid)

        # --- 输出
        out_box = QGroupBox("生成的数组定义")
        out_lay = QVBoxLayout(out_box)
        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.txt.setFont(f)
        self.txt.setLineWrapMode(QPlainTextEdit.NoWrap)
        out_lay.addWidget(self.txt)

        btn_row = QHBoxLayout()
        self.lbl_fontsize = QLabel("")
        self.lbl_fontsize.setStyleSheet("color:#666;")
        btn_row.addWidget(self.lbl_fontsize, 1)

        self.btn_save = QPushButton("保存为文本…")
        self.btn_save.clicked.connect(self.on_save)
        btn_row.addWidget(self.btn_save)

        self.btn_copy = QPushButton("一键复制")
        self.btn_copy.setMinimumWidth(110)
        self.btn_copy.clicked.connect(self.on_copy)
        btn_row.addWidget(self.btn_copy)
        out_lay.addLayout(btn_row)

        outer.addWidget(out_box, 1)

        self.status = self.statusBar()

    def _caption(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet("color:#333; font-weight:bold;")
        return lb

    def _build_options(self) -> QGroupBox:
        box = QGroupBox("取模选项")
        box.setFixedWidth(360)
        g = QGridLayout(box)
        g.setVerticalSpacing(6)
        r = 0

        g.addWidget(QLabel("数组名"), r, 0)
        self.ed_name = QLineEdit("logo")
        self.ed_name.textChanged.connect(self._refresh)
        g.addWidget(self.ed_name, r, 1)
        r += 1

        g.addWidget(QLabel("声明前缀"), r, 0)
        self.cb_decl = QComboBox()
        self.cb_decl.setEditable(True)
        self.cb_decl.addItems([
            "const static uint8_t",
            "const uint8_t",
            "static uint8_t",
            "uint8_t",
        ])
        self.cb_decl.currentTextChanged.connect(self._refresh)
        g.addWidget(self.cb_decl, r, 1)
        r += 1

        g.addWidget(QLabel("数组头部（记录宽高，供 fontSize 读）"), r, 0, 1, 2)
        r += 1
        self.cb_header = QComboBox()
        for fmt in converter.HEADER_FORMATS:
            self.cb_header.addItem(converter.HEADER_LABELS[fmt], fmt)
        self.cb_header.setCurrentIndex(
            converter.HEADER_FORMATS.index(converter.HEADER_TAGGED)
        )
        self.cb_header.setToolTip(
            "宽度最大等于屏宽 256，一个字节装不下，所以头部是自描述的：\n"
            "    字节 0 : 尺寸描述符 —— 高 4 位 = 宽的字节数，低 4 位 = 高的字节数\n"
            "    字节 1+: 宽，小端\n"
            "    之后   : 高，小端\n"
            "当前固定 2 + 1，所以描述符是 0x21，整个头部 4 字节。\n"
            "将来换高也超过 255 的屏，描述符写 0x22 即可，读取端多认一个 case。\n\n"
            "两种格式都要求 fontSize() 的 w/h 参数加宽成 uint16_t。"
        )
        self.cb_header.currentIndexChanged.connect(self._refresh)
        g.addWidget(self.cb_header, r, 0, 1, 2)
        r += 1

        self.ck_invert = QCheckBox("反相（现有 logo[] 的规则）")
        self.ck_invert.setChecked(True)
        self.ck_invert.setToolTip(
            "SSD1322 里 0 最暗、15 最亮；位图习惯是黑字白底，\n"
            "所以要取反：半字节 = 15 - (灰度 >> 4)。"
        )
        self.ck_invert.toggled.connect(self._refresh)
        g.addWidget(self.ck_invert, r, 0, 1, 2)
        r += 1

        g.addWidget(QLabel("每行字节数"), r, 0)
        self.sp_perline = QSpinBox()
        self.sp_perline.setRange(4, 64)
        self.sp_perline.setValue(16)
        self.sp_perline.valueChanged.connect(self._refresh)
        g.addWidget(self.sp_perline, r, 1)
        r += 1

        self.ck_offset = QCheckBox("每行末尾加字节偏移注释")
        self.ck_offset.toggled.connect(self._refresh)
        g.addWidget(self.ck_offset, r, 0, 1, 2)
        r += 1

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#ccc;")
        g.addWidget(sep, r, 0, 1, 2)
        r += 1

        self.ck_resize = QCheckBox("缩放到指定尺寸")
        self.ck_resize.toggled.connect(self._on_resize_toggle)
        g.addWidget(self.ck_resize, r, 0, 1, 2)
        r += 1

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("宽"))
        self.sp_w = QSpinBox()
        self.sp_w.setRange(4, 4096)
        self.sp_w.setValue(64)
        self.sp_w.valueChanged.connect(self._refresh)
        size_row.addWidget(self.sp_w)
        size_row.addWidget(QLabel("高"))
        self.sp_h = QSpinBox()
        self.sp_h.setRange(1, 4096)
        self.sp_h.setValue(48)
        self.sp_h.valueChanged.connect(self._refresh)
        size_row.addWidget(self.sp_h)
        size_row.addWidget(QLabel(f"（本屏 {OLED_WIDTH}x{OLED_HEIGHT}）"))
        g.addLayout(size_row, r, 0, 1, 2)
        r += 1

        self._set_resize_enabled(False)

        hint = QLabel(
            "尺寸要求：宽必须是 4 的倍数（驱动用 x/4 算列地址），\n"
            "高度建议 8 的倍数。"
        )
        hint.setStyleSheet("color:#666; font-size:11px;")
        g.addWidget(hint, r, 0, 1, 2)
        r += 1

        g.setRowStretch(r, 1)
        return box

    def _set_resize_enabled(self, on: bool):
        self.sp_w.setEnabled(on)
        self.sp_h.setEnabled(on)

    def _on_resize_toggle(self, on: bool):
        self._set_resize_enabled(on)
        if on and self.img is not None:
            self.sp_w.setValue(self.img.size[0])
            self.sp_h.setValue(self.img.size[1])
        self._refresh()

    # --------------------------------------------------------------- 行为
    def load_image(self, path: str | Path) -> bool:
        """读取图片并刷新。返回是否成功。（on_open() 与自动化测试都走这里）"""
        try:
            im = Image.open(path)
            im.load()
        except Exception as e:                          # noqa: BLE001
            return False
        self.path = Path(path)
        self.img = im
        self.lbl_file.setText(
            f"{self.path.name}   原始 {im.size[0]}x{im.size[1]}  {im.mode}"
        )
        if self.ck_resize.isChecked():
            self.sp_w.setValue(im.size[0])
            self.sp_h.setValue(im.size[1])
        self._refresh()
        return True

    def on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.bmp *.jpg *.jpeg *.gif *.tif *.tiff *.webp);;所有文件 (*)"
        )
        if not path:
            return
        if not self.load_image(path):
            QMessageBox.critical(self, "打不开", f"无法读取这张图片：\n{path}")

    def _options(self) -> Options:
        return Options(
            invert=self.ck_invert.isChecked(),
            header=self.cb_header.currentData() or converter.HEADER_TAGGED,
            name=self.ed_name.text().strip() or "logo",
            decl=self.cb_decl.currentText().strip() or "const static uint8_t",
            per_line=self.sp_perline.value(),
            line_offset_comment=self.ck_offset.isChecked(),
        )

    def _work_image(self) -> Image.Image | None:
        if self.img is None:
            return None
        im = self.img.convert("L")
        if self.ck_resize.isChecked():
            im = im.resize((self.sp_w.value(), self.sp_h.value()), Image.LANCZOS)
        return im

    def _refresh(self):
        im = self._work_image()
        opt = self._options()

        if im is None:
            self.prev_src.set_image(None)
            self.prev_out.set_image(None)
            self.txt.setPlainText(
                "打开一张图片开始。\n\n"
                "取模规则（与 font.c 的 logo[] 一致）：\n"
                "    半字节 = 15 - (灰度 >> 4)        // 取反后取高 4 位\n"
                "    字节   = (左像素 << 4) | 右像素\n"
                "    排列   = 行正序、自上而下、每行 宽/2 字节"
            )
            self.lbl_fontsize.setText("")
            self.status.showMessage("就绪")
            return

        self.prev_src.set_image(im)

        try:
            res = converter.convert(im, opt)
        except ConvertError as e:
            self.prev_out.set_image(None)
            self.result = None
            self.txt.setPlainText(f"// 无法生成：\n// {e}")
            self.lbl_fontsize.setText("")
            self.status.showMessage(f"错误：{e}".replace("\n", " "))
            return

        self.result = res
        self.prev_out.set_image(converter.nibbles_to_image(res.nibbles))
        self.txt.setPlainText(converter.format_c_array(res, opt))

        if opt.with_header:
            self.lbl_fontsize.setText(converter.FONTSIZE_HINT.get(opt.header, ""))
            self.lbl_fontsize.setToolTip(
                converter.FONTSIZE_TOOLTIP.get(opt.header, "")
            )
        else:
            self.lbl_fontsize.setText("")
            self.lbl_fontsize.setToolTip("")

        head = (f"{res.width}x{res.height}   数据 {len(res.data)} 字节"
                f"   数组共 {res.byte_count} 字节"
                f"（占 FLASH {res.byte_count} B）")
        if res.warnings:
            self.status.showMessage("⚠ " + "  |  ".join(res.warnings))
            self.status.setStyleSheet("color:#b00;")
        else:
            self.status.showMessage("✔ " + head)
            self.status.setStyleSheet("")

    def on_copy(self):
        text = self.txt.toPlainText()
        if not text.strip():
            self.status.showMessage("没有可复制的内容")
            return
        QApplication.clipboard().setText(text)
        n = self.result.byte_count if self.result else 0
        self.status.showMessage(f"已复制到剪贴板（数组 {n} 字节）")

    def on_save(self):
        text = self.txt.toPlainText()
        if not text.strip():
            self.status.showMessage("没有可保存的内容")
            return
        default = (self.path.stem if self.path else "logo") + "_array.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存数组定义", default, "文本 (*.txt);;C 源文件 (*.c);;所有文件 (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(text + "\n", encoding="utf-8")
        except Exception as e:                          # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.status.showMessage(f"已保存到 {path}")


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
