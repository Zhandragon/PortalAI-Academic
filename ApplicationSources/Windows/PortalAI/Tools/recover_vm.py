"""Verify the VM code snapshot; optionally restore the pre-VM source files."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import portable_path

CHANGED = ["Agent/mission_runner.py", "ControlCenter/PortableAI_GUI.py", "AGENTS.md",
           "Maintenance/Tests/test_mission_runner.py", "Documentation/Portable_Foundation.txt"]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / "Backups/PortableVM_before_20261009_195116")
    parser.add_argument("--restore-source", action="store_true", help="Close PortalAI and stop all components/workers first")
    args = parser.parse_args()
    data = json.loads((args.snapshot / "manifest.json").read_text(encoding="utf-8"))
    archive = args.snapshot / "source.zip"
    with archive.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != data["sha256"]:
            raise RuntimeError("VM recovery archive hash mismatch")
    with zipfile.ZipFile(archive) as z:
        names = {r["path"] for r in data["files"]}
        for row in data["files"]:
            portable_path(ROOT, row["path"])
            if hashlib.sha256(z.read(row["path"])).hexdigest() != row["sha256"]:
                raise RuntimeError("VM recovery entry hash mismatch: " + row["path"])
        print(json.dumps({"verified": True, "files": len(names)}))
        if args.restore_source:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", 8080)) == 0:
                    raise RuntimeError("Stop PortalAI components/workers and close the GUI before restoring")
            for path in (ROOT / "Data/Missions").glob("*/mission.json"):
                m = json.loads(path.read_text(encoding="utf-8"))
                if m.get("status") in {"queued", "running", "waiting"}:
                    raise RuntimeError("Stop/pause all active missions before restoring source")
            for name in CHANGED:
                if name not in names:
                    raise RuntimeError("Snapshot is missing " + name)
            for name in CHANGED:
                destination = portable_path(ROOT, name)
                temp = destination.with_name(destination.name + ".recovery-part")
                temp.write_bytes(z.read(name))
                temp.replace(destination)
            print(json.dumps({"restored": CHANGED, "note": "VM runtime, new helpers and all mission data remain; restored code no longer exposes VM missions."}))

if __name__ == "__main__":
    main()
