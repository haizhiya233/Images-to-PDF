# Images-to-PDF

一键把文件夹里的图片合并成多页 PDF（基于 IrfanView `/multipdf` 命令行）。

Turn image folders into multi-page PDFs — powered by IrfanView's `/multipdf` command line. No GUI clicking, no third-party Python deps.

## Features / 功能特性

- 📁 **一拖一按** — 拖入图片文件夹，按 Enter 自动转换
- 🗂️ **批量模式** — 拖入含多个子文件夹的父文件夹（如剧集），每个子文件夹各生成一个 PDF
- ♻️ **持续运行** — 处理完一个文件夹窗口不关闭，可继续拖入下一个
- 🛡️ **容错** — 单个文件夹失败不中断其余处理
- 🔢 **自然排序** — `2.jpg` 排在 `10.jpg` 之前
- ⚡ **并行处理** — 默认 16 线程并行批量转换（可按机器性能调整）
- 📊 **TUI 进度网格** — 实时方格进度 + 百分比 + ETA 预估
- 🗜️ **体积可控** — 自动把 PDF 插件切到 JPEG 压缩，输出约为素材的 **1.1 倍**（IrfanView 默认的 Flate 无损会膨胀 **4~17 倍**）
- 🔧 **智能探测** — 5 种策略自动定位 IrfanView
- 📦 **便携模式** — 免安装 IrfanView，自动下载官方包到临时缓存（退出即清）
- 🧯 **不吞错误** — 输出重定向到管道/日志时也不因 emoji 崩溃；临时文件在超时后同样会清理
- 📱 **手机版** — `feat/mobile` 分支提供 Termux + 浏览器方案，JPEG 原样嵌入 PDF（见下文）

## Supported formats / 支持格式

`jpg` `jpeg` `png` `bmp` `tif` `tiff` `gif` `webp` `jfif` `avif` `heic`

## Requirements / 环境要求

- **Windows** 10+
- **Python 3.7+**（仅标准库，无需 pip install；已在 3.14 上验证）
- **IrfanView 64** + 官方 **PDF 插件**（`Plugins/PDF.dll`）— 或用便携模式自动获取

## Quick Start / 快速开始

```bat
git clone https://github.com/haizhiya233/Images-to-PDF.git
cd Images-to-PDF

:: 方式一：已装 IrfanView，直接运行
python folder_to_pdf.py

:: 方式二：免安装 IrfanView（自动下载官方便携包）
python launcher.py
```

运行后把图片文件夹拖进窗口，按 **Enter** 开始。

## Usage / 使用方法

**单文件夹** — 拖入含图片的文件夹 → 生成同名 PDF。

**批量模式** — 拖入含子文件夹的父文件夹 → 每个子文件夹各生成一个 PDF，实时显示进度网格：

```
检测到 80 个子文件夹，开始批量处理...
进度：42/80 (52.5%) ETA: 120s
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ❌ ✅ ✅ ✅ ✅ ✅
⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳
批量处理完成：成功 78 个，失败 2 个。
```

**连续处理** — 窗口不关闭，可继续拖入下一个文件夹；输入 `exit`/`q`、`Ctrl+C` 或关闭窗口退出。

**直接传路径** — `python folder_to_pdf.py "D:\MyFolder"`

## PDF 体积 / Output Size

IrfanView 的 PDF 插件默认用 **Flate 无损**压缩：它会把每张 JPEG 解码成裸 RGB 再用
zlib 重新压缩。对漫画这类网点/线条素材几乎压不动，于是输出比源图大 4~17 倍，
**画质却毫无提升**。

本工具在每次运行前自动写入一份 IrfanView 配置（`i_view64.ini` 的 `[PDF]` 节），
把压缩方式改成 JPEG，并通过官方 `/ini=` 开关让 IrfanView 读取它：

| `PDF_COMPRESSION` | 实际压缩方式 | 相对源图体积 |
|---|---|---|
| 1 | Flate 无损（IrfanView 默认，不建议） | 4.6x |
| **2（默认）** | **JPEG q95** | **1.14x** |
| 3 | JPEG q80 | 0.89x |
| 4 | JPEG q65 | 0.79x |
| 5 | JPEG q40 | 0.44x |

> 实测数据（1988×3057、q80 的漫画页，源图 1.10 MB）：Flate 输出 5.07 MB，
> q95 输出 1.25 MB。**q95 与 Flate 的像素完全相同**，省下的体积纯属编码方式优化。
> 调到 3~5 会更小，但会引入一次可见的有损重编码。

配置写在脚本旁的 `.irfanview_ini/` 目录，**不需要管理员权限**，也不会改动
`Program Files` 里的 IrfanView 安装。

## Configuration / 配置

编辑 `folder_to_pdf.py` 顶部常量：

```python
OUTPUT_DIR = Path(r"C:\Users\YourName\Desktop\PDF_Output")  # 输出目录（必改）
MAX_WORKERS = 16                  # 批量并行线程数（默认 16）
GRID_WIDTH = 8                    # TUI 网格每行方格数
PDF_COMPRESSION = 2               # PDF 压缩：1=Flate 2=q95 3=q80 4=q65 5=q40
PDF_INI_DIR = Path(__file__).parent / ".irfanview_ini"   # IrfanView 配置目录
CMD_LENGTH_LIMIT = 3800           # 命令行超过此长度就改用临时文件列表
```

> `CMD_LENGTH_LIMIT` 平时不用动。图片路径总长超过它就自动回退到写一份临时
> 文件列表（`filelist=`）并把路径逐行写进去，因此**路径再长、中文再多也能处理**。
> 3800 是保守值，离 `cmd.exe` 的 8191 上限留了足够余量。

## Portable Mode / 便携模式

`launcher.py` 自动从官方 `irfanview.info` 下载 IrfanView-64 便携包 + PDF 插件，解压到 `%TEMP%` 缓存后运行；**退出时自动清理缓存，不占磁盘**。

```bat
python launcher.py               # 下载(如需) + 运行
python launcher.py --update      # 强制重新下载最新版
python launcher.py --download-only  # 只下载缓存，不运行
python launcher.py --keep-cache  # 保留缓存（默认退出即清）
python launcher.py --cleanup     # 手动清理缓存
```

- 仅从官方域名下载，已登记版本默认 SHA-256 校验；未登记版本需先补哈希或显式使用 `--no-verify`
- 首次运行需联网（~30MB）；`folder_to_pdf.py` 则使用本机已装的 IrfanView

## 手机版（Android / Termux）· feat/mobile 分支

> 本节内容只在 `feat/mobile` 分支存在。`main` 分支仍是纯 Windows + IrfanView 版。
> 手机版不依赖 IrfanView、不依赖任何第三方 Python 包，只用标准库 + `ffmpeg`。

### 为什么手机上要自己写 PDF

Windows 版靠 IrfanView 的 PDF 插件，插件把 JPEG 解码成裸 RGB 再用 Flate 重压一遍，
漫画素材会膨胀 4~17 倍。项目一直想做「JPEG 字节直通（`/DCTDecode`）」但被多格式
兼容成本挡住了。手机端直接自己写一个最小 PDF 容器，把这件事做掉：

| 输入 | 处理方式 | 画质 / 体积 |
|---|---|---|
| baseline JPEG（灰度/RGB、无旋转） | **字节原样嵌入**，不碰 ffmpeg | 像素完全一致，体积 = 源图之和 + 每页约 300B |
| progressive JPEG、CMYK、带 EXIF 旋转的手机照片 | ffmpeg 转 baseline JPEG | 一次有损重编码，q2 默认 |
| PNG / WebP / HEIC / AVIF / GIF / TIFF / BMP | ffmpeg 转 baseline JPEG | 同上 |

逐页流式写盘，内存里始终只有一页；原子落盘（同目录临时文件 + `os.replace`），
失败或点「停止」都不会留下半截 PDF。

### 启动

```bash
# Termux 里，第一次会自动装 ffmpeg、挂 wakelock
./start-mobile.sh --open

# 或者手动
python3 mobile_app.py                    # 只监听 127.0.0.1:8765
python3 mobile_app.py --open             # 顺便调起浏览器
python3 mobile_app.py --host 0.0.0.0     # 允许同局域网其他设备访问
```

手机浏览器打开 `http://127.0.0.1:8765`，界面是触摸优先的本地网页：

1. **选文件夹** — 点目录逐层进入（DCIM / Pictures / 下载快捷入口），或直接贴完整路径；
   中文、空格路径都能用，顶层图片有缩略图预览。
2. **设置** — 单个 PDF / 批量（每个子文件夹一个 PDF）、原尺寸 / A4 等比居中、
   非 JPEG 的转码质量、输出目录（默认 `/storage/emulated/0/Download/Images-to-PDF`，
   在「文件管理 → 下载」里直接能看）。
3. **转换** — 按页显示进度和「第 x/y 张（已转码）」，可随时点「停止」；
   完成后每个 PDF 一行结果，点「打开」直接调起手机 PDF 阅读器。

服务只监听回环地址，且把可浏览路径限制在手机存储 / Termux 家目录 / 临时目录内。
`termux-wake-lock` 会在启动脚本里挂上，息屏后仍能继续转换。

### 文件

| 文件 | 作用 |
|---|---|
| `pdf_builder.py` | 纯标准库 PDF 写入器：JPEG 头解析、EXIF 旋转识别、DCTDecode 直通、ffmpeg 转码、原子落盘 |
| `mobile_cli.py` | **Agent 直调主入口**：一次性转换，默认输出结构化 JSON |
| `mobile_app.py` | `http.server` 本地服务 + 手机网页 UI（浏览 / 缩略图 / 任务状态 / 取消 / 打开 PDF） |
| `start-mobile.sh` | Termux 一键启动网页版 |
| `test_mobile.py` | 29 个单元测试（不依赖手机，Windows/Linux 也能跑） |

### 给 Agent / 脚本用的 CLI（主要入口）

网页是给人点的；**自动化调用走 `i2p`**，它已装进 `~/.local/bin` 的 PATH，
跨会话可直接用。默认 stdout 输出结构化 JSON、进度日志走 stderr：

```bash
i2p --info                                      # 环境自检（ffmpeg / 输出目录 / Python）
i2p --list /sdcard/DCIM/Camera                  # 只探查：图片数、自然序、子文件夹
i2p /sdcard/DCIM/Camera --json                 # 单个 PDF → 默认输出目录
i2p /sdcard/DCIM/Camera -o /sdcard/Download/x.pdf --open
i2p /sdcard/DCIM --mode batch --page-size a4   # 每个子文件夹一个 PDF
i2p /sdcard/DCIM/Camera --human --quiet        # 人类可读输出、不打进度
```

返回示例（成功）：

```json
{
  "ok": true, "mode": "single", "page_size": "auto",
  "pdf_count": 1, "pages": 12,
  "results": [{"name": "Camera", "output": "/sdcard/Download/Images-to-PDF/Camera.pdf",
               "pages": 12, "size": 3456789, "size_h": "3.3 MB", "reencoded": 2}]
}
```

失败返回 `{"ok": false, "error": "..."}`，退出码 `0` 成功 / `1` 参数或转换失败 /
`2` 中断。网页版与 CLI 共用同一套 `pdf_builder` / `folder_to_pdf` 逻辑，不会走岔。

直接调 Python 库也行：

```python
from pathlib import Path
import pdf_builder
from folder_to_pdf import collect_images   # 复用自然排序、扩展名过滤

imgs = collect_images(Path("/storage/emulated/0/DCIM/Camera"))
pdf_builder.build_pdf(imgs, "/storage/emulated/0/Download/Camera.pdf",
                      page_size="a4", quality=2)
```

### 与 Windows 版共存

- 共用 `folder_to_pdf.py` 的 `IMAGE_EXTS` / `natural_key` / `subfolders_with_images`，
  不改动其中任何一行；Windows 版逻辑零影响。
- 云端 APK 打包（p4a）在历史上多次编译失败已移除；手机版走「Termux + 浏览器」，
  不需要 buildozer、不需要 root、不需要编译。

## Tests / 测试

```bash
python -m unittest test_folder_to_pdf -v   # 30 个测试（Windows 版）
python -m unittest test_mobile -v          # 29 个测试（手机端，含 CLI）
python -m unittest discover -v             # 59 个全跑
python -m py_compile *.py
```

`test_folder_to_pdf` 不依赖 IrfanView，Linux / WSL 上同样可以运行。
`test_mobile` 内置纯标准库构造的最小 JPEG，除一个 ffmpeg 转码用例（缺 ffmpeg 时自动
skip）外，Windows / Linux / Termux 全平台可跑。

## License / 许可证

MIT — see `LICENSE`. IrfanView 由其官方分发，本项目仅调用其命令行，不重新分发其二进制。
