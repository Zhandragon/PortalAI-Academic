#!/bin/sh
# Portable headless missions. No host Python, root privileges or installation.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PY="$ROOT/Runtime/LinuxPython/run-python"
if [ ! -x "$PY" ]; then
    printf '%s\n' 'Bundled Linux Python is missing or this drive is mounted noexec.' >&2
    exit 2
fi
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$PY" -B -I "$ROOT/Launchers/portalai_missions_linux.py" "$@"
