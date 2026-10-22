"""Verify handoff/scan recovery copies; optionally restore this increment's source."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from runtime_policy import portable_path
from mission_supervisor import running

CHANGED = {
    "PortableHandoff_before_20261009": ["Agent/service_manager.py", "ControlCenter/native_chat.py", "Documentation/Portable_Foundation.txt", "AGENTS.md"],
    "PortableScan_before_20261009": ["SecureAgent/Updater/rollback_secureagent_parity_v15_43.py", "SecureAgent/Updater/test_secureagent_parity_v15_43.py"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", type=Path, default=ROOT/"Backups")
    parser.add_argument("--restore-source", action="store_true", help="Close GUI and stop all missions/components first")
    args = parser.parse_args()
    verified, restore = [], {}
    for folder, changed in CHANGED.items():
        snapshot = args.backup_root/folder
        manifest = json.loads((snapshot/"manifest.json").read_text(encoding="utf-8"))
        archive = snapshot/"source.zip"
        with archive.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != manifest["sha256"]:
                raise RuntimeError("Archive checksum mismatch: " + folder)
        with zipfile.ZipFile(archive) as z:
            entries = {r["path"]: r for r in manifest["files"]}
            for name, row in entries.items():
                portable_path(ROOT, name)
                if hashlib.sha256(z.read(name)).hexdigest() != row["sha256"]:
                    raise RuntimeError("Entry checksum mismatch: " + name)
            if any(name not in entries for name in changed): raise RuntimeError("Incomplete snapshot: " + folder)
            restore.update({name: z.read(name) for name in changed})
        verified.append({"snapshot": str(snapshot), "files": len(entries), "sha256": manifest["sha256"]})
    if args.restore_source:
        if running(): raise RuntimeError("Stop mission supervision first")
        for port in (8080, 8188, 8001, 8765):
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    raise RuntimeError("Close PortalAI and stop components before restoring")
        for path in (ROOT/"Data/Missions").glob("*/mission.json"):
            if json.loads(path.read_text()).get("status") in ("queued", "running", "waiting"):
                raise RuntimeError("Pause all missions before restoring")
        for name, data in restore.items():
            target = portable_path(ROOT, name)
            tmp = target.with_name(target.name+".recovery-part")
            tmp.write_bytes(data); tmp.replace(target)
    print(json.dumps({"verified": verified, "restored": list(restore) if args.restore_source else [],
                      "scope": "Selected changed source only. User data, new helper files, weights and runtimes remain. Not a full SSD backup."}))


if __name__ == "__main__": main()
