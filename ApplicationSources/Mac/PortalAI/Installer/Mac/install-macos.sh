#!/bin/bash
set -euo pipefail

# Milestones describe completed stages, not elapsed time or estimated bytes.
portal_stage() {
  portal_done=$1; shift
  portal_bar=''; portal_i=0
  while [ "$portal_i" -lt 10 ]; do
    if [ "$portal_i" -lt "$portal_done" ]; then portal_bar="${portal_bar}#"; else portal_bar="${portal_bar}-"; fi
    portal_i=$((portal_i + 1))
  done
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then printf '\033[38;5;73mPortalAI\033[0m  \033[38;5;136m[%s]\033[0m  %s/10 stages complete | %s\n' "$portal_bar" "$portal_done" "$*"
  else printf 'PortalAI [%s] %s/10 stages complete | %s\n' "$portal_bar" "$portal_done" "$*"; fi
}
portal_stage 0 'Checking destination and requirements'

SELF_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH
ARCH="$(uname -m)"
case "$ARCH" in
  arm64) RUNTIME="$SELF_DIR/python-runtime-arm64.tar.gz" ;;
  x86_64) RUNTIME="$SELF_DIR/python-runtime-x86_64.tar.gz" ;;
  *) echo "PortalAI supports Apple silicon (arm64) and Intel (x86_64) Macs; found $ARCH." >&2; exit 2 ;;
esac

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this installer on macOS. It cannot install on Linux or Windows." >&2
  exit 2
fi
if [[ "$(id -u)" == "0" ]]; then
  echo "Run this installer as your regular Mac user, not with sudo." >&2
  exit 2
fi
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Apple Command Line Tools are required. Run: xcode-select --install" >&2
  exit 2
fi
if ! command -v xcrun >/dev/null 2>&1 || ! xcrun -f metal >/dev/null 2>&1; then
  echo "The Apple Metal shader compiler is unavailable. Install Xcode with its Metal toolchain and rerun." >&2
  exit 2
fi
if ! command -v cmake >/dev/null 2>&1; then
  echo "CMake is required to compile the Metal inference backend." >&2
  if command -v brew >/dev/null 2>&1; then
    echo "Install it with: brew install cmake" >&2
  else
    echo "Install CMake from https://cmake.org/download/ and rerun this installer." >&2
  fi
  exit 2
fi

INSTALL_PARENT="$(dirname -- "$SELF_DIR")"
DEST="${1:-$SELF_DIR/PortalAI Academic Mac}"
case "$DEST" in
  /|"$HOME"|"$HOME/") echo "Choose a dedicated PortalAI install directory." >&2; exit 2 ;;
esac
if [[ -e "$DEST" || -L "$DEST" ]]; then
  echo "Install destination already exists; no files were replaced: $DEST" >&2
  exit 2
fi
PARENT="$(dirname -- "$DEST")"
mkdir -p "$PARENT"
case "$ARCH" in
  arm64) sh "$SELF_DIR/storage-preflight.sh" "$PARENT" 18821506 52428800 104857600 10 ;;
  x86_64) sh "$SELF_DIR/storage-preflight.sh" "$PARENT" 18822372 52428800 104857600 10 ;;
esac

WRITE_CHECK="$(mktemp "$PARENT/.portalai-macos-write-check.XXXXXX")" || {
  echo "The destination volume is not writable by macOS: $PARENT" >&2
  exit 2
}
if ! chmod 700 "$WRITE_CHECK" || [[ ! -x "$WRITE_CHECK" ]]; then
  rm -f "$WRITE_CHECK"
  echo "The destination filesystem does not preserve executable permissions: $PARENT" >&2
  echo "Choose a writable Mac filesystem suitable for native application files." >&2
  exit 2
fi
rm -f "$WRITE_CHECK"

portal_stage 1 'Verifying package checksums'
(cd "$SELF_DIR" && shasum -a 256 -c SHA256SUMS)
STAGE="$(mktemp -d "$PARENT/.portalai-macos-install.XXXXXX")"
cleanup() {
  if [[ -n "${STAGE:-}" && -d "$STAGE" ]]; then rm -rf -- "$STAGE"; fi
}
trap cleanup EXIT INT TERM

portal_stage 2 'Unpacking application'
tar -xzf "$SELF_DIR/payload.tar.gz" -C "$STAGE"
ROOT="$STAGE/PortalAI"
if [[ ! -d "$ROOT/Agent" || ! -f "$ROOT/ControlCenter/PortableAI_GUI.py" ]]; then
  echo "Installer payload is incomplete." >&2
  exit 1
fi
mkdir -p "$ROOT/Runtime/MacPython"
portal_stage 3 'Unpacking Python runtime'
tar -xzf "$RUNTIME" --strip-components=1 -C "$ROOT/Runtime/MacPython"
PYTHON="$ROOT/Runtime/MacPython/bin/python3.12"
if [[ ! -x "$PYTHON" ]]; then echo "Bundled Mac Python did not extract." >&2; exit 1; fi
if ! "$PYTHON" -I -c 'import platform,sys,tkinter; assert sys.version_info[:2] == (3,12); print(platform.machine(), tkinter.Tcl().eval("info patchlevel"))'; then
  echo "Bundled Mac Python/Tk failed its startup check." >&2
  exit 1
fi
"$PYTHON" -B -I -c 'import sys; from pathlib import Path; root=Path(sys.argv[1]); sys.path.insert(0,str(root/"Agent")); from runtime_policy import require_space; require_space(root,8*1024**3)' "$ROOT"

portal_stage 4 'Preparing model engine build'
mkdir -p "$STAGE/llama-source" "$STAGE/llama-build"
tar -xzf "$SELF_DIR/llama.cpp-source.tar.gz" --strip-components=1 -C "$STAGE/llama-source"
JOBS="${PORTALAI_BUILD_JOBS:-2}"
if [[ ! "$JOBS" =~ ^[1-8]$ ]]; then echo "PORTALAI_BUILD_JOBS must be an integer from 1 to 8." >&2; exit 2; fi
PREFIX="$ROOT/LLM/backends/macos-metal"
cmake -S "$STAGE/llama-source" -B "$STAGE/llama-build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DGGML_METAL=ON -DGGML_NATIVE=ON -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
portal_stage 5 'Building model engine'
cmake --build "$STAGE/llama-build" --target llama-server --parallel "$JOBS"
cmake --install "$STAGE/llama-build"
if [[ ! -x "$PREFIX/bin/llama-server" ]]; then
  echo "llama.cpp did not install the expected llama-server executable." >&2
  exit 1
fi

portal_stage 6 'Installing and checking runtime components'
"$PYTHON" -B "$ROOT/Tools/import_macos_layers.py"
"$PYTHON" -B "$ROOT/Tools/macos_installer_smoke.py"

# Academic installs one standard chat model; no alternate downloads.
portal_stage 7 'Downloading and verifying models'
"$PYTHON" -B "$ROOT/Tools/import_foundation_assets.py" --install --only qwen1.7-q8

# The fresh wheelhouses and pip resolution reports are installer scratch only.
rm -rf -- "$ROOT/Cache/macos-gui-wheelhouse" "$ROOT/Cache/macos-accounts-wheelhouse" \
  "$ROOT/Cache/macos-gui-resolution.json" "$ROOT/Cache/macos-accounts-resolution.json" \
  "$ROOT/Cache/pip" "$ROOT/Cache/tmp"

mkdir -p "$ROOT/PortalAI.app/Contents/MacOS"
cat > "$ROOT/PortalAI.app/Contents/MacOS/PortalAI" <<'LAUNCHER'
#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../../.." && pwd)"
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$ROOT/Runtime/MacPython/bin/python3.12" "$ROOT/Launchers/portalai_gui_macos.py"
LAUNCHER
chmod 755 "$ROOT/PortalAI.app/Contents/MacOS/PortalAI"
cat > "$ROOT/PortalAI.app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>PortalAI</string>
  <key>CFBundleIdentifier</key><string>ai.portalai.academic.desktop</string>
  <key>CFBundleName</key><string>PortalAI Academic</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>2026.10.18</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

rm -rf -- "$STAGE/llama-source" "$STAGE/llama-build"
mkdir -p "$ROOT/Maintenance/Imports"
"$PYTHON" -B - "$SELF_DIR/manifest.json" "$ROOT/Maintenance/Imports/macos-python.json" "$ARCH" <<'PY'
import json,sys
manifest=json.load(open(sys.argv[1],encoding='utf-8'))
row=manifest['python_runtimes'][sys.argv[3]]
json.dump({'python':'3.12.15','architecture':sys.argv[3],'archive':row['asset'],
           'archive_sha256':row['sha256'],'source':'astral-sh/python-build-standalone release 20261009',
           'verified_archive':True,'recipient_runtime_smoke_passed':True},
          open(sys.argv[2],'w',encoding='utf-8'),indent=2)
PY

portal_stage 8 'Creating verified recovery backups'
"$PYTHON" -B -I "$ROOT/Tools/repair_executables.py" --seed-fresh-native-install

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  echo "Refusing to overwrite a path created during installation: $DEST" >&2
  exit 2
fi
portal_stage 9 'Publishing verified installation'
mv "$ROOT" "$DEST"
rmdir "$STAGE"
STAGE=""
portal_stage 10 'Installation complete'
echo "PortalAI Academic Mac installed at: $DEST"
echo "Open $DEST/PortalAI.app. The standard Qwen 1.7B chat model was installed. Academic mode is permanent."
echo "This build is unsigned and not notarized. On first launch, Control-click PortalAI.app and choose Open."
