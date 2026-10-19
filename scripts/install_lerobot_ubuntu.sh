#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
LEROBOT_COMMIT="3991580a5673f5f0219a4e8835a5f973eeccf9a7"
LEROBOT_DIR="$PROJECT_DIR/.dependencies/lerobot"
SDK_COMMIT="040412542c0b6b6fd2bb6dd652c0de6c666631be"
SDK_DIR="$PROJECT_DIR/.dependencies/startouch_sdk"

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info[:2] != (3, 12):
    raise SystemExit("Use an activated Python 3.12 environment for this integration baseline")
print("Python:", sys.executable)
PY

# Pin the reviewed SDK before the original installer rebuilds it.
mkdir -p "$PROJECT_DIR/.dependencies"
if [[ ! -e "$SDK_DIR" ]]; then
  git clone https://github.com/lumos-open/startouch_sdk.git "$SDK_DIR"
  git -C "$SDK_DIR" checkout --detach "$SDK_COMMIT"
elif [[ "$(git -C "$SDK_DIR" rev-parse HEAD)" != "$SDK_COMMIT" ]]; then
  echo "Existing $SDK_DIR differs from reviewed SDK $SDK_COMMIT. No checkout/reset performed." >&2
  exit 1
fi

# Includes OS dependencies and rebuilds the Lumos SDK in the active environment.
PYTHON_BIN="$PYTHON_BIN" bash "$PROJECT_DIR/scripts/install_ubuntu.sh"

if [[ ! -e "$LEROBOT_DIR" ]]; then
  git clone https://github.com/huggingface/lerobot.git "$LEROBOT_DIR"
  git -C "$LEROBOT_DIR" checkout --detach "$LEROBOT_COMMIT"
else
  actual_commit="$(git -C "$LEROBOT_DIR" rev-parse HEAD)"
  if [[ "$actual_commit" != "$LEROBOT_COMMIT" ]]; then
    echo "Existing $LEROBOT_DIR is at $actual_commit; expected $LEROBOT_COMMIT. No checkout/reset performed." >&2
    exit 1
  fi
fi

"$PYTHON_BIN" -m pip install -e "$LEROBOT_DIR[core_scripts]"
"$PYTHON_BIN" -m pip install -e "$PROJECT_DIR"

# Make recording save the target actually sent after follower safety limits.
"$PYTHON_BIN" "$PROJECT_DIR/tools/patch_record.py" \
  "$LEROBOT_DIR/src/lerobot/scripts/lerobot_record.py"

if [[ ! -e "$PROJECT_DIR/configs/local.json" ]]; then
  cp -- "$PROJECT_DIR/configs/example.json" "$PROJECT_DIR/configs/local.json"
fi

"$PYTHON_BIN" -m pip check
echo "Installed. Edit configs/local.json, then run: lumos-lerobot calibrate --config configs/local.json"
echo "No robot connection or motion was performed by this installation script."
