#!/usr/bin/env python3
"""Build a clean dual-architecture macOS installer from approved release inputs."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT.parent / "Utilities/PortalAI Windows Installer"
SOURCE = SOURCE_DIR / "payload.zip"
OUT = ROOT.parent / "Utilities/PortalAI Mac Installer"
ARM_RUNTIME = ROOT / "Cache/cpython-3.12.15-macos-arm64.tar.gz"
X64_RUNTIME = ROOT / "Cache/cpython-3.12.15-macos-x64.tar.gz"
LLAMA_SOURCE = ROOT / "Cache/llama.cpp-v0.7.0-source.tar.gz"
RUNTIME_HASHES = {
    "arm64": "233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f",
    "x86_64": "fb3187d95334813b88940db0f1ca57b84cedfd552739c3a5771c3ea0e49988c9",
}
LLAMA_SHA = "55d67acf3ad2ad747a9bbeb75f9f0e173dbcc0d1753a471038a90c819421c5e1"
BLOCKED_SUFFIXES = {
    ".exe", ".dll", ".pyd", ".so", ".dylib", ".cmd", ".bat", ".ps1", ".msi",
    ".lnk", ".sys", ".whl", ".pdb", ".lib", ".obj", ".o", ".a", ".gguf",
    ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".zip", ".7z", ".tar", ".gz",
}
BLOCKED_PARTS = {
    "Backups", "Cache", "Data", "Outputs", "Private", "User Folder", "Logs",
    ".runtime", ".git", "__pycache__", "Validation", "Patches", "Archive", "Reports",
}
BLOCKED_PREFIXES = (
    "PortalAI/Runtime/", "PortalAI/LLM/backends/", "PortalAI/LLM/models/",
    "PortalAI/Generative/", "PortalAI/Music/", "PortalAI/MusicUnderstanding/",
    "PortalAI/OpenWebUI/", "PortalAI/SpeechToText/", "PortalAI/StableDiffusion/",
    "PortalAI/Voice/", "PortalAI/Scientific/", "PortalAI/Installer/",
    "PortalAI/Documentation/Business-Mission/", "PortalAI/Maintenance/Validation/",
    "PortalAI/Maintenance/Patches/", "PortalAI/Maintenance/Archive/",
    "PortalAI/Maintenance/Reports/",
)
OVERLAYS = (
    "README.md",
    "Agent/account_runtime.py", "Agent/local_accounts.py", "Agent/macos_job.py",
    "Agent/macos_lifecycle.py", "Agent/macos_process.py", "Agent/mission_accounts.py",
    "Agent/mission_supervisor.py", "Agent/platform_runtime.py", "Agent/portable_process.py",
    "Agent/runtime_policy.py", "Agent/service_manager.py", "Agent/linux_lifecycle.py",
    "Agent/bounded_comfy.py", "Agent/dialogue_portable.py", "Agent/piper_bridge.py",
    "Agent/sdcpp_bridge.py", "Agent/vm_runner.py", "ControlCenter/control_center_bootstrap.py",
    "ControlCenter/portable_runtime.py", "ControlCenter/PortableAI_GUI.py",
    "ControlCenter/native_chat.py", "ControlCenter/native_ui_state.py",
    "ControlCenter/media_devices.py", "Agent/profile_shutdown.py",
    "Launchers/portalai_gui_macos.py",
    "Launchers/portalai_missions_macos.py", "Tools/import_macos_layers.py",
    "Tools/macos_installer_smoke.py", "Documentation/Mac_Compatibility_Review_20261017.txt",
    "Documentation/Mac_Clean_Installer_20261017.txt",
    "Maintenance/Imports/macos-account-pins.json", "Maintenance/Imports/macos-gui-pins.json",
    "Maintenance/Imports/macos-storage-policy.json",
)
FORBIDDEN_NAMES = {"missionv2.md", "mission.md", "secrets.yaml", "secrets.yml", ".env"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def relpath(value: str) -> PurePosixPath:
    rel = PurePosixPath(value.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts or ":" in rel.parts[0]:
        raise ValueError("Unsafe installer path: " + value)
    return rel


def source_hash() -> str:
    rows = json.loads((SOURCE.parent / "PACKAGE_SHA256.json").read_text(encoding="utf-8"))
    expected = next((row["sha256"] for row in rows if row.get("path") == "payload.zip"), None)
    if not expected or sha(SOURCE) != expected:
        raise RuntimeError("Clean Windows source payload does not match its published checksum")
    return expected


def add_tar(tar: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644) -> None:
    rel = relpath(name)
    info = tarfile.TarInfo(rel.as_posix())
    info.size = len(data)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))


def deterministic_tar(path: Path, rows) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as stream:
            with tarfile.open(fileobj=stream, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name, data, mode in rows:
                    add_tar(archive, name, data, mode)


def selected(name: str) -> bool:
    rel = relpath(name)
    if not rel.parts[0] == "PortalAI" or rel.suffix.lower() in BLOCKED_SUFFIXES:
        return False
    if rel.name.lower() in FORBIDDEN_NAMES or any(part in BLOCKED_PARTS for part in rel.parts):
        return False
    if any(name.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        return False
    if any(part.lower().endswith((".pem", ".key")) for part in rel.parts):
        return False
    if rel.name == "PortalAI.sh" or rel.name in ("portalai_gui_linux.py", "portalai_missions_linux.py"):
        return False
    return True


def app_payload(source_sha: str, temp: Path) -> tuple[Path, dict]:
    files: dict[str, tuple[bytes, int]] = {}
    skipped = 0
    with zipfile.ZipFile(SOURCE) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = relpath(member.filename).as_posix()
            if not selected(name):
                skipped += 1
                continue
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError("Symlink in clean application source: " + name)
            files[name] = (archive.read(member), 0o755 if name.endswith(".sh") else 0o644)

    for relative in OVERLAYS:
        local = ROOT / relative
        if not local.is_file():
            raise FileNotFoundError("Mac package overlay is missing: " + str(local))
        files["PortalAI/" + relative.replace("\\", "/")] = (local.read_bytes(),
            0o755 if relative.endswith(".sh") else 0o644)

    from web_installer_assets import files as web_files
    for name,path in web_files(ROOT,'Mac'):
        if name in files:raise RuntimeError('Duplicate web runtime file: '+name)
        files[name]=(path.read_bytes(),0o755 if path.name=='node' else 0o644)

    required = (
        "PortalAI/ControlCenter/PortableAI_GUI.py", "PortalAI/Agent/mission_supervisor.py",
        "PortalAI/Agent/macos_job.py", "PortalAI/Agent/macos_process.py",
        "PortalAI/Agent/portable_process.py", "PortalAI/Agent/local_accounts.py",
        "PortalAI/Launchers/portalai_gui_macos.py", "PortalAI/Launchers/portalai_missions_macos.py",
        "PortalAI/Tools/import_macos_layers.py", "PortalAI/Tools/macos_installer_smoke.py",
        "PortalAI/Documentation/Mac_Compatibility_Review_20261017.txt",
        "PortalAI/Documentation/Mac_Clean_Installer_20261017.txt",
        "PortalAI/Maintenance/Imports/macos-account-pins.json",
        "PortalAI/Maintenance/Imports/macos-gui-pins.json",
        "PortalAI/Maintenance/Imports/macos-storage-policy.json",
    )
    missing = [name for name in required if name not in files]
    if missing:
        raise RuntimeError("Clean Mac source is missing required files: " + ", ".join(missing))

    nested = temp / "payload.tar.gz"
    rows = [(name, data, mode) for name, (data, mode) in sorted(files.items())]
    deterministic_tar(nested, rows)
    receipt = {"files": len(files), "skipped_source_entries": skipped,
               "source_payload_sha256": source_sha, "payload_sha256": sha(nested),
               "payload_bytes": nested.stat().st_size,
               "owner_data_included": False, "model_weights_included": False,
               "windows_native_files_included": False, "linux_native_files_included": False}
    return nested, receipt


def verify_nested(path: Path, expected: str, *, runtime: bool = False) -> dict:
    if sha(path) != expected:
        raise RuntimeError("A pinned Mac runtime/source archive checksum differs: " + path.name)
    result = {"asset": path.name, "bytes": path.stat().st_size, "sha256": expected}
    if runtime:
        with tarfile.open(path, "r:gz") as archive:
            names = {item.name for item in archive.getmembers() if item.isfile()}
            if not any(name.endswith("/bin/python3.12") or name == "python/bin/python3.12" for name in names):
                raise RuntimeError("Bundled Mac Python executable is missing")
            if not any(name.endswith("/_tkinter.cpython-312-darwin.so") for name in names):
                raise RuntimeError("Bundled Python runtime lacks the Tk bridge")
            if not any("/tcl9.0/" in name for name in names):
                raise RuntimeError("Bundled Python runtime lacks Tcl data")
            result["files"] = len(names)
    return result


def build(options) -> dict:
    src_sha = source_hash()
    arm = verify_nested(ARM_RUNTIME, RUNTIME_HASHES["arm64"], runtime=True)
    x64 = verify_nested(X64_RUNTIME, RUNTIME_HASHES["x86_64"], runtime=True)
    llama = verify_nested(LLAMA_SOURCE, LLAMA_SHA)
    output = Path(options.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = "PortalAI-Mac-Clean-Installer-20261019-r14-universal.tar.gz"
    archive_path = output / name
    if archive_path.exists() or archive_path.is_symlink():
        raise FileExistsError("Refusing to overwrite existing Mac installer: " + str(archive_path))
    readme_path = ROOT / "Installer/Mac/README.txt"
    script_path = ROOT / "Installer/Mac/install-macos.sh"
    with tempfile.TemporaryDirectory(prefix="portalai-macos-build-", dir=output) as temp_name:
        temp = Path(temp_name)
        payload, payload_info = app_payload(src_sha, temp)
        artifacts = {
            "payload.tar.gz": payload,
            "python-runtime-arm64.tar.gz": ARM_RUNTIME,
            "python-runtime-x86_64.tar.gz": X64_RUNTIME,
            "llama.cpp-source.tar.gz": LLAMA_SOURCE,
        }
        hashes = {name: sha(path) for name, path in artifacts.items()}
        runtime_rows = {
            "arm64": {"asset": "python-runtime-arm64.tar.gz", **arm},
            "x86_64": {"asset": "python-runtime-x86_64.tar.gz", **x64},
        }
        manifest = {
            "release": "PortalAI-2026.10.19-Mac-r14",
            "status": "BUILT_NOT_FULL_RECIPIENT_INSTALL_TESTED",
            "platforms": ["macOS arm64 (Apple silicon)", "macOS x86_64 (Intel)"],
            "macOS_physical_tested": False,
            "source_payload": {"sha256": src_sha, "release": json.loads((SOURCE.parent / "release.json").read_text(encoding="utf-8"))["release"]},
            "application": payload_info,
            "python_runtimes": runtime_rows,
            "llama_cpp_source": {**llama, "upstream_tag": "v0.7.0", "metal_build": True},
            "components": {"local_gui": True, "missions_and_schedules": True,
                           "encrypted_accounts": True, "metal_llama_server": "compiled on recipient Mac",
                           "model_weights_included": False, "optional_media_stack_included": False,
                           "vm_transport_included": False, "notarized": False, "signed": False},
            "limitations": ["macOS process group and sampled memory supervision are not a kernel sandbox",
                            "model handoff/recovery is disabled on macOS",
                            "recipient-side GUI/model acceptance remains required"],
            "artifacts": {key: {"bytes": path.stat().st_size, "sha256": hashes[key]}
                          for key, path in artifacts.items()},
        }
        sums = "".join(f"{hashes[key]}  {key}\n" for key in sorted(hashes))
        outer = temp / name
        prefix = "PortalAI-Mac-Clean-Installer-r14/"
        with outer.open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                    add_tar(tar, prefix + "install-macos.sh", script_path.read_bytes(), 0o755)
                    add_tar(tar, prefix + "README.txt", readme_path.read_bytes())
                    add_tar(tar, prefix + "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
                    add_tar(tar, prefix + "SHA256SUMS", sums.encode("ascii"))
                    for key, path in artifacts.items():
                        add_tar(tar, prefix + key, path.read_bytes())
        verification = verify_bundle(outer)
        shutil.copy2(outer, archive_path)
        sidecar = archive_path.with_suffix(archive_path.suffix + ".sha256")
        sidecar.write_text(f"{sha(archive_path)}  {archive_path.name}\n", encoding="ascii")
        (output / "README.txt").write_bytes(readme_path.read_bytes())
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (output / "SHA256SUMS").write_text(sums, encoding="ascii")
        return {"installer": str(archive_path), "sha256": sha(archive_path),
                "bytes": archive_path.stat().st_size, **verification}


def verify_bundle(path: Path) -> dict:
    with tarfile.open(path, "r:gz") as archive:
        expected = {"install-macos.sh", "README.txt", "manifest.json", "SHA256SUMS",
                    "payload.tar.gz", "python-runtime-arm64.tar.gz",
                    "python-runtime-x86_64.tar.gz", "llama.cpp-source.tar.gz"}
        members = {item.name.removeprefix("PortalAI-Mac-Clean-Installer-r14/"): item
                   for item in archive.getmembers()}
        if set(members) != expected or any(not item.isfile() for item in members.values()):
            raise RuntimeError("Mac installer archive has unexpected members")
        if members["install-macos.sh"].mode & 0o111 == 0:
            raise RuntimeError("Mac install script is not executable")
        contents = {name: archive.extractfile(member).read() for name, member in members.items()}
        install_text = contents["install-macos.sh"].decode("utf-8")
        if 'SELF_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"' not in install_text or \
                'DEST="${1:-${PORTALAI_INSTALL_DIR:-$SELF_DIR/PortalAI Mac}}"' not in install_text:
            raise RuntimeError("Mac installer no longer defaults inside its script folder")
        if ".portalai-macos-write-check." not in install_text:
            raise RuntimeError("Mac installer is missing its writable executable-filesystem preflight")
        sums = {}
        for line in contents["SHA256SUMS"].decode("ascii").splitlines():
            checksum, filename = line.split(None, 1)
            sums[filename.strip()] = checksum
        if set(sums) != expected - {"install-macos.sh", "README.txt", "manifest.json", "SHA256SUMS"}:
            raise RuntimeError("Mac installer checksum manifest has the wrong artifact set")
        for filename, checksum in sums.items():
            if hashlib.sha256(contents[filename]).hexdigest() != checksum:
                raise RuntimeError("Nested Mac installer asset checksum differs: " + filename)
        manifest = json.loads(contents["manifest.json"])
        if manifest.get("status") != "BUILT_NOT_FULL_RECIPIENT_INSTALL_TESTED":
            raise RuntimeError("Mac package overstates its recipient install status")
        import io
        with tarfile.open(fileobj=io.BytesIO(contents["payload.tar.gz"]), mode="r:gz") as payload:
            files = [item for item in payload.getmembers() if item.isfile()]
            names = {item.name for item in files}
            if len(names) != len(files):
                raise RuntimeError("Mac application payload contains duplicate paths")
            from web_installer_assets import native_web_path
            forbidden = [item.name for item in files if not native_web_path(item.name,'Mac') and (
                         PurePosixPath(item.name).suffix.lower() in BLOCKED_SUFFIXES or
                         any(part in BLOCKED_PARTS for part in PurePosixPath(item.name).parts) or
                         any(item.name.startswith(prefix) for prefix in BLOCKED_PREFIXES))]
            if forbidden:
                raise RuntimeError("Foreign native or private payload entered Mac archive: " + forbidden[0])
            required = ("PortalAI/README.md", "PortalAI/ControlCenter/PortableAI_GUI.py", "PortalAI/Agent/macos_job.py",
                        "PortalAI/Agent/macos_process.py", "PortalAI/Tools/import_macos_layers.py",
                        "PortalAI/Documentation/Mac_Clean_Installer_20261017.txt")
            if any(name not in names for name in required):
                raise RuntimeError("Mac payload is missing required app/install files")
            app_readme = next(item for item in files if item.name == "PortalAI/README.md")
            readme = payload.extractfile(app_readme).read().decode("utf-8")
            if "installer's own folder" not in readme or "NTFS" not in readme:
                raise RuntimeError("Mac app README does not describe portable install placement")
        python_files = {}
        for arch, filename in (("arm64", "python-runtime-arm64.tar.gz"),
                               ("x86_64", "python-runtime-x86_64.tar.gz")):
            with tarfile.open(fileobj=io.BytesIO(contents[filename]), mode="r:gz") as python_tar:
                names = {item.name for item in python_tar.getmembers() if item.isfile()}
                if not any(name.endswith("/bin/python3.12") for name in names):
                    raise RuntimeError(f"Bundled Python executable is missing for {arch}")
                if not any("/_tkinter.cpython-312-darwin.so" in name for name in names):
                    raise RuntimeError(f"Bundled Tk bridge is missing for {arch}")
                python_files[arch] = len(names)
    return {"passed": True, "payload_files": len(files),
                "python_files": python_files, "macos_physical_tested": False,
                "owner_data_files": 0, "windows_native_files": 0, "linux_native_files": 0}


def main() -> int:
    global SOURCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-payload", default=str(SOURCE))
    parser.add_argument("--output-dir", default=str(OUT))
    args = parser.parse_args()
    SOURCE = Path(args.source_payload).resolve()
    result = build(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
