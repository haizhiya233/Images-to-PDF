#!/system/bin/env bash
# 手机端一键启动（Termux）：装 ffmpeg → 起本地服务 → 用浏览器打开
# 用法：./start-mobile.sh [--open] [--port 8765] [--host 127.0.0.1]
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "未找到 ffmpeg，正在安装（仅第一次需要）…"
  pkg install -y ffmpeg
fi

# 息屏后仍要能继续转换：Termux 的 partial wakelock 必须挂着
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
fi

echo "服务启动后按 Ctrl+C 停止。"
exec python3 mobile_app.py "$@"
