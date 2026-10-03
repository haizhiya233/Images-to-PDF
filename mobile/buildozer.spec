# =============================================================================
# Images-to-PDF —— Android 构建配置（Buildozer / python-for-android）
#
# 格式提醒（这是 Buildozer 的 spec，不是普通 INI）：
#   * 必须有 [app] / [buildozer] 两节 —— buildozer 直接 config.get('app', key)，
#     没有 [app] 会 NoSectionError。见 kivy/buildozer 的 buildozer/default.spec。
#   * 键名大小写敏感（SpecParser.optionxform 原样返回，不做小写化）。
#   * 行内不能加 "# 注释" —— "#" 起的内容会算进值里。
#   * 顶格写，缩进会被当成多行字符串。
#   * 值里出现 % 会触发插值，只有 %(已定义的键)s 是合法写法。
# =============================================================================

[app]

# (str) 应用显示名（桌面图标下的名字、设置里显示的名字）
title = Images to PDF

# (str) Java 包名，最终 = package.domain + '.' + package.name，且整体转小写。
#       package.name 必须是合法 Java 标识符：不能有 "-"、"."、空格，不能以数字开头。
package.name = imagetopdf
package.domain = org.images2pdf

# (str) 源码根目录。本 spec 就放在 mobile/ 里，buildozer 也跑在 mobile/ 下
#       （CI 侧用 buildozer-action 的 workdir: mobile 指定），所以 "." = mobile/。
source.dir = .

# (list) 打进 APK 的源文件扩展名：
#   py    main.py / pdf_engine.py / storage.py
#   png   icon.png 及界面用图
#   jpg   测试素材
#   kv    Kivy 的 .kv 布局
#   atlas Kivy 图集
#   json  资源/配置数据
#   ttf/otf/ttc  fonts/ 下的 CJK 字体 —— main.py 的 _resolve_font() 会按
#         fonts/NotoSansSC-Regular.otf → fonts/DroidSansFallback.ttf 的顺序找，
#         打包时漏掉这些扩展名，真机上中文就全是豆腐块。
source.include_exts = py,png,jpg,kv,atlas,json,ttf,otf,ttc

# (list) 打包时排除的目录。
#   bin/        —— 产物目录，APK 落在这里
#   .buildozer/ —— 本地构建缓存（以 "." 开头的隐藏目录 buildozer 本来就会跳过，
#                  写出来主要是提醒自己别提交它）
source.exclude_dirs = bin,.buildozer

# (str) 版本号，写进 APK 的 versionName / versionCode。与 version.regex 互斥。
version = 0.1.0

# (list) 构建依赖，全部是 python-for-android 认识的名字：
#
#   python3  p4a 自带的 Python 3.14.2 recipe。
#   kivy     GUI 框架。
#   pillow   图片解码 + PDF 写出。p4a 有 Pillow 11.3.0 recipe，自动拉起
#            png / jpeg / freetype / harfbuzz 依赖，所以写小写 pillow 即可
#            （get_recipe() 按目录名大小写不敏感匹配到 Pillow/ 目录；
#             旧名 pil 仍在但会打弃用警告，pil 与 pillow 互斥）。
#            ⚠️ 不要写 img2pdf —— p4a 没有它的 recipe。
#   plyer   文件选择器。p4a **没有** plyer recipe，走的是 graph.py 里
#            "找不到 recipe 就假定能用 pip 装" 的分支，由 p4a pip 安装。
#            （kivy/plyer 自己的 examples/*/buildozer.spec 也是这么写的。）
#   android p4a 的 android 模块（activity / mActivity / onActivityResult 回调）。
#            plyer 的 AndroidFileChooser 第一行就是 `from android import ...`，
#            而 sdl2 bootstrap 的 recipe_depends 里**没有** android，
#            不显式写这一条 import 就会挂；它还会连带拉起 pyjnius。
#   pypdf    纯 Python（无 C 扩展）PDF 库。多块转换时用它把若干独立单块 PDF
#            合并成一个——Pillow 的 append=True 增量追加实测只能撑 4 块
#            （第 5 块抛 PdfFormatError: trailer loop found），而真实用例是
#            200 页左右的漫画话数。p4a 对无 C 扩展的包会自动 pip 安装，无需 recipe。
requirements = python3,kivy,pillow,plyer,android,pypdf

# (list) 屏幕方向。portrait = 竖屏（列表式 UI，竖屏更顺手）
orientation = portrait

# (bool) 是否去掉标题栏全屏
fullscreen = 0


# ---------------------------------------------------------------------------
# Android
# ---------------------------------------------------------------------------

# (list) Android 权限 —— 只申请一条：MANAGE_EXTERNAL_STORAGE（所有文件访问）。
#
# 【为什么 SAF 不够】
# 理论上"用户在系统选择器里挑一个文件夹"走 Storage Access Framework，
# 只要拿到 content:// Uri + 一次性读授权，**一条权限都不用声明**。
# 但本项目的实际代码不是这么走的：
#   * main.py 的注释写明 Android 上 plyer 的 choose_dir() 不可用，只能
#     ACTION_GET_CONTENT 让用户选一张图片，再拿它的父目录当工作文件夹；
#   * plyer 的 AndroidFileChooser._resolve_uri() 对
#     com.android.externalstorage.documents 这个 authority **不查 ContentResolver**，
#     而是直接把 document id 拼成裸文件路径返回（primary:DCIM/a.jpg →
#     /storage/emulated/0/DCIM/a.jpg）。也就是说最常见的路径是**裸路径**，
#     而不是 content://；
#   * 打开裸路径需要存储权限，SAF 的 Uri 授权在这里用不上；
#   * main.py 已经内置了对应流程：storage.has_all_files_access() /
#     storage.request_all_files_access() + 首页的「去授权」横幅，
#     跳的是 ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION 设置页。
#     这个设置页**只在 manifest 声明了 MANAGE_EXTERNAL_STORAGE 时才存在**，
#     不声明的话 isExternalStorageManager() 永远 false、横幅永远消不掉，
#     按钮点了也没有可开的开关 —— 整条授权流程会死在里面。
#
# 【为什么只申请这一条】
#   READ_EXTERNAL_STORAGE    不申请：危险权限，得再跑一次 requestPermissions()
#                            运行时弹窗，而代码里没有这条路径；而且它在
#                            Android 13+（targetSdk 34）上已废，申请了也不生效。
#   WRITE_EXTERNAL_STORAGE   不申请：PDF 写到 storage.default_output_dir()
#                            （应用私有目录 getExternalFilesDir），API 19 起免权限。
#   INTERNET                 不申请：纯本地工具，没有网络功能。
#
# 【代价 / 注意】
#   * MANAGE_EXTERNAL_STORAGE 是"特殊权限"，安装时不会自动授予，
#     必须用户自己进设置页打开（App 已经做了这个引导）；
#   * 上 Google Play 会被重点审查，需要申报核心功能理由 —— 本项目目前
#     只是侧载 debug APK，不受影响；真要上架，应该把读取改成纯 SAF
#     （把 plyer 返回的裸路径改成走 ContentResolver），然后删掉这一行。
android.permissions = MANAGE_EXTERNAL_STORAGE

# (int) targetSdkVersion。34 = Android 14。
#       ⚠️ 只影响侧载/测试；若将来要上 Google Play，targetSdk 下限已抬到
#       35（2025-08 起），届时需要同步抬高这一项。
android.api = 34

# (int) minSdkVersion。24 = Android 7.0：覆盖 2017 年之后几乎全部在用的机型，
#       也是 Kivy / p4a 常用基线；再低既没有用户量，还要多背一堆兼容分支。
#       （buildozer 会把它同时当作 --minsdk 和 --ndk-api。）
android.minapi = 24

# (bool) 自动接受 SDK licence —— CI 的命门。
#       不开的话 sdkmanager 会停下来等你在终端按 y，headless runner 上
#       没有 stdin，构建会一直挂到超时。这是这套工具链最常见的 CI 失败原因。
#       （buildozer-action 也会额外用 APP_ANDROID_ACCEPT_SDK_LICENSE=1 覆盖，
#        但本地 `buildozer -v android debug` 只有这一行能救你。）
android.accept_sdk_license = True

# (list) 只编 arm64-v8a。
#       四个 ABI 全编 ≈ 4 倍构建时间 + APK 体积明显变大；arm64 覆盖
#       2017 年之后几乎每台在用的手机，对一个侧载工具足够。
#       要跑 x86_64 模拟器时改成：
#           android.archs = arm64-v8a, x86_64
#       （旧的 android.arch 单数写法已弃用，buildozer 会打警告。）
android.archs = arm64-v8a

# (bool) 允许 Android 自动备份应用数据（API >= 23）。本应用没有敏感数据，开。
android.allow_backup = True

# (str) 启动用的 p4a bootstrap。sdl2 是 buildozer 的默认值，也是 Kivy 官方
#       主线路径；写死在这里免得 p4a 改默认值后行为突变。
p4a.bootstrap = sdl2

# (str) logcat 过滤规则，真机调试时 `adb logcat -s python:D` 能只看 Python 层
android.logcat_filters = *:S python:D


# ---------------------------------------------------------------------------
# 图标 / 启动图
# ---------------------------------------------------------------------------

# 两个都指向同一张 512x512 的 icon.png（路径相对本 spec 所在目录）。
#   icon       桌面图标源图，p4a 会据此生成各 dpi 的 mipmap
#   presplash  App 冷启动时全屏显示的图
# （暂时没有单独做启动图，先复用 icon；等有设计稿了把这行换掉即可。）
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/icon.png


[buildozer]

# (int) 日志级别：0=只报错 1=info 2=debug（带子进程输出）。
#       CI 上必须是 2，不然失败了也看不出卡在哪一步。
log_level = 2

# (bool) 以 root 运行时提示一次。GitHub Actions 的 Docker 容器里就是 root，
#       但 buildozer-action 会用 BUILDOZER_WARN_ON_ROOT=0 环境变量覆盖掉它
#       （buildozer 的环境变量优先级高于 spec），所以这里保留 1 不影响 CI。
warn_on_root = 1

# 目录默认值（不写就是这两个，写在这里备查）：
#   build_dir = ./.buildozer     →  mobile/.buildozer   构建中间产物
#   bin_dir   = ./bin            →  mobile/bin          **最终 APK 在这里**
# 注意 mobile/.buildozer、mobile/bin、仓库根的 .buildozer_global 目前都没有
# 被根 .gitignore 覆盖，提交前自己确认不要误加。
