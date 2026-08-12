#!/usr/bin/env bash
# SoftHertz Tool 一键入口（macOS / Linux）
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
FORCE_UPDATE=0
MODE="app"
MODE_SELECTED=0

usage() {
  cat <<'EOF'
用法:
  ./run.sh [--update] [app] [应用参数...]
  ./run.sh [--update] afdtr-sim [TX端口] [RX端口] [模拟器参数...]
  ./run.sh [--update] qs-sim <QS端口> [模拟器参数...]

模式:
  app         启动 SoftHertz Tool（默认）
  afdtr-sim   启动 AFDT1024/AFDR1024 双串口模拟器
  qs-sim      启动 AFD01_QS 串口模拟器

选项:
  --update, -u  更新依赖并重新注册 editable install
  --help, -h    显示本帮助

示例:
  ./run.sh
  ./run.sh app --smoke
  ./run.sh afdtr-sim /dev/ttys010 /dev/ttys011 --ids 1,2,3
  ./run.sh qs-sim /dev/ttys012 --baudrate 921600
EOF
}

while (($#)); do
  case "$1" in
    --update|-u)
      FORCE_UPDATE=1
      shift
      ;;
    app|afdtr-sim|qs-sim)
      if ((MODE_SELECTED)); then
        echo "✗ 只能选择一个运行模式" >&2
        exit 2
      fi
      MODE="$1"
      MODE_SELECTED=1
      shift
      ;;
    --help|-h)
      if ((MODE_SELECTED)); then
        break
      fi
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if [[ ! -f "$ROOT_DIR/pyproject.toml" || ! -f "$ROOT_DIR/src/soft_hertz_tool/__main__.py" ]]; then
  echo "✗ 当前目录不是完整的 SoftHertz Tool 仓库: $ROOT_DIR" >&2
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  SYSTEM_PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  SYSTEM_PYTHON=python
else
  echo "✗ 未找到 Python，请先安装 Python 3.9+" >&2
  exit 1
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "▶ 创建虚拟环境: $VENV_DIR"
  "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
  FORCE_UPDATE=1
fi

VENV_PYTHON="$VENV_DIR/bin/python"
STAMP="$VENV_DIR/.deps_installed"

run_python_module() {
  # 输入为模块名及其参数；成功时以 Python 进程替换当前脚本，不返回输出。
  local module="$1"
  shift
  exec "$VENV_PYTHON" -m "$module" "$@"
}

if ((FORCE_UPDATE)) || [[ ! -f "$STAMP" ]]; then
  echo "▶ 从仓库根目录安装依赖和入口..."
  "$VENV_PYTHON" -m pip install --upgrade pip
  "$VENV_PYTHON" -m pip install --editable "$ROOT_DIR"
  touch "$STAMP"
else
  # editable install 中含绝对源码路径；仓库移动或改名后必须重新注册。
  "$VENV_PYTHON" -m pip install --quiet --no-deps --editable "$ROOT_DIR"
fi

cd "$ROOT_DIR"
case "$MODE" in
  app)
    echo "▶ 启动 SoftHertz Tool..."
    run_python_module soft_hertz_tool "$@"
    ;;
  afdtr-sim)
    echo "▶ 启动 AFDT1024/AFDR1024 模拟器（Ctrl+C 退出）..."
    run_python_module soft_hertz_tool.devices.afdtr1024.simulator "$@"
    ;;
  qs-sim)
    echo "▶ 启动 AFD01_QS 模拟器（Ctrl+C 退出）..."
    run_python_module soft_hertz_tool.devices.afd01_qs.simulator "$@"
    ;;
esac
