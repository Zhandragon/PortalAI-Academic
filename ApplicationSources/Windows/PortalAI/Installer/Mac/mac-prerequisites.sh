#!/bin/bash
# Sourced by the verified installer after bundled Python and version checks.
# CMake stays inside PortalAI. Apple controls its own tool downloads and licenses.
portalai_apple_permission() {
  local answer
  echo "$1"
  if [ ! -t 0 ]; then
    echo 'Run this installer interactively to authorize Apple developer-tool setup.' >&2
    return 1
  fi
  read -r -p 'Start this Apple setup now? [y/N] ' answer
  case "$answer" in y|Y|yes|YES) return 0 ;; *) echo 'Apple setup was not started.'; return 1 ;; esac
}

portalai_mac_prerequisites() {
  local python="$1" root="$2" package="$3" cmake_dir archive selected
  cmake_dir="$root/Runtime/BuildTools/CMake-3.31.8"
  if command -v cmake >/dev/null 2>&1; then
    CMAKE_EXECUTABLE="$(command -v cmake)"
  elif [ -d "$cmake_dir" ]; then
    CMAKE_EXECUTABLE="$("$python" -B -I "$package/mac-cmake.py" --destination "$cmake_dir" --verify)" || return 2
  else
    echo 'Downloading portable CMake 3.31.8 (74.7 MiB). It stays inside PortalAI; no Homebrew or system install.'
    mkdir -p "$root/Cache/installer-prerequisites"
    archive="$root/Cache/installer-prerequisites/cmake-3.31.8-macos-universal.tar.gz"
    if [ ! -f "$archive" ]; then
      /usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --output "$archive.part" 'https://github.com/Kitware/CMake/releases/download/v3.31.8/cmake-3.31.8-macos-universal.tar.gz' || return 2
      mv "$archive.part" "$archive"
    fi
    CMAKE_EXECUTABLE="$("$python" -B -I "$package/mac-cmake.py" --archive "$archive" --destination "$cmake_dir")" || return 2
  fi
  "$CMAKE_EXECUTABLE" --version || return 2
  if ! xcode-select -p >/dev/null 2>&1; then
    portalai_apple_permission 'Apple Command Line Tools are missing. PortalAI can open Apple’s installation dialog; Apple may require license acceptance.' || return 2
    xcode-select --install || { echo 'Apple setup could not start. Open Xcode from the App Store to continue.' >&2; return 2; }
    echo 'Finish Apple’s installation, then rerun this same PortalAI installer. No application update was applied.'
    return 3
  fi
  if xcrun -f metal >/dev/null 2>&1; then return 0; fi
  if xcodebuild -version >/dev/null 2>&1; then
    portalai_apple_permission 'Apple’s Metal compiler is missing. PortalAI can request the Metal Toolchain download for the selected Xcode installation.' || return 2
    xcodebuild -downloadComponent MetalToolchain || { echo 'Metal download failed or needs Apple setup/license completion. Finish it in Xcode > Settings > Components, then rerun.' >&2; return 2; }
    xcrun -f metal >/dev/null 2>&1 || { echo 'Apple completed the request but the Metal compiler is still unavailable. Check the selected Xcode installation.' >&2; return 2; }
    return 0
  fi
  portalai_apple_permission 'Command Line Tools are present, but full Xcode with Metal is unavailable. PortalAI can open Apple’s Xcode download page; choose Get/Install there.' || return 2
  /usr/bin/open 'macappstore://itunes.apple.com/app/id497799835' || return 2
  echo 'Install and open Xcode, finish Apple’s setup, then rerun PortalAI. PortalAI will request the Metal component if still missing.'
  return 3
}
