#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd -P)"
VERIFY=0; PREPARE=0
case "${1:-}" in --verify-only) VERIFY=1;; --prepare-only) PREPARE=1;; '') ;; *) echo 'Use --prepare-only or --verify-only, or no option.' >&2; exit 2;; esac
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
  if [ "$url" = UNCONFIGURED ]; then
    if [ -z "$release_base" ]; then
      read -r -p 'Enter this Full release URL (https://github.com/OWNER/REPO/releases/download/TAG): ' release_base <&3
      [[ "$release_base" =~ ^https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/download/[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid GitHub release URL.' >&2; exit 2; }
    fi
    url="$release_base/$filename"
  fi
  case "$url" in https://github.com/*/releases/download/*) ;; *) echo 'Expected a GitHub HTTPS release URL.' >&2; exit 2;; esac
  [ ! -e "$target" ] && [ ! -L "$target" ] || { echo "Existing package differs; review before retrying: $target" >&2; exit 2; }
  temporary=$(mktemp "$ROOT/Packages/.download.XXXXXX")
  echo "Downloading $platform package"
  curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --output "$temporary" "$url"
  valid "$temporary" "$bytes" "$hash" || { echo 'Download checksum/size mismatch.' >&2; exit 2; }
  mv -- "$temporary" "$target";temporary=''
done < "$ROOT/assets.tsv"
[ "$count" = 3 ] || { echo 'Expected exactly three platform packages.' >&2; exit 2; }
echo 'All three OS packages are verified. Each OS completes its own native installation.'
[ "$VERIFY" = 0 ] && [ "$PREPARE" = 0 ] || exit 0
case "$(uname -s)" in Darwin) platform=Mac; script=install-macos.sh;; Linux) platform=Linux;script=install.sh;; *) echo 'Use Prepare Universal.cmd on Windows.';exit 0;; esac
read -r -p "Open the $platform installer now? [y/N] " answer
case "$answer" in y|Y|yes|YES) ;; *) exit 0;; esac
filename=$(awk -F '\t' -v p="$platform" '$1==p {print $2}' "$ROOT/assets.tsv")
folder="$ROOT/Platforms/${filename%.tar.gz}"
[ ! -e "$folder" ] && [ ! -L "$folder" ] || { echo "An extracted installer already exists. Run $folder/$script directly.";exit 2; }
mkdir -p "$folder"
tar -xzf "$ROOT/Packages/$filename" --strip-components=1 -C "$folder"
exec bash "$folder/$script"
