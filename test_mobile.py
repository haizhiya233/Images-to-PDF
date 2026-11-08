#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机端（pdf_builder.py / mobile_app.py）单元测试。

纯标准库，可在 Windows / Linux / Termux 上跑；只有标记了 ffmpeg 的用例
才需要本机有 ffmpeg（缺失时自动 skip）。

运行：python -m unittest test_mobile -v
"""

import importlib.util
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pdf_builder = _load("pdf_builder")
mobile_app = _load("mobile_app")
mobile_cli = _load("mobile_cli")


def _make_mini_jpeg(w=8, h=8):
    """纯标准库造一个合法 baseline RGB JPEG（全黑，8x8 对齐）。

    不依赖 Pillow / ffmpeg：自己写 JFIF/DQT/SOF0/DHT/SOS，熵数据每个
    8x8 块只用「DC 差值 0」+「EOB」两个 1 位 Huffman 码。测试只需要
    让 jpeg_info / PDF 阅读器认出它是合法 JPEG，不需要好看的画面。
    """
    def seg(marker, payload):
        return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload

    app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt = b"\x00" + bytes([16] * 64)                       # Pq/Tq=0，量化表全 16
    sof0 = struct.pack(">BHHB", 8, h, w, 3) + bytes(
        [1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0]
    )
    # DC / AC 各一张 Huffman 表：只有一个 1 位码（0），symbol 都是 0
    counts = bytes([1] + [0] * 15)
    dht_dc = b"\x00" + counts + b"\x00"                    # category 0
    dht_ac = b"\x10" + counts + b"\x00"                    # EOB (0x00)
    sos = bytes([3, 1, 0x00, 2, 0x00, 3, 0x00, 0, 63, 0])

    mcus = ((w + 7) // 8) * ((h + 7) // 8)
    bits = "00" * 3 * mcus                                 # 每块：DC(0)+EOB(0)
    bits += "1" * ((-len(bits)) % 8)                       # 用 1 补齐字节
    entropy = bytearray()
    for i in range(0, len(bits), 8):
        b = int(bits[i:i + 8], 2)
        entropy.append(b)
        if b == 0xFF:                                       # 字节填充
            entropy.append(0x00)
    return (b"\xff\xd8" + seg(0xE0, app0) + seg(0xDB, dqt)
            + seg(0xC0, sof0) + seg(0xC4, dht_dc) + seg(0xC4, dht_ac)
            + seg(0xDA, sos) + bytes(entropy) + b"\xff\xd9")


_MINI_JPEG = _make_mini_jpeg()


def _make_exif(orientation):
    """构造一个带 Orientation tag 的最小 APP1/Exif 段（大端 TIFF）。

    IFD 结构：entry count(2) + entry(12: tag2/type2/count4/value4) + next IFD(4)。
    SHORT 类型的值占 entry 的前 2 字节，后 2 字节补 0。
    """
    ifd = struct.pack(">H", 1)                                  # 1 个 entry
    ifd += struct.pack(">HHIHH", 0x0112, 3, 1, orientation, 0)
    ifd += struct.pack(">I", 0)                                 # 无后续 IFD
    tiff = b"MM" + struct.pack(">HI", 42, 8) + ifd             # IFD0 在偏移 8
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


class TestJpegInfo(unittest.TestCase):
    def test_mini_jpeg_parsed(self):
        info = pdf_builder.jpeg_info(_MINI_JPEG)
        self.assertEqual((info["width"], info["height"]), (8, 8))
        self.assertEqual(info["components"], 3)
        self.assertEqual(info["colorspace"], "/DeviceRGB")
        self.assertFalse(info["progressive"])
        self.assertEqual(info["orientation"], 1)

    def test_not_jpeg_raises(self):
        with self.assertRaises(ValueError):
            pdf_builder.jpeg_info(b"not a jpeg")

    def test_progressive_sofc2(self):
        # 把 SOF0 (FFC0) 改成 SOF2 (FFC2)，其余字节不变
        data = bytearray(_MINI_JPEG)
        idx = data.find(b"\xff\xc0")
        self.assertGreater(idx, 0)
        data[idx + 1] = 0xC2
        info = pdf_builder.jpeg_info(bytes(data))
        self.assertTrue(info["progressive"])

    def test_exif_orientation_6_detected(self):
        data = _MINI_JPEG[:2] + _make_exif(6) + _MINI_JPEG[2:]
        self.assertEqual(pdf_builder.jpeg_info(data)["orientation"], 6)

    def test_exif_orientation_1_stays_passthrough(self):
        data = _MINI_JPEG[:2] + _make_exif(1) + _MINI_JPEG[2:]
        self.assertTrue(pdf_builder._can_passthrough(pdf_builder.jpeg_info(data)))

    def test_num_has_no_scientific_notation(self):
        self.assertEqual(pdf_builder._num(595.2756), "595.2756")
        self.assertEqual(pdf_builder._num(0), "0")
        self.assertNotIn("e", pdf_builder._num(1e-8))


class TestPassthroughDecision(unittest.TestCase):
    def test_progressive_still_passthrough(self):
        # progressive 也是合法 DCT 流，PDF 阅读器能解码，不该浪费一次有损重编码
        info = pdf_builder.jpeg_info(_MINI_JPEG)
        info["progressive"] = True
        self.assertTrue(pdf_builder._can_passthrough(info))

    def test_rotated_not_passthrough(self):
        info = pdf_builder.jpeg_info(_MINI_JPEG)
        info["orientation"] = 6
        self.assertFalse(pdf_builder._can_passthrough(info))

    def test_cmyk_colorspace_is_none(self):
        info = pdf_builder.jpeg_info(_MINI_JPEG)
        info["colorspace"] = None
        self.assertFalse(pdf_builder._can_passthrough(info))


class TestBuildPdf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inp = self.root / "in"
        self.inp.mkdir()
        self.out = self.root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, data):
        p = self.inp / name
        p.write_bytes(data)
        return p

    def test_two_pages_structure_and_embedded_bytes(self):
        a = self._write("1.jpg", _MINI_JPEG)
        b = self._write("2.jpg", _MINI_JPEG)
        out = self.out / "x.pdf"
        r = pdf_builder.build_pdf([a, b], out)
        self.assertEqual(r["pages"], 2)
        self.assertEqual(r["reencoded"], 0)
        data = out.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/Type /Pages /Kids [3 0 R 6 0 R] /Count 2", data)
        self.assertIn(b"/Filter /DCTDecode", data)
        # JPEG 原始字节必须原样出现两次（零重编码）
        self.assertEqual(data.count(_MINI_JPEG), 2)
        # xref 偏移正确：每个对象都能被定位
        startxref = int(data.rsplit(b"startxref\n", 1)[1].split()[0])
        self.assertEqual(data[startxref:startxref + 4], b"xref")
        self.assertIn(b"/Root 1 0 R", data)

    def test_no_temp_residue(self):
        a = self._write("a.jpg", _MINI_JPEG)
        pdf_builder.build_pdf([a], self.out / "x.pdf")
        leftovers = [p for p in self.root.rglob("*")
                     if p.name.startswith(".i2p_") or p.name.startswith("i2p_")]
        self.assertEqual(leftovers, [])

    def test_failure_deletes_old_pdf(self):
        a = self._write("a.jpg", _MINI_JPEG)
        out = self.out / "x.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"OLD")
        with patch.object(pdf_builder, "_iter_pages", side_effect=pdf_builder.PageError("boom")):
            with self.assertRaises(pdf_builder.PageError):
                pdf_builder.build_pdf([a], out)
        self.assertFalse(out.exists())

    def test_cancel_cleans_up_and_no_pdf(self):
        a = self._write("a.jpg", _MINI_JPEG)
        out = self.out / "x.pdf"
        with self.assertRaises(pdf_builder.ConversionCancelled):
            pdf_builder.build_pdf([a], out, should_cancel=lambda: True)
        self.assertFalse(out.exists())

    def test_progress_callback(self):
        a = self._write("1.jpg", _MINI_JPEG)
        b = self._write("2.jpg", _MINI_JPEG)
        seen = []
        pdf_builder.build_pdf([a, b], self.out / "x.pdf",
                              progress=lambda d, n, name, re: seen.append((d, n, name, re)))
        self.assertEqual([(d, n) for d, n, _, _ in seen], [(1, 2), (2, 2)])
        self.assertEqual([name for _, _, name, _ in seen], ["1.jpg", "2.jpg"])
        self.assertFalse(any(re for _, _, _, re in seen))

    def test_a4_geometry(self):
        pw, ph, dw, dh, x, y = pdf_builder._page_geometry(1000, 2000, "a4")
        self.assertAlmostEqual(pw / ph, 595.2756 / 841.8898, places=4)
        self.assertAlmostEqual(dw / dh, 0.5, places=4)
        self.assertGreater(x, 0)
        self.assertAlmostEqual(y, 0, places=3)

    def test_auto_geometry(self):
        self.assertEqual(pdf_builder._page_geometry(320, 480, "auto"),
                         (320.0, 480.0, 320.0, 480.0, 0.0, 0.0))

    @unittest.skipUnless(shutil.which("ffmpeg"), "需要 ffmpeg")
    @unittest.skipUnless(shutil.which("magick"), "需要 ImageMagick 造 progressive JPEG")
    def test_progressive_jpeg_is_embedded_unchanged(self):
        # 造一张真 progressive JPEG，确认字节原样进 PDF、零重编码
        import subprocess
        base = self.inp / "1.jpg"
        subprocess.run(["magick", "-size", "16x16", "xc:orange", "-quality", "92",
                        str(base)], check=True, capture_output=True)
        prog = self.inp / "2.jpg"
        subprocess.run(["magick", str(base), "-interlace", "Plane", "-quality", "92",
                        str(prog)], check=True, capture_output=True)
        info = pdf_builder.jpeg_info(prog.read_bytes())
        self.assertTrue(info["progressive"])
        r = pdf_builder.build_pdf([prog], self.out / "x.pdf")
        self.assertEqual(r["reencoded"], 0)
        self.assertEqual(self.out.joinpath("x.pdf").read_bytes().count(prog.read_bytes()), 1)

    @unittest.skipUnless(shutil.which("ffmpeg"), "需要 ffmpeg")
    def test_png_is_transcoded(self):
        (self.inp / "1.jpg").write_bytes(_MINI_JPEG)
        png = self.inp / "2.png"
        # 用 ffmpeg 造一张真 PNG
        import subprocess
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=blue:s=8x6:d=1",
                        "-frames:v", "1", str(png)], check=True)
        r = pdf_builder.build_pdf([self.inp / "1.jpg", png], self.out / "x.pdf")
        self.assertEqual(r["pages"], 2)
        self.assertEqual(r["reencoded"], 1)
        self.assertEqual(self.out.joinpath("x.pdf").read_bytes().count(_MINI_JPEG), 1)


class TestMobileAppHelpers(unittest.TestCase):
    def test_safe_path_blocks_escape(self):
        with self.assertRaises(ValueError):
            mobile_app.safe_path("/etc/passwd", must_exist=False)

    def test_safe_path_allows_home(self):
        self.assertEqual(mobile_app.safe_path(str(Path.home())),
                         Path.home().resolve())

    def test_human(self):
        self.assertEqual(mobile_app._human(512), "512 B")
        self.assertEqual(mobile_app._human(2048), "2.0 KB")

    def test_list_folder_natural_sort(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "album"
            root.mkdir()
            for n in ("第10集", "第2集"):
                d = root / n
                d.mkdir()
                (d / "1.jpg").write_bytes(_MINI_JPEG)
            for n in ("10.jpg", "2.jpg", "1.jpg"):
                (root / n).write_bytes(_MINI_JPEG)
            # 临时目录不在手机存储根内，把白名单临时扩到它
            with patch.object(mobile_app, "ALLOWED_ROOTS", [Path(t).resolve()]):
                info = mobile_app.list_folder(str(root))
            self.assertEqual([d["name"] for d in info["dirs"]], ["第2集", "第10集"])
            self.assertEqual([i["name"] for i in info["images"]],
                             ["1.jpg", "2.jpg", "10.jpg"])
            self.assertEqual(info["image_count"], 3)

    def test_job_to_dict(self):
        j = mobile_app.Job()
        d = j.to_dict()
        self.assertIn("pages_total", d)
        self.assertEqual(d["state"], "idle")


class TestCli(unittest.TestCase):
    """CLI 是 Agent 的主入口：JSON 契约、退出码、错误处理。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inp = self.root / "in"
        self.inp.mkdir()
        (self.inp / "2.jpg").write_bytes(_MINI_JPEG)
        (self.inp / "10.jpg").write_bytes(_MINI_JPEG)

    def tearDown(self):
        self.tmp.cleanup()

    def test_info_ok(self):
        d = mobile_cli.do_info()
        self.assertIn("ffmpeg", d)
        self.assertIn("output_dir", d)

    def test_list_sorted_and_has_counts(self):
        d = mobile_cli.do_list(str(self.inp))
        self.assertEqual(d["image_count"], 2)
        self.assertEqual([i["name"] for i in d["images"]], ["2.jpg", "10.jpg"])

    def test_list_missing_path_raises(self):
        with self.assertRaises(ValueError):
            mobile_cli.do_list(str(self.root / "nope"))

    def test_convert_returns_structured_result(self):
        out = self.root / "out.pdf"
        d = mobile_cli.do_convert(str(self.inp), "single", str(out),
                                  "a4", 2, False, False)
        self.assertTrue(d["ok"])
        self.assertEqual(d["pdf_count"], 1)
        self.assertEqual(d["pages"], 2)
        self.assertEqual(d["results"][0]["output"], str(out))
        self.assertTrue(out.exists())

    def test_convert_empty_folder_raises(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(ValueError):
            mobile_cli.do_convert(str(empty), "single", None, "auto", 2, False, False)

    def test_main_json_stdout_and_exit_codes(self):
        # 成功 → 0 且 stdout 是可解析 JSON
        out = self.root / "out2.pdf"
        rc = mobile_cli.main([str(self.inp), "-o", str(out), "--quiet"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.exists())
        # 失败 → 1
        rc = mobile_cli.main(["--list", str(self.root / "nope")])
        self.assertEqual(rc, 1)

    def test_batch_mode(self):
        parent = self.root / "album"
        for n in ("第2集", "第10集"):
            d = parent / n
            d.mkdir(parents=True)
            (d / "1.jpg").write_bytes(_MINI_JPEG)
        out_dir = self.root / "batch_out"
        d = mobile_cli.do_convert(str(parent), "batch", str(out_dir),
                                  "auto", 2, False, False)
        self.assertEqual(d["pdf_count"], 2)
        self.assertEqual(d["pages"], 2)
        self.assertEqual([r["name"] for r in d["results"]], ["第2集", "第10集"])


if __name__ == "__main__":
    unittest.main()
