#!/bin/bash
# PortalAI Academic online installer. Requires no host Python.
set -euo pipefail
SOURCE='https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/packages/20261021-r1/Linux'
ARCHIVE='PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz'
ARCHIVE_HASH='8efa43d13a4059d1d2fd14a3c31d5a55b1e2eaa71926b5502f57f6a9f9afadd7'
TOP='PortalAI-Academic-Linux-Installer-20261021-r1'
PLATFORM='Linux'
OWNER='PortalAI-Academic-bootstrap-20261021-r1-Linux'
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
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part001|24000000|7c561025861c5e7fd63b2dbda4f0e6d7e8f1ccef69fc2e64de805392471eda3f
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part002|24000000|f53e73a33ec243c8015fa55fdb10ba003c4152c40ad319fb0f5476c2d8a4434e
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part003|24000000|fee227f30ab04bf26e884ee58cef598626d2b7598cc65b35a7dfad643d3b09b6
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part004|24000000|7932b8b9838aebd733c0b11bade3b6032d930b5145b45a3c89c5ff2b875c6ac9
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part005|24000000|475a3e898514aea6e7112f572ebea2fa1d28ec463e688be7a6bae06cb704717c
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part006|7529248|1d06c52ec8a16262cfddfcafd2938ca90d77309d9cce174ff27f9a48678cc3d3
ACADEMIC_PARTS
if [ ! -f "$CACHE/$ARCHIVE" ] || [ "$(digest "$CACHE/$ARCHIVE")" != "$ARCHIVE_HASH" ]; then
    echo 'Reconstructing the installer archive...'
    TEMP=$(mktemp "$CACHE/.assemble.XXXXXXXX")
    while IFS='|' read -r name size expected; do cat "$CACHE/$name" >> "$TEMP"; done <<'ACADEMIC_PARTS'
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part001|24000000|7c561025861c5e7fd63b2dbda4f0e6d7e8f1ccef69fc2e64de805392471eda3f
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part002|24000000|f53e73a33ec243c8015fa55fdb10ba003c4152c40ad319fb0f5476c2d8a4434e
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part003|24000000|fee227f30ab04bf26e884ee58cef598626d2b7598cc65b35a7dfad643d3b09b6
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part004|24000000|7932b8b9838aebd733c0b11bade3b6032d930b5145b45a3c89c5ff2b875c6ac9
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part005|24000000|475a3e898514aea6e7112f572ebea2fa1d28ec463e688be7a6bae06cb704717c
PortalAI-Academic-Linux-Installer-20261021-r1-x86_64.tar.gz.part006|7529248|1d06c52ec8a16262cfddfcafd2938ca90d77309d9cce174ff27f9a48678cc3d3
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
manifest.json|2018|354bd668c6e51b9bc8b1909b9b23b7f697b9ed5561db37c6161b350ddea85be8
payload.tar.gz|61257137|9ee31faaf14072933ec6bec95c6732832117fbf07f8d635fcebc63f4310da4ab
python-runtime.tar.gz|67038113|1f929539c96625b1dfb0ac90717ce627a02579709baf9304fa51c44af7f2d5e4
README.txt|5885|298422bc6bc7dce02f20fb26dfed6efe8de3a35bf33c2f42e92eff42e712dc7e
SHA256SUMS|408|5abb50fca5ac74fea5d730001d30477c969b14df31632f12027c76b5246e6e98
ACADEMIC_FILES
echo 'The complete Academic installer has been downloaded and verified.'
if [ "$PREPARE_ONLY" -eq 1 ]; then printf 'Prepared installer: %s\n' "$PACKAGE"; exit 0; fi
echo 'Starting the Academic installation. Additional runtime/model downloads may follow.'
sh "$PACKAGE/install.sh" "$SETUP/PortalAI Academic Linux"
