#!/bin/sh
# Checked before any payload extraction/download. Numeric inputs are build-generated.
set -eu
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
