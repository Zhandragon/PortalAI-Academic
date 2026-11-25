#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd -P)"
VERIFY=0; PREPARE=0; EXTRACT=0; PRIVATE_RELEASE=1
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
if [ -f "$ROOT/setup.tsv" ]; then
  while IFS=$'\t' read -r name bytes hash; do
    [[ "$name" =~ ^Setup/[A-Za-z0-9._/-]+$ && "$bytes" =~ ^[0-9]+$ && "$hash" =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid model setup pin.' >&2; exit 2; }
    case "/$name/" in */../*) echo 'Unsafe model setup path.' >&2; exit 2;; esac
    valid "$ROOT/$name" "$bytes" "$hash" || { echo "Missing/corrupt model setup file: $name" >&2; exit 2; }
  done < "$ROOT/setup.tsv"
else
  echo 'The complete model setup inventory is missing. Extract a fresh bundle.' >&2; exit 2
fi
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
[ ! -L "$ROOT/Setup/Models" ] && [ ! -L "$ROOT/Setup/$platform" ] || { echo 'Linked model setup folder refused.' >&2; exit 2; }
cp -R "$ROOT/Setup/Models" "$folder/model-setup"
cp "$ROOT/Setup/$platform/$script" "$folder/$script"
cp "$ROOT/Setup/$platform/SHA256SUMS" "$folder/SHA256SUMS"
cp "$ROOT/Setup/$platform/suite-local.json" "$folder/suite-local.json"
while IFS=$'\t' read -r source destination bytes hash; do
  case "$source" in "Utilities/$platform/"*) ;; *) echo 'Invalid companion source.' >&2; exit 2;; esac
  case "$destination" in SuiteAssets/*) ;; *) echo 'Invalid companion destination.' >&2; exit 2;; esac
  case "/$source/$destination/" in */../*) echo 'Unsafe companion path.' >&2; exit 2;; esac
  valid "$ROOT/$source" "$bytes" "$hash" || { echo "Corrupt bundled companion: $source" >&2; exit 2; }
  mkdir -p "$(dirname -- "$folder/$destination")"
  cp "$ROOT/$source" "$folder/$destination"
done < "$ROOT/Setup/$platform/suite-copy.tsv"
[ "$EXTRACT" = 0 ] || { echo "Prepared $folder"; exit 0; }
mount_root=$(LC_ALL=C df -Pk "$ROOT" | awk 'NR==2 {for(i=1;i<=5;i++)sub(/^[[:space:]]*[^[:space:]]+[[:space:]]+/,"");print}')
[ -n "$mount_root" ] || { echo 'Cannot determine the drive root. Run the native installer with your chosen destination.' >&2; exit 2; }
read -r -p "Installation root directory [$mount_root]: " install_parent
install_parent="${install_parent:-$mount_root}"
case "$install_parent" in /*) ;; *) echo 'Choose an absolute installation root.' >&2; exit 2;; esac
echo "Application: ${install_parent%/}/PortalAI $platform"
echo "Optional companions: ${install_parent%/}/Utilities"
exec bash "$folder/$script" "${install_parent%/}/PortalAI $platform"
