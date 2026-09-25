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

## Supported formats / 支持格式

`jpg` `jpeg` `png` `bmp` `tif` `tiff` `gif` `webp` `jfif` `avif` `heic`

## Requirements / 环境要求

- **Windows** 10+
- **Python 3.7+**（仅标准库，无需 pip install）
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
```

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

## Tests / 测试

```bash
python -m unittest test_folder_to_pdf -v   # 29 个测试
```

## License / 许可证

MIT — see `LICENSE`. IrfanView 由其官方分发，本项目仅调用其命令行，不重新分发其二进制。
