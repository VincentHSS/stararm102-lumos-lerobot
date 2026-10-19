#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_DIR="$PROJECT_DIR/.dependencies/startouch_sdk"
SDK_URL="https://github.com/lumos-open/startouch_sdk.git"
PYTHON_BIN="${PYTHON_BIN:-python}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "找不到 Python 命令：$PYTHON_BIN。请先激活 Python 3.10 环境，或设置 PYTHON_BIN。" >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "缺少 git。请先安装 git。" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"需要 Python 3.10 或更高版本，当前为 {sys.version.split()[0]}。请先激活 Python 3.10 环境。")
print(f"使用 Python {sys.version.split()[0]}: {sys.executable}")
PY

if [[ ! -r /etc/os-release ]]; then
  echo "此安装脚本仅支持 Ubuntu/Debian。" >&2
  exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" ]]; then
  echo "检测到 ${PRETTY_NAME:-未知系统}；此安装脚本仅支持 Ubuntu/Debian。" >&2
  exit 1
fi

if [[ ! -d "$SDK_DIR/.git" ]]; then
  if [[ -e "$SDK_DIR" ]]; then
    echo "$SDK_DIR 已存在但不是 Git 仓库。请先检查该目录，避免覆盖本地文件。" >&2
    exit 1
  fi
  mkdir -p "$(dirname -- "$SDK_DIR")"
  echo "正在从 Lumos 官方仓库下载 StarTouch SDK 到 $SDK_DIR"
  git clone --depth 1 "$SDK_URL" "$SDK_DIR"
else
  echo "使用已下载的 SDK：$SDK_DIR"
fi

if [[ ! -f "$SDK_DIR/src/config/robot_kinematics.yaml" ]]; then
  echo "SDK 缺少配置：$SDK_DIR/src/config/robot_kinematics.yaml。请检查 SDK 下载是否完整。" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  build-essential \
  cmake \
  pkg-config \
  libeigen3-dev \
  libyaml-cpp-dev \
  liborocos-kdl-dev \
  libtinyxml2-dev \
  pybind11-dev

"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
"$PYTHON_BIN" -m pip install pyserial fashionstar-uart-sdk
"$PYTHON_BIN" -m pip install -r "$SDK_DIR/requirements.txt"
"$PYTHON_BIN" -m pip install "$SDK_DIR"

"$PYTHON_BIN" -c "import serial, fashionstar_uart_sdk; from startouchclass import SingleArm; print('StarArm 与 Lumos SDK 安装成功')"
echo "安装完成。遥操作脚本：$PROJECT_DIR/stararm102_lumos_teleop.py"
echo "Lumos SDK 源码：$SDK_DIR"
echo "Lumos 运行配置：$SDK_DIR/src/config/robot_kinematics.yaml（请保留 SDK 源码目录）"
