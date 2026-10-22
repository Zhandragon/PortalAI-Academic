#!/bin/sh
set -eu
MODULE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
umask 077
mkdir -p "$MODULE/state/tmp" "$MODULE/state/cache" "$MODULE/state/input" "$MODULE/Connections"
export TMPDIR="$MODULE/state/tmp" XDG_CACHE_HOME="$MODULE/state/cache"
export FONTCONFIG_FILE="$MODULE/Runtime/LinuxFonts/fonts.conf"
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
exec "$MODULE/Runtime/LinuxPython/run-python" -B -I "$MODULE/app/projection_boot.py"
