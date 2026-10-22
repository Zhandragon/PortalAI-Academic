#!/bin/sh
# Linux model server entry point. No host Python, installation, or fixed mount path.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PY="$ROOT/Runtime/LinuxPython/run-python"
if [ ! -x "$PY" ]; then
    printf '%s\n' 'Portable Linux Python is not installed. See Documentation/Portable_Foundation.txt.' >&2
    exit 2
fi
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV
exec "$PY" "$ROOT/Launchers/portalai_linux.py" "$@"
