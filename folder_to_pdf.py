#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把文件夹内的图片合并成一个多页 PDF（使用 IrfanView）。

使用方法：
  1. 双击本脚本（或命令行运行）。
  2. 控制台提示时，把图片文件夹拖进窗口，按 Enter。
  3. 脚本自动收集该文件夹的图片，按文件名自然排序，
     然后调用 IrfanView 的 /multipdf 生成一个多页 PDF，保存到 OUTPUT_DIR。

两种模式：
  - 文件夹直接含图片：生成单个 PDF（以该文件夹名命名）。
  - 文件夹含子文件夹（且子文件夹有图片）：批量模式，每个子文件夹各生成一个 PDF。

处理完成后窗口不会关闭，可继续把其他文件夹拖进窗口继续工作；
输入 exit/quit/q 或直接关闭窗口即退出。

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

# ================= 用户可修改区 =================
OUTPUT_DIR = Path(r"C:\Users\31657\Desktop\PDF_Output")  # 用户在此修改输出目录
MAX_WORKERS = 4  # 批量处理时的并行线程数
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

    按顺序尝试：
      0. 外部通过 set_irfanview_override 指定的路径（便��版用）
      1. Powershell 解析桌面快捷方式 IrfanView 64.lnk 的目标路径
      2. C:\\Program Files\\IrfanView\\i_view64.exe
      3. C:\\Program Files (x86)\\IrfanView\\i_view32.exe
      4. shutil.which("i_view64.exe") / ("i_view32.exe")
      5. 注册表 HKCU\\Software\\IrfanView 的 InstallDir
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
        raise ValueError(f"文件夹中没有找到支持的图片（{sorted(IMAGE_EXTS)}）：{folder}")
    imgs.sort(key=lambda p: natural_key(p.name))
    return imgs


def build_multipdf_cmd(irfan, output_pdf, image_paths):
    """构建 IrfanView /multipdf 命令行整串（用于 shell=True 调用）。

    关键：Windows 下 subprocess.run(列表) 会用 list2cmdline 重写命令，内嵌引号被转义，
    导致 IrfanView 的 /multipdf=(...) 参数被拆碎而静默失败。因此必须返回整串字符串，
    用 shell=True 传参，引号原样保留。

    命令行总长超过 3800 字符时，回退到写临时 ANSI 编码文件列表（filelist=）。
    返回 (cmd_string, temp_listfile_or_None)。
    """
    quoted = ",".join(f'"{p}"' for p in image_paths)
    direct = f'/multipdf=("{output_pdf}",{quoted})'
    full_len = len(str(irfan)) + 1 + len(direct) + len(" /cmdexit")
    if full_len <= 3800:
        cmd = f'"{irfan}" {direct} /cmdexit'
        return cmd, None

    # mbcs 是 Windows 专属编码；非 Windows 平台（WSL/Linux）无法识别，回退系统默认编码
    try:
        import codecs
        codecs.lookup("mbcs")
        enc = "mbcs"
    except LookupError:
        enc = sys.getdefaultencoding()

    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="irfan_pdf_")
    os.close(fd)
    # 注入命令的是 Windows 反斜杠路径（IrfanView 需要），真实路径用于读写与清理
    win_path = tmp_path.replace("/", "\\")
    with open(tmp_path, "w", encoding=enc) as f:
        for p in image_paths:
            f.write(str(p).replace("/", "\\") + "\n")
    cmd = f'"{irfan}" /multipdf=("{output_pdf}",filelist="{win_path}") /cmdexit'
    return cmd, tmp_path


def prompt_folder():
    """提示并读取拖入的文件夹路径，支持 exit/quit/q/空输入退出。返回路径字符串或 None。"""
    raw = input("请把【图片文件夹】拖到此窗口，然后按 Enter 开始：").strip().strip('"')
    if not raw:
        return None
    if raw.lower() in ("exit", "quit", "q"):
        return None
    return raw


def convert_single_folder(folder, irfan):
    """把单个文件夹转成 PDF，返回生成的 PDF 路径或 None（失败时打印错误）。

    此函数不做路径校验（由调用方负责），集中处理从收集图片到生成 PDF 的完整流程。
    """
    images = collect_images(folder)
    print(f"找到 {len(images)} 张图片，正在生成 PDF ...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_pdf = OUTPUT_DIR / f"{folder.name}.pdf"

    cmd, tmp_list = build_multipdf_cmd(irfan, output_pdf, images)
    if tmp_list:
        print(f"图片较多，已使用文件列表方式：{tmp_list}")

    print("正在调用 IrfanView 生成 PDF ...")
    try:
        # shell=True 必须：列表传参的 list2cmdline 会转义 /multipdf=(...) 内嵌引号，导致 IrfanView 静默失败
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise RuntimeError("IrfanView 处理超时（>600 秒），可能图片过多或插件异常。")

    # 清理临时文件列表
    if tmp_list:
        try:
            os.unlink(tmp_list)
        except Exception:
            pass

    if output_pdf.exists() and output_pdf.stat().st_size > 0:
        print("\n✅ 生成成功！")
        print(f"   输出文件：{output_pdf}")
        print(f"   页数（图片数）：{len(images)}")
        return output_pdf
    else:
        stderr = (result.stderr or "")[-400:]
        raise RuntimeError(f"IrfanView 未生成 PDF。退出码：{result.returncode}\n{stderr}")


def subfolders_with_images(folder):
    """返回 folder 下含图片的子文件夹，按自然序排序；无则返回空列表。"""
    subs = [
        p for p in folder.iterdir()
        if p.is_dir() and any(x.is_file() and x.suffix.lower() in IMAGE_EXTS for x in p.iterdir())
    ]
    subs.sort(key=lambda p: natural_key(p.name))
    return subs


def convert_folder_batch(folder, irfan):
    """批量模式：并行处理所有子文件夹，带进度条。"""
    subdirs = subfolders_with_images(folder)
    if not subdirs:
        return
    
    print(f"\n检测到 {len(subdirs)} 个子文件夹，开始批量处理 ...")
    
    # 简单进度条
    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, sub in enumerate(subdirs, 1):
            future = executor.submit(convert_single_folder, sub, irfan)
            futures[future] = (i, sub.name, len(subdirs))
        
        for future in as_completed(futures):
            idx, name, total = futures[future]
            try:
                result = future.result()
                if result:
                    ok += 1
                    status = "✅"
                else:
                    fail += 1
                    status = "❌"
            except Exception as e:
                fail += 1
                status = "❌"
                print(f"   ❌ 该子文件夹转换失败：{e}")
            
            # 显示进度条
            progress = f"[{ok + fail}/{total}]"
            print(f"\r{progress} {status} {name:<30}", end="", flush=True)
        
        print()  # 换行
    
    print(f"\n批量处理完成：成功 {ok} 个，失败 {fail} 个。")


def convert_folder(raw):
    """把文件夹转成 PDF。

    两种模式：
      - 若文件夹直接含图片 -> 生成单个 PDF。
      - 若文件夹含子文件夹（且子文件夹有图片）-> 批量模式，每个子文件夹各生成一个 PDF。
    成功或失败都会打印结果，不抛出未捕获异常。
    """
    folder = Path(raw)
    try:
        if not folder.exists():
            raise ValueError(f"文件夹不存在：{folder}")
        if not folder.is_dir():
            raise ValueError(f"路径不是文件夹：{folder}")

        # 只探测一次 IrfanView（后续调用直接返回缓存）
        irfan = resolve_irfanview()
        print(f"IrfanView: {irfan}")
        check_pdf_plugin(irfan.parent)

        subdirs = subfolders_with_images(folder)
        if subdirs:
            convert_folder_batch(folder, irfan)
            return

        # 单个文件夹模式
        convert_single_folder(folder, irfan)

    except Exception as e:
        print(f"\n❌ 出错了：{e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="图片合并成 PDF 工具（基于 IrfanView）")
    parser.add_argument("--irfanview-path", help="指定 i_view64.exe 路径（便携版由 launcher 传入）")
    parser.add_argument("folder", nargs="?", help="可直接传入文件夹路径，跳过多选提示")
    args = parser.parse_args()

    if args.irfanview_path:
        set_irfanview_override(args.irfanview_path)

    print("=" * 50)
    print("图片合并成 PDF 工具")
    print("=" * 50)
    print("处理完成后窗口不会关闭，可继续拖入其他文件夹。")
    print("输入 exit 或直接关闭窗口即可退出。")

    while True:
        try:
            print("-" * 50)
            if args.folder:
                raw = args.folder
                args.folder = None
                print(f"开始处理：{raw}")
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
