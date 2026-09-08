#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""便携版启动器：自动下载/更新 IrfanView-64 便携版到本地缓存，然后运行主脚本。

- 只从官方 irfanview.info 域名下载，不违反 EULA（非重分发，而是首次运行时下载官方包）。
- 缓存目录：%LOCALAPPDATA%/Images-to-PDF/irfanview/（Linux/WSL 用 ~/.local/share）。
- 通过 SHA-256 校验下载文件，解压后调用 folder_to_pdf.py。
- 联网且未缓存 → 自动下载。已缓存 → 直接用。离线但已缓存 → 直接用。

用法：
  python launcher.py [--version 475] [--update] [--download-only]
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# 官方 64-bit 便携版下载（版本号为 URL 的一部分，改版时只改这里）
DEFAULT_VERSION = "475"
IVIEW_URL = "https://www.irfanview.info/files/iview{v}_x64.zip"
PLUGINS_URL = "https://www.irfanview.info/files/iview{v}_plugins_x64.zip"
# 官方 SHA-256（对应 475；若改版本需同步更新）
IVIEW_SHA = "b657c6fcb3e758b28cda00c1ded32af97b1441ead522053b4930d7304f0506e7"
PLUGINS_SHA = "37ab14c2280f5919043b2e30f481f657629978285bdbd138dcace60565c768bb"

SCRIPT_DIR = Path(__file__).resolve().parent
EXE_NAME = "i_view64.exe"


def cache_dir():
    """返回缓存根目录。Windows 用 LOCALAPPDATA，其他平台用 ~/.local/share。"""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Images-to-PDF" / "irfanview"
    return Path.home() / ".local" / "share" / "images-to-pdf" / "irfanview"


def ensure_irfanview(version=DEFAULT_VERSION, update=False, download_only=False, no_verify=False):
    """确保 IrfanView 便携版在主程序目录可用，返回 i_view64.exe 路径。"""
    root = cache_dir()
    install_dir = root / f"iview{version}"
    exe = install_dir / EXE_NAME

    if exe.exists() and not update:
        print(f"[便携版] 已存在：{exe}")
        return exe

    os.makedirs(root, exist_ok=True)

    zip_main = root / f"iview{version}_x64.zip"
    zip_plugins = root / f"iview{version}_plugins_x64.zip"

    try:
        _download_verified(IVIEW_URL.format(v=version), zip_main, IVIEW_SHA, no_verify)
        _download_verified(PLUGINS_URL.format(v=version), zip_plugins, PLUGINS_SHA, no_verify)
    except Exception as e:
        print(f"[便携版] 下载失败：{e}")
        # 若已有旧缓存但解压失败，尝试用旧缓存兜底
        if exe.exists():
            print(f"[便携版] 使用已有缓存：{exe}")
            return exe
        raise

    # 解压到 install_dir
    print(f"[便携版] 解压到 {install_dir} ...")
    if install_dir.exists():
        shutil.rmtree(install_dir)
    os.makedirs(install_dir, exist_ok=True)
    try:
        _extract_zip(zip_main, install_dir)
        _extract_zip(zip_plugins, install_dir)
        # 插件 ZIP 的根级 DLL（如 PDF.dll）需归位到 Plugins/ 子目录
        _relocate_plugin_dlls(install_dir)
    except Exception as e:
        print(f"[便携版] 解压失败：{e}")
        raise

    # 清理 zip 避免残留
    try:
        os.unlink(zip_main)
        os.unlink(zip_plugins)
    except OSError:
        pass

    if not exe.exists():
        raise FileNotFoundError(f"解压后未找到 {EXE_NAME}（{exe}）")
    print(f"[便携版] 就绪：{exe}")
    return exe


def _download_verified(url, dest, expected_sha, no_verify=False):
    """下载文件到 dest，处理官方"点击继续下载"中间页，并校验 SHA-256。

    irfanview.info 的 ZIP 直链会先返回一个 HTML"Click again to start Download"页，
    实际文件需从该页里的真实链接二次下载。这里自动提取。
    若 no_verify=True 或页面不带哈希，则跳过 SHA 校验（仅限官方域名可信场景）。
    """
    data, headers = _fetch(url)
    # 检测是否官方"点击继续下载"中间页；是则携带 Referer 从真实链接二次下载
    if b"Click again to start Download" in data:
        real_url = _extract_download_url(data, url)
        print(f"[便携版] 检测到下载中间页，从链接获取实际文件：{real_url}")
        data, headers = _fetch(real_url, referer=url)

    if expected_sha and not no_verify:
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha:
            raise ValueError(f"SHA-256 校验失败：{dest.name} 期望 {expected_sha} 实际 {actual}")

    with open(dest, "wb") as f:
        f.write(data)
    print(f"[便携版] 下载完成{'(校验通过)' if expected_sha and not no_verify else ''}：{dest.name}")
    return dest


def _fetch(url, referer=None):
    """下载 URL 内容为 bytes。带 UA 头；referer 用于绕过官方反爬（需从中间页点击）。"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read(), dict(resp.headers)


def _extract_download_url(data, fallback_url):
    """从官方"Click again"页提取真实下载 URL（data 为 bytes/str），失败则回退原 URL。"""
    import re
    text = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else data
    m = re.search(r'href="(https://[^"]+)"', text)
    if m:
        return m.group(1)
    return fallback_url


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_zip(zip_path, dest_dir):
    """解压 zip 到 dest_dir，安全处理路径穿越（禁止 '../'）。"""
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            # 防 zip-slip：解析后不得逃出 dest_dir
            target = (dest_dir / member).resolve()
            if not str(target).startswith(str(dest_dir.resolve())):
                raise ValueError(f"非法路径：{member}")
        z.extractall(dest_dir)


def _relocate_plugin_dlls(install_dir):
    """把插件 ZIP 解到根目录的 DLL 归位到 Plugins/ 子目录（IrfanView 期望如此）。

    主程序 ZIP 把基础插件放 Plugins/，但插件 ZIP 的根级 DLL（尤其 PDF.dll）
    落在 install_dir 根，需移到 Plugins/ 才能被 IrfanView 找到。
    """
    plugins = install_dir / "Plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    for dll in install_dir.glob("*.dll"):
        # 跳过 Plugins 子目录内已有的同名文件（主程序 zip 已装的基础插件）
        target = plugins / dll.name
        if target.exists():
            continue
        shutil.move(str(dll), str(target))


def run_main(irfan_exe, extra_args=None):
    """把便携版路径传给主脚本并运行。"""
    cmd = [sys.executable, str(SCRIPT_DIR / "folder_to_pdf.py")]
    if irfan_exe:
        cmd += ["--irfanview-path", str(irfan_exe)]
    if extra_args:
        cmd += extra_args
    print(f"[便携版] 运行：{' '.join(cmd)}")
    return subprocess.call(cmd)


def main():
    parser = argparse.ArgumentParser(description="Images-to-PDF 便携版启动器")
    parser.add_argument("--version", default=DEFAULT_VERSION, help="IrfanView 版本 (默认 475)")
    parser.add_argument("--update", action="store_true", help="强制重新下载最新版")
    parser.add_argument("--download-only", action="store_true", help="只下载/更新缓存，不运行主脚本")
    parser.add_argument("--no-verify", action="store_true",
                        help="跳过 SHA-256 校验（官方域名可信；版本更新哈希变化时用）")
    parser.add_argument("extra", nargs="*", help="透传给主脚本的参数")
    args = parser.parse_args()

    try:
        irfan = ensure_irfanview(version=args.version, update=args.update,
                                 download_only=args.download_only, no_verify=args.no_verify)
    except Exception as e:
        print(f"[便携版] ❌ 初始化失败：{e}")
        print("       请检查网络，或手动安装 IrfanView 后直接运行 folder_to_pdf.py。")
        sys.exit(1)

    if args.download_only:
        print(f"[便携版] 下载完成：{irfan}")
        sys.exit(0)

    sys.exit(run_main(irfan, args.extra))


if __name__ == "__main__":
    main()
