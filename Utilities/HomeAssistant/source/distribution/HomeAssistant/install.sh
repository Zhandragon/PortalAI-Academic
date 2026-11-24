#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.9+ is required. Use the Windows installer against a writable HA config share, or the manual copy steps in README_FIRST.txt.' >&2
  exit 1
fi
if [ "$#" -eq 0 ]; then
  exec python3 -B -I install.py wizard
fi
exec python3 -B -I install.py "$@"
