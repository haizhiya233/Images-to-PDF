#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdf_engine.py 的单元测试（unittest，仅依赖 stdlib + Pillow）。

运行：python -m unittest mobile.test_pdf_engine -v
所有合成图片都生成在 tempfile.TemporaryDirectory() 中，不写入仓库。

Pillow 12 的 PdfImagePlugin 是纯输出插件（无 PDF 读取器），因此页数校验
通过解析 PDF 字节完成：沿 /Prev 链合并所有 xref 小节（与 PdfParser /
poppler 等合规读取器的行为一致），再从 /Root 走到 /Pages 核对 /Count、
/Kids 以及每个页面引用的图片 XObject 是否都能解析。
"""

import re
import tempfile
import unittest
from pathlib import Path
from typing import Dict

import importlib.util

from PIL import Image

SCRIPT_PATH = Path(__file__).parent / "pdf_engine.py"
spec = importlib.util.spec_from_file_location("pdf_engine", SCRIPT_PATH)
assert spec is not None and spec.loader is not None, "无法加载 pdf_engine.py"
pdf_engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf_engine)


# ================= 测试辅助 =================

def make_image(path, size=(200, 150), color=(200, 30, 30)):
    """生成一张纯色合成图片。"""
    Image.new("RGB", size, color).save(path)
    return path


def make_noise_image(path, size=(300, 200)):
    """生成一张随机噪声图片（高熵，用于 quality 测试）。"""
    import random
    rng = random.Random(42)
    im = Image.new("RGB", size)
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                 for _ in range(size[0] * size[1])])
    im.save(path)
    return path


def _parse_xref_chain(data: bytes) -> Dict[int, int]:
    """沿 /Prev 链解析所有 xref 小节，返回 {object_id: offset}（只含 n 项）。

    与 PdfParser.read_trailer 的行为一致：从最后一个 startxref 出发，
    新段优先（setdefault），再沿 /Prev 向前合并。
    """
    live = {}
    idx = data.rfind(b"startxref")
    assert idx != -1, "找不到 startxref"
    offsets = []
    while idx != -1:
        m = re.match(rb"startxref\s+(\d+)", data[idx:])
        assert m is not None, "startxref 后缺少偏移量"
        offsets.append(int(m.group(1)))
        idx = data.rfind(b"startxref", 0, idx)
    for sx in offsets:
        pos = sx + len(b"xref")
        while True:
            m = re.match(rb"\s*(\d+)\s+(\d+)\s*\n", data[pos:])
            if not m:
                break
            first, count = int(m.group(1)), int(m.group(2))
            pos += m.end()
            for i in range(count):
                entry = data[pos:pos + 20]
                assert len(entry) == 20, f"xref 条目长度异常：{entry!r}"
                if entry[17:18] == b"n":
                    live.setdefault(first + i, int(entry[0:10]))
                pos += 20
    return live


def _read_object_body(data: bytes, live: Dict[int, int], oid: int) -> bytes:
    """读取对象 oid 的字典体（处理嵌套 << >>）。"""
    off = live[oid]
    m = re.match(rb"(\d+)\s+0\s+obj\s*<<", data[off:])
    assert m is not None, f"对象 {oid} 在偏移 {off} 处不存在"
    depth = 1
    i = off + m.end()
    while depth:
        if data[i:i + 2] == b"<<":
            depth += 1
            i += 2
        elif data[i:i + 2] == b">>":
            depth -= 1
            i += 2
        else:
            i += 1
    return data[off + m.end():i - 2]


def pdf_page_count(data: bytes) -> int:
    """解析最终 PDF 文档的页数（沿 /Prev 链，与合规读取器一致）。"""
    assert data[:5] == b"%PDF-", "缺少 PDF 文件头"
    assert data.rstrip().endswith(b"%%EOF"), "缺少 PDF 文件尾"
    live = _parse_xref_chain(data)
    # 最后一个 trailer 的 /Root
    trailers = list(re.finditer(rb"trailer\s*<<(.*?)>>\s*\nstartxref", data, re.S))
    assert trailers, "找不到 trailer"
    m_root = re.search(rb"/Root\s+(\d+)\s+0\s+R", trailers[-1].group(1))
    assert m_root is not None, "trailer 中缺少 /Root"
    root = int(m_root.group(1))
    root_body = _read_object_body(data, live, root)
    m_pages = re.search(rb"/Pages\s+(\d+)\s+0\s+R", root_body)
    assert m_pages is not None, "catalog 中缺少 /Pages"
    pages = int(m_pages.group(1))
    pages_body = _read_object_body(data, live, pages)
    m_count = re.search(rb"/Count\s+(\d+)", pages_body)
    assert m_count is not None, "pages 树中缺少 /Count"
    count = int(m_count.group(1))
    m_kids = re.search(rb"/Kids\s*\[(.*?)\]", pages_body, re.S)
    assert m_kids is not None, "pages 树中缺少 /Kids"
    kids = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", m_kids.group(1))]
    assert len(kids) == count, f"/Count={count} 但 /Kids 有 {len(kids)} 项"
    # 每个页面及其图片 XObject 都必须能在 xref 中解析
    for k in kids:
        kb = _read_object_body(data, live, k)
        xm = re.search(rb"/XObject\s*<<(.+?)>>", kb, re.S)
        if xm:
            for ref in re.findall(rb"(\d+)\s+0\s+R", xm.group(1)):
                assert int(ref) in live, f"页面 {k} 引用的对象 {int(ref)} 不在 xref 中"
    return count


# ================= 测试用例 =================

class TestNaturalKey(unittest.TestCase):
    """自然排序：数字感知，'2' 排 '10' 前；字母顺序且大小写无关。"""

    def test_numeric_order(self):
        self.assertLess(
            pdf_engine.natural_key("2.jpg"),
            pdf_engine.natural_key("10.jpg"),
        )

    def test_case_insensitive(self):
        self.assertEqual(
            pdf_engine.natural_key("A.jpg"),
            pdf_engine.natural_key("a.jpg"),
        )

    def test_mixed_parts(self):
        names = ["page10b", "page2a", "page10a"]
        self.assertEqual(
            sorted(names, key=pdf_engine.natural_key),
            ["page2a", "page10a", "page10b"],
        )


class TestChunks(unittest.TestCase):
    """chunks() 边界情况。"""

    def test_size_one(self):
        self.assertEqual(
            list(pdf_engine.chunks([1, 2, 3], 1)),
            [[1], [2], [3]],
        )

    def test_size_larger_than_input(self):
        self.assertEqual(
            list(pdf_engine.chunks([1, 2], 10)),
            [[1, 2]],
        )

    def test_empty_input(self):
        self.assertEqual(list(pdf_engine.chunks([], 3)), [])

    def test_exact_multiple(self):
        self.assertEqual(
            list(pdf_engine.chunks([1, 2, 3, 4], 2)),
            [[1, 2], [3, 4]],
        )

    def test_remainder(self):
        self.assertEqual(
            list(pdf_engine.chunks([1, 2, 3, 4, 5], 2)),
            [[1, 2], [3, 4], [5]],
        )

    def test_invalid_size(self):
        with self.assertRaises(ValueError):
            list(pdf_engine.chunks([1], 0))


class TestCollectImages(unittest.TestCase):
    """collect_images：仅顶层、按扩展名过滤、自然序排序。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_natural_sort_two_before_ten(self):
        make_image(self.folder / "10.png")
        make_image(self.folder / "2.png")
        make_image(self.folder / "1.png")
        imgs = pdf_engine.collect_images(self.folder)
        self.assertEqual([p.name for p in imgs], ["1.png", "2.png", "10.png"])

    def test_ignores_non_image_files(self):
        make_image(self.folder / "a.png")
        (self.folder / "notes.txt").write_text("hello")
        (self.folder / "data.csv").write_text("1,2,3")
        (self.folder / "no_ext").write_bytes(b"x")
        imgs = pdf_engine.collect_images(self.folder)
        self.assertEqual([p.name for p in imgs], ["a.png"])

    def test_top_level_only(self):
        make_image(self.folder / "top.png")
        sub = self.folder / "sub"
        sub.mkdir()
        make_image(sub / "nested.png")
        imgs = pdf_engine.collect_images(self.folder)
        self.assertEqual([p.name for p in imgs], ["top.png"])

    def test_empty_folder_raises(self):
        with self.assertRaises(ValueError):
            pdf_engine.collect_images(self.folder)

    def test_not_a_folder_raises(self):
        f = self.folder / "file.txt"
        f.write_text("x")
        with self.assertRaises(ValueError):
            pdf_engine.collect_images(f)


class TestSubfoldersAndIsImage(unittest.TestCase):
    """subfolders_with_images 与 is_image。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_subfolders_with_images(self):
        (self.folder / "b").mkdir()
        make_image(self.folder / "b" / "1.png")
        (self.folder / "a").mkdir()
        make_image(self.folder / "a" / "1.png")
        (self.folder / "empty").mkdir()
        make_image(self.folder / "top.png")
        subs = pdf_engine.subfolders_with_images(self.folder)
        self.assertEqual([p.name for p in subs], ["a", "b"])

    def test_is_image(self):
        make_image(self.folder / "a.png")
        (self.folder / "b.txt").write_text("x")
        self.assertTrue(pdf_engine.is_image(self.folder / "a.png"))
        self.assertFalse(pdf_engine.is_image(self.folder / "b.txt"))
        self.assertFalse(pdf_engine.is_image(self.folder / "missing.png"))


class TestOpenForPdf(unittest.TestCase):
    """open_for_pdf：模式归一化与 EXIF 方向纠正。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rgba_normalized_to_rgb(self):
        src = self.folder / "rgba.png"
        Image.new("RGBA", (50, 60), (1, 2, 3, 128)).save(src)
        im = pdf_engine.open_for_pdf(src)
        try:
            self.assertEqual(im.mode, "RGB")
        finally:
            im.close()

    def test_palette_and_la_normalized_to_rgb(self):
        p = self.folder / "p.png"
        Image.new("P", (40, 40)).save(p)
        la = self.folder / "la.png"
        Image.new("LA", (40, 40)).save(la)
        for src in (p, la):
            im = pdf_engine.open_for_pdf(src)
            try:
                self.assertEqual(im.mode, "RGB")
            finally:
                im.close()

    def test_rgb_passthrough(self):
        src = self.folder / "rgb.png"
        Image.new("RGB", (40, 40), (9, 9, 9)).save(src)
        im = pdf_engine.open_for_pdf(src)
        try:
            self.assertEqual(im.mode, "RGB")
        finally:
            im.close()

    def test_exif_orientation_applied(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation = 6 -> ROTATE_270
        src = self.folder / "rotated.jpg"
        Image.new("RGB", (400, 200), (255, 0, 0)).save(src, exif=exif)
        im = pdf_engine.open_for_pdf(src)
        try:
            self.assertEqual(im.size, (200, 400))
            self.assertEqual(im.mode, "RGB")
        finally:
            im.close()


class TestConvertImagesToPdf(unittest.TestCase):
    """convert_images_to_pdf：分块转换、取消、失败清理、quality。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_images(self, n):
        return [
            make_image(self.folder / f"img{i:02d}.png",
                       color=(i * 25 % 256, 10, 20))
            for i in range(n)
        ]

    def test_page_count_across_chunk_boundary(self):
        # 7 张图、chunk_pages=3 -> 跨 3 个分块，最终 7 页
        paths = self._make_images(7)
        out = pdf_engine.convert_images_to_pdf(
            paths, self.folder / "out.pdf", chunk_pages=3)
        data = Path(out).read_bytes()
        self.assertEqual(pdf_page_count(data), 7)
        # 单块（不分块）结果一致
        out2 = pdf_engine.convert_images_to_pdf(
            paths, self.folder / "out2.pdf", chunk_pages=10)
        self.assertEqual(pdf_page_count(Path(out2).read_bytes()), 7)

    def test_returns_path(self):
        paths = self._make_images(2)
        out = pdf_engine.convert_images_to_pdf(paths, self.folder / "out.pdf")
        self.assertIsInstance(out, Path)
        self.assertEqual(out, self.folder / "out.pdf")
        self.assertTrue(out.exists())

    def test_empty_image_list_raises(self):
        with self.assertRaises(ValueError):
            pdf_engine.convert_images_to_pdf([], self.folder / "out.pdf")
        self.assertFalse((self.folder / "out.pdf").exists())

    def test_invalid_chunk_pages_raises(self):
        paths = self._make_images(1)
        with self.assertRaises(ValueError):
            pdf_engine.convert_images_to_pdf(
                paths, self.folder / "out.pdf", chunk_pages=0)

    def test_cancellation_after_first_chunk(self):
        # 7 张图、chunk_pages=3：第一块写完后取消
        paths = self._make_images(7)
        out = self.folder / "out.pdf"
        out.write_bytes(b"sentinel")  # 预置文件，验证取消时会被删除
        calls = []

        def should_cancel():
            calls.append(1)
            return len(calls) > 1  # 第一次 False，之后 True

        with self.assertRaises(pdf_engine.ConversionCancelled):
            pdf_engine.convert_images_to_pdf(
                paths, out, chunk_pages=3, should_cancel=should_cancel)
        self.assertFalse(out.exists())

    def test_corrupt_image_leaves_no_partial_pdf(self):
        good = make_image(self.folder / "good.png")
        bad = self.folder / "bad.jpg"
        bad.write_bytes(b"this is definitely not an image")
        out = self.folder / "out.pdf"
        out.write_bytes(b"sentinel")  # 预置文件，验证失败时会被删除
        with self.assertRaises((OSError, ValueError)):
            pdf_engine.convert_images_to_pdf([good, bad], out)
        self.assertFalse(out.exists())

    def test_quality_reaches_encoder(self):
        # 同一张高熵噪声图，quality=10 必须比 quality=95 小
        noise = make_noise_image(self.folder / "noise.png")
        out_lo = pdf_engine.convert_images_to_pdf(
            [noise], self.folder / "lo.pdf", quality=10)
        out_hi = pdf_engine.convert_images_to_pdf(
            [noise], self.folder / "hi.pdf", quality=95)
        self.assertLess(
            Path(out_lo).stat().st_size,
            Path(out_hi).stat().st_size,
        )

    def test_progress_callback(self):
        paths = self._make_images(5)
        events = []
        pdf_engine.convert_images_to_pdf(
            paths, self.folder / "out.pdf", chunk_pages=2,
            progress=lambda done, total, name: events.append((done, total, name)))
        # 每张图一次 + 最后一次完成通知
        self.assertEqual(len(events), 6)
        self.assertEqual(events[0], (0, 5, paths[0].name))
        self.assertEqual(events[-1], (5, 5, ""))
        self.assertEqual([e[0] for e in events], [0, 1, 2, 3, 4, 5])
        self.assertTrue(all(e[1] == 5 for e in events))


class TestConvertFolder(unittest.TestCase):
    """convert_folder：端到端文件夹转换。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_end_to_end(self):
        for i in range(4):
            make_image(self.folder / f"{i}.png", color=(i * 40 % 256, 0, 0))
        (self.folder / "ignore.txt").write_text("not an image")
        out = pdf_engine.convert_folder(
            self.folder, self.folder / "out.pdf", chunk_pages=2)
        self.assertEqual(pdf_page_count(Path(out).read_bytes()), 4)

    def test_empty_folder_raises(self):
        with self.assertRaises(ValueError):
            pdf_engine.convert_folder(self.folder, self.folder / "out.pdf")


class TestManyChunksWithRealParser(unittest.TestCase):
    """回归测试：分块数超过 4 时的合并正确性。

    这个类使用 pypdf（独立于本文件那个手写的 /Prev 链解析器）作为校验器。
    手写解析器是围绕 Pillow append 模式的增量结构写的，会把 append 产生的
    病态结构当成合法结果——正是它让「5 块即崩」的缺陷两次绿灯。

    缺陷本身：Pillow 的 append=True 增量追加在第 5 块抛
    PdfFormatError: trailer loop found（实测 23 张图 / chunk_pages=5）。
    默认 chunk_pages=10 意味着超过 40 张图必崩，而真实用例是 200 页左右。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_52_images_over_6_chunks_is_valid_pdf(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf 未安装，无法用独立解析器校验")

        count = 52
        for i in range(count):
            make_image(self.folder / f"{i:03d}.png", size=(60, 90),
                       color=(i * 5 % 256, 40, 90))
        images = pdf_engine.collect_images(self.folder)
        out = pdf_engine.convert_images_to_pdf(
            images, self.folder / "out.pdf", chunk_pages=10)

        reader = PdfReader(str(out))
        self.assertEqual(len(reader.pages), count,
                         f"块数 {-(-count // 10)} 超过 4，合并结果页数不对")

    def test_single_page_tree_in_merged_output(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf 未安装")

        for i in range(30):
            make_image(self.folder / f"{i:03d}.png", size=(60, 90))
        out = pdf_engine.convert_images_to_pdf(
            pdf_engine.collect_images(self.folder),
            self.folder / "out.pdf", chunk_pages=5)

        raw = Path(out).read_bytes()
        self.assertEqual(raw.count(b"/Type /Pages"), 1,
                         "合并后的 PDF 应只有一棵页树，实际出现了多棵")

    def test_jpeg_filter_used_not_flate(self):
        for i in range(30):
            make_image(self.folder / f"{i:03d}.png", size=(60, 90))
        out = pdf_engine.convert_images_to_pdf(
            pdf_engine.collect_images(self.folder),
            self.folder / "out.pdf", chunk_pages=5)

        raw = Path(out).read_bytes()
        self.assertIn(b"/DCTDecode", raw,
                      "应使用 JPEG(DCTDecode)；出现 Flate 即意味着体积会膨胀 4x+")


if __name__ == "__main__":
    unittest.main()
