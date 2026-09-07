#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把文件夹内的图片合并成一个多页 PDF（使用 IrfanView）。

使用方法：
  1. 双击本脚本（或命令行运行）。
  2. 控制台提示时，把图片文件夹拖进窗口，按 Enter。
  3. 脚本自动收集该文件夹（仅顶层，不含子文件夹）的图片，按文件名自然排序，
     然后调用 IrfanView 的 /multipdf 生成一个多页 PDF，保存到 OUTPUT_DIR。

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

# ================= 用户可修改区 =================
OUTPUT_DIR = Path(r"C:\Users\31657\Desktop\PDF_Output")  # 用户在此修改输出目录
# ===============================================

# 支持的图片扩展名（小写，忽略大小写）
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
    ".gif", ".webp", ".jfif", ".avif", ".heic",
}


def natural_key(name):
    """自然排序键：让 '2.jpg' 排在 '10.jpg' 前面。"""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", str(name))
    ]


def resolve_irfanview():
    """定位 i_view64.exe（或 i_view32.exe），返回 Path，找不到则抛 RuntimeError。

    按顺序尝试：
      1. Powershell 解析桌面快捷方式 IrfanView 64.lnk 的目标路径
      2. C:\\Program Files\\IrfanView\\i_view64.exe
      3. C:\\Program Files (x86)\\IrfanView\\i_view32.exe
      4. shutil.which("i_view64.exe") / ("i_view32.exe")
      5. 注册表 HKCU\\Software\\IrfanView 的 InstallDir
    """
    exe_name = "i_view64.exe"

    # 1. 解析 .lnk（最可靠，你的 IrfanView 装在非标准位置）
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
                    return p
        except Exception:
            pass

    # 2. 3. 常见安装目录
    for cand in [
        Path(r"C:\Program Files\IrfanView\i_view64.exe"),
        Path(r"C:\Program Files (x86)\IrfanView\i_view32.exe"),
    ]:
        if cand.exists():
            return cand

    # 4. PATH
    for name in ("i_view64.exe", "i_view32.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)

    # 5. 注册表
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\IrfanView") as k:
            install_dir = winreg.QueryValueEx(k, "InstallDir")[0]
        p = Path(install_dir) / exe_name
        if p.exists():
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


def main():
    print("=" * 50)
    print("图片合并成 PDF 工具")
    print("=" * 50)
    print("请把【图片文件夹】拖到此窗口，然后按 Enter 开始：")
    raw = input().strip().strip('"')
    if not raw:
        print("未输入路径，退出。")
        input("\n按 Enter 退出...")
        return

    folder = Path(raw)
    try:
        if not folder.is_dir():
            raise ValueError(f"路径不是文件夹：{folder}")
        if not folder.exists():
            raise ValueError(f"文件夹不存在：{folder}")

        images = collect_images(folder)
        print(f"找到 {len(images)} 张图片，正在生成 PDF ...")

        irfan = resolve_irfanview()
        print(f"IrfanView: {irfan}")

        check_pdf_plugin(irfan.parent)

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
        else:
            stderr = (result.stderr or "")[-400:]
            raise RuntimeError(f"IrfanView 未生成 PDF。退出码：{result.returncode}\n{stderr}")

    except Exception as e:
        print(f"\n❌ 出错了：{e}")

    input("\n按 Enter 退出...")


if __name__ == "__main__":
    main()
