#!/bin/sh
# Linux entry to the same PortalAI GUI; everything except OS/driver services is on this drive.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NATIVE="$ROOT/Runtime/LinuxSystem/rootfs"
PY="$ROOT/Runtime/LinuxPython/run-python"
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export FONTCONFIG_PATH="$NATIVE/etc/fonts"
exec "$PY" -B -I "$ROOT/Launchers/portalai_gui_linux.py" "$@"
