"""macOS desktop start/stop glue using the native POSIX managed-process layer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("start", "stop"), default="stop")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--requested-at", type=float)
    parser.add_argument("--include-opengui", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or args.root.resolve() != ROOT.resolve():
        raise SystemExit("macOS lifecycle is limited to this installed PortalAI root")
    from macos_job import preflight
    preflight()
    from linux_lifecycle import start_all, stop_all
    result = start_all(ROOT, args.requested_at) if args.action == "start" else stop_all(ROOT)
    print(json.dumps(result))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
