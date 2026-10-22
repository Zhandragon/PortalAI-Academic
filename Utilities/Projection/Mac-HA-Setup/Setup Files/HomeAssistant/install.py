#!/usr/bin/env python3
"""PortalAI HA file installer. Python 3.9+, standard library only.

The journal and verified originals are saved before replacing any file. Automatic
configuration edits are prepared before writing. Run only one installer
at a time, and avoid editing the managed files during install/rollback.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import time
import uuid
import importlib.util

RELEASE = "0.5.11"
HERE = Path(__file__).resolve().parent
META = ".portalai-installer"
PLACEHOLDER = "REPLACE_WITH_MODULE_DEVICE_ID"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Invalid relative path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError("Invalid relative path: " + name)
    return path


def linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()) or (
        os.name == "nt" and path.exists() and bool(
            getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def within(root, name):
    """Reject traversal, symlinks and junctions before following target paths."""
    rel = safe_relative(name)
    current = root
    for part in rel.parts:
        current = current / part
        if linked(current):
            raise ValueError("Linked paths are not supported: " + str(current))
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escaped target: " + name)
    return current


def target_root(value):
    root = Path(value).expanduser().resolve()
    if not root.is_dir() or not within(root, "configuration.yaml").is_file():
        raise ValueError("--config must be the existing HA configuration directory containing configuration.yaml")
    return root


def managed(name):
    rel = safe_relative(name)
    return (
        len(rel.parts) == 3 and rel.parts[0] == "custom_components"
        and rel.parts[1] in ("portalai_native", "portalai_projection", "portalai_recovery")
        and rel.suffix in (".py", ".json", ".yaml")
    ) or (len(rel.parts) == 2 and rel.parts[0] == "www"
          and rel.name in ("portalai-live-v0.5.11.js", "portalai-quick-chat-v0.4.3.js", "portalai-projection-v0.5.11.js", *ALIASES))


def generated(name):
    rel = safe_relative(name)
    return name in ('configuration.yaml','portalai/dashboard.yaml') or (len(rel.parts) == 4 and rel.parts[:3] == ("portalai", "examples", RELEASE) and rel.suffix == ".yaml")


ALIASES={**{name:'portalai-live-v0.5.11.js' for name in ('portalai-live-v0.5.1.js','portalai-live-v0.5.2.js','portalai-live-v0.5.3.js','portalai-live-v0.5.4.js','portalai-live-v0.5.5.js','portalai-live-v0.5.6.js','portalai-live-v0.5.7.js','portalai-live-v0.5.8.js','portalai-live-v0.5.9.js','portalai-live-v0.5.10.js')},
         'portalai-quick-chat-v0.4.1.js':'portalai-quick-chat-v0.4.3.js',
         'portalai-quick-chat-v0.4.2.js':'portalai-quick-chat-v0.4.3.js',
         'portalai-projection-demand-v1.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-demand-v2.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-demand-v3.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-v0.5.4.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-v0.5.5.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-v0.5.6.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-v0.5.7.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-v0.5.8.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-v0.5.9.js':'portalai-projection-v0.5.11.js',
         'portalai-projection-v0.5.10.js':'portalai-projection-v0.5.11.js'}

class PreparedFiles(dict):
    """Remember the configuration bytes used to prepare a merge."""
    expected = None


def automatic_setup(root,files,device_id,package=HERE):
    if not re.fullmatch('[0-9a-f]{32}',device_id):
        raise ValueError('Complete setup needs --device-id (public 32-character pairing ID). Use --files-only only for manual configuration.')
    spec=importlib.util.spec_from_file_location('portalai_setup_configure',package/'configure.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original=current_bytes(root,'configuration.yaml')
    files=PreparedFiles(files);files.expected={'configuration.yaml':original}
    try:files['configuration.yaml']=module.configure(original.decode('utf-8-sig'),device_id).encode('utf-8')
    except module.yaml.YAMLError as exc:raise ValueError('Cannot parse existing HA YAML. Fix its syntax before automatic setup; no files changed.') from None
    files['portalai/dashboard.yaml']=module.dashboard(device_id).encode('utf-8')
    # Old storage-mode resource registrations may still point at these URLs.
    # Upgrade their payloads too, with the same backup/rollback guarantees.
    for old,new in ALIASES.items():
        if current_bytes(root,'www/'+old) is not None:files['www/'+old]=files['www/'+new]
    return files


def verify_package(package=HERE):
    manifest = json.loads((package / "SHA256SUMS.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Missing package checksum manifest")
    for name, expected in manifest.items():
        if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError("Invalid checksum: " + name)
        path = within(package, name)
        if not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError("Package checksum failed: " + name)
    for folder in ("custom_components", "www", "examples", "vendor"):
        for path in (package / folder).rglob("*"):
            if path.is_dir() and not linked(path):
                continue
            name = path.relative_to(package).as_posix()
            if name not in manifest:
                raise ValueError("Unlisted payload file: " + name)
    required = {"custom_components/" + domain + "/" + file
                for domain in ("portalai_projection", "portalai_native", "portalai_recovery")
                for file in ("__init__.py", "manifest.json", "services.yaml")}
    required |= {"www/portalai-live-v0.5.11.js", "www/portalai-quick-chat-v0.4.3.js", "www/portalai-projection-v0.5.11.js",
                 "examples/configuration.merge.yaml", "RELEASE.json", "install.py", "configure.py", "finish.py", "vendor/yaml/__init__.py", "vendor/PyYAML-LICENSE.txt"}
    if not required.issubset(manifest):
        raise ValueError("Incomplete release payload")
    if json.loads((package / "RELEASE.json").read_text(encoding="utf-8"))["version"] != RELEASE:
        raise ValueError("Release/installer version mismatch")
    return manifest


def payload(package, device_id):
    if device_id != PLACEHOLDER and not re.fullmatch("[0-9a-f]{32}", device_id):
        raise ValueError("device-id must be the 32 lowercase hexadecimal PUBLIC pairing ID")
    manifest = verify_package(package)
    files = {}
    for name in sorted(manifest):
        if managed(name):
            files[name] = within(package, name).read_bytes()
        elif name.startswith("examples/") and len(PurePosixPath(name).parts) == 2 and name.endswith(".yaml"):
            files[f"portalai/examples/{RELEASE}/" + PurePosixPath(name).name] = within(package, name).read_text(
                encoding="utf-8").replace(PLACEHOLDER, device_id).replace('FIRST_8_DEVICE_ID_CHARS',device_id[:8] if device_id!=PLACEHOLDER else 'FIRST_8_DEVICE_ID_CHARS').encode("utf-8")
    return files


def current_bytes(root, name):
    path = within(root, name)
    if path.exists() and not path.is_file():
        raise ValueError("Target is not a file: " + str(path))
    return path.read_bytes() if path.exists() else None


def atomic_write(root, name, data):
    path = within(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        if path.read_bytes() != data:
            raise OSError("Written file verification failed: " + name)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def changed_files(root, files):
    changed = []
    for name, data in files.items():
        before = current_bytes(root, name)
        if before != data:
            changed.append((name, before, data))
    return changed


def rollback(root, backup_name):
    backup = within(root, backup_name)
    if not backup.resolve().is_relative_to(within(root, META + "/backups").resolve()):
        raise ValueError("Rollback requires this HA directory's installer backup")
    journal = json.loads(within(backup, "journal.json").read_text(encoding="utf-8"))
    if journal.get("format") != 1 or journal.get("release") != RELEASE:
        raise ValueError("Unknown rollback journal")
    rows = journal["files"]
    restores = []
    seen = set()
    # Validate ALL originals and current files before making any rollback changes.
    for row in rows:
        name = row["path"]
        if name in seen or not (managed(name) or generated(name)):
            raise ValueError("Invalid rollback target: " + name)
        seen.add(name)
        before = row["before"]
        old = None if before is None else within(backup, "files/" + name).read_bytes()
        if old is not None and digest(old) != before:
            raise ValueError("Backup checksum failed: " + name)
        current = current_bytes(root, name)
        current_hash = None if current is None else digest(current)
        if current_hash not in (before, row["after"]):
            raise ValueError("Changed since installation; refusing rollback over: " + name)
        restores.append((name, current, old))
    for name, current, old in reversed(restores):
        if current == old:
            continue
        if old is None:
            within(root, name).unlink()
        else:
            atomic_write(root, name, old)
    journal["state"] = "rolled_back"
    atomic_write(backup, "journal.json", (json.dumps(journal, indent=2) + "\n").encode())
    print("Restored managed files and automatic configuration edits. Validate HA configuration and restart HA.")


def install(root, files):
    changes = changed_files(root, files)
    for name,before in (getattr(files,'expected',None) or {}).items():
        if current_bytes(root,name)!=before or any(n==name and old!=before for n,old,_ in changes):
            raise ValueError('Configuration changed since setup was prepared: '+name)
    if not changes:
        print("All installed files already match. No files changed; no new backup needed.")
        return None
    # Exclusive lock also catches an interrupted installer; no stale lock is
    # removed automatically because another process may still be using it.
    lock = within(root, META + "/install.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()) + "\n")
    backup_name = META + "/backups/" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    journal_ready = False
    try:
        backup = within(root, backup_name)
        backup.mkdir(parents=True, exist_ok=False)
        rows = []
        for name, old, data in changes:
            rows.append({"path": name, "before": None if old is None else digest(old), "after": digest(data)})
            if old is not None:
                atomic_write(backup, "files/" + name, old)
        journal = {"format": 1, "release": RELEASE, "state": "prepared", "files": rows}
        atomic_write(backup, "journal.json", (json.dumps(journal, indent=2) + "\n").encode())
        journal_ready = True
        print("Backup: " + str(backup), flush=True)
        for name, old, data in changes:
            if current_bytes(root, name) != old:
                raise ValueError("File changed during installation: " + name)
            atomic_write(root, name, data)
        journal["state"] = "installed"
        atomic_write(backup, "journal.json", (json.dumps(journal, indent=2) + "\n").encode())
        print(f"Installed and verified {len(changes)} files.")
        print('Rollback: python install.py rollback --config "' + str(root) + '" --backup "' + backup_name + '"')
        return backup_name
    except BaseException:
        if journal_ready:
            try:
                rollback(root, backup_name)
                print("Installation failed; managed files restored.", file=sys.stderr)
            except Exception as error:
                print("Automatic restore could not finish: " + str(error) + "\nKeep backup: " + backup_name, file=sys.stderr)
        raise
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "plan", "install", "rollback", "wizard"))
    parser.add_argument("--config", help="Existing HA config directory (local, mounted share, or Windows UNC)")
    parser.add_argument("--device-id", default=PLACEHOLDER, help="Public pairing ID; omitted IDs remain placeholders in examples")
    parser.add_argument("--backup", help="Relative .portalai-installer/backups/... directory printed by install")
    parser.add_argument('--files-only',action='store_true',help='Copy files/examples without automatic YAML setup (advanced custom layouts)')
    parser.add_argument('--restart',action='store_true',help='Validate/restart through local HA CLI; requires ha command on the HA machine')
    parser.add_argument('--ha-url',help='Optional trusted HA origin for automatic config check/restart; prompts privately for an admin token')
    parser.add_argument('--pairing-public-file',help='Optional PUBLIC projection pairing JSON for first-time pairing after restart; requires --ha-url')
    args = parser.parse_args(argv)
    if args.action == "verify":
        print(f"Verified {len(verify_package())} package files.")
        return
    if args.action == "wizard":
        print("PortalAI HA 0.5.11 - installs files to an existing HA configuration directory.")
        print("Use a writable HA config share or mounted directory. This does not configure remote access.")
        args.config = args.config or input("HA config directory (or writable share): ").strip().strip('"')
        if args.device_id==PLACEHOLDER:args.device_id = input("Public device ID (32 lowercase hexadecimal characters): ").strip()
        args.ha_url=args.ha_url or input('HA URL for automatic check/restart (Enter to finish in HA manually): ').strip() or None
        if args.ha_url and not args.pairing_public_file:
            args.pairing_public_file=input('First install: PUBLIC projection pairing JSON file (Enter if already paired or pairing later): ').strip().strip('"') or None
        args.action = "install"
    if not args.config:
        parser.error("--config is required")
    root = target_root(args.config)
    if args.action == "rollback":
        if not args.backup:
            parser.error("rollback requires --backup")
        if within(root, META + "/install.lock").exists():
            raise ValueError("Install lock exists. See README interruption recovery before removing it.")
        rollback(root, args.backup)
        return
    files = payload(HERE, args.device_id)
    if not args.files_only:files=automatic_setup(root,files,args.device_id)
    changes = changed_files(root, files)
    for name, old, data in changes:
        print(("ADD     " if old is None else "REPLACE ") + name)
    if args.action == "plan":
        print(f"Plan only: {len(changes)} files would change; nothing written.")
        return
    api=None;pairing_request=None
    if args.restart and args.ha_url:raise ValueError('Choose --restart or --ha-url, not both.')
    if args.pairing_public_file:
        if not args.ha_url:raise ValueError('--pairing-public-file requires --ha-url')
        path=Path(args.pairing_public_file)
        if path.stat().st_size>4096:raise ValueError('Public pairing JSON is too large.')
        pairing_request=json.loads(path.read_text(encoding='utf-8-sig'))
        if type(pairing_request) is not dict or pairing_request.get('device_id')!=args.device_id:
            raise ValueError('Public pairing ID differs from the installed device ID.')
    if args.ha_url:
        import getpass
        spec=importlib.util.spec_from_file_location('portalai_finish',HERE/'finish.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        api=module.HomeAssistant(args.ha_url,getpass.getpass('HA administrator token (not saved): '))
        api.request('/api/')  # Authenticate before making any filesystem changes.
    if args.restart:
        import shutil,subprocess
        if not shutil.which('ha') or root!=Path('/config').resolve():
            raise ValueError('--restart requires the HA CLI and its local /config directory; no files installed.')
    backup=install(root, files)
    if api:
        try:api.check()
        except Exception:
            if backup:rollback(root,backup)
            raise
        api.restart()
        if pairing_request:api.pair_projection(pairing_request,args.device_id)
    if args.restart:
        try:subprocess.run(['ha','core','check'],check=True)
        except BaseException:
            if backup:rollback(root,backup)
            raise ValueError('HA configuration check failed; restored this installation. No restart requested.')
        subprocess.run(['ha','core','restart'],check=True)
    print('PortalAI files and '+('examples' if args.files_only else 'configuration/dashboard/module registrations')+' installed.')
    print('NEXT: '+('validate configuration and restart HA, then ' if not (args.restart or api) else '')+'reload browser/app caches.')
    print('First-time pairing remains an administrator action. Existing pairing and .storage are preserved. See README_FIRST.txt.')


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
