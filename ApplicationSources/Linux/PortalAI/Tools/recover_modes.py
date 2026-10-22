"""Verify the mission-mode recovery snapshot; optionally restore changed source."""
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

CHANGED = ['Agent/mission_runner.py', 'ControlCenter/mission_settings.py', 'Agent/PORTABLEAI_COMMANDS.md', 'Agent/REFERENCE.md', 'Documentation/Portable_Foundation.txt', 'AGENTS.md']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, default=ROOT/"Backups/PortableModes_before_20261009_2210")
    p.add_argument("--restore-source", action="store_true", help="Close GUI and stop all missions/components first")
    args = p.parse_args()
    manifest = json.loads((args.snapshot/"manifest.json").read_text())
    archive = args.snapshot/"source.zip"
    with archive.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != manifest["sha256"]:
            raise RuntimeError("Recovery archive checksum mismatch")
    with zipfile.ZipFile(archive) as z:
        entries = {row["path"]: row for row in manifest["files"]}
        for name, row in entries.items():
            portable_path(ROOT, name)
            if hashlib.sha256(z.read(name)).hexdigest() != row["sha256"]:
                raise RuntimeError("Recovery entry mismatch: " + name)
        if args.restore_source:
            if running(): raise RuntimeError("Stop mission supervision first")
            for port in (8080, 8188, 8001, 8765):
                with socket.socket() as sock:
                    if sock.connect_ex(("127.0.0.1", port)) == 0:
                        raise RuntimeError("Close PortalAI and stop components before restoring")
            for path in (ROOT/"Data/Missions").glob("*/mission.json"):
                if json.loads(path.read_text()).get("status") in ("queued", "running", "waiting"):
                    raise RuntimeError("Pause all missions before restoring")
            if any(name not in entries for name in CHANGED): raise RuntimeError("Incomplete snapshot")
            for name in CHANGED:
                target = portable_path(ROOT, name)
                tmp = target.with_name(target.name+".recovery-part")
                tmp.write_bytes(z.read(name)); tmp.replace(target)
    print(json.dumps({"verified": True, "files": len(entries), "restored": CHANGED if args.restore_source else [],
                      "scope": "Changed source only. User data, weights, runtimes and new helper files remain. Not a full SSD backup."}))


if __name__ == "__main__": main()
