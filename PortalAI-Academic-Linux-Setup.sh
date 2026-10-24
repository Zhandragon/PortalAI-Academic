#!/bin/bash
# PortalAI Academic online installer. Requires no host Python.
set -euo pipefail
SOURCE='https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.24-r6'
ARCHIVE='PortalAI-Academic-Linux-Installer-20261024-r6.tar.gz'
ARCHIVE_HASH='a2b8ac55a4d12c3ae5479a4e198654a8942e8527ec0c89bbc681d754b2cf4371'
TOP='PortalAI-Academic-Linux-Installer-20261024-r6'
PLATFORM='Linux'
OWNER='PortalAI-Academic-bootstrap-20261024-r6-Linux'
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
    check_setup_space "$SETUP" 2410312 0 0 0
else
    check_setup_space "$SETUP" 17586907 52428800 104857600 10
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
PortalAI-Academic-Linux-Installer-20261024-r6.tar.gz|592753179|a2b8ac55a4d12c3ae5479a4e198654a8942e8527ec0c89bbc681d754b2cf4371
ACADEMIC_PARTS
if [ ! -f "$CACHE/$ARCHIVE" ] || [ "$(digest "$CACHE/$ARCHIVE")" != "$ARCHIVE_HASH" ]; then
    echo 'Reconstructing the installer archive...'
    TEMP=$(mktemp "$CACHE/.assemble.XXXXXXXX")
    while IFS='|' read -r name size expected; do cat "$CACHE/$name" >> "$TEMP"; done <<'ACADEMIC_PARTS'
PortalAI-Academic-Linux-Installer-20261024-r6.tar.gz|592753179|a2b8ac55a4d12c3ae5479a4e198654a8942e8527ec0c89bbc681d754b2cf4371
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
install.sh|3696|fcab51e6d3e67c1a0701acaea7227cfbf9c36b713e94c2ffa0ef111e05e95c81
manifest.json|13182|7d849e8e1635076b3b560ef6bbd952ff88534f81913e1978a6edd2d20b1da81f
payload.tar.gz|467321492|68333499508bc7ecaaa7680280d149e1d9fe060efc682fa42c3ad5dc4efd2060
python-runtime.tar.gz|67038113|1f929539c96625b1dfb0ac90717ce627a02579709baf9304fa51c44af7f2d5e4
README.txt|6598|27c946099c13ad199e95569035a649d7327ff01ba4aa3f44d147907da47d8f5d
SHA256SUMS|205464|2dbbe1fb434c64225bf71721e8e4866278083e0bf5d02269459f0b882f390a1e
storage-plan.json|768|a84b68a48b6934341a244e887f015c4f4c2c2eeb3f4878c36e8c1eb4f9d40ca6
storage-preflight.sh|1697|44136581cdad9dc8638e3d690694c41ca2097c2bfad0a535293e85f8faff4e67
Utilities/PortalAI HA Setup/Install PortalAI HA.sh|312|e9faf65cb70c4e9e06143e4586a73040454d8a8d404809b6a144242b5699e548
Utilities/PortalAI HA Setup/README.txt|3114|19d382cee8759952042cb86fa513134fc78cb9f9c0f39e2c44f50df3336916b2
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/AOOSTAR_HANDOFF.txt|1643|446352772e118becd6c8dd01d3d2291e78116a2733dfca70e5f6df6f6431637f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/configure.py|7175|ce063b8397e3d68a00570ebbcab23d2335453d7ceb8d96c5ed1e5c89fdb9975b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/__init__.py|16676|965745de4bc57ab045a28d2f3e69362116d7bf0a3c2e79ddd7b90cdd44cf13fa
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/commands.py|5881|5886d67d876d9ada5707c499279563ce6609fed8e8be57e7850d0573f005c025
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/core.py|4462|cbc94d7b5d15ea60283b2821fda83061d87eebcff9252f193cbe7bac4fb7c55f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/manifest.json|358|03fcf2034547057cfb6f5bfaac09bd7069f770c18ce5d58ddbe0800fe57bba60
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/rich_chat.py|3397|ff52078a2bcf7d5b71ff36132ffa46717b1bb180e5a6b1cb7b2a11841a34ece5
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/rich_protocol.py|4476|ab9ea713b27d0e023bee2314f5831cfc3cca696086b5c488add7b51e853ba9bc
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/schema.py|6252|f570f0f7e4bc65be326353b1f523aca4723ae2423dfa7b7d166ff9c5c4f2c658
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/services.yaml|494|2e3bf4100a2c30d92378f9465098f09279797346ce7f849c45f9491be15ac62a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_native/workflows.py|12227|652c3fc9d59b614a750d5ee5975cc88834168bcd630c33c9008e473f6b0b68ff
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_projection/__init__.py|8729|9a38611a18d83571ec7e8983d734a27fd03e97a0816e559b45f062cf0ba0acb0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_projection/manifest.json|321|7332ad010e5162a4fe832531e1c2fbeb1681a947a2485c7dbcfff99a92dbea03
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_projection/receiver.py|8950|4ad314d608adabf5b304ef5367370e8befe20eeeccdad6e5b55864b85129893b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_projection/services.yaml|1079|b6d4d12233a9127fbca4db984ebec7c355574a71f5fab0539b9e04f0087f2088
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_projection/viewer_demand.py|6914|bff925034fb033a8db67b679ecf61377d3de26d22855ce3a572e3517f6e534b9
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_recovery/__init__.py|5902|f07cb70763d20c0a481bb3d234530b55f257550ce28b2386401e23d7a7d0329f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_recovery/manifest.json|311|a6bdea401e49c692a180fc6ab8218deb7d20373d33bbe0e15587eb695bc76f55
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_recovery/receiver.py|6152|68b5d14224706768a06bbd454d5a1d4640431e0e83de9a619d29524de9460972
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_recovery/services.yaml|685|9f7254b90c24a796188ddaf3402d281744803c3dc6f95e50653e7759a04cc890
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/DISTRIBUTION.txt|456|542423ae30216c49fe83e529ab68675b1f252175a4c9f7fc9a723268f55c63d0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/configuration.merge.yaml|579|d9661e181ac3a7ed5ea229cc5618c1a736a731e3961f9f7b72b2f67083ff66a8
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/desktop-projection-card.yaml|100|ca7c41ecc30a7e42a485e7cfdd46e649da38971395cb153c608e5574949e3bad
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/projection-dashboard.yaml|205|52727167f1870fb62993cdaab6a93b5d69d20b0538a8dd4000a9ce9478fcc05f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/quick-chat-card.yaml|172|a4765c335fc583140500a1380928e21995979c3dd1ea4bf2b64006abeef8c0c1
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/quick-controls-card.yaml|1027|807de3d54154dda5b49e96880a75c47983f21cbc7aa1442017f115ae30600fc2
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/quick-view.yaml|1182|0fff241740be8d1ef46a1a32636a3430d168205f1b4a509315c2d1bd5eb6176b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/recovery-card.yaml|577|87c137a6be7e6fc6e1a4e7c4ea3e9537e62de911b9b1d719a44bddbd9723603d
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/examples/resources.yaml|526|84be10e5f5a15cc436721cd56461482684aa81c05a9ccce3c0b2d1bb0f7a3e79
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/finish.py|2904|836850de5e446bf6c5b360056c60ec93c34e19668d5786f7a461ec69b48d9bb6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/HTTP_COMPATIBILITY.txt|1065|e377fc36342ffdcef9dc7c849b967a5c06dd021dafe0c8efc88e3930bea77e34
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Install Home Assistant.cmd|982|53f81e876e9240cefc25474afdd59814d99d4a88cf89da883a6a93ca19a81c39
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/install.py|18694|cc6d7fc95679ec2513694fadbc6d5a5eff65416393795bdaaf5036935e7c54b4
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/install.sh|361|737e2fa7df074092a380a23073712518330244102ed5e25de62904fe0fc403c9
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/MERGE_NOTES.txt|2323|278e023e59bc7952087a1e0faaadea3e130c61f6d25686b5e3037e1c8339aaf8
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/PORTABLE_MERGE.txt|6035|7a23a1c37216419223cb44e89f67555ce13076a240829f6e0586fe9fa18be091
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/PORTABLE_VALIDATION.txt|279|f894c432839d7a8d5c412098cc9d947dc007e518478b95b23811c7f93eed6be6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/README_FIRST.txt|5147|2529d75b001ec6eca4ffec8403fac20510bdf684494a13dcc51170a76d533e2e
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/RECOVERY.txt|7590|15b1513936947966bcaf8deabedeed766c8e21c5459fe27a5ed0e0801c85b6bb
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/RELEASE.json|676|be3989b77ebed74a5f666a48149ba58633320fa2734c987d227b530d2fafc629
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/SHA256SUMS.json|19278|ecb2f1b8efc1e38389b907db824875412ab1e3fa98b7183244bb8b94e5fc9eb7
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/aoostar-compatibility-20261012/examples/ready-empty-unknown.json|1309|b5632af0864cd62f4fad225d3e6e362cab84fcf63ad265d9cd91e5d57f375fb1
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/build-live.mjs|2034|22f592234c3afebe70a9a19ac0a2ab163e80c51eb53ca1fff374449ecd2b357b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/build-projection.mjs|614|ff7a0057d8cc6a2d041c4945af81561e91c252db81bbaf5db04601edeea4b05a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/build-quick.mjs|953|967f5bdc34882e2db11546735a2a6256cf973d7ad29c50a2986bd720f19773c8
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/AOOSTAR_HANDOFF.txt|1643|446352772e118becd6c8dd01d3d2291e78116a2733dfca70e5f6df6f6431637f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/configure.py|7175|ce063b8397e3d68a00570ebbcab23d2335453d7ceb8d96c5ed1e5c89fdb9975b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/DISTRIBUTION.txt|456|542423ae30216c49fe83e529ab68675b1f252175a4c9f7fc9a723268f55c63d0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/configuration.merge.yaml|579|d9661e181ac3a7ed5ea229cc5618c1a736a731e3961f9f7b72b2f67083ff66a8
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/desktop-projection-card.yaml|100|ca7c41ecc30a7e42a485e7cfdd46e649da38971395cb153c608e5574949e3bad
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/projection-dashboard.yaml|205|52727167f1870fb62993cdaab6a93b5d69d20b0538a8dd4000a9ce9478fcc05f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/quick-chat-card.yaml|172|a4765c335fc583140500a1380928e21995979c3dd1ea4bf2b64006abeef8c0c1
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/quick-controls-card.yaml|1027|807de3d54154dda5b49e96880a75c47983f21cbc7aa1442017f115ae30600fc2
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/quick-view.yaml|1182|0fff241740be8d1ef46a1a32636a3430d168205f1b4a509315c2d1bd5eb6176b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/recovery-card.yaml|577|87c137a6be7e6fc6e1a4e7c4ea3e9537e62de911b9b1d719a44bddbd9723603d
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/examples/resources.yaml|526|84be10e5f5a15cc436721cd56461482684aa81c05a9ccce3c0b2d1bb0f7a3e79
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/finish.py|2904|836850de5e446bf6c5b360056c60ec93c34e19668d5786f7a461ec69b48d9bb6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/HTTP_COMPATIBILITY.txt|1065|e377fc36342ffdcef9dc7c849b967a5c06dd021dafe0c8efc88e3930bea77e34
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/Install Home Assistant.cmd|982|53f81e876e9240cefc25474afdd59814d99d4a88cf89da883a6a93ca19a81c39
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/install.py|18694|cc6d7fc95679ec2513694fadbc6d5a5eff65416393795bdaaf5036935e7c54b4
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/install.sh|361|737e2fa7df074092a380a23073712518330244102ed5e25de62904fe0fc403c9
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/MERGE_NOTES.txt|2323|278e023e59bc7952087a1e0faaadea3e130c61f6d25686b5e3037e1c8339aaf8
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/PORTABLE_MERGE.txt|6035|7a23a1c37216419223cb44e89f67555ce13076a240829f6e0586fe9fa18be091
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/PORTABLE_VALIDATION.txt|279|f894c432839d7a8d5c412098cc9d947dc007e518478b95b23811c7f93eed6be6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/README_FIRST.txt|5147|2529d75b001ec6eca4ffec8403fac20510bdf684494a13dcc51170a76d533e2e
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/RECOVERY.txt|7590|15b1513936947966bcaf8deabedeed766c8e21c5459fe27a5ed0e0801c85b6bb
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/STABILITY.txt|2212|fdc9eb852f90555cdbe013da983d71d4b00d8410fe7293269e8e84ed6068cd99
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/VALIDATION.txt|1213|d4e1bee77557d3edfc58733e8f2549cd0c7522e7d614cdaaa28721f189a925f2
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/PyYAML-LICENSE.txt|1101|8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/README.txt|212|54dcb92579793d604b02d7188049d805dba5bd72894299a68a3ea8fa48f158a2
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/__init__.py|12311|6e1974e6a49e3bed59c654918c6aef9769bd9eb5dbd67f7e1906ad4cdd0caea7
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/composer.py|4883|fcaa37d16afa783594794a5ab94193dcb720f503c19ce3d59539c8311189f453
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/constructor.py|28639|90d8247da78b524c10618fd0e857f54f3d97570fe91b5c5513d024ef3faf88b0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/cyaml.py|3851|e99ac01bd7c062f7557b614aff0d21997a06ed962ca185306a91bc0a20bbd87d
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/dumper.py|2837|3cb72d66563064ba7b5e679477046ebf89d8399d940670c8532f3e94a7cb17ea
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/emitter.py|43006|8e086d694ede170837d5b1b407b45979aff6f40762f422a65eafd08e04290a44
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/error.py|2533|021f73fada072546c4f63f8cf18a7181244ce4280b09cc15cc980b2d1176171a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/events.py|2445|e74fd392c810884e2ea7e94aa3f57e9c1cbeb402319083d0c58e6a0e1282787c
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/loader.py|2061|5156becc8aa6905482218abf3e04869b835226db4763645fff3438fdbd5f1cdd
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/nodes.py|1440|80f28d8fca4a09d87677882bde021820d9cf39a3b11a12405226211919cf13ce
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/parser.py|25495|8a55a9e6fbe0a07146cef3990c8b45a068c3e83e369e1959ad9ca30306b4a09a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/reader.py|6794|d1d9b38ab3a20c6e17a38d519ee412ecaf6b918df18c78956ac7c330d4ea08dc
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/representer.py|14190|22e58ff9c016f6c1ca1274b4802a926bcf78935060e1c813c5a0f021c6d143e6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/resolver.py|9004|f4bf9561f9b89961f1503d558385fbae30d12bfed565de9bf76c33abb63620a6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/scanner.py|51279|60433788b652690c17710460da5d91e0c753d3318fd85f5e1e42862a71f25906
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/serializer.py|4165|0a1b85826854d35863e31808f0668abfabdf33606e8f06bd8bb7761401e3edc0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/distribution/HomeAssistant/vendor/yaml/tokens.py|2573|953408cd2570f0c83dc2fe39f7e4e388e41eeb05738aa69196a5f6ffcf6ba79e
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/__init__.py|16676|965745de4bc57ab045a28d2f3e69362116d7bf0a3c2e79ddd7b90cdd44cf13fa
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/commands.py|5881|5886d67d876d9ada5707c499279563ce6609fed8e8be57e7850d0573f005c025
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/core.py|4462|cbc94d7b5d15ea60283b2821fda83061d87eebcff9252f193cbe7bac4fb7c55f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/manifest.json|358|03fcf2034547057cfb6f5bfaac09bd7069f770c18ce5d58ddbe0800fe57bba60
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/rich_chat.py|3397|ff52078a2bcf7d5b71ff36132ffa46717b1bb180e5a6b1cb7b2a11841a34ece5
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/rich_protocol.py|4476|ab9ea713b27d0e023bee2314f5831cfc3cca696086b5c488add7b51e853ba9bc
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/schema.py|6252|f570f0f7e4bc65be326353b1f523aca4723ae2423dfa7b7d166ff9c5c4f2c658
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/services.yaml|494|2e3bf4100a2c30d92378f9465098f09279797346ce7f849c45f9491be15ac62a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_native/workflows.py|12227|652c3fc9d59b614a750d5ee5975cc88834168bcd630c33c9008e473f6b0b68ff
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_projection/__init__.py|8729|9a38611a18d83571ec7e8983d734a27fd03e97a0816e559b45f062cf0ba0acb0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_projection/manifest.json|321|7332ad010e5162a4fe832531e1c2fbeb1681a947a2485c7dbcfff99a92dbea03
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_projection/receiver.py|8950|4ad314d608adabf5b304ef5367370e8befe20eeeccdad6e5b55864b85129893b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_projection/services.yaml|1079|b6d4d12233a9127fbca4db984ebec7c355574a71f5fab0539b9e04f0087f2088
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_projection/viewer_demand.py|6914|bff925034fb033a8db67b679ecf61377d3de26d22855ce3a572e3517f6e534b9
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_recovery/__init__.py|5902|f07cb70763d20c0a481bb3d234530b55f257550ce28b2386401e23d7a7d0329f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_recovery/manifest.json|311|a6bdea401e49c692a180fc6ab8218deb7d20373d33bbe0e15587eb695bc76f55
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_recovery/receiver.py|6152|68b5d14224706768a06bbd454d5a1d4640431e0e83de9a619d29524de9460972
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/ha/custom_components/portalai_recovery/services.yaml|685|9f7254b90c24a796188ddaf3402d281744803c3dc6f95e50653e7759a04cc890
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/package.json|166|a478b87f12e2ddef75fc17749b4a56e72ba4dc3dbd8f67133cedba740ff44c41
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/browser-crypto.test.mjs|5915|f99b95d06984150056d313d2d0530e4bc4b6c59b2613556775c6488972cf9b76
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/chat-timeline.test.mjs|2662|dfc214be94a4907f5c6961559d38ca575a7a1ab210d8ec974f455f4371a8fa56
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/history-preview.test.mjs|2727|f3bb40166fb00f7ec6bcb1ae9d387a0feeefd33c676bbd6712f7c2025349b088
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/http-bundles.test.mjs|9404|7cc2f34f89e122841ce32b36e6efbc18f86871a395053758c18452d084ba4d53
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/iphone-attachments.test.mjs|18108|84b48ef123605558fd8e8fb320a573a00d507cf7355c88cd37d071432eded52c
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/iphone-review-fixture.js|6462|a3025db89764c8064f5ef7d8fa37ab6456db9bab76be68cab22267059d13a88b
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/iphone-review-server.mjs|1007|96938244565e236a42802cebf61b0c3c114398b0d6900ff430c97aac8d0ba53a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/live-state.test.mjs|5268|146e810782f91554fd2b1432f911054bc3d0ba50a845abe6bbe64315638b62f7
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/projection-lifecycle.test.mjs|4258|bc237326730c6502116c9c0f0b64f85af2be5eba1d61e3fa30de208388fb27d6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/state.test.mjs|5920|5826c87a6b552be8f87959a1afc6a8922f1289407f8d2b1355148797d130599f
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_batch_media_receiver.py|4031|2856602320dcf6760455c49d1c13cf2505d76c9cc9f553970e6f91824882dd87
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_batch_rich_bridge.py|5749|66f8777e5a0496405d9116da4b593b1b0fa78d4b799eb27d60d45e5da6005307
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_ha_autosetup.py|5588|0667429cd379fe2ff2f0c06f450701adeba6b310e581703d0ba8764ecd991f8a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_ha_installer.py|10853|41428c0bde6b3dcc81859f83572813dc951669a66b165ac879878877a8c8fd93
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_native_receiver.py|6936|ae9e31a26adf0ea274be9c5e7bcb54009f9f4ae746e684e79a068edd50c8a9fe
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_native_websocket.py|6234|5b47a01f161d57f01c2979ee3c2134b4964156eaa2b4043b499aea6579e380e0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_quick_chat.py|6682|7533c2c8c5854c1b3c1ae269ce544812cd636f61e43eb381d3750060e8f646e3
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_recovery_receiver.py|2275|b06d0d910be6c6deed133fa90aa7965badbf3254d10825d31fd42921f9c7991d
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_upload_v2.py|5857|5d26ee4ac4d8cd2bbb847facc1d4c406d4dad01a87fda9298a30d8a81e962810
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/test_workflow_priority.py|4988|c09fe1cf74605631fb082b0a6563c3502cbced51dfbde34974ee77996f50471d
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/upload-v2.test.mjs|3960|34168a5a3a7688b47da1d82f2079644394320d3a0e04f9c7f3debc2bcaed4922
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tests/visibility-grace.test.mjs|3159|24c67ee97057849211147a257cfa4ed2e5571778bc1a56ce342b31c2176ebbf0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/tools/build-ha-distribution.py|7593|3d67e2229be2f7a1a2f0ebd0136e834a14d2a6c6685fb178ffcfaf0e12be1199
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/assets/emblem.png|113582|8cc61bcbf28fe633bb3fd2177c0140bc01b0632d623ae55d0420a1b7aca44ec0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/assets/icon.png|15600|a9daf13f592f688560e0166017474b48058e1864993d0a6a6c3e2ed2a3e090e6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/assets/wordmark.png|3101|f13dac63e2d870f53403a3558f7cdbbdaaf52ae33420611df9aa3a892c62ccdf
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/browser-crypto.js|3492|789737c46c79be43056bfa1893c8af43799e3de4063812120c4f2628287fbf38
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/catalog.js|15339|50898760184232ead1b368fab815b764a7f1979f508b49b35c40c451693aa118
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/iphone-attachments.js|2093|6b246297275afed6bbe7a8f30fdedf482746edc66c1b20913d877e7b12867530
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/live-state.js|8246|8ce402edce0ed1fa83fbf822e6866ee4ac8ec19ac431d8bfb12b9e47cb190cbd
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/native-workflows.js|31656|5129107d8e7f5711a09d9a645a028b28cc06f9742570a62b6d31d4ac92195805
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/panel.css|18402|8c9dc296361683e84b565274c8c78743f61c2dc1d09f09aff36a11643c476eb9
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/patch-dom.js|2002|da5f8dc5075ae366b9cf2d19d4051ef67b2e3b7672821001d0d87f845cf253b6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/portalai-live-panel.js|28663|f8d906f12590d891e3e1ad31dfc79e906ffc5416133e1feb20165e1a0d21d122
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/portalai-native-panel.js|31010|db491e05cc6deb070ffea21ec119943abfab63ca7bad8103d0b6217cabb9b975
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/portalai-projection.js|16785|8f9349638f0889a298f7281a6169762bac50d11bf6c750bd1ec79efb16533ec9
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/portalai-quick-card.js|15583|caadaa2ba1b380d32bde64df1c3ba16451febee289502b9dbe8585a8a7b81851
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/portalai-viewer-demand.js|3580|eb87de3fb68fe977264adf11ce5df8eb1f115165ea61f33a791e885a2a8de393
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/rich-chat.js|15606|b071037aa6fe354a1fca21d113f3c1ea1a10dcf654899f36b18b555c0f5c85d9
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/state.js|9297|b891b067f7a89d6ba01ce7f4425200c8e0bf35ff69d104481608190ec076a1a3
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/Source/web/visibility-grace.js|742|33dd059a4e70885f16ef3bc0e050daaa9ac1c38f145cf771b5368a82e70b2cff
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/STABILITY.txt|2212|fdc9eb852f90555cdbe013da983d71d4b00d8410fe7293269e8e84ed6068cd99
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/VALIDATION.txt|1213|d4e1bee77557d3edfc58733e8f2549cd0c7522e7d614cdaaa28721f189a925f2
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/PyYAML-LICENSE.txt|1101|8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/README.txt|212|54dcb92579793d604b02d7188049d805dba5bd72894299a68a3ea8fa48f158a2
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/__init__.py|12311|6e1974e6a49e3bed59c654918c6aef9769bd9eb5dbd67f7e1906ad4cdd0caea7
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/composer.py|4883|fcaa37d16afa783594794a5ab94193dcb720f503c19ce3d59539c8311189f453
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/constructor.py|28639|90d8247da78b524c10618fd0e857f54f3d97570fe91b5c5513d024ef3faf88b0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/cyaml.py|3851|e99ac01bd7c062f7557b614aff0d21997a06ed962ca185306a91bc0a20bbd87d
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/dumper.py|2837|3cb72d66563064ba7b5e679477046ebf89d8399d940670c8532f3e94a7cb17ea
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/emitter.py|43006|8e086d694ede170837d5b1b407b45979aff6f40762f422a65eafd08e04290a44
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/error.py|2533|021f73fada072546c4f63f8cf18a7181244ce4280b09cc15cc980b2d1176171a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/events.py|2445|e74fd392c810884e2ea7e94aa3f57e9c1cbeb402319083d0c58e6a0e1282787c
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/loader.py|2061|5156becc8aa6905482218abf3e04869b835226db4763645fff3438fdbd5f1cdd
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/nodes.py|1440|80f28d8fca4a09d87677882bde021820d9cf39a3b11a12405226211919cf13ce
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/parser.py|25495|8a55a9e6fbe0a07146cef3990c8b45a068c3e83e369e1959ad9ca30306b4a09a
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/reader.py|6794|d1d9b38ab3a20c6e17a38d519ee412ecaf6b918df18c78956ac7c330d4ea08dc
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/representer.py|14190|22e58ff9c016f6c1ca1274b4802a926bcf78935060e1c813c5a0f021c6d143e6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/resolver.py|9004|f4bf9561f9b89961f1503d558385fbae30d12bfed565de9bf76c33abb63620a6
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/scanner.py|51279|60433788b652690c17710460da5d91e0c753d3318fd85f5e1e42862a71f25906
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/serializer.py|4165|0a1b85826854d35863e31808f0668abfabdf33606e8f06bd8bb7761401e3edc0
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/vendor/yaml/tokens.py|2573|953408cd2570f0c83dc2fe39f7e4e388e41eeb05738aa69196a5f6ffcf6ba79e
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/www/portalai-live-v0.5.11.js|346353|0daf0ac7ad6db364ccdba71e296dd49bd552cd6d28588db24b3e12ad9099ed07
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/www/portalai-live-v0.5.12.js|346297|96883b93d91505086a12b229af6a80a6a3a6ca7406fc61ac8124da3887740c59
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/www/portalai-projection-v0.5.11.js|20959|4af552ab83a35bed468a08496358e0555d25ccaad435d0612f338e8f81f58753
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/www/portalai-projection-v0.5.12.js|20959|aebe2db50a609386fb096e7bcfefa0eaf0a5fe21852ad9429eca32a82ef6194c
Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/www/portalai-quick-chat-v0.4.3.js|63767|b66c13961530ba0bb4641360e6051d5d570c01235e7deebae49ad704b4019e9b
Utilities/PortalAI-HomeAssistant-0.5.12-recovery-0.1.0.zip|679400|811641c9b9d932ed235cc1d8a4f6070ac6aee63f2155a6f45dd22d11fd04b79d
Utilities/PortalAI-Projection/app/assets/projection-dark.ico|15622|a71cd6fe8d82ffbb84563c8edce144161e4e9cf52ad8190f9b064a3e3d6d8cdc
Utilities/PortalAI-Projection/app/assets/projection-dark.png|15600|a9daf13f592f688560e0166017474b48058e1864993d0a6a6c3e2ed2a3e090e6
Utilities/PortalAI-Projection/app/connection_vault.py|3628|6e3c2c62a0aeece7cfa78ed41728365897a4d4a24a95ba308fb07316bfb5a080
Utilities/PortalAI-Projection/app/elegant_native_ui.py|16970|edcc9639f47bb1e582e105a47e19b89d6aed4edd37e4032b1496684b0b7092c2
Utilities/PortalAI-Projection/app/host_runtime.py|2814|be4825cf74a228bd4ce9e6f843d6bc91d781088b9f979fcaf83e124ba3b99ad6
Utilities/PortalAI-Projection/app/linux_desktop.py|8860|b9f0dce5d8bb9ed50a8248ea186241c0679c3ec15364d1912e1dc40c1bc04730
Utilities/PortalAI-Projection/app/linux_target.py|1942|eba110bfee0b033e34b373951933486595368fdf59f41a811718951cdec170b2
Utilities/PortalAI-Projection/app/macos_check.py|1225|2cdce3ab1a7b55b7efd4824f80dffd89748273e9047de444fc46b1207df09bfc
Utilities/PortalAI-Projection/app/macos_desktop.py|6441|f37421044663a1421bff20361470d0ad9941e4a668bd850419bb121faa53cba7
Utilities/PortalAI-Projection/app/macos_target.py|1280|284e13f075a11023d1c77ea2b84c2c58984bd8bf7f9548f7fbb99717652fb2ac
Utilities/PortalAI-Projection/app/native_receiver_schema.py|6252|f570f0f7e4bc65be326353b1f523aca4723ae2423dfa7b7d166ff9c5c4f2c658
Utilities/PortalAI-Projection/app/native_state_client.py|5927|b34e8c500aa4f288a5cf2255564a28c1534cde6bdaa00702009aef269e6a2283
Utilities/PortalAI-Projection/app/native_transport.py|10047|9b3ec7d01f246f8cac45a0794645096653377a40000e624df64a51123f0abf3e
Utilities/PortalAI-Projection/app/ornate_ui.py|23230|ecf95c5d6cce4406584c584ebb6a669fca15dc1e50a342926aace86d08050ff8
Utilities/PortalAI-Projection/app/portalai_target.py|23833|4637cebf54e6f748f3fae8d54300a94834b1043220c417d1894b2c1d1f040bf9
Utilities/PortalAI-Projection/app/projection_boot.py|2660|76e33a441b5e3650c8b45a84de3753b69021930d095315ee0e7d5cbf7a1b41cb
Utilities/PortalAI-Projection/app/projection_client.py|3922|a50f0022a81076ccb5cb2f5c70574772b1f544e87c481f024c8a59e6ea75c76c
Utilities/PortalAI-Projection/app/projection_local.py|1724|67b418d13880b1a51d5b8e4f7cd59365ef9684cc539648c04b620ca60d337e87
Utilities/PortalAI-Projection/app/projection_theme.py|19043|339d5392f811afade237d04699a9bf2460d2963be3c22af15c22f840a295d506
Utilities/PortalAI-Projection/app/projection_tray.py|8812|73585ff3f6bd1bd08ee6c41866426033e3b5151922aa494a1eba38e8a2d67f0c
Utilities/PortalAI-Projection/app/projection_ui.py|13613|45132f53aa0ec226444682d9b6bb582d336f80cee562cdc2bbeba90e96b278be
Utilities/PortalAI-Projection/app/projection_worker.py|16096|f552782bd724c23e653ee13baa94d49a7d65232a7f5edcf663d3f8077e350c0a
Utilities/PortalAI-Projection/app/recovery_runtime.py|12769|c159e6d5e6d6ea0ec4b989ec0ff166614784b534c9d5f7be1060fd82b8d5ed82
Utilities/PortalAI-Projection/app/recovery_transport.py|4266|3cc2baa97f396702b9bccb32187d214fcaa96bf425cf8354b79d2af50540c278
Utilities/PortalAI-Projection/app/recovery_ui.py|7663|b8bb1148d38a7fddb967b1f38b3f1dfab5efaec22987bc978b51f023ccfec3db
Utilities/PortalAI-Projection/app/ui_style_cache.py|827|850c9389b4b869b5c555f12520227317aa83c7d2a87afa2726331170264f4bc8
Utilities/PortalAI-Projection/app/viewer_demand.py|2437|6111572a21176284ad5a28c03ff3c90681c06486c39bb0af66e36ac48f2dd9fe
Utilities/PortalAI-Projection/app/windows_desktop.py|13814|7e1181fd801b66c3c97e713d00b4cd27816d80c8aa6bb7316b6f23c53cf6a726
Utilities/PortalAI-Projection/README-MAC.txt|5785|a8aee5d9a0630bff78df6f72917ef85a8d97db98e307383c45084056eb2f7b19
Utilities/PortalAI-Projection/README-PROJECTION-UI.txt|1217|9cc0204c038f7c2f7102920b2bb42a7ec39414bfa22e0d9b3637addce1d707e0
Utilities/PortalAI-Projection/README.txt|3114|a26ea42e249d7cca3e783d91a6ebb51318f9233889c3ad29a3f3fae495d33d6b
Utilities/PortalAI-Projection/Runtime/cacert.pem|240216|9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f
Utilities/PortalAI-Projection/Runtime/distribution-receipt.json|222006|87626c7082376931dd92886f84861fa4618d5eb555e653af152d1d20c5f7a9e8
Utilities/PortalAI-Projection/Runtime/LinuxFonts/DejaVuSans-Bold.ttf|708920|a4c5bc453ca281d90ea079e596da7ae0dfeb5777497c29ec254e76d97ff6f890
Utilities/PortalAI-Projection/Runtime/LinuxFonts/DejaVuSans.ttf|759720|57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e
Utilities/PortalAI-Projection/Runtime/LinuxFonts/fonts.conf|275|4b637547e7aaca7ec6ad783da7e756b96c77a121e2e91f73a6afa3fee5d9fe65
Utilities/PortalAI-Projection/Runtime/LinuxNative/ld-linux-x86-64.so.2|225672|c8438e4fde1934e61c88311633f00949ff645d5c04cdb8671fa3d78164d2f307
Utilities/PortalAI-Projection/Runtime/LinuxNative/libc.so.6|1995216|9792e3cbb541c8f44c7acf5f14f4022ea62998ecc787d326bed4d8b6547dfd92
Utilities/PortalAI-Projection/Runtime/LinuxNative/libcrypt.so.1|206776|436788729ab71d794a66954d62e930c723e624587f39beb2f4f86ff1000b1d29
Utilities/PortalAI-Projection/Runtime/LinuxNative/libdl.so.2|14408|295fa521a03cd2faa99974f378c9e23dd622021ec7d32bcad4f8ea61aec8a872
Utilities/PortalAI-Projection/Runtime/LinuxNative/libgcc_s.so.1|182856|30c61ab012a4241bed033725a09b61f5fdd3bb7df95ee852d0b096520524c7af
Utilities/PortalAI-Projection/Runtime/LinuxNative/libm.so.6|977112|6d567d53e895273ca14a1f9dc164fc6c8d39aed2f60aa46a733c2784228915f3
Utilities/PortalAI-Projection/Runtime/LinuxNative/libnss_dns.so.2|14336|d6ff05b8003825fbef5ad779b5e2f870f179953e4fb560697b6f261010efe8d4
Utilities/PortalAI-Projection/Runtime/LinuxNative/libnss_files.so.2|14336|8c93b2ae43dac3c2d688d227609d713f71620d3f0980ebf6bbb371c6eb542108
Utilities/PortalAI-Projection/Runtime/LinuxNative/libpthread.so.0|14408|85e21f7dba0394411d00959176fd18b470e575b0b05f1f4f41e5636802ce0500
Utilities/PortalAI-Projection/Runtime/LinuxNative/librt.so.1|14552|7b7b84d1aedda0e0b2bdfc68844362782132180b8f02be1300e21e77572e514b
Utilities/PortalAI-Projection/Runtime/LinuxNative/libutil.so.1|14408|e3981d10efd152a53f083e38f5f9ddde7a049c85d0ab388a5eec91b52fc98a11
Utilities/PortalAI-Projection/Runtime/LinuxNative/libX11.so.6|1342984|b03e563b316b8b53c7988f0ee91d6656cc425538e00947a8b14482d179e80099
Utilities/PortalAI-Projection/Runtime/LinuxNative/libXau.so.6|14472|4275ec5b14bec21770c44447b3a52977e211c7ba08745008f3a1783878e091bb
Utilities/PortalAI-Projection/Runtime/LinuxNative/libxcb.so.1|170936|a1cde2cec9b7b8b38e4cca450c55c63651efb80a2458d76964b56b763043f533
Utilities/PortalAI-Projection/Runtime/LinuxNative/libXcomposite.so.1|14320|b80f2a638fc5bb3ed9a400d48e758135687f10ee8e3b236c89bf0687250858db
Utilities/PortalAI-Projection/Runtime/LinuxNative/libXdmcp.so.6|26728|761409b24c818719f8c8a2a64a61c8ac6a3067f3d8882485dca64a98d7500040
Utilities/PortalAI-Projection/Runtime/LinuxPackages/_cffi_backend.cpython-312-x86_64-linux-gnu.so|348856|9bc1d08072255a5ec2db10fc75df1dd9e73097a75cd9150cfe875ebd6712f17c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/__init__.py|511|c47b2db28c5f197e242d4dd4af95b7ebb0da65763fc76972cafd06f93e942cda
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/_cffi_errors.h|3583|5b383ed01bb5fcad8610ad29494e5be90d86000b9d71a17cec7346f0ba05996c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/_cffi_gen_src.py|7044|c94479de91526ec6b7b2c17bfd53aa5d368a78be402531ccfddc99f48198f6cc
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/_cffi_include.h|15234|cd8e8a168a3f6e96b4d8f6a042cd61cde5bd3b9eac9e2a25a32c6abd1280a2df
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/_embedding.h|17554|3e101d00c70a0a5013559fa505c65e0c4735d85e85a9575a1ed689d8f920e84f
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/_imp_emulation.py|2960|4714441bccc06c8d913c6070c3dd2eff97e2f2c59d6a1a5d8a93a83f3929ec2d
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/_shimmed_dist_utils.py|2230|0638f6c26f3265bbc5bd6131e4011f9aa6aa6726458587e8c8b2d01e45d9b9aa
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/api.py|42013|7165f5665b1c98ec9392fb61881a5458b712441b6a9699fe9a806ee1eb019b32
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/backend_ctypes.py|42283|4fb092735e0fe6fca5a22e61ca8c7af2a841597d3bf68c075da1836d8fd4edba
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/cffi_opcode.py|5723|e7ed5c53aa691c6cecb2d17f7a88250fff2d08393bebf6619338f77d6e1289cd
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/commontypes.py|2805|ecdeb33ed08596fc57316847574f29b148dd6082b65e0b0ddf2a39760b9afefe
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/cparser.py|44754|598fa8c785064ae552613b609b4d8598681b99cb9a6812b79a816591d1529ac5
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/error.py|877|bfac53892e14d24bc3732e21fc10d1a39bf7f5942e8fe20c4582efe444dd759b
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/ffiplatform.py|3584|6afc458dd8a460626812d9893bb7b0566c06fd511597a119fd668d859602aafe
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/gen_src.py|132|4d4fd9543c282e71cf95a97cfe63e6a71ab2589ed4ef9da34dcdd4b13984d502
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/lock.py|747|97d4d37703083298ba8c39091a742013d72f4c847b0809ed209afc1061edde96
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/model.py|21752|700f9b10089b70751bb5ba9f80cab408b42314f02357425247333229588d805e
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/parse_c_type.h|5976|39dc107f033d92dababe5081e377b11509b10c1b63d8c04d74af0b625d79b63c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/pkgconfig.py|4365|bb2b75d7b4d079e6b77636a03355b9828f11a67c921938280b337c407c997657
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/recompiler.py|65140|4c9545d3b985cd819357ab33a76ccfac977674928737e781fd2ba22621a5f4ac
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/setuptools_ext.py|9566|a59ae74ea54290632abbc37123191d6c8b65eb981e84c3f52e8ada51d4fbfb85
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/vengine_cpy.py|43030|ad1a2e610e819650085cd8d91933d45b9e2b07de76aa2de0726d7a4965d628b7
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/vengine_gen.py|26931|67f2aa685eabe789f98b886341385975bfb50c14c48a69d4e32e04fcac520838
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi/verifier.py|11154|c48cd5f220cc859d7eaa15f74515f80d6a36934ed6a5c271761840157023ae66
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/direct_url.json|323|9eac62c5effa173d034da2c2c3277344ad3d5051a8322af2ae33697cf9103ec0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/entry_points.txt|132|a6b6108011f8e27050fe5269bba88c8051b414697880d3b0b6fbe3a03a0b001c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/INSTALLER|4|ceebae7b8927a3227e5303cf5e0f1f7b34bb542ad7250ac03fbcde36ec2f1508
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/licenses/LICENSE|1123|5ba24ddc57067f9249add644c3afc41a5d6dc37e23433ef759d95df370b0af63
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/METADATA|2527|558bafb9093a8e790175d9ecff9688382981d744877dad86fd6770db0f4dc918
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/RECORD|2762|a8be8062dadcd8f1749ce10436c7facfd20fe1f3b1385b38583515157b341c00
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/REQUESTED|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/top_level.txt|19|ac4ed6477ad97cd2b1588f7e8e7ea1b0708097b303901f859ae41bc568c57a14
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cffi-2.1.1.dist-info/WHEEL|151|504ac80cc95190c99aea177550563d7939b8fca6b1431c01c0d435e74afbbd0e
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/__about__.py|445|95184137751279e4ccc0ababa44ed8bc380fbcdd5ba584f0407c5d14e31c109d
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/__init__.py|364|9ad86e52b4dde0544e0a9518ad322a863cfab3a4fd763019ad5ee7675a0c9b6a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/cobblestone.py|693|4fff85d3cf8051fde58daca965e92535357585639b1f9ee8a38e66552ce4f707
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/exceptions.py|1087|f37e445882dcd9fc31c3e83214cae27220b64aa8558844c1d742c14b2b670c87
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/fernet.py|7687|dac2c23ce99e8e13956ee75c4b742c3353c8b876f109e45c46d5a49dc437982a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/__init__.py|455|e48c2b2d6ad5a7402312bff815d586fd5d39ecd489198fd6e1e80d36cb9cb748
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/_oid.py|18150|3a17b69d413a5e32b1d5417a4c0b06532daff06509f958bd0d2e32c52ba4b795
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/asn1/__init__.py|812|62a613a071858cb38a8a0442d341c68fa86b8c4c1bbb548fa408aeebebbe7daa
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/asn1/asn1.py|19152|f6671fae676f2bb2ad8e1458a1f3330235b4bbb9efa9b7ecbcf7db84d40ad414
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/backends/__init__.py|361|3b98ef28541d6675e129ea89f87b6e95a10bf4d8bb9abd660f3658e641e56212
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/backends/openssl/__init__.py|305|a778e625f9c26a0f62139b1d32b37a56f544bb9e6ee3ac5a4bf223a08d12ae60
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/backends/openssl/backend.py|10475|d0d73315b8b01b17eaf6a8b6f281d8af4f2bfebed5420e005c78dbd2814fc2a0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/__init__.py|216|c0709b59f69e7daf9f93a4c74b0f6d87d7c952c4ad268ef6e39c1f141aa676e0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/__init__.pyi|2285|b949e7bceabfb9a99e62704da66b2fdd244054ed16406a63239f1a47594be0ac
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/_openssl.pyi|228|4ffe53a583bc6e08483e3010dc1b40001ab0f82718b241e9f76c26e4f358e9d7
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/asn1.pyi|354|06b1a30bc27a9f0b92fabdc455c757241f27768b5f63d99b41839fa5b3c6d070
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/cobblestone.pyi|1325|f6551fd56d614ebb33109e18a527093483d20fd04e33ba3e0bcdbe9ad4831bda
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/declarative_asn1.pyi|3866|30198e6732d37663c9ebed4ae80ab73d3b872753068117c8bb484881a83ba1c1
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/exceptions.pyi|640|7b15ebdb1c3fd29075924f777186ccdcca216f3a149233a6b3564c522d2e4191
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/ocsp.pyi|4020|54f556b8a1c8f4432cd3d64b458006bd1d08cf49823261335c0920247a2fa683
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/__init__.pyi|1578|3ba18ecaf0f1b7aca589c0766851aebb945c199cbd5232a762a191f2bab3bddc
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/aead.pyi|4582|eddfbec5d734beecd17b84b6bae41a1a6fbd1862afe0d7122d070bc9671a0fab
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/ciphers.pyi|1315|2e13f31d649726ae20ac02579facd2bd249d57e698208b1c1c3c083e524618fb
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/cmac.pyi|564|9cf1f45f9ed1629b00911a305698d0887139eba4e1513c7b617aec69d9ab9879
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/dh.pyi|1564|6774c2f86d38f931ed49d00e3cb3358761bb9a5e5b75ad4495951c9f9c29ba19
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/dsa.pyi|1299|a81b64823d9a95bb76a8572767d503ae1ce83610953bb1d36f2e5549fd445cc2
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/ec.pyi|1691|cc9cb4a516b99fefe9d9d9b8e4fc44081ffe07a49567234a7e3c450e93ea4f7f
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/ed25519.pyi|532|5577d77791ba8548af837f7d4750d87665b77936f411e6f30d3aa3442da0691c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/ed448.pyi|514|631e3d96a7678ec0fb6f188357591c68cac392dba0e5ebe2e5aeb37ab322cb6b
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/hashes.pyi|1076|6c57b74f5dd47b24489d424c0fe47902b19318ba960e25a8d8bbf6286cd46dfe
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/hmac.pyi|702|057667ecd0e32f72406d85b4490f298358b20b90db4175615008b0b22f03151f
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/hpke.pyi|2914|a7f8462e7e981fe11aac91755796d4b14b638a9be2100a5c4793b4b141c92ed7
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/kdf.pyi|6619|1e288b74407d9ea32c4ef330885a694297cfcfa7c7533f7f8298c407f5c03970
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/keys.pyi|912|b5e22df0ce9910c26b9f8b375b45275b40d9fb7d0977af169d2b0a286d76e25d
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/keywrap.pyi|733|9860891284389718b8091393044b94cdbf54e24cbc9f9d8bde20ef08e5cd0512
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/mldsa.pyi|1421|1fce170d6d134372c785d1890f9b8f6834f98a31222ba319cad5d873cac135fe
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/mlkem.pyi|835|6f2a1ebace3e9483a55a5122450742734d2a0a45e9381e6978163aca8f6293cb
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/poly1305.pyi|585|fd25bd36d4391439406dd72516d5a94f89469b1288287a4dfb88fc27607361f4
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/rsa.pyi|1364|d8e4023525e4c6073edeec35c620829682104d5ea9f7f90aefd62ed2b85980f7
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/x25519.pyi|523|7b09f81a94326fbccfc04fa78bb1adc9080c0b403598bbaa62c4b2aafea723fb
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/openssl/x448.pyi|505|8ee4d94e6962f233bfe5572e7e0faf1efc7fb42c9ece648b221ffd3d4dd37332
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/pkcs12.pyi|1605|bc411de700e266f6fc64615ace22c26962f3030a06fedbcf5312d0c39fee3a5f
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/pkcs7.pyi|1601|b711812628ea66c84472aadae9bc8f35b9e2b08765c733922073f6865f5aacfb
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/test_support.pyi|757|3cf86577e5a43bbe3789714f79b786d0bb602b4693cc6763708b1acb51a6e461
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust/x509.pyi|10211|2d54f886d04db1ee608a3421e0685535811b00ed04d40360136f2d5aac378382
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/_rust.abi3.so|14436232|f28d787117880abb13cc08822d1a0704d27e0fb33155d353f10a0a67efa6c4c1
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/openssl/__init__.py|216|c0709b59f69e7daf9f93a4c74b0f6d87d7c952c4ad268ef6e39c1f141aa676e0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/openssl/_conditional.py|5611|bdfce2fb11dd4ad01c2508cbaaa3a54a8b3de0bf03feda85b417bb3afc3e2ad6
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/bindings/openssl/binding.py|3706|16cb8bc5b4e7aea5bad3e7405ad6a482e7deabb4e7a9a41a8b53dcec3a30ae3a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/decrepit/__init__.py|216|c0709b59f69e7daf9f93a4c74b0f6d87d7c952c4ad268ef6e39c1f141aa676e0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/decrepit/ciphers/__init__.py|216|c0709b59f69e7daf9f93a4c74b0f6d87d7c952c4ad268ef6e39c1f141aa676e0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/decrepit/ciphers/algorithms.py|3752|5923e3336b177eb2c35ebb4de51ecdeab0355c5edbf772357bf96f0f8cb1da80
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/decrepit/ciphers/modes.py|1649|3aafcf1300a47b938b73339faffbf300e27ac0fc7eae5b2f1c05cf06e8796fda
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/__init__.py|216|c0709b59f69e7daf9f93a4c74b0f6d87d7c952c4ad268ef6e39c1f141aa676e0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/_asymmetric.py|532|46181ca2e501e874e214306b4752f1aa4323a54c4888dbd0d6bff3263446eaa4
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/_cipheralgorithm.py|1522|121de2ee5c1e7477e2d1e2d2b07f773d9c502b363d23a9642baeef2f8579b4e7
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/_modes.py|3075|fc4880383f096fa5a915796ec247144f7102cff4c7f318c6bdb4251a4366e7d4
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/_serialization.py|4440|862d3125b941019f29999c769566be96bba9871befbc6de0f4334ad06f0e75fb
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/__init__.py|216|c0709b59f69e7daf9f93a4c74b0f6d87d7c952c4ad268ef6e39c1f141aa676e0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/dh.py|5793|467b767cb683a501234125fc7cdb659935ce2478e5b7f0ca419d5595f85d8dae
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/dsa.py|4482|910cd3562a8023d3e210b34e05ca3f9fa31f3f737d7a120f91276e3a9ba9b743
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/ec.py|10183|2e495508b2f16db433aa213a1d16984d16ae2cca61614c37b44e9cf28048c584
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/ed25519.py|2998|99b7df2efb3edcf8020de835ad05d55e1ec62e7b6554be004e390811ce29b793
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/ed448.py|4002|9f474aeb2f952f1bb0fb3beb0f1b8f4f8e7df21ca6817fb5472fe3abd6944211
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/mldsa.py|13803|2c731a694d26eba12c4ab4a87567f87b691d99d0d14c41910b5cbe7c22b118ad
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/mlkem.py|7901|c2f5647854fee287fe55c500111dbecc8ff98574faaf04c93cc090f2017d1930
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/padding.py|3678|8db81a8ef18763090f8cc0e58c7bb99713019437e60b15947b6005d92e8a135d
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/rsa.py|8492|94813b9467b8e3d5b95112d3282a6f1467ab213a2e2a8655f46c2e4f349cb12a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/types.py|2588|4a32614eb9c544b9533dd62b043d69a0c8ba723606f9f8747d221a427dd0522c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/utils.py|821|42cf117bd1853e35bfb4da7fef721e2448cf09fd2c94e22c58ec68eaaca64fa9
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/x25519.py|3888|950720524f8f8ae6e3f329c535641e6267b7b5864c80742a9112a42033872f3a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/asymmetric/x448.py|3913|6f7ee283b93ba681ba4890ebcb8da3f849428f9ab8790d17e421663744a7f33f
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/ciphers/__init__.py|680|7b21179a393afc265768e3d80ebeef018197af6f50bf38162f6fb8092a252c5b
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/ciphers/aead.py|634|173972c7bc3c29841a9330e9d735a026722beb6ce066b815875bb68787b1079e
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/ciphers/algorithms.py|3496|2067c2c9c6093a1d53be8237e2b7f0f0a7c9ff19add69fc3a4186dd8582171ea
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/ciphers/base.py|4253|6810bb1c7041a22c5e6e6a5aad5af4525383b37543d00ec1ea8cff01a4630eff
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/ciphers/modes.py|6003|1fb0194a02624930428b482b2fdecdc5a912f79d09c852982ecadaf2d8c73f14
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/cmac.py|338|b33fece87fdc6273afc7e54d59d20a85185edd89a9f33f09d03dc206a397de08
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/constant_time.py|422|c5dba7593d277fc3af29d72a52186514a6b21a9e3f3e0549454d96d702d2aff0
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/hashes.py|7916|4abb7081cdffa45bd97c88518fd7b5a7859d8be17f3e995e18796a240460b4e8
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/hmac.py|423|469077cfdcf9b248ab090ae6ef341bb67a7da4b327023ae54d4bcaa85e5a0c37
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/hpke.py|865|46c1e2b2c0b997e7533e7d69d896dcac8ac09c306b2ea339ba0045486a662aee
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/__init__.py|1037|bf7ca2601194dbbd84a233576f07d865d6db7c8f5c54e0821b79d78530dd6b79
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/argon2.py|632|649c7e7a7525000e28edbe3a0b5c25cc6fd7010416d3022416050a92b33fc00f
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/concatkdf.py|591|0459ce292ef6b71285d3242f012af435aeee873bcb1e95027242b988d002fda4
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/hkdf.py|543|33494011f468738929a78fa7c038fdc81faf359ba420e60442b5255ac04d9fda
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/kbkdf.py|737|0b7c3df6f8c5aa1ab3031cc5387e33cef5681e46f9002e8bcfa00440657b77f8
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/pbkdf2.py|468|5dc86493df6cf8c93a6fa2920a8baa764f0557288d54e48521e9e69d6ded2e04
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/scrypt.py|590|5f259475452686e23d57a4ea00f3afba3092306bf55d0760d1adb52160a63be5
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/kdf/x963kdf.py|456|40a8e145e86e4ec02cb4bdfce1b29fbe3bafd727dd6a6007561b014567a7d95c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/keywrap.py|735|b7db7c299bb367852cdf4012521236ecc64f3cf2b2e041114439002be94ced34
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/padding.py|1865|413f94f8dbd5d9e4063b5c153db0e234635273d91e4434be8a0e5c40eacbcf41
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/poly1305.py|355|3f910f415f9107f1493da869834d6ed13b384bf3e7026b2ba312065db19e451a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/serialization/__init__.py|2217|7d772ee3dba02fdaf1869465ff06639cca84f430a484231cb11c5f8ffa93bde8
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/serialization/base.py|651|48006bbe8d12f3a41ca01963ec3a6378b5b2da5cd032bca28a827a0eb1184150
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/serialization/pkcs12.py|5104|992f5c14d1b869fcefb1ea1ce5ed4c5a863656c91f2fc37c63f3858e5ebb96e6
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/serialization/pkcs7.py|13998|98533b385b99f1c0b1506528a380a87fa06708773f21bc750108e37f19cf971a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/serialization/ssh.py|53592|162b177bf9d429d3c67ea10d5612a99a86b399a23ca87f067be5466dcd1dca4c
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/twofactor/__init__.py|258|b66319181fa0e08535afb94816a012534d7dcebd2e3e9ff010161cc1d0c22820
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/twofactor/hotp.py|3256|8af668e41adc08658bb2aaa5e27655d175c28f218f8bf8877c3165b4694e2709
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/hazmat/primitives/twofactor/totp.py|1652|9b92cfa512f4d24a78cd8f204e3af9e477f3f5a3253d2e7790799591240299d6
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/py.typed|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/utils.py|4635|21aed2d106734b47b3c2920741f63c1b57bea381a3ac78a31175e3c00af58ae2
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/__init__.py|8253|d0a54d4e646d758357fe2fdec2c4cdcdb4e6d9ed6ac9fa0e85ce1e9a883984be
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/base.py|28311|50830a9309acc75d01477fe09c14410814f0429d7e3bcc247d59bb6b31fefe61
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/certificate_transparency.py|797|26aa0e203865c089eb60c156e88167efb589d2f885f8f07fae5655defb3d3187
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/extensions.py|77975|fa25dcc169c82f5ce5e4c977055245904a3fef59dc5def387a1beacd6d6c2b83
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/general_name.py|7836|b0ffeb575d50969b24e31dd75c6258fccbf443fb3d76d8de2dc907b23a4b4284
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/name.py|15566|a08db0e95758f33830eeaa4d865c44c79d765b40215835d0ac361fe44b0cd8f6
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/ocsp.py|12699|61ecba35d155d4c3e3a29db8323fd57a78c4a60de451a328a5258e2b401b781b
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/oid.py|931|054ce05d71955a296406474a3d39bd478a84944f600061e07583cc640a7b3c9a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography/x509/verification.py|958|811d82d9cf97650b5b959853e53e6f8d228eb426fbe1e7f66a53d59847301653
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/direct_url.json|310|a5057f0491c668ab3b5559a260ae2a9626bb908aad325eabc769719a98ef3809
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/INSTALLER|4|ceebae7b8927a3227e5303cf5e0f1f7b34bb542ad7250ac03fbcde36ec2f1508
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/licenses/LICENSE|197|3e0c7c091a948b82533ba98fd7cbb40432d6f1a9acbf85f5922d2f99a93ae6bb
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/licenses/LICENSE.APACHE|11360|aac73b3148f6d1d7111dbca32099f68d26c644c6813ae1e4f05f6579aa2663fe
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/licenses/LICENSE.BSD|1532|602c4c7482de6479dd2e9793cda275e5e63d773dacd1eca689232ab7008fb4fb
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/METADATA|4394|047cfc71226409de4318b360aef15c63a2adf609731e3dcf7fe932f14ea042ee
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/RECORD|12502|407ea0745de2721ee6f46b135b3a57fff713500011365e63dbc7039fe9790e3a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/REQUESTED|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/sboms/cryptography-rust.cyclonedx.json|45685|b2dc68865311153a886ba5631d7f4d67af7c44b23cd2b375c3b37184b1a2db38
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/sboms/sbom.json|1206|1d9756164a26855b671fd64bc484e9e0834666be75cc53c4f204bdb761eaa76d
Utilities/PortalAI-Projection/Runtime/LinuxPackages/cryptography-50.0.2.dist-info/WHEEL|109|d6ef5e0a74f57394b6b6f26d88cf0e687862a6157a09a5f177cd7211acb9ee9f
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/__init__.py|2816|a78bf364bc0be541872ee109193d3e852d569cc82bd6715c8716d99808b190ff
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/_ast_gen.py|11521|f3ee67c4806e366f89c8a081fb6a96b25e7daf5eb789e6719dd09878ecc1307a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/_c_ast.cfg|5078|9b0d422a7a039ea02d37bb411f1b8a4188303bbc1a7a16e8aa203e452c1c76e8
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/ast_transforms.py|6512|be8a97e579b7864abc9bb62b78fed044fdeb9d1ad542d2e3ad7c86b3e295c071
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/c_ast.py|34029|ea7da69073a22bf4f97a4ac8ba0651a2ebe63d50debc4da67d051402cd8c3be4
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/c_generator.py|22157|68211cc34c0a18462061e5c21ab14f8e9005c1662ce886e5a2e393538f7bb1b6
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/c_lexer.py|25842|f390447cdc32939eb727cd5ae4e87e276acf7454a414b06a8507d2657b2e6e75
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser/c_parser.py|95003|ceb19bdbc09e5ebc8fc8bd1050d7103adf57ce7fc3bfce17815ea67b723b2579
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/direct_url.json|285|d24bbf1964581c8b84ab0224fe3dae36388f3e252124894a5b84274269850a8a
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/INSTALLER|4|ceebae7b8927a3227e5303cf5e0f1f7b34bb542ad7250ac03fbcde36ec2f1508
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/licenses/LICENSE|1543|0a9e78156ae8b96caf1b4f11ac2df424b83de29736f9e757630548a6272fdf90
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/METADATA|8238|e3a74c846648bb55f4f907284b745e2003b87b96d9c9d17a8a50cf37804541c9
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/RECORD|1321|6985a2fccbca7b9f1958f0e54426ece3318d4c7de48f9099edbf0c188ac06d8e
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/REQUESTED|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/top_level.txt|10|73e94f712ef82fff0aa07ec813a3d0179a1fca2ad140d57856191b48520f7963
Utilities/PortalAI-Projection/Runtime/LinuxPackages/pycparser-3.11.dist-info/WHEEL|91|61532836a2b3111b7ec23519c09df7c41180c27165fb872a6d8913b566b88ad1
Utilities/PortalAI-Projection/Runtime/LinuxPython/bin/python3|30990408|708fefcd7df61b1327cb7b9740fafd42cb2f6cd1d387378892d4a28b7479fb78
Utilities/PortalAI-Projection/Runtime/LinuxPython/bin/python3-config|3219|276d083c8dc925f0640eb86029cd09c0f2564540a8d5344b885390b8b4eeaafa
Utilities/PortalAI-Projection/Runtime/LinuxPython/bin/python3.12|30990408|708fefcd7df61b1327cb7b9740fafd42cb2f6cd1d387378892d4a28b7479fb78
Utilities/PortalAI-Projection/Runtime/LinuxPython/bin/python3.12-config|3219|276d083c8dc925f0640eb86029cd09c0f2564540a8d5344b885390b8b4eeaafa
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/itcl.tcl|5162|75db5e1e5695215a6cf0b8bd241c984b575c4493747eef9a8c307513ca7832c4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/itclConfig.sh|2886|7c02788468a3c9ca443feb49fadf32dda28f1690695d8644bf80a1fbd6fbdd5d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/itclHullCmds.tcl|19377|015378168f4431e23ef8df19ff4f03d1e772a91b02e625e584da257d4ae6fad3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/itclWidget.tcl|12113|cfe9a5eb616e1a8d5c97d5ff1ebdd6a69e0a033c6b9b05a8ce371f41edd38c92
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/libitclstub.a|2308|55b4b9f4c432fc21b7ae1d1f65450490142b4f55f270e54711b8e50ab159f5a7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/libitclstub4.3.8.a|2308|9d4595b807933e9058a6a95d2a8aa5bbc392048908a14c82890c44311cef381d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/libtcl9itcl4.3.8.so|301408|fb88c621a72963518aa773732b25245cdfcdd543a4fdc6ac8b8623c398bf46f7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/itcl4.3.8/pkgIndex.tcl|435|41b9e5f541106593a92eee84d5f39888d862f5c40737e57e89a81a286498aeb3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/libpython3.12.so|32790528|49e94230e2ec954dc86398bb8b099275793843ec41d1e6c38b65764ebb1ccf90
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/libpython3.12.so.1.0|32790528|49e94230e2ec954dc86398bb8b099275793843ec41d1e6c38b65764ebb1ccf90
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/libpython3.so|20736|3de35cc4f112b2638be0a258985019ef624cd490a8c83803a496088c6b040c02
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/libtcl9.0.so|2347768|ade8803ec44f874099cd330f14ee39592aeccd02b4f2e7764fe16c6b005cc2fc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/libtcl9tk9.0.so|3123880|a578b9f852d3ebc646bdf09d9f2ba81d0900162e985bbce50535a42284133c5d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/pkgconfig/python-3.12-embed.pc|312|097367804cb41980b1a7fea8252cd63bc387cb2f23cbdd8af62265b2d36290c4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/pkgconfig/python-3.12.pc|298|8fd251c5eaf0c622acd26df4d224429a2f43e0b20c423b830c4a719c10a81853
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/pkgconfig/python3-embed.pc|312|097367804cb41980b1a7fea8252cd63bc387cb2f23cbdd8af62265b2d36290c4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/pkgconfig/python3.pc|298|8fd251c5eaf0c622acd26df4d224429a2f43e0b20c423b830c4a719c10a81853
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/__future__.py|5218|981d4c398849f9ebcab72300d9c1fe288fd6d7f28957b3b3fa3a493a5836d95c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/__hello__.py|227|a8ce70b199497950f0f06def93115a6814daf1f961934457f59046909901487f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/__phello__/__init__.py|97|56f7ed595e767c558ded05def14b682893105daf504500c3443b458ca2431bc6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/__phello__/spam.py|97|56f7ed595e767c558ded05def14b682893105daf504500c3443b458ca2431bc6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_aix_support.py|4021|0982f187c62fbfc1e8d368c8eb4104b56df71009a6b2823565a699e7b4cd945c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_collections_abc.py|32089|d4945c8410c4bab351741b04bca3de066f7c27ed7e38df89e206a96617102ffb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_compat_pickle.py|8761|12c8356a3d40bd0a336f13d7c6e2bed50d5c1a876563766a3175a6b328b5855e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_compression.py|5681|3ad5d60627477a60939ee44fc1bb3a05dbe8fb52f0f75039b8f5d8f1a278b981
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_markupbase.py|14653|cb14dd6f2e2439eb70b806cd49d19911363d424c2b6b9f4b73c9c08022d47030
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_osx_support.py|22023|363d3240acbba18a270bd3161f1ddb478f8492dc14fc451b2dc314db5c5ee09c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_py_abc.py|6189|f9c6fe3dd9b51bd7d93f867356e9d362600c924febfd903ee1c6e298860dca92
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_pydatetime.py|92087|a03268abe53ccab406fa29cdfcf75b89f7f485d9e6523e00c448ff7a9961dd26
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_pydecimal.py|227283|87a3372df4c4269adcdac5725e04675d306abcfa8d65e8dda59c1846e3d202ac
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_pyio.py|93593|22a2730be3230802593c75c930387e635809c6d82420e5234ef8d9cd1166ac8d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_pylong.py|10790|05da132ba902633430bf12b5007fa1983630de423e29402998e9edc349bdf591
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_sitebuiltins.py|3128|b9388bc1d6d12ed6be12da420ab1feca40f99c0e33ec315d92b1e01cb69b25bc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_strptime.py|28393|dcec0ad5efc41dd29fb125b477530ef22c70da117b59fa49cec39aae04e1f868
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_sysconfigdata__linux_x86_64-linux-gnu.py|50049|87c1d51a885981ab186b56daa0a331529b41fad4aa6b1638e4dd313c143d6e35
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_threading_local.py|7220|e1bf3dae66d0bfa63c8bb8a1d10c611203c35c636f7f5191fd56105788ef29cb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/_weakrefset.py|5893|91895a451d06e9f521a1171b31b9b19bc9740f35af00d4fa106338ab7167c9ac
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/abc.py|6538|e558702a95cdce3febd289da021715d2b92bc43995b8a1bc58dfa1c3d8010287
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/aifc.py|34211|e027e8a33567890ad7f84fea3be423cc0f6e49a33a31bbf279c2d0f64b6f8345
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/antigravity.py|500|8a5ee63e1b79ba2733e7ff4290b6eefea60e7f3a1ccb6bb519535aaf92b44967
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/argparse.py|101155|7cc582dcb3b76e2c957f78a3f74e9809d6c311d6aab7bcaa2c9954d0cbff5f30
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ast.py|64452|b515c23dbbc459329d3b802a3aac742cc456d7472e66f7ed6e9dc97e40596d7d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/__init__.py|1220|61102f2b5f8fb832f0558cb66391f227970b3dd34ea2a621455587b4295e89a1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/__main__.py|3491|c1e67c3b5f5d964029b407e71397d9d93d8b545abde482ffb0eab02dd16ad820
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/base_events.py|78567|53b71bbbd79e7fb2251460119afc379ebd71bbc599d9018313cc62ef218ae795
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/base_futures.py|1974|2f3798c4b82f5ac77647908b157c924f734f36871d98970e72849ea9a9a07856
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/base_subprocess.py|8869|d69ba8f97bf8c89564cadce49427574ddb98103a5db6f04b98798240332e7adf
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/base_tasks.py|2672|56efac65b63db927af336fa55eb5bda93c97a2defa4734ea8d695ed20fd6712a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/constants.py|1413|873fc2f9e66313c3c19c337269e704f204b59f9e91d6ecbec59f68335484d338
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/coroutines.py|3342|2feec17557c230a80cc2a6391bbb1c44b9f3341820b05667e36a4eb12b749436
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/events.py|29339|6a18b7eee5926622c146e61a7eb39726b4656e07ca41d36b06936ffb2354f0ed
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/exceptions.py|1752|a5971f88be14cd1417d59adf539ae48c5d818f95362a4e0eb00017e3690ab37b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/format_helpers.py|2404|6377b672b3f4ba8b6f0f7a5f0ea00cde24c8cddc0ca764e3329f302763477f59
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/futures.py|14340|f6daaf2a051fc61ea146811d7d4b4db1cac31d7f4777aa4d10617812d78bd943
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/locks.py|18995|5234295a0456e9a6ba2e80446848b602cd9195bca4fca2c711c6e3f41989cd86
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/log.py|124|80e4cc3ded4b138baba486519e7444801a23d6ac35f229d336a407a96af7e8d2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/mixins.py|481|8f4a3e16eca845ebfba422550cbcee7340ec8166d2bff6b750a8ed0de6b9ae3c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/proactor_events.py|33500|62d15e99315cae52e8548f487391ae6c46827bf8e5b4bcf3382c777a494a759b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/protocols.py|6957|1d1b49988c338b4ef06e30f9e92d9db2e00080c341f0a3f573bb8312deb8aff6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/queues.py|7974|8f020744ebd1f557dcb051a1530b504447660df906c2127a94bbcc8450ea7ef9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/runners.py|7230|739e0ecbb335cfec821a39f9e225583b5911bb6e3894ef93782005f852c54263
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/selector_events.py|48332|b77c4b8a85f1e1e2882a2bf3bd85a4b1c1fcfd7cb37ed0d8d8eb5f9a2ea44231
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/sslproto.py|31899|6c7fa1b81dc41850281cbf284c99ca18e824939fa5778860327040f3a80f6218
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/staggered.py|7077|3998d04fcff2c8052af03f3f34dbd3bd510b2dadddd5f2629a2c1cccbecd136d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/streams.py|27619|6ec5c70fd95b0d51cc1e81cd21e8abe8c1b69650148d6bb75ab4aa4797319bd4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/subprocess.py|7737|7b70605716334f63cc482123b2aaa3b7c5bb7138eeab63a037bd8068d43307c1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/taskgroups.py|9559|1d2bcd2da66524b45024841b94100cd6e7a7825a1b8f8ee125bf16b4ad0ca9bc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/tasks.py|37362|6f6aad82d597fea1800004075b9a2481604da0035f1143af1eb267823ec460e3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/threads.py|790|39d37295383641565f0c08bd992e2f661dc8051eb17e890b834fce96bde0910e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/timeouts.py|5321|3e40ca0dca3e54776579797837cd4936d73d04aae09fe0cf83ce1e5449d00163
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/transports.py|10722|940108bc133de399f38928cad3274f463096168d8a3ee5148f2478d3cb636f1c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/trsock.py|2475|c0eac37debcc51b702b808f6b7ed3e417343f5ff5f57125dad600a27eb082328
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/unix_events.py|53124|1fff06cce78763800f05f4d2bebfcdbc07ebf9564ca7e7222e0d91e39dee08c9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/windows_events.py|32587|163927e5834c10c6c106d81cf3cfd568fd1ced7fa34d857836447d3c4cc7a9d3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/asyncio/windows_utils.py|5060|e6fcffefa2521666bc2aed0f5caf8e862c1c1014ad12d2ab5fbce09c2df9c6f0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/base64.py|20635|8d1f608dbf030d11d6ec4df9e4c55b73fb68cdfbd9f53a7c91684a93b55564b5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/bdb.py|33573|171ba6b07dc5d3b9f718f3890fedc97e1fe750e39855f4342d71514169ccc29a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/bisect.py|3423|f1cf7b85fc36b5da249813fc5ab97d9464f8cc1bc817f7146206fa2713e35999
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/bz2.py|11847|76ab3252924e71e859d7d90e8d3db13b6554975cfcac0fdadced4de7f8779330
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/calendar.py|25864|0010004d32c694e4afa554db2434952040819c09c438e88d465dcf6d9fb63718
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/cgi.py|34479|a3fed254b9eb19e736b5c70da8056cadf6b276e57d0e95a0bae3793df38f3ee0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/cgitb.py|12421|08bbcca13a431551da73a2144c13f21e68cb79ac82223fbe5e60fcf89ce10f9c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/chunk.py|5500|4817eb94eeb8835c3325433f68f17e0ebbf7c96065ecf6aba3af7852f9a5314b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/cmd.py|14873|fb82a8c4e44e5b559c88d516d79051534cec69a463df97defe05ac8a261f0a0d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/code.py|10962|dab54e60985a3770782a7f031b6a80f91009c372465a09cdd1221b2ca03080eb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/codecs.py|36870|7b7839e53a77961153240aecfe11edc8054d05b1dedd83894450dae21ec05785
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/codeop.py|5908|3fb545862a1f9030c0d8f1ae6c72457d14a26d67a9b45de455e49900ff84a3a9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/collections/__init__.py|52378|7fdb04dd248ab37909f46d2085bfee56b32d7e91e49ad3a2fad99c453295659b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/collections/abc.py|119|9cb4208f99128a0489b6c8e6c61637617dd7d4250c59e065491957eda084dd10
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/colorsys.py|4062|65e3dfbf7bad61d4d7d7731a69dd7e75a347fd350d91327a51010a94e6fd2f1d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/compileall.py|20507|588f003bb5088ce380f3c335febaec1318811d275e5554b106655c4ceebabcfb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/concurrent/__init__.py|38|87ad5c8954dd56fbbca04517bf87477ff4dce575170c7dd1281d7ef1f4214ac8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/concurrent/futures/__init__.py|1583|9b597f6de7da771109ca7bf96a1af5ea4d5fda69b27b39312d34966d987f73cd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/concurrent/futures/_base.py|22833|8c6d5f09f7c535d40fa1c30ebfcb35e0601c2abf32286a82cf151af7ddf72473
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/concurrent/futures/process.py|35854|66b4fe880563a604ac4a094b72c6535b56b3bb8b14f4b6025705d53d28816fba
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/concurrent/futures/thread.py|8946|fe940a20adc4d3e66a8ea42a4c7e6c16957b011e8ada50c4e7a7bddbcbbffa0d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/config.c|8329|f9508b6b66f9157e02fd47267fe18dbc12ff7ba4ccf834cf0f1a36ca5efb9e0a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/config.c.in|1752|5c76ef60a799f420b09b047dc1087728e5ed08ba82f6c7664c4d4f1d1d715b21
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/install-sh|15358|3d7488bebd0cfc9b5c440c55d5b44f1c6e2e3d3e19894821bae4a27f9307f1d2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/Makefile|182584|9e349d6bbfc18bcf7fe1c2135cf32c6892f8f0798293d629ac1ab2a1a387ad4d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/makesetup|9312|0615264cbe9f3a4fce27de0054839ea814f2fe6f6091a0e17b18b5b15c665cfa
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/python-config.py|2100|2b10c2f47d035259835eab4c68c34b026184d52b548dbe6886911fa548648948
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/python.o|4444|4b7700d69e432077cdc7a7884f7d0f130464b50bd50c8cea0797e8180506a461
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/Setup|11525|17c83234ffe6302e7eaf62a363571fe6cc240b8b97bed7e503b85429fd10a5ca
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/Setup.bootstrap|902|2917936af36bd7d641c737f72f68599fd13c26a28faebba7c07799879b1b9b31
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/Setup.local|895|fe34a32f0a8f41ebc4d4631ad0f18b1e2f305f8bcf9910c012eef999bb748a47
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/config-3.12-x86_64-linux-gnu/Setup.stdlib|6318|7d9ba5ea3c511018e64ae070b7516edcb30ce05df884cae13f2b81ad41427234
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/configparser.py|54331|030e13cb6d44866812227640cd9746cf9a335254f715674112deae95e88f2645
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/contextlib.py|27637|8b7a477f978a8532852fd81e241c78182516bc4975d672d580a5848a76e11eb6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/contextvars.py|129|5ed260be8d1f4fe92261b7810b4bb1e8539c42093d7493f677d076e1a87f459a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/copy.py|8412|cbd25547933176fcf6bb05c2adc9f4796d15ac20b9b82dcf890daea7203daeab
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/copyreg.py|7614|c8eda41f05c6bf95a4da4726a530409d2485ae060b8d019b3a8034389a15d3e9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/cProfile.py|6556|c4c3edb84862431dffd6c044f5c02bb27f94e5b79a708bce195a7981efcb43bc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/crypt.py|3913|208df2ff33c19056345dcf5474abef1a58da799e2f3bab09d1d28b77ad3c623d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/csv.py|17132|2fd2a39ec59a5cbcd71596a93205001e593c65dc2ca3bef6028f148372028a88
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/__init__.py|18268|e048845f8f5c14a5fc873526a27da4a19d4eed25ab2f2a01fa6e0b79faca78d0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/_aix.py|12505|540e2821fa36981bde5c6ffb8f972474b06db4a37c1854c0e0e379b75d2b0fa3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/_endian.py|2535|c5d692bdce10dfee242752620061bab684633bc72445a3def484961ef1bdbf3a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/macholib/__init__.py|154|1e77c01eec8f167ed10b754f153c0c743c8e5196ae9c81dffc08f129ab56dbfd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/macholib/dyld.py|5024|eb8e7b17f1533bc3e86e23e8695f7a5e4b7a99ef1b1575d10af54f389161b655
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/macholib/dylib.py|960|f19ee056b18165cc6735efab0b4ca3508be9405b9646c38113316c15e8278a6f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/macholib/fetch_macholib|84|a9f6faacdb1aa00ac2f68043cd445171de9639a732b861bd5e64090a2865ab23
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/macholib/fetch_macholib.bat|75|7497fbdbb98afca4ac455e3a057c59bcdebaf1280e25c94741dc301f05cb53e5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/macholib/framework.py|1105|302439e40d9cbdd61b8b7cffd0b7e1278a6811b635044ee366a36e0d991f62da
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/macholib/README.ctypes|296|dc29d1da83b6a0a09a41647e4111eee878ed079c2d6b54a98fd6d8b88dd581f2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/util.py|13959|a54310b64a080b0103f3de5df86b21d884bc2985760f3596ab85d458eae8cba5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ctypes/wintypes.py|5629|5c4d9ba1a21683838ed1d1f007b6038304e42aacf34c576e820311d26cb243f3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/curses/__init__.py|3369|d8730e360dd00ec046bdd85cae41fe83c907c6ae3716a964158fce8f31ab28b0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/curses/ascii.py|2543|780dd8bbaf0ee7e832f164c1772953e694a9cd1031d1ab1471af65344d3645e6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/curses/has_key.py|5634|15a052812d9ae80124bb25b3f5b9ffae38e2b03073774e163abf3d773140cfb3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/curses/panel.py|87|13ef404a30da1825a612ca3e453db88c305d45deef4441c4c9e2ef7ee0ef50c7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/curses/textpad.py|7754|6fd91c3fd9f4a6f213979a2c1df6b737c49c95d9c3acf22cf40cfdb1f88fb737
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/dataclasses.py|62085|d242aea5fcf6408b1c1f622442f88f68b9526ce1f8bd2890d74a144677c427d9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/datetime.py|268|ef20dc6b3554cd585dddffdc573f1f9a7a54c522f2a3fb4576c44edbb1e14238
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/dbm/__init__.py|5882|389407b292f30c38a334599d2546ca1fea316b038a5252f985bbccfce6c8453b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/dbm/dumb.py|11594|c99202d9eb4e25a023715a1b804c886fdb7d9f957730959bb071a57d607443b5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/dbm/gnu.py|72|36cd4904f50e00c4df4ad9d450b3970e150957425f47c00cf979ba73eff49778
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/dbm/ndbm.py|70|1bcc2d9b2fad1901f3421a174eeecb5b8ccc6763283b87bbe0705b404c71904b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/decimal.py|2805|c3e37c55ef72b3dd6cb7b466a907b966467b6a9c58d85302193e64cbb5fd53d0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/difflib.py|83368|3eb2d371b4a171b063921de6bbf115108bc39de8bf72866315868ce2599213b7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/dis.py|30227|44c0b389c96124d8fb5cb0bc41c7a2aa7a6848ef4001b4000dcbd858efa4a1a2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/doctest.py|106749|8fb954ef7e775270461f1baf1331749cab6765a4006d0183cb8a0dfede1bbdc8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/__init__.py|1764|e4f46e3414c4602c9abb8b404a45e84412fc49dbe38a3d163f9575132dc7c93e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/_encoded_words.py|8541|4178321600c0a19ca04cfe8542ce44487f339d15d89a473b58cea63c0b230217
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/_header_value_parser.py|111685|fde2476258d76ae53259f377778cdacdbaca421c2424acada1ef5a94245892cb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/_parseaddr.py|17821|4308932872acbf4a674312a45a49b870e48026e3dfedc878ee2f512ddf2f30ba
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/_policybase.py|15535|284be073d7fe99d1021958e6dbeefe4c98a6c00021ea465d01aac71338d1579f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/architecture.rst|9561|f2b2ba7497fd02d13abcfc2a98099283a94b09e8b4f2c1c822ecacde3bec3eae
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/base64mime.py|3551|e2b4b87a5f42a8c5780e343f675513bbcc6abdd23fa14f8f1a7d4f7d72304770
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/charset.py|17063|a90653f13a4dc5eb3205079dda1d62561a8bf9a7b45585f5dbf90aa31a966680
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/contentmanager.py|10588|2d81026aef17e4786b15d9ec0629304987e3f275a0fd0a421a81b4ed87234b2c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/encoders.py|1778|690b275529788cc48e8f541a2aef321dc31e92f75764ac7924896db72d8a9555
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/errors.py|3814|dbfb4bbfc85e9d556d3385dc6356518846d8a122bc643b171ea61b6e8dc42c8b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/feedparser.py|22796|6046239fcdd6977d1c25841581cabedaeec8046cc5fedcb8ff2d6450a36442bd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/generator.py|21403|1cf088e6632b61b7c428caa8b5007b18e405fba68055716a11bd3ceb55c0d4c7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/header.py|24092|4d9baa908ad5288dd8fad8cf20b3802ffac77ba1642727804a633b201c56e5ca
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/headerregistry.py|20819|fada56c25b6a457c6a62af43f9f929bbc29424103ce65f40f114adb4fdf3d39f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/iterators.py|2129|1080a2d03779176d6d45f6ecd976dbe69f5579f7e4e83b75224c3f92fd258102
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/message.py|48396|ba32efea2602ea52e73028a2817afddccccacc4385b9800896556d5c22db2b90
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/__init__.py|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/application.py|1321|b82a944ccba03e7e7eec46232e50ffe4ce2c32f4b0e26662e6bde30d533584ae
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/audio.py|3094|856263b25a3384a7450a1a0b9869fb897b84f893b2e7147c7e045ae50d132cd3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/base.py|914|9a7b36653b5657525a0aeeaa72d4a0b09f598e6edc29c139c2dc2612b7d29fb8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/image.py|3726|460be5b50cfcaab8e72a73f24f14ab062cedf1a40a775b8b0d80c13aed44bb5e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/message.py|1315|30fccea73b874b5ddaccbd3c64936833749ff039f08d40524c1b0b25b8e8e2b8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/multipart.py|1619|8bf2beca6de95d66f12968380a428d3bb0a28a8a6ea2078da521511e1ed80a38
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/nonmultipart.py|689|4eb9ad32603d66fc9d55aebcc4d3cf759edd9e95a591d38690659afb2e57b050
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/mime/text.py|1394|71c56a41675a36801259c9946f7b7bf838e6c29c453ba8c34d89401f2b972d6c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/parser.py|4975|88890ea9994c55ff7d6c1fd570fece2785f51ed407ee95df4aff946e250bcd66
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/policy.py|10614|35fcbece24fac56fdefe15c93351eefda47c3440204746b8519e71d4633b0f3e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/quoprimime.py|9864|77b454bd3ba3b5e3776be28ae3a0fd8de5d1e50d5b8ee10dd539c37c2bd68082
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/email/utils.py|16071|65d259aded3b7d29609d320decdb59cb0a0f7f0e5c453e1d3c380e8a4a5d61c9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/__init__.py|5884|78c4744d407690f321565488710b5aaf6486b5afa8d185637aa1e7633ab59cd8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/aliases.py|15677|6fdcc49ba23a0203ae6cf28e608f8e6297d7c4d77d52e651db3cb49b9564c6d2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/ascii.py|1248|578aa1173f7cc60dad2895071287fe6182bd14787b3fbf47a6c7983dfe3675e3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/base64_codec.py|1533|cf9ac7a464f541492486241d1b4bf33e37b45c6499275cc4d69c5a8e564e5976
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/big5.py|1019|98fac6f86a20dd05da197e2058176ebfd47edee7074c3248f5f48fe0fb672d7c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/big5hkscs.py|1039|21d051a00fb5c6a86ba187e0c50e811d659ce00991fd5f5b408f71ebb2ef0f16
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/bz2_codec.py|2249|1181a2a89102a2b1d2b2f1f4473236d5d1ececdd0be8fdaa498a3dbe21a185ab
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/charmap.py|2084|1b8b5fdb36ce3becc62a6115ed904a17083949ec8aaef5a80f7078cec232f43b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp037.py|13121|fda6ca994d710e4e0c760e0204c29a4273fc0f14ebe3169306d2eb54c9953f58
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1006.py|13568|eaded38b427841bdf280e878f1e26da506e743eaa9429075332af60cce429473
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1026.py|13113|f5227237dd7ce5005b16a8e4d8342f0d193193c878e3cf35b9305d22b3b1aaf9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1125.py|34597|f84c7d30ce222e6a50cff1a4c9737173411da108cbd2c9bb57c854480103c470
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1140.py|13105|3379d78b244aa905ffe1171a968caaf41b9a0154d1ddc76c05a2abaca2b289fd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1250.py|13686|ebcec1adf9167863fb0bab29708c546300c80a77ef07838c9e0437a59e265970
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1251.py|13361|d57f8cfa34494c5acb6692ddb31f616ae2dd89a075d2af6d36b0b7ec2ffe7af1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1252.py|13511|19aa5bee667f5fb387924a813aec9fa1dda47769d09e8483a748bdb202be6a84
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1253.py|13094|8c27696dcfb6894b378869bc89f113703fbd1e9b13a83934463d5999b055d1e8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1254.py|13502|06517ec2f74f1c6562d0a1a500c48ba43f2e6e9d0c3d28356d747f274f1a4c8d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1255.py|12466|54a1b5087578fa78e5bdd0afa6a9e80e8c5467c1e4226cf6e586cfe7a674a653
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1256.py|12814|ad3768ac2fef2a646b3301c20af705f4d4a1544f22fa8a84241bada27ab84133
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1257.py|13374|d9149d2925b3f719809ef2297e541461079f15c658af207a3e498be314ab2c6b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp1258.py|13364|672e05b51952a82c8dbd5603769195fcedf565e457bb86c0d5bae04955d04630
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp273.py|14132|6c6aec3b213ea3aebc2c526dd4d121c95d4a25a2fc928a87cd80f8448988185f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp424.py|12055|30414c2186ea0802bbf3db034122ddec1f8a10061b97c50871e14b74ee36d0ca
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp437.py|34564|5c2a5015cd36cf7f561269f33dec4c323093d3d88b0673969accdabdcb9ce2cb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp500.py|13121|630f503f9110d98ea3e1529f2f965ebc275a2f78d3de47f8e9b69d35589d764b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp720.py|13686|395496001271b92efe5df07fc0ae7c3410d1dd2bdfebbd3e4d8e806c8166beb0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp737.py|34681|be3ca1785a3970ec62310710eaf7de82932181b04d06fe4528f8adaba9fb8c4b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp775.py|34476|e0dba85b99329d7f16907e620adada06be5216abcb964406c827b569b2cf1aeb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp850.py|34105|257e29f235e2a8790dd68cee45668776648bab809ce8584f893cdd8fd007993c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp852.py|35002|cc6faaa9dc4a933127da0aaacd1dc7a44c09266051af56bfe3215ff228636b6b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp855.py|33850|7b25c61c9e8c47b218d3fbb801541a2861926ac712843d2113fff90e2074f5ba
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp856.py|12423|2e52ec5cb1eafa6739b5569b0b98ee89df5f7358b84ccdc8da64e86f017d359f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp857.py|33908|8d1b769058bfccdb3c6c70c49a104f5081a2fcc9fad68f7b5eb3e4f67f0b33da
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp858.py|34015|a24930c4a6ad0ff66dde9a69f2027e4b92c2c9c61dcda2992e940654c606577b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp860.py|34681|2dfae7e31d3d9aa3013cff44a4d7ad842f257ac63765a9998436701b629cd86a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp861.py|34633|701930d77a2177497586e99bc3fe60f2d4beffb645608f167c76874a72ff405e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp862.py|33370|15a2844b6ed9544c6400cf7299b42d0c2bef93c9bee70a9e89f66b8610ad6d6d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp863.py|34252|a3d57f61fce1b98fc81ea8e4ebebaf402fae40bbcdd35d4b8297b9bb49a79aa2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp864.py|33663|15ad8f1fdfdd842c7522241372e7eddda7df687e815692a89157c5f256f21a08
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp865.py|34618|bdbaded987242ed2a8de7133ec2f61ddcc1c2e9de27816ab7cd0a4c678a3a907
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp866.py|34396|9efcc8e85bbd1687272a0991f6d0429a4c06679db2d114b2ac95db27a70f9d13
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp869.py|32965|52582d9fb769b24eac7154f18d7dae856588297d6da98f37fb5efd8da883826d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp874.py|12595|fe4752fa2e65741e08a563a31ff914fe71068942ce9c6f4070b1dfd7b25e5e7f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp875.py|12854|2fe72632015db2cba2bb4367055551da6fe22051b96d170c7b96fa271c46b257
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp932.py|1023|99748e28113d2d49f5d666b49b78accd2c6e10a7852f7dd6dece9b5b71aa83c4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp949.py|1023|950a7d29467ce0590b4a1137830d43d88d8f20e4035dcaaa8b2a5c3c3f1de962
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/cp950.py|1023|27811178b450731fc955b1247656a605d04e5ee98e0d585e4596b94b703a27f6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/euc_jis_2004.py|1051|9fa426cd9f17629f6320700ed18baa94839304cf1bcabbee7edb501747dc055d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/euc_jisx0213.py|1051|e28315910da20218dae8b7d5becd81de1e283dfd8b0415a4980d67065de73a0b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/euc_jp.py|1027|b453a439787b0efa031e43416a7d852a6be705c985e1200693eb96d87ea79cdc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/euc_kr.py|1027|633a1a5504bfad04b1ec9c96d44d4ebb3bb99066a218318e7d67d866e20887a6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/gb18030.py|1031|6c10b4dc49bc63724e539137ede6936304fcca1c97c28d16d89f381e10849521
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/gb2312.py|1027|3d2d567d8d079b78f3f3b566ed52ad2f38af61bf832b7dc28858b0039a032d6b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/gbk.py|1015|eff9b8cbc9ad2ef2e10e96afa83d3db1f775ea044aed275b7a35574ae0d8645b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/hex_codec.py|1508|fc5f0a31b59efe990b86efb98936769f33dd91d912ce55b49a5a4cfc516cd047
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/hp_roman8.py|13475|c43cce763d12e8f71a63dbc16641bd87147eaf5f9d9054ea856864b216b2735b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/hz.py|1011|025a9531e3046e52d3e039c0be04f9a5a74651d7683a13c7c7ebd4c7dfb5996a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/idna.py|9710|9ca58e82d12b171f25d57239ad237dae5c44214a70f2f4f39358c2759b8b9013
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso2022_jp.py|1053|461a0e7f72eccb8b29f351c4e7926cfbda58e0edd6d0770bd82e0b36c5febe77
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso2022_jp_1.py|1061|63bacad13a979a5519fcaa4f1e1e07b2c7415005167fac3a689408c7d886fabd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso2022_jp_2.py|1061|5d4248181548b0fc89a9f5ee9cf52ebecb235708ba87d47896ad14130884ef9f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso2022_jp_2004.py|1073|b4d1468bcd608b46f38cb0c6ef115510dcf9aa0f71e590792f407efc6e165164
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso2022_jp_3.py|1061|3aceaa5661909de14e2861d864443b8472460ce39b99cce5c6965346d47aa5ac
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso2022_jp_ext.py|1069|f4c9ed8f3031995faa224bcb10153d2b6144944477d1f27d1a6cc4a879fac34c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso2022_kr.py|1053|1c86362e17944f0bcf68db02f4995bdeea605867795fff7ab4079073f96705e4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_1.py|13176|b5cebd515e057d670bf54e10b8a6f162ef3daa7f21b146aee3249160caf3c32d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_10.py|13589|54c886b41819ebb7f4fb34b8dbae1c45f4fc0864f019ecd772676ccfac5fae7b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_11.py|12335|ed5a964470a241b4da7a6cfb718e4149d09644933af38f0497602baab6e563ef
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_13.py|13271|7312237e8e5d201d920b4130f057cfdf1b0be9baafaa246826e6d93204fcc206
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_14.py|13652|82778b995a0ee87c5f1180fcc52900359eee15bd9a6e3a0e25f0d963e0b2a343
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_15.py|13212|01976a81811873dc9a0c79db9fc00d1c30103487f3c6bc3a6d81b4043cd48e02
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_16.py|13557|b5ac8f5a5d8f84c0f903b2b7c342184758d590d8bcf810d561f942fe5b372d66
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_2.py|13404|2b57cab6111cae9021505e3ae1b2adbbfc344ec48165fda322f6b069fbb18adc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_3.py|13089|4ffdf89004bf0c5230caa7079f7ca3142fc112f8b923ddb2c7358369d2d3c242
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_4.py|13376|87bd130daa0eaef3e4cb465e10cffb2bcd194ff74097e0c186b4b8eb7be41ac5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_5.py|13015|9961d96cc7b9fdf011ebcaaeaeca7b50b8670fadbd7b75fde66192f8c1f68f30
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_6.py|10833|4840e68014346517680f593ca22f67133c39ba7e46f34b9be62c980a728448c6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_7.py|12844|b352eca3b819488f64fb3338fd93f39c1e30f32bb13f2f9c577925e58f2960e4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_8.py|11036|4cf9e8a8bbe04accb1c1a80853efb19ae0772d18f81e270adefc1b2386cb368e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/iso8859_9.py|13156|84d9b15263e81685f7513c5ab45caf80b2f73c301c68e659f7162c1b1882d359
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/johab.py|1023|9586615917afd3d848c1c4328656603b2834af6115f2aec932fccc935e1a60fb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/koi8_r.py|13779|4d4e353aee8039bb71e2145a6e68fe1e6833a1b4250b70ee0ac5ec70bbb8c51d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/koi8_t.py|13193|9c9043814abdbe7dc39ff98f3857d5d110a84c978ad2304158d810a4e9eacef1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/koi8_u.py|13762|d449f9858e357fa8c2edbd4b9fe739337e9f201cac3ded20f99bfcecd4970ff7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/kz1048.py|13723|76beb30e98a911f72f97609a2373782573c17c88a5fb3537db338aa382979ffc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/latin_1.py|1264|b75503e532a27c636477396c855209ff5f3036536d2a4bede0a576c89382b60c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_arabic.py|36467|5eafd9a3136abfbd8ed52df9c90203c7a283e7429ed60502a87a02511e0fb777
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_croatian.py|13633|a880cd05c82a8d11a29c65ee86a396def3344465dd71441b0bb4a73826024953
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_cyrillic.py|13454|83616786a1c6308b03a0dc82536908d24d0974b2248d67393d613fe558cea4bd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_farsi.py|15170|f5763c38fb4ab0423fafe2fdca34d6f9932ac7f1a74c0cd8109d60234c7dc624
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_greek.py|13721|63016a323ddf98cb3aa9cfa78f3bab4768bedbfe9a5262a36a5aecb13d291f6e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_iceland.py|13498|753cc1ac635caa7e1b4630fbcebef8db8db332c098154a5b11f652912bf64f37
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_latin2.py|14118|31670da18ce8b5394cd53fe6bf216268e7e8eae4c0247532e420e2e103727d50
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_roman.py|13480|230367d96aef8e8d7f185b4acfb84923714f39ddbcbf9cf38a06bf6f5d621c22
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_romanian.py|13661|49630cf035c19e896a123ed6e5fee18b5e485123daf2f15da38bf727ff387bee
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mac_turkish.py|13513|99758a5cad2825cb3be3fa5d031e0821e4eba910a46f417fd890207b9b6be77b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/mbcs.py|1211|f6ed445ed537c9f856d8defe8b56505727737d0dc9348d0a877abedab4bdd864
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/oem.py|1019|481656d3a35f792d0e5109e3f821e6dbfcf097163a19b0cdfcbff3b3db99292f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/palmos.py|13519|eccf7418adefcc2a59e9a07fc4e34363bd62f7e878d48c8a02730a8ed1c584c8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/ptcp154.py|14015|0eabcb2c287d335e86b71b0abe5718bd6ddc9aaee234f0f0f2363845d2926d8d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/punycode.py|6883|34edc8fb1c50e4d1cbaa1e008bb491cd7c12116c316e51974f333fe7b628eb7c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/quopri_codec.py|1525|502a213c34c05a94ed063ee03f47680bd6efbb35036e06fb4dc809bf398cfa64
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/raw_unicode_escape.py|1332|fa6328486b8f5a5cbd10e377e80adb8cf94acbbe19c38b4e1bf708d831a80a3a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/rot_13.py|2448|14767f475acdc0bf48e6272280dd15b80efaecafb93c06be21136f83dd1ee7e4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/shift_jis.py|1039|ad4ac50ebf58294304e412cc0f1b12980988dd6edc414e4110029c0a1abbe966
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/shift_jis_2004.py|1059|d21c5930f21063ea78fea3b0f76dfb8fd92858d2a4a200064a52126a43dd1a99
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/shift_jisx0213.py|1059|2c8d0b93bb36edf31c1236b1b4d1c0008553868bd2fc9137570115b96b834f2e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/tis_620.py|12300|647c4719e2c1a7375105e15a89b377c66f6b699977dcabbb71d923a4607b7902
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/undefined.py|1299|85bba5c5e1007cd8c1ade5c0214bcc825396d2bbd02054e62a9f162104748b64
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/unicode_escape.py|1304|507e7ca8f18df639fd823d7cc23ce4028a3550ceefdfa40b3c76f81d1a94531d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_16.py|5236|6c36257f7b8d214473560d195e71bccef0c69a53e1e52d2800b7a7890aad7e58
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_16_be.py|1037|3357196f3fa52433326a6626880e34964e00c5570aee50e9a0a0a7c6d86f6e4f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_16_le.py|1037|3aedaf3eb49769282daef1eaedfd4fa1c31fe5eebeff67fe2307c89dc2e2fd80
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_32.py|5129|2072eece5f6026ad2d3549ab193a9e38894ea15ca9d5b3cd408fd6b116acc0c2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_32_be.py|930|cbba20e1f6d0879c7c4293446c371a9f79e7c90bf3c78a77a9b8fc72b18915dd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_32_le.py|930|9134b91047d85b442898d59effe23e7e0cf4167ca341ae31119a731dbf880a7b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_7.py|946|9ff32314f4f1fa074f206bbf7fdb851504e5313128636d73b4bf75b886e4a87d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_8.py|1005|ba0cac060269583523ca9506473a755203037c57d466a11aa89a30a5f6756f3d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/utf_8_sig.py|4133|1ef3da8d8aa08149e7f274dc64dbfce2155da812e5258ca8e8f832428d3b5c2d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/uu_codec.py|2851|45ba92000718abf85f158563c755205e100356ce1b4ab9444b4d0a3d21f061a3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/encodings/zlib_codec.py|2204|6ef01e8d3a5fe1cc52f7b5ae008df12f1dbce7304111bf8d4758f1bfc0115759
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/enum.py|81540|f35e542d8c4c1d2b5e910138d726fa48774925f3c4dc5462793ebcb66aa55501
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/filecmp.py|10381|803d8494d5ae72f986f3dedaa30360fcc4467f9cb7b3106cf0d434d87a033d60
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/fileinput.py|15714|b0cd2a3f01c96f594b6038e52bd83d489bfa081cc757103c70aab4e5b2c4fe1f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/fnmatch.py|5999|6683da36e47af523f3f41e18ad244d837783e19e98911cc0b7415dea81494ebc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/fractions.py|38147|d52d1ab9d5be26924e4914a5e40069c992bbfa68f773694c2e5ee8452d0766a0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ftplib.py|35240|fb32563e0157d25e1a4b72cdbb5607893014d1accc2dbb986b2e3a61aebfe26e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/functools.py|37940|de4a1d37c795e2a065124b5c49357893433bc6bb111b41277ccc9930ef08d4c9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/genericpath.py|5572|2b0b35d2206778af4081cf81dd9b513876e72c35a55bec941402e1fa62b1f1aa
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/getopt.py|7488|0ce875700c8798193b8e2748f7a27fc542cc4d525a1e6fc403767450ec92be99
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/getpass.py|5990|e74fd445337ff503223dd8aa4bdd7d04917067d00c796a10bedb7a1381a4960a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/gettext.py|21320|a5c249a522b6b8e3aa6f1b12a8bcc09508b99ad612b58d2fc973db27ea3b7cc3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/glob.py|8732|c9e5f9ae0752660ede63328a456f58f87c29500b31f58c1b813458b00fceb6d5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/graphlib.py|9648|2a29e0adee584dc76251afef1236d7bedf250aca27911f91a4d442133ce81117
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/gzip.py|25402|ea6e194b9df26398bf0d5215e63320c7b9d801b2d8b723fb9c80619df48076e9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/hashlib.py|9349|6dbdebf270868b391080e21dc9687eddfaf321c965ad979f68d3f5c423c613ab
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/heapq.py|23024|6d43277e5c76fc0f073cd388fcff852d14d068f6bb6d4886c340f8b75a1229a9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/hmac.py|7716|7facd1330e5487ed995eda5c8619df0d3e32f69cb619f97662372fb76325746e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/html/__init__.py|4775|923d82d821e75e8d235392c10c145ab8587927b3faf9c952bbd48081eebd8522
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/html/entities.py|75512|d9c65fb2828dbc1f3e399058a341d51e9375ec5bca95a8e92599c41bd5b78bde
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/html/parser.py|22048|a4c5558209ffe6d677dbe18e4a4b2d34672c73aee46e39b1d118846afa62a9ff
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/http/__init__.py|8308|17f4f6832cfc84b5b9600414bab80b77e67ccb611bdfed10a3f2beca9d0d568b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/http/client.py|59574|c2c0694155837d72fc710a4138e5d1e53ae1a652b117a2e23a5b1b0db527a0f9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/http/cookiejar.py|77438|2a64dbc46edd0173600f32d195531741de562522da28bc76c2f97dccceb37ddb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/http/cookies.py|21568|6387f676095ae5374943eff99fbcd2d9c681172c00209fadf54c311cf7228149
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/http/server.py|49202|12f8db637047c12ec053bfaa6671ad1cb7ca9ca8d1dae82b562e5866c5b02990
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/__init__.py|396|3f8058df4fec56eb20ff67ff84c86fd3d9697e2384c5a290ed696f6d3187aa45
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/__main__.py|107|26699e80e7e8ba278a649881b80e8c7301c729d04d2f8fb2268365b10a48a91e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/autocomplete.py|9354|0d36f7694a50cbaa22d9bf03b91fa0658a147bd90dd867714a9b411febb36427
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/autocomplete_w.py|20863|91170b060749d0b3c8f2ab31499104028bedf971e5575155d43392d5c8dae5d6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/autoexpand.py|3216|c8eb28ef7addf5a664a7e3addfbfebe29040a8695e1db515828305aacba2ee4e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/browser.py|8588|b607102a6e2ff7de241744008144a5480e2925098694be2a46003d8f60da0f52
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/calltip.py|7267|3a723fdf88c0018dfadd19757142a643b01b785c6df17a50bbe21463663ab590
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/calltip_w.py|7083|077e9d0d95946296077d5c95f343e242a7d250a6efece4afc58759b5e984e6c3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/ChangeLog|56360|b7f42699e5e5a7c82ebdf2a2962946b7228c933ece0ea7c0d7789f21a7dd7e64
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/codecontext.py|11420|628a13325b3bf2f76dea9254b20178b3232261f83c660f0e33785e6215dd6492
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/colorizer.py|14783|4de77a632286cf7cb616a2cf50dcd16a99d452fe7b16bf94c34950be97f293c2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/config-extensions.def|2266|e75df0b77ff61253be457af636d5eb7c55a3ff2b6a733beea844d2b294972ebf
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/config-highlight.def|2864|609eada44ff4aa9d5cd10ad8b4c29bb76db8ebc74912a0ae86f5ea3cd19b7547
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/config-keys.def|10910|bee81ba5c5abec1e35e313268f8d8fe72d305d0ad73abfba3d2ea1e2b2308710
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/config-main.def|3168|e783704ad5cd9b3f44c026f55c98be2c52190bf9b7832251283f3e953ba80f87
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/config.py|38403|c1e1557b1fa2a161d42f6231ee36ef090b07bffe58839b3c58f008e39d4fa856
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/config_key.py|15230|856bd4b2c1fd7275856d3869cad8975f7770edbf021a93c64816a41c2322c2fa
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/configdialog.py|105310|eaf4a08fbd3a8b92fd77a6c3cd5be824c570b38340c3a9afe4f36580320a3d48
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/CREDITS.txt|2148|4fca8182cab71d43991f3d9370a5a9df1389dab5626c19e0e0f1510a0dd84852
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/debugger.py|20991|6e595d5a388e46b6b6e24490e970a3d355ec116a16a064bfca6ed86d4b17dcb4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/debugger_r.py|12115|ddc797740231f068ca7c7c8610e799d72ad11af670d9bc0b6f9e04fe2ba222d1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/debugobj.py|4177|aae9e2468a3d05366480864dc56689c65896757faf3b0364b8eef9feb4876a43
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/debugobj_r.py|1082|4e583b43fdf9bd4a731d70e074ee597aba03f3c8c36302bdc7e74650fb1fcc11
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/delegator.py|1044|c2b31919d27056fc3aaa8f4ef798fbdf162665175fa9216d665f58ba2e4a464d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/dynoption.py|1993|29933f56722b2efb5cf451825a7fe50f357983e68f6a261afdf89b52f778e488
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/editor.py|69561|c564a1d52a311436e1242b959d1553599b3744d6ff7da1bf5dec28613bdae260
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/extend.txt|3632|4b2c5af0c4f8e67f875b9f6a5a957b84a7b8732b73678953be4825232813a608
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/filelist.py|3871|64e194e4514141414ecb231ac165ed861749bb0d31d0758c7c3a823ce154abe1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/format.py|15777|dc2b00fb239f38543bf973d94daef2c52457b905d4d89c640993823127b7923c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/grep.py|7521|f30014ca750f79c7742bbe9d363368a6fa8b484112dc5a1450f858792a1d2fb1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/help.html|60566|a60a5a7dca96fdf993126b74ed36b7f5dd5de81990600fbcd18ae2a67712c9e4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/help.py|11843|78e392dc7543838cd72e68baf51c0da2fe51669a381d04cd1304b927404155f5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/help_about.py|9023|2f89f495a3ed95143ce74ba380fe34f779daf4598fec4c775c46cb43745a4fef
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/history.py|4065|f91f1568d083bdbc856d38ef48493bcb138c6a492d523385b300a5bac30133e6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/HISTORY.txt|10313|12a6e0d745e08d55616e65a91f26e3bf9585ca64b8cec04a1daf865e855b655d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/hyperparser.py|12889|18563d2b4c248aed70b7f29fd903fd51d1b5aceb3dc93c23f9a54141eed7a9b0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/folder.gif|120|7c98d566a13fd599d1c11a375f387fef69b6c595c4f18c5d88c188a860be0e55
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle.ico|57746|7f13eeb5dca39d05e24b9eb069c6dcb2748633822d67288a8bf8b7e21cdddf55
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle_16.gif|634|fe3af292b38660a8a58b1a8b4fa4240aa190602e7e9a700ea0536b3181fc968e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle_16.png|1031|78fb3fb0ec11f61bc6cf0947f3c3923aa18e1c6513684058ed0fa01ac858143e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle_256.png|39205|3f517467d12e0e3ecf20f9bd68ce4bd18a2b8088f32308fd978fd80e87d3628b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle_32.gif|1019|fe70991cfccd1267922e94d91e02e9a58d2d29fd3382a2f4975280b9023cb7b9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle_32.png|2036|797cd05f1964d57c4c6c248ac7f7ea6a38019ada32a9ab7e6c28d060f87b03de
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle_48.gif|1388|37484901eb40eefa846308e1da3ff6f240ea98f769a2afc3cf4fdba00327ecbe
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/idle_48.png|3977|a09f433197c8870b12bb7859cc4c3fe2068908cb1ddbd4880ab0f6fee91b6c23
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/minusnode.gif|75|efa5aa1d1e3439ab85425bd2aa3a25b9e6c21309e672690cfb32219e1eb7a7f3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/openfolder.gif|125|9a59e2abf1840156e9db8f85a38822fd56ab79a139eb95ec86f1fba1bb87326b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/plusnode.gif|78|6ace9e90a2bcb16d06c4d78837137f2c14bc26b3bd9f24b7b6afeadb689bdafb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/python.gif|380|158c31382f8e5b41fded0c2aa9cc66a382928b003cdd8b5b0518836ad9c89377
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/README.txt|1935|3feadfa48fb8e9025fccc91bff9ac494519137ed4a7d9b8f4e6847165b43de4e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/Icons/tk.gif|72|7f16cb2e322891dbd9101302c09ffda0c2a3a72d053bb8c0927d507414c59cad
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/idle.bat|177|15a3977f0d2c6a8e87db2ef7050ea10afb3a88b064bf5ef95439924e42464114
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/idle.py|454|33ffa2f718e123fd1c4e536bb4a471978515787ee9fbf7806a92073a787a733a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/idle.pyw|570|26101d297127132c5e9634499f41ad00e125ea308343a20b278bee9e9225eb5c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/iomenu.py|16159|7004f1ab2cfa5994e453f426507170ec37c1c4a5b9837ba319e5eaebf1a29c34
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/macosx.py|9290|e6c687754bb60cd1015a413073b4d85b5e5bc7993c1acbfbc92d70600a83132e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/mainmenu.py|3938|092fad4454f593d7bf2e5e1e746acade92bb346d06476ba527f162f843ae3208
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/multicall.py|18652|efb7d9bddcae17fab2108cb714c240c82d1368087b6d2b91e02ec224ddebce12
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/NEWS2x.txt|27172|c89a3b513501ebace8e428aea68dce39d0af9f29196e08fc9ea49c99605e79e7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/News3.txt|56500|608bda1a7d2c95b3898328e7749725fd6c17d3039a9bab5b51de0bc70fca1200
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/outwin.py|5705|a24f67d1ebe5e1dce84de0009d0caefaa1c795280507e1b0b7f0ea63d2ea68b4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/parenmatch.py|7204|f122e13c385a135cbbbe8b1d87efeed43ddd3e0be9ddd8aa24b267b61fac4287
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/pathbrowser.py|3093|42a4e008922c991049f1b42ca18700b65f2f8d0ab6dd12cc22671771e90c2065
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/percolator.py|3568|42fe72c167eb3a2795cbe64c498d7cbe1de05132be29a99a58226ae83efb31d4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/pyparse.py|19864|21c6bf43370998d5a5a6670f7b13409335e9a2c1a350ed586bbe63be5f226648
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/pyshell.py|62194|a99a92f60190271720a5e3109126c937c435c6f181438038b97b20330f0b8c0b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/query.py|15067|faea5edd6b8693e6a32107054ad0de3be4d28e6aacb7792f86cbbe146131373b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/README.txt|11653|4f2dc8ffdbfc7837b60edc32ac2f593a220f4abf0ea00cc477382ad8ecf8eb3d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/redirector.py|6777|7911a7534eb0c73ee3e2464c5f8498109653f73ebed8fa903780c5fd7ca00754
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/replace.py|9841|ea13db39aa89df369b36200c7301874a5636403e8270b1862f946e2fff081b84
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/rpc.py|21078|8d0cb6e11c8dcc5dbda89b9a582bfaa74fe2b661dde442b02eb61b8fc47d9eb3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/run.py|21654|49a87a54dda2a595720d90f93a70045ac017f2dc826e578e2d2bb5360739db8e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/runscript.py|8273|b92740fddc7b1d603b1736a135bd15518081f20c0db1e1a779cab715ee9120fe
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/scrolledlist.py|4478|25b0ad247977f6079226052e2b76dd4c127bf50f2f5e8ffbd1fe10bc631bfca9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/search.py|5567|c53ff4d4814d97d0d95b7e15030d3ae8c732366ed84c2b300183e933270df724
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/searchbase.py|7852|d6db91e0d9aa869289f11677bcad7184be70fdb942d37b341cd9de6643f82f87
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/searchengine.py|7415|11b0c8df926e4f6bd2e26d0264b2d902c41bcc70d68a4a830df1ea2da2c2a6cc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/sidebar.py|20338|760f14ebb0312adb289cda0562c9eff70982a0acde5d9d9d0b591390cd4a581e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/squeezer.py|12834|112221334fee94a88cba2ca7ac455e1bd6ab796397cbe036b1e8a98bc0787e30
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/stackviewer.py|4016|ee053a65298e2ec2f4628d8269a33362816271fd81fab4e550a621493c26a76f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/statusbar.py|1474|3f4dc0f27b0c23e488d022abe8461529ce8a1b4eaf9dbfd97123ef2c502f684e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/textview.py|6808|eace58159e9636bb1456885c21f5ed474e203090139e5dd3457ac72ad5552006
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/TODO.txt|8477|97a1d6cafad64ba55456ea99b46ebb3a1ef6af4babee8f3cc8877084c2e772d0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/tooltip.py|6665|f2779d85a9a1ddf302364e9087ceacf270938f24f3c13f3332a1bdda0414d296
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/tree.py|16773|eaa604df6184f7efc90edf4cd725db718508898d87c17699fe812690c09d9093
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/undo.py|11016|291fda98995bb4688fbe05fd3fa689e21aade3627c4c16e8971ed353f6cc3107
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/util.py|1312|91cfc9e882b1b67a166a8a98a139904c40d6d62efad754b9b344f91cf82e1495
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/window.py|2616|ca31d8c01c9b468fcad0a4e529c8e205c1e4ecf30520545db654d466bd7158bd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/zoomheight.py|4203|5f6ff83cb0df3ee5e7d997ffe23efb341b994bfbaf00b79a4832d54231a095dd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/idlelib/zzdummy.py|2005|5e248f0ea4f35052d23bb2c43564aa567b8cebaf91fd63ba0be8fef2f4167945
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/imaplib.py|54040|ab3d485f7ee89deaf132533cd135888326be3c92a88ede79a16fa4c0e4709632
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/imghdr.py|4398|c1bb52ea0816db4c5f3420655ab4a476fb3829709141e91f1a56b9c6fe286d56
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/__init__.py|4784|d540b5ac137fcb3e26a8d5f2939649e34373c6685f98a30a9f682cf231be5854
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/_abc.py|1354|80aab7931dc999dee581c8b8b56fcd973fe156335a96ceeaf6acfc03cebf10e8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/_bootstrap.py|57057|d112d54b7831cf4a818d4841d5ff8003b54df220a6dabafa61f67d7c7a5603f7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/_bootstrap_external.py|69428|e6ad72f3f0f9b65c99ab52598cd02ab748511dcdce1dd51f18dace9be9a680c6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/abc.py|7612|5f9cb36ca1bce9d5df00bc8d4d7f46b7ea2353dfa99292ad7f099affddfb5d03
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/machinery.py|880|d045cd7ecf2a12b6ecbfbef79eb114e87ef2ebd756f5b705f73e6f3266e3dede
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/metadata/__init__.py|28757|1a26dfee8cb302b729501e944626f77e2cbcc4675038f3d18c2d8534751b3e8b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/metadata/_adapters.py|2406|de9a880abc4513af1b69ce150cd5a5093201c39131717cdc2ba6b19f4364c163
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/metadata/_collections.py|743|089d0e4c21c88d6034648552e2fa0e440b27d91e11d9c40112d3ec6442690126
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/metadata/_functools.py|2895|3ec636fb8aeb297e1155e442d681a9d65075a660bd78a37cf3f7fe6c3f6e3a80
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/metadata/_itertools.py|2068|72faffdaff0145bc5c225e71e6575fa9d1e3848f188bcb3cca4e741bf9e6ea34
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/metadata/_meta.py|1590|bd3504040497cd049e6b529bde0b461f63cd2be3070f2d0815d4dd7609b266c8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/metadata/_text.py|2166|1c2b0592c66924b7933f734493f9e0ac079755146d4ebb7287d78e001a113f80
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/readers.py|327|d0d57d118d64916f7e6edb04f8bd1a760a1abb879125899ef50a36d09ef54df4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/__init__.py|532|4146e1d00d56a783d4087f15257f0c284fae52e71fa3f20613fa268d911bf6d5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/_adapters.py|4482|be9ac919b51e1db6a35fa5c2b8c3fa27794caea0a2f8ffcc4e5ce225447b8df9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/_common.py|5486|a0de4a899a2aa787b052f92f516b39f80b183c3f0d409d1305cc6dc374f18870
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/_itertools.py|1277|7838ac57a46a88d64ea202d25dfe8b3861ce61cefd14680faca34bcc52e60ab5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/_legacy.py|2949|79c566fdf1a61129683e38e8c11a660d6233dd84422456ae5dd230e658a7857f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/abc.py|5203|a726c48590b21ba5532f0c654735991571bc0ecafe88145cb8891d82cd364e5e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/readers.py|4370|10884a02b4a97636887fcedc7bae248a4ff42f3e52abb80d613cc0b2190b6ce9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/resources/simple.py|2584|090dd3888305889b3ff34a3eef124bd44a5b5145676b8f8d183ad24d0dc75b66
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/simple.py|354|8e687aeeb1db537d2717cb0352c5f126ff7d4095c6de6dc7f00d5103f3009c40
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/importlib/util.py|10994|671f2995653f673f6d5056a1089debef473bc28ae7114f7a8db71475733d6876
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/inspect.py|127125|5c54ebf0bfdc25397750e5d0f63800751650ee50e65325ff3ea4069c9bfa5f75
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/io.py|3582|7cec3cb8ac004058dd0a5af246e6d950fb59c7ddd0058fda48bcb3fcb98d8822
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ipaddress.py|81414|ba8d3389ff084fcb232b48204ec04f2b3ea4bd0eadf7b18c814947d185de2c64
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/json/__init__.py|14020|d5d41e2c29049515d295d81a6d40b4890fbec8d8482cfb401630f8ef2f77e4d5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/json/decoder.py|12525|382cd02af6f7efede5a6d4abbcda1015e5c7a75794b0016022878f9cf32a24f6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/json/encoder.py|16075|52bfb1b66029cc70fa3bd7fe11df9f2e03922d413407a341b387a22c987f24f8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/json/scanner.py|2434|572958017eae8842eeddd0e3d18d3c56cc0a197348224915e1d87ce937841764
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/json/tool.py|3339|d5174b728b376a12cff3f17472d6b9b609c1d3926f7ee02d74d60c80afd60c77
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/keyword.py|1073|18c2be738c04ad20ad375f6a71db34b3823c7f40b0340f5294d0e89f3c9b093b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib-dynload/.empty|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib-dynload/_crypt.cpython-312-x86_64-linux-gnu.so|18560|daf71f9136a88f1c1c5bb3fc3ae37e81baaa8fa1bcd23d46474a144d0e0ea703
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib-dynload/_dbm.cpython-312-x86_64-linux-gnu.so|2376896|f98d64513fe583364a2c58533fdc3a604f49a355826ec8bd93f7addd5af3250d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so|138688|0665203e18f974df0ed95df52c5eba6b6b1ac79b00b539bfb544c90a8e12b961
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/__init__.py|156|5373a81ab198cda8e95652dff46ecfee197a0b8901e8432ab448d97b8bc37f87
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/__main__.py|67|c7b09f90e66dea194ad63dc02c6425dff977d16f1f21a157b7475905c219a707
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/btm_matcher.py|6623|a1aa5d35558acf4b6016054963285cb145f97a764926bea07cbd674563f3248d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/btm_utils.py|9945|c0653eb497a1a48195dd9c4ecbbf87e4eab31188be29ab1640e353209741588c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixer_base.py|6690|c795a53ca849c42212c8ec33a74284e0377df852eb4ea599aba62d5af1df282a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixer_util.py|15206|306d0b2ea8169bdca711c6a31c0b1a3ce710d38ae2b6568ef519aa38451af608
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/__init__.py|47|836cdb388117cf81e78d9fa2a141cca1b14b0179733322e710067749a1b16fe9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_apply.py|2346|b5171e32758a78450854f40867775d4aca58665bc920ebece04fcfcc153af02a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_asserts.py|984|4c77972812cb5ec0a72afbce3e1d618c27ef7b239329c5c952c2bcbe77dba5dd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_basestring.py|320|d041443d6499a735bb78fec9da1bf33b3d034b5192c98bc273b16a44692fc88f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_buffer.py|590|2da37b49c30d6a0b4db43146ebb4ac8e5ffcb9814816b4742e464cb856977883
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_dict.py|3760|38f460596ebfb64046aab3d9a65935bd4c76a470118fb7d10a088dc0ecdc53ea
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_except.py|3344|7ff6f560c3c3d7a5d9ceef5ba31c556341f7ce1bc1b52d96b063f6c2c4765651
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_exec.py|979|9e0893327205dea12004e88d18c580286e7977e081b5eda7baf5b7bc93bc6c52
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_execfile.py|2048|6ff65db1192099457cb3d9f2618a893c6ac430028550284f3a34d5c08042b0eb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_exitfunc.py|2495|ef4f18f651d32410c43644c27590903d41e38e763b0e108e6c685a3412a7d29c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_filter.py|2765|2c7f0121193395750eab2b2abf5059d9a3b1a61f81763f52511265d7bca5cb21
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_funcattrs.py|644|111df53fac6a121d61abe33883a68e731820ddc4864b0a4c1000cf2ac5f019cd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_future.py|547|baba8cafb48dd9181a0e1f7b0f20b585ce2925e8f347e00b87407a256bb16663
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_getcwdu.py|451|5bc5252f683a401e7d81c5911617c4af1a1bcdf99a51c4bf1cfccb00446ff220
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_has_key.py|3196|32943d3b921c1c3f0d3776d19e5120806990b817bc99a7e22799847abfda1f63
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_idioms.py|4876|600e34faf36e14307e59d55088e3979881d497b8fc9d77659e77709f9e8bafd7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_import.py|3256|803baf96f9603c957eb974f252b0ad9829c889a293e0ce6829db1bce3da6dd4e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_imports.py|5684|cdf7ee6d85e2b148230984cfc4ea3f193be458958ea42ef290854a9672a64370
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_imports2.py|289|b6f3c628839ffe7fd72569dd6ca2210e18edae3e180002747ea011b76b7ec0ef
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_input.py|708|10c5ef3b45a4ee7e88af8852181916a788aae2bea52b08f3473815c1c43598d1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_intern.py|1144|8d29a162536b99c91bd2f9259dda7f39fec751949d6354d2c1f2e5d070c87d66
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_isinstance.py|1608|8408c92b99f50d8c4978b47a2b2155588e315f2ebbe58c160dcdcdcb89e19914
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_itertools.py|1548|578a51b9935020b03a510de15ece55fcd02c9474f37a54c158fb97ba5fd15af1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_itertools_imports.py|2086|2e419cfbd7f2a326ae7fa10873aa377112ebec32545238fdf988acb088c3cdb7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_long.py|476|306b80e0a72c0d16dd934b7d51ab0c9a4224f83be5d6cbad8a7158a0a5d73551
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_map.py|3640|b82c0762c44adf2af7745c030afe291e2badfe360925046c8e58d85340717696
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_metaclass.py|8197|45a30c866aa2ff69e089da147ed09986aad4516b5e5dd943f8dfcb7d3946a3e1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_methodattrs.py|606|8d60082f98ce52ee4955099bfd447cbadfa0e9b24ccb8d135cecc833168d44e8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_ne.py|571|4f9cb1388ba86f29422d20979d3423fdf3541ba35a17ed44d6f4a517ff784ecd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_next.py|3174|5c7d86d9f81b2498486d626c7feced1b92f23171cf9e42881abb78de1a93bccd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_nonzero.py|591|c2cd7e3ba44508643a20eec4ea4c19f2f1adfd36f6b974d7c143e449571ae736
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_numliterals.py|768|1c4dd0f7881999abde6cf4d232836fa3e55fc41a7d5aa2b9866092f65707db7f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_operator.py|3426|023872fe9f03a25387cf2c17fc950cf0f990353df66e603c3a1cd3199dbccd86
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_paren.py|1226|53734f1d7778ad28a4ec3ab4415923e2da8f230de4cd527589829f570e9f254d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_print.py|2844|cf2690f1b502249289f52cd544190db0b94d59df5eca139829cd2bf0742e9dba
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_raise.py|2926|c38ffec5862597ee8f9dac50385af943ee312bfc394366be08b2fc12563ca1a5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_raw_input.py|454|ce04cbaa76d414949afc230360dd9a29ff579bd868cc7f8805230d126ac9ce9b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_reduce.py|837|9a03910a6c183586e1db01863fcde6417d06745fb3e63032333d71c5e82e7919
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_reload.py|1081|17570148167e43b2155b6e1c814a3cca9e3ef53750c504932a9c7d62a8b68a3f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_renames.py|2221|8b71472317bf3adabf819e665c725d03e3064baa45f6ffbfd78cca83eaa46e8d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_repr.py|613|d16930b7ef8577747cfef602aba854c64ce85d4ae1e54a18a456eaa202643e3d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_set_literal.py|1697|33f2c0b6e16357e083c3a98877e7317abe1578a44c288e5979c9d96fb5aa6727
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_standarderror.py|449|ce7eb37bc7fb29aa138b1cec6656ae8b4886cbfa700e119a1bb8484284cb717a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_sys_exc.py|1034|0143830586d09d702ca3eeaa8f86698e5fd18af69fd28147e71a1a77600d356a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_throw.py|1582|fec731ed523d5cdfa21893833b52b2844eabfd1549792c1c9f8ceac2d0e8e901
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_tuple_params.py|5565|f3307d4750d0657d9c42b857d5f37bdb5824f9358939da7d16d13f61eb8abc72
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_types.py|1774|a0a133cfc78e82e1f71ce628408e7d10a38552ba3e3228ebd113838c1ce44484
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_unicode.py|1256|01b2a9b1084b6a0424f27eec488c761f75f053a409608ec36a9ee0ede0d38097
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_urllib.py|8367|3d1c04d976ff4d2841025a785aaab0cc4ee06c9c9b4e09d1e2456949fa273856
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_ws_comma.py|1090|5e7a16daec0b2619110516804bf90cac459a4d0315198fd4eff69c36c54378dd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_xrange.py|2694|60d8ce92db6f399606d2e40a3c631ba566127e8cd637ebbf35b822672139cab2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_xreadlines.py|689|e8c2f19f7047bfc7539fd78839929004d8fe0efba1fbcbd9d712d285e43834ba
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/fixes/fix_zip.py|1289|55ce115556c7513dd967364dc6a40c39210c874e8168cf090ddd6dc606df34cb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/Grammar.txt|8696|508e62e787dd756eb0a4eb1b8d128320ca02cd246ab14cc8ce0a476dc88cc5b6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/Grammar3.12.15.final.0.pickle|15313|97c8ed74d091fcfd23498029bb819c29d096c3dcb1326edee5dfb0591ade2e4b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/main.py|11854|8f5dfa77b8c8b375daba8bb88aaa195395674311e2513b29575a70821e3aa0b8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/patcomp.py|7054|a033a3eb91a39f96747d4300aa3394965e529c71896cd6503dd27e6b685eede5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/PatternGrammar.txt|793|ee5ba5db3b6722a0e2fbe2560ebc1c883e72328ef9c3b4da1c7c5d1cc649bce3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/PatternGrammar3.12.15.final.0.pickle|1225|36ee934395b9209737b13893ddaff05fad8e239c2fdfac29d401d3fceeb30768
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/__init__.py|143|858eb0f50533bd3bd16fe32815f77fabfed92ede885070b6cb15827ec66ea500
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/conv.py|9642|e2946a686c12e02248fafb1a57e7514e0c22bdb2b4a66e644215c86fedc37bff
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/driver.py|5969|57af5e220cd6c6b75e8dead2cea395ead2297dd98e398ad705ca2bce0e9e6594
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/grammar.py|5552|4898d446d6ae73f7259a3f91839eca1a3380670a9f378b80780707f714fad17c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/literals.py|1635|84bc9d5387a2e20fab844e530358571afa39fa3fc0e8024270b5f7d8ac5a595a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/parse.py|8155|e245e005e524ab445a570df31f70c6fd7b901ee3b0b68bd3bcf4b41b37fa7bb6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/pgen.py|13830|8fe2ac7e0303f0110d75832d746e6661fcd5373fa498d929163f557fd1027434
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/token.py|1302|7ee05616410d46d8caed0cb0755bf780c62cccf17e3c93c8ccb8dcaaa1e7094c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pgen2/tokenize.py|21119|aaa0b98f6a65e08e9f8e34358198e329d29554a0d4b5f5059924a252eeb0f5c4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pygram.py|1305|b49d77876a9d1822ff6be04daf464341a8e4c0c3414240abf519254de2a97a48
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/pytree.py|27974|e53689352fb4fc83d85a09369650389ee01db802ad872a8abfc0bf6603ec38b9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lib2to3/refactor.py|27507|6e9a4262fb65cd4d277f009df73ffa5748f5fe3b963d3c5395c160d5f88b089b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/LICENSE.txt|13936|3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/linecache.py|5800|9eb9194707991b49f9fea67a5222b0e6a0e49c865cdffc69fbc80a1f829e77fb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/locale.py|78599|3988c5419552d5b9f0bef3695102376f79357f0f440e9cd1f32c501f966e6ef3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/logging/__init__.py|83437|43f86bbc08fdd5c7b6e697abffe1381f534a92bb32e1f1aee8360d6a142592a1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/logging/config.py|42798|6b4bdac4318ee794f667a5d5df30040abf70b9786ec5ed8bf597bd8ad0b71d27
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/logging/handlers.py|62596|e0d31066e1d11142dc795af60351ea3610c2a08ff1cedf705743ce4522517495
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/lzma.py|13277|58fb9d2fdc8a8af7b25e218f17ea3b51bdfa53bdf40f440ab33c605974ca5c2e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/mailbox.py|78911|1c356f03e8df0b99d9d40a08ac7f3f5f71e9626c3ee1149cbed7307968ba0a4f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/mailcap.py|9333|d3242c92bfedb13c7cf5e7aa116e9a38c07e9c6de58f53d03f72a469e9448ca6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/mimetypes.py|23037|ed21537405f4b076318f966b810ae1d9415e16315603ad8003b1ecb24baf5950
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/modulefinder.py|23699|e07ab000c3698a7530af2c52955ac8bb7647140d22dca1c30f83443faa191e0f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/__init__.py|916|a5a42976033c7d63ee2740acceef949a3582dcb0e0442845f9717e1be771c68b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/connection.py|41398|c2f2d6f3d32d48d4d8c51a7d7c98766a04e958cae72a67c7f905438a7c332bdd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/context.py|11673|63f15d3169f4453eb80af4ce673a193a0670941206673ab5192ea16a17e8419f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/dummy/__init__.py|3061|9127a40ea0ff342cb414383b5e7c594a05be2dd835fe246bd3bb0dc036a32a90
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/dummy/connection.py|1598|d63dd1979fde9c133efe430ee870e6ba6de43c0a0513866ce3ce475791fe57ab
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/forkserver.py|12202|11c9f2e90ae7b0d5882a608ecc074047c10c7360834b026865696a0439bf873f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/heap.py|11626|f6bb79bb99b9ae484935f0d68822e9603a1622dd0b6c4966c79db232a93ba614
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/managers.py|47893|2cb074d33a3085904e1702b0b521b22fd3428d499fc656cd740e338f6e129333
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/pool.py|32760|418cd41ea5c341e66c6979a38070f6f552cbbdf0539073022b6d15c67e53f480
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/popen_fork.py|2377|0a09db57e7fab7061c01a61778feea6e2b6bb02ccbc150332f2960b05258ef95
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/popen_forkserver.py|2230|0588ad0e5a36718b4377dc2a2a97864a10986c25a33dc3bfed12595711b0cdab
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/popen_spawn_posix.py|2029|97b5d25aa479516894489877e6a7921252ee35f51e118c2f1f91f32919e7caa8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/popen_spawn_win32.py|4515|6ef8efd9cd4e99c64a6778f7ad0957e924de9eb4aa167337ed121a2621b1ffaa
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/process.py|12139|67f0c2a7a3a83c92dd024705bac18619a2e123c9df77c414beb81035ea4a0e18
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/queues.py|12693|f4721a323ab2981a172dd2b853d2cfeded696e9716fba340cf6e168f5ed95f83
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/reduction.py|9512|4999f8b9ae7b3e8a7f5de302612b4131498dc2e238a2c47f894905c1c63294fe
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/resource_sharer.py|5145|bba3c7f2b76a9cf4e8ceb642801c405411da95adf91947d81b0043586038290e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/resource_tracker.py|11077|f9d73a8145f8026ec48ebe4127e7e84960e297cb2e247159f8df4f858cfccbf6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/shared_memory.py|18458|51301e70710220e1c494ff5383ac94442a38a4a6622f2eb94e40128c45de1aeb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/sharedctypes.py|6306|77ef522912474652490b7df523112858e51721e63dcf109b8567a35ce9b31b0d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/spawn.py|9644|ebf9fa40eb622384c37690d8c78e7208744df031155ab4ceedab0fc791a1669b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/synchronize.py|12272|78ff49cff58c0c590324e5097241371f25d61d592c598a8b2c2788f2de32a53e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/multiprocessing/util.py|14261|6752c4515ec69f82e9df64e017da490c3754e51d818c270ea1ad2d64e09268be
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/netrc.py|6922|229da6d0cbe6a10295be6c64ac3806420ea018124c09e4887410548fc2fc8b5d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/nntplib.py|41087|6a76a94b951b273aa87335d7c9c4d7273e4c59485c784b057f681443b32d9004
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ntpath.py|30404|6c0d55ee892f98ef87b1ed3c50c9dfc7e267a98d2db47e08d3dc67529af56725
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/nturl2path.py|2374|560e42264a337d0d41b42713fbda072890997161aca8b7397cca8967a23f8b63
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/numbers.py|11467|ac381960a3dc1db0498b0bd43d8ef278d6599713121a186b153ff09d9552e0db
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/opcode.py|13174|192f6008508f28d3273bff42eaea9b01c8394dab1607cd36aea778bdd166c3a6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/operator.py|10965|b2af20f67667203c1730e686cc5d0427becc94db4c97f1d3efe3ed2158473f6a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/optparse.py|60369|07d224301cba312fa0697bff9cd5a4bb4f778a90629632091b3f4ae874d89af5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/os.py|40821|54c43a1fc69c979c70d8f7d097174cee163bfe59937723ee353043dd4a0211e1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pathlib.py|51052|10ba48ae8063cfe7589436041d0d4628c05f427c7709cf8e75e486f8930cc32c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pdb.py|70298|c87944ee79327e534816bf8fb72b79b89ad9ef9d3664d2a7b90f8fb961450f25
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pickle.py|66911|7e3447b6d993a6306a7893fd2fba916010ed79f8e09ceb56158a550fa8099a14
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pickletools.py|94052|a4242b8728b0c29d15d9534fac4f7303d9c562a8edb65c87f6bc09f764953412
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pipes.py|8978|153f2d249d954b5536c6a049202617ff43ba2f9b109c426e06676c577ddedc61
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pkgutil.py|18281|44300bc77f6f52ef2ad74d26e5053309c04f49eaa91c099356eb61426cde504f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/platform.py|43388|f5ff83f15c841792be42709a6710dc8d7a9f72791c1ae4cad719b1fb0abe0a05
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/plistlib.py|28582|7f427a3b717507598c73bae26ff09d3fb7664540d9b7209ca97be80c76648069
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/poplib.py|14619|e1596878e408b1702dea74ca55f13b367f93b12fd9950fc62f70d8e7b47fce83
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/posixpath.py|17356|03825681086638649a43480954f7f6a16b4da3bd41ece956864ae96e4f795cd9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pprint.py|24158|1585c8d74d7f485590db2af46680ae0a73737ca9fb66022b2bcbbc4c4925e203
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/profile.py|23093|dee2125b2a0913fcfd0330b75d7fb752f2dbbe1bf43e479fb0cba117b9ae6e17
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pstats.py|29289|476a7f4298d02d7445f65f464b1eeca3b1de7a74ce104e91f75c10a7eb1f9aee
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pty.py|6137|ddbb1749387539c2929957c7ec1235fd201d7ec15d285fe5246e88b35c722a4a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/py_compile.py|7837|3464f04938b57a7aafbc5c394ccd4c46823ee607f7fe36b48b91ecbc30ff4e48
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pyclbr.py|11396|e8ca09333701ba41244e20b8c2c37b7ed0499b88c4b2ca82cac51ef89ca9e647
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pydoc.py|113508|d181676eadd154121c64ffdc908b0fe520da2be4095fd13f8b4c6d1bb1897797
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pydoc_data/__init__.py|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pydoc_data/_pydoc.css|1325|038d4bf51b4d373284640f3658d70eaa856def24d8d02b8e29b289beaabf1cc9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/pydoc_data/topics.py|519590|b34de99ce149e2fe8e8d8bbe23d74ddb2735334ea0bb3c1962442d41f5c4642b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/queue.py|11496|f6c37fc37cd7440979f7d22d40ee818fa3b714c573610c08fa52911d541193f0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/quopri.py|7184|a1cd7f3b22033d32151209886cc855d4b71cc4c83530769f920097582339013a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/random.py|34689|de48263a837339c7e01cf9f3c4d756696e0e0775f7778eb9cf81ad5b00134569
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/re/__init__.py|16315|8ff3c37c63b917fcf8dc8d50993a502292a3dc159e41de4f4018c72a53d1c07b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/re/_casefix.py|5444|1b12d9136f23db6c3f6f26053fefc15ca964b886838c7b9c1fabf8d2efc1e5c8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/re/_compiler.py|26399|c75620761098a70ed75b9accef63ef2881d8abb6d4e5cbfd10074bd165eefe4d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/re/_constants.py|5930|fa4fdb200f238f9e7817b63892b0d69833d8165134801e775e10cc113348a375
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/re/_parser.py|41201|a51a85b37cf3f44ba7ff25754da5f31306e4ccfa6eb3c017f9d37bdf4e770840
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/reprlib.py|7148|e177bc70da83a7fbcde6fd261dc15da34e8a20873b1cccd4f9a1f8f27cca3779
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/rlcompleter.py|7827|fee9ad9c55529be48329b78e982fbba0201bd218326eaf80a87996c9f8c805bb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/runpy.py|12885|81e07da29bb2235111079bb64efea7d291639c5d2cf163e7af187d6a38cef389
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sched.py|6351|56588f00a68ef953014f41baf36e0dbb7ed7793f8aa883ebcb1a8bd3787c06a6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/secrets.py|1984|277000574358a6ecda4bb40e73332ae81a3bc1c8e1fa36f50e5c6a7d4d3f0f17
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/selectors.py|19671|1eeb102373e18c96311203f30c516e785bd8642275aa0bd66e43a284c9692385
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/shelve.py|8560|b978c6f0ffa901b041d6518afed03f2938a62168066013ee7d23baac31c356c0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/shlex.py|13353|f927227de5ba5b1b2bdd75e3d9c8cb72b602b3bba3cc8edbf8fb554de0dc1fd7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/shutil.py|56198|53496e06742fe008fee2bccc8caeac77473e69923bec05358bd43eea467db1f8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/signal.py|2495|0363c964c90ac0b3e515de5749205e6e6454051a1211058375d84d91eab6071a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/site.py|23198|b39ab288cc7a6d0cb3bb2655179221411340b22418e4efdee4c20175537a5fa2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/smtplib.py|43532|f19369e751e199f5dfc05882e2f77b6a692719cebd8a18c84552544a0b93e963
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sndhdr.py|7448|d1cb49f6545ef831a69322275ef26f6ca6964953e70d81a8a80fcca8d600ffc0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/socket.py|37815|7d4d4c66e6f4bcc961ab462c4f08002ca97def8713a4be1c7373bdbd970a5274
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/socketserver.py|28065|ecbbe1a633801460399a8f10b39007aa0e13cdbdad507e39414000f097b769b5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sqlite3/__init__.py|2501|f7cc982617b68e147540ef352d38310fe4d25c2c9c2542b67d0590c871df09a8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sqlite3/__main__.py|3855|495a939623e825a487cde07b62a68aeefdbb1704b53a8b5388af070dc3fac690
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sqlite3/dbapi2.py|3631|7c5c8d98df1f2c50c4062a3be2c0f0499190c179fa4fc281507a1ef763a98f28
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sqlite3/dump.py|3538|bbd9b9d14affcb013f8bd996e30e2cfd1b214d40a37916b9a67fce5b11820eff
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sre_compile.py|231|f7fd87f8ac9dad7d1387e2401761ec05806c5108201a6d1ede6ab2f481f6df54
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sre_constants.py|232|87013dc0b349c2c044100f70a8daa9d713e60a527e26f6ab8ee1fc978a6d3234
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sre_parse.py|229|c4929134532306081918f185c99305c6f55213bc16b32f8c259bc60f7f81e810
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/ssl.py|52287|c3490a080c4fb1bc6cf2629a624cf1c32ad83b15609a33ddaf1b3c815cf36e1f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/stat.py|5485|052af0327eae6941b69b05c088b3e748f79995635f80ac4cc7125eb333eb4c77
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/statistics.py|50227|5845851a5833a1436bfdfd19001f7cd6b4d95a438b76c47162897106d29449c6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/string.py|11786|24aeae1f0526250f442022022bf98df9a823b1cb330543ee79e70e44907462e9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/stringprep.py|25834|a5989150f7f74a68eb98b47966c1ed166033ba8cae07c3f376bcc162efd2ee47
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/struct.py|257|9c231f9497caf513a22dee8f790b07f969b0e45854a0bdd6dd84b492e08c2856
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/subprocess.py|88747|85d29b2bf0249f5436838298c9a60ee93508b1102e9ac43b001f8a7e7ae8f375
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sunau.py|18478|7e4f850f6460bcd302439d6d2a9fc1bfc31f88f87ad86c508489f5612b346b7a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/symtable.py|12477|3858ba5f1bd23175cf36a4b774c4e3d937d7cf15181fe49085b7a2f1cac76af8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/sysconfig.py|31850|ce56212ba89be181fb90fe62496e6d2e436befaf2dffd10e87ce37d1685271a8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tabnanny.py|11532|5dae83b384db40d6ebadc7af0cbb8396343e8ab289ce30de784a4cb41d5fbdab
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tarfile.py|114896|f0891b6936a39e5a41bd857fc149191fbe30ca84e5958f203682e76e218ff2a4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/telnetlib.py|23334|9b0e127e2d0853cc90a596a7b26a2df4ee49dc66c44ac30372aae64d015fd0f9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tempfile.py|32386|2eea4401f4f29d0d3647ed6fc8bcf6aa1daf879c8aa407a8ea310edac9dfc317
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/textwrap.py|19718|62867e40cdea6669b361f72af4d7daf0359f207c92cbeddfc7c7506397c1f31c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/this.py|1003|481d0cb3de511eae0b5713dad18542b07eafd9c013bb7690f7497bad49923a71
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/threading.py|60200|846f450ae794e4aab823a163f8c71d27751148af33e91dd3de886686a4e8ebfb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/timeit.py|13464|d47d9deb6be0136d817e04d0e4824aa66c66efa01fe61cf62860fff08ecfe83a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/__init__.py|173168|4648028778a32184f92ba0912b64d26f3aaf583644a12326f6081125bc20164d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/__main__.py|148|9738a6cb9cdd8139721dd82118bd527897db5325d807222883f70fb1c5a1c27e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/colorchooser.py|2660|1224241dcfb4ec6aff3cafc66adeb2b2a3759397a28693173915458c50040143
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/commondialog.py|1289|e683ab0ee9404baec656a88d637910bcb2badb4b4e5d5def2b80cc4534551e6f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/constants.py|1493|c01314dc51d1c8effeba2528720a65da133596d4143200c68595c02067bf1da2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/dialog.py|1535|4f8201d3ada7b6d0f450b417e55747adaee5f894412c4875169b0736a5ff0faa
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/dnd.py|11644|542b804b243b502b5525a8b1f04a02a120b1db4e3599f5c7865e60693ed3672a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/filedialog.py|14939|d75c1eb4131db658b8622acffd8262ecbd7337425c799ea3be8d605ea6be7b94
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/font.py|7000|a73482badacc4a69ff7fae9445793a4d858212fdef103360a478bbfd6ed2f496
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/messagebox.py|3861|cdbf655c66778a19f0e25754a5f198a850c8bd958ce651e8fe4b2b52ad7f9c63
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/scrolledtext.py|1816|c7cc050ec9cc3cc6a47215b5bc79b2d3e5c6ed895a4300ab0e20f6c249385e3f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/simpledialog.py|11753|984eb0bb02ebdf76da3cadde9f54587204f819723346a576176410b86141d15b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/tix.py|77032|5d7a11093a1f6510de786b0e9d67902ab33a57f637cd8f5e2603cf6c5c609a18
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tkinter/ttk.py|56318|6c13af04d672c71abc82181961a7f7bce7b9ea79becdae37f55c78001053ce87
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/token.py|2511|1a4d994ce9744f4bfe2d964fc24d112a1e76796a08c2e45a2d73c82a8587f922
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tokenize.py|21570|026f566ac63e60d69c8185a3880831b657accc5eac984fadf271fc99a5e5825d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tomllib/__init__.py|308|71f67036895f4c5acab942618af0cbd3d814451ba61e967f358d0f341a5b8f51
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tomllib/_parser.py|23117|559366e5c672449a271a6553675c5d1f699b6a3730f6c14c4e4955b184f29d86
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tomllib/_re.py|2943|75b8e0e428594f6dca6bdcfd0c73977ddb52a4fc147dd80c5e78fc34ea25cbec
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tomllib/_types.py|254|f864c6d9552a929c7032ace654ee05ef26ca75d21b027b801d77e65907138b74
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/trace.py|29352|cbed87376cb326ad5c02e6152597d16f4229e96ddb2d8299bfb403ba4d804ba5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/traceback.py|46393|2c44af2848836d9af0c7b3547469695cd22586c64274d362eafcf466af284bd6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tracemalloc.py|18047|c2cc84a05b824df79840c98729a0e94ef8909b11c528a1b2c5a00aa436b97b25
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/tty.py|2035|1ab5e5e047130b310355e907a3306178299b9f2044fb526ac63bd116e9a16d2b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtle.py|146363|5e0e21a736c0d20fc49df5f08a69f544e54efa5d9516e1b73d3bfb50da1c6323
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/__init__.py|314|5f465277c96c107a5af544b0a962561f97cb0bfd75906d9bf9741450ed02b0e1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/__main__.py|15384|03594b9dc866cbf17c36c4b133c64975295a3bc4f242187af3ea8ea0c75b1095
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/bytedesign.py|4248|6deeee99e0ddb4ed29a648f95d4d33e9f3292c21dbecec301337c22a605a280f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/chaos.py|951|bc8a3a9b77e90446fb7060ff68ee008ffd6b23b366052207ec225cc163b4dae5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/clock.py|3304|70e6033c112f699da2b54a56f9366f31466c95af9ca3607e6b94b87eb76ee3c5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/colormixer.py|1339|bbb065830edb37fd53b1c004118853176fd8da32ee532cb0d363960880920374
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/forest.py|2966|68cd81b7da35ca49d9066cc2cba24768cddbf90797dbd619a559cf899cde926b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/fractalcurves.py|3473|29fadf34c5eabda4649848d052fa2ed3ae829e55bc3ac5933f2aedf3fb04b320
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/lindenmayer.py|2434|4b597f52c1cb35ae8ed540d1db2dab52276c7874febd7a659ee50f26be26f61e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/minimal_hanoi.py|2051|0e458a6257fb5a4ecd2785962850fa87924b23d4ead8aebb70aab38904ff8ef5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/nim.py|6513|939d1ee904a7b00579bb44719b0286e7524bf560c7ffff6d482064b41b09fdb3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/paint.py|1291|81aa22d0da1d934cb47edfef1883f9fe8ef864c56d484f79f9ec4b46457d047e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/peace.py|1066|b260b857164684b3065ad760fec0245ab6505c220814fb179a3d080f2bba0814
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/penrose.py|3380|14aeb10db966bfd4ec923a19eb96892eb2aa2723c0962c0824fe2ca9f30e300a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/planet_and_moon.py|2825|cd2c5344b67dbe781cf4c7f0f1eb1b97e6d8a5bf50329bdaa4e42e7d390ea609
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/rosette.py|1361|61dfd5bb932cc5a0c3bb9caa8ed74889a19a8d3ee3cb6707ea8f63595ec350b0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/round_dance.py|1804|4ecaac02e68f11ec1a406a6ce8a4b17e4f8af74f76157e0776360d0dd041f276
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/sorting_animate.py|5053|7d38adf061cecaf08edfbe8ebc194937f7f070a35e19641a472778f6d3a10927
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/tree.py|1401|3318448046c83c176f95a97c33b5cd82e0076bee038d72810bef3dac1085e590
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/turtle.cfg|160|de66698dc4f083792df6aaed1e5d94e879852d72f1f24ac09c8fb4cd144c6c88
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/two_canvases.py|1119|3300593114fb9286af9360cc9d871a40e5dcbea4aedc24b832607d1dd71c7b96
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/turtledemo/yinyang.py|821|0737a80b939aafcf3d8a1bf60b63e781979c749337d02b6c216680893f9fffc5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/types.py|10993|345474ef027a1273f353da9bdc1f7c18f65335e72e681bcc0376774cc51f2405
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/typing.py|118836|be92d60fb8382bb29ead21c128825d7c96d0e8c915b44f840791e49f5a8d554c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/__init__.py|3487|32ed48385c0377bc2900a76e9a6acc3705aeef402c72de8554b3c637420506f0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/__main__.py|472|ff6b9a100d32001715b40d61bc4d613623b139edb1fdc3566427b83c331caae3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/_log.py|2746|905672317ab26c656c600defce25d477728068f597f00a7f94e22e8128c323b9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/async_case.py|5483|c600343ffa27eac746001b2f35df2e4e2e52b90f14026dcfb4c43b25dfd7b261
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/case.py|57531|45bac6d80a4fc3a0dea8340a80681e30b263f017b4a5002cb8f489a632e0f987
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/loader.py|21116|7f0af414bfa7fe8612a424b14cfcf8a3c34fcac999d976461beb738ef8b211b8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/main.py|11991|db58280574389c0d6cba9559cc51e1787f5b418c4e85d354aa55ca43335c487a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/mock.py|106317|1de18141992c6742bff27e77c0cbe46d53d6a5ab1850574a536910508823fc5c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/result.py|9130|5db286bdd3821d64150377e554d7edbdd58db7bb8b950772f977e9ec1d535617
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/runner.py|10368|76d9beb9c21d0d367a1b040a921ad43f90b7971fcc8cacfccd6f9760bedf1ce2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/signals.py|2403|f8286e818ca56e10e03745bc056cdfd31147678f9a1dc8cb6b0fe96ef9a4362a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/suite.py|13512|ed2da92bc9f97c53403ee2d3d12cc53b16a96e85d596ebc887b5a93458f3f6bc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/unittest/util.py|5215|fdcc640c3505d16deab9c32eae7c3f5f67c3b5e81c563dc6698fa7fcf403854d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/urllib/__init__.py|0|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/urllib/error.py|2415|d12b3cc66af3f42a8ebe63e1c91d24f92c6237b6a93a3702938dffabd812d77b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/urllib/parse.py|45676|e6af7f475262f1de335bb2e41e26adb94d6103977cf5fe1ddc430dc6a3b1623f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/urllib/request.py|104270|b6a7860356d99186e7ad1b35c47f2f09d7524a398096214d8c276277947b672c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/urllib/response.py|2361|7e6c3b6d7a95f0d74f5968f51a87adae8a51bf42390cdfec98c7a99203e7bb76
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/urllib/robotparser.py|9468|644cc6d2b09948e8782cb1e7dea3bb39a2d83932c67e7a8eae65a711318c002c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/uu.py|7365|dd1f5be33fb25a1b0832891ea07db4a4a2ae41b466e37e24e204604fdc6d18cf
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/uuid.py|29656|fe357bff7241e9fd6f86ee81567fd20aeec2e17460428ea9b7924bebf57301fc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/venv/__init__.py|26750|976ba2fbc7b22cd2ed315d679aef096d8ddadebbc65492cf892ff29e41860c58
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/venv/__main__.py|145|722537c68c0622f8293d39bb6ab1288f3637d8dc45d6f9aae96e49af8145ca36
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/venv/scripts/common/activate|2170|aba58c76034e4c5ddf9e2351070827d3082606c302d0174d387d2b7e97811b0b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/venv/scripts/common/Activate.ps1|9033|3795a060dea7d621320d6d841deb37591fadf7f5592c5cb2286f9867af0e91df
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/venv/scripts/posix/activate.csh|934|2b48fcd78f4a7f4437caa76284030d69969be6e56c25cc8acc8c9610bc8ecfcc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/venv/scripts/posix/activate.fish|2209|179d0e20caf4c36d0c6a4457c487dceb51bd5bd379939362b76759ef324c7930
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/warnings.py|21909|6405e281882932205eae641b2d31fba7776f94517a206d289465a1caffbf310e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wave.py|22769|0330428ea9e45fee49acc4ae5bdca4c235f4236c51dab09f30442ccafa25c1f8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/weakref.py|21513|56f8d313fb74019e53eb9287400702fbce788b7fe30e097b0b6e06296f3f080c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/webbrowser.py|24207|8a7d3cea5e22f227b2fbfcdb21be2ffc3f1c940d2ea26d2da479e1efeec49388
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wsgiref/__init__.py|657|c30e144025a63d267778d92f2f066fa592b476e789d888f79b96c059bf0bef60
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wsgiref/handlers.py|21809|ad6af74ec157c3a9153d9b34d7ce684e2df1d329aa703990ae5cdc1a08fc6f7f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wsgiref/headers.py|7370|9e579ab07be58d321f820b481230a10d5ba6dc4db6512c5323051c4870465ca4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wsgiref/simple_server.py|5171|d435cad48b5f63c0356e1ac70755e6e35eb94b02f9844b813e5762199110bc2b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wsgiref/types.py|1717|ba66d30ce511a88eba9b809616c51e12bf89c67972102e7d976b18557f7a6387
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wsgiref/util.py|5472|93783cda348368538525f52a5e9a5a43a3de93caec26b6a030ecfb3aedf98b98
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/wsgiref/validate.py|15036|4132f87dcf11a332f6ec5b051e68e59ff493dd6fdcc4f716ea72373734977a0a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xdrlib.py|5942|983c5e8e3090bdbeb94bf4faf841c1f8c916bcbca423863f6870a142d16a4fb8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/__init__.py|557|34296f728e7fe68cccb97a9f6edbf3bf3a686f44044c744fe85f207a92ed4811
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/__init__.py|4019|b415a6f3d3663c3ac332ee4a0f4213eadad9281508dc97410e258a03633b063a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/domreg.py|3451|826b02a803930834b96b1086cbee7db1d21c684f65dd3073706dc7bb5ba1a3e8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/expatbuilder.py|35693|80598dbc5970feaa36ea2b7549e3e76dd018fb80cf79e4a5e27e9e71af60c82c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/minicompat.py|3367|42974c4c67803dfe80b016ff8aeea0d1e5c751703ab3aec5be765f4e534367be
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/minidom.py|67982|ceb557c3bc32e2a734d947dffb2452676cfb2f6d83d6b490b9e2d9f700f45d33
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/NodeFilter.py|936|9bfacbbb64e239a75591a7260b3ed86748eeb4366e6c40f3542753e79bace9a7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/pulldom.py|11637|614b88673d496a360e6b10efe8d733c7c0826fb214470ff12f24a1e597699870
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/dom/xmlbuilder.py|12420|26883dc30a461cb6a3583bd79d363858059569c04e94e3787d4d028f5fab7354
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/etree/__init__.py|1605|91950edfb196c105d93886f8af7ea3c0a79e06a6b63be3e5a4ea09804e8672a6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/etree/cElementTree.py|82|d0f57acab07fe4f9c116c3392d85946bac8e78608f409cea70005f16ea019b57
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/etree/ElementInclude.py|6952|8e10c99668216701224831c82f13b36d29cd408554c19e34d290c351595df4ce
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/etree/ElementPath.py|14228|f9c2102cf56cf9859d34e69877ad4e8a04a0cdabb6390cf2189f04aa8101759f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/etree/ElementTree.py|74017|897618a09d05dadfa9d1707b39533526be69bf01d133747395d27fdc23db3f9f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/parsers/__init__.py|167|b88497adc30d5d5eda7789c25a2206ee9270c932d584d7ac42680325651da45c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/parsers/expat.py|248|64e1947747c2874117a7458bba1f07c86620cc0ed9a4a4116d262878e4a2aa09
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/sax/__init__.py|3238|2f949d27b9eda6284482b43f4c202830fb35ea94f4101d70452119d3210bdbe0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/sax/_exceptions.py|4699|26564d5742496196d17a4a0ee135d28f652ec81742cf2fa4bff83e64323578ac
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/sax/expatreader.py|16034|5b6750ae591cffa303b20f092b13409a92df5ee1c403adac08dd5320eafee0be
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/sax/handler.py|15617|64c7aae49f1dd382a7b9012610307bfa1d43a14a5dc09a5c8da30903f6805c3d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/sax/saxutils.py|12255|3fe2cdb6386e0c4d42d37c657bbecb78b69c57aedb1610dbd8bf4043944130ab
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xml/sax/xmlreader.py|12624|0962c8d64ac8b03148d4ae62a531f544c4fd1be2116c6f4a53b480cff463dbba
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xmlrpc/__init__.py|38|87ad5c8954dd56fbbca04517bf87477ff4dce575170c7dd1281d7ef1f4214ac8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xmlrpc/client.py|49331|c77e7072ab9aaab6c6f16f89f2e7d528183b816df5d9f80e490f773ab45fe238
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/xmlrpc/server.py|36822|6781c25a6224b8bafe13050d26456c8a8b480c96e7974bcf60d4deb0c4ad454c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zipapp.py|7543|56e098b62cef6c39944bb898326dd920b70be461fe644139e2b699977d2997a1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zipfile/__init__.py|90763|6190320a1e64275b0b5d8f30eefa620ea6c95a3c2428f10a32140ae477efd32a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zipfile/__main__.py|58|e418cdbb27adf0063e3cec28179ac6b7bdb6ac743bb49d157f450551fcf38be2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zipfile/_path/__init__.py|10860|63fc930890d38a662253bcf7ae50a1bfa06ce38bade19084f9c89f964dcd0e12
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zipfile/_path/glob.py|1158|64e27d3872da2ea18b901718c91297d32b9610ebdad058de8561344b0a10e8d7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zipimport.py|27840|a96f1d7a7b6aaf421a3cf382b94b1422f4f0ad452fdd0bb61d635b560d7a4e91
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zoneinfo/__init__.py|703|ac7fb403e4371d07482ef2fda81dbcf6879484e9fc41d4be42c156d7e54c68a8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zoneinfo/_common.py|5294|67deaf0ba41aa4865e007297677207485a89b75629eea0ee5c472be8a3e83bf6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zoneinfo/_tzpath.py|5388|5dc473af6f6ae35e5531cc9705a1e4923aa07e7d35f6b4c275b90c6a3c2591c4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/python3.12/zoneinfo/_zoneinfo.py|24674|ebb9b679519a23252eb90541003a2fdbb3f2d7bc36713fd70672baa575dcdcb6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9/9.0/http-2.10.2.tm|180243|56372f15e8f73234b7fb2b68f597d5a56a42d995416cdf65fe0c2da1c114e5a9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9/9.0/msgcat-1.7.1.tm|37407|80301481addb70362ffd4eb1c301471a41e59987d39dbbc2a6096ddfb415071e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9/9.0/platform/shell-1.1.4.tm|5975|54337e9db387e5f3c0a714ae225d3d915da83751d5be4a9e177e9b726d3f92d6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9/9.0/platform-1.1.0.tm|11052|4af798475ffe6a0af32f0202a7cbc7b07b59de5ddcd7f89fcbdd1b07ffe5f6e1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9/9.0/tcltest-2.5.11.tm|105217|03da6ebf2e314e6c931430761cc47cf586ded9210f9c5afed804858a78034e67
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/auto.tcl|22931|629dc86958aa1c5f8697a638f296c706458e7a3418d2d81a2e81ce945f3828c6
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/clock.tcl|60997|6b286804649120c7c249d8c2941cee8e1da59211132d985ad97b8ab196073546
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/cookiejar0.2/cookiejar.tcl|21330|9d0811415b98c15bbb5c8f86ec3b92e812dac61e3f4d564f7e0dd0b066ba632a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/cookiejar0.2/idna.tcl|7453|fa329853cd186ea405f4bec122913f1e4286c54488d0ffd445f7f120c71583fe
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/cookiejar0.2/pkgIndex.tcl|214|7d6f5e0236fad3b60cf5b7b10fa5629effcebead382083a7d9543c9526095d1f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/cookiejar0.2/public_suffix_list.dat.gz|70835|22b8b49a17178863832dbbb646946b38f0f879cb1cd5cb3e7490e62a055fc623
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/ascii.enc|1090|a2b03c43e2bb86bd50b022fe961bfb0e0ed632edaf838454ace8a565e827160c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/big5.enc|92873|65175eb63b96c5d5436a83bffac26d6efed0c4b90e6a95a8b66476105bbbd49a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cns11643.enc|97050|0a95f67f90b1cdd407a78ea4032af9eb996fc38864c46d74b42b3a7f7eda0c8a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1250.enc|1091|852fba18eddf59ca2d70e1398a59686fbb1c9fb473d759382935bb17c4258156
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1251.enc|1091|acac49a21371cd35adfcb969b5edffc43689fd9b3becdc7367e4b26674a25ccb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1252.enc|1091|73bc277663125f376973065cfc3c9d834c74b1ad72c8d284978e19ea00d2de7d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1253.enc|1091|04b00244838fc509d16b395d5888db572cba8bd57ae11462940f96be39ab390c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1254.enc|1091|499fc6830e99a8087cae8cebc5777a94ba278cd0f950d206d059f68824b4fe3c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1255.enc|1091|2cf2e3f75cf30853a80282fd284297309616835bf218f200cb9a7400c5ed8173
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1256.enc|1091|bbacea81d4f7a3a7f3c036273a4534d31dbf8b6b5cca2bcc4c00cb1593cf03d8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1257.enc|1091|50d0ff658100b103805a66e381f77a5bd612ed548d94eedc97a472ddf53fbf4b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp1258.enc|1091|5515ba9a9787bb80148216f3b3d99047c1577b14db529a0d29b484a1f900685b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp165.enc|1090|644bc93a948341eb8e2ecb09ec1870d03375e5af69115b094b66dec80d1bba9c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp437.enc|1090|d707a1f03514806e714f01cbfcb7c9f9973acdc80c2d67bbd4e6f85223a50952
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp737.enc|1090|8bfca34869b3f9a3b2fc71b02cbac41512af6d1f8ab17d2564e65320f88ede10
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp775.enc|1090|44fb04b5c72b584b6283a99b34789690c627b5083c5df6e8b5b7ab2c68903c06
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp850.enc|1090|55aa2d13b789b3125f5c9d0dc5b6e3a90d79426d3b7825dcd604f56d4c6e36a2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp852.enc|1090|5266b6f18c3144cfadbcb7b1d27f0a7eaa1c641fd3b33905e42e4549fd373770
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp855.enc|1090|e3f071c63ac43af66061506ef2c574c35f7bf48553fb5158ae41d9230c1a10df
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp857.enc|1090|e39985c6a238086b54427475519c9e0285750707db521d1820e639723c01c36f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp860.enc|1090|6db59139627d29abd36f38ed2e0de2a6b234a7d7e681c7dbaf8b888f1cac49a5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp861.enc|1090|a43a5b58bfc57bd723b12bbdea9f6e1a921360b36d2d52c420f37299788442d3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp862.enc|1090|aea716d490c35439621a8f00ca7e4397ef1c70428e206c5036b7af25f1c3d82f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp863.enc|1090|13b5cb481e0216a8fc28bfa9d0f6b060cdf5c457b3e12435ca826eb2ef52b068
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp864.enc|1090|338f9a4e70dd3d0b9be292a630db51a9090379afcc9c2c6da0332cffa7868752
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp865.enc|1090|407fc0fe06d2a057e9ba0109ea9356cab38f27756d135ef3b06a85705b616f50
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp866.enc|1090|82633643cd326543915acc5d28a634b5795274cd39974d3955e51d7330ba9338
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp869.enc|1090|a25cdbba0d29fba9cc2982456f39397797ec05de91cabe39f44974b63f186e05
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp874.enc|1090|f0ec3dcb2e20957de7e35f815d212e819ebc28c1ce4bd17e0529cee94db1ef1d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp932.enc|48207|a797d602482055705b0bc2c8e64eb72899841addd2d5ee05dcab7e077ce55ef8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp936.enc|132509|619330192984a80f93ac6f2e4e5eaa463fd3dddc75c1f65f3975f33e0dd7a0bb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp949.enc|130423|dc9384c3d367b75f73e5ae82cbbf2e815ff98621ac26c323ea5e8580a336d193
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/cp950.enc|91831|1ef0ff7cfbd4d52059a21c0b880fd7a5b1003d6f1bb1fd490f0b2d3d9ce328c4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/dingbats.enc|1093|909a196858cb8bccdd88c74440a878c84a0f8af7b61acafadfd6cb7bccd13139
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/ebcdic.enc|1091|b5e5c2ac0d0ae2c11c9568e97c692a2f9c1bfbfe2c92e663a48b0f2583cb873a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/euc-cn.enc|85574|579bd7804e9e387bb9ed9ba88af79d142eaf0e46e0f7273779320c64fcec3039
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/euc-jp.enc|82537|ee20bda6c47b4d0baaca43a1438256ee8c8549eb7dfae1860b2f93eead18b6ed
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/euc-kr.enc|93918|4a88667d0f6d91110f87875cd827da3f4db23b49b35db0051ce218380d8f0142
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/gb12345.enc|86619|0c0df17bfece897a1da7765c822453b09866573028cecced13e2efee02bcccc4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/gb1988.enc|1091|ebb084b998266362c9eb1bea7b0aafe04967a6447ae6b2483a83c9cbe1da51da
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/gb2312-raw.enc|84532|ec11bfd49c715cd89fb9d387a07cf54261e0f4a1ccec1a810e02c7b38ad2f285
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/gb2312.enc|85574|546392237f47d71cee1daa1aae287d94d93216a1fabd648b50f59ddce7e8ae35
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso2022-jp.enc|192|e12928e8b5754d49d0d3e799135de2b480ba84b5dbaa0e350d9846fa67f943ec
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso2022-kr.enc|115|6ac0f1845a56a1a537b9a6d9bcb724dddf3d3a5e61879ae925931b1c0534fbb7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso2022.enc|226|753dda518a7e9f6dc0309721b1faae58c9661f545801da9f04728391f70be2d0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-1.enc|1094|754ef6bf3a564228ab0b56dde391521dcc1a6c83cfb95d4b761141e71d2e8e87
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-10.enc|1095|79f6470d9bebd30832b3a9ca59cd1fdca28c5be6373bd01d949eee1ba51aa7a8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-11.enc|1095|ad939139ff7140970bde3d91180f7c4d703d7fcf67a02c71392de1980dc560e4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-13.enc|1095|33c6072a006ba4e9513d7b7fd3d08b1c745ca1079b6d796c36b2a5ae8e4ae02b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-14.enc|1095|8d737283289baf8c08ef1dd7e47a6c775dace480419c5e2a92d6c0e85bb5b381
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-15.enc|1095|c7b0377f30e42048492e4710fe5a0a54fa9865395b8a6748f7dac53b901284f9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-16.enc|1095|c40ca014b88f97ae62ae1a816c5963b1ed432a77d84d89c3a764ba15c8a23708
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-2.enc|1094|0e0732480338a229cc3ad4cdde09021a0a81902dc6edfb5f12203e2aff44668f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-3.enc|1094|73342c27cf55f625d3db90c5fc8e7340ffdf85a51872dbfb1d0a8cb1e43ec5da
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-4.enc|1094|17745bdd299779e91d41db0cee26cdc7132da3666907a94210b591ced5a55adb
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-5.enc|1094|bc5ed164d15321404bbdcad0d647c322ffab1659462182dbd3945439d9ecbae7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-6.enc|1094|f502e07ae3f19ccdc31e434049cfc733dd5df85487c0160b0331e40241ad0274
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-7.enc|1094|013b3b2911c66bc1ca54e510814af4954c310da10737f9b2a2474d714be2ab39
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-8.enc|1094|e1d207917aa3483d9110e24a0cc0cd1e0e5843c8bfc901cfee7a6d872dd945a9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/iso8859-9.enc|1094|1cdcf510c38464e5284edcfaec334e3fc516236c1ca3b9ab91ca878c23866914
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/jis0201.enc|1092|867ae0cbf181b80a0e4644eeaab6332fdd3877a24ed29696c6e5060d8b790eee
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/jis0208.enc|80453|118ea160ef29e11b46dec57af2c44405934dd8a7c49d2bc8b90c94e8baa6138b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/jis0212.enc|70974|24a9d379fda39f2bcc0580ca3e0bd2e99ae279af5e2841c9e7dbe7f931d19cc0
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/koi8-r.enc|1091|7142b1120b993d6091197574090fe04be3ea64ffc3ad5a167a4b5e0b42c9f062
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/koi8-ru.enc|1092|087f597d223a0835262b0fb963924628fc7316ba2dffb28b73c1fe0db001f531
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/koi8-t.enc|1091|b54215edddcbf3c2ba13cb4ba16fa9a152a035b75a4aacfddfa46d1581f2db42
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/koi8-u.enc|1091|cbaf0e6426c8d1766815528ccf10a438b1f3e4c5b105761da3ae810a094f2a62
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/ksc5601.enc|92877|0f8b530ad0decbf8dd81da8291b8b0f976c643b5a292db84680b31ecfbe5d00a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macCentEuro.enc|1096|8f3089f4b2ca47b7ac4cb78375b2bfac01268113a7c67d020f8b5b7f2c25bbda
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macCroatian.enc|1096|8d0b6a882b742c5cce938241328606c111dda0cb83334ebedcda17605f3641ae
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macCyrillic.enc|1096|eb135a89519f2e004282ded21b11c3af7ccb2320c9772f2df7d1a4a1b674e491
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macDingbats.enc|1096|fa365a695d5610cf5c2aeb288432d4cea40ce63c99e68c447d6ac15b47102cd5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macGreek.enc|1093|f7bff98228ded981ec9a4d1d0da62247a8d23f158926e3acbec3cce379c998c2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macIceland.enc|1095|633f5e3e75bf1590c94ab9cbf3538d0f0a7a319db9016993908452d903d9c4fd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macJapan.enc|48028|a8be085ab3afb537dbb4930acb693e67f736b7805cbd648b274bcf7007dead34
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macRoman.enc|1093|68f22bad30daa81b215925416c1cc83360b3bb87efc342058929731ac678ff37
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macRomania.enc|1095|71ae80adfb437b7bc88f3c76fd37074449b3526e7aa5776d2b9fd5a43c066fa8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macThai.enc|1092|cead5eb2b0b44ef4003fbcb2e49ca0503992ba1d6540d11acbbb84fdbbd6e79a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macTurkish.enc|1095|f703b7f74cc6f5faa959f51c757c94623677e27013bcae23befba01a392646d9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/macUkraine.enc|1095|4c94e7fbe183379805056d960ab624d78879e43278262e4d6b98ab78e5fefea8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/shiftjis.enc|41862|fbf9b3ded58d966c42c463feed6363e7de774a5fb9d39c0c9dda1dd3eb26768c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/symbol.enc|1091|e05e07d65b6a073acffbda743f3860fcbc0e8cfe34a300646f4687042df0bc63
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/encoding/tis-620.enc|1092|7219d1bf862cab7a61468118ad56abe63e826186395134efd74a4acba18dd959
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/foreachline.tcl|608|5073f9015583f00b25354a7877f55c68d93674ae11384ee042e3b094a8a900e8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/history.tcl|7899|ca38bb6652bbc562a3a82d2919f4e900cc5deedfb3582fa4503c573754ccf007
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/icu.tcl|3861|bc125ef0732af6e67367e324c0b3de87e03f04f48c72c42fbb8f77b7b5849a8d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/init.tcl|23574|8c5907793b2b8aa05e8d8cf39c0cb7f033c01ca1b8be683e7159774d1a01357a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/install.tcl|7312|5508d98832c4f3cf52b297511206c5dd020111f1dfbe358eee023ee1bff3e012
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/opt0.4/optparse.tcl|30413|3d14ecf300f9fdd21875e22ce348988f852c177c4bf25fb6a7f37ba4be9fca73
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/opt0.4/pkgIndex.tcl|625|9eaa82aeb3d308b655b69660380829c54a6bbc011280667ac8cf0e5882132846
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/package.tcl|24081|473bf551d3156a144d6483ce730c72add640168a3ab426b3ee0b122f6d06a96e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/parray.tcl|814|b8677236d4e687e686426718e78d3984146d2f318e5b34cbd43824206e85a40a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/readfile.tcl|599|eff41b30c70251d068e24d1500ad504404d692f8d48ab74cf8f99bb4dba64414
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/safe.tcl|46995|0d3e8ddb147d713206139b7c4c915f11d0a53aebeee3a5ca3e7aebf26854e238
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/tclAppInit.c|4852|b055dfdc5744814a27ebdce6a466d56a269776ac6d0739d6f4f39d9f2db4e4dc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/tclIndex|9866|a44757ba1e8499c88f71ee63979980f9db851793643ee21879e9b53873461b1c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/tm.tcl|11904|7c1de0bc512b362c26d489bd332f3d883041d98c2ed1cc99b4d64cd97e646786
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/word.tcl|4764|3a481eacbcca1c611843cdc387ac51be0b8ac98a994cbe8fa43091fee35b207e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tcl9.0/writefile.tcl|911|b454723873db2e587ac1323bcebff2e8929f5dc98a6fe001ed34fcaf0c2aa320
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/thread3.0.6/libtcl9thread3.0.6.so|105432|063ee0558a4a12d7b789b35e30faae2ddaf397479447867a77c66a327d161b3c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/thread3.0.6/pkgIndex.tcl|2151|b18a83036b134eee16ac3a7cc651a994bed612f575dd34eac5190cb6edd0f532
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/thread3.0.6/ttrace.tcl|24364|261d96832df31668c944e0989b077fbf093ed49558f164bddf01b6a260da15b9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/bgerror.tcl|8924|391d0b6ab287c01887db14a270fd7456caf9dea8163806d2a6910b085c1c9c64
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/button.tcl|20834|7fba8f38b382468ae412541d63ab75223822fac023febb0b46532f2fa8d7fff9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/choosedir.tcl|9681|1536eae9e69ba05da9951a7125e836534423014700a09ec63c82d9cbbe9cb244
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/clrpick.tcl|21550|c91f2715d02624249aff12c9ed7825d65964c21bcf5c0c32b0331c9260b07dc9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/comdlg.tcl|8355|fed47f393ff89f299d83ff482d3aa4ae61ced53dd75f3819a52c8e69b9a318cf
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/console.tcl|32084|dc90799d3fb1828944f8394a9846b3d4a9e10d280bdff5bacbf02b82f0bd284b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/dialog.tcl|5800|463fdecfc1af0f70c8f0dba06a4865ce2a3311c2a52308df23891f0fcbc4f6ad
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/entry.tcl|18659|8904b3e1fc746afdd4e3731d80dac785d5e8cab1ad954eeec525800be8c8ed85
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/focus.tcl|4856|2b6f3cfb78c0a1d1e88dbdf9afe8eb80e5f5a0035f7d0f18981a327dd79d8377
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/fontchooser.tcl|15648|8b78e74195f9e13e82349e0472c241db3382b6c4524a936d5cfe9ad3e6aab61b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/iconbadges.tcl|13046|e5015ee51106c53e623013ba6b6bcf17f6bec9686909bd3af44db9a58062ece2
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/iconlist.tcl|16403|0e7c03224247b03ca1db39d01f58498b0356e2e483630f79f629e0b0c50d392f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/icons.tcl|2380|1082bdba6aeb87061d7147097b969edb8b458377078928bfdcc627778a710822
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/logo.eps|32891|0dbef0fdf9c232ea53d9676b43eda981fd13f75366bd26898394f5da5923076a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/logo100.gif|2341|72f6b34d3c8f424ff0a290a793fcfbf34fd5630a916cd02e0a5dda0144b5957f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/logo64.gif|1670|138c240382304f350383b02ed56c69103a9431c0544eb1ec5dcd7dec7a555dd9
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/logoLarge.gif|11000|0f404764d07a6ae2ef9e1e0e8eaac278b7d488d61cf1c084146f2f33b485f2ed
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/logoMed.gif|3889|4d0bd3228ab4cc3e5159f4337be969ec7b7334e265c99b7633e3daf3c3fcfb62
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/pwrdLogo.eps|27800|4928cb22d8fd8abd96f6803437bb8b9cb786170a840e824f5ea41810a8d02691
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/pwrdLogo100.gif|1615|bcc0e6458249433e8cba6c58122b7c0efa9557cbc8fb5f9392eed5d2579fc70b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/pwrdLogo150.gif|2489|5fc25c30aee76477f1c4e922931cc806823df059525583ff5705705d9e913c1c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/pwrdLogo175.gif|2981|62866e95501c436b329a15432355743c6efd64a37cfb65bcece465ab63ecf240
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/pwrdLogo200.gif|3491|bad9116386343f4a4c394bdb87146e49f674f687d52bb847bd9e8198fda382cc
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/pwrdLogo75.gif|1171|462a8ff8fd051a8100e8c6c086f497e4056ace5b20b44791f4aab964b010a448
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/README|322|2695adff8e900c31b4d86414d22b8a49d6dd865ca3dd99678fa355cdc46093a8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/images/tai-ku.gif|5473|e538f8f4934ca6e1ce29416d292171f28e67da6c72ed9d236ba42f37445ea41e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/listbox.tcl|13771|5cb48eecb7389ad0868e42d8a5a1ef86f193d6461b32210c54e5a69705bca1bf
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/megawidget.tcl|9570|eeb4dfdc6bb2256c83c0374782cc6afe1578232b32b4cb216faccdb975f42958
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/menu.tcl|38199|4ab1819b71532aeb493c63df54b572fe7ce3f474f1e449714b25c6dadd302ab8
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/mkpsenc.tcl|29352|0ac9d11d4046ef4d8e6d219f6941bf69c6ae448c6a1c2f7fc382f84b5786f660
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/msgbox.tcl|17249|1da78ffbd719cc38cfbeb2aeb0a1b18e46ba4477963c2fc7a0c22f4d3254a187
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/optMenu.tcl|1580|2805d470102800d8af66fee3c030feeb45b4e969c37414838acb086e5fe14dcd
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/palette.tcl|9491|59709065d66d690b50cd8b5a6dd99fa5e92a90e94d4e9df0c107eff1198f4e01
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/panedwindow.tcl|5162|813d5da099883418818d9a9eb8dea0d38e1eebe29b903f794bedba64e7304a32
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/pkgIndex.tcl|220|55d1ff619b31c2f26f06afa6f4cd7b0b91dcdb8d98d9a4d0a60ae000dc3f0508
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/print.tcl|42536|973d400c618b83956ca0ab88ec7711f03c18e9311cfe3d204fa600e2f139d01a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/safetk.tcl|7372|318c663c2ff6e8fd2c33e8cf0918342b0431a9151c1e05d8037f4ee7bfc6add1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/scale.tcl|7928|43b1e9c6f29e6a9fa09186fc51029a95dd4dc70a0cf0ddf92af058083fd4567c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/scaling.tcl|6496|20c4f15b4859e029122901abdbb6b95fe744094fb982f6168e4d55135e69efe7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/scrlbar.tcl|14282|ba1c40064864b01a25a3edd869b05b2dae745ddda8b12721db6980563a4b040f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/spinbox.tcl|16029|7239b27458867b25ec2fde06f2ea8833d481f1cfaf5804e7977f8d5a10bbb57b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/systray.tcl|14489|36b25a0a9cf4a9f1897aa90e145235aeb69e4146a761510d7475b16fc104b339
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/tclIndex|20142|f083821ef84fa181a8e7cb95018490d3661b17fee06897e738eeb92823da0234
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/tearoff.tcl|4439|7e0262027b3923105262ada30dcc285124397e3929eb1b198b429ddda81e73ff
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/text.tcl|36150|03448f1557595e4487d86a68b93129b81f5e256301ddcc6b3742a40adca87b66
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/tk.tcl|26717|a8a68093d26a32b78cc58b074fb4cd29b5a3312b4898be452395d7e2ce635cf1
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/tkAppInit.c|5543|620e519f26d3c1c147e4c703c2c36b39d4f8704c6d7df8d499c41350d683fcfa
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/tkfbox.tcl|37326|f4a89638d5145cb5a356a7eca38999356070e70392d74aab3e0da16470b2cfc5
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/altTheme.tcl|5618|a92d5585c91f1c2e4bb8e92cf874e99d61bbdbecad1c2b9a9511d5a13e20238c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/aquaTheme.tcl|8137|25a38de6dbd4b9f8fb64635d55a5a0da4bc6b3b3d256bcb94b84303a99cf645d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/button.tcl|2916|58c4c1ac28e7a4da35df11a40ce9d7dc69b7ff56882c69a50d2947f47449076a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/clamTheme.tcl|6792|4d4c1a399553d4198ea822fbe73cf21c2c1fb60a4edd4069cad0ecf58dc614c3
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/classicTheme.tcl|5285|8156dadbff4efde1cf4c48286e73aa915f7d8869583660e28d4eb608fdb6ebf7
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/combobox.tcl|15488|56999ea89dd3b97f64c11de9b515fc2a71ee3dbaee927c6fd45d37be4fdee133
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/cursors.tcl|4439|685b7f1737c606841f2a797f989b0153f88bbb62e80210c00524ef8526073682
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/defaults.tcl|8025|8a2d71b2d98bc05ae8ce68fe888ebefeaee5e788734f8ea9bc0ab7aeab02bced
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/entry.tcl|18034|081ae003913a17172782a9ae48c08f7433a6e3f02e51e52ed46cc99a62f4d694
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/fonts.tcl|5031|235fbff958f5f420d86fdc40063441625ab3838f4a35d2210a9e1f43c30cdc78
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/menubutton.tcl|6202|98fdf67d20188be9074e04a1ce4d91c4dc0562bc4762598ac42520d4d0eb100f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/notebook.tcl|7464|6aa711938fd62ff90535ab71d9091440c66f7c9ef028fe1db883acc38f0d58e4
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/panedwindow.tcl|2028|5cdd719102c4f978cbd225ff9ea81256967839c26b2460c93a94702b94b9cc80
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/progress.tcl|1218|440dfbd799945c9ee8abf275ef8715ef0663f278cc3117f6dd033fabca6c295b
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/scale.tcl|2580|419012f3c07d4ae138f324b40b2e19178d3f7d277d85078451fbf4cfbed6125a
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/scrollbar.tcl|2956|eab2c42fdd826b37b7308d4834ddef063b5f8125f21b00677746c03f66e2351e
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/sizegrip.tcl|2353|a7132288dda9b5acc5f7751ba6eec8399f60988a2bebd480982a8c0a6418a27f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/spinbox.tcl|5309|b6522ed8a2f1bb6d999a2e010c6ec276f770ba39432615eb7fc0635c431dd956
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/treeview.tcl|11898|cdc70e8b5f49cc77daf2866a69fbe2b37a0e3f12742e405eb5c1b31fe3a9d62d
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/ttk.tcl|6408|ccfae8b866f51fdc5ce415a82300c8a85423228d99b80c61453c242989127f1c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/utils.tcl|7293|c7886c6bcf00c33c2ae165a9cdafb9eb65ef0a1ca93e91f54d9f7783e089c038
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/vistaTheme.tcl|9491|7fb0dabbcf6044447d422ec552ba42776b8bf9c2b100c1ea62849abcca1aa13c
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/winTheme.tcl|4054|f85a87d14deab7ab5d7306be8a0b3deaad2c81e7111eefce10e14b863bf06eff
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/ttk/xpTheme.tcl|3299|6d6f529ed6055e74e9324aeeaeca1060a46180cdc561b55cc52a74cc710bff6f
Utilities/PortalAI-Projection/Runtime/LinuxPython/lib/tk9.0/xmfbox.tcl|25855|8051bca4e346a27eb1d0e361bbfa10ff5aff9a4c8c7ef14f283a050656da1624
Utilities/PortalAI-Projection/Runtime/LinuxPython/run-python|312|adc68b7be233ab9ba1f56ef2ce34c9149836183269ac9d50e01a80ea4311e43c
Utilities/PortalAI-Projection/Runtime/NativeState/receipt.json|509|a0dab3fb308c60f8c9f1c28fa03e066d06c074d5e8404a6b081a8e0dfa98ac02
Utilities/PortalAI-Projection/Runtime/NativeState/websockets-15.0.1-py3-none-any.whl|169743|f7a866fbc1e97b5c617ee4116daaa09b722101d4a3c170c787450ba409f9736f
Utilities/PortalAI-Projection/Start Projection.sh|446|a4cb64b362ef582ccc45bdf0c389245a5821fae73beb40bcf302a83fabe6c5e9
Utilities/PortalAI-Projection/Tests/test_macos_projection.py|6618|5512d155524f282dd1b59a5cd7c3baf7548b20e7396908a2f88856f2180c3ade
Utilities/PortalAI-Projection/Tests/test_macos_setup.py|3040|232c4cedb9c00fe9618367c8545ccbe41e792c8ebb47a98f9ee943c0ff5566cb
Utilities/PortalAI-Projection/Tests/test_projection_ui.py|8642|48694fd6a00bfd631c9b345add187116d3826b5b5f57edcda345cd217c0605d3
ACADEMIC_FILES
echo 'The complete Academic installer has been downloaded and verified.'
if [ "$PREPARE_ONLY" -eq 1 ]; then printf 'Prepared installer: %s\n' "$PACKAGE"; exit 0; fi
echo 'Starting the Academic installation. Additional runtime/model downloads may follow.'
sh "$PACKAGE/install.sh" "$SETUP/PortalAI Academic Linux"
