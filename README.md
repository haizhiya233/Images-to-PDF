# Images-to-PDF

一键把文件夹里的图片合并成多页 PDF（基于 IrfanView `/multipdf` 命令行）。

Turn an image folder into a single multi-page PDF in one shot — powered by IrfanView's `/multipdf` command line, no GUI clicking.

## Why this approach / 为什么用这种方式

Uses IrfanView's native command-line `/multipdf` instead of GUI automation (mouse clicks). It is faster, more reliable, works unattended, and handles more image formats including HEIC.

## Features / 功能特性

- 📁 Drag & drop a folder path into the console, press Enter → done
- 🖼️ Collects images from the **top level only** (no recursion into subfolders)
- 🔢 **Natural sort** — `2.jpg` comes before `10.jpg`
- 📄 Generates a multi-page PDF named after the folder
- ✅ Validates IrfanView and its PDF plugin before running
- 🔧 Smart IrfanView auto-detection (5 strategies, incl. resolving `IrfanView 64.lnk`)
- 🇨🇳 Localized Chinese console output

## Supported image formats / 支持的图片格式

`jpg` `jpeg` `png` `bmp` `tif` `tiff` `gif` `webp` `jfif` `avif` `heic`

## Requirements / 环境要求

- **Windows** (the script calls IrfanView's Windows executable)
- **Python 3.7+**
- **IrfanView 64** with the official **PDF plugin** (`Plugins/PDF.dll`)

> IrfanView download: https://www.irfanview.net/
> PDF plugin: https://www.irfanview.net/main_plugins.htm

## Installation / 安装

No external dependencies — uses only the Python standard library.

```bat
:: clone, then run
git clone https://github.com/haizhiya233/Images-to-PDF.git
cd Images-to-PDF
```

## Usage / 使用方法

**Windows:** double-click `folder_to_pdf.py` (or run it from a terminal), drag your image folder into the console, and press **Enter**.

```
==================================================
图片合并成 PDF 工具
==================================================
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：
```

The resulting PDF is written to the output directory (see configuration), named after your folder (e.g. `001_第1集.pdf`).

### Configure the output directory / 修改输出目录

Edit the `OUTPUT_DIR` constant at the top of `folder_to_pdf.py`:

```python
# ================= 用户可修改区 =================
OUTPUT_DIR = Path(r"C:\Users\31657\Desktop\PDF_Output")  # 用户在此修改输出目录
# ===============================================
```

## Tests / 测试

Run the bundled unit tests (works on any platform with Python):

```bash
python -m unittest test_folder_to_pdf -v
```

## How it works / 工作原理

1. `resolve_irfanview()` locates IrfanView via 5 strategies: resolve the desktop `.lnk` target → check standard install paths → scan `PATH` → query the Windows registry → raise a helpful error.
2. `collect_images()` gathers top-level images and natural-sorts them by filename.
3. `build_multipdf_cmd()` builds the IrfanView `/multipdf` command. The command is invoked with `shell=True` — passing it as a Python list would let Windows `list2cmdline` escape the embedded quotes and silently break IrfanView's `/multipdf=(...)` argument.
4. When the command line would exceed the limit, it falls back to a temporary file list (`filelist=`) written in ANSI encoding for Chinese-path compatibility, then cleans it up.
5. The script verifies the PDF was actually created before reporting success.

## Contribution / 贡献

Issues, feature requests, and pull requests are welcome.

## License / 许可证

MIT — see `LICENSE`.
