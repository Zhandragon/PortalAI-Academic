#!/bin/sh
set -eu
MODULE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /bin/sh "$MODULE/Runtime/mac-python.sh" "$MODULE/app/recovery_ui.py"
