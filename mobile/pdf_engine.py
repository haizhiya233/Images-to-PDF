#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 的 PDF 转换引擎 —— Android 版 Images-to-PDF 的核心模块。

背景（PDF 体积之战）：
Windows 版 folder_to_pdf.py 通过 IrfanView 64 的 /multipdf CLI 生成多页 PDF。
IrfanView 的 PDF 插件默认使用 Flate/zlib 无损压缩：它把每张 JPEG 解码成原始
RGB（3976x6114 的单页约 72.9 MB）再重新压缩，在漫画/网点内容上造成 4x–17x 的
体积膨胀——158 MB 的 JPEG 曾产出 2.6 GB 的 PDF。Windows 版的解决方案是逆向
PDF.dll，发现插件会读取 INI 的 [PDF] ComprColor/ComprGray/ComprBW 键，于是用
未公开的 /ini= CLI 参数强制插件使用 JPEG q95（1.14x）。

Pillow 的 PDF 写入器（src/PIL/PdfImagePlugin.py）原生支持 DCTDecode：
RGB / L / CMYK 模式的图像直接以 JPEG 流写入 PDF，无需任何 INI 或逆向工程。
本模块的 quality 参数直接对应原来的 JPEG 压缩档位（默认 95），
那段与 IrfanView 插件搏斗的历史就此终结。

内存约束（本模块存在的理由）：
手机只有几 GB RAM。一张 1988x3057 的 RGB 图片解码后约 18.2 MB，
一次性加载 200 页 = 3.6 GB = 必然 OOM。因此本引擎分块转换：
每块最多 chunk_pages 张图，写成一个**独立合法**的单块 PDF；每块结束后关闭
所有 PIL.Image 对象并丢弃引用——绝不同时持有全部打开的图片。

为什么不用 Pillow 的 append=True 增量追加（实测结论，勿轻易改回去）：
最初实现是「第一块 save_all 写入，后续块 append=True 追加」。实测（23 张
400x600 JPEG，pdfinfo 校验）发现 Pillow 的增量追加只能撑 4 块：

    块数 1/ 2/ 3/ 4  -> valid, Pages=23
    块数 5         -> PdfFormatError: trailer loop found

原因是每次 append 都会重新解析既有 PDF 并重写 trailer，xref 的 /Prev 链不断
累积，约第 5 块时 Pillow 自己的 PdfParser 就会绕死。默认 chunk_pages=10
意味着「超过 40 张图就崩」——而真实用例是 200 页左右的漫画话数，必崩。

现在的做法：Pillow 只写独立块（单块永远有效），再用 pypdf 合并。
pypdf 是纯 Python（无 C 扩展），p4a 会自动 pip 安装，不需要 recipe。
实测 52 张图 / 6 块 -> pdfinfo valid, Pages=52, /Type /Pages 数量为 1。

依赖：stdlib + Pillow（+ pypdf，仅在块数 > 1 时才需要）。
不import 任何 Kivy / plyer / android / jnius 模块，在桌面 Linux 上也能干净导入。
"""

from __future__ import annotations

import itertools
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional, Tuple

from PIL import Image, ImageOps

# ================= 用户可修改区 =================

# 支持的图片扩展名（小写，比较时忽略大小写）
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
    ".gif", ".webp", ".jfif", ".avif", ".heic",
})

# JPEG 压缩质量（1-100）。对应 Windows 版 IrfanView 插件的 Compr* 档位，
# 默认 95 ≈ 当年逆向 PDF.dll 后强制的 q95（1.14x 体积）。
DEFAULT_QUALITY = 95

# 输出 PDF 的分辨率（DPI）。72 = 按图片原始像素尺寸排版。
DEFAULT_DPI = (72.0, 72.0)

# 每个分块最多包含的图片数。手机内存有限，切勿调大到能一次装下全部图片。
DEFAULT_CHUNK_PAGES = 10

# ===============================================


class ConversionCancelled(Exception):
    """用户取消转换时抛出（should_cancel() 返回 True）。"""


def natural_key(name: str) -> List[Any]:
    """自然排序键：让 '2.jpg' 排在 '10.jpg' 前面。"""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", str(name))
    ]


def is_image(path: Path) -> bool:
    """判断 path 是否为受支持的图片文件（按扩展名，忽略大小写）。"""
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def collect_images(folder: Path) -> List[Path]:
    """收集 folder 顶层（不递归）的图片文件，返回按自然序排序的 Path 列表。"""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"不是有效的文件夹：{folder}")
    imgs = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not imgs:
        raise ValueError(f"文件夹中没有找到支持的图片：{folder}")
    imgs.sort(key=lambda p: natural_key(p.name))
    return imgs


def subfolders_with_images(folder: Path) -> List[Path]:
    """返回 folder 下含图片的子文件夹，按自然序排序。"""
    folder = Path(folder)
    subs = [
        p for p in folder.iterdir()
        if p.is_dir() and any(x.is_file() and x.suffix.lower() in IMAGE_EXTENSIONS for x in p.iterdir())
    ]
    subs.sort(key=lambda p: natural_key(p.name))
    return subs


def chunks(seq: List[Any], size: int) -> Iterator[List[Any]]:
    """把 seq 切成大小为 size 的若干块（最后一块可能不足 size）。"""
    if size < 1:
        raise ValueError(f"分块大小必须 >= 1，收到 {size}")
    it = iter(seq)
    while True:
        chunk = list(itertools.islice(it, size))
        if not chunk:
            return
        yield chunk


def open_for_pdf(path: Path) -> Image.Image:
    """打开图片并归一化为 PDF 可编码的模式，供 PdfImagePlugin 以 DCTDecode 写入。

    - 应用 ImageOps.exif_transpose() 纠正 EXIF 方向。
    - RGB / L / CMYK 原样返回（PdfImagePlugin 对这三种模式直接发 DCTDecode）；
      其余模式（RGBA / P / LA / 1 / I 等）统一转为 RGB。
    - 注意：Pillow 的 exif_transpose() 内部会 load() 并返回独立副本，
      因此本函数返回时原图已关闭；调用方仍需在转换结束后 close() 返回的对象。
    """
    src = Image.open(path)
    try:
        im = ImageOps.exif_transpose(src)
    finally:
        # exif_transpose 返回的是独立副本（或 transpose 新图），原图可安全关闭
        src.close()
    if im.mode in ("RGB", "L", "CMYK"):
        return im
    try:
        return im.convert("RGB")
    except Exception as exc:
        im.close()
        raise ValueError(f"无法把图片模式 {im.mode} 转为 PDF 支持的格式：{path}") from exc


def _merge_pdfs(parts: List[Path], out_pdf: Path) -> None:
    """把若干个独立合法的单块 PDF 合并成一个 PDF。

    只在块数 > 1 时调用，因此 pypdf 是唯一会用到它的路径（单块直写不需要）。
    pypdf 是纯 Python、无 C 扩展，p4a 会自动 pip 安装，无需 recipe。
    """
    try:
        from pypdf import PdfWriter
    except ImportError as exc:
        raise RuntimeError(
            "分块合并需要 pypdf（纯 Python 包）。单块转换不需要它；"
            "请确认已安装 pypdf，或调大 chunk_pages 让所有图片放进同一块。"
        ) from exc

    writer = PdfWriter()
    try:
        for part in parts:
            writer.append(str(part))
        with open(out_pdf, "wb") as handle:
            writer.write(handle)
    finally:
        writer.close()


def convert_images_to_pdf(images: List[Path], out_pdf: Path, *,
                          quality: int = DEFAULT_QUALITY,
                          dpi: Tuple[float, float] = DEFAULT_DPI,
                          chunk_pages: int = DEFAULT_CHUNK_PAGES,
                          progress: Optional[Callable[[int, int, str], None]] = None,
                          should_cancel: Optional[Callable[[], bool]] = None) -> Path:
    """把 images（Path 列表）分块转换为多页 PDF，写入 out_pdf 并返回其 Path。

    分块转换以限制内存峰值：每块最多 chunk_pages 张图，写成一个独立合法的
    单块 PDF；块数 > 1 时用 pypdf 合并成最终文件。每块结束后关闭所有
    PIL.Image 对象并丢弃引用——绝不同时持有全部打开的图片。

    块数 == 1 时直接把该块写入 out_pdf，不产生临时文件、不需要 pypdf。

    progress: Callable[[int, int, str], None]，每处理一张图片前调用一次，
        参数为 (已完成数, 总数, 当前文件名)；全部完成后再调用一次
        (总数, 总数, "")。
    should_cancel: Callable[[], bool]，每个分块开始前检查；返回 True 则抛出
        ConversionCancelled。

    异常处理：images 为空、转换失败或被取消时，删除可能已生成的半成品
    out_pdf，绝不留下一个看似有效的截断 PDF。
    """
    image_paths = [Path(p) for p in images]
    if not image_paths:
        raise ValueError("图片列表为空，无法生成 PDF")
    if chunk_pages < 1:
        raise ValueError(f"分块大小必须 >= 1，收到 {chunk_pages}")
    out_pdf = Path(out_pdf)
    total = len(image_paths)
    done = 0
    try:
        if len(image_paths) <= chunk_pages:
            # 单块：直接写最终文件，无需临时文件与 pypdf
            opened = []
            try:
                for path in image_paths:
                    if progress is not None:
                        progress(done, total, path.name)
                    opened.append(open_for_pdf(path))
                    done += 1
                opened[0].save(out_pdf, "PDF", save_all=True,
                               append_images=opened[1:], quality=quality, dpi=dpi)
            finally:
                for im in opened:
                    im.close()
        else:
            # 多块：每块写成独立合法 PDF，最后合并。见模块 docstring 的实测结论。
            with tempfile.TemporaryDirectory(prefix="i2pdf_") as scratch:
                parts: List[Path] = []
                for index, chunk in enumerate(chunks(image_paths, chunk_pages)):
                    if should_cancel is not None and should_cancel():
                        raise ConversionCancelled(f"转换已被取消（完成 {done}/{total} 页）")
                    opened = []
                    try:
                        for path in chunk:
                            if progress is not None:
                                progress(done, total, path.name)
                            opened.append(open_for_pdf(path))
                            done += 1
                        part = Path(scratch) / f"part{index:06d}.pdf"
                        opened[0].save(part, "PDF", save_all=True,
                                       append_images=opened[1:],
                                       quality=quality, dpi=dpi)
                        parts.append(part)
                    finally:
                        for im in opened:
                            im.close()
                        opened = []
                _merge_pdfs(parts, out_pdf)
        if progress is not None:
            progress(total, total, "")
    except BaseException:
        # 失败/取消时删除半成品 PDF，避免被误认为有效输出
        try:
            out_pdf.unlink()
        except FileNotFoundError:
            pass
        raise
    return out_pdf


def convert_folder(src: Path, out_pdf: Path, **kwargs) -> Path:
    """把文件夹 src 顶层的所有图片转换为多页 PDF，写入 out_pdf 并返回其 Path。

    kwargs 透传给 convert_images_to_pdf（quality / dpi / chunk_pages /
    progress / should_cancel）。
    """
    images = collect_images(src)
    return convert_images_to_pdf(images, out_pdf, **kwargs)
