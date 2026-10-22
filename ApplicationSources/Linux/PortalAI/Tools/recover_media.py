"""Verify the media increment's recovery snapshot, or restore its previous source."""
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

CHANGED = ["Agent/ai_tools.py", "Agent/comfy_bridge.py", "Agent/stt_bridge.py", "Agent/stt_worker.py",
           "Agent/hardware_profiles.json", "Agent/REFERENCE.md", "Agent/PORTABLEAI_COMMANDS.md",
           "ControlCenter/model_settings.py", "Documentation/Portable_Foundation.txt"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT/"Backups/PortableMedia_before_20261009_202243")
    parser.add_argument("--restore-source", action="store_true", help="Close PortalAI and stop its components/workers first")
    args = parser.parse_args()
    manifest = json.loads((args.snapshot/"manifest.json").read_text(encoding="utf-8"))
    archive = args.snapshot/"source.zip"
    with archive.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != manifest["sha256"]:
            raise RuntimeError("Recovery archive checksum mismatch")
    with zipfile.ZipFile(archive) as z:
        entries = {row["path"]:row for row in manifest["files"]}
        for name, row in entries.items():
            portable_path(ROOT, name)
            if hashlib.sha256(z.read(name)).hexdigest() != row["sha256"]:
                raise RuntimeError("Recovery entry checksum mismatch: " + name)
        if args.restore_source:
            for port in (8080, 8188, 8001, 18188):
                with socket.socket() as sock:
                    if sock.connect_ex(("127.0.0.1", port)) == 0:
                        raise RuntimeError("Close PortalAI and stop all components/workers before restoring")
            for path in (ROOT/"Data/Missions").glob("*/mission.json"):
                if json.loads(path.read_text()).get("status") in ("queued", "running", "waiting"):
                    raise RuntimeError("Stop active missions before restoring")
            if any(name not in entries for name in CHANGED):
                raise RuntimeError("Snapshot is incomplete")
            for name in CHANGED:
                dest = portable_path(ROOT, name)
                tmp = dest.with_name(dest.name + ".recovery-part")
                tmp.write_bytes(z.read(name)); tmp.replace(dest)
        print(json.dumps({"verified": True, "files": len(entries), "restored": CHANGED if args.restore_source else [],
                          "scope": "Source only. New models, workflows, helpers, and user data remain. Not a complete SSD backup."}))


if __name__ == "__main__":
    main()
