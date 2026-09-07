#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""folder_to_pdf.py 核心逻辑的单元测试（unittest，无外部依赖）。

运行：python -m unittest test_folder_to_pdf -v
在 WSL/Linux 主机上可运行（不测试需要 winreg/PDF.dll 的探测与插件逻辑）。
"""

import unittest
import tempfile
import os
from pathlib import Path

# 让测试能 import 到目标脚本（Windows 中文路径在 WSL 下也可访问）
SCRIPT_PATH = Path(__file__).parent / "folder_to_pdf.py"
import importlib.util

spec = importlib.util.spec_from_file_location("folder_to_pdf", SCRIPT_PATH)
assert spec is not None and spec.loader is not None, "无法加载 folder_to_pdf.py"
folder_to_pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(folder_to_pdf)

natural_key = folder_to_pdf.natural_key
collect_images = folder_to_pdf.collect_images
build_multipdf_cmd = folder_to_pdf.build_multipdf_cmd
IMAGE_EXTS = folder_to_pdf.IMAGE_EXTS


class TestNaturalKey(unittest.TestCase):
    """自然排序：数字感知，'2' 排 '10' 前；字母顺序且大小写无关。"""

    def test_numeric_order(self):
        names = ["10.jpg", "2.jpg", "1.jpg", "001.jpg"]
        # natural_key 对数值相同的项（1 vs 001）保持输入稳定顺序
        self.assertEqual(
            sorted(names, key=natural_key),
            ["1.jpg", "001.jpg", "2.jpg", "10.jpg"],
        )

    def test_numeric_sort_correct(self):
        # 模拟 000~105 的命名
        names = [f"{i:03d}.jpg" for i in range(105, -1, -1)]
        sorted_names = sorted(names, key=natural_key)
        self.assertEqual(sorted_names[0], "000.jpg")
        self.assertEqual(sorted_names[-1], "105.jpg")
        self.assertEqual(len(sorted_names), 106)

    def test_case_insensitive_alpha(self):
        names = ["B.jpg", "a.jpg", "C.jpg", "b.jpg"]
        self.assertEqual(
            sorted(names, key=natural_key),
            ["a.jpg", "B.jpg", "b.jpg", "C.jpg"],
        )


class TestCollectImages(unittest.TestCase):
    """仅顶层、按扩展名过滤、自然序排序、空文件夹报错。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_only_images_top_level(self):
        (self.folder / "2.png").write_bytes(b"x")
        (self.folder / "1.jpg").write_bytes(b"x")
        (self.folder / "10.txt").write_bytes(b"x")  # 非图片
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / "3.jpg").write_bytes(b"x")  # 子文件夹应被忽略
        imgs = collect_images(self.folder)
        self.assertEqual([p.name for p in imgs], ["1.jpg", "2.png"])

    def test_natural_sort(self):
        (self.folder / "10.jpg").write_bytes(b"x")
        (self.folder / "2.jpg").write_bytes(b"x")
        imgs = collect_images(self.folder)
        self.assertEqual([p.name for p in imgs], ["2.jpg", "10.jpg"])

    def test_empty_folder_raises(self):
        with self.assertRaises(ValueError):
            collect_images(self.folder)

    def test_nonexistent_folder_raises(self):
        with self.assertRaises(ValueError):
            collect_images(Path(self.folder) / "nope")

    def test_extension_match_case_insensitive(self):
        (self.folder / "A.PNG").write_bytes(b"x")
        (self.folder / "b.Jpg").write_bytes(b"x")
        imgs = collect_images(self.folder)
        self.assertEqual(len(imgs), 2)


class TestBuildMultipdfCmd(unittest.TestCase):
    """命令构建：短列表直传 CLI；长列表回退 filelist（ANSI 编码）。"""

    def test_short_direct_list(self):
        out = Path(r"C:\out\out.pdf")
        imgs = [Path(r"C:\img\a.jpg"), Path(r"C:\img\b.jpg")]
        cmd, tmp = build_multipdf_cmd(Path("i_view64.exe"), out, imgs)
        self.assertIsNone(tmp)
        self.assertIn("/multipdf=", cmd)
        self.assertIn('"C:\\img\\a.jpg"', cmd)
        self.assertIn('"C:\\img\\b.jpg"', cmd)
        self.assertTrue(cmd.endswith("/cmdexit"))

    def test_long_list_falls_back_to_filelist(self):
        # 构造超过 3800 字符的路径列表（长路径 + 大量文件）
        out = Path(r"C:\out\out.pdf")
        long_path = r"C:\VeryLongDirectoryNameToPushLengthOverLimit" + "\\" * 5 + "image"
        imgs = [Path(long_path + f"_{i}.jpg") for i in range(60)]
        cmd, tmp = build_multipdf_cmd(Path("i_view64.exe"), out, imgs)
        self.assertIsNotNone(tmp)
        self.assertIn("filelist=", cmd)
        # 文件列表存在且每个路径一行
        # mbcs 仅 Windows 有效，这里用系统默认编码（与生产代码的兜底一致）
        import sys
        with open(tmp, "r", encoding=sys.getdefaultencoding()) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 60)
        # 清理
        os.unlink(tmp)

    def test_normal_paths_stay_direct_when_short(self):
        # 短路径总长 <3800 应走直传（不含 filelist=），且空格路径不崩溃、引号保留
        out = Path(r"C:\out space\out.pdf")
        imgs = [Path(r"C:\img space\a.jpg")]
        cmd, tmp = build_multipdf_cmd(Path(r"C:\Program Files\IrfanView\i_view64.exe"), out, imgs)
        self.assertIsNone(tmp)
        self.assertNotIn("filelist=", cmd)
        self.assertIn("/multipdf=", cmd)
        # 内嵌引号必须原样保留（shell=True 依赖此特性），不能是转义反斜杠
        self.assertNotIn('\\"', cmd)


if __name__ == "__main__":
    unittest.main()
