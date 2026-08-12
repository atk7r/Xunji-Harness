#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV_DIR="$ROOT_DIR/.venv"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  BOOTSTRAP_PYTHON=""
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'
    then
      BOOTSTRAP_PYTHON=$candidate
      break
    fi
  done
  if [ -z "$BOOTSTRAP_PYTHON" ]; then
    printf '%s\n' 'Xunji requires Python 3.10+ to create .venv' >&2
    exit 1
  fi
  "$BOOTSTRAP_PYTHON" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" "$ROOT_DIR/tools/check_project_env.py"
