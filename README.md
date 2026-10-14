# ImageToSSD1322

SSD1322 单色灰度 OLED 的**位图取模工具**（PyQt5 图形界面）。

给一张任意图片（彩色会自动转灰度），生成可以直接贴进 `NTP_PRO_II/font.c` 的
C 数组，并给出宽高信息。

取模规则不是猜的：是拿现有的 `xaut_logo.bmp` 与 `font.c` 里真实的 `logo[]`
**逐字节反推并验证**出来的（见下面「规则是怎么确认的」）。

---

## 取模规则

```
半字节 = 15 - (灰度 >> 4)          // 取反后取高 4 位
字节   = (左像素 << 4) | 右像素     // 高 4 位是左边那个像素
排列   = 行正序（自上而下）、每行 宽/2 字节、连续存放
数据量 = 宽 × 高 ÷ 2 字节
```

三条要点：

1. **要高 4 位不要低 4 位。** 源图是 8 位灰度，屏上只有 16 级，砍掉低 4 位
   （`>> 4`）就等于按 16 级量化。
2. **要取反。** SSD1322 里 `0` 最暗、`15` 最亮，而位图习惯是"黑字白底"，
   所以 `15 - x` 把亮度翻过来。`LTMCU/util/conv.c` 里那两行被注释掉的
   `a = 0xFF - a;` 想干的就是这件事。
3. **高 4 位放左像素。** 这与驱动自己组装图标时用的半字节顺序一致 ——
   `oled.c` 的 `off_remap[] = {4, 0, 12, 8}` 就是"第 0 个像素放 bit4-7"。

> ⚠️ 注意 `conv.c` 并不完全是这样：它写的是 `(a >> 4) | (b & 0xF0)`，
> 把先读到的字节放进了**低** 4 位，和面板实际约定相反。
> 本工具按面板约定来（也就是按 `font.c` 里真实数组的约定来）。
> 另外 `conv.c` 也不做反相（那两行是注释掉的），而且它只处理 8 位数据，
> 喂 24 位 BMP 会错位。

### 尺寸要求

| 项 | 要求 | 为什么 |
|---|---|---|
| 宽 | 必须是 **4 的倍数** | `oledAddr()` 用 `x/4` 算列地址，列对不齐会横向错位 |
| 宽 | 必须是偶数 | 两像素拼一字节（4 的倍数已蕴含） |
| 高 | 建议 **8 的倍数** | `font.c` 的说明；`oledBinary()` 按 8 行一段处理 |
| 尺寸 | 不超过 **256×64** | 本驱动的屏（`oled.h` 的 `OLED_WIDTH/OLED_HEIGHT`） |

宽度不合法时工具会拒绝生成并说明原因；是偶数但不是 4 的倍数时会给警告但照常生成。

---

## 运行

```powershell
pip install -r requirements.txt
python main.py
```

依赖：Python 3.8+、PyQt5、Pillow。

> 启动时若刷出 `QFontDatabase: Cannot find font directory ...`，那是 PyQt5 自带的
> Qt5 没带字体目录导致的，**无害**，Windows 下会用系统字体正常显示，可以忽略。

### 界面说明

* **打开图片…** —— 支持 PNG/BMP/JPG/GIF/TIFF/WebP，彩色自动转灰度。
* **两个预览** —— 左边是灰度化后的原图，右边是"屏上实际效果"
  （已按规则量化并反相，1 像素 = 1 点，方便看细节有没有糊掉）。
* **取模选项**
  * *数组名* / *声明前缀* —— 默认 `logo` / `const static uint8_t`（与 `font.c` 一致）。
  * *数组开头写入宽高两个字节* —— 默认**开**，见下一节。
  * *反相* —— 默认**开**（现有 `logo[]` 的规则）。关掉它做出来的数组是负片。
  * *每行字节数* —— 默认 16。
  * *每行末尾加字节偏移注释* —— 调试大数组时好定位。
  * *缩放到指定尺寸* —— 默认关；开了会用 LANCZOS 重采样到指定宽高。
* **生成的数组定义** —— 只读文本框，**一键复制**直接进剪贴板，也可另存为文本。

---

## 数组头部的宽高

宽度最大就是屏宽 **256**，而 **256 装不进一个字节**（`uint8_t` 到 255 为止），
所以头部做成**自描述**的：

```
字节 0 : 尺寸描述符 —— 高 4 位 = 宽的字节数，低 4 位 = 高的字节数
字节 1+: 宽，小端
之后   : 高，小端
```

当前固定「宽 2 字节 + 高 1 字节」，所以描述符是 **(2 << 4) | 1 = 0x21**，
整个头部 **4 字节**：

```c
const static uint8_t logo[] = {
    0x21,0x40,0x00,0x30,   // 宽 64、高 48（0x21 = 宽 2 字节 + 高 1 字节）
    0x09,0xB5,0x00, ...
```

| 尺寸 | 头部 4 字节 |
|---|---|
| 64 × 48 | `0x21, 0x40, 0x00, 0x30` |
| 256 × 64 | `0x21, 0x00, 0x01, 0x40` |

生成时头部后面会跟一句注释写明真实尺寸，不用心算小端。

**为什么让首字节自描述字节数**：将来换一块高也超过 255 的屏，描述符写成 `0x22`、
高排 2 字节即可，读取端多认一个 `case`，数据格式的约定本身不用动。
界面里也可以选「无头部」，那时尺寸仍写死在 `fontSize()` 里。

### ⚠️ 光改头部还不够：`fontSize()` 的参数必须一起加宽

现在的签名是

```c
void fontSize(const uint8_t* font, uint8_t* w, uint8_t* h);
```

`w`/`h` 是 `uint8_t*`，`oled.c` 里的 `f_w / f_h` 也是 `uint8_t` ——
**就算头部存下了 256，这个值也传不出去**：`fontSize()` 只能回 0，
`oledBmpC(x - w/2, ...)` 就用了个错的宽度。所以 256 宽要真正能用，必须一起改：

```c
// font.h
void fontSize(const uint8_t* font, uint16_t* w, uint16_t* h);

// oled.c
uint16_t f_w, f_h;      // 原来是 uint8_t f_w, f_h, pos, off;
uint8_t  pos, off;
```

其余环节**本来就是 16 位的，不用动**：

* `oledBmpC / oledBmp / oledTransfer` 的 `w / h` 形参是 `uint16_t`
* `oledTransfer` 里 `f = w * h / 2`，256×64 → 8192，`f` 是 `uint16_t`，放得下
* `oledAddr` 算出的列地址：`x/4 + (w-1)/4` = 0 + 63 = 63，在 SSD1322 的范围内

> 另外：256 宽的数组只能走 `oledBmpC → oledBmp → oledTransfer`（整幅位图）。
> **别用 `oledBinary`** —— 它内部按 `FONT_MAX_WIDTH(16)` 开了 32 个 `uint16_t`
> 的行缓冲，256 宽会直接写穿。文字/图标才走那条路。

### 改 `fontSize()`

```c
void fontSize(const uint8_t* font, uint16_t* w, uint16_t* h) {
    if (font == font_8x8) {
        *w = 8; *h = 8;
    } else if (font == font_8x16) {
        *w = 8; *h = 16;
    } else if (font == logo) {
        /* 头部 4 字节：font[0] 是尺寸描述符（高 4 位 = 宽的字节数，
           低 4 位 = 高的字节数），后面依次是宽、高，都是小端。
           取模工具当前写 0x21 = 宽 2 字节 + 高 1 字节。 */
        switch (font[0]) {
            case 0x21:
                *w = (uint16_t) font[1] | ((uint16_t) font[2] << 8);
                *h = font[3];
                break;
            default:                    /* 认不出的格式，交回调用方判断 */
                *w = 0; *h = 0;
                break;
        }
    }
}
```

工具界面上选中某种头部格式后，输出框下方会直接给出对应的 `fontSize()` 代码。

**平滑迁移**：现有的 `logo[]` 是 64×48，头部 4 字节就是 `0x21,0x40,0x00,0x30`。
在数组的 `{` 后面插这一行即可，**1536 字节像素数据一个都不用动**，
固件行为也不会变（只是尺寸来源从硬编码换成了数组头）。

---

## 规则是怎么确认的

不是照着 `conv.c` 想当然，而是**用现有的图与数组做回归**。

`tools/` 下的脚本（都需要 Pillow）：

| 脚本 | 作用 |
|---|---|
| `analyze_packing.py` | 枚举行序/列序/半字节序/量化方式共 64 种组合，与真实 `logo[]` 逐字节比对 |
| `render_logo.py` | 把 `logo[]` 直接渲染成 PNG —— 一眼就能看出方向对不对 |
| `analyze_quant.py` | 统计「源图灰度值 → 参考半字节」的映射表，把量化规则精确挖出来 |
| `verify_against_font_c.py` | **回归测试**：`converter.py` 复现 `logo[]`，报告差异。尺寸从数组头部读；换过图之后找不到对应源图会**明确报跳过并返回 0**（不是失败）—— 要回归就 `python tools/verify_against_font_c.py <源图>` |
| `smoke_test_gui.py` | GUI 无人值守冒烟测试（`QT_QPA_PLATFORM=offscreen`），覆盖加载/三种头部格式/选项切换/尺寸校验/复制 |
| `test_converter.py` | `converter.py` 的单元测试（含**宽度 256 的头部编码**与彩色转灰度），并生成对照图 |

关键结论：

* 映射表完全干净 —— **每个灰度值都唯一对应一个半字节**，不存在二义性，
  规则就是 `15 - (g >> 4)`。（顺带排除了 `round(g*15/255)` 与 `floor(g*15/255)`：
  灰度 97 时前者给 9、后者给 10，而参考值是 9，只有 `g>>4` 对得上。）
* `verify_against_font_c.py` 的最终结果：**1536 字节里 2 个字节不同，
  3072 个像素里 2 个像素不同**。两个都在 `(34,38)` 与 `(51,43)`，
  源图灰度 175、规则要求 ≥176 —— 源图与生成数组时的版本差 1 个灰度级，
  不是规则问题。

跑一遍回归：

```powershell
python tools\verify_against_font_c.py
```

---

## 打包成 exe

```powershell
pip install pyinstaller

# 目录版（启动快，运行时不解包 —— **推荐日常用**）
python -m PyInstaller --noconfirm --clean --onedir  --windowed --name ImageToSSD1322 main.py
# -> dist_onedir\ImageToSSD1322\ImageToSSD1322.exe   约 137 MB / 229 个文件

# 单文件（好分发，但每次启动都要把 55MB 解到 %TEMP%\_MEIxxxx，冷启动慢）
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ImageToSSD1322 main.py
# -> dist\ImageToSSD1322.exe                         约 55 MB
```

两者都**不需要目标机器装 Python / PyQt5 / Pillow**。

### ⚠️ 单文件版可能起不来：`Could not create temporary directory!`

单文件版的启动器要先在 `%TEMP%` 下建一个 `_MEIxxxx` 目录再把内容解进去。
**有些机器上这一步会被拒**，表现为弹一个对话框（`--windowed` 下）或
`[PYI-xxxxx:ERROR] Could not create temporary directory!`（`--console` 下）。

实测记录（2026-10，PyInstaller 6.19 / Python 3.14 / PyQt5 5.15.11）：

| 做法 | 结果 |
|---|---|
| onefile，`%TEMP%` = 默认的用户 Temp | ✘ 失败 |
| onefile，`TEMP` 指向默认 Temp 下的**空子目录** | ✘ 也失败 → 与目录里的内容无关 |
| onefile，`TEMP` 指向 `E:\Works\...\rt` | ✔ 成功 |
| **hello-world** 的 onefile，`%TEMP%` = 默认 | ✔ 成功 |
| **onedir**（同一个包） | ✔ 成功 |
| `icacls <新目录> /inheritance:r /grant:r 本人:(F)` | ✔ 两边都成功 |

也就是说：**不是 DACL 权限的问题**（那一步能过），**也不是包的问题**（目录版和
换过 TEMP 的单文件版都跑得起来），而是**这台机器上"往默认 `%TEMP%` 里解包"这条路**
有问题。Defender 日志里没有拦截记录、受控文件夹访问也是关的，但 MDE 在运行，
所以怀疑是安全软件 / 完整性级别那一层，**根因未最终确认**。

**能用的两个办法：**

```powershell
# 1) 用目录版 —— 最省事，运行时根本不解包（见上面的 --onedir）

# 2) 仍要单文件，就把解包位置指到别处
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --runtime-tmpdir "D:\SomeWritableDir" --name ImageToSSD1322 main.py
```

判别"是不是只有这个工具这样"：拿**任何**别的 onefile 程序（比如 `yt-dlp.exe`）
在这台机器上跑一下。如果它也报同样的错，那就是机器级的问题 —— 社区里有同款报告
（[yt-dlp#12812](https://github.com/yt-dlp/yt-dlp/issues/12812)）。

排查技巧：先用 `--console` 再打一份。`--windowed` 会把 stdout/stderr 丢掉，
出错时除了一个对话框什么都看不到。

---

## 文件

```
ImageToSSD1322/
├── main.py                 PyQt5 界面
├── converter.py            转换核心（无 GUI 依赖，可单独导入/测试）
├── requirements.txt
├── README.md
├── dist/                   --onefile 产物
├── dist_onedir/            --onedir 产物
└── tools/
    ├── analyze_packing.py
    ├── analyze_quant.py
    ├── render_logo.py
    ├── verify_against_font_c.py
    ├── smoke_test_gui.py
    ├── test_converter.py
    └── out/                分析过程产出的对照图（可删）
```
