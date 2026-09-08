# Images-to-PDF

一键把文件夹里的图片合并成多页 PDF（基于 IrfanView `/multipdf` 命令行）。

Turn an image folder into a single multi-page PDF in one shot — powered by IrfanView's `/multipdf` command line, no GUI clicking.

## Why this approach / 为什么用这种方式

Uses IrfanView's native command-line `/multipdf` instead of GUI automation (mouse clicks). It is faster, more reliable, works unattended, and handles more image formats including HEIC.

## Features / 功能特性

- 📁 Drag & drop a folder path into the console, press Enter → done
- 🗂️ **Batch mode** — drop a parent folder containing subfolders (e.g. TV episodes); each subfolder becomes its own PDF
- ♻️ **Keep running** — process multiple folders in one session; the console stays open until you close it
- 🛡️ Errors in one folder do **not** interrupt the loop — drop in the next folder right away
- 🖼️ Collects images from the **top level only** (no recursion into subfolders)
- 🔢 **Natural sort** — `2.jpg` comes before `10.jpg`
- 📄 Generates a multi-page PDF named after the folder
- ✅ Validates IrfanView and its PDF plugin before running
- 🔧 Smart IrfanView auto-detection (5 strategies, incl. resolving `IrfanView 64.lnk`)
- 🇨🇳 Localized Chinese console output
- ❌ Exit via `exit`/`quit`/`q`, `Ctrl+C`, or just closing the window

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

### Portable mode (no IrfanView install needed) / 便携模式（免安装 IrfanView）

Use `launcher.py` instead of `folder_to_pdf.py` to run **without pre-installing IrfanView**. It auto-downloads the official IrfanView-64 portable package + PDF plugin from `irfanview.info` into a local cache, verifies/extracts it, then runs the main script:

```bat
:: one-shot: download (if needed) & run
python launcher.py

:: force re-download of the latest version
python launcher.py --update

:: only download/extract the cache, don't run
python launcher.py --download-only
```

- **Cache location:** `%LOCALAPPDATA%\Images-to-PDF\irfanview\` (Windows) or `~/.local/share/images-to-pdf/irfanview/` (WSL/Linux).
- Downloads only from the **official** `irfanview.info` domain — no redistribution, EULA-friendly. SHA-256 verified by default (pass `--no-verify` if you repin a new version).
- First run needs internet; later runs are offline-ready once cached.
- Requires installed IrfanView? No — `launcher.py` uses the cache. `folder_to_pdf.py` (only) still probes the machine for an installed IrfanView.

## Usage / 使用方法

**Windows:** double-click `folder_to_pdf.py` (or run it from a terminal), drag your image folder into the console, and press **Enter**.

```
==================================================
图片合并成 PDF 工具
==================================================
处理完成后窗口不会关闭，可继续拖入其他文件夹。
输入 exit 或直接关闭窗口即可退出。
--------------------------------------------------
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：
```

The resulting PDF is written to the output directory (see configuration), named after your folder (e.g. `002_第2集.pdf`).

### Batch mode: a parent folder with subfolders / 批量模式：含子文件夹的父文件夹

If you drop a **parent folder** that contains subfolders with images (e.g. TV episodes), the script generates **one PDF per subfolder**, each named after that subfolder:

```
--------------------------------------------------
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：
检测到 80 个子文件夹，开始批量处理 ...
[1/80] 第1集 ...
✅ 生成成功！输出文件：C:\...\PDF_Output\第1集.pdf
[2/80] 第2集 ...
✅ 生成成功！输出文件：C:\...\PDF_Output\第2集.pdf
...
批量处理完成：成功 80 个，失败 0 个。
```

- Only subfolders that actually contain images are processed.
- A failed subfolder is reported and does **not** stop the rest of the batch.

### Process multiple folders in one session / 一次处理多个文件夹

The console **keeps running** after each conversion, so you can drag in one folder after another without restarting:

```
--------------------------------------------------
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：找到 104 张图片，正在生成 PDF ...
✅ 生成成功！
   输出文件：C:\...\PDF_Output\002_第2集.pdf
   页数（图片数）：104
--------------------------------------------------
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：   ← 窗口未关，可继续拖入
```

- An invalid folder path is reported but does **not** interrupt the loop.
- **Exit options:** type `exit` / `quit` / `q` and press Enter, press `Ctrl+C`, or just close the window.

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
3. `subfolders_with_images()` checks whether the dropped folder contains subfolders with images — if so, **batch mode** kicks in and each such subfolder is converted to its own PDF; otherwise a single PDF is produced from the folder itself.
4. `build_multipdf_cmd()` builds the IrfanView `/multipdf` command. The command is invoked with `shell=True` — passing it as a Python list would let Windows `list2cmdline` escape the embedded quotes and silently break IrfanView's `/multipdf=(...)` argument.
5. When the command line would exceed the limit, it falls back to a temporary file list (`filelist=`) written in ANSI encoding for Chinese-path compatibility, then cleans it up.
6. The script verifies the PDF was actually created before reporting success.

## Contribution / 贡献

Issues, feature requests, and pull requests are welcome.

## License / 许可证

MIT — see `LICENSE`.
