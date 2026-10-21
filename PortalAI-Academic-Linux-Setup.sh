#!/bin/bash
# PortalAI Academic online installer. Requires no host Python.
set -euo pipefail
SOURCE='https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/packages/20261020-r2/Linux'
ARCHIVE='PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz'
ARCHIVE_HASH='3f627b48bb3ccca6d5202fec51afad34e6da2afc22495bbc3e9fb7a71f52e8ca'
TOP='PortalAI-Academic-Linux-Installer-r2'
PLATFORM='Linux'
OWNER='PortalAI-Academic-bootstrap-20261020-r2-Linux'
PREPARE_ONLY=0
SETUP=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prepare-only) PREPARE_ONLY=1; shift ;;
        --directory) [ "$#" -ge 2 ] || { echo 'Missing setup directory.' >&2; exit 2; }; SETUP="$2"; shift 2 ;;
        *) echo 'Usage: bash installer [--directory PATH] [--prepare-only]' >&2; exit 2 ;;
    esac
done
if [ "$PREPARE_ONLY" -eq 0 ]; then
    [ "$(uname -s)" = Linux ] || { echo 'This installer requires Linux.' >&2; exit 2; }
    case "$(uname -m)" in x86_64|amd64) ;; *) echo 'This installer requires Linux x86-64.' >&2; exit 2 ;; esac
fi
printf '\nPortalAI Academic - %s Setup\n\n' "$PLATFORM"
printf '%s\n' 'This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students.'
if [ -z "$SETUP" ]; then
    DEFAULT_SETUP="$HOME/PortalAI Academic $PLATFORM Setup"
    printf '\nSetup folder [%s]: ' "$DEFAULT_SETUP"
    IFS= read -r SETUP || exit 1
    SETUP="${SETUP:-$DEFAULT_SETUP}"
fi
case "$SETUP" in /*) ;; *) SETUP="$PWD/$SETUP" ;; esac
for tool in curl tar mktemp wc; do command -v "$tool" >/dev/null || { echo "Required tool is missing: $tool" >&2; exit 1; }; done
if command -v sha256sum >/dev/null 2>&1; then
    digest() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
    digest() { shasum -a 256 "$1" | awk '{print $1}'; }
else echo 'SHA-256 tool missing (sha256sum or shasum).' >&2; exit 1
fi
if [ -e "$SETUP" ] && [ ! -d "$SETUP" ]; then echo 'Setup path is not a folder.' >&2; exit 1; fi
if [ -d "$SETUP" ] && [ -n "$(ls -A "$SETUP")" ]; then
    if [ ! -f "$SETUP/.portalai-academic-setup" ] || [ "$(cat "$SETUP/.portalai-academic-setup")" != "$OWNER" ]; then
        echo 'Choose a new, empty setup folder. This folder contains unrelated files.' >&2; exit 1
    fi
fi
mkdir -p "$SETUP"
SETUP=$(cd "$SETUP" && pwd -P)
printf '%s' "$OWNER" > "$SETUP/.portalai-academic-setup"
if ! mkdir "$SETUP/.bootstrap.lock" 2>/dev/null; then
    echo 'Another setup is running. If a prior setup was interrupted, remove the empty .bootstrap.lock folder after ensuring it is no longer running.' >&2; exit 1
fi
TEMP=''
cleanup() {
    if [ -n "$TEMP" ] && [ -f "$TEMP" ]; then rm -f "$TEMP"; fi
    rmdir "$SETUP/.bootstrap.lock" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
CACHE="$SETUP/downloads"
mkdir -p "$CACHE"
valid() { [ -f "$1" ] && [ "$(wc -c < "$1" | tr -d '[:space:]')" = "$2" ] && [ "$(digest "$1")" = "$3" ]; }
while IFS='|' read -r name size expected; do
    printf '\nVerifying/downloading %s\n' "$name"
    if ! valid "$CACHE/$name" "$size" "$expected"; then
        TEMP=$(mktemp "$CACHE/.download.XXXXXXXX")
        downloaded=0
        for attempt in 1 2 3; do
            if curl --fail --location --retry 2 --connect-timeout 20 --speed-time 90 --speed-limit 1024 --max-filesize "$size" --proto '=https' --proto-redir '=https' --output "$TEMP" "$SOURCE/$name"; then downloaded=1; break; fi
            if [ "$attempt" -lt 3 ]; then echo 'Retrying the interrupted download...'; sleep 1; fi
        done
        if [ "$downloaded" -ne 1 ]; then
            echo 'Download failed. Check the connection and that all package parts have been committed to main.' >&2; exit 1
        fi
        if ! valid "$TEMP" "$size" "$expected"; then echo "Downloaded part failed size/SHA-256 verification: $name" >&2; exit 1; fi
        mv -f "$TEMP" "$CACHE/$name"
        TEMP=''
    fi
done <<'ACADEMIC_PARTS'
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part001|24000000|ef6de54456a1f77948b102f1474be29156077b39e4ccec473bd74f75867a7ca5
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part002|24000000|d605cab524c0f20f7586a340be29d0018f9a4ddd433e8e76f8a35bfa725477c4
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part003|24000000|177e965e0e67d7e101e83bd9ddd487f65080b20925e4c9130d1f344ff8ca432e
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part004|24000000|e87310207e51feffae9acd7a45f0664e6fcc1a0da919f200ce0d25ebc7b8117c
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part005|24000000|b32e5dd82e2d6bb52eaf44b2235d9b2e985a67893e6d2b79cbe32e6913bac3aa
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part006|7537112|07f668d64b728373d2bb6070809890bda3267302c57fc7e25c2e584eb04f2685
ACADEMIC_PARTS
if [ ! -f "$CACHE/$ARCHIVE" ] || [ "$(digest "$CACHE/$ARCHIVE")" != "$ARCHIVE_HASH" ]; then
    echo 'Reconstructing the installer archive...'
    TEMP=$(mktemp "$CACHE/.assemble.XXXXXXXX")
    while IFS='|' read -r name size expected; do cat "$CACHE/$name" >> "$TEMP"; done <<'ACADEMIC_PARTS'
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part001|24000000|ef6de54456a1f77948b102f1474be29156077b39e4ccec473bd74f75867a7ca5
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part002|24000000|d605cab524c0f20f7586a340be29d0018f9a4ddd433e8e76f8a35bfa725477c4
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part003|24000000|177e965e0e67d7e101e83bd9ddd487f65080b20925e4c9130d1f344ff8ca432e
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part004|24000000|e87310207e51feffae9acd7a45f0664e6fcc1a0da919f200ce0d25ebc7b8117c
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part005|24000000|b32e5dd82e2d6bb52eaf44b2235d9b2e985a67893e6d2b79cbe32e6913bac3aa
PortalAI-Academic-Linux-Installer-20261020-r2-x86_64.tar.gz.part006|7537112|07f668d64b728373d2bb6070809890bda3267302c57fc7e25c2e584eb04f2685
ACADEMIC_PARTS
    if [ "$(digest "$TEMP")" != "$ARCHIVE_HASH" ]; then echo 'Reconstructed archive checksum failed.' >&2; exit 1; fi
    mv -f "$TEMP" "$CACHE/$ARCHIVE"
    TEMP=''
fi
PACKAGE="$SETUP/installer"
if [ ! -d "$PACKAGE" ]; then
    echo 'Extracting the verified installer...'
    STAGE=$(mktemp -d "$SETUP/.extract.XXXXXXXX")
    tar -xzf "$CACHE/$ARCHIVE" -C "$STAGE"
    [ -d "$STAGE/$TOP" ] || { echo 'Expected installer folder is missing.' >&2; exit 1; }
    mv "$STAGE/$TOP" "$PACKAGE"
    rmdir "$STAGE"
fi
while IFS='|' read -r name size expected; do
    if ! valid "$PACKAGE/$name" "$size" "$expected"; then
        echo "Extracted installer file is missing or changed: $name. Choose a new setup folder." >&2; exit 1
    fi
done <<'ACADEMIC_FILES'
install.sh|3520|98e2ec1b8ce35adc3a2a204fa9a2bf90b0f4b262f0e38e9adedabc084128e019
manifest.json|2076|48db5b2e848e632a2af6e657e00339fc6b37e4cbe2ecd080407a3c8a8c9d5c21
payload.tar.gz|61256780|7a7774772e6bdfa394a433976851eb7a8eab92effc74c96db5137b239ffbe77a
python-runtime.tar.gz|67038113|1f929539c96625b1dfb0ac90717ce627a02579709baf9304fa51c44af7f2d5e4
README.txt|5780|244392ea452788493df9c4fb63bbf31478f25b9be7c8455c2f88209f354a6134
SHA256SUMS|408|a1404881b76e407a733ad9220df3785ec8fee4a074325f2a66fc9182d0d0cb61
ACADEMIC_FILES
echo 'The complete Academic installer has been downloaded and verified.'
if [ "$PREPARE_ONLY" -eq 1 ]; then printf 'Prepared installer: %s\n' "$PACKAGE"; exit 0; fi
echo 'Starting the Academic installation. Additional runtime/model downloads may follow.'
sh "$PACKAGE/install.sh" "$SETUP/PortalAI Academic Linux"
