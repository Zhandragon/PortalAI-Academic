"""Install pinned CPU speech assets into an isolated, relocatable SSD folder."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from runtime_policy import atomic_json, portable_path, require_space
from import_foundation_assets import install, sha256


def install_packages(root, assets):
    dest = root/"Voice/Piper/packages"
    receipt = root/"Maintenance/Imports/piper-packages.json"
    if dest.exists():
        old = json.loads(receipt.read_text()) if receipt.exists() else {}
        if not old.get("installed_files") or not all(portable_path(dest, x["path"]).is_file() and
            sha256(portable_path(dest, x["path"])) == x["sha256"] for x in old["installed_files"]):
            raise RuntimeError("Existing Piper package folder does not match its verified receipt")
        return {"status": "verified-existing", "files": len(old["installed_files"])}
    wheels = [portable_path(root, a["dest"]) for a in assets if a["kind"] == "wheel"]
    expanded = 0
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as z: expanded += sum(x.file_size for x in z.infolist())
    require_space(root, expanded)
    staging = root/"Cache/imports"; staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="piper-packages-", dir=staging) as tmp:
        payload = Path(tmp)/"packages"; payload.mkdir()
        for wheel in wheels:
            with zipfile.ZipFile(wheel) as z:
                for member in z.infolist():
                    out = portable_path(payload, member.filename)
                    license_data = member.filename.endswith(".data/data/COPYING")
                    if (member.external_attr >> 16) & 0o170000 == 0o120000 or (".data/" in member.filename and not license_data):
                        raise ValueError("Unsupported wheel member: " + member.filename)
                    if member.is_dir(): continue
                    if out.exists(): raise ValueError("Conflicting wheel member: " + member.filename)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, out.open("wb") as dst: shutil.copyfileobj(src, dst)
        rows = [{"path": p.relative_to(payload).as_posix(), "sha256": sha256(p)} for p in payload.rglob("*") if p.is_file()]
        atomic_json(receipt, {"verified": True, "installed_files": rows, "expanded_bytes": expanded,
                             "method": "Verified wheel payloads; no generated absolute-path console launchers"})
        from portable_permissions import grant_runtime_read_execute
        stage = dest.with_name(dest.name+'-stage')
        if stage.exists(): raise RuntimeError('Retained Piper stage requires review')
        payload.rename(stage)
        grant_runtime_read_execute(root, stage)
        stage.rename(dest)
    return {"status": "installed-verified", "files": len(rows), "expanded_bytes": expanded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT/"Agent/voice_assets.json").read_text())
    assets = lock["assets"]
    budget = require_space(ROOT, sum(a["size"] for a in assets)*6)
    if not args.install:
        print(json.dumps({"assets": assets, "budget": budget}, indent=2)); return
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("These packages require the bundled Windows x64 Python 3.12")
    for a in assets:
        # An explicitly staged HF CLI download is still verified before activation.
        staged = ROOT/"Cache/imports/piper-voice-fetch"/a.get("filename", "missing")
        dest = portable_path(ROOT, a["dest"])
        if a["kind"] == "model" and staged.is_file() and not dest.exists():
            if staged.stat().st_size != a["size"] or sha256(staged) != a["sha256"]:
                raise RuntimeError("HF staged model failed pinned checksum/size verification")
            require_space(ROOT, a["size"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, dest)
            atomic_json(ROOT/"Maintenance/Imports"/(a["id"]+".json"), {**a, "verified": True, "source": "hf download pinned revision"})
            print(json.dumps({"id": a["id"], "status": "installed-verified"}), flush=True)
        else: print(json.dumps(install(a)), flush=True)
    print(json.dumps(install_packages(ROOT, assets)))


if __name__ == "__main__": main()
