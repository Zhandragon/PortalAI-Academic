#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd -P)"
VERIFY=0; PREPARE=0
case "${1:-}" in --verify-only) VERIFY=1;; --prepare-only) PREPARE=1;; --extract-only) EXTRACT=1;; '') ;; *) echo 'Use --prepare-only, --verify-only, --extract-only, or no option.' >&2; exit 2;; esac
for command in curl tar awk wc mktemp; do command -v "$command" >/dev/null || { echo "Required OS utility missing: $command" >&2; exit 2; }; done
if command -v shasum >/dev/null; then digest() { shasum -a 256 "$1" | awk '{print $1}'; }
elif command -v sha256sum >/dev/null; then digest() { sha256sum "$1" | awk '{print $1}'; }
else echo 'The OS SHA-256 utility is missing.' >&2; exit 2; fi
[ ! -L "$ROOT/Packages" ] || { echo 'Linked package folder refused.' >&2; exit 2; }
if [ "$VERIFY" = 0 ]; then mkdir -p "$ROOT/Packages"; fi
valid() { [ -f "$1" ] && [ ! -L "$1" ] && [ "$(wc -c < "$1" | tr -d '[:space:]')" = "$2" ] && [ "$(digest "$1")" = "$3" ]; }
total=$(awk -F '\t' '{s+=$3} END {printf "%.0f",s+536870912}' "$ROOT/assets.tsv")
available=$(LC_ALL=C df -Pk "$ROOT" | awk 'NR==2 {printf "%.0f", $4*1024}')
if [ "$VERIFY" = 0 ] && [ "$available" -lt "$total" ]; then echo 'Insufficient free space to prepare all three packages.' >&2; exit 2; fi
count=0; temporary=''; seen=''; release_base=''
exec 3<&0
cleanup() { if [ -n "$temporary" ] && [ -f "$temporary" ]; then rm -f -- "$temporary"; fi; }
trap cleanup EXIT
while IFS=$'\t' read -r platform filename bytes hash url; do
  count=$((count+1))
  case "$platform" in Windows|Linux|Mac) ;; *) echo 'Invalid platform.' >&2; exit 2;; esac
  case ":$seen:" in *":$platform:"*) echo 'Duplicate platform.' >&2; exit 2;; esac
  seen="$seen:$platform"
  case "$filename" in ''|*[!A-Za-z0-9._-]*) echo 'Invalid archive name.' >&2; exit 2;; esac
  [[ "$bytes" =~ ^[0-9]+$ && "$hash" =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid asset pin.' >&2; exit 2; }
  target="$ROOT/Packages/$filename"
  if valid "$target" "$bytes" "$hash"; then echo "Verified $platform package"; continue; fi
  [ "$VERIFY" = 0 ] || { echo "Missing/corrupt $platform package." >&2; exit 2; }
  echo 'An included installer is missing or corrupt. Extract a fresh complete bundle; see START_HERE.txt.' >&2
  exit 2
done < "$ROOT/assets.tsv"
[[ "$count" = 1 || "$count" = 3 ]] || { echo 'Expected one or three platform packages.' >&2; exit 2; }
echo 'All included OS packages are verified. Each OS completes its own native installation.'
[ "$VERIFY" = 0 ] && [ "$PREPARE" = 0 ] || exit 0
case "$(uname -s)" in Darwin) platform=Mac; script=install-macos.sh;; Linux) platform=Linux;script=install.sh;; *) echo 'Use Start Setup.cmd on Windows.';exit 0;; esac
if [ "$EXTRACT" = 0 ]; then
  read -r -p "Open the $platform installer now? [y/N] " answer
  case "$answer" in y|Y|yes|YES) ;; *) exit 0;; esac
fi
filename=$(awk -F '\t' -v p="$platform" '$1==p {print $2}' "$ROOT/assets.tsv")
[ -n "$filename" ] || { echo "This bundle does not include $platform. Use the matching OS bundle or Universal." >&2; exit 2; }
folder="$ROOT/Platforms/${filename%.tar.gz}"
[ ! -e "$folder" ] && [ ! -L "$folder" ] || { echo "An extracted installer already exists. Run $folder/$script directly.";exit 2; }
mkdir -p "$folder"
tar -xzf "$ROOT/Packages/$filename" --strip-components=1 -C "$folder"
[ "$EXTRACT" = 0 ] || { echo "Prepared $folder"; exit 0; }
exec bash "$folder/$script"
