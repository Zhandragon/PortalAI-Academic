#!/usr/bin/env python3
"""Build a clean Linux x86-64 installer from the released source payload and verified runtimes."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "Utilities/PortalAI Windows Installer/payload.zip"
DEFAULT_OUTPUT = ROOT.parent / "Utilities/PortalAI Linux Installer"
RUNTIME = ROOT / "Runtime/LinuxPython"
LLAMA = ROOT / "LLM/backends/linux-cpu"
QEMU = ROOT / "Runtime/QEMU/linux-x64"
QEMU_RECEIPT = ROOT / "Maintenance/Imports/linux-x64-payload.json"
PYTHON_RECEIPT = ROOT / "Maintenance/Imports/linux-python.json"
INSTALLER_RECEIPT = "PortalAI/Maintenance/Imports/linux-clean-installer-r14.json"
LAUNCHER = ROOT / "Runtime/LinuxPython/run-python"
BLOCKED_SUFFIXES = {
    ".exe", ".dll", ".pyd", ".cmd", ".bat", ".ps1", ".msi", ".lnk",
    ".sys", ".dylib", ".whl", ".pdb", ".lib", ".obj", ".o",
}
BLOCKED_TOP_LEVEL = {"Utilities"}
BLOCKED_PARTS = {
    "Backups", "Cache", "Data", "Outputs", "Private", "User Folder",
    ".runtime", ".git", "__pycache__",
}
BLOCKED_PREFIXES = (
    "PortalAI/Runtime/Web/",
    "PortalAI/Runtime/BootstrapPython/",
    "PortalAI/Runtime/ScientificPython/",
    "PortalAI/Runtime/AccountPython/",
    "PortalAI/Runtime/LinuxPython/",
    "PortalAI/Runtime/LinuxPackages/",
    "PortalAI/Runtime/LinuxSystem/",
    "PortalAI/Runtime/LinuxTorch/",
    "PortalAI/Runtime/AMDPython/",
    "PortalAI/Runtime/AMDAudio/",
    "PortalAI/Runtime/AMDMusic/",
    "PortalAI/Runtime/StableDiffusion/windows-",
    "PortalAI/Runtime/FFmpeg/windows-",
    "PortalAI/Runtime/QEMU/",
    "PortalAI/Runtime/KiCad/",
    "PortalAI/LLM/backends/",
    "PortalAI/Documentation/Business-Mission/",
    "PortalAI/Maintenance/Validation/",
    "PortalAI/Maintenance/Patches/",
    "PortalAI/Maintenance/Archive/",
    "PortalAI/Maintenance/Reports/",
    "PortalAI/Tools/KiCad/",
    "PortalAI/Installer/",
)
SCRIPT_SUFFIXES = {".sh"}
EXECUTABLES = {
    "PortalAI/PortalAI.sh",
    "PortalAI/Launchers/portalai.sh",
    "PortalAI/Launchers/portalai-missions.sh",
    "PortalAI/Launchers/DrivePortalAI.sh",
}


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts or ":" in path.parts[0]:
        raise ValueError(f"Unsafe package path: {value}")
    return path


def add_tar_file(archive: tarfile.TarFile, name: str, source, size: int, mode: int) -> None:
    rel = safe_relative(name)
    info = tarfile.TarInfo(rel.as_posix())
    info.size = size
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    if isinstance(source, bytes):
        import io
        archive.addfile(info, io.BytesIO(source))
    else:
        with Path(source).open("rb") as stream:
            archive.addfile(info, stream)


def write_tar_gz(destination: Path, entries) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name, source, size, mode in entries:
                    add_tar_file(archive, name, source, size, mode)


def verify_source_payload(source: Path, installer_dir: Path) -> tuple[str, str]:
    digest_file = installer_dir / "PACKAGE_SHA256.json"
    if not digest_file.is_file():
        raise FileNotFoundError(f"Missing clean installer checksum manifest: {digest_file}")
    rows = json.loads(digest_file.read_text(encoding="utf-8"))
    expected = next((row["sha256"] for row in rows if row.get("path") == "payload.zip"), None)
    if not expected or sha_file(source) != expected:
        raise RuntimeError("Windows clean source payload does not match its published package checksum")
    start = (installer_dir / "START_HERE.txt").read_text(encoding="utf-8")
    match = re.search(r"^Package:\s*(.+)$", start, re.MULTILINE)
    release = match.group(1).strip() if match else "PortalAI clean payload"
    return expected, release


def verify_receipt_tree(base: Path, receipt_path: Path, *, destination: str | None = None,
                        rows_key: str = "files", skip_pycache: bool = False) -> list[dict]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    dest = destination or receipt.get("destination") or receipt.get("dest")
    if not dest:
        raise RuntimeError(f"Receipt has no destination: {receipt_path}")
    rows = receipt.get(rows_key)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Receipt has no {rows_key}: {receipt_path}")
    actual_root = (ROOT / dest).resolve()
    if not actual_root.is_relative_to(ROOT.resolve()):
        raise RuntimeError(f"Receipt escaped the portable root: {receipt_path}")
    result = []
    for row in rows:
        rel = safe_relative(row.get("path", ""))
        if skip_pycache and "__pycache__" in rel.parts:
            continue
        path = actual_root.joinpath(*rel.parts)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Verified asset is missing or linked: {path}")
        size = path.stat().st_size
        if row.get("bytes") is not None and size != int(row["bytes"]):
            raise RuntimeError(f"Asset byte count differs: {path}")
        expected = row.get("sha256")
        actual = sha_file(path)
        if expected and actual != expected:
            raise RuntimeError(f"Asset checksum differs: {path}")
        result.append({"path": rel.as_posix(), "bytes": size, "sha256": actual})
    return result


def verify_python_runtime() -> list[dict]:
    receipt = json.loads(PYTHON_RECEIPT.read_text(encoding="utf-8"))
    if not receipt.get("verified") or receipt.get("sha256") != "ffa8f85f1b56e88b687f08d743d817015524b86a9365fd921243132b80f1a36d":
        raise RuntimeError("The Linux standalone Python receipt is not the reviewed release")
    rows = receipt.get("installed_files", [])
    if not rows:
        raise RuntimeError("The Linux Python receipt has no installed-file hashes")
    verified = verify_receipt_tree(ROOT, PYTHON_RECEIPT, destination="Runtime/LinuxPython",
                                   rows_key="installed_files", skip_pycache=True)
    if len(verified) != sum("__pycache__" not in PurePosixPath(row["path"]).parts for row in rows):
        raise RuntimeError("Linux Python receipt file count changed")
    actual = {p.relative_to(RUNTIME).as_posix() for p in RUNTIME.rglob("*")
              if p.is_file() and "__pycache__" not in p.parts}
    expected = {row["path"] for row in rows if "__pycache__" not in PurePosixPath(row["path"]).parts} | {"run-python"}
    if actual != expected:
        raise RuntimeError("Linux Python runtime contains missing or unrecorded files")
    if not LAUNCHER.is_file() or LAUNCHER.is_symlink():
        raise RuntimeError("The bundled Linux Python launcher is missing or linked")
    return verified


def verify_qemu() -> list[dict]:
    receipt = json.loads(QEMU_RECEIPT.read_text(encoding="utf-8"))
    if not receipt.get("verified"):
        raise RuntimeError("The Linux QEMU payload has no verified receipt")
    return verify_receipt_tree(ROOT, QEMU_RECEIPT, destination="Runtime/QEMU/linux-x64")


def file_mode(name: str) -> int:
    if name in EXECUTABLES or name.endswith(".sh"):
        return 0o755
    return 0o644


def code_payload_entries(source: Path, source_sha: str, release: str,
                         linux_receipts: list[tuple[str, Path, bytes]],
                         backend_files: list[dict], qemu_files: list[dict],
                         installer_script: Path) -> tuple[list, int, int]:
    entries = []
    included = skipped = 0
    seen: set[str] = set()
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            raw = item.filename
            if item.is_dir():
                continue
            rel = safe_relative(raw)
            if rel.parts[0] in BLOCKED_TOP_LEVEL or rel.parts[0] != "PortalAI":
                skipped += 1
                continue
            if rel.suffix.lower() in BLOCKED_SUFFIXES or rel.suffix.lower() == ".so":
                skipped += 1
                continue
            if any(part in BLOCKED_PARTS for part in rel.parts):
                skipped += 1
                continue
            name = rel.as_posix()
            # These explicit local overlays may also be present in a newer
            # Windows source release. Include their current bytes exactly once.
            if name in {"PortalAI/README.md",
                        "PortalAI/Documentation/Linux_Clean_Installer_20261017.txt",
                        "PortalAI/Documentation/Mac_Compatibility_Review_20261017.txt"}:
                skipped += 1
                continue
            if name.startswith(BLOCKED_PREFIXES):
                skipped += 1
                continue
            if name.startswith("PortalAI/LLM/models/") and not name.startswith("PortalAI/LLM/models/licenses/"):
                skipped += 1
                continue
            if name == "PortalAI/Tools/install_linux_clean.py":
                skipped += 1
                continue
            mode = (item.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError(f"Symlink found in clean source payload: {name}")
            if name in seen:
                raise RuntimeError(f"Duplicate source file: {name}")
            entries.append((name, archive.read(item), item.file_size, file_mode(name)))
            seen.add(name)
            included += 1

    def add_bytes(name: str, data: bytes, mode: int = 0o644):
        if name in seen:
            raise RuntimeError(f"Installer payload collision: {name}")
        entries.append((name, data, len(data), mode))
        seen.add(name)

    add_bytes("PortalAI/Tools/install_linux_clean.py", installer_script.read_bytes(), 0o644)
    add_bytes("PortalAI/README.md", (ROOT / "README.md").read_bytes(), 0o644)
    for doc_name in ("Linux_Clean_Installer_20261017.txt", "Mac_Compatibility_Review_20261017.txt"):
        doc_path = ROOT / "Documentation" / doc_name
        add_bytes("PortalAI/Documentation/" + doc_name, doc_path.read_bytes(), 0o644)
    for name, path, data in linux_receipts:
        add_bytes(name, data, 0o644)
    for row in backend_files:
        path = LLAMA / row["path"]
        name = "PortalAI/LLM/backends/linux-cpu/" + row["path"]
        mode = 0o755 if Path(row["path"]).suffix == "" else 0o644
        entries.append((name, path, row["bytes"], mode))
        seen.add(name)
    for row in qemu_files:
        path = QEMU / row["path"]
        name = "PortalAI/Runtime/QEMU/linux-x64/" + row["path"]
        mode = 0o755 if Path(row["path"]).suffix == "" else 0o644
        entries.append((name, path, row["bytes"], mode))
        seen.add(name)
    run_python = LAUNCHER.read_bytes()
    add_bytes("PortalAI/Runtime/LinuxPython/run-python", run_python, 0o755)
    from web_installer_assets import files as web_files
    for name, path in web_files(ROOT, 'Linux'):
        if name in seen:raise RuntimeError('Duplicate web runtime file: '+name)
        entries.append((name,path,path.stat().st_size,0o755 if path.name in ('node','patchelf') else 0o644))
        seen.add(name)
    receipt = {
        "installer_release": "PortalAI-2026.10.19-Linux-x86_64-r14",
        "source_release": release,
        "source_payload_sha256": source_sha,
        "platform": "Linux x86-64; glibc >= 2.28",
        "cpu_backend_files": backend_files,
        "qemu_source_receipt": "Maintenance/Imports/linux-x64-payload.json",
        "python_source_receipt": "Maintenance/Imports/linux-python.json",
        "runtime_python_launcher_sha256": sha_bytes(run_python),
        "owner_data_included": False,
        "model_weights_included": False,
        "optional_torch_media_science_layers_included": False,
    }
    add_bytes(INSTALLER_RECEIPT, json.dumps(receipt, indent=2).encode("utf-8") + b"\n")
    return entries, included, skipped


def verify_bundle(bundle_path: Path) -> dict:
    """Re-open the finished artifact and verify its paths, checksums, and platform exclusions."""
    import io
    with tarfile.open(bundle_path, "r:gz") as outer:
        members = outer.getmembers()
        files = {}
        prefix = "PortalAI-Linux-Clean-Installer-r14/"
        for member in members:
            rel = safe_relative(member.name)
            if not member.isfile() or member.issym() or member.islnk():
                raise RuntimeError(f"Unexpected non-file in installer archive: {member.name}")
            if not member.name.startswith(prefix):
                raise RuntimeError(f"Unexpected installer archive root: {member.name}")
            files[member.name[len(prefix):]] = member
        expected_outer = {"install.sh", "README.txt", "manifest.json", "SHA256SUMS",
                          "payload.tar.gz", "python-runtime.tar.gz"}
        if set(files) != expected_outer:
            raise RuntimeError("Installer archive contents differ from the reviewed set")
        def read(name: str) -> bytes:
            return outer.extractfile(files[name]).read()
        install_text = read("install.sh").decode("utf-8")
        if 'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)' not in install_text or \
                'DEST="${1:-${PORTALAI_INSTALL_DIR:-$SCRIPT_DIR/PortalAI Linux}}"' not in install_text:
            raise RuntimeError("Linux installer no longer defaults inside its script folder")
        if ".portalai-exec-check." not in install_text:
            raise RuntimeError("Linux installer is missing the executable-filesystem preflight")
        manifest = json.loads(read("manifest.json"))
        if manifest.get("status") != "BUILT_NOT_FULL_RECIPIENT_INSTALL_TESTED":
            raise RuntimeError("Installer manifest claims an unverified release status")
        if files["install.sh"].mode & 0o111 == 0:
            raise RuntimeError("Linux install.sh is not executable")
        sums = {}
        for line in read("SHA256SUMS").decode("ascii").splitlines():
            digest, name = line.split(None, 1)
            sums[name.strip()] = digest
        for name in ("payload.tar.gz", "python-runtime.tar.gz"):
            if sums.get(name) != sha_bytes(read(name)):
                raise RuntimeError(f"Nested archive checksum differs: {name}")

        payload_blob = read("payload.tar.gz")
        with tarfile.open(fileobj=io.BytesIO(payload_blob), mode="r:gz") as payload:
            payload_members = payload.getmembers()
            payload_files = {}
            for member in payload_members:
                rel = safe_relative(member.name)
                if not member.isfile() or member.issym() or member.islnk():
                    raise RuntimeError(f"Unexpected non-file in app payload: {member.name}")
                if rel.suffix.lower() in BLOCKED_SUFFIXES or (
                    rel.suffix.lower() == ".so" and not member.name.startswith((
                        "PortalAI/LLM/backends/linux-cpu/",
                        "PortalAI/Runtime/QEMU/linux-x64/",
                        "PortalAI/Runtime/Web/linux-x64/",
                    ))
                ):
                    raise RuntimeError(f"Windows/native foreign file in source payload: {member.name}")
                if any(part in BLOCKED_PARTS for part in rel.parts):
                    raise RuntimeError(f"Owner data path in source payload: {member.name}")
                if member.name.startswith("PortalAI/Documentation/Business-Mission/"):
                    raise RuntimeError("Owner mission documentation entered the clean payload")
                if member.name.startswith("PortalAI/LLM/models/") and not member.name.startswith("PortalAI/LLM/models/licenses/"):
                    raise RuntimeError("Model weights entered the clean payload")
                payload_files[member.name] = member
            required = (
                "PortalAI/README.md",
                "PortalAI/PortalAI.sh",
                "PortalAI/Tools/install_linux_clean.py",
                "PortalAI/Runtime/LinuxPython/run-python",
                "PortalAI/Runtime/QEMU/linux-x64/bin/qemu-system-x86_64",
                "PortalAI/LLM/backends/linux-cpu/llama-server",
                "PortalAI/Maintenance/Imports/linux-python.json",
                "PortalAI/Maintenance/Imports/linux-x64-payload.json",
                "PortalAI/Maintenance/Imports/linux-clean-installer-r14.json",
                "PortalAI/Documentation/Linux_Clean_Installer_20261017.txt",
                "PortalAI/Documentation/Mac_Compatibility_Review_20261017.txt",
            )
            missing = [name for name in required if name not in payload_files]
            if missing:
                raise RuntimeError("Required Linux payload files are missing: " + ", ".join(missing))
            readme = payload.extractfile(payload_files["PortalAI/README.md"]).read().decode("utf-8")
            if "installer's own folder" not in readme or "NTFS" not in readme:
                raise RuntimeError("Linux app README does not describe portable install placement")
            py_receipt = json.loads(payload.extractfile(
                payload_files["PortalAI/Maintenance/Imports/linux-python.json"]).read())
            package_receipt = json.loads(payload.extractfile(
                payload_files["PortalAI/Maintenance/Imports/linux-clean-installer-r14.json"]).read())
            qemu_receipt = json.loads(payload.extractfile(
                payload_files["PortalAI/Maintenance/Imports/linux-x64-payload.json"]).read())
            backend_rows = package_receipt["cpu_backend_files"]
            if len(backend_rows) != manifest["components"]["linux-cpu-llama-backend"]["files"]:
                raise RuntimeError("CPU backend manifest count differs")
            for row in backend_rows:
                member = payload_files.get("PortalAI/LLM/backends/linux-cpu/" + row["path"])
                if member is None or member.size != row["bytes"]:
                    raise RuntimeError("Missing CPU llama.cpp file: " + row["path"])
                if hashlib.sha256(payload.extractfile(member).read()).hexdigest() != row["sha256"]:
                    raise RuntimeError("CPU llama.cpp checksum differs: " + row["path"])
            for row in qemu_receipt["files"]:
                member = payload_files.get("PortalAI/Runtime/QEMU/linux-x64/" + row["path"])
                if member is None:
                    raise RuntimeError("Missing verified QEMU file: " + row["path"])
                blob = payload.extractfile(member).read()
                if len(blob) != member.size or hashlib.sha256(blob).hexdigest() != row["sha256"]:
                    raise RuntimeError("QEMU checksum differs: " + row["path"])
            python_rows = py_receipt["installed_files"]
            source_files = len(payload_files)

        python_blob = read("python-runtime.tar.gz")
        with tarfile.open(fileobj=io.BytesIO(python_blob), mode="r:gz") as python_archive:
            python_members = {member.name: member for member in python_archive.getmembers()}
            if "LinuxPython/bin/python3" not in python_members or "LinuxPython/run-python" not in python_members:
                raise RuntimeError("Bundled Linux Python entry points are missing")
            if python_members["LinuxPython/bin/python3"].mode & 0o111 == 0:
                raise RuntimeError("Bundled Python is not executable")
            verified_python = 0
            for row in python_rows:
                rel = PurePosixPath(row["path"])
                if "__pycache__" in rel.parts:
                    continue
                member = python_members.get("LinuxPython/" + rel.as_posix())
                if member is None:
                    raise RuntimeError("Bundled Python file is missing: " + rel.as_posix())
                blob = python_archive.extractfile(member).read()
                if hashlib.sha256(blob).hexdigest() != row["sha256"]:
                    raise RuntimeError("Bundled Python checksum differs: " + rel.as_posix())
                verified_python += 1
        return {"passed": True, "source_files": source_files,
                "python_files_verified": verified_python,
                "cpu_backend_files_verified": len(backend_rows),
                "qemu_files_verified": len(qemu_receipt["files"]),
                "windows_native_files": 0, "owner_data_files": 0,
                "physical_install_tested": False}

def build(options) -> dict:
    source = Path(options.source_payload).resolve()
    installer_dir = source.parent
    source_sha, release = verify_source_payload(source, installer_dir)
    installer_source = ROOT / "Installer/Linux"
    for required in ("install.sh", "README.txt"):
        if not (installer_source / required).is_file():
            raise FileNotFoundError(installer_source / required)

    python_files = verify_python_runtime()
    qemu_files = verify_qemu()
    backend_files = []
    if not LLAMA.is_dir():
        raise FileNotFoundError(f"Missing Linux CPU llama.cpp backend: {LLAMA}")
    for path in sorted(LLAMA.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Linked Linux CPU backend file is not packageable: {path}")
        if path.is_file():
            relative = path.relative_to(LLAMA).as_posix()
            backend_files.append({"path": relative, "bytes": path.stat().st_size,
                                 "sha256": sha_file(path)})
    if not backend_files or not any(row["path"] == "llama-server" for row in backend_files):
        raise RuntimeError("The Linux CPU llama-server executable is missing")
    entries, source_count, skipped_count = code_payload_entries(
        source, source_sha, release,
        [
            ("PortalAI/Maintenance/Imports/linux-python.json", PYTHON_RECEIPT,
             PYTHON_RECEIPT.read_bytes()),
            ("PortalAI/Maintenance/Imports/linux-x64-payload.json", QEMU_RECEIPT,
             QEMU_RECEIPT.read_bytes()),
        ],
        backend_files, qemu_files, ROOT / "Tools/install_linux_clean.py")
    base = Path(options.output_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    package_name = "PortalAI-Linux-Clean-Installer-20261019-r14-x86_64.tar.gz"
    output_file = base / package_name
    checksum = base / (package_name + ".sha256")
    sidecars = [base / "manifest.json", base / "README.txt", base / "SHA256SUMS"]
    conflicts = [path for path in [output_file, checksum, *sidecars] if path.exists()]
    if conflicts:
        raise FileExistsError("Refusing to overwrite existing installer output: " +
                              ", ".join(str(path) for path in conflicts))
    temp_dir = Path(tempfile.mkdtemp(prefix=".portalai-linux-build-", dir=base))
    try:
        payload = temp_dir / "payload.tar.gz"
        write_tar_gz(payload, entries)
        python_tar = temp_dir / "python-runtime.tar.gz"
        python_entries = []
        receipt_rows = {row["path"]: row for row in json.loads(
            PYTHON_RECEIPT.read_text(encoding="utf-8"))["installed_files"]}
        for relative, row in receipt_rows.items():
            if "__pycache__" in PurePosixPath(relative).parts:
                continue
            path = RUNTIME / relative
            mode = 0o755 if relative.startswith("bin/") else 0o644
            python_entries.append(("LinuxPython/" + relative, path, path.stat().st_size, mode))
        python_entries.append(("LinuxPython/run-python", LAUNCHER, LAUNCHER.stat().st_size, 0o755))
        write_tar_gz(python_tar, python_entries)

        payload_hash, python_hash = sha_file(payload), sha_file(python_tar)
        manifest = {
            "schema": 1,
            "release": "PortalAI-2026.10.19-Linux-x86_64-r14",
            "status": "BUILT_NOT_FULL_RECIPIENT_INSTALL_TESTED",
            "platform": "Linux x86-64, glibc >= 2.28",
            "built_utc": datetime.now(timezone.utc).isoformat(),
            "source_release": release,
            "source_payload": {"file_name": source.name, "bytes": source.stat().st_size,
                               "sha256": source_sha, "included_files": source_count,
                               "excluded_files": skipped_count},
            "components": {
                "payload.tar.gz": {"bytes": payload.stat().st_size, "sha256": payload_hash},
                "python-runtime.tar.gz": {"bytes": python_tar.stat().st_size,
                                          "sha256": python_hash,
                                          "python_files": len(python_files) + 1},
                "linux-cpu-llama-backend": {"files": len(backend_files),
                                            "bytes": sum(row["bytes"] for row in backend_files),
                                            "sha256_manifest": sha_bytes(json.dumps(
                                                backend_files, sort_keys=True).encode())},
                "linux-qemu": {"files": len(qemu_files),
                               "bytes": sum(row["bytes"] for row in qemu_files)},
                "target_downloads": ["Debian Trixie rootfs", "pinned Linux GUI wheels",
                                     "pinned Linux account wheels"],
            },
            "excluded": ["owner data and credentials", "model weights",
                         "Windows executables and runtimes",
                         "optional Torch/media/science/GPU layers"],
            "installation": {"host_python_required": False,
                             "host_node_required": False,
                             "sudo_required": False,
                             "host_packages_modified": False,
                             "internet_required": True},
            "verification_scope": "Bundled payload paths and hashes are verified by the builder; recipient installation and runtime execution were not tested.",
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8") + b"\n"
        sums = (f"{payload_hash}  payload.tar.gz\n{python_hash}  python-runtime.tar.gz\n").encode()
        readme = (installer_source / "README.txt").read_bytes()
        installer_script = (installer_source / "install.sh").read_bytes()


        bundle_dir = "PortalAI-Linux-Clean-Installer-r14"
        bundle_entries = [
            (bundle_dir + "/install.sh", installer_script, len(installer_script), 0o755),
            (bundle_dir + "/README.txt", readme, len(readme), 0o644),
            (bundle_dir + "/manifest.json", manifest_bytes, len(manifest_bytes), 0o644),
            (bundle_dir + "/SHA256SUMS", sums, len(sums), 0o644),
            (bundle_dir + "/payload.tar.gz", payload, payload.stat().st_size, 0o644),
            (bundle_dir + "/python-runtime.tar.gz", python_tar, python_tar.stat().st_size, 0o644),
        ]
        staged_output = temp_dir / package_name
        write_tar_gz(staged_output, bundle_entries)
        bundle_validation = verify_bundle(staged_output)
        artifact_sha = sha_file(staged_output)
        staged_output.replace(output_file)
        checksum.write_text(f"{artifact_sha}  {package_name}\n", encoding="ascii")
        for name, data in (("manifest.json", manifest_bytes), ("README.txt", readme),
                           ("SHA256SUMS", sums)):
            target = base / name
            if target.exists():
                raise FileExistsError(f"Refusing to overwrite existing output: {target}")
            target.write_bytes(data)
        return {**manifest, "artifact": {"path": str(output_file),
                                         "bytes": output_file.stat().st_size,
                                         "sha256": artifact_sha},
                "checksum_file": str(checksum), "bundle_validation": bundle_validation}
    finally:
        resolved_base = base.resolve()
        resolved_temp = temp_dir.resolve()
        if resolved_temp.parent == resolved_base and resolved_temp.name.startswith(".portalai-linux-build-"):
            shutil.rmtree(resolved_temp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-payload", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    options = parser.parse_args()
    result = build(options)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
