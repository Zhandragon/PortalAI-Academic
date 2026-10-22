"""Fetch pinned VM assets onto the SSD without installing anything on the host."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import require_space, atomic_json, portable_env

ASSETS = [
    {"id": "7zr-26.04", "name": "7zr.exe", "size": 602624, "sha256": "256feca8e274e5da655e2a284fabafd9f554365eb164862089dacd4e8276d282", "url": "https://github.com/ip7z/7zip/releases/download/26.04/7zr.exe"},
    {"id": "7zip-26.04", "name": "7z2604-x64.exe", "size": 1664082, "sha256": "d54bf805f9f3704d1e8db2fa3498ae7ef2df0312b40b558e7c71c734430a665d", "url": "https://github.com/ip7z/7zip/releases/download/26.04/7z2604-x64.exe"},
    {"id": "qemu-20260811", "name": "qemu-w64-setup-20260811.exe", "size": 206615928, "sha512": "5bcf9eed634e8575a37b74f445af41a2fe4106da512d0c30c368301d4c105037fdfab40a5287367a28a957624cddebbc8c07e16c88ab6634f554cdf3d16bf543", "url": "https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.exe", "checksum_source": "https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.sha512"},
    {"id": "alpine-virt-3.24.2", "name": "alpine-virt-3.24.2-x86_64.iso", "size": 69206016, "sha256": "3ab424762af704b2c2a9e57df1dc37f982af260071504d977f2fb96822e7130b", "url": "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-virt-3.24.2-x86_64.iso", "checksum_source": "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-virt-3.24.2-x86_64.iso.sha256"},
]

def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4*1024**2), b""):
            h.update(block)
    return h.hexdigest()

def fetch(asset, root=ROOT):
    folder = root / "Cache/imports/vm"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / asset["name"]
    algorithm = "sha512" if "sha512" in asset else "sha256"
    if target.exists():
        if target.stat().st_size == asset["size"] and digest(target, algorithm) == asset[algorithm]:
            return target
        raise RuntimeError("Existing VM download failed verification: " + str(target))
    require_space(root, asset["size"]*6)
    part = target.with_suffix(target.suffix + ".part")
    # Windows curl uses the OS trust store. Never pass -k or disable certificate checks.
    curl = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/curl.exe") if os.name == "nt" else "curl"
    argv = [curl, "--fail", "--location", "--silent", "--show-error", "--proto", "=https", "--proto-redir", "=https",
            "--connect-timeout", "30", "--max-time", "1800", "--max-filesize", str(asset["size"]),
            "--output", str(part), asset["url"]]
    print("Downloading " + asset["id"], flush=True)
    p = subprocess.Popen(argv, env=portable_env(root), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        while p.poll() is None:
            require_space(root, 8*1024**2)
            if part.exists() and part.stat().st_size > asset["size"]:
                raise RuntimeError("Download exceeded pinned size")
            time.sleep(.25)
        if p.returncode:
            raise RuntimeError("Verified HTTPS download failed")
        if part.stat().st_size != asset["size"] or digest(part, algorithm) != asset[algorithm]:
            raise RuntimeError("VM asset checksum/size mismatch; download stays quarantined")
        part.replace(target)
        atomic_json(root / "Maintenance/Imports" / (asset["id"] + ".json"),
                    {**asset, "verified": True, "sha256": digest(target), "path": target.relative_to(root).as_posix()})
        return target
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--only", choices=[a["id"] for a in ASSETS])
    args = parser.parse_args()
    selected = [a for a in ASSETS if not args.only or a["id"] == args.only]
    if args.download:
        for asset in selected:
            print(fetch(asset), flush=True)
    else:
        print(json.dumps({"assets": selected, "space": require_space(ROOT, sum(a["size"]*6 for a in selected))}, indent=2))
