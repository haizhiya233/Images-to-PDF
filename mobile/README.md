# Images-to-PDF · 移动版（Android APK）

把一个装满图片的文件夹合并成多页 PDF 的手机端实现。技术栈 **Kivy + Pillow +
Buildozer / python-for-android**，产物是普通 debug APK，侧载安装。

> 这是仓库根目录那个 **Windows 版**的独立移植版，不是它的打包产物。
> 两套代码互不依赖，详见文末[与 Windows 版的关系](#与-windows-版的关系)。

---

## 它是移植版：IrfanView 换成了 Pillow

**先说清楚这一点，免得有人拿两版的行为互相对照。**

Windows 版（`folder_to_pdf.py`）自己不写 PDF，它调用 **IrfanView 64 的
`/multipdf` 命令行**，由 IrfanView 的 PDF 插件出图。IrfanView 是 Windows 独占
的闭源软件，没有 Android 版本，也没有可用的命令行替代品 —— 所以移植到 Android
时**只能把 PDF 生成这一层整个换掉**，换成 Python 的 **Pillow**。

换掉之后有一个意外收获：**Windows 版跟 PDF 体积搏斗的那段历史，在移动版里
根本不存在。**

| | Windows 版（IrfanView） | 移动版（Pillow） |
|---|---|---|
| 压缩方式 | 插件默认 **Flate 无损**：JPEG 解成裸 RGB 再用 zlib 重压 → 网点/线条内容膨胀 **4~17 倍** | `PdfImagePlugin` 对 RGB/L/CMYK **直接发 `/DCTDecode`**，JPEG 原样嵌进 PDF |
| 输出体积 | 默认 4.63x，逆向 `PDF.dll` 换成 q95 后 1.14x | ≈ **1.0x**（源图字节基本原样搬过去） |
| 达成手段 | 反汇编出 `[PDF] ComprColor` 这组**未公开**的 INI 键，用同样未公开的 `/ini=` 参数强制注入 | `quality` 参数，开箱即用 |

也就是说：Windows 版为了让 158 MB 的 JPEG 不再产出 2.6 GB 的 PDF，不得不
逆向插件、写配置、再把配置路径塞进命令行；移动版这条路**天然就是通的**，
Pillow 默认就把 JPEG 当 JPEG 处理。

代价是引入了第三方依赖（Windows 版是纯标准库）。在 Android 上这点不重要 ——
p4a 本来就带 Pillow recipe，它已经打进 APK 里了。

---

## 中文字体（头号风险，装之前先看这节）

**Kivy 的默认字体 Roboto / DejaVu 不含任何 CJK 字形。** 不处理的话，整个中文界面
会显示成一片豆腐块（□）——界面等于不可用。这是本项目最容易踩且后果最严重的坑。

解决办法是随包分发一个中文字体：`fonts/DroidSansFallback.ttf`。

| 项 | 值 |
|---|---|
| 字体 | Droid Sans Fallback（Android 自己的 CJK 回退字体，源自 AOSP） |
| 许可 | **Apache-2.0**，Google。可合法随应用分发 |
| 体积 | 3.8 MB |
| 探测位置 | `main.py` 的 `_FONT_CANDIDATES` 第 3 项，`APP_DIR / "fonts/..."` |

`_resolve_font()` 按候选顺序探测，第一个存在的即用；都找不到就返回 `None`，
Kivy 回退到默认字体——**这时就是满屏豆腐块**，同时会打一条
`没找到任何中文字体，界面中文会显示成方块` 的警告日志。首次跑 APK 时
**务必看 logcat 里有没有这条警告**。

### 两个必须注意的坑

1. **`buildozer.spec` 的 `source.include_exts` 必须含 `ttf`**，否则字体不会被打进
   APK。当前值 `py,png,jpg,kv,atlas,json,ttf,otf,ttc` 已包含。

2. **别用 `.ttc` 字体集合。** Kivy 的 `Label` 不支持指定 collection 里的 face 索引，
   SDL_ttf 只会加载 face 0 —— 对NotoSansCJK 来说那通常是**日文字形**，汉字能显示但
   字形是日式变体，看着不对。所以这里选 `.ttf`（单一字重、简体中文）。

### 打包后字体路径为什么应该是可读的

这条没法在开发环境验证（没有 p4a），但有一条逻辑链：`main.py` 做了
`sys.path.insert(0, str(APP_DIR))` 然后 `import pdf_engine`。**如果 `APP_DIR`
不是一个真实可读的目录，App 连启动都做不到。** 而 p4a 是按同一套
`source.*` 规则把 `.py` 和字体一起铺到那个目录的，所以 `APP_DIR/fonts/` 可读。

即便如此，首次真机跑仍应确认字体真的加载了（看 logcat 有无上述警告）。

---

## 目录结构

```
mobile/
├── buildozer.spec      # Buildozer 构建配置（ABI、SDK、权限、依赖…）
├── icon.png            # 512×512 启动图标 / 桌面图标源图
├── main.py             # Kivy 界面入口
├── pdf_engine.py       # 基于 Pillow 的 PDF 生成引擎（分块转换防 OOM）
├── storage.py          # Android 存储层：SAF 授权、content:// 解析、输出目录
├── fonts/              # 打包进 APK 的 CJK 字体
├── test_pdf_engine.py  # pdf_engine 的单元测试
└── README.md           # 本文
```

`pdf_engine.py` **不 import 任何 Kivy / plyer / android 模块**，纯
stdlib + Pillow，在桌面 Linux 上也能直接跑和测。

---

## 本地构建（Linux / WSL）

### 前置

```bash
sudo apt-get install -y git zip openjdk-17-jdk python3-pip
pip install buildozer
```

- **JDK 17**：Gradle 打包需要。
- **`zip`**：p4a 重打包 AAR 时会用到，缺了会报 `zip: not found`。
- Android SDK / NDK / Gradle **不用手动装**，Buildozer 首次构建时自动下载
  （好几个 GB，所以第一次特别慢）。

### 构建

```bash
cd mobile                 # ⚠️ 必须在 mobile/ 里跑，buildozer.spec 在这儿
buildozer -v android debug
```

产物落在：

```
mobile/bin/<包名>-<版本>-<abi>-debug.apk
```

- 首次构建 **30~60 分钟**（下 SDK/NDK + 编译 Pillow/freetype/jpeg 等原生库），
  这是正常量级，不是卡住。
- 之后的增量构建快很多（只重编改动部分）。
- `-v` 是打开详细日志；CI 上 spec 里已经把 `log_level` 设成 2，本地建议也带 `-v`。

### 构建会生成的目录

| 路径 | 内容 |
|---|---|
| `mobile/.buildozer/` | 构建中间产物（编译缓存） |
| `mobile/bin/` | 最终 APK |
| `.buildozer_global/`（仓库根） | 下载好的 SDK / NDK / platform-tools |
| `mobile/__pycache__/` | Python 字节码 |

> ⚠️ 前三个**目前不在根 `.gitignore` 里**（根 `.gitignore` 只覆盖
> `.irfanview_ini/` 和 `__pycache__/`）。提交前请自己确认没有误加。

### 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `buildozer: command not found` | 没 `pip install buildozer`，或装在别的 Python 环境里 |
| 卡在 SDK licence 不动 | spec 里 `android.accept_sdk_license = True` 就是防这个的，确认没被删 |
| `zip: command not found` | `sudo apt-get install zip` |
| `No section 'app' in ...` | `buildozer.spec` 的 `[app]` 节丢了，或者在错误目录里跑了 |
| 想清理重来 | `buildozer clean`（或直接删 `mobile/.buildozer/` 和 `mobile/bin/`） |

---

## PDF 引擎：分块合并，以及为什么不能用 Pillow 的 `append=True`

手机只有几 GB RAM。一张 1988×3057 的 RGB 图解码后约 18.2 MB，一次性加载 200 页
= 3.6 GB = **必然 OOM**。所以 `pdf_engine.py` 分块转换：每 `chunk_pages`
（默认 10）张写成一个**独立合法**的 PDF，块数 > 1 时合并成最终文件。

合并用的是 **pypdf**（纯 Python、无 C 扩展，p4a 会自动 pip 安装，**不需要
recipe**）。块数 == 1 时直接把该块写入最终文件，不产生临时文件、不需要 pypdf。

> **为什么不用 Pillow 的 `append=True` 增量追加——这是实测结论，别改回去**
>
> 最初的实现就是「第一块 `save_all` 写入，后续块 `append=True` 追加」。
> 用 `pdfinfo` 实测 23 张图：
>
> | 块数 | 结果 |
> |---|---|
> | 1 / 2 / 3 / 4 | `valid, Pages=23` |
> | 5 | `PdfFormatError: trailer loop found` |
>
> 每次 append 都会重新解析既有 PDF 并重写 trailer，xref 的 `/Prev` 链不断累积，
> 约第 5 块时 Pillow 自己的 `PdfParser` 就绕死了。默认 `chunk_pages=10` 意味着
> **「超过 40 张图就崩」**——而真实用例是 200 页左右的漫画话数，必崩。

`test_pdf_engine.py` 里的 `TestManyChunksWithRealParser` 是**回归测试**，
专门盯这个缺陷：52 张图 / 6 块，用**独立的 pypdf 解析器**校验页数、页树数量
（必须恰好一棵`/Type /Pages`）、以及 Filter 必须是 `/DCTDecode` 而非 Flate。

> 校验器特意用 pypdf 而不是本测试文件里那个手写的 `/Prev` 链解析器——后者是围绕
> append 模式的增量结构写的，会把病态结构当成合法结果。正是它让这个缺陷两次绿灯。

### 顺带解决的历史问题

Windows 版跟 PDF 体积搏斗了很久：IrfanView 的 PDF 插件默认用 Flate/zlib 无损
压缩，把每张 JPEG 解码成原始 RGB 再重压，在漫画/网点内容上造成 **4x–17x** 的
膨胀——158 MB 的 JPEG 曾产出 2.6 GB 的 PDF。当时的解法是**逆向 `PDF.dll`**，
发现插件会读 INI 的 `[PDF] ComprColor/ComprGray/ComprBW` 键，于是用未公开的
`/ini=` CLI 参数强制它改用 JPEG q95（1.14x）。

**Pillow 的 PDF 写入器原生就是 DCTDecode（JPEG）**，不需要任何 INI 和逆向工程。
`quality` 参数直接对应那 5 个档位，那段历史就此终结。

---

## 用 GitHub Actions 构建（网页操作，不用配环境）

工作流文件是仓库根的 `.github/workflows/build-apk.yml`，**不依赖任何 secret**。

### 触发方式一：手动

1. 打开仓库 → 顶部 **Actions** 标签
2. 左侧列表选 **build-apk**
3. 右上角 **Run workflow** → **分支选 `mobile`** → 点绿色 **Run workflow**

> ⚠️ **分支要选 `mobile`，不是 `main`。** 工作流文件在 `main` 上（这样按钮才会出现），
> 但代码在 `mobile` 上。

> ⚠️ **为什么 workflow 必须先存在于默认分支**：GitHub 官方规则——`workflow_dispatch`
> 事件要求 workflow 文件在默认分支上，否则 Actions 页面根本不会列出它，
> 「Run workflow」按钮也不会出现。所以流程是：代码推 `mobile`（开发）→
> workflow 合入 `main`（能触发）→ 手动触发时分支选 `mobile`（跑 `mobile` 的代码）。

### 触发方式二：推一个 `v` 开头的 tag

```bash
git tag v0.1.0
git push origin v0.1.0
```

普通分支 push **不会**触发（工作流只监听 `v*` tag 和手动触发）。

### 下载产物

> 下载 artifact 需要登录 GitHub 账号，未登录的访客看不到它。

1. 仓库 → **Actions**
2. 点开那一条 **build-apk** 的运行记录（跑完是绿色 ✓，跑失败是红色 ✗）
3. 往下滚到 **Artifacts** 区块
4. 点 **Images-to-PDF-debug-apk** → 会下载一个 ZIP
5. 解压，里面就是 `xxx-debug.apk`

耗时：**首跑 45~60 分钟**（工作流的 `timeout-minutes` 也是 60，超时会主动掐掉），
可以边看日志边等。构建日志分组折叠，点开 `Build debug APK with Buildozer`
那一组能看 Buildozer 的完整输出。

---

## 安装到手机

1. **把 APK 弄到手机上**：数据线拷贝 / 微信文件传输 / 网盘，或者
   `adb install xxx-debug.apk`
2. **点开 APK，允许安装未知应用**：
   - Android 8.0+：弹窗里点 **设置** → 打开 **来自此来源**（针对给你安装的那个
     App，比如文件管理器或浏览器）→ 返回 → 再点 **安装**
   - Android 7.x：设置 → **安全** → 打开 **未知来源**
3. 装完打开即可。

**覆盖升级的坑**：CI 构建的是 **debug 签名** APK。同一套签名才能覆盖安装；
如果签名不一致（比如换了自己的机器构建、或 CI 签名变了），系统会提示
「应用未安装 / 签名冲突」—— 卸载旧版再装即可（应用数据会丢）。

---

## 权限

`buildozer.spec` 里**只申请一条**：

```
android.permissions = MANAGE_EXTERNAL_STORAGE
```

| 权限 | 申请？ | 理由 |
|---|---|---|
| `MANAGE_EXTERNAL_STORAGE`（所有文件访问） | ✅ | 见下方「为什么不是 0 条」 |
| `READ_EXTERNAL_STORAGE` | ❌ | 危险权限，得再弹一次运行时授权框，代码里没有这条路径；且 Android 13+ 已废，申请了也不生效 |
| `WRITE_EXTERNAL_STORAGE` | ❌ | PDF 写到应用私有目录（`storage.default_output_dir()`），API 19 起免权限 |
| `INTERNET` | ❌ | 纯本地工具，没有网络功能 |

### 为什么不是 0 条（SAF 不够吗？）

**理论上够，但本项目的代码路径没有走纯 SAF。** 具体链路是：

1. Android 上 plyer 的 `choose_dir()` 不可用，界面只能拉起
   `ACTION_GET_CONTENT` 让用户**选一张图片**，再拿它的父目录当工作文件夹；
2. plyer 的 `AndroidFileChooser._resolve_uri()` 对
   `com.android.externalstorage.documents` 这个 authority **不查
   ContentResolver**，而是直接把 document id 拼成**裸文件路径**返回
   （`primary:DCIM/Camera/a.jpg` → `/storage/emulated/0/DCIM/Camera/a.jpg`）；
3. 打开裸文件路径需要存储权限 —— SAF 给的那一次性 `content://` 授权在这里用不上；
4. 应用已经内置了对应流程：首页的权限横幅 +「去授权」按钮，调
   `storage.request_all_files_access()` 跳
   `ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION` 设置页，
   回到前台后用 `storage.has_all_files_access()` 复查。

**关键点**：那个「所有文件访问」设置页**只在 manifest 声明了
`MANAGE_EXTERNAL_STORAGE` 时才会出现**。不声明的话，`isExternalStorageManager()`
永远返回 false、横幅永远消不掉、按钮点了也没有可开的开关 —— 整条授权流程会死在
里面。所以这条权限是让现有代码能跑通的**最小集合**，不是顺手多要的。

**注意它是"特殊权限"**：安装时不会自动授予，必须用户自己进设置页打开
（App 已经做了这个引导）。另外 `MANAGE_EXTERNAL_STORAGE` 是 **Android 11+
（API 30）**才有意义的权限，Android 7~10 上系统不认识它。

### 如果要上 Google Play

`MANAGE_EXTERNAL_STORAGE` 属于 Play 重点审查的权限，需要申报核心功能理由，
而这个应用靠 SAF + 应用私有目录其实完全够用。**正确的精简路径**是：
把读取改成不落地、直接走 `ContentResolver`（即让 plyer 的裸路径回退失效），
然后把 `buildozer.spec` 里的 `android.permissions` 整行删掉 —— 那时
SAF 就真的 0 权限了。目前的侧载 debug APK 不受 Play 政策约束，先保持能用。

---

## ABI 权衡：为什么只编 `arm64-v8a`

```ini
android.archs = arm64-v8a
```

| | 只编 arm64-v8a | 编全部四个 ABI |
|---|---|---|
| 构建时间 | 1x | **≈ 4x**（每个 ABI 都要独立编译一遍原生库） |
| APK 体积 | 小 | 明显变大（四份 `.so`） |
| 覆盖机型 | 2017 年以后几乎**所有**在用的手机 | 多出 x86/x86_64（几乎只有模拟器）+ 老 armv7 |

对一个侧载自用的工具来说，砍掉三个 ABI 是性价比最高的一刀。

### 要跑 x86_64 模拟器怎么办

编辑 `mobile/buildozer.spec`：

```ini
android.archs = arm64-v8a, x86_64
```

然后重新构建即可（改完建议 `buildozer clean` 一次，避免复用上一次的 dist）。

- **别只留 `armeabi-v7a`/`arm64-v8a` 去跑 x86 模拟器** —— 能跑，但走的是
  ARM 翻译层，慢到没法用。
- 现代 Android 模拟器镜像默认就是 x86_64（或 arm64）。
- `android.arch`（单数）是旧写法，buildozer 会打弃用警告，请用复数的
  `android.archs`。

---

## 与 Windows 版的关系

- **Windows 版使用方法见仓库根目录的 [`README.md`](../README.md)** —— 拖文件夹、
  按 Enter、IrfanView `/multipdf`、`launcher.py` 便携模式等所有内容都在那边。
- **两版是完全独立的两套实现**，互不影响：

  | | 仓库根（Windows 版） | `mobile/`（移动版） |
  |---|---|---|
  | 平台 | Windows 10+ | Android 7.0+（minSdk 24） |
  | 入口 | `folder_to_pdf.py` / `launcher.py` | `main.py` |
  | 写 PDF | **IrfanView** 64 + PDF 插件 | **Pillow** |
  | 依赖 | **纯标准库** | Kivy / Pillow / plyer |
  | 界面 | 终端 TUI 进度网格 | Kivy GUI |

- 仓库根 `AGENTS.md` 里的「**禁止引入第三方依赖**」等约束**只针对 Windows 版**，
  `mobile/` 目录不受这条限制（否则 Kivy 根本装不上）。
- 你在 `mobile/` 里改动不会影响 Windows 版；反过来改 `folder_to_pdf.py`
  也不会碰到 Android 构建。

---

## 许可证

MIT —— 与仓库其余部分相同，见 [`../LICENSE`](../LICENSE)。
Kivy / Pillow / plyer 各自遵循其上游许可证。
