#!/usr/bin/env python3
"""Install checksum-verified macOS GUI and account wheel layers."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "Runtime/MacPython/bin/python3.12"
def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalized(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def pins_for(kind: str) -> dict[str, str]:
    if kind == "gui":
        data = json.loads((ROOT / "Maintenance/Imports/macos-gui-pins.json").read_text())
        return {normalized(k): str(v) for k, v in data.items()}
    if kind == "accounts":
        data = json.loads((ROOT / "Maintenance/Imports/macos-account-pins.json").read_text())
        return {normalized(k): str(v) for k, v in data.items()}
    raise ValueError("Unknown macOS runtime layer")


def verify_wheel(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        total = 0
        for item in members:
            rel = PurePosixPath(item.filename)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts or item.file_size > 4 * 1024**3:
                raise ValueError("Unsafe or oversized wheel member: " + item.filename)
            total += item.file_size
        records = [name for name in archive.namelist()
                   if name.endswith(".dist-info/RECORD") and name.count("/") == 1]
        if len(records) != 1:
            raise RuntimeError("Wheel has a missing or ambiguous RECORD: " + path.name)
        for name, checksum, size in csv.reader(io.StringIO(archive.read(records[0]).decode("utf-8"))):
            if not checksum:
                continue
            algorithm, expected = checksum.split("=", 1)
            if algorithm != "sha256":
                raise ValueError("Unexpected wheel RECORD hash algorithm")
            blob = archive.read(name)
            actual = base64.urlsafe_b64encode(hashlib.sha256(blob).digest()).rstrip(b"=").decode()
            if actual != expected or len(blob) != int(size):
                raise RuntimeError("Wheel RECORD entry failed verification: " + name)
        return total


def portable_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__",
                "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               PIP_CACHE_DIR=str(ROOT / "Cache/pip"), TMPDIR=str(ROOT / "Cache/tmp"))
    (ROOT / "Cache/tmp").mkdir(parents=True, exist_ok=True)
    return env


def install_layer(kind: str) -> dict:
    destination = (ROOT / ("Runtime/MacPackages/gui" if kind == "gui" else
                           "Runtime/AccountPython/macos-packages"))
    if destination.exists():
        raise RuntimeError(f"The macOS {kind} layer already exists; verify it instead of replacing it")
    pins = pins_for(kind)
    report_path = ROOT / f"Cache/macos-{kind}-resolution.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(PYTHON), "-B", "-m", "pip", "install", "--dry-run", "--ignore-installed",
               "--only-binary=:all:", "--no-deps", "--report", str(report_path),
               *(f"{name.replace('_', '-') }=={version}" for name, version in pins.items())]
    subprocess.run(command, cwd=ROOT, env=portable_env(), check=True, timeout=240)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = report.get("install", [])
    found = {normalized(row["metadata"]["name"]): str(row["metadata"]["version"]) for row in rows}
    if found != pins:
        raise RuntimeError(f"macOS {kind} wheel resolution does not match the reviewed versions")

    wheelhouse = ROOT / f"Cache/macos-{kind}-wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    locked = []
    assets = []
    expanded = 0
    for row in rows:
        metadata = row["metadata"]
        name, version = metadata["name"], str(metadata["version"])
        info = row["download_info"]
        url = info["url"]
        parsed = urllib.parse.urlsplit(url)
        filename = urllib.parse.unquote(Path(parsed.path).name)
        if parsed.scheme != "https" or parsed.hostname != "files.pythonhosted.org" or not filename.endswith(".whl"):
            raise ValueError("Unexpected macOS wheel source")
        with urllib.request.urlopen(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{version}/json", timeout=45) as src:
            published = json.load(src)
        artifact = next((asset for asset in published["urls"] if asset["filename"] == filename), None)
        if artifact is None:
            raise RuntimeError("Resolved wheel is not in the PyPI release metadata")
        size, sha = int(artifact["size"]), artifact["digests"]["sha256"]
        if info.get("archive_info", {}).get("hashes", {}).get("sha256") != sha:
            raise RuntimeError("pip and PyPI disagree on the wheel checksum")
        target = wheelhouse / filename
        if not target.exists():
            part = target.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60) as src, part.open("wb") as out:
                total = 0
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    total += len(block)
                    if total > size:
                        raise RuntimeError("Wheel exceeded its published size")
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            if part.stat().st_size != size or digest(part) != sha:
                raise RuntimeError("Downloaded wheel failed published size/SHA-256 verification")
            part.replace(target)
        if target.stat().st_size != size or digest(target) != sha:
            raise RuntimeError("Cached wheel differs from its publisher metadata")
        expanded += verify_wheel(target)
        locked.append(f"{target.as_uri()} --hash=sha256:{sha}")
        assets.append({"name": name, "version": version, "wheel": filename,
                       "bytes": size, "sha256": sha, "url": url})

    from runtime_policy import require_space
    require_space(ROOT, expanded * 2 + 256 * 1024**2)
    requirements = wheelhouse / "locked.txt"
    requirements.write_text("\n".join(locked) + "\n", encoding="utf-8")
    stage = destination.with_name(destination.name + "-stage")
    if stage.exists():
        raise RuntimeError("An earlier macOS package staging directory requires review")
    subprocess.run([str(PYTHON), "-B", "-m", "pip", "install", "--no-index", "--no-deps",
                    "--no-compile", "--only-binary=:all:", "--require-hashes", "--target", str(stage),
                    "-r", str(requirements)], cwd=ROOT, env=portable_env(), check=True, timeout=300)
    files = [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size,
              "sha256": digest(path)} for path in sorted(stage.rglob("*")) if path.is_file()]
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage, destination)
    receipt = {"python": "3.12", "platform": f"macOS {os.uname().machine}",
               "status": "installed-dependencies-only", "assets": assets,
               "files": files, "expanded_bytes": expanded,
               "hash_provenance": "PyPI published wheel size and SHA-256 plus wheel RECORD verification"}
    receipt_path = ROOT / f"Maintenance/Imports/macos-{kind}-lock.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return {"layer": kind, "files": len(files), "expanded_bytes": expanded}


def main() -> int:
    if sys.platform != "darwin" or os.name == "nt":
        raise RuntimeError("This dependency installer must run on macOS")
    if os.geteuid() == 0:
        raise RuntimeError("Run the PortalAI installer as a regular user, not with sudo")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("PortalAI's macOS runtime layers require bundled Python 3.12")
    root = ROOT.resolve()
    gui = install_layer("gui")
    accounts = install_layer("accounts")
    sys.path[:0] = [str(root / "Runtime/MacPackages/gui"),
                    str(root / "Runtime/AccountPython/macos-packages"), str(root / "Agent")]
    import tkinter
    import PIL
    import psutil
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import mission_schedule
    import mission_supervisor
    from local_accounts import _crypto
    aes, _ = _crypto()
    if aes is not AESGCM:
        raise RuntimeError("PortalAI account cryptography did not load from its verified local layer")
    print(json.dumps({"installed": True, "gui": gui, "accounts": accounts,
                      "tk": tkinter.Tcl().eval("info patchlevel"), "pillow": PIL.__version__,
                      "psutil": psutil.__version__, "mission_schedule": hasattr(mission_schedule, "Schedules"),
                      "mission_supervisor": mission_supervisor.__file__}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        print(f"PortalAI macOS runtime installer: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
