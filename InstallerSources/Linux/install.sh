#!/bin/sh
set -eu

case "$(uname -s)" in
  Linux) ;;
  *) echo "This installer supports Linux x86-64 only." >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) ;;
  *) echo "This installer supports Linux x86-64 only." >&2; exit 2 ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
INSTALL_PARENT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
# Keep the installed app beside this installer script by default so the whole
# installation can travel with the drive. A positional path
# override remains available for an explicitly chosen destination.
DEST="${1:-$SCRIPT_DIR/PortalAI Academic Linux}"
case "$DEST" in
  /*) ;;
  *) DEST="$PWD/$DEST" ;;
esac
DEST_NAME=$(basename -- "$DEST")
DEST_PARENT=$(dirname -- "$DEST")
case "$DEST_NAME" in
  ""|"."|"..") echo "Choose a new installation folder." >&2; exit 2 ;;
esac
mkdir -p -- "$DEST_PARENT"
DEST_PARENT=$(CDPATH= cd -- "$DEST_PARENT" && pwd -P)
DEST="$DEST_PARENT/$DEST_NAME"
case "$DEST" in
  /|"$HOME"|"$HOME/") echo "Choose a dedicated PortalAI install directory." >&2; exit 2 ;;
esac
DEST_PARENT="$(dirname -- "$DEST")"
DEST_NAME="$(basename -- "$DEST")"
DEST="$DEST_PARENT/$DEST_NAME"

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  echo "Refusing to overwrite existing path: $DEST" >&2
  exit 2
fi

sh "$SCRIPT_DIR/storage-preflight.sh" "$DEST_PARENT" 14702402 52428800 104857600 10

# Check executable-bit support before unpacking the multi-gigabyte payload.
EXEC_CHECK=$(mktemp "$DEST_PARENT/.portalai-exec-check.XXXXXX")
if ! chmod 700 "$EXEC_CHECK" || [ ! -x "$EXEC_CHECK" ]; then
  rm -f -- "$EXEC_CHECK"
  echo "The destination filesystem does not support executable permissions: $DEST_PARENT" >&2
  echo "Choose a Linux-writable filesystem that preserves Unix executable bits." >&2
  exit 2
fi
rm -f -- "$EXEC_CHECK"

(
  cd "$SCRIPT_DIR"
  sha256sum --check SHA256SUMS
)

STAGE=$(mktemp -d "$DEST_PARENT/.portalai-linux-install.XXXXXX")
cleanup() {
  if [ -n "${STAGE:-}" ] && [ -d "$STAGE" ]; then
    case "$STAGE" in
      "$DEST_PARENT"/.portalai-linux-install.*) rm -rf -- "$STAGE" ;;
      *) echo "Refusing to remove unexpected staging path: $STAGE" >&2 ;;
    esac
  fi
}
trap cleanup EXIT HUP INT TERM

tar -xzf "$SCRIPT_DIR/payload.tar.gz" -C "$STAGE"
mkdir -p "$STAGE/PortalAI/Runtime"
tar -xzf "$SCRIPT_DIR/python-runtime.tar.gz" -C "$STAGE/PortalAI/Runtime"
chmod 755 "$STAGE/PortalAI/Runtime/LinuxPython/run-python"
chmod 755 "$STAGE/PortalAI/PortalAI.sh" "$STAGE/PortalAI/Launchers/portalai.sh" "$STAGE/PortalAI/Launchers/portalai-missions.sh" "$STAGE/PortalAI/LLM/backends/linux-cpu/llama-server" "$STAGE/PortalAI/Runtime/QEMU/linux-x64/bin/qemu-system-x86_64"

PYTHON="$STAGE/PortalAI/Runtime/LinuxPython/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "The bundled Linux Python runtime did not extract correctly." >&2
  exit 1
fi
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV __PYVENV_LAUNCHER__ LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

"$PYTHON" -B -I "$STAGE/PortalAI/Tools/install_linux_clean.py" --preflight
"$PYTHON" -B -I "$STAGE/PortalAI/Tools/install_linux_clean.py" --install-core

# Academic installs one standard chat model; no alternate downloads.
"$PYTHON" -B -I "$STAGE/PortalAI/Tools/import_foundation_assets.py" --install --only qwen1.7-q8

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  echo "Refusing to overwrite a path created during installation: $DEST" >&2
  exit 2
fi
mv -- "$STAGE/PortalAI" "$DEST"
echo
echo "PortalAI installed at: $DEST"
echo "Start the desktop app with: $DEST/PortalAI.sh"
echo "No mission or background service was started automatically."
