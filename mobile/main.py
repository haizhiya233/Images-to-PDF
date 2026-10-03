# -*- coding: utf-8 -*-
"""图片转 PDF — Android/Kivy 移动端界面层。

============================================================================
架构（ARCHITECTURE）
============================================================================
本文件是 **纯 UI + 编排（orchestration）**。所有 PDF 生成工作都在
`pdf_engine` 里，本文件一行 PDF 逻辑都没有。

单文件交付：所有 widget、样式、字符串都写在下面，没有额外的 .kv 文件。

    main.py            ← 本文件：Kivy 界面 + 线程编排
    pdf_engine.py      ← 同级模块：图片收集 / 自然排序 / PDF 写出（stdlib + Pillow）
    storage.py         ← 同级模块：SAF 授权、content:// 解析、缓存目录

导入顺序说明：`pdf_engine` 与 `storage` 是**同级模块**（不是包），所以先把本文件
所在目录塞进 `sys.path`，这样无论从哪个工作目录启动（`python main.py`、
buildozer 的 `main.py`、或被测试 import）都能找到它们。

模块级依赖契约（两个 peer agent 并行编写，我按契约编码，未创建这两个文件）：

    pdf_engine:
        IMAGE_EXTENSIONS, DEFAULT_QUALITY, DEFAULT_CHUNK_PAGES
        class ConversionCancelled(Exception)
        natural_key(name) -> list
        collect_images(folder: Path) -> list[Path]      # 仅顶层，自然排序
        subfolders_with_images(folder: Path) -> list[Path]
        convert_folder(src, out_pdf, **kw) -> Path
            kw: quality:int, dpi:tuple, chunk_pages:int,
                progress(done:int, total:int, name:str),
                should_cancel() -> bool
        # 注意：没有 convert_folder_batch —— 批量编排是**我的活**，见 _convert_batch。

    storage:
        class StorageError / PermissionDenied(StorageError) / UnsupportedUri(StorageError)
        is_android() -> bool
        has_all_files_access() -> bool
        request_all_files_access() -> bool        # True = 已跳转设置页，需 on_resume 复查
        list_images(target: str) -> list[Path]
        default_output_dir() -> Path
        unique_output_path(folder: Path, stem: str) -> Path
        clear_cache() -> None
        subfolders_with_images_for(target: str) -> list[Path]
        materialise(target: str) -> Path

============================================================================
线程模型（THREADING MODEL）—— 本文件最容易出 bug 的地方
============================================================================
Kivy 的 widget 树 **只能在主线程**改。`progress_bar.value = x` 或
`label.text = y` 从工作线程调用是真 bug（不是风格问题）：Kivy 的 Canvas
指令、`texture_update()`、`Clock` 事件派发都不是线程安全的，典型症状是
偶发崩溃或画面卡死不刷新。

规则（贯穿全文件，逐条自查过）：

1. **工作线程只做纯粹的 CPU/IO**：调用 `pdf_engine` / `storage`，
   以及 `threading.Thread`、`concurrent.futures`、`Event.is_set()`。
   工作线程**从不**触碰任何 widget 属性。

2. **所有 widget 变更通过 `self._post(fn, *args)` 回到主线程**执行，
   内部是 `Clock.schedule_once(cb, 0)`。这是本项目规定的唯一回主线程通道。

3. **批量模式只有一个协调线程**。`_convert_worker`（1 个 daemon 线程）
   内部再开 `ThreadPoolExecutor(max_workers=MAX_BATCH_WORKERS)` 并发跑子文件夹，
   复刻桌面版 `convert_folder_batch` + `TUIProgressGrid` 的行为，
   但整个线程池对 Kivy 主线程不可见 —— 主线程只看到「排队好的回调」。

4. **取消**走 `threading.Event`，由主线程的 Cancel 按钮 set，
   `should_cancel()` 在引擎自己的线程里读。`Event.is_set()` 是线程安全的，
   不需要额外加锁。

5. **拆卸保护**：
   - `self._torn_down`（threading.Event）在 `on_stop()` 里 set；
     `_post()` 和 `_run_on_main()` 两处都检查它，set 之后一律丢弃回调。
   - ETA 定时器（`Clock.schedule_interval`）在 **取消** 和 **on_stop** 时
     都用 `Clock.unschedule(...)` 摘掉，避免 widget 没了还在被 tick。
   - 拖动系统选择器会触发 Android `on_pause` —— 所以 `on_pause()`
     **故意不** 取消转换（否则用户挑个文件夹回来转换就被自己杀了）。

6. **plyer 的选择器也跑在工作线程**。plyer 文档明写：
   "these methods will return only after user interaction. Use threads or you
   will stop the mainloop"。在 Android 上更极端 —— 它立刻返回 `None`，
   真结果走 `on_selection=` 回调（在 pyjnius 的 Java 主线程上），
   所以 `on_selection` 内部同样用 `_post()` 回 Kivy 主线程。

============================================================================
设计系统（DESIGN SYSTEM）
============================================================================
没有 .kv、没有第三方 UI 库，所以设计 token 显式写在模块顶部，并且
**所有** 颜色 / 间距 / 字号 / 圆角都从 `C` / `SP` / `FS` / `R` / `H`
这五个表里取。文件里不允许出现裸的视觉魔法数字。

    C   颜色（rgba 元组，0~1）。深墨底 + 琥珀强调色，避开了
        「白底紫渐变」那套烂大街配色，也保证长时间看漫画截图不刺眼。
    SP  间距刻度，4px 基数：xs 4 / sm 8 / md 12 / lg 16 / xl 24 / xxl 32
    FS  字号刻度：caption 11 / label 13 / body 15 / title 18 / display 22
    R   圆角刻度：sm 8 / md 14 / lg 20 / pill 999
    H   组件高度：mini 6 / row 44 / control 48 / primary 56

组件原语（本文件自建的一套，全部走同一套 token）：
    _label()            文本，带 width→text_size 自动换行绑定
    _card()             圆角卡片背景（pos/size 跟随，自动重绘）
    _paint_round_rect() 通用圆角矩形绘制器，返回 repaint() 闭包
    _button()           primary / ghost / danger 三种按钮
    _style_meter()      把 ProgressBar 的默认外观盖掉，改用 C["track"]/C["accent"]

============================================================================
未在真机验证的部分（UNVERIFIED）
============================================================================
写这个文件的环境**没有显示器、也没有装 Kivy / plyer**（`import kivy`
和 `import plyer` 都失败），所以下面这些**只是按 API 文档编码，没有跑过**。
真机首跑请优先看这几条：

1. **整个文件从未被执行过。** 只验证了 `python3 -m py_compile main.py` 通过。
   没有实例化过任何 widget，没有跑过一次事件循环。

2. **中文字形（最可能出问题的一条）。** Kivy 内置默认字体（Roboto/DejaVu）
   **不含 CJK 字形**，不处理的话满屏「豆腐块」。`_resolve_font()` 会按
   `_FONT_CANDIDATES` 顺序探测真实字体文件，找不到就退回 Kivy 默认字体
   （= 豆腐块）。**强烈建议把一个 CJK 字体（如 NotoSansSC-Regular.otf）
   放到 `mobile/fonts/` 并写进 buildozer.spec 的 `source.include_exts`**。
   另外 `.ttc` 字体集合里 Kivy 只能取 face 0，通常是日文字形，
   汉字能显示但是日文字形变体（不算错字，看着有点怪）。

3. **`plyer.filechooser.choose_file()` 这个名字在现代 plyer 里不存在。**
   我读了 plyer master 的源码确认：`plyer.filechooser` 是一个
   `Proxy('filechooser', facades.FileChooser)`，而 `facades.FileChooser`
   只有 `open_file()` / `save_file()` / `choose_dir()` 三个方法；
   `plyer/filechooser.py` 这个文件在 master 上是 **404**。
   `choose_file()` 是 plyer 1.x 的旧模块级 API。
   → 因此代码里用 `getattr(filechooser, "choose_file", None) or
   getattr(filechooser, "open_file", None)` 做版本兼容，两个都拿不到时
   给出中文提示并引导用户用手输路径。

4. **Android 上「选文件夹」根本做不到。** `AndroidFileChooser`
   （`plyer/platforms/android/filechooser.py`）只实现了 `mode='open'`
   和 `mode='save'`；`choose_dir()` 传的 `mode='dir'` 落到
   `_file_selection_dialog` 里既不匹配 `'open'` 也不匹配 `'save'`，
   于是**静默什么都不做、不报错**。
   → 所以 Android 分支我只能拉起文件选择器，让用户任选一张图片，
   再用它的父目录当工作文件夹（`_normalize_target()`）。
   **手动路径 TextInput 不是「降级方案」，而是 Android 上的主路径之一。**

5. **plyer Android 选择器的返回形态。** `ACTION_GET_CONTENT` 是异步的，
   `_open_file()` 立刻返回 `self.selection`（初值 `None`）；真结果在
   `on_activity_result` 里通过 `on_selection=` 回调送出，且列表里
   **可能含 `None`**（Android 11+ scoped storage 拿不到 `_data` 列）。
   代码对 `None` / `[]` / `[None]` / `['']` 全部做了归一化，
   但**真机上到底返回 content:// 还是裸路径，没有验证过**，
   所以两种都交给 `storage.materialise()` 处理。

6. **plyer 的 `filters` 参数在两个平台语义不同。** Android 实现取
   `filters[0]` 去一张固定表里查**短 key**（`'image'` → `'image/*'`）；
   传 `[["Image", "*jpg"]]` 这种桌面通配符写法在 Android 上查不到 → 退化成 `*/*`。
   → 所以 `filters=["image"]` **只在 Android 分支**传，桌面分支不传
   （桌面会把它当文件名通配符）。我读的是源码逻辑，没在设备上试过。

7. **「打开所在文件夹」在 Android 上大概率打不开。** 用 jnius 发
   `ACTION_VIEW` + `file://` URI，在 API 24+ 会撞 StrictMode 的
   `FileUriExposedException`。代码用 try/except 包住，失败时显示中文提示
   并把完整路径留在屏幕上。**正解是用 FileProvider 发 `content://`
   URI，或干脆换成「分享」** —— 那是独立的一次改动，本次没做。

8. **`Spinner.option_cls = SpinnerOption`。** 换成自定义下拉项是 Kivy 文档
   里的做法，但样式是我自己画的，没在设备上看过。功能上即使画丑了也能用。

9. **进度条外观。** 没用 Kivy 的 `ProgressBar.background_color` /
   `foreground_color`（我对这两个属性存在没有 100% 把握），
   而是在 `canvas.after` 上盖一层自己画的圆角矩形。原理上 `canvas.after`
   一定画在 widget 默认指令之上，但**没在真机确认过**默认样式被完全盖住。

10. **输出目录写不进系统目录时会报错。** PDF 写到
    `storage.default_output_dir()`（不是源文件夹），因为 Android 上源目录
    未必可写（SAF 只给读权限）。如果连 `default_output_dir()` 都建不出来，
    会显示中文错误而不是静默失败。

11. **`Clock.schedule_once` 从工作线程调用。** 这是本项目指定的模式，
    也是 Kivy 社区的通行做法，但 Kivy **没有**对 Clock 的线程安全做文档承诺。
    唯一真正的「主线程消费者」是 `Clock.tick()`。请把这条当作已知风险。

12. **未使用的 storage API：** `list_images()` 和
    `subfolders_with_images_for()` 我都没用。我选择
    `materialise()` 一次 + `pdf_engine.collect_images()` /
    `subfolders_with_images()`，这样「预览看到的顺序」和
    「真正转换用的顺序」必然是同一份数据，不会出现预览与实际不一致。
    这两个 API 留给将来做「不落地、直接流式读取」时用。
"""

from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------------------
# 同级模块解析：pdf_engine / storage 与本文件平级
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from kivy.app import App                     # noqa: E402
from kivy.clock import Clock                 # noqa: E402
from kivy.core.window import Window           # noqa: E402
from kivy.graphics import Color, Line, RoundedRectangle   # noqa: E402
from kivy.logger import Logger               # noqa: E402
from kivy.metrics import dp, sp              # noqa: E402
from kivy.uix.boxlayout import BoxLayout      # noqa: E402
from kivy.uix.button import Button           # noqa: E402
from kivy.uix.label import Label             # noqa: E402
from kivy.uix.progressbar import ProgressBar  # noqa: E402
from kivy.uix.screenmanager import (          # noqa: E402
    NoTransition,
    Screen,
    ScreenManager,
)
from kivy.uix.scrollview import ScrollView    # noqa: E402
from kivy.uix.spinner import Spinner         # noqa: E402
from kivy.uix.switch import Switch            # noqa: E402
from kivy.uix.widget import Widget            # noqa: E402
from kivy.utils import platform as KIVY_PLATFORM   # noqa: E402

import pdf_engine                            # noqa: E402  (peer agent)
import storage                               # noqa: E402  (peer agent)


# ===========================================================================
# 设计 token —— 全文件唯一的视觉真值来源
# ===========================================================================

C: dict[str, tuple[float, float, float, float]] = {
    "bg":          (0.043, 0.047, 0.063, 1.0),   # #0B0C10 墨底
    "surface":     (0.075, 0.082, 0.106, 1.0),   # #13151B 卡片
    "surface_alt": (0.110, 0.120, 0.153, 1.0),   # #1C1F27 次级面（文件名列表底）
    "border":      (0.176, 0.192, 0.235, 1.0),   # #2D313C 分隔线
    "text":        (0.910, 0.925, 0.949, 1.0),   # #E8ECF2 主文字
    "text_dim":    (0.596, 0.631, 0.686, 1.0),   # #98A1AF 次要文字
    "accent":      (1.000, 0.702, 0.239, 1.0),   # #FFB33D 琥珀（主强调）
    "accent_ink":  (0.086, 0.067, 0.024, 1.0),   # 压在琥珀上的深色文字
    "ok":          (0.271, 0.788, 0.518, 1.0),   # 成功
    "warn":        (0.984, 0.749, 0.141, 1.0),   # 警告 / 取消
    "err":         (0.937, 0.325, 0.314, 1.0),   # 错误
    "track":       (0.141, 0.153, 0.192, 1.0),   # 进度条底槽
    "disabled":    (0.212, 0.224, 0.259, 1.0),   # 禁用态填充
}

SP: dict[str, float] = {          # 间距刻度，4px 基数
    "xs":  dp(4),
    "sm":  dp(8),
    "md":  dp(12),
    "lg":  dp(16),
    "xl":  dp(24),
    "xxl": dp(32),
}

FS: dict[str, float] = {          # 字号刻度
    "caption": sp(11),
    "label":   sp(13),
    "body":    sp(15),
    "title":   sp(18),
    "display": sp(22),
}

R: dict[str, float] = {           # 圆角刻度
    "sm":   dp(8),
    "md":   dp(14),
    "lg":   dp(20),
    "pill": dp(999),
}

H: dict[str, int] = {             # 组件高度（dp）
    "mini":    6,
    "row":     44,
    "control": 48,
    "primary": 56,
}


# ===========================================================================
# 可调配置
# ===========================================================================

# 上游 folder_to_pdf.py 的 PDF_COMPRESSION 5 档（1=Flate 无损 2=q95 3=q80
# 4=q65 5=q40）→ pdf_engine 的 JPEG DCTDecode quality。
#
# ⚠️ 第 1 档说明：桌面版的「Flate 无损」在 pdf_engine 的契约里**无法表达**
#    —— pdf_engine 只接受一个 JPEG quality 整数，没有 Flate/LZ 模式。
#    所以这里映射成 q100（最接近无损的 JPEG），并且**不编造体积倍数**
#    （Flate 的 4.63x 是针对无损 LZ 的实测值，对 JPEG q100 无意义）。
#    2~5 档的倍数是 AGENTS.md 里 IrfanView 插件的实测值，直接沿用。
QUALITY_LEVELS: list[tuple[int, int, str]] = [
    (1, 100, "第1档 · q100（最接近无损，体积最大）"),
    (2,  95, "第2档 · q95（体积约 1.14x，推荐）"),
    (3,  80, "第3档 · q80（体积约 0.89x）"),
    (4,  65, "第4档 · q65（体积约 0.79x）"),
    (5,  40, "第5档 · q40（体积约 0.44x，最小）"),
]
DEFAULT_LEVEL_INDEX = 1                       # = 上游默认的 q95

DPI: tuple[float, float] = (150.0, 150.0)     # 交给 pdf_engine 的 dpi kwarg
MAX_BATCH_WORKERS = 4                         # 手机上别学桌面的 16
PREVIEW_HEAD = 4                              # 预览列出前 N 个文件名
PREVIEW_TAIL = 4                              # 和后 N 个，证明自然排序

SCREEN_SOURCE = "source"
SCREEN_PROGRESS = "progress"
SCREEN_DONE = "done"

Log = Logger


# ===========================================================================
# 字体解析（中文必需，见头注释「未验证」第 2 条）
# ===========================================================================

# 相对路径按 mobile/ 解析，绝对路径直接用。第一个命中的生效。
_FONT_CANDIDATES: tuple[str, ...] = (
    "fonts/NotoSansSC-Regular.otf",              # 首选：随 app 打包
    "fonts/NotoSansSC-Regular.ttf",
    "fonts/DroidSansFallback.ttf",
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/NotoSansSC-Regular.ttf",
    "/system/fonts/NotoSansCJK-Regular.ttc",     # .ttc 只取 face 0（一般是日文）
    "/system/fonts/DroidSansFallback.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "C:/Windows/Fonts/msyh.ttc",                 # 桌面调试用
)

# 字体探测缓存：每个 widget 都会调 _apply_font()，不缓存会做几百次 stat()。
_FONT_CACHE: dict[str, str | None] = {}


def _resolve_font() -> str | None:
    """返回第一个真实存在的 CJK 字体文件路径；都没有则返回 None。

    结果缓存（每个 widget 都调一次，不缓存会做几百次 stat）。
    返回 None 时**不设置** font_name —— Kivy 会用默认字体，
    而默认字体没有中文字形（满屏豆腐块）。这属于已知限制，见头注释。
    """
    if "path" in _FONT_CACHE:
        return _FONT_CACHE["path"]

    for candidate in _FONT_CANDIDATES:
        path = Path(candidate) if os.path.isabs(candidate) else APP_DIR / candidate
        try:
            if path.is_file():
                _FONT_CACHE["path"] = str(path)
                Log.info("main: 使用字体 %s", path)
                return _FONT_CACHE["path"]
        except OSError as exc:            # 权限/坏符号链接等，不该中断启动
            Log.debug("main: 字体探测失败 %s: %s", path, exc)

    Log.warning(
        "main: 没找到任何中文字体，界面中文会显示成方块。"
        "请把 NotoSansSC-Regular.otf 放到 mobile/fonts/ 并写进 "
        "buildozer.spec 的 source.include_exts"
    )
    _FONT_CACHE["path"] = None
    return None


def _apply_font(widget: Widget) -> None:
    """给任意有 font_name 属性的 widget（Label/Button/Spinner）套上中文字体。"""
    name = _resolve_font()
    if name is None:
        return
    widget.font_name = name
    # 字体是构造之后才赋值的，显式重算一次纹理更稳（Label.texture_update
    # 对 font_name 的绑定在某些 Kivy 版本上不完整）。
    update = getattr(widget, "texture_update", None)
    if callable(update):
        update()


# ===========================================================================
# 组件原语（全部只吃 token，不接受裸视觉数字）
# ===========================================================================

def _relayout(parent: Widget | None) -> None:
    """BoxLayout 只监听子控件的 size_hint 变化，改 height 不一定触发重排。

    所以凡是折叠/展开控件高度 afterwards 都要显式踢一脚 do_layout()。
    """
    if parent is None:
        return
    layout = getattr(parent, "do_layout", None)
    if not callable(layout):
        return
    try:
        layout()
    except Exception:                      # noqa: BLE001 - 重排失败不该弄崩界面
        Log.exception("main: do_layout 失败")


def _set_visible(widget: Widget, visible: bool, natural_height: float) -> None:
    """在竖向 BoxLayout 里显示/隐藏控件（height=0 + opacity=0 + disabled）。"""
    widget.disabled = not visible
    widget.opacity = 1.0 if visible else 0.0
    widget.size_hint_y = None
    widget.height = natural_height if visible else 0
    _relayout(widget.parent)


def _paint_round_rect(
    widget: Widget,
    fill: tuple[float, float, float, float] | None,
    border_color: tuple[float, float, float, float] | None = None,
    radius: float | None = None,
    border_width: float = 1.0,
):
    """在 widget.canvas.before 上挂一个跟随 pos/size 的圆角矩形。

    返回 ``repaint(fill, border)`` 闭包，用来换色（禁用态、hover 等）。
    注意：绘制进的是 ``canvas.before``，所以会被 widget 自己的 kv 规则盖住
    —— 这正是我们要的效果（把 Button/ProgressBar 的默认外观压掉）。
    """
    rad = R["md"] if radius is None else radius
    with widget.canvas.before:
        fill_instr = Color(0.0, 0.0, 0.0, 0.0)
        fill_rect = RoundedRectangle(pos=widget.pos, size=widget.size,
                                     radius=[rad, rad, rad, rad])
        border_instr = Color(0.0, 0.0, 0.0, 0.0)
        border_line = Line(width=border_width,
                           rounded_rectangle=(widget.pos[0], widget.pos[1],
                                              widget.size[0], widget.size[1], rad))

    def repaint(new_fill=None, new_border=None) -> None:
        fill_instr.rgba = new_fill if new_fill is not None else (0.0, 0.0, 0.0, 0.0)
        border_instr.rgba = new_border if new_border is not None else (0.0, 0.0, 0.0, 0.0)

    def _sync(*_args) -> None:
        fill_rect.pos = widget.pos
        fill_rect.size = widget.size
        border_line.rounded_rectangle = (widget.pos[0], widget.pos[1],
                                         widget.size[0], widget.size[1], rad)

    widget.bind(pos=_sync, size=_sync)
    repaint(fill, border_color)
    return repaint


def _card(
    widget: Widget,
    fill: tuple[float, float, float, float] | None = None,
    radius: float | None = None,
    border: bool = True,
):
    """卡片容器：surface 底 + border 描边 + 内边距。"""
    _paint_round_rect(
        widget,
        fill=C["surface"] if fill is None else fill,
        border_color=C["border"] if border else None,
        radius=R["md"] if radius is None else radius,
    )
    return widget


def _wrap_text(label: Label) -> Label:
    """width -> text_size 自动换行。halign/valign 只有在 text_size 设定后才生效。"""

    def _on_width(_widget: Widget, value: float) -> None:
        _widget.text_size = (value, None)

    label.bind(width=_on_width)
    label.text_size = (label.width, None)
    return label


def _label(
    text: str = "",
    size: str = "body",
    color: tuple[float, float, float, float] | None = None,
    wrap: bool = True,
    **kwargs,
) -> Label:
    """统一文本原语：字号来自 FS，颜色来自 C，自动换行 + 中文字体。"""
    label = Label(
        text=text,
        font_size=FS[size],
        color=C["text"] if color is None else color,
        halign=kwargs.pop("halign", "left"),
        valign=kwargs.pop("valign", "top"),
        **kwargs,
    )
    _apply_font(label)
    if wrap:
        _wrap_text(label)
    return label


def _button(
    text: str,
    kind: str = "primary",
    height: int = H["control"],
    **kwargs,
):
    """三档按钮：primary（琥珀实心）/ ghost（描边）/ danger（红描边）。

    禁用 Kivy 默认 Button 外观的四张图 + background_color 置全 0，
    再用 _paint_round_rect 自己画 —— 这是 Kivy 里做自定义按钮的常规做法。
    """
    fills = {
        "primary": (C["accent"], None),
        "ghost": (None, C["border"]),
        "danger": (None, C["err"]),
    }
    if kind not in fills:
        raise ValueError(f"未知的按钮样式：{kind}")
    fill, border = fills[kind]

    button = Button(
        text=text,
        size_hint_y=None,
        height=dp(height),
        font_size=FS["body"],
        color=C["accent_ink"] if kind == "primary" else C["text"],
        # 去掉默认九宫格/图片背景
        background_normal="",
        background_down="",
        background_disabled_normal="",
        background_disabled_down="",
        background_color=(0.0, 0.0, 0.0, 0.0),
        halign="center",
        valign="middle",
        **kwargs,
    )
    _apply_font(button)
    _wrap_text(button)
    repaint = _paint_round_rect(button, fill=fill, border_color=border,
                                radius=R["md"])

    def _refresh(*_args) -> None:
        """禁用态换个更暗的颜色，让用户一眼看出不能按。"""
        if button.disabled:
            repaint(C["disabled"], C["border"])
        else:
            repaint(fill, border)

    button.bind(disabled=_refresh, state=_refresh)
    _refresh()
    return button


def _style_meter(bar: ProgressBar, fill: tuple[float, float, float, float]) -> None:
    """用 token 覆盖 ProgressBar 的默认外观。

    画在 ``canvas.after`` 上 —— 一定压在 widget 默认 kv 指令之上，
    所以 ProgressBar 长什么样都会被完全盖住（也顺手盖掉了它的 text，
    所以这里从来不设 bar.text，百分比用旁边的 Label 显示）。

    没用 ``ProgressBar.background_color`` / ``foreground_color``：
    对这两个属性我没有十足把握，而这个办法只依赖 Canvas 指令，行为确定。
    """
    height = dp(H["mini"])

    with bar.canvas.after:
        track_instr = Color(*C["track"])
        track_rect = RoundedRectangle(pos=bar.pos, size=bar.size,
                                      radius=[height, height, height, height])
        fill_instr = Color(*fill)
        fill_rect = RoundedRectangle(pos=bar.pos, size=(0.0, bar.size[1]),
                                     radius=[height, height, height, height])

    def _sync(*_args) -> None:
        track_rect.pos = bar.pos
        track_rect.size = bar.size
        # ProgressBar.max 固定 100，value/max 即填充比例；留 1px 视觉余量。
        ratio = 0.0
        try:
            if bar.max:
                ratio = max(0.0, min(1.0, bar.value / float(bar.max)))
        except (TypeError, ZeroDivisionError):
            ratio = 0.0
        width = max(0.0, (bar.size[0] - dp(2)) * ratio)
        fill_rect.pos = (bar.pos[0] + dp(1), bar.pos[1])
        fill_rect.size = (width, bar.size[1])

    bar.bind(pos=_sync, size=_sync, value=_sync, max=_sync)
    _sync()


def _human_size(num_bytes: int) -> str:
    """把字节数写成「1.2 MB」。用 1024 进制，和 Windows 资源管理器一致。"""
    size = float(max(0, int(num_bytes)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"          # 不可达，留给类型检查器看


def _ellipsize(text: str, limit: int = 40) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _running_on_android() -> bool:
    """优先问 storage，问不到（函数缺失/抛异常）就退回 Kivy 自己的判断。"""
    try:
        return bool(storage.is_android())
    except Exception:                     # noqa: BLE001 - peer 模块可能还没这个函数
        return KIVY_PLATFORM == "android"


def _chunk_pages() -> int:
    try:
        return int(pdf_engine.DEFAULT_CHUNK_PAGES)
    except (AttributeError, TypeError, ValueError):
        return 10


def _quality_for_level(level: int) -> int:
    """上游档位 → pdf_engine 的 JPEG quality。"""
    for level_value, quality, _label_text in QUALITY_LEVELS:
        if level_value == level:
            return quality
    return QUALITY_LEVELS[DEFAULT_LEVEL_INDEX][1]


def _open_folder_desktop(path: Path) -> None:
    """桌面调试用：xdg-open / open / os.startfile。"""
    import subprocess

    if sys.platform.startswith("win"):
        # os.startfile 只在 Windows 上存在，用 getattr 取，避免类型抑制注释。
        startfile = getattr(os, "startfile")
        startfile(str(path))
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, str(path)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _open_folder_android(path: Path) -> None:
    """Android：用 jnius 发 ACTION_VIEW 打开目录。

    ⚠️ 未验证：API 24+ 对 file:// URI 有 StrictMode FileUriExposedException，
    所以这条路径很可能抛异常并被上层转成中文提示。正解是 FileProvider
    发 content:// URI（属于独立改动，本次没做）。见头注释「未验证」第 7 条。
    """
    from jnius import autoclass           # noqa: PLC0415 - 只在 Android 上可用

    Intent = autoclass("android.content.Intent")
    Uri = autoclass("android.net.Uri")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")

    intent = Intent(Intent.ACTION_VIEW)
    intent.setDataAndType(Uri.parse("file://" + str(path)), "resource/folder")
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    PythonActivity.mActivity.startActivity(intent)


# ===========================================================================
# 自定义 widget
# ===========================================================================

class SpinnerOption(Button):
    """Spinner 下拉里的单项。文档里的标准做法；样式跟 _button 一致。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(H["control"]))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_disabled_normal", "")
        kwargs.setdefault("background_disabled_down", "")
        kwargs.setdefault("background_color", (0.0, 0.0, 0.0, 0.0))
        kwargs.setdefault("font_size", FS["body"])
        kwargs.setdefault("color", C["text"])
        super().__init__(**kwargs)
        _apply_font(self)
        _wrap_text(self)
        _paint_round_rect(self, fill=C["surface_alt"], border_color=C["border"],
                          radius=R["sm"])


class BatchRow(BoxLayout):
    """批量模式进度列表的一行 —— 手机上替代桌面版 TUIProgressGrid 的方格。

    桌面版用一个 emoji 方块表示 ⏳/✅/❌；手机上信息密度更高，所以改成
    「序号 + 文件夹名 + 状态词 + 细进度条」两行结构。
    状态用文字（等待中 / 处理中 / 完成 / 失败 / 已取消）而不是 emoji，
    因为 emoji 在部分 Android 字体下缺字形。

    **本类的所有 setter 只能在 Kivy 主线程调用。**
    """

    WAITING = "等待中"
    RUNNING = "处理中"
    DONE = "完成"
    FAILED = "失败"
    CANCELLED = "已取消"

    def __init__(self, index: int, name: str, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("size_hint_x", 1)
        kwargs.setdefault("height", dp(H["row"] + H["mini"] + SP["md"]))
        kwargs.setdefault("spacing", SP["xs"])
        kwargs.setdefault("padding", (0, SP["xs"], 0, SP["xs"]))
        super().__init__(**kwargs)

        self.folder_name = name
        head = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(FS["label"] + SP["sm"]))
        self.name_label = _label(
            text=f"{index + 1:02d} · {_ellipsize(name, 26)}",
            size="label", color=C["text"], wrap=False,
            halign="left", valign="middle", shorten=True, shorten_from="right",
        )
        self.state_label = _label(
            text=self.WAITING, size="caption", color=C["text_dim"], wrap=False,
            halign="right", valign="middle",
            size_hint_x=None, width=dp(72),
        )
        head.add_widget(self.name_label)
        head.add_widget(self.state_label)
        self.add_widget(head)

        self.bar = ProgressBar(max=100.0, value=0.0, size_hint_y=None,
                               height=dp(H["mini"]))
        _style_meter(self.bar, C["accent"])
        self.add_widget(self.bar)

        _card(self, fill=C["surface"], radius=R["sm"])

    # -- 以下方法全部假定已在主线程 ----------------------------------------

    def mark_running(self) -> None:
        self.state_label.text = self.RUNNING
        self.state_label.color = C["accent"]

    def mark_progress(self, done: int, total: int, current: str) -> None:
        self.bar.value = 100.0 * (float(done) / float(total)) if total else 0.0
        self.name_label.text = f"{_ellipsize(self.folder_name, 20)} · {_ellipsize(current, 14)}"

    def mark_done(self) -> None:
        self.bar.value = 100.0
        self.state_label.text = self.DONE
        self.state_label.color = C["ok"]

    def mark_failed(self, reason: str) -> None:
        self.state_label.text = self.FAILED
        self.state_label.color = C["err"]
        self.name_label.text = f"{_ellipsize(self.folder_name, 20)} · {_ellipsize(reason, 16)}"

    def mark_cancelled(self) -> None:
        self.state_label.text = self.CANCELLED
        self.state_label.color = C["warn"]


# ===========================================================================
# App
# ===========================================================================

class ImagesToPdfApp(App):
    """图片转 PDF —— Kivy 界面 + 线程编排。

    状态字段（非 Kivy property，因为全部在主线程读写，不需要绑定）：
        target     用户选中的原始目标，str：路径 或 content:// URI
        local      materialise() 之后的本地目录（转换真正用的目录）
        images     顶层图片列表（预览 + 单个模式的页数）
        subs       含图片的子文件夹列表（批量模式的任务表）
        quality_level  上游 1~5 档位号
        batch_mode    是否「每个子文件夹生成一个 PDF」
    """

    title = "图片转 PDF"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target: str | None = None
        self.local: Path | None = None
        self.images: list[Path] = []
        self.subs: list[Path] = []
        self.quality_level: int = QUALITY_LEVELS[DEFAULT_LEVEL_INDEX][0]
        self.batch_mode = False

        # --- 线程与生命周期 -------------------------------------------------
        self.cancel_event = threading.Event()
        self.torn_down = threading.Event()
        self._worker: threading.Thread | None = None
        self._eta_event = None
        self._picker_busy = False
        self._scan_serial = 0                 # 丢弃过期的扫描结果
        self._converted_pages = 0             # 用于 ETA
        self._started_at = 0.0
        self._last_output_dir: Path | None = None

        # --- 进度屏批量列表 -------------------------------------------------
        self.batch_rows: list[BatchRow] = []
        self._active_total = 0

        # --- 下面这些 widget 由 build() 填充 --------------------------------
        self.sm: ScreenManager
        self.path_label: Label
        self.path_input: object                 # TextInput（避免类型注解导入）
        self.source_msg: Label
        self.perm_card: BoxLayout
        self.perm_msg: Label
        self.quality_spinner: Spinner
        self.batch_switch: Switch
        self.batch_hint: Label
        self.preview_label: Label
        self.start_btn: Button
        self.prog_title: Label
        self.prog_bar: ProgressBar
        self.prog_status: Label
        self.prog_count: Label
        self.prog_eta: Label
        self.prog_msg: Label
        self.cancel_btn: Button
        self.batch_box: BoxLayout
        self.batch_scroll: ScrollView
        self.done_title: Label
        self.done_detail: Label
        self.done_error: Label
        self.open_folder_btn: Button

    # =======================================================================
    # 线程回调通道（整个文件唯一允许「从工作线程调用」的东西）
    # =======================================================================

    def _post(self, callback, *args, **kwargs) -> None:
        """把一个 widget 变更从工作线程 marshal 回 Kivy 主线程。

        Kivy 的 widget 只能在主线程改。从工作线程直接写 progress_bar.value
        或 label.text 是真 bug（Canvas / texture_update / Clock 派发都
        不是线程安全的），所以**所有** UI 更新都必须走这里。

        已拆卸（torn_down）时直接丢弃回调，不排队。
        """
        if self.torn_down.is_set():
            return
        Clock.schedule_once(
            lambda _dt: self._run_on_main(callback, *args, **kwargs), 0
        )

    def _run_on_main(self, callback, *args, **kwargs) -> None:
        """在主线程执行被 marshal 过来的回调；widget 可能已被拆掉，所以兜住异常。"""
        if self.torn_down.is_set():
            return
        try:
            callback(*args, **kwargs)
        except Exception:                     # noqa: BLE001 - UI 回调不该弄崩 app
            Log.exception("main: UI 回调 %r 失败",
                          getattr(callback, "__qualname__", callback))

    # =======================================================================
    # 生命周期
    # =======================================================================

    def build(self):
        _resolve_font()                        # 提前探测，日志里能第一时间看到
        Window.clearcolor = C["bg"]

        root = BoxLayout(orientation="vertical")
        self.sm = ScreenManager(transition=NoTransition())
        self.sm.add_widget(self._build_source_screen())
        self.sm.add_widget(self._build_progress_screen())
        self.sm.add_widget(self._build_done_screen())
        root.add_widget(self.sm)

        self._refresh_permission()            # 只在有 storage 的设备上才有意义
        return root

    def on_resume(self):
        """Android 从系统设置页/文件选择器回来。

        ``request_all_files_access()`` 是「跳设置页」，授权结果只能回来再查；
        文件选择器也会走一次 on_pause/on_resume，所以顺便复查权限横幅。
        """
        self._refresh_permission()

    def on_pause(self):
        """**故意什么都不做。**

        拉起 SAF 选择器 / 授权页都会触发 on_pause。如果在这里
        cancel_event.set()，用户挑完文件夹回来转换就被自己杀掉了。
        真要处理进程被杀，那是 Android 的事（进程都没了，存什么状态都白搭）。
        """
        Log.info("main: on_pause（转换继续，不主动取消）")

    def on_stop(self):
        """拆卸：取消转换、摘掉定时器、之后所有回主线程的回调全部丢弃。"""
        self.cancel_event.set()
        self.torn_down.set()
        self._stop_eta()
        Log.info("main: on_stop，已取消并停止 UI 回调")

    # =======================================================================
    # 界面搭建 —— 三块屏
    # =======================================================================

    def _build_source_screen(self) -> Screen:
        screen = Screen(name=SCREEN_SOURCE)
        scroll = ScrollView(do_scroll_x=False)
        column = BoxLayout(
            orientation="vertical", size_hint_y=None,
            padding=(SP["lg"], SP["lg"], SP["lg"], SP["xl"]),
            spacing=SP["md"],
        )
        column.bind(minimum_height=column.setter("height"))
        scroll.add_widget(column)

        # --- 标题 ----------------------------------------------------------
        column.add_widget(_label("图片转 PDF", size="display"))
        column.add_widget(_label(
            "选一个装满图片的文件夹，生成单个多页 PDF；"
            "如果里面有子文件夹，可以一个子文件夹出一个 PDF。",
            size="caption", color=C["text_dim"],
        ))

        # --- 权限横幅（仅 Android 且未授权时可见）--------------------------
        self.perm_card = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(H["row"] + 72),
            padding=SP["md"], spacing=SP["sm"],
        )
        self.perm_msg = _label(
            "没有「所有文件访问权限」，可能读不到你选的文件夹。",
            size="label", color=C["warn"],
        )
        perm_btn = _button("去授权", kind="ghost", height=H["row"])
        perm_btn.bind(on_release=self._on_request_permission)
        self.perm_card.add_widget(self.perm_msg)
        self.perm_card.add_widget(perm_btn)
        _card(self.perm_card, fill=C["surface"], border=True)
        _paint_round_rect(self.perm_card, fill=None, border_color=C["warn"],
                          radius=R["md"])
        column.add_widget(self.perm_card)

        # --- 1. 来源文件夹 --------------------------------------------------
        column.add_widget(_card(self._build_source_card(), radius=R["lg"]))

        # --- 3. 预览 -------------------------------------------------------
        column.add_widget(_card(self._build_preview_card(), radius=R["lg"]))

        # --- 2. 设置 -------------------------------------------------------
        column.add_widget(_card(self._build_settings_card(), radius=R["lg"]))

        # --- 出错 / 提示文字 ------------------------------------------------
        self.source_msg = _label("", size="label", color=C["warn"], wrap=True,
                                 size_hint_y=None, height=0)
        self.source_msg.bind(texture_size=self._grow_to_texture)
        column.add_widget(self.source_msg)

        screen.add_widget(scroll)

        # --- 底部固定操作栏 -------------------------------------------------
        footer = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(H["primary"] + SP["lg"]),
            padding=(SP["lg"], 0, SP["lg"], SP["lg"]),
        )
        self.start_btn = _button("开始转换", kind="primary", height=H["primary"],
                                size_hint_x=1)
        self.start_btn.bind(on_release=self._on_start)
        self.start_btn.disabled = True
        footer.add_widget(self.start_btn)
        screen.add_widget(footer)

        _set_visible(self.perm_card, False, dp(H["row"] + 72))
        return screen

    def _build_source_card(self) -> BoxLayout:
        """需求 1：已选路径显示 + 「选择文件夹」按钮 + 手动路径兜底。"""
        card = BoxLayout(
            orientation="vertical", size_hint_y=None,
            padding=SP["md"], spacing=SP["sm"],
        )
        card.bind(minimum_height=card.setter("height"))

        card.add_widget(_label("来源文件夹", size="label", color=C["text_dim"]))

        self.path_label = _label(
            "尚未选择", size="body", color=C["text"],
            size_hint_y=None, height=0,
        )
        self.path_label.bind(texture_size=self._grow_to_texture)
        card.add_widget(self.path_label)

        pick_btn = _button("选择文件夹", kind="primary", height=H["control"])
        pick_btn.bind(on_release=self._on_pick_folder)
        card.add_widget(pick_btn)

        card.add_widget(_label("手动输入路径（SAF 选不中文件夹时用这个）",
                               size="caption", color=C["text_dim"]))
        self.path_input = self._make_path_input()
        card.add_widget(self.path_input)

        use_btn = _button("用这个路径", kind="ghost", height=H["row"])
        use_btn.bind(on_release=self._on_use_manual_path)
        card.add_widget(use_btn)
        return card

    def _make_path_input(self):
        """单独抽出来只为加 try —— 具体的 TextInput 构造失败要有中文提示。"""
        from kivy.uix.textinput import TextInput

        field = TextInput(
            hint_text="/storage/emulated/0/DCIM/漫画",
            multiline=False,
            size_hint_y=None,
            height=dp(H["control"]),
            font_size=FS["label"],
            padding=[SP["sm"], SP["sm"], SP["sm"], SP["sm"]],
            background_color=C["surface_alt"],
            foreground_color=C["text"],
            cursor_color=C["accent"],
            hint_text_color=C["text_dim"],
            write_tab=False,
        )
        _apply_font(field)
        _paint_round_rect(field, fill=None, border_color=C["border"],
                          radius=R["sm"])
        return field

    def _build_preview_card(self) -> BoxLayout:
        """需求 3：图片数量 + 按自然排序的首尾文件名（证明 2 在 10 前面）。"""
        card = BoxLayout(
            orientation="vertical", size_hint_y=None,
            padding=SP["md"], spacing=SP["sm"],
        )
        card.bind(minimum_height=card.setter("height"))

        card.add_widget(_label("预览", size="label", color=C["text_dim"]))
        self.preview_label = _label(
            "选好文件夹之后，这里会显示图片数量和排序后的文件名。",
            size="caption", color=C["text_dim"], size_hint_y=None, height=0,
        )
        self.preview_label.bind(texture_size=self._grow_to_texture)
        card.add_widget(self.preview_label)
        return card

    def _build_settings_card(self) -> BoxLayout:
        """需求 2 + 6：压缩档位选择、chunk 提示、批量模式开关。"""
        card = BoxLayout(
            orientation="vertical", size_hint_y=None,
            padding=SP["md"], spacing=SP["sm"],
        )
        card.bind(minimum_height=card.setter("height"))

        card.add_widget(_label("压缩质量", size="label", color=C["text_dim"]))
        self.quality_spinner = Spinner(
            text=QUALITY_LEVELS[DEFAULT_LEVEL_INDEX][2],
            values=[item[2] for item in QUALITY_LEVELS],
            size_hint_y=None,
            height=dp(H["control"]),
            option_cls=SpinnerOption,
            font_size=FS["label"],
            color=C["text"],
            background_normal="",
            background_down="",
            background_disabled_normal="",
            background_disabled_down="",
            background_color=(0.0, 0.0, 0.0, 0.0),
            halign="left",
            valign="middle",
        )
        _apply_font(self.quality_spinner)
        _wrap_text(self.quality_spinner)
        _paint_round_rect(self.quality_spinner, fill=C["surface_alt"],
                          border_color=C["border"], radius=R["md"])
        self.quality_spinner.bind(on_text=self._on_quality_changed)
        card.add_widget(self.quality_spinner)

        # 体积倍数的解释：上游 2~5 档是 IrfanView 插件实测值
        card.add_widget(_label(
            "体积倍数是桌面版 IrfanView 的实测值；"
            "第1档在移动端是 q100（pdf_engine 没有无损 Flate 模式）。",
            size="caption", color=C["text_dim"],
        ))

        card.add_widget(_divider())
        card.add_widget(_label(
            f"分块写入：每 {_chunk_pages()} 页落一次盘，降低内存占用"
            "（大文件夹建议 10~20）。",
            size="caption", color=C["text_dim"],
        ))

        card.add_widget(_divider())

        # 需求 6：批量模式开关
        batch_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(H["control"]), spacing=SP["sm"])
        self.batch_switch = Switch(active=False, size_hint_x=None, width=dp(64))
        self.batch_switch.bind(active=self._on_batch_toggled)
        batch_row.add_widget(self.batch_switch)
        batch_row.add_widget(_label("每个子文件夹生成一个 PDF", size="label",
                                    valign="middle"))
        card.add_widget(batch_row)

        self.batch_hint = _label("选好文件夹之后才知道有没有子文件夹。",
                                 size="caption", color=C["text_dim"])
        card.add_widget(self.batch_hint)
        return card

    def _build_progress_screen(self) -> Screen:
        """需求 4 + 5 + 6：进度条 / 当前文件名 / 页数 / 取消 / 批量列表。"""
        screen = Screen(name=SCREEN_PROGRESS)
        column = BoxLayout(
            orientation="vertical", padding=(SP["lg"], SP["xl"], SP["lg"], SP["lg"]),
            spacing=SP["md"],
        )

        self.prog_title = _label("准备中…", size="title", color=C["text"])
        column.add_widget(self.prog_title)

        self.prog_bar = ProgressBar(max=100.0, value=0.0, size_hint_y=None,
                                    height=dp(H["mini"]))
        _style_meter(self.prog_bar, C["accent"])
        column.add_widget(self.prog_bar)

        self.prog_status = _label("正在准备…", size="body", color=C["accent"])
        column.add_widget(self.prog_status)

        count_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(FS["label"] + SP["sm"]))
        self.prog_count = _label("已处理 0 / 0 页", size="label",
                                 color=C["text_dim"], valign="middle")
        self.prog_eta = _label("", size="label", color=C["text_dim"],
                               valign="middle", halign="right")
        count_row.add_widget(self.prog_count)
        count_row.add_widget(self.prog_eta)
        column.add_widget(count_row)

        self.prog_msg = _label("", size="label", color=C["err"], wrap=True)
        self.prog_msg.bind(texture_size=self._grow_to_texture)
        column.add_widget(self.prog_msg)

        # 批量任务列表（替代桌面 TUIProgressGrid）
        self.batch_scroll = ScrollView(do_scroll_x=False)
        self.batch_box = BoxLayout(orientation="vertical", size_hint_y=None,
                                   spacing=SP["sm"])
        self.batch_box.bind(minimum_height=self.batch_box.setter("height"))
        self.batch_scroll.add_widget(self.batch_box)
        column.add_widget(self.batch_scroll)

        # 需求 5：取消按钮
        self.cancel_btn = _button("取消", kind="danger", height=H["primary"])
        self.cancel_btn.bind(on_release=self._on_cancel)
        self.cancel_btn.disabled = True
        column.add_widget(self.cancel_btn)

        screen.add_widget(column)
        _set_visible(self.batch_scroll, False, dp(200))
        return screen

    def _build_done_screen(self) -> Screen:
        """需求 7：输出路径 / 大小 / 打开所在文件夹。"""
        screen = Screen(name=SCREEN_DONE)
        column = BoxLayout(
            orientation="vertical", padding=(SP["lg"], SP["xl"], SP["lg"], SP["lg"]),
            spacing=SP["md"],
        )

        self.done_title = _label("完成", size="display", color=C["ok"])
        column.add_widget(self.done_title)

        detail_card = BoxLayout(
            orientation="vertical", size_hint_y=None,
            padding=SP["md"], spacing=SP["sm"],
        )
        detail_card.bind(minimum_height=detail_card.setter("height"))
        self.done_detail = _label("", size="label", color=C["text"],
                                  size_hint_y=None, height=0)
        self.done_detail.bind(texture_size=self._grow_to_texture)
        detail_card.add_widget(self.done_detail)
        _card(detail_card, radius=R["lg"])
        column.add_widget(detail_card)

        self.done_error = _label("", size="label", color=C["err"], wrap=True,
                                 size_hint_y=None, height=0)
        self.done_error.bind(texture_size=self._grow_to_texture)
        column.add_widget(self.done_error)

        spacer = Widget()
        column.add_widget(spacer)

        self.open_folder_btn = _button("打开所在文件夹", kind="ghost",
                                       height=H["control"])
        self.open_folder_btn.bind(on_release=self._on_open_folder)
        column.add_widget(self.open_folder_btn)

        clear_btn = _button("清理临时缓存", kind="ghost", height=H["row"])
        clear_btn.bind(on_release=self._on_clear_cache)
        column.add_widget(clear_btn)

        again_btn = _button("再转一个", kind="primary", height=H["primary"])
        again_btn.bind(on_release=self._on_back_to_source)
        column.add_widget(again_btn)

        screen.add_widget(column)
        return screen

    @staticmethod
    def _grow_to_texture(widget: Widget, value) -> None:
        """让自撑高度的 Label 跟着内容长（配合 size_hint_y=None 使用）。"""
        widget.height = value[1]

    # =======================================================================
    # 选择文件夹
    # =======================================================================

    def _on_pick_folder(self, *_args) -> None:
        """打开系统选择器。

        plyer 的调用跑在工作线程里，原因见文件头：plyer 文档要求用线程
        （否则阻塞 Kivy 主循环），Android 上则干脆立刻返回 None。
        """
        if self._picker_busy:
            self._set_source_message("选择器已经打开了，请先在系统界面里选一个文件夹。")
            return
        self._picker_busy = True
        threading.Thread(target=self._picker_worker, name="picker",
                         daemon=True).start()

    def _picker_worker(self) -> None:
        """**工作线程**：只负责调 plyer 和归一化结果，绝不碰 widget。"""
        outcome: dict = {}

        def on_selection(selection) -> None:
            """plyer 的回调。Android 上真结果走这里，而且是在 pyjnius 的
            Java 主线程上被调用的 —— 所以照样要 _post 回 Kivy 主线程。"""
            self._post(self._apply_selection, selection)

        try:
            try:
                from plyer import filechooser
            except ImportError as exc:
                outcome["error"] = (
                    "没装 plyer，打不开系统选择器。请在 buildozer.spec 的 "
                    f"requirements 里加上 plyer，或者直接手动输入路径。（{exc}）"
                )
                self._post(self._picker_finished, outcome)
                return

            if _running_on_android():
                # Android 分支。⚠️ 见文件头「未验证」第 4、6 条：
                #  - choose_dir() 在 Android 上是静默 no-op，选不了文件夹；
                #  - filters 必须是 plyer 的短 key（'image'），桌面通配符写法
                #    在 Android 上会退化成 */*。
                opener = (getattr(filechooser, "choose_file", None)
                          or getattr(filechooser, "open_file", None))
                if opener is None:
                    outcome["error"] = (
                        "当前 plyer 版本没有可用的文件选择器"
                        "（既没有 choose_file 也没有 open_file），"
                        "请手动输入路径。"
                    )
                else:
                    outcome["picked"] = opener(
                        on_selection=on_selection,
                        multiple=False,
                        filters=["image"],
                        title="选择图片文件夹（任选一张图片即可定位目录）",
                    )
            else:
                # 桌面分支：choose_dir 真的能选目录。不传 filters ——
                # 桌面后端会把 filters 当文件名通配符。
                opener = (getattr(filechooser, "choose_dir", None)
                          or getattr(filechooser, "open_file", None))
                if opener is None:
                    outcome["error"] = "当前 plyer 版本没有可用的目录选择器，请手动输入路径。"
                else:
                    outcome["picked"] = opener(on_selection=on_selection,
                                               title="选择图片文件夹")
        except Exception as exc:             # noqa: BLE001 - 平台代码，必须兜住
            Log.exception("main: plyer filechooser 失败")
            outcome["error"] = f"系统选择器出错：{exc}"

        self._post(self._picker_finished, outcome)

    def _picker_finished(self, outcome: dict) -> None:
        """**主线程**：收尾选择器。"""
        self._picker_busy = False
        error = outcome.get("error")
        if error:
            self._set_source_message(str(error))
            return

        # Android 上 open_file 立刻返回 None，真结果已经/将由 on_selection 送来。
        # 桌面上 open_file 阻塞到用户选完，返回列表，同时也会调 on_selection ——
        # 两条路都可能有，靠 _apply_selection 的去重标志兜住。
        picked = outcome.get("picked")
        if picked:
            self._apply_selection(picked)

    def _apply_selection(self, selection) -> None:
        """**主线程**：归一化 plyer 的返回，然后开始扫描。

        plyer 在各平台会返回 None / [] / [None] / [''] / 单个 str / list[str]，
        Android 的 content:// URI 解析失败时列表里会**含 None**。全都要处理。
        """
        if selection is None:
            # Android 的正常「还没结果」和桌面的「用户取消」都走这里。
            self._set_source_message("")
            return

        if isinstance(selection, (str, Path)):
            candidates = [selection]
        else:
            try:
                candidates = list(selection)
            except TypeError:
                self._set_source_message("选择器返回了无法识别的结果，请手动输入路径。")
                return

        cleaned = [str(item).strip() for item in candidates
                   if item is not None and str(item).strip()]
        if not cleaned:
            self._set_source_message(
                "没能从系统选择器拿到路径（Android 上很常见）。"
                "请把完整路径粘贴到上面的输入框，例如 "
                "/storage/emulated/0/DCIM/xxx"
            )
            return

        # 防重复：on_selection 和 pickered 的返回值可能送来同一个结果
        target = self._normalize_target(cleaned[0])
        if target is None:
            return
        if target == self.target:
            self._set_source_message("已经选过这个文件夹了。")
            return
        self.set_target(target)

    @staticmethod
    def _normalize_target(raw: str) -> str | None:
        """把选择器的原始返回整理成 pdf_engine/storage 能吃的 target。

        - ``content://…`` 原样保留，交给 storage.materialise() 解析。
        - ``file://…`` 剥掉协议头并 URL 解码。
        - 选到的是**文件**而不是目录（Android 上必然如此）→ 取父目录。
        """
        text = str(raw).strip().strip('"')
        if not text:
            return None

        if text.startswith("file://"):
            from urllib.parse import unquote, urlparse
            text = unquote(urlparse(text).path) or text[len("file://"):]

        if "://" in text:                    # content:// 等，storage 负责解析
            return text

        path = Path(text)
        try:
            if path.is_file():
                # Android 选不了文件夹，就拿这张图片的父目录当工作目录。
                return str(path.parent)
        except OSError:
            # 路径太长 / 权限不足 / 坏符号链接：当作目录交给后面报错。
            pass
        return text

    def _on_use_manual_path(self, *_args) -> None:
        """**主线程**：用输入框里的路径。"""
        try:
            text = str(self.path_input.text).strip()
        except AttributeError:
            self._set_source_message("输入框出错了，请重启应用。")
            return

        if not text:
            self._set_source_message("请先在输入框里填写文件夹的完整路径。")
            return

        target = self._normalize_target(text)
        if target is None:
            self._set_source_message("路径为空或格式不对。")
            return
        if target == self.target:
            self._set_source_message("已经选过这个文件夹了。")
            return
        self.set_target(target)

    def set_target(self, target: str) -> None:
        """**主线程**：记录目标并启动后台扫描。"""
        self.target = target
        self.local = None
        self.images = []
        self.subs = []
        self.batch_mode = False
        self.batch_switch.active = False

        self.path_label.text = _ellipsize(target, 160)
        self._set_source_message("正在扫描这个文件夹…")
        self._render_preview()

        self._scan_serial += 1
        serial = self._scan_serial
        threading.Thread(target=self._scan_worker, args=(target, serial),
                         name="scan", daemon=True).start()

    def _scan_worker(self, target: str, serial: int) -> None:
        """**工作线程**：materialise + 收集图片/子文件夹，不碰 widget。"""
        outcome: dict = {}
        try:
            local = Path(storage.materialise(target))
            if not local.is_dir():
                raise storage.StorageError(f"这个位置不是文件夹：{local}")
            images = pdf_engine.collect_images(local)
            subs = pdf_engine.subfolders_with_images(local)
            outcome = {"serial": serial, "local": local,
                       "images": images, "subs": subs}
        except storage.PermissionDenied as exc:
            # PermissionDenied 是 StorageError 的子类，必须先接
            outcome = {"serial": serial, "permission": True,
                       "error": f"没有权限读取这个位置：{exc}"}
        except ValueError as exc:
            # pdf_engine.collect_images 在没有图片时抛 ValueError ——
            # 这不是程序错误，单独给一句人话。
            outcome = {"serial": serial, "error": str(exc)}
        except storage.UnsupportedUri as exc:
            outcome = {"serial": serial, "error": f"这个位置不受支持：{exc}"}
        except Exception as exc:             # noqa: BLE001 - 扫描不能弄崩 app
            Log.exception("main: 扫描 %s 失败", target)
            outcome = {"serial": serial, "error": f"扫描失败：{exc}"}

        self._post(self._apply_scan, outcome)

    def _apply_scan(self, outcome: dict) -> None:
        """**主线程**：应用扫描结果（丢弃过期 serial 的结果）。"""
        if outcome.get("serial") != self._scan_serial:
            return                                  # 用户已经换了文件夹

        if outcome.get("error"):
            self.local = None
            self.images = []
            self.subs = []
            self.batch_mode = False
            self.batch_switch.active = False
            self._render_preview()
            self._set_start_enabled(False)
            message = str(outcome["error"])
            if outcome.get("permission"):
                message += "\n请点上面的「去授权」，在系统设置里打开"
                message += "「所有文件访问权限」，然后回到本应用。"
                self._show_permission(message)
            self._set_source_message(message)
            return

        self.local = outcome["local"]
        self.images = outcome["images"]
        self.subs = outcome["subs"]
        self._render_preview()
        self._set_start_enabled(bool(self.images) or bool(self.subs))
        self._set_source_message("")

    def _render_preview(self) -> None:
        """**主线程**：刷新预览卡片 + 批量开关的可用性。

        刻意只列前几个和后几个文件名 —— 一页塞 500 个名字没法看，但
        「前 4 个 + 后 4 个」正好能证明自然排序生效（第 2 话排在第 10 话前）。
        """
        if self.local is None:
            self.preview_label.text = "选好文件夹之后，这里会显示图片数量和排序后的文件名。"
            self.batch_hint.text = "选好文件夹之后才知道有没有子文件夹。"
            self.batch_switch.disabled = True
            return

        if not self.images and not self.subs:
            self.preview_label.text = (
                f"{self.local}\n顶层没有图片，也没有含图片的子文件夹。"
            )
            self.batch_hint.text = "没有可转换的内容。"
            self.batch_switch.disabled = True
            return

        self.batch_switch.disabled = not self.subs
        if self.subs:
            self.batch_hint.text = (
                f"检测到 {len(self.subs)} 个含图片的子文件夹，"
                f"批量模式会并发 {min(MAX_BATCH_WORKERS, len(self.subs))} 路转换。"
            )
        else:
            if self.batch_switch.active:
                self.batch_switch.active = False
            self.batch_hint.text = "没有含图片的子文件夹，将生成单个 PDF。"

        lines = [f"共 {len(self.images)} 张图片（只统计顶层，不含子文件夹）。", ""]
        names = [path.name for path in self.images]
        if not names:
            lines.append("（顶层没有图片）")
        elif len(names) <= PREVIEW_HEAD + PREVIEW_TAIL:
            lines.append("排序后的文件名：")
            for position, name in enumerate(names, start=1):
                lines.append(f"{position:>3}. {name}")
        else:
            lines.append(f"排序后的前 {PREVIEW_HEAD} 个：")
            for position, name in enumerate(names[:PREVIEW_HEAD], start=1):
                lines.append(f"{position:>3}. {name}")
            lines.append("   …")
            tail_start = len(names) - PREVIEW_TAIL
            for position, name in enumerate(names[tail_start:], start=tail_start + 1):
                lines.append(f"{position:>3}. {name}")
        lines.append("")
        lines.append("（自然排序：第 2 话排在第 10 话前面）")
        self.preview_label.text = "\n".join(lines)

    # =======================================================================
    # 设置
    # =======================================================================

    def _on_quality_changed(self, _spinner, text: str) -> None:
        """**主线程**：Spinner 选中项 → 上游档位号。"""
        try:
            index = list(self.quality_spinner.values).index(text)
        except ValueError:
            Log.warning("main: 未知压缩档位 %r，保持原设置", text)
            return
        self.quality_level = QUALITY_LEVELS[index][0]
        Log.info("main: 压缩档位 -> %s (quality=%s)",
                 self.quality_level, _quality_for_level(self.quality_level))

    def _on_batch_toggled(self, _switch, active: bool) -> None:
        """**主线程**：批量模式开关。没有子文件夹时强制关掉。"""
        if active and not self.subs:
            self.batch_switch.active = False
            self.batch_hint.text = "没有含图片的子文件夹，无法使用批量模式。"
            return
        self.batch_mode = bool(active)
        self.batch_hint.text = (
            f"批量模式：{len(self.subs)} 个子文件夹各出一个 PDF，"
            f"并发 {min(MAX_BATCH_WORKERS, len(self.subs))} 路。"
            if self.batch_mode
            else "单文件模式：这个文件夹的顶层图片合成一个 PDF。"
        )

    # =======================================================================
    # 权限
    # =======================================================================

    def _refresh_permission(self) -> None:
        """**主线程**：更新权限横幅。只有 Android 上才有意义。"""
        if not _running_on_android():
            _set_visible(self.perm_card, False, dp(H["row"] + 72))
            return
        try:
            granted = bool(storage.has_all_files_access())
        except Exception:                     # noqa: BLE001 - peer 函数可能不存在
            Log.exception("main: has_all_files_access 调用失败")
            granted = False
        if granted:
            _set_visible(self.perm_card, False, dp(H["row"] + 72))
        else:
            self.perm_msg.text = (
                "没有「所有文件访问权限」，可能读不到你选的文件夹。"
                "点下面的按钮去系统设置里打开。"
            )
            _set_visible(self.perm_card, True, dp(H["row"] + 72))

    def _show_permission(self, message: str) -> None:
        """**主线程**：强制显示权限横幅。"""
        self.perm_msg.text = message
        _set_visible(self.perm_card, True, dp(H["row"] + 72))

    def _on_request_permission(self, *_args) -> None:
        """**主线程**：跳系统设置页。真正的结果在 on_resume 里复查。"""
        if not _running_on_android():
            self._set_source_message("只有 Android 需要授权，桌面上直接选文件夹就行。")
            return
        try:
            launched = storage.request_all_files_access()
        except Exception as exc:              # noqa: BLE001
            Log.exception("main: 申请权限失败")
            self._set_source_message(f"申请权限失败：{exc}")
            return

        if not launched:
            self._set_source_message(
                "没能打开系统授权页面。你可以手动到：设置 → 应用 → 本应用 →"
                " 权限 → 文件和媒体 → 允许所有文件访问。"
            )
            return
        self._set_source_message("请在系统设置里打开「所有文件访问权限」，然后返回本应用。")

    # =======================================================================
    # 转换：主线程侧
    # =======================================================================

    def _set_source_message(self, message: str) -> None:
        self.source_msg.text = message
        _relayout(self.source_msg.parent)

    def _set_start_enabled(self, enabled: bool) -> None:
        self.start_btn.disabled = not enabled

    def _on_start(self, *_args) -> None:
        """**主线程**：切到进度屏并启动**唯一一个**工作线程。"""
        if self.local is None:
            self._set_source_message("请先选一个有图片的文件夹。")
            return
        if not self.images and not (self.batch_mode and self.subs):
            self._set_source_message("没有可转换的图片。")
            return
        if self._worker is not None and self._worker.is_alive():
            self._set_source_message("上一批还在处理中。")
            return

        self.cancel_event.clear()
        self._active_total = len(self.subs) if (self.batch_mode and self.subs) else 1
        self._converted_pages = 0
        self._reset_progress_screen()
        self.sm.current = SCREEN_PROGRESS

        self._worker = threading.Thread(target=self._convert_worker,
                                        name="pdf-worker", daemon=True)
        self._worker.start()

    def _reset_progress_screen(self) -> None:
        """**主线程**：清空进度屏并激活取消按钮。"""
        batch_mode = bool(self.batch_mode and self.subs)
        self.prog_title.text = ("批量转换中…" if batch_mode else "正在转换…")
        self.prog_bar.value = 0.0
        self.prog_status.text = "正在准备…"
        self.prog_count.text = "已处理 0 / 0 页"
        self.prog_eta.text = ""
        self.prog_msg.text = ""
        self._clear_batch_rows()
        _set_visible(self.batch_scroll, batch_mode, dp(200))
        self.cancel_btn.text = "取消"
        self.cancel_btn.disabled = False

        self._started_at = _monotonic()
        self._start_eta()

    def _on_cancel(self, *_args) -> None:
        """**主线程**：请求取消。只 set Event，真正的收尾在 worker 里。"""
        if self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.cancel_btn.text = "正在取消…"
        self.cancel_btn.disabled = True
        self.prog_status.text = "正在取消，等待当前页写完…"
        self._stop_eta()

    # =======================================================================
    # 转换：工作线程侧（**绝不碰 widget**）
    # =======================================================================

    def _convert_worker(self) -> None:
        """**工作线程（协调者）**。所有 pdf_engine 调用都在这里或其子线程。"""
        local = self.local
        if local is None:
            self._post(self._fail, "内部错误：没有可用的源文件夹。")
            return

        try:
            out_dir = Path(storage.default_output_dir())
            out_dir.mkdir(parents=True, exist_ok=True)
        except storage.PermissionDenied as exc:
            self._post(self._fail,
                       f"没有权限创建输出目录：{exc}\n"
                       "请在系统设置里给本应用「所有文件访问权限」。")
            return
        except Exception as exc:              # noqa: BLE001
            Log.exception("main: 准备输出目录失败")
            self._post(self._fail, f"无法准备输出目录：{exc}")
            return

        self._last_output_dir = out_dir
        quality = _quality_for_level(self.quality_level)
        use_batch = bool(self.batch_mode and self.subs)

        try:
            if use_batch:
                self._convert_batch(local, out_dir, quality)
            else:
                self._convert_single(local, out_dir, quality)
        except Exception as exc:              # noqa: BLE001 - 最后的兜底
            Log.exception("main: 转换流程异常")
            self._post(self._fail, f"转换过程中出错：{exc}")

    def _convert_single(self, local: Path, out_dir: Path, quality: int) -> None:
        """**工作线程**：顶层图片 → 一个 PDF。"""
        try:
            images = pdf_engine.collect_images(local)
        except Exception as exc:              # noqa: BLE001 - 扫描时可能已失效
            self._post(self._fail, f"无法读取源文件夹：{exc}")
            return

        self._post(self._apply_phase, local.name or "图片", len(images))

        try:
            out_pdf = storage.unique_output_path(out_dir, local.name or "images")
        except Exception as exc:              # noqa: BLE001
            self._post(self._fail, f"无法确定输出文件名：{exc}")
            return

        self._post(self._apply_status, f"正在生成 {out_pdf.name}")

        def progress(done: int, total: int, name: str) -> None:
            # 这个函数由 pdf_engine 在**它自己的**线程里调用 → 必须 marshal。
            self._post(self._apply_progress, int(done), int(total), str(name))

        try:
            result = pdf_engine.convert_folder(
                local, out_pdf,
                quality=quality,
                dpi=DPI,
                chunk_pages=_chunk_pages(),
                progress=progress,
                should_cancel=self.cancel_event.is_set,
            )
        except pdf_engine.ConversionCancelled:
            # 用户主动取消 —— 是正常流程，**不是**错误。
            Log.info("main: 用户取消了单文件转换")
            self._post(self._apply_cancelled, out_pdf)
            return
        except Exception as exc:              # noqa: BLE001
            Log.exception("main: convert_folder 失败")
            self._post(self._fail, f"转换失败：{exc}")
            return

        self._post(self._apply_single_done, Path(result), len(images))

    def _convert_batch(self, local: Path, out_dir: Path, quality: int) -> None:
        """**工作线程**：每个含图片的子文件夹 → 自己的 PDF，并发执行。

        pdf_engine 故意**没有** convert_folder_batch，所以批量的编排在这里 ——
        对应桌面版的 convert_folder_batch + TUIProgressGrid。
        线程池对 Kivy 主线程完全不可见：只有 _post 排出去的回调会碰到 widget。
        """
        subs = list(self.subs)
        if not subs:
            self._post(self._fail, "批量模式下没有可处理的子文件夹。")
            return

        self._post(self._apply_batch_rows, [sub.name for sub in subs])

        results: list[tuple[str, object]] = [("pending", None)] * len(subs)
        workers = max(1, min(MAX_BATCH_WORKERS, len(subs)))

        def convert_one(index: int, sub: Path) -> tuple[str, object]:
            """跑在线程池里的单个任务。**只返回数据，绝不碰 widget。**"""
            if self.cancel_event.is_set():
                return ("cancelled", None)
            try:
                out_pdf = storage.unique_output_path(out_dir, sub.name)
            except Exception as exc:          # noqa: BLE001
                Log.exception("main: 子文件夹 %s 无法确定输出名", sub)
                return ("error", f"无法确定输出文件名：{exc}")

            def progress(done: int, total: int, name: str) -> None:
                self._post(self._apply_row_progress, index,
                           int(done), int(total), str(name))

            try:
                path = pdf_engine.convert_folder(
                    sub, out_pdf,
                    quality=quality,
                    dpi=DPI,
                    chunk_pages=_chunk_pages(),
                    progress=progress,
                    should_cancel=self.cancel_event.is_set,
                )
            except pdf_engine.ConversionCancelled:
                return ("cancelled", None)
            except Exception as exc:          # noqa: BLE001
                Log.exception("main: 子文件夹 %s 转换失败", sub)
                return ("error", str(exc))
            return ("ok", Path(path))

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(convert_one, i, sub): i
                           for i, sub in enumerate(subs)}
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        status, payload = future.result()
                    except Exception as exc:  # noqa: BLE001 - convert_one 已兜底
                        Log.exception("main: 子任务 %d 抛出异常", index)
                        status, payload = "error", str(exc)
                    results[index] = (status, payload)
                    self._post(self._apply_row_done, index, status, payload)
        except Exception as exc:              # noqa: BLE001 - 线程池本身炸了
            Log.exception("main: 批量线程池异常")
            self._post(self._fail, f"批量转换失败：{exc}")
            return

        if self.cancel_event.is_set():
            self._post(self._apply_batch_cancelled, results, out_dir)
        else:
            self._post(self._apply_batch_done, results, out_dir)

    # =======================================================================
    # 转换：主线程侧的结果应用（全部由 _post 调进来）
    # =======================================================================

    def _apply_phase(self, title: str, total: int) -> None:
        self.prog_title.text = f"正在转换：{_ellipsize(title, 24)}"
        self.prog_count.text = f"共 {total} 页"

    def _apply_status(self, text: str) -> None:
        self.prog_status.text = text

    def _apply_progress(self, done: int, total: int, name: str) -> None:
        self.prog_bar.value = 100.0 * (float(done) / float(total)) if total else 0.0
        self.prog_status.text = f"正在处理 {_ellipsize(name, 30)}"
        self.prog_count.text = f"已处理 {done} / {total} 页"
        self._converted_pages = done

    def _apply_cancelled(self, out_pdf: Path) -> None:
        """用户主动取消单文件转换。"""
        self._stop_eta()
        self.prog_title.text = "已取消"
        self.prog_status.text = "转换已取消。"
        self.prog_bar.value = 0.0
        self._show_done(
            title="已取消",
            title_color=C["warn"],
            detail=(f"你在转换过程中点了取消。\n"
                    f"输出文件：{out_pdf}\n"
                    f"（如果这个文件之前就存在，可能是上次的旧文件，本次没动它。）"),
            error="",
            open_enabled=False,
        )

    def _fail(self, message: str) -> None:
        """**主线程**：任何失败都走这里，必须给用户看得懂的中文。"""
        self._stop_eta()
        self.cancel_btn.disabled = True
        self.prog_title.text = "出错了"
        self.prog_status.text = ""
        self.prog_msg.text = message
        self._show_done(
            title="转换失败",
            title_color=C["err"],
            detail="没能完成这次转换。",
            error=message,
            open_enabled=False,
        )

    def _apply_single_done(self, path: Path, pages: int) -> None:
        self._stop_eta()
        self.prog_bar.value = 100.0
        self.prog_title.text = "完成"
        self.prog_status.text = ""
        try:
            size = path.stat().st_size
            size_text = _human_size(size)
        except OSError as exc:
            Log.warning("main: 读不到产物大小：%s", exc)
            size_text = "未知"

        level = self.quality_level
        self._show_done(
            title="转换完成",
            title_color=C["ok"],
            detail=(f"输出文件：{path}\n"
                    f"所在目录：{path.parent}\n"
                    f"文件大小：{size_text}\n"
                    f"页数：{pages} 页\n"
                    f"压缩档位：第{level}档（quality={_quality_for_level(level)}）"),
            error="",
            open_enabled=True,
        )

    def _apply_batch_rows(self, names: list[str]) -> None:
        """**主线程**：建好批量进度行（对应 TUIProgressGrid 的格子）。"""
        self._clear_batch_rows()
        self.batch_rows = [BatchRow(index, name)
                           for index, name in enumerate(names)]
        for row in self.batch_rows:
            self.batch_box.add_widget(row)

    def _clear_batch_rows(self) -> None:
        for row in self.batch_rows:
            self.batch_box.remove_widget(row)
        self.batch_rows = []

    def _apply_row_progress(self, index: int, done: int, total: int, name: str) -> None:
        if not 0 <= index < len(self.batch_rows):
            return
        row = self.batch_rows[index]
        row.mark_running()
        row.mark_progress(done, total, name)

    def _apply_row_done(self, index: int, status: str, payload: object) -> None:
        if not 0 <= index < len(self.batch_rows):
            return
        row = self.batch_rows[index]
        finished = sum(1 for item in self.batch_rows if item.bar.value >= 100.0)
        if status == "ok":
            row.mark_done()
        elif status == "cancelled":
            row.mark_cancelled()
        else:
            row.mark_failed(str(payload))
        self.prog_bar.value = 100.0 * (len(self.batch_rows)
                                       and _ratio(finished, len(self.batch_rows)))
        self.prog_count.text = f"已完成 {finished} / {len(self.batch_rows)} 个子文件夹"

    def _apply_batch_done(self, results: list[tuple[str, object]], out_dir: Path) -> None:
        self._stop_eta()
        ok = [Path(item[1]) for item in results if item[0] == "ok"]
        errors = [str(item[1]) for item in results if item[0] == "error"]
        total_size = 0
        for path in ok:
            try:
                total_size += path.stat().st_size
            except OSError as exc:
                Log.warning("main: 读不到 %s 的大小：%s", path, exc)

        self.prog_bar.value = 100.0
        self.prog_title.text = "批量完成"
        self.prog_status.text = ""

        lines = [f"输出目录：{out_dir}",
                 f"成功：{len(ok)} 个　失败：{len(errors)} 个",
                 f"合计大小：{_human_size(total_size)}"]
        if ok:
            lines.append("")
            lines.append("已生成：")
            for path in ok:
                lines.append(f"· {_ellipsize(path.name, 34)}")
        error_text = ""
        if errors:
            error_text = "\n".join(f"· {_ellipsize(item, 90)}" for item in errors)

        self._show_done(
            title="批量转换完成" if not errors else "部分子文件夹失败",
            title_color=C["ok"] if not errors else C["warn"],
            detail="\n".join(lines),
            error=error_text,
            open_enabled=True,
        )

    def _apply_batch_cancelled(self, results: list[tuple[str, object]],
                               out_dir: Path) -> None:
        self._stop_eta()
        ok = sum(1 for item in results if item[0] == "ok")
        total = len(results)
        self.prog_title.text = "已取消"
        self.prog_bar.value = 0.0
        self._show_done(
            title="已取消",
            title_color=C["warn"],
            detail=(f"你在批量转换过程中点了取消。\n"
                    f"已完成 {ok} / {total} 个子文件夹，"
                    f"其余的已中止（已完成的 PDF 保留在输出目录里）。\n"
                    f"输出目录：{out_dir}"),
            error="",
            open_enabled=ok > 0,
        )

    def _show_done(self, title: str, title_color, detail: str, error: str,
                   open_enabled: bool) -> None:
        """**主线程**：统一填充完成屏。"""
        self.done_title.text = title
        self.done_title.color = title_color
        self.done_detail.text = detail
        self.done_error.text = error
        self.open_folder_btn.disabled = not open_enabled
        self.cancel_btn.disabled = True
        self.sm.current = SCREEN_DONE

    # =======================================================================
    # 完成屏
    # =======================================================================

    def _on_open_folder(self, *_args) -> None:
        out_dir = self._last_output_dir
        if out_dir is None:
            self.done_error.text = "还没有可打开的输出目录。"
            return

        def worker() -> None:
            """**工作线程**：拉起系统文件管理器。"""
            error = None
            try:
                if _running_on_android():
                    _open_folder_android(out_dir)
                else:
                    _open_folder_desktop(out_dir)
            except Exception as exc:          # noqa: BLE001 - 平台相关，必须兜住
                Log.exception("main: 打开目录失败")
                error = str(exc)
            self._post(self._apply_open_result, error)

        threading.Thread(target=worker, name="open-folder", daemon=True).start()

    def _apply_open_result(self, error: str | None) -> None:
        if error is None:
            return
        out_dir = self._last_output_dir
        self.done_error.text = (
            f"系统没能打开这个目录（{error}）。\n"
            f"请手动打开手机上的「文件管理」，路径是：{out_dir}"
        )

    def _on_clear_cache(self, *_args) -> None:
        """materialise() 落地的那份拷贝是可以随时删的。"""
        try:
            storage.clear_cache()
        except Exception as exc:              # noqa: BLE001
            self.done_error.text = f"清理缓存失败：{exc}"
            return
        self.done_error.text = "临时缓存已清理（已生成的 PDF 不受影响）。"
        self.done_error.color = C["ok"]

    def _on_back_to_source(self, *_args) -> None:
        self.sm.current = SCREEN_SOURCE

    # =======================================================================
    # ETA 定时器
    # =======================================================================

    def _start_eta(self) -> None:
        self._stop_eta()
        self._eta_event = Clock.schedule_interval(self._eta_tick, 0.5)

    def _stop_eta(self) -> None:
        """取消和 on_stop 都要摘掉定时器，否则 widget 没了还在被 tick。"""
        event = self._eta_event
        self._eta_event = None
        if event is None:
            return
        try:
            Clock.unschedule(event)
        except Exception:                     # noqa: BLE001 - 已经取消过也算成功
            Log.debug("main: ETA 定时器已经不在调度里了")

    def _eta_tick(self, _dt: float) -> None:
        """**主线程**（Clock 事件）。"""
        if self.torn_down.is_set():
            self._stop_eta()
            return
        elapsed = max(0.0, _monotonic() - self._started_at)
        if self.prog_count.text.startswith("已完成"):
            self.prog_eta.text = f"用时 {_format_duration(elapsed)}"
            return
        pages = self._converted_pages
        if pages <= 0:
            self.prog_eta.text = ""
            return
        remaining = elapsed / pages * max(0, self._active_total - pages)
        self.prog_eta.text = f"已用 {_format_duration(elapsed)}　剩余约 {_format_duration(remaining)}"


def _divider() -> Widget:
    """1px 分隔线。用固定高度的 Widget + 画一条线，避免嵌套 BoxLayout。"""
    line = Widget(size_hint_y=None, height=dp(1))
    _paint_round_rect(line, fill=C["border"], radius=dp(0.5))
    return line


def _ratio(done: int, total: int) -> float:
    return (float(done) / float(total)) if total else 0.0


def _monotonic() -> float:
    import time
    return time.monotonic()


def _format_duration(seconds: float) -> str:
    """秒 → 「1 分 05 秒」/「12 秒」。"""
    total = int(max(0.0, seconds))
    if total < 60:
        return f"{total} 秒"
    minutes, rest = divmod(total, 60)
    return f"{minutes} 分 {rest:02d} 秒"


def main() -> None:
    ImagesToPdfApp().run()


if __name__ == "__main__":
    main()
