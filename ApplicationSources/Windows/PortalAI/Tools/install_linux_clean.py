#!/usr/bin/env python3
"""Install and verify PortalAI's small, portable Linux core layers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_rows(root: Path, receipt_path: Path, destination: str | None = None,
                row_field: str = "files", skip_pycache: bool = False) -> int:
    receipt = read_json(receipt_path)
    dest = destination or receipt.get("destination") or receipt.get("dest")
    if not dest:
        raise RuntimeError(f"Receipt has no destination: {receipt_path.name}")
    base = (root / dest).resolve()
    if not base.is_relative_to(root.resolve()):
        raise RuntimeError(f"Receipt destination escaped install root: {receipt_path.name}")
    rows = receipt.get(row_field)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Receipt has no file rows: {receipt_path.name}")
    for row in rows:
        rel = PurePosixPath(str(row.get("path", "")))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise RuntimeError(f"Unsafe receipt path: {receipt_path.name}")
        if skip_pycache and "__pycache__" in rel.parts:
            continue
        path = base.joinpath(*rel.parts)
        if not path.is_file():
            raise RuntimeError(f"Missing verified file: {path.relative_to(root)}")
        if row.get("bytes") is not None and path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Byte count differs: {path.relative_to(root)}")
        expected = row.get("sha256")
        if expected and digest(path) != expected:
            raise RuntimeError(f"SHA-256 differs: {path.relative_to(root)}")
    return sum(1 for row in rows if not (skip_pycache and "__pycache__" in PurePosixPath(str(row.get("path", ""))).parts))


def check_host() -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("This installer supports Linux x86-64 only.")
    if platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError("This installer supports Linux x86-64 only.")
    libc_name, libc_version = platform.libc_ver()
    if libc_name.lower() != "glibc" or tuple(int(x) for x in libc_version.split(".")[:2]) < (2, 28):
        raise RuntimeError("PortalAI requires glibc 2.28 or newer.")
    if not (ROOT / "Runtime/LinuxPython/bin/python3").is_file():
        raise RuntimeError("The bundled Linux Python runtime is missing.")


def storage_preflight() -> dict:
    sys.path.insert(0, str(ROOT / "Agent"))
    from runtime_policy import storage_budget
    return storage_budget(ROOT, additional_bytes=3 * GIB)


def preflight() -> None:
    check_host()
    budget = storage_preflight()
    print(json.dumps({"install_root": str(ROOT), "machine": platform.machine(),
                      "glibc": platform.libc_ver()[1],
                      "storage": budget}, sort_keys=True), flush=True)
    if not budget.get("allowed"):
        raise RuntimeError(
            "Install stopped to preserve PortalAI's configured free-space and output reserves. "
            "Choose a volume with more free space or review Agent/hardware_profiles.json."
        )


def run_installer(relative_script: str, *args: str) -> None:
    command = [sys.executable, "-B", str(ROOT / relative_script), *args]
    env = os.environ.copy()
    from runtime_policy import portable_env
    env.update(portable_env(ROOT, before_login=True))
    print("Running " + " ".join([relative_script, *args]), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def verify_python_runtime() -> None:
    receipt = ROOT / "Maintenance/Imports/linux-python.json"
    verify_rows(ROOT, receipt, row_field="installed_files")


def clean_installer_receipt(root: Path) -> Path:
    """Use this installation's unique receipt, without assuming a release number."""
    receipts = sorted((root / "Maintenance/Imports").glob("linux-clean-installer-r*.json"))
    if len(receipts) != 1:
        raise RuntimeError(f"Expected one Linux clean installer receipt; found {len(receipts)}")
    return receipts[0]


def verify_installed_layers() -> dict:
    checked = {}
    checked["python"] = verify_rows(
        ROOT, ROOT / "Maintenance/Imports/linux-python.json",
        destination="Runtime/LinuxPython", row_field="installed_files", skip_pycache=True)
    checked["linux_cpu_llm"] = verify_rows(
        ROOT, clean_installer_receipt(ROOT),
        destination="LLM/backends/linux-cpu", row_field="cpu_backend_files")
    checked["qemu"] = verify_rows(
        ROOT, ROOT / "Maintenance/Imports/linux-x64-payload.json",
        destination="Runtime/QEMU/linux-x64")
    checked["linux_system"] = verify_rows(
        ROOT, ROOT / "Maintenance/Imports/linux-system-payload.json")
    checked["gui_packages"] = verify_rows(
        ROOT, ROOT / "Maintenance/Imports/linux-gui-lock.json",
        destination="Runtime/LinuxPackages/gui")
    checked["account_packages"] = verify_rows(
        ROOT, ROOT / "Maintenance/Imports/linux-accounts-lock.json",
        destination="Runtime/AccountPython/linux-packages")
    return checked


def run_elf(root: Path, executable: Path, *args: str) -> str:
    sys.path.insert(0, str(root / "Agent"))
    from platform_runtime import linux_elf_command
    command, cwd = linux_elf_command(root, [str(executable), *args])
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            timeout=45, env=os.environ.copy())
    if result.returncode:
        raise RuntimeError(f"{executable.name} failed: {(result.stderr or result.stdout)[-1500:]}")
    return (result.stdout or result.stderr).strip().splitlines()[0]


def verify_core_imports() -> None:
    env = os.environ.copy()
    from runtime_policy import portable_env
    env.update(portable_env(ROOT, before_login=True))
    code = (
        "import sys; from pathlib import Path; r=Path(sys.argv[1]); "
        "sys.path[:0]=[str(r/'Runtime/LinuxPackages/gui'),"
        "str(r/'Runtime/AccountPython/linux-packages'),str(r/'Agent')]; "
        "import tkinter, PIL, psutil; "
        "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; "
        "import mission_schedule; assert hasattr(mission_schedule, 'Schedules'); "
        "print('GUI, account crypto, and mission modules import')"
    )
    python = ROOT / "Runtime/LinuxPython/run-python"
    subprocess.run([str(python), "-B", "-I", "-c", code, str(ROOT)],
                   cwd=ROOT, env=env, check=True, timeout=60)
    llama = run_elf(ROOT, ROOT / "LLM/backends/linux-cpu/llama-server", "--version")
    qemu = run_elf(ROOT, ROOT / "Runtime/QEMU/linux-x64/bin/qemu-system-x86_64", "--version")
    print(json.dumps({"llama": llama, "qemu": qemu}, sort_keys=True), flush=True)


def install_core() -> None:
    preflight()
    run_installer("Tools/import_linux_system.py")
    run_installer("Tools/import_linux_packages.py", "gui")
    run_installer("Tools/import_linux_accounts.py")
    checked = verify_installed_layers()
    verify_core_imports()
    print(json.dumps({"installed": True, "verified_file_counts": checked,
                      "models_included": False,
                      "optional_cpu_torch_media_science_layers_included": False},
                     sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--install-core", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.preflight:
        preflight()
    elif args.install_core:
        install_core()
    else:
        preflight()
        checked = verify_installed_layers()
        verify_core_imports()
        print(json.dumps({"verified": True, "verified_file_counts": checked,
                          "models_included": False}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"PortalAI Linux installer: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
