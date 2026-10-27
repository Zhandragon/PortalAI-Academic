#!/bin/bash
# PortalAI Academic online installer. Requires no host Python.
set -euo pipefail
SOURCE='https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.27-Desktop-r47'
ARCHIVE='PortalAI-Academic-Linux-Installer-2026.10.27-Desktop-r47-suite.tar.gz'
ARCHIVE_HASH='ccc7253d41b0c914198ab0d5b96901789a4b7323aa5cb335ddc2c7ccd55e836a'
TOP='PortalAI-Academic-Linux-Installer-2026.10.27-Desktop-r47-suite'
PLATFORM='Linux'
OWNER='PortalAI-Academic-bootstrap-20261027-Desktop-r47-Linux'
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
check_setup_space() {
DESTINATION=$1
BASE_KIB=$2
MIN_FREE_KIB=$3
OUTPUT_KIB=$4
FREE_PERCENT=$5
for value in "$BASE_KIB" "$MIN_FREE_KIB" "$OUTPUT_KIB" "$FREE_PERCENT"; do
    case "$value" in ''|*[!0-9]*) echo 'Invalid installer disk-space budget.' >&2; exit 2 ;; esac
done
PROBE=$DESTINATION
while [ ! -d "$PROBE" ]; do
    [ ! -e "$PROBE" ] || { echo 'Installation destination is not a directory.' >&2; exit 2; }
    PARENT=$(dirname -- "$PROBE")
    [ "$PARENT" != "$PROBE" ] || { echo 'Cannot locate destination volume.' >&2; exit 2; }
    PROBE=$PARENT
done
SPACE=$(LC_ALL=C df -Pk "$PROBE") || { echo 'Cannot determine destination disk space.' >&2; exit 2; }
printf '%s\n' "$SPACE" | awk -v base="$BASE_KIB" -v floor="$MIN_FREE_KIB" -v output="$OUTPUT_KIB" -v fraction="$FREE_PERCENT" -v destination="$DESTINATION" '
    NR == 2 && $2 ~ /^[0-9]+$/ && $4 ~ /^[0-9]+$/ {
        valid=1; available=$4; reserve=int(($2*fraction+99)/100);
        if(reserve<floor) reserve=floor;
        need=base+reserve+output;
        printf "Disk space at %s: required %.2f GiB; available %.2f GiB.\n",destination,need/1048576,available/1048576;
        printf "Includes installation, downloads, working space and %.2f GiB of output/free-space reserves.\n",(reserve+output)/1048576;
        if(available<need) {
            printf "Not enough disk space: need %.2f GiB more. Choose another destination or free space before retrying.\n",(need-available)/1048576;
            failed=1;
        }
    }
    END { if(!valid) { print "Cannot determine destination disk space; installation stopped."; exit 2 } if(failed) exit 1 }
'

}
if [ "$PREPARE_ONLY" -eq 1 ]; then
    check_setup_space "$SETUP" 1561783 0 0 0
else
    check_setup_space "$SETUP" 17603954 52428800 104857600 10
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
            echo 'Download failed. Check the connection and that the pinned release asset is available.' >&2; exit 1
        fi
        if ! valid "$TEMP" "$size" "$expected"; then echo "Downloaded part failed size/SHA-256 verification: $name" >&2; exit 1; fi
        mv -f "$TEMP" "$CACHE/$name"
        TEMP=''
    fi
done <<'ACADEMIC_PARTS'
PortalAI-Academic-Linux-Installer-2026.10.27-Desktop-r47-suite.tar.gz|532027356|ccc7253d41b0c914198ab0d5b96901789a4b7323aa5cb335ddc2c7ccd55e836a
ACADEMIC_PARTS
if [ ! -f "$CACHE/$ARCHIVE" ] || [ "$(digest "$CACHE/$ARCHIVE")" != "$ARCHIVE_HASH" ]; then
    echo 'Reconstructing the installer archive...'
    TEMP=$(mktemp "$CACHE/.assemble.XXXXXXXX")
    while IFS='|' read -r name size expected; do cat "$CACHE/$name" >> "$TEMP"; done <<'ACADEMIC_PARTS'
PortalAI-Academic-Linux-Installer-2026.10.27-Desktop-r47-suite.tar.gz|532027356|ccc7253d41b0c914198ab0d5b96901789a4b7323aa5cb335ddc2c7ccd55e836a
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
ACADEMIC_EDITION.txt|1721|de6f4dbbd0eb64cc87ab7a0b22a41dacbb9491aefb9a35cbf655f1259b24855a
install.sh|6209|2acb40fdce2a695c7d02fa7e0af0a4502b231fc1ad502ca9afc1e1d76cb576c7
manifest.json|29353|ae15cd07db6695689ded361373a8477999aadf5aa25c0005f729bff14ac45e1f
payload.tar.gz|467443533|c2012658f4c06a90afaf8059ae3ba56d5112b69e5e69bfe68114325e244f7fe8
python-runtime.tar.gz|67038113|1f929539c96625b1dfb0ac90717ce627a02579709baf9304fa51c44af7f2d5e4
README.txt|3538|466f65427ed41ad3cfcecb8bbf3553faad965238d4dde884deef6806a6245871
SHA256SUMS|961|e779b8fd47d248f2445721685a5ac8ccb4dffbcf987d1cd94cef6e4a19edc2a8
storage-plan.json|837|5f0eca0c374c8ad59a695f2bdf8e7a6d8c1c9815a2723dec92329f0c01618a94
storage-preflight.sh|1697|44136581cdad9dc8638e3d690694c41ca2097c2bfad0a535293e85f8faff4e67
Utilities/PortalAI-HomeAssistant-0.5.12-recovery-0.1.0.zip|679400|811641c9b9d932ed235cc1d8a4f6070ac6aee63f2155a6f45dd22d11fd04b79d
upgrade.json|926|5ed7b89218de0fc05e12852ea7cf6085ecb70ba8073c7575ad02856a618dd3b6
suite-catalog.json|4338|0df33217af5e67eb9bc1a3ab4cadb212ebb9a9d06533ff13556c126b4e15e10a
ACADEMIC_FILES
echo 'The complete Academic installer has been downloaded and verified.'
if [ "$PREPARE_ONLY" -eq 1 ]; then printf 'Prepared installer: %s\n' "$PACKAGE"; exit 0; fi
echo 'Starting the Academic installation. Additional runtime/model downloads may follow.'
sh "$PACKAGE/install.sh" "$SETUP/PortalAI Academic Linux"
