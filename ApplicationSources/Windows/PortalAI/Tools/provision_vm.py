"""Extract verified VM packages locally; no installer is executed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from import_vm_assets import ROOT, ASSETS, fetch, digest
from runtime_policy import atomic_json, portable_path, require_space

def record(dest, sources):
    receipt = {"verified": True, "destination": dest.relative_to(ROOT).as_posix(), "sources": sources,
               "files": [{"path": p.relative_to(dest).as_posix(), "sha256": digest(p)}
                         for p in sorted(dest.rglob("*")) if p.is_file()]}
    atomic_json(ROOT / "Maintenance/Imports" / (dest.name + "-payload.json"), receipt)
    return receipt

def extract(z, archive, dest, select):
    receipt = ROOT / "Maintenance/Imports" / (dest.name + "-payload.json")
    if dest.exists():
        if not receipt.exists():
            raise RuntimeError("Existing destination has no verification receipt: " + str(dest))
        info = json.loads(receipt.read_text())
        if not info.get("files") or not all(digest(portable_path(dest, r["path"])) == r["sha256"] for r in info["files"]):
            raise RuntimeError("Installed payload checksum mismatch")
        return
    output = subprocess.check_output([str(z), "l", "-slt", str(archive)], text=True)
    rows = []
    for block in output.split("----------\n", 1)[1].split("\n\n"):
        row = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" in row and select(row["Path"].replace("\\", "/")):
            rows.append(row)
    if not rows:
        raise RuntimeError("No selected archive members")
    require_space(ROOT, sum(int(r.get("Size") or 0) for r in rows))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-vm-", dir=ROOT / "Cache/imports/vm") as tmp:
        work = Path(tmp) / "payload"
        work.mkdir()
        for row in rows:
            portable_path(work, row["Path"])
            if row.get("Symbolic Link") or row.get("Hard Link"):
                raise RuntimeError("Archive links are not accepted")
        names = Path(tmp) / "members.txt"
        names.write_text("\n".join(r["Path"] for r in rows), encoding="utf-8")
        subprocess.run([str(z), "x", str(archive), "-o" + str(work), "-scsUTF-8", "@"+str(names), "-y"], check=True,
                       stdout=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        from portable_permissions import grant_runtime_read_execute
        stage = dest.with_name(dest.name+'-stage')
        if stage.exists(): raise RuntimeError('Retained VM stage requires review')
        work.rename(stage)
        grant_runtime_read_execute(ROOT, stage)
        stage.rename(dest)
    record(dest, [archive.name])

def main():
    assets = {a["id"]: fetch(a) for a in ASSETS}
    zdir = ROOT / "Tools/7zip"
    if zdir.exists() and not (ROOT / "Maintenance/Imports/7zip-payload.json").exists():
        # Bootstrap already extracted during this supervised first provisioning.
        # Re-extract a verified source to a new directory, compare every installed file.
        with tempfile.TemporaryDirectory(prefix="verify-7zip-", dir=ROOT / "Cache/imports/vm") as tmp:
            subprocess.run([str(assets["7zr-26.04"]), "x", str(assets["7zip-26.04"]), "-o"+tmp, "-y"], check=True, stdout=subprocess.DEVNULL)
            for p in zdir.rglob("*"):
                if p.is_file() and digest(p) != digest(Path(tmp) / p.relative_to(zdir)):
                    raise RuntimeError("7-Zip bootstrap mismatch")
        record(zdir, [assets["7zip-26.04"].name])
    extract(assets["7zr-26.04"], assets["7zip-26.04"], zdir,
            lambda p: p in {"7z.exe", "7z.dll", "License.txt", "readme.txt"})
    extract(zdir / "7z.exe", assets["qemu-20260811"], ROOT / "Runtime/QEMU/windows-x64",
            lambda p: ("/" not in p and (p.endswith(".dll") or p in {"qemu-system-x86_64.exe", "COPYING", "COPYING.LIB", "README.rst", "VERSION"}))
                      or p.startswith("share/"))
    extract(zdir / "7z.exe", assets["alpine-virt-3.24.2"], ROOT / "Runtime/VM/alpine-3.24.2",
            lambda p: p in {"boot/vmlinuz-virt", "boot/initramfs-virt", ".alpine-release"})
    print("Verified VM payloads are installed on the SSD.")

if __name__ == "__main__":
    main()
