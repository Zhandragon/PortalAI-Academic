#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /bin/sh "$HERE/../PortalAI-Projection/Runtime/mac-python.sh" "$HERE/Setup Files/setup_macos.py" "$@"
