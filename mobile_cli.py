#!/system/bin/env python3
# -*- coding: utf-8 -*-
"""手机端一次性转换 CLI —— 给 Agent / 自动化脚本直接调用，不需要起服务、不需要浏览器。

默认输出**结构化 JSON 到 stdout**（日志与错误走 stderr），方便调用方解析：

    i2p --list /sdcard/DCIM/Camera          # 探查：有几张图、按什么顺序
    i2p /sdcard/DCIM/Camera --json          # 生成单个 PDF（默认输出目录）
    i2p /sdcard/DCIM/Camera -o /sdcard/Download/x.pdf --open
    i2p /sdcard/DCIM --mode batch --json    # 每个子文件夹一个 PDF
    i2p --info                              # 环境自检

退出码：0 成功 / 1 转换或参数失败 / 2 被中断。
"""

from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

from pdf_builder import build_pdf, ConversionCancelled, PageError
from folder_to_pdf import natural_key, IMAGE_EXTS, subfolders_with_images

DEFAULT_OUTPUT_DIR = Path("/storage/emulated/0/Download/Images-to-PDF")


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%d B" % n if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def _images_in(folder):
    return sorted(
        [x for x in folder.iterdir()
         if x.is_file() and x.suffix.lower() in IMAGE_EXTS],
        key=lambda x: natural_key(x.name),
    )


def do_info():
    ff = shutil.which("ffmpeg")
    return {
        "ok": bool(ff),
        "ffmpeg": ff,
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "output_dir_exists": DEFAULT_OUTPUT_DIR.is_dir(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }


def do_list(raw):
    p = Path(str(raw)).expanduser().resolve()
    if not p.exists():
        raise ValueError("路径不存在：%s" % p)
    if not p.is_dir():
        raise ValueError("不是文件夹：%s" % p)
    imgs = _images_in(p)
    # 跳过 .thumbnails 之类的隐藏系统目录
    subs = [s for s in subfolders_with_images(p) if not s.name.startswith(".")]
    return {
        "path": str(p),
        "image_count": len(imgs),
        "images": [
            {"name": x.name, "path": str(x), "size": x.stat().st_size}
            for x in imgs
        ],
        "subfolders": [
            {"name": s.name, "path": str(s), "images": len(_images_in(s))}
            for s in subs
        ],
    }


def _chapter_dirs(folder):
    """单次遍历找出所有「话目录」：自身直接含图片、且没有任何后代目录含图片。

    漫画库结构是 分类/书名/第NNN话/*.jpg；书根只有一个 cover.jpg，
    按「话」目录切分正好。返回 [(Path, 相对显示名)]，自然序。
    只做一次 os.walk，不在循环里重复 listdir（FUSE 上很贵）。
    """
    folder = Path(folder)
    with_imgs = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if any(f.lower().endswith(tuple(IMAGE_EXTS)) for f in filenames):
            with_imgs.append(Path(dirpath))

    # 祖先判定：若某目录是另一个含图目录的严格前缀，则它不是叶子
    parents = set()
    for p in with_imgs:
        for anc in p.parents:
            if anc in with_imgs and anc != p:
                parents.add(str(anc))
            if anc == folder.parent:
                break
    leaves = [p for p in with_imgs if str(p) not in parents]
    leaves.sort(key=lambda p: natural_key(str(p.relative_to(folder))))
    return [(p, str(p.relative_to(folder))) for p in leaves]


def do_convert(folder_raw, mode, output, page_size, quality, open_after, log,
               recursive=False, skip_existing=False, verbose=False):
    folder = Path(str(folder_raw)).expanduser()
    if not folder.is_dir():
        raise ValueError("不是文件夹：%s" % folder)

    if mode == "batch":
        if recursive:
            # 每个话目录一个 PDF，输出目录镜像原目录结构
            chapters = _chapter_dirs(folder)
            if not chapters:
                raise ValueError("递归批量下没有找到含图片的话目录：%s" % folder)
            out_dir = Path(str(output or DEFAULT_OUTPUT_DIR)).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            pairs = []
            for ch, rel in chapters:
                imgs = _images_in(ch)
                dst = out_dir / (rel + ".pdf")
                dst.parent.mkdir(parents=True, exist_ok=True)
                pairs.append((imgs, dst, rel))
        else:
            subs = [s for s in subfolders_with_images(folder)
                    if not s.name.startswith(".")]
            if not subs:
                raise ValueError("批量模式下没有找到含图片的子文件夹：%s" % folder)
            out_dir = Path(str(output or DEFAULT_OUTPUT_DIR)).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            pairs = []
            for sub in subs:
                imgs = _images_in(sub)
                if imgs:
                    pairs.append((imgs, out_dir / ("%s.pdf" % sub.name), sub.name))
    else:
        if recursive:
            # 整棵树的所有图片按目录自然序合成一个 PDF
            chapters = _chapter_dirs(folder)
            if not chapters:
                raise ValueError("递归单本下没有找到含图片的话目录：%s" % folder)
            imgs = [img for ch, _ in chapters for img in _images_in(ch)]
            if not imgs:
                raise ValueError("没有收集到图片：%s" % folder)
            out = Path(str(output or (DEFAULT_OUTPUT_DIR / ("%s.pdf" % folder.name)))).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            pairs = [(imgs, out, folder.name)]
        else:
            imgs = _images_in(folder)
            if not imgs:
                raise ValueError("文件夹中没有找到支持的图片：%s" % folder)
            out = Path(str(output or (DEFAULT_OUTPUT_DIR / ("%s.pdf" % folder.name)))).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            pairs = [(imgs, out, folder.name)]

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    results = []
    skipped = 0
    failed = []
    for imgs, out_pdf, label in pairs:
        if skip_existing and out_pdf.exists() and out_pdf.stat().st_size > 0:
            skipped += 1
            if log:
                print("[i2p] 跳过（已存在）%s" % out_pdf, file=sys.stderr)
            continue
        if log:
            print("[i2p] %s：%d 张 → %s" % (label, len(imgs), out_pdf),
                  file=sys.stderr)

        def progress(done, total, name, reencoded):
            if log and verbose:
                print("[i2p]   第 %d/%d 页 %s%s" % (
                    done, total, name, " (转码)" if reencoded else ""),
                    file=sys.stderr)

        try:
            r = build_pdf(imgs, out_pdf, page_size=page_size, quality=quality,
                          ffmpeg=ffmpeg, progress=progress)
        except Exception as e:
            # 单个话失败不能拖垮整批（1116 话里有一两张坏图很正常）
            failed.append({"name": label, "error": "%s: %s" % (type(e).__name__, e)})
            if log:
                print("[i2p]   ❌ %s 失败：%s" % (label, e), file=sys.stderr)
            continue
        results.append({
            "name": label,
            "output": r["output"],
            "pages": r["pages"],
            "size": r["size"],
            "size_h": _human(r["size"]),
            "reencoded": r["reencoded"],
        })

    if open_after and results and shutil.which("termux-open"):
        subprocess.Popen(
            ["termux-open", "--view", results[-1]["output"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    return {
        "ok": not failed,
        "mode": mode,
        "page_size": page_size,
        "recursive": bool(recursive),
        "pdf_count": len(results),
        "skipped": skipped,
        "failed": failed,
        "pages": sum(r["pages"] for r in results),
        "results": results,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="i2p",
        description="把图片文件夹合成 PDF（手机端，主要供 Agent / 脚本调用）",
    )
    ap.add_argument("folder", nargs="?", help="图片文件夹路径")
    ap.add_argument("-o", "--output", help="单个模式=PDF 文件路径；批量模式=输出目录")
    ap.add_argument("--mode", choices=("single", "batch"), default="single")
    ap.add_argument("--page-size", choices=("auto", "a4"), default="auto",
                    help="auto=原尺寸(1px=1pt)，a4=A4 等比居中")
    ap.add_argument("--quality", type=int, default=2,
                    help="非 JPEG 转码的 ffmpeg -q:v（1 最好 / 31 最小）")
    ap.add_argument("--list", action="store_true", help="只列出图片与子文件夹（JSON），不转换")
    ap.add_argument("--info", action="store_true", help="环境自检，不转换")
    ap.add_argument("--open", action="store_true", help="完成后用 termux-open 打开生成的 PDF")
    ap.add_argument("--recursive", "-r", action="store_true",
                    help="递归：batch=每个话目录一个 PDF（镜像目录结构），single=整棵树合成一个 PDF")
    ap.add_argument("--skip-existing", action="store_true",
                    help="输出 PDF 已存在且非空就跳过（断点续跑）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认即为 JSON，此参数兼容显式写法）")
    ap.add_argument("--human", action="store_true", help="改用人类可读输出（非 JSON）")
    ap.add_argument("--quiet", action="store_true", help="完全静默（不打进度日志）")
    ap.add_argument("--verbose", "-v", action="store_true", help="逐页打印进度（默认只打每个 PDF 一行）")
    args = ap.parse_args(argv)

    try:
        if args.info:
            data = do_info()
        elif args.list:
            if not args.folder:
                raise ValueError("--list 需要一个文件夹路径")
            data = do_list(args.folder)
        else:
            if not args.folder:
                raise ValueError("需要提供图片文件夹路径（或用 --list / --info）")
            if not 1 <= args.quality <= 31:
                raise ValueError("--quality 必须在 1~31 之间")
            data = do_convert(
                args.folder, args.mode, args.output, args.page_size,
                args.quality, args.open, log=not args.quiet,
                recursive=args.recursive, skip_existing=args.skip_existing,
                verbose=args.verbose,
            )
    except (ConversionCancelled, KeyboardInterrupt):
        print(json.dumps({"ok": False, "error": "已中断"}, ensure_ascii=False))
        return 2
    except (ValueError, PageError, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1

    if args.human:
        if "results" in data:
            for r in data["results"]:
                print("✅ %s  %d 页  %s%s" % (
                    r["output"], r["pages"], r["size_h"],
                    "（%d 张转码）" % r["reencoded"] if r["reencoded"] else ""))
            if data.get("failed"):
                for f in data["failed"]:
                    print("❌ %s：%s" % (f["name"], f["error"]))
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        # 大规模批量时 results 可能上千条，默认只回摘要 + 失败清单
        if len(data.get("results", [])) > 20:
            data = dict(data)
            data["results"] = data["results"][:3] + ["…（共 %d 条，用 --human 看全量）" % len(data["results"])]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    # 只有转换结果用 ok 判定失败；--info / --list 不算
    if "results" in data and not data.get("ok", True):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
