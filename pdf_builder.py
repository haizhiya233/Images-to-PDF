#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机端 PDF 生成器：纯标准库写一个最小 PDF 容器，把图片逐页塞进去。

设计取舍（对应 README 里 Windows 版"未实现的 DCTDecode 直通"）：
  Windows 版靠 IrfanView 的 PDF 插件，插件默认用 Flate 无损重编码，
  会把 JPEG 解码成裸 RGB 再压一遍，漫画素材体积膨胀 4~17 倍。
  这里直接自己写 PDF：JPEG 字节流原样作为 /DCTDecode 嵌入，
  **零重编码、像素完全一致、体积 = 源图之和 + 每页几百字节的容器开销**。

  - JPEG（baseline / 灰度 / RGB / 无 EXIF 旋转）→ 字节直通，不碰 ffmpeg
  - 其余（PNG/WebP/HEIC/AVIF/GIF/TIFF/BMP、progressive JPEG、带 EXIF
    旋转的手机照片、CMYK JPEG）→ 交给 ffmpeg 转成 baseline JPEG 再嵌
  - 逐页流式写盘，内存里始终只有一页，手机内存吃紧也不会爆
  - 原子落盘（同目录临时文件 + os.replace），失败绝不留半截 PDF

生产依赖：Python 标准库 + ffmpeg（手机 Termux 自带）。没有 Pillow / img2pdf / pypdf。
"""

from pathlib import Path
import os
import shutil
import struct
import subprocess
import tempfile

# 可以直接直通的 JPEG 扩展名
JPEG_EXTS = {".jpg", ".jpeg", ".jfif", ".jpe"}

# 页面尺寸：auto = 1 像素 1 点（原尺寸），a4 = A4 纵向等比居中
A4_POINTS = (595.2756, 841.8898)

# JPEG SOF marker（带长度、含帧参数的段），排除 DHT(C4)/JPG(C8)/DAC(CC)
_SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}

# 没有长度字段、需要直接跳过的 marker
_STANDALONE_MARKERS = {0x01, 0xD8, 0xD9} | set(range(0xD0, 0xD8))


class ConversionCancelled(Exception):
    """用户点了停止。"""


class PageError(Exception):
    """单张图片无法转成可嵌入的 JPEG。"""


def _exif_orientation(app1_payload):
    """从 APP1/Exif 段里读 IFD0 的 Orientation(0x0112)。

    手机拍的照片几乎都带 EXIF，但大多数 orientation=1，不该因此触发重编码。
    所以只认这一个 tag，读不到就当 1（不旋转）。
    app1_payload 是段内容（不含 FF E1 和 2 字节长度）。
    """
    if not app1_payload.startswith(b"Exif\x00\x00"):
        return 1
    base = 6  # 跳到 TIFF header
    if len(app1_payload) < base + 8:
        return 1
    tiff = app1_payload[base:]
    if tiff[:2] == b"II":
        endian = "<"
    elif tiff[:2] == b"MM":
        endian = ">"
    else:
        return 1
    try:
        if struct.unpack_from(endian + "H", tiff, 2)[0] != 42:
            return 1
        ifd0 = struct.unpack_from(endian + "I", tiff, 4)[0]
        if ifd0 + 2 > len(tiff):
            return 1
        count = struct.unpack_from(endian + "H", tiff, ifd0)[0]
        for i in range(min(count, 512)):
            entry = ifd0 + 2 + 12 * i
            if entry + 12 > len(tiff):
                break
            tag, typ = struct.unpack_from(endian + "HH", tiff, entry)
            if tag == 0x0112 and typ == 3:  # SHORT
                return struct.unpack_from(endian + "H", tiff, entry + 8)[0] & 0xFFFF
    except (struct.error, IndexError):
        return 1
    return 1


def jpeg_info(data):
    """解析 JPEG 头，返回 dict：
    width / height / components / colorspace / progressive / orientation。
    不是合法 JPEG 时抛 ValueError。
    """
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("不是 JPEG 文件（缺少 SOI 标记）")

    i = 2
    n = len(data)
    info = None
    orientation = 1
    while i < n - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker == 0xFF:          # 填充字节
            i -= 1
            continue
        if marker in _STANDALONE_MARKERS:
            continue
        if marker in (0xD9, 0xDA):  # EOI / SOS：帧参数一定在之前
            break
        if i + 2 > n:
            break
        seg_len = struct.unpack_from(">H", data, i)[0]
        if seg_len < 2:
            break
        payload_start = i + 2
        payload_end = min(i + seg_len, n)
        payload = data[payload_start:payload_end]

        if marker == 0xE1 and orientation == 1:
            orientation = _exif_orientation(payload)
        elif marker in _SOF_MARKERS and info is None:
            if len(payload) >= 6:
                height, width, comps = struct.unpack_from(">HHB", payload, 1)
                info = {
                    "width": width,
                    "height": height,
                    "components": comps,
                    "progressive": marker == 0xC2,
                }
        i += seg_len

    if info is None or info["width"] <= 0 or info["height"] <= 0:
        raise ValueError("JPEG 缺少有效的 SOF 帧头")

    comps = info["components"]
    if comps == 1:
        colorspace = "/DeviceGray"
    elif comps == 3:
        colorspace = "/DeviceRGB"
    else:
        colorspace = None  # CMYK / 罕见通道数 → 走 ffmpeg 重编码

    info["colorspace"] = colorspace
    info["orientation"] = orientation or 1
    return info


def _can_passthrough(info):
    """判断这份 JPEG 能否原样嵌入 PDF。"""
    return (
        info["colorspace"] is not None
        and not info["progressive"]
        and info["orientation"] == 1
    )


def _transcode(path, dst, quality, ffmpeg):
    """用 ffmpeg 把任意图片转成 baseline JPEG。返回 (jpeg_bytes, info)。

    ffmpeg 默认对 JPEG 输入按 EXIF 自动旋转（autorotate），所以带旋转的
    手机照片走这里正好被摆正。多帧 GIF/TIFF 用 -frames:v 1 只取首帧。
    """
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path),
        "-frames:v", "1",
        "-q:v", str(max(1, min(31, int(quality)))),
        "-f", "image2", str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
    except FileNotFoundError:
        raise PageError("找不到 ffmpeg，请在 Termux 里执行 pkg install ffmpeg") from None
    except subprocess.TimeoutExpired:
        raise PageError("ffmpeg 转码超时（180s）：%s" % path.name) from None
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
        raise PageError("ffmpeg 无法转换 %s：%s" % (path.name, err or "未知错误"))
    data = dst.read_bytes()
    return data, jpeg_info(data)


def _iter_pages(image_paths, quality, ffmpeg, temp_dir, should_cancel=None):
    """逐页产出 (jpeg_bytes, info, reencoded)。同一时刻内存里只有一页。"""
    scratch = Path(temp_dir) / "page.jpg"
    for path in image_paths:
        if should_cancel and should_cancel():
            raise ConversionCancelled()
        data = None
        info = None
        if path.suffix.lower() in JPEG_EXTS:
            try:
                data = path.read_bytes()
                info = jpeg_info(data)
            except (OSError, ValueError):
                data, info = None, None
        if data is not None and info is not None and _can_passthrough(info):
            yield data, info, False
        else:
            # 复用同一个 scratch 路径，磁盘上始终只有一个临时 JPEG
            if scratch.exists():
                scratch.unlink()
            data, info = _transcode(path, scratch, quality, ffmpeg)
            yield data, info, True


def _num(v):
    """PDF 数字格式化：固定小数、去掉尾随 0，绝不出现科学计数法。"""
    s = "%.4f" % float(v)
    return s.rstrip("0").rstrip(".") if "." in s else s


def _page_geometry(width, height, page_size):
    """返回 (page_w, page_h, draw_w, draw_h, x, y)，单位 pt。"""
    if page_size == "a4":
        pw, ph = A4_POINTS
        scale = min(pw / width, ph / height)
        dw, dh = width * scale, height * scale
        return pw, ph, dw, dh, (pw - dw) / 2, (ph - dh) / 2
    # auto：1 px = 1 pt
    return float(width), float(height), float(width), float(height), 0.0, 0.0


def build_pdf(image_paths, output_pdf, page_size="auto", quality=2,
              ffmpeg=None, progress=None, should_cancel=None):
    """把 image_paths 按顺序合成多页 PDF，原子写入 output_pdf。

    参数：
      page_size  "auto"（原尺寸）/ "a4"（A4 等比居中）
      quality    ffmpeg 转码的 -q:v（1 最好 ~31 最差，默认 2）
      progress   callable(done, total, name, reencoded)，逐页回调
      should_cancel  callable() -> bool，返回 True 时中断并清理

    返回 dict：pages / size / reencoded / output。
    抛 ConversionCancelled / PageError / OSError。
    """
    image_paths = [Path(p) for p in image_paths]
    if not image_paths:
        raise ValueError("没有图片可转换")
    output_pdf = Path(output_pdf)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    # 立刻删掉旧 PDF：转换过程任何一步抛异常都不能把旧文件误判为本次成功
    # （与 Windows 版 convert_folder 一致）。失败后旧文件也不该继续留在目录里。
    if output_pdf.exists():
        output_pdf.unlink()

    ffmpeg = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
    total = len(image_paths)

    # 同目录临时文件：保证 os.replace 是原子操作（不跨文件系统）
    fd, tmp_pdf = tempfile.mkstemp(
        prefix=".i2p_", suffix=".pdf", dir=str(output_pdf.parent)
    )
    os.close(fd)
    tmp_pdf = Path(tmp_pdf)

    scratch_dir = tempfile.mkdtemp(prefix="i2p_")

    offsets = {}
    reencoded = 0
    pages_written = 0
    try:
        with open(tmp_pdf, "wb") as f:
            def w(b):
                f.write(b if isinstance(b, bytes) else b.encode("ascii"))

            def obj(num, body):
                offsets[num] = f.tell()
                w("%d 0 obj\n" % num)
                w(body)
                w("\nendobj\n")

            w(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

            # 对象号固定：1=Catalog, 2=Pages, 之后每页 3 个（page/content/image）
            def page_obj(i):
                return 3 + 3 * i

            kids = " ".join("%d 0 R" % page_obj(i) for i in range(total))
            obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
            obj(2, ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, total)).encode("ascii"))

            for i, (data, info, was_transcoded) in enumerate(
                _iter_pages(image_paths, quality, ffmpeg, scratch_dir, should_cancel)
            ):
                if should_cancel and should_cancel():
                    raise ConversionCancelled()

                pw, ph, dw, dh, x, y = _page_geometry(
                    info["width"], info["height"], page_size
                )
                p_obj = page_obj(i)
                c_obj, im_obj = p_obj + 1, p_obj + 2

                page_body = (
                    "<< /Type /Page /Parent 2 0 R "
                    "/MediaBox [0 0 %s %s] "
                    "/Resources << /XObject << /Im0 %d 0 R >> >> "
                    "/Contents %d 0 R >>"
                ) % (_num(pw), _num(ph), im_obj, c_obj)
                obj(p_obj, page_body.encode("ascii"))

                content = (
                    "q\n%s 0 0 %s %s %s cm\n/Im0 Do\nQ\n"
                    % (_num(dw), _num(dh), _num(x), _num(y))
                ).encode("ascii")
                obj(c_obj, ("<< /Length %d >>\nstream\n" % len(content)).encode("ascii")
                    + content + b"\nendstream")

                img_dict = (
                    "<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                    "/ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode "
                    "/Length %d >>\nstream\n"
                ) % (info["width"], info["height"], info["colorspace"], len(data))
                obj(im_obj, img_dict.encode("ascii") + data + b"\nendstream")

                if was_transcoded:
                    reencoded += 1
                pages_written += 1
                if progress:
                    progress(pages_written, total, image_paths[i].name, was_transcoded)
                del data

            # xref + trailer
            size = 2 + 3 * total + 1
            xref_off = f.tell()
            w("xref\n0 %d\n" % size)
            w("0000000000 65535 f \n")
            for num in range(1, size):
                w("%010d 00000 n \n" % offsets[num])
            w("trailer\n<< /Size %d /Root 1 0 R >>\n" % size)
            w("startxref\n%d\n%%%%EOF\n" % xref_off)

        os.replace(tmp_pdf, output_pdf)
        tmp_pdf = None
    finally:
        if tmp_pdf is not None and tmp_pdf.exists():
            try:
                tmp_pdf.unlink()
            except OSError:
                pass
        shutil.rmtree(scratch_dir, ignore_errors=True)

    return {
        "pages": pages_written,
        "size": output_pdf.stat().st_size,
        "reencoded": reencoded,
        "output": str(output_pdf),
    }
