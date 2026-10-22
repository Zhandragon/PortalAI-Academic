#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=
for name in "PortalAI Linux" PortalAI PortableAI; do
    if [ -f "$BASE/$name/PortalAI.sh" ]; then
        if [ -n "$ROOT" ]; then
            printf '%s\n' 'Two PortalAI installations found beside this launcher; choose one explicitly.' >&2
            exit 1
        fi
        ROOT="$BASE/$name"
    fi
done
if [ -z "$ROOT" ]; then
    printf '%s\n' 'Keep this launcher beside the PortalAI Linux, PortableAI, or PortalAI folder.' >&2
    exit 1
fi
cd -- "$ROOT"
exec sh "$ROOT/PortalAI.sh" "$@"
