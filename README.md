# Images-to-PDF

一键把文件夹里的图片合并成多页 PDF（基于 IrfanView `/multipdf` 命令行）。

Turn an image folder into a single multi-page PDF in one shot — powered by IrfanView's `/multipdf` command line, no GUI clicking.

## Why this approach / 为什么用这种方式

Uses IrfanView's native command-line `/multipdf` instead of GUI automation (mouse clicks). It is faster, more reliable, works unattended, and handles more image formats including HEIC.

## Features / 功能特性

### Core Features / 核心功能
- 📁 **一拖一按** — 拖入图片文件夹，按 Enter，自动转换
- 🗂️ **批量处理** — 父文件夹含多个子文件夹时，自动批量转换（如电视剧集）
- ♻️ **持续运行** — 处理完一个文件夹后窗口不关闭，可继续拖入下一个
- 🛡️ **容错处理** — 某个文件夹转换失败不会中断后续处理
- 🖼️ **仅顶层** — 只收集顶层图片，不递归子文件夹
- 🔢 **智能排序** — 自然排序，`2.jpg` 排在 `10.jpg` 之前
- 📄 **自动命名** — PDF 自动以文件夹名命名

### Performance & UX / 性能和用户体验
- ⚡ **并行处理** — 4 线程并行转换，批量处理快 **3-4 倍**（对比逐个处理）
- 🎨 **TUI 进度网格** — 美观的方格网格显示每个任务状态
- 📊 **百分比进度** — 实时显示进度百分比（0-100%）
- ⏱️ **ETA 预估** — 动态计算剩余时间
- 🔒 **缓存优化** — IrfanView 路径缓存到内存，首次探测后无重复开销
- 🧹 **内存清理** — 进程退出时自动清除，不占磁盘

### Advanced / 高级特性
- ✅ 转换前验证 IrfanView 和 PDF 插件是否存在
- 🔧 **智能探测** — 5 种策略检测 IrfanView（快捷方式 → 标准路径 → PATH → 注册表）
- 🇨🇳 **本地化输出** — 中文界面和提示
- ❌ **灵活退出** — 输入 `exit`/`quit`/`q`、`Ctrl+C` 或直接关闭窗口即可退出

## Supported image formats / 支持的图片格式

`jpg` `jpeg` `png` `bmp` `tif` `tiff` `gif` `webp` `jfif` `avif` `heic`

## Requirements / 环境要求

- **Windows** 10+ （脚本调用 IrfanView 的 Windows 可执行文件）
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

Use `launcher.py` instead of `folder_to_pdf.py` to run **without pre-installing IrfanView**. It auto-downloads the official IrfanView-64 portable package + PDF plugin from `irfanview.info`.

```bat
:: 一行命令：自动下载（如需）并运行
python launcher.py

:: 强制重新下载最新版本
python launcher.py --update

:: 只下载/提取，不运行
python launcher.py --download-only

:: 保留缓存不删除（默认会自动清理）
python launcher.py --keep-cache

:: 清理缓存并退出
python launcher.py --cleanup
```

**Portable Mode Details:**
- **缓存位置（临时）：** `%TEMP%\Images-to-PDF\irfanview\` (Windows) 或 `~/.local/share/images-to-pdf/irfanview/` (WSL/Linux)
- **自动清理：** 退出时自动删除缓存（关闭窗口/shutdown），不占磁盘。传入 `--keep-cache` 保留缓存，或 `--cleanup` 手动清理
- **安全下载：** 仅从官方 `irfanview.info` 域名下载，SHA-256 验证（`--no-verify` 跳过）
- **首次联网：** 首次运行需要网络下载 ~30MB 包；后续如未清理缓存则直接使用本地版本
- **无需预装：** `launcher.py` 使用便携版。`folder_to_pdf.py` 只支持预装的 IrfanView

## Usage / 使用方法

### Quick Start / 快速开始

**Windows 用户：** 双击 `folder_to_pdf.py`，或在终端运行：

```bash
python folder_to_pdf.py
```

系统会显示提示信息，拖入图片文件夹，按 **Enter** 开始转换。

### User Interface / 用户界面

#### Single folder mode / 单个文件夹模式

拖入包含图片的文件夹，自动生成单个 PDF：

```
==================================================
图片合并成 PDF 工具 (TUI 版本)
==================================================
处理完成后窗口不会关闭，可继续拖入其他文件夹。
输入 exit / quit / q 或直接关闭窗口即可退出。
--------------------------------------------------
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：D:\MyPhotos

✓ IrfanView: C:\Program Files\IrfanView\i_view64.exe

处理单个文件夹...
找到 100 张图片，正在生成 PDF ...
正在调用 IrfanView 生成 PDF ...

✅ 生成成功！
   输出文件：C:\...\PDF_Output\MyPhotos.pdf
   页数（图片数）：100
```

#### Batch mode with TUI progress grid / 批量模式 + TUI 进度网格

拖入包含多个子文件夹的父文件夹（如包含多个电视剧集的文件夹），系统自动进入**批量模式**，显示实时的方格进度网格：

```
检测到 80 个子文件夹，开始批量处理...
并行线程数：4

进度：0/80 (0.0%)
--------------------------------------------------------------------
⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳
⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳
⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳
...
--------------------------------------------------------------------

进度：42/80 (52.5%) ETA: 120s
--------------------------------------------------------------------
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ❌ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ⏳ ⏳
✅ ✅ ✅ ✅ ✅ ⏳ ⏳ ⏳
⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳ ⏳
--------------------------------------------------------------------

进度：80/80 (100.0%) ✓ 完成！
--------------------------------------------------------------------
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ❌ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
--------------------------------------------------------------------

✓ 批量处理完成：成功 78 个，失败 2 个。
```

**Grid Legend / 网格说明：**
- ⏳ 等待中（任务队列中）
- ✅ 成功（PDF 已生成）
- ❌ 失败（转换出错）

### Process multiple folders / 处理多个文件夹

窗口保持运行，可继续拖入下一个文件夹，无需重启：

```
--------------------------------------------------
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：D:\Folder1
[处理完成]
--------------------------------------------------
请把【图片文件夹】拖到此窗口，然后按 Enter 开始：D:\Folder2  ← 直接拖入下一个
```

### Configure the output directory / 修改输出目录

编辑 `folder_to_pdf.py` 顶部的 `OUTPUT_DIR` 常量：

```python
# ================= 用户可修改区 =================
OUTPUT_DIR = Path(r"C:\Users\YourName\Desktop\PDF_Output")  # 改成你的输出目录
MAX_WORKERS = 4                                             # 并行线程数（可选）
GRID_WIDTH = 8                                              # 网格宽度（可选）
# ===============================================
```

**参数说明：**
- `OUTPUT_DIR` — PDF 输出目录（必改）
- `MAX_WORKERS` — 批量处理时的并行线程数，默认 4（建议 = CPU 核数）
- `GRID_WIDTH` — TUI 网格每行显示的方格数，默认 8

## Performance / 性能对比

### 批量处理 80 个文件夹（每个 100 张图片）的性能

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| **IrfanView 探测次数** | 80 次 | 1 次 | **80 倍** |
| **并行处理** | 逐个 | 4 线程 | **3-4 倍** |
| **总处理时间** | ~40 分钟 | ~10 分钟 | **快 3-4 倍** |
| **内存占用** | 随文件数增长 | 恒定 | **内存优化** |
| **缓存清理** | 磁盘残留 | 进程结束自清 | **干净** |
| **用户体验** | 无进度反馈 | 实时网格 + ETA | **显著提升** |

## Tests / 测试

Run the bundled unit tests (works on any platform with Python):

```bash
python -m unittest test_folder_to_pdf -v
```

**Test Coverage / 测试覆盖：**
- ✅ 自然排序逻辑
- ✅ 图片收集（顶层、扩展名过滤）
- ✅ 命令构建（长路径回退）
- ✅ 批量模式检测
- ✅ IrfanView 覆盖机制
- ✅ 共 18 个单元测试

## How it works / 工作原理

1. **IrfanView 探测** — `resolve_irfanview()` 通过 5 种策略定位 IrfanView（快捷方式解析 → 标准路径 → PATH 环境变量 → Windows 注册表），结果缓存到内存避免重复
2. **图片收集** — `collect_images()` 收集顶层图片，按自然序排序（1, 2, 10 而非 1, 10, 2）
3. **模式检测** — `subfolders_with_images()` 检测文件夹是否含子文件夹；有则进入**批量模式**并行处理，无则单个处理
4. **命令构建** — `build_multipdf_cmd()` 构建 IrfanView 的 `/multipdf` 命令；超过 3800 字符时回退到临时文件列表
5. **并行转换** — `ThreadPoolExecutor` 4 线程并行执行，实时更新 TUI 网格和 ETA
6. **验证成功** — 检查 PDF 是否生成且大小 > 0，确保转换成功

**Key Implementation Details:**
- 使用 `shell=True` 保留命令中的引号（避免 Windows 转义）
- ANSI 编码支持中文路径
- 线程安全的 IrfanView 缓存（使用 Lock）

## Advanced Usage / 高级用法

### 命令行直接传入文件夹

```bash
python folder_to_pdf.py "D:\MyFolder"
```

### 便携版使用

```bash
# 自动下载 + 运行
python launcher.py

# 只下载不运行
python launcher.py --download-only

# 下载特定版本
python launcher.py --version 475
```

### 指定 IrfanView 路径（开发者用）

```bash
python folder_to_pdf.py --irfanview-path "C:\Program Files\IrfanView\i_view64.exe"
```

## FAQ / 常见问题

### Q: 为什么需要安装 IrfanView？
A: IrfanView 的 `/multipdf` 命令行是生成 PDF 的核心。Python 标准库没有高效的多页 PDF 生成工具，IrfanView 既轻量又功能完整。

### Q: 支持递归子文件夹吗？
A: 不支持。只收集顶层图片，避免无意中混合多个文件夹的图片。如需递归，可先手动组织结构。

### Q: 图片排序不对？
A: 确保图片名称包含数字（如 `001.jpg` 而非 `a.jpg`）。脚本使用自然排序，不会出现 `10.jpg` 排在 `2.jpg` 前的情况。

### Q: 如何修改输出目录？
A: 编辑 `folder_to_pdf.py` 顶部的 `OUTPUT_DIR` 常量，改成你的目标路径。

### Q: 支持命令行批处理吗？
A: 支持直接传入路径：`python folder_to_pdf.py "D:\Folder"`。可配合 Windows 批处理脚本实现自动化。

### Q: 处理大量文件会不会很慢？
A: 不会。支持 4 线程并行（可配置），批量处理快 3-4 倍。同时 IrfanView 路径缓存到内存，避免重复探测。

## Contribution / 贡献

Issues, feature requests, and pull requests are welcome! 欢迎提交 Issue、功能建议和 PR。

## License / 许可证

MIT — see `LICENSE`.

## Changelog / 更新日志

### v2.0.0 (Latest / 最新)
- ✨ **TUI 进度网格** — 美观的方格显示，每个任务一个方格
- ✨ **百分比进度** — 实时显示 0-100% 的进度百分比
- ✨ **ETA 预估** — 动态计算剩余处理时间
- ⚡ **并行处理** — 4 线程批量转换，快 3-4 倍
- 🔒 **缓存优化** — IrfanView 路径缓存到内存，进程结束自清
- 🐛 **线程安全** — 使用 Lock 保护缓存初始化

### v1.0.0
- 基础功能：图片转 PDF、批量处理、自然排序
- IrfanView 自动探测
- 中文界面
