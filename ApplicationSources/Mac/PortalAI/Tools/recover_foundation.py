"""Verify the pre-change snapshot, or restore the six changed application files."""
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

CHANGED = ["Agent/ai_tools.py", "Agent/service_manager.py", "ControlCenter/native_chat.py",
           "ControlCenter/PortableAI_GUI.py", "Launchers/Start_PortableAI_Native_v15_133.py",
           "Launchers/Start_Secure_Agent_v15_53.ps1"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / "Backups/PortableFoundation_before_20261009_192304")
    parser.add_argument("--restore-source", action="store_true", help="Close PortalAI and stop its components first")
    args = parser.parse_args()
    manifest = json.loads((args.snapshot / "manifest.json").read_text(encoding="utf-8"))
    archive = args.snapshot / "snapshot.zip"
    with archive.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != manifest["archive_sha256"]:
            raise RuntimeError("Archive checksum mismatch")
    rows = {row["path"]: row for row in manifest["files"]}
    with zipfile.ZipFile(archive) as z:
        for name, row in rows.items():
            portable_path(ROOT, name)
            with z.open(name) as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != row["sha256"]:
                    raise RuntimeError("Snapshot entry checksum mismatch: " + name)
        print(json.dumps({"verified": True, "files": len(rows)}))
        if args.restore_source:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", 8080)) == 0:
                    raise RuntimeError("Stop PortalAI components and close its GUI before restoring source")
            for name in CHANGED:
                data = z.read(name)
                if hashlib.sha256(data).hexdigest() != rows[name]["sha256"]:
                    raise RuntimeError("Restore checksum mismatch")
                portable_path(ROOT, name).write_bytes(data)
            print(json.dumps({"restored_source": CHANGED,
                              "note": "New tools/models remain installed; existing code no longer imports the new policy."}))


if __name__ == "__main__":
    main()
