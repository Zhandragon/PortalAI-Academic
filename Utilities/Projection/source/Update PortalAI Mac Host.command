#!/bin/sh
set -eu
MODULE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" = 0 ]; then
  printf 'PortalAI Mac installation folder: '
  IFS= read -r TARGET
  exec /bin/sh "$MODULE/Runtime/mac-python.sh" "$MODULE/Tools/update_mac_host.py" --root "$TARGET" --apply
fi
exec /bin/sh "$MODULE/Runtime/mac-python.sh" "$MODULE/Tools/update_mac_host.py" "$@"
