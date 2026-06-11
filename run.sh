#!/usr/bin/env bash
# 一键运行 SoftHertz_AFDTR_Tool 上位机（macOS / Linux）
# 自动创建虚拟环境、安装依赖并启动 GUI
#
# 用法:
#   ./run.sh            启动上位机
#   ./run.sh --update   强制重新安装依赖后启动
#   ./run.sh --sim      启动设备模拟器（无硬件联调用）
#   ./run.sh --help     查看帮助
set -euo pipefail

# 仓库根目录 = 脚本所在目录
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$ROOT_DIR/KauDC004A_TestTool/code"
REQ_FILE="$ROOT_DIR/KauDC004A_TestTool/requirements.txt"
VENV_DIR="$ROOT_DIR/.venv"

# 解析参数
FORCE_UPDATE=0
RUN_SIM=0
for arg in "$@"; do
  case "$arg" in
    --update|-u) FORCE_UPDATE=1 ;;
    --sim)       RUN_SIM=1 ;;
    -h|--help)
      echo "用法: ./run.sh [--update] [--sim]"
      echo "  --update, -u  强制重新安装依赖"
      echo "  --sim         启动设备模拟器（device_simulator.py）"
      exit 0 ;;
    *) echo "✗ 未知参数: $arg（用 --help 查看用法）" >&2; exit 1 ;;
  esac
done

# 确认在正确的分支 / 目录（dev_kaudc004a）
if [ ! -f "$CODE_DIR/main_qt6.py" ]; then
  echo "✗ 找不到 $CODE_DIR/main_qt6.py" >&2
  echo "  本脚本针对 dev_kaudc004a 分支，请确认已切换：git checkout dev_kaudc004a" >&2
  exit 1
fi

# 选择 Python 解释器
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "✗ 未找到 Python，请先安装 Python 3.9+" >&2
  exit 1
fi

# 创建虚拟环境（首次）
if [ ! -d "$VENV_DIR" ]; then
  echo "▶ 创建虚拟环境: $VENV_DIR"
  "$PY" -m venv "$VENV_DIR"
  FORCE_UPDATE=1
fi

# 激活虚拟环境
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# 安装依赖（首次或 --update）
STAMP="$VENV_DIR/.deps_installed"
if [ "$FORCE_UPDATE" = "1" ] || [ ! -f "$STAMP" ]; then
  echo "▶ 安装依赖（$REQ_FILE）..."
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -r "$REQ_FILE"
  touch "$STAMP"
fi

# 启动
cd "$CODE_DIR"
if [ "$RUN_SIM" = "1" ]; then
  echo "▶ 启动设备模拟器（Ctrl+C 退出）..."
  exec python device_simulator.py
else
  echo "▶ 启动上位机 SoftHertz_AFDTR_Tool..."
  exec python main_qt6.py
fi
