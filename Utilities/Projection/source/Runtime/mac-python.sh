#!/bin/sh
# Self-contained native runtime; no host Python, Homebrew, compiler or sudo.
set -eu
MODULE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(uname -s)" != Darwin ] || [ "$(id -u)" = 0 ]; then
  echo 'Run this launcher on a Mac as your regular user (without sudo).' >&2; exit 2
fi
case "$(sw_vers -productVersion)" in
  10.*|11.*|12.*|13.*) echo 'PortalAI Projection requires macOS 14 or newer.' >&2; exit 2 ;;
esac
ARCH=$(uname -m)
case "$ARCH" in
  arm64) EXPECTED=233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f ;;
  x86_64) EXPECTED=fb3187d95334813b88940db0f1ca57b84cedfd552739c3a5771c3ea0e49988c9 ;;
  *) echo 'Supported Macs: Apple silicon and Intel.' >&2; exit 2 ;;
esac
umask 077
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH
RUNTIME="$MODULE/Runtime/MacPython-$ARCH"
if [ -L "$RUNTIME" ]; then echo 'Linked runtime refused.' >&2; exit 2; fi
if [ ! -d "$RUNTIME" ]; then
  ARCHIVE="$MODULE/Runtime/python-runtime-$ARCH.tar.gz"
  ACTUAL=$(/usr/bin/shasum -a 256 "$ARCHIVE"); ACTUAL=${ACTUAL%% *}
  if [ "$ACTUAL" != "$EXPECTED" ]; then echo 'Bundled runtime checksum failed.' >&2; exit 2; fi
  LOCK="$MODULE/Runtime/.mac-bootstrap-$ARCH.lock"
  if ! mkdir "$LOCK"; then echo 'Runtime setup is already running or was interrupted; inspect its lock before retrying.' >&2; exit 2; fi
  trap 'rmdir "$LOCK"' EXIT
  STAGE=$(mktemp -d "$MODULE/Runtime/.mac-$ARCH.XXXXXX")
  /usr/bin/tar -xzf "$ARCHIVE" --strip-components=1 -C "$STAGE"
  "$STAGE/bin/python3.12" -B -I -c 'import sys,tkinter,ssl; assert sys.version_info[:2]==(3,12); print("Bundled Mac Python/Tk/TLS ready")'
  if [ -e "$RUNTIME" ]; then echo 'Runtime appeared during setup; staged files retained for review.' >&2; exit 2; fi
  mv "$STAGE" "$RUNTIME"
  rmdir "$LOCK"; trap - EXIT
fi
mkdir -p "$MODULE/state/tmp" "$MODULE/state/cache" "$MODULE/state/input" "$MODULE/Connections"
export TMPDIR="$MODULE/state/tmp" XDG_CACHE_HOME="$MODULE/state/cache"
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
exec "$RUNTIME/bin/python3.12" -B -I "$@"
