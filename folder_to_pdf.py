#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把文件夹内的图片合并成一个多页 PDF（使用 IrfanView）— TUI 版本。

使用方法：
  1. 双击本脚本（或命令行运行）。
  2. 控制台提示时，把图片文件夹拖进窗口，按 Enter。
  3. 脚本自动收集该文件夹的图片，按文件名自然排序，
     然后调用 IrfanView 的 /multipdf 生成一个多页 PDF，保存到 OUTPUT_DIR。

两种模式：
  - 文件夹直接含图片：生成单个 PDF（以该文件夹名命名）。
  - 文件夹含子文件夹（且子文件夹有图片）：批量模式，美观 TUI 显示进度。

特色：
  - 每个任务用方格表示，支持 ✅/❌/⏳ 三种状态
  - 百分比进度条实时更新
  - 彩色输出（支持 Windows 10+）
  - 处理完成后窗口不会关闭，可继续拖入其他文件夹

修改输出目录：编辑下方 OUTPUT_DIR 常量即可。
依赖：Windows + 已安装 IrfanView 64（含 PDF 插件）+ Python 3。
"""

from pathlib import Path
import subprocess
import sys
import os
import re
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

# ================= 用户可修改区 =================
OUTPUT_DIR = Path(r"C:\Users\31657\Desktop\PDF_Output")  # 用户在此修改输出目录
MAX_WORKERS = 16  # 批量处理时的并行线程数
GRID_WIDTH = 8  # TUI 网格宽度（每行显示多少个方格）
# ===============================================

# 支持的图片扩展名（小写，忽略大小写）
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
    ".gif", ".webp", ".jfif", ".avif", ".heic",
}

# 全局 IrfanView 路径缓存（避免重复探测）
_irfanview_cache = None
_irfanview_lock = threading.Lock()
_irfanview_override = None

# 任务状态枚举
class TaskStatus:
    PENDING = "⏳"  # 等待中
    SUCCESS = "✅"  # 成功
    FAILED = "❌"   # 失败


def set_irfanview_override(path):
    """外部设置 IrfanView 可执行文件的偏好路径（便携版用），可传 None 清除。"""
    global _irfanview_override
    _irfanview_override = str(path) if path else None


def natural_key(name):
    """自然排序键：让 '2.jpg' 排在 '10.jpg' 前面。"""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", str(name))
    ]


def resolve_irfanview():
    """定位 i_view64.exe（或 i_view32.exe），返回 Path，找不到则抛 RuntimeError。
    
    首次调用会探测并缓存结果，后续调用直接返回缓存，避免重复的注册表查询和 PowerShell 调用。
    """
    global _irfanview_cache
    
    # 检查缓存（快速路径，无锁）
    if _irfanview_cache is not None:
        return _irfanview_cache
    
    # 线程安全的初始化
    with _irfanview_lock:
        # 再次检查（防止多线程间的竞态）
        if _irfanview_cache is not None:
            return _irfanview_cache
        
        # 外部覆盖优先（便携版）
        if _irfanview_override:
            p = Path(_irfanview_override)
            if p.exists():
                _irfanview_cache = p
                return p
        
        exe_name = "i_view64.exe"
        
        # 1. 解析 .lnk（最可靠，IrfanView 可能装在非标准位置）
        lnk = Path(r"C:\Users\Public\Desktop\IrfanView 64.lnk")
        if lnk.exists():
            try:
                ps = (
                    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('"
                    + str(lnk) + "'); $s.TargetPath"
                )
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=15,
                )
                target = res.stdout.strip()
                if target:
                    p = Path(target)
                    if p.exists():
                        _irfanview_cache = p
                        return p
            except Exception:
                pass
        
        # 2. 3. 常见安装目录
        for cand in [
            Path(r"C:\Program Files\IrfanView\i_view64.exe"),
            Path(r"C:\Program Files (x86)\IrfanView\i_view32.exe"),
        ]:
            if cand.exists():
                _irfanview_cache = cand
                return cand
        
        # 4. PATH
        import shutil
        for name in ("i_view64.exe", "i_view32.exe"):
            found = shutil.which(name)
            if found:
                p = Path(found)
                _irfanview_cache = p
                return p
        
        # 5. 注册表
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\IrfanView") as k:
                install_dir = winreg.QueryValueEx(k, "InstallDir")[0]
            p = Path(install_dir) / exe_name
            if p.exists():
                _irfanview_cache = p
                return p
        except Exception:
            pass
        
        raise RuntimeError(
            "找不到 IrfanView！请确认已安装 IrfanView 64（含 PDF 插件）。\n"
            "可尝试手动指定路径：修改 resolve_irfanview() 直接返回 Path(r'完整路径\\i_view64.exe')。"
        )


def check_pdf_plugin(irfan_dir):
    """检查 PDF 插件 PDF.dll 是否存在，缺失则抛 RuntimeError。"""
    dll = Path(irfan_dir) / "Plugins" / "PDF.dll"
    if not dll.exists():
        raise RuntimeError(
            "缺少 IrfanView 的 PDF 插件（PDF.dll）！\n"
            "请到 https://www.irfanview.net/main_plugins.htm 下载并安装官方的 PDF 插件包，"
            "确保 Plugins 目录下有 PDF.dll。"
        )


def collect_images(folder):
    """收集 folder 顶层（不递归）的图片文件，返回按自然序排序的 Path 列表。"""
    if not folder.is_dir():
        raise ValueError(f"不是有效的文件夹：{folder}")
    imgs = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    if not imgs:
        raise ValueError(f"文件夹中没有找到支持的图片：{folder}")
    imgs.sort(key=lambda p: natural_key(p.name))
    return imgs


def build_multipdf_cmd(irfan, output_pdf, image_paths):
    """构建 IrfanView /multipdf 命令行整串（用于 shell=True 调用）。

    命令行总长超过 3800 字符时，回退到写临时 ANSI 编码文件列表（filelist=）。
    返回 (cmd_string, temp_listfile_or_None)。
    """
    quoted = ",".join(f'"{p}"' for p in image_paths)
    direct = f'/multipdf=("{output_pdf}",{quoted})'
    full_len = len(str(irfan)) + 1 + len(direct) + len(" /cmdexit")
    if full_len <= 3800:
        cmd = f'"{irfan}" {direct} /cmdexit'
        return cmd, None

    # 回退到 filelist
    try:
        import codecs
        codecs.lookup("mbcs")
        enc = "mbcs"
    except LookupError:
        enc = sys.getdefaultencoding()

    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="irfan_pdf_")
    os.close(fd)
    win_path = tmp_path.replace("/", "\\")
    with open(tmp_path, "w", encoding=enc) as f:
        for p in image_paths:
            f.write(str(p).replace("/", "\\") + "\n")
    cmd = f'"{irfan}" /multipdf=("{output_pdf}",filelist="{win_path}") /cmdexit'
    return cmd, tmp_path


def prompt_folder():
    """提示并读取拖入的文件夹路径。"""
    raw = input("请把【图片文件夹】拖到此窗口，然后按 Enter 开始：").strip().strip('"')
    if not raw:
        return None
    if raw.lower() in ("exit", "quit", "q"):
        return None
    return raw


def convert_single_folder(folder, irfan):
    """把单个文件夹转成 PDF，返回生成的 PDF 路径或 None（失败时打印错误）。"""
    tmp_list = None
    try:
        images = collect_images(folder)
        
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_pdf = OUTPUT_DIR / f"{folder.name}.pdf"

        # 删除旧文件，避免 IrfanView 失败时把旧 PDF 误判为本次成功。
        if output_pdf.exists():
            output_pdf.unlink()

        cmd, tmp_list = build_multipdf_cmd(irfan, output_pdf, images)

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)

        if result.returncode == 0 and output_pdf.exists() and output_pdf.stat().st_size > 0:
            return output_pdf
    except Exception:
        return None
    finally:
        if tmp_list:
            try:
                os.unlink(tmp_list)
            except OSError:
                pass


def subfolders_with_images(folder):
    """返回 folder 下含图片的子文件夹，按自然序排序。"""
    subs = [
        p for p in folder.iterdir()
        if p.is_dir() and any(x.is_file() and x.suffix.lower() in IMAGE_EXTS for x in p.iterdir())
    ]
    subs.sort(key=lambda p: natural_key(p.name))
    return subs


class TUIProgressGrid:
    """TUI 进度网格：显示每个任务的状态方格。"""
    
    def __init__(self, total, grid_width=GRID_WIDTH):
        self.total = total
        self.grid_width = grid_width
        self.results = [TaskStatus.PENDING] * total
        self.start_time = time.time()
    
    def update(self, index, status):
        """更新第 index 个任务的状态。"""
        self.results[index] = status
    
    def render(self):
        """渲染进度网格。"""
        # 计算进度
        completed = sum(1 for r in self.results if r != TaskStatus.PENDING)
        percent = (completed / self.total) * 100
        elapsed = time.time() - self.start_time
        
        # 预计剩余时间
        if completed > 0 and completed < self.total:
            avg_time = elapsed / completed
            remaining = (self.total - completed) * avg_time
            eta = f" ETA: {int(remaining)}s"
        elif completed == self.total:
            eta = " ✓ 完成！"
        else:
            eta = ""
        
        print(f"\n进度：{completed}/{self.total} ({percent:.1f}%){eta}")
        print("-" * (self.grid_width * 2 + 5))
        
        # 绘制网格
        for i in range(0, self.total, self.grid_width):
            row = self.results[i:i + self.grid_width]
            print(" ".join(f"{status}" for status in row))
        
        print("-" * (self.grid_width * 2 + 5))


def convert_folder_batch(folder, irfan):
    """批量模式：并行处理所有子文件夹，使用 TUI 网格显示进度。"""
    subdirs = subfolders_with_images(folder)
    if not subdirs:
        return
    
    print(f"\n检测到 {len(subdirs)} 个子文件夹，开始批量处理...")
    print(f"并行线程数：{MAX_WORKERS}\n")
    
    # 创建 TUI 网格
    grid = TUIProgressGrid(len(subdirs), grid_width=GRID_WIDTH)
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, sub in enumerate(subdirs):
            future = executor.submit(convert_single_folder, sub, irfan)
            futures[future] = i
        
        for future in as_completed(futures):
            idx = futures[future]
            try:
                result = future.result()
                status = TaskStatus.SUCCESS if result else TaskStatus.FAILED
            except Exception:
                status = TaskStatus.FAILED
            
            grid.update(idx, status)
            grid.render()
    
    # 统计结果
    success = sum(1 for r in grid.results if r == TaskStatus.SUCCESS)
    failed = sum(1 for r in grid.results if r == TaskStatus.FAILED)
    
    print(f"\n✓ 批量处理完成：成功 {success} 个，失败 {failed} 个。")


def convert_folder(raw):
    """把文件夹转成 PDF。两种模式：单个或批量。"""
    folder = Path(raw)
    try:
        if not folder.exists():
            raise ValueError(f"文件夹不存在：{folder}")
        if not folder.is_dir():
            raise ValueError(f"路径不是文件夹：{folder}")

        # 只探测一次 IrfanView（后续调用直接返回缓存）
        irfan = resolve_irfanview()
        print(f"\n✓ IrfanView: {irfan}")
        check_pdf_plugin(irfan.parent)

        subdirs = subfolders_with_images(folder)
        if subdirs:
            convert_folder_batch(folder, irfan)
            return

        # 单个文件夹模式
        print("\n处理单个文件夹...")
        images = collect_images(folder)
        print(f"找到 {len(images)} 张图片，正在生成 PDF ...")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_pdf = OUTPUT_DIR / f"{folder.name}.pdf"

        # 与批量模式一致，避免失败时沿用旧 PDF。
        if output_pdf.exists():
            output_pdf.unlink()

        cmd, tmp_list = build_multipdf_cmd(irfan, output_pdf, images)

        print("正在调用 IrfanView 生成 PDF ...")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)

        if tmp_list:
            try:
                os.unlink(tmp_list)
            except Exception:
                pass

        if result.returncode == 0 and output_pdf.exists() and output_pdf.stat().st_size > 0:
            print("\n✅ 生成成功！")
            print(f"   输出文件：{output_pdf}")
            print(f"   页数（图片数）：{len(images)}")
        else:
            stderr = (result.stderr or "")[-400:]
            print(f"\n❌ 生成失败：{stderr}")

    except Exception as e:
        print(f"\n❌ 出错了：{e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="图片合并成 PDF 工具（TUI 版本）")
    parser.add_argument("--irfanview-path", help="指定 i_view64.exe 路径")
    parser.add_argument("folder", nargs="?", help="直接传入文件夹路径")
    args = parser.parse_args()

    if args.irfanview_path:
        set_irfanview_override(args.irfanview_path)

    # 启用 Windows 10+ 的 ANSI 颜色支持
    if sys.platform == "win32":
        os.system("mode con: cols=120 lines=40")

    print("=" * 50)
    print("图片合并成 PDF 工具 (TUI 版本)")
    print("=" * 50)
    print("处理完成后窗口不会关闭，可继续拖入其他文件夹。")
    print("输入 exit / quit / q 或直接关闭窗口即可退出。")

    while True:
        try:
            print("-" * 50)
            if args.folder:
                raw = args.folder
                args.folder = None
            else:
                raw = prompt_folder()
                if raw is None:
                    print("已退出。")
                    break
            
            convert_folder(raw)
        
        except KeyboardInterrupt:
            print("\n已退出。")
            break
        except Exception as e:
            print(f"\n❌ 出错：{e}")


if __name__ == "__main__":
    main()
