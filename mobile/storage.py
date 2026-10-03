#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Android 存储抽象层 —— 隔离 SAF / 分区存储 / 权限，向上层只暴露普通 Path。

桌面版 folder_to_pdf.py 直接读一个文件夹路径。Android 上没有这种东西：

* 系统文件选择器返回的是 ``content://`` URI，背后是某个 ContentProvider，
  没有可用的 ``.parent``，也不能直接 open()；
* 自 Android 11（API 30）起，分区存储禁止应用自由读取 /sdcard，必须由用户
  在系统设置里授予「所有文件访问权限」（MANAGE_EXTERNAL_STORAGE）。

本模块把这些差异全部吞掉，让 Kivy 界面只需要处理一个字符串 target，
并且无论目标是 content:// URI 还是普通路径，最终都拿到一个**真实的本地
目录 Path**，交给 pdf_engine 去遍历。

桌面 Linux 上的可测试性（硬约束）
--------------------------------
本模块在桌面 Linux 上必须能干净导入 —— 那儿没有 jnius / android / plyer，
``is_android()`` 返回 False 而不是抛异常。因此所有 Android 专有依赖都在
**函数内部**惰性导入，所有平台分支也都关在各自的函数里。凡是本环境下
执行不到的代码路径，都在函数注释里明确标注「未在本环境验证」。

content:// 的设计取舍（重要，不是巧合）
------------------------------------
Android 上 ``plyer.filechooser.choose_dir()`` 是**静默空操作**
（AndroidFileChooser._file_selection_dialog 只处理 mode in ('open','save')，
mode='dir' 直接掉出去且不报错）。所以用户在 Android 上**只能选到单个文件，
永远选不到文件夹**。这意味着 materialise() 收到的 content:// URI 通常指向
**一张图片**，而不是一个目录。

折中方案：
1. 能枚举时 —— 用 DocumentsContract 找到该文档的父目录，枚举同级文档，
   把整个同级集合物化到缓存目录，返回该目录；
2. 不能枚举时 —— 只物化这一个文件，返回缓存中的目录（里就这一张）。

两种情况返回的都是目录，因此 pdf_engine.collect_images() 总能工作。
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, List, Optional

# ================= 用户可修改区 =================

CACHE_DIRNAME = "saf_cache"

# 输出目录名（在 app 外部私有目录下，不需要任何权限）
OUTPUT_DIRNAME = "PDF_Output"

# ===============================


class StorageError(Exception):
    """存储层通用错误。"""


class PermissionDenied(StorageError):
    """缺少读取用户所选目录所需的权限。UI 应据此提示用户去授权。"""


class UnsupportedUri(StorageError):
    """无法解析的 target。既不是路径，也不是可识别的 content:// URI。"""


def is_android() -> bool:
    """是否运行在 Android 上。桌面环境恒为 False，且绝不抛异常。"""
    if os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_ROOT"):
        return True
    try:
        from jnius import autoclass  # noqa: F401
    except Exception:
        return False
    # jnius 存在几乎必然意味着 p4a 运行时，但仍在真机语义上再确认一次
    try:
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        return activity is not None
    except Exception:
        return False


def cache_dir() -> Path:
    """app缓存目录 / saf_cache，按需创建。

    桌面环境下退回到 tempfile.gettempdir()，便于本地开发与测试。
    """
    try:
        from android.storage import primary_external_storage_path  # type: ignore
        base = str(primary_external_storage_path())
    except Exception:
        import tempfile
        base = tempfile.gettempdir()
    root = Path(base) / CACHE_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def clear_cache() -> None:
    """删除缓存目录。幂等：目录不存在时静默返回。"""
    root = cache_dir()
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


def default_output_dir() -> Path:
    """默认输出目录，无需任何权限即可写入。"""
    try:
        from android.storage import primary_external_storage_path  # type: ignore
        return Path(primary_external_storage_path()) / OUTPUT_DIRNAME
    except Exception:
        return cache_dir() / OUTPUT_DIRNAME


def unique_output_path(folder: Path, stem: str) -> Path:
    """在 folder 下为 stem 生成不覆盖已有文件的 PDF 路径。

    依次尝试 stem.pdf / stem (1).pdf / stem (2).pdf …… 已存在的绝不覆盖。
    """
    folder = Path(folder)
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(stem).strip()) or "images"
    candidate = folder / f"{safe}.pdf"
    counter = 1
    while candidate.exists():
        candidate = folder / f"{safe} ({counter}).pdf"
        counter += 1
    return candidate


# ============================ 权限 ============================

def has_all_files_access() -> bool:
    """是否已获得「所有文件访问权限」。

    API 30 以下不适用，一律视为已授权。
    """
    if not is_android():
        return True
    try:
        # 未在本环境验证：Settings.canWrite / MANAGE_EXTERNAL_STORAGE 的标准检查法
        from jnius import autoclass
        Build = autoclass("android.os.Build")
        if Build.VERSION.SDK_INT < 30:
            return True
        context = autoclass("org.kivy.android.PythonActivity").mActivity
        env = autoclass("android.os.Environment")
        return bool(context.checkSelfPermission(
            env.MANAGE_EXTERNAL_STORAGE
        ) == 0)
    except Exception:
        # 检查失败时保守返回 False，让 UI 提示用户；绝不假装已授权。
        return False


def request_all_files_access() -> bool:
    """打开系统「所有文件访问权限」设置页。返回是否成功拉起。

    **这是异步的**：拉起设置页后必须由用户在系统里手动开关，App 收不到回调。
    调用方应在 on_resume 时重新调用 has_all_files_access() 复查。
    """
    if not is_android():
        return False
    try:
        # 未在本环境验证：通过 Intent + ACTION_MANAGE_APP_PERMISSION 跳设置
        from jnius import autoclass, cast
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        env = autoclass("android.os.Environment")
        Build = autoclass("android.os.Build")
        action = "android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION" \
            if Build.VERSION.SDK_INT >= 30 else "android.settings.APPLICATION_DETAILS_SETTINGS"
        intent = Intent(action, Uri.parse("package:" + activity.getPackageName()))
        activity.startActivity(cast("android.content.Intent", intent))
        return True
    except Exception:
        return False


# ===================== content:// 解析（Android 专属） =====================
# 以下函数全部只在 Android 上可达，均未在桌面 Linux 环境中执行过。

def _resolve_content_resolver() -> Any:
    from jnius import autoclass
    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    return activity.getContentResolver()


def _open_stream(uri: Any) -> Any:
    resolver = _resolve_content_resolver()
    return resolver.openInputStream(uri)


def _parse_uri(target: str) -> Any:
    from jnius import autoclass
    return autoclass("android.net.Uri").parse(target)


def _query_display_name(resolver: Any, uri: Any) -> Optional[str]:
    try:
        cursor = resolver.query(uri, None, None, None, None)
        if cursor is None:
            return None
        try:
            index = cursor.getColumnIndex(
                "_display_name")  # DocumentsContract.Document.COLUMN_DISPLAY_NAME
            if index < 0:
                return None
            cursor.moveToFirst()
            return cursor.getString(index)
        finally:
            cursor.close()
    except Exception:
        return None


def _list_document_children(tree_uri: Any) -> List[Any]:
    """枚举一棵 SAF 树下的子文档 URI。失败返回空列表。"""
    from jnius import autoclass
    DocumentsContract = autoclass("android.provider.DocumentsContract")
    resolver = _resolve_content_resolver()
    children = DocumentsContract.buildChildDocumentsUriUsingTree(tree_uri, DocumentsContract.getTreeDocumentId(tree_uri))
    cursor = resolver.query(children, None, None, None, None)
    out: List[Any] = []
    if cursor is None:
        return out
    try:
        doc_id_col = cursor.getColumnIndex(
            DocumentsContract.Document.COLUMN_DOCUMENT_ID)
        if doc_id_col < 0:
            return out
        while cursor.moveToNext():
            child = DocumentsContract.buildDocumentUriUsingTree(tree_uri, cursor.getString(doc_id_col))
            out.append(child)
    finally:
        cursor.close()
    return out


def _is_tree_uri(uri: Any) -> bool:
    from jnius import autoclass
    DocumentsContract = autoclass("android.provider.DocumentsContract")
    try:
        DocumentsContract.getTreeDocumentId(uri)
        return True
    except Exception:
        return False


def _copy_stream_to(uri: Any, dest: Path) -> int:
    """把 content:// 流复制到 dest，返回写入字节数。"""
    written = 0
    source = _open_stream(uri)
    if source is None:
        raise StorageError("无法打开该 URI 的输入流（可能已被删除或无授权）")
    try:
        with open(dest, "wb") as handle:
            while True:
                buffer = bytearray(8192)
                read = source.read(buffer, 0, len(buffer))
                if read <= 0:
                    break
                handle.write(bytes(buffer[:read]))
                written += read
    finally:
        source.close()
    return written


def _materialise_content_uri(target: str) -> Path:
    """把 content:// URI 物化到缓存目录，返回本地目录 Path。

    未在本环境验证：依赖 jnius + DocumentsContract 的 SAF 语义。
    设计取舍见模块 docstring —— 单文件 URI 会退化为「只缓存这一张」。
    """
    from jnius import autoclass
    DocumentsContract = autoclass("android.provider.DocumentsContract")

    uri = _parse_uri(target)
    name = _query_display_name(_resolve_content_resolver(), uri) or "picked"

    # 情况 1：这本身是一棵树（ACTION_OPEN_DOCUMENT_TREE 选到的文件夹）
    if _is_tree_uri(uri):
        dest_dir = cache_dir() / "tree"
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        dest_dir.mkdir(parents=True, exist_ok=True)
        children = _list_document_children(uri)
        for child in children:
            child_name = _query_display_name(_resolve_content_resolver(), child) or "f"
            try:
                _copy_stream_to(child, dest_dir / child_name)
            except StorageError:
                # 单个子文档读不到就跳过，不让整批失败
                continue
        return dest_dir

    # 情况 2：单个文件。尝试找父目录；找不到就只缓存这一个文件。
    parent_uri = None
    try:
        if DocumentsContract.isDocumentUri(_resolve_content_resolver(), uri):
            doc_id = DocumentsContract.getDocumentId(uri)
            parent_id = doc_id.rsplit(":", 1)[0] if ":" in doc_id else doc_id
            parent_uri = DocumentsContract.buildDocumentUriUsingTree(uri, parent_id)
    except Exception:
        parent_uri = None

    dest_dir = cache_dir() / "single"
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    siblings = _list_document_children(parent_uri) if parent_uri is not None else []
    for sibling in siblings:
        sibling_name = _query_display_name(_resolve_content_resolver(), sibling) or "f"
        try:
            _copy_stream_to(sibling, dest_dir / sibling_name)
        except StorageError:
            # 某个同级文档读不到就跳过，不让整批失败
            continue
    if not any(dest_dir.iterdir()):
        # 同级一个都没读下来，退化为只缓存选中的那一张
        _copy_stream_to(uri, dest_dir / name)
    return dest_dir


# ============================ 主入口 ============================

def materialise(target: str) -> Path:
    """把 target 解析成一个真实的本地目录 Path。

    * 普通路径且是已存在的目录 -> 原样返回（桌面/已授权场景零拷贝）
    * 普通路径且是已存在的文件 -> 返回其父目录（调用方按"选到文件就取其所在
      目录"处理，因为 Android 上选不到文件夹）
    * ``content://`` URI -> 物化到缓存目录后返回本地目录（Android 专属路径）
    * 其余 ->抛 UnsupportedUri，且异常消息里带上原始 target
    """
    if target is None:
        raise UnsupportedUri("target 为 None")
    text = str(target).strip().strip('"').strip("'")
    if not text:
        raise UnsupportedUri("target 为空字符串")

    if "://" in text:
        scheme = text.split("://", 1)[0]
        if scheme != "content":
            raise UnsupportedUri(
                f"不支持的 URI scheme：{scheme}（仅支持 content://）。原始输入：{text}")
        try:
            return _materialise_content_uri(text)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"解析 content URI 失败：{exc}") from exc

    path = Path(text)
    try:
        exists = path.exists()
    except OSError as exc:
        raise PermissionDenied(f"无法访问 {text}：{exc}") from exc

    if not exists:
        # Android 11+ 上未授权时，路径看起来就是「不存在」的
        if is_android() and not has_all_files_access():
            raise PermissionDenied(
                f"无法读取 {text}：缺少「所有文件访问权限」。请在系统设置中授予。"
            )
        raise UnsupportedUri(f"路径不存在：{text}")

    if path.is_dir():
        return path
    return path.parent


def list_images(target: str) -> List[Path]:
    """materialise + pdf_engine.collect_images 的便捷组合。

    注意：pdf_engine 未导入本模块，此处延迟导入以避免循环依赖。
    """
    import pdf_engine

    return pdf_engine.collect_images(materialise(target))