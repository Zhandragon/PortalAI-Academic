#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON="$HERE/../PortalAI-Projection/Runtime/LinuxPython/run-python"
if [ "$#" -eq 0 ]; then
    exec "$PYTHON" -B -I "$HERE/Setup Files/HomeAssistant/install.py" wizard
fi
exec "$PYTHON" -B -I "$HERE/Setup Files/HomeAssistant/install.py" "$@"
