"""Import pinned portable backends and small models; verify before activation.

No administrator permissions or system package manager needed. Downloads and
extraction stay on the SSD. Existing installed files are never overwritten.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import atomic_json, portable_path, require_space

ASSETS = [
{"id": "qwen27-standard-q4", "url": "https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/71bc7b627595dc8a91039addd9c791ae548d6747/Qwen3.8-27B-Q4_K_M.gguf", "size": 18973870528, "sha256": "c600de0300ae8a0eb3a6c0b8b5561b8b96f16bd2c863c2a66c42de29d391a747", "dest": "LLM/models/Qwen3.8-27B-Q4_K_M.gguf", "base_model": "Qwen/Qwen3.8-27B", "license": "apache-2.0"},
{"id": "qwen27-standard-projector", "url": "https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/71bc7b627595dc8a91039addd9c791ae548d6747/mmproj-Qwen3.8-27B-BF16.gguf", "size": 931145888, "sha256": "de2a49866988ea272c43dc2a43ee2662c25725a717ca5b9059ea420a97f53fe8", "dest": "LLM/models/mmproj-Qwen3.8-27B-Standard-BF16.gguf", "base_model": "Qwen/Qwen3.8-27B", "license": "apache-2.0"},
{"id": "linux-vulkan", "url": "https://github.com/ggml-org/llama.cpp/releases/download/b10935/llama-b10935-bin-ubuntu-vulkan-x64.tar.gz", "size": 30163686, "sha256": "f375e5c829eaf57984d6e94c88a1bd4688f98ab1c01e9d3a183cfff216469ec5", "dest": "LLM/backends/linux-vulkan", "archive": "tar"},
{"id": "qwen-license", "url": "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/90862c4b9d2787eaed51d12237eafdfe7c5f6077/LICENSE", "size": 11544, "sha256": "5de36594c10839788a8c589443a8ef9d8b8d17c65a1b5807206ae037fc36c6bd", "dest": "LLM/models/licenses/Qwen-Apache-2.0.txt"},
{"id": "linux-python", "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.12.15%2B20261009-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz", "size": 34304557, "sha256": "ffa8f85f1b56e88b687f08d743d817015524b86a9365fd921243132b80f1a36d", "dest": "Runtime/LinuxPython", "archive": "tar", "payload": "python"},
{"id": "windows-cpu", "url": "https://github.com/ggml-org/llama.cpp/releases/download/b10935/llama-b10935-bin-win-cpu-x64.zip", "size": 18426355, "sha256": "fe3295d94d2a701e4cc6f0e6a63da0c42e4f9f0dd470f8e589953759a4e082c2", "dest": "LLM/backends/windows-cpu", "archive": "zip"},
{"id": "windows-vulkan", "url": "https://github.com/ggml-org/llama.cpp/releases/download/b10935/llama-b10935-bin-win-vulkan-x64.zip", "size": 31673582, "sha256": "6b6b5fd895a43d9323249995f829c20b88f60347c3d7d3981de458cb23e7c079", "dest": "LLM/backends/windows-vulkan", "archive": "zip"},
{"id": "linux-cpu", "url": "https://github.com/ggml-org/llama.cpp/releases/download/b10935/llama-b10935-bin-ubuntu-x64.tar.gz", "size": 16822017, "sha256": "d49bbb607c13ac6aa72673ff6257628cb483d0b22e9762290b9ec7dc766d7f18", "dest": "LLM/backends/linux-cpu", "archive": "tar"},
{"id": "qwen1.7-q8", "url": "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/90862c4b9d2787eaed51d12237eafdfe7c5f6077/Qwen3-1.7B-Q8_0.gguf", "size": 1834426016, "sha256": "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a", "dest": "LLM/models/Qwen3-1.7B-Q8_0.gguf"},
{"id": "qwen4-q4", "url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf", "size": 2497280256, "sha256": "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5", "dest": "LLM/models/Qwen3-4B-Q4_K_M.gguf"}
]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024**2), b""):
            h.update(block)
    return h.hexdigest()


def checked_space(root, additional_bytes):
    """Retry a brief Windows settings-file sharing conflict, never a low-space denial."""
    for attempt in range(4):
        try:
            return require_space(root, additional_bytes)
        except PermissionError:
            if attempt == 3: raise
            time.sleep(.1)


def download(asset, part, root):
    """Resume only an exact pinned URL; activation still rehashes the whole file."""
    from academic_policy import require_asset
    require_asset(asset)
    if part.exists() and (part.is_symlink() or part.stat().st_nlink != 1 or
                          getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
        raise ValueError('Import staging file must not be linked')
    offset = part.stat().st_size if part.is_file() else 0
    if offset > asset['size']:
        raise RuntimeError('Retained partial exceeds pinned size; review it before retrying')
    if offset == asset['size']:
        return offset  # The caller must still verify the complete on-disk digest.
    headers = {'User-Agent':'PortalAI-portable-import/1', 'Accept-Encoding':'identity'}
    if offset: headers['Range'] = f'bytes={offset}-'
    req = urllib.request.Request(asset['url'], headers=headers)
    print(f"Downloading {asset['id']} ({asset['size'] / 1024**2:.1f} MiB; retained {offset / 1024**2:.1f} MiB)", flush=True)
    with urllib.request.urlopen(req, timeout=45) as response:
        # Local pinned file fixtures have no HTTP status; they are full responses.
        status = getattr(response, 'status', None) or 200
        if status == 206:
            expected = f"bytes {offset}-{asset['size']-1}/{asset['size']}"
            if response.headers.get('Content-Range') != expected:
                raise RuntimeError('Download resume range does not match pinned asset')
        elif status == 200:
            offset = 0  # Server ignored Range; never append the complete response.
        else:
            raise RuntimeError('Unexpected download status: ' + str(status))
        total = offset
        with part.open('ab' if offset else 'wb') as f:
            while True:
                block = response.read(4 * 1024**2)
                if not block: break
                total += len(block)
                if total > asset['size']: raise RuntimeError('Download exceeds pinned size')
                checked_space(root, len(block))
                f.write(block)
            f.flush()
            os.fsync(f.fileno())
    return total


def install(asset, root=ROOT):
    from academic_policy import require_asset
    require_asset(asset)
    dest = portable_path(root, asset["dest"])
    receipt = root / "Maintenance/Imports" / (asset["id"] + ".json")
    if dest.exists():
        if not asset.get("archive") and sha256(dest) == asset["sha256"]:
            return {"id": asset["id"], "status": "verified-existing"}
        if receipt.exists() and asset.get("archive"):
            old = json.loads(receipt.read_text())
            if old.get("sha256") == asset["sha256"] and all(
                portable_path(dest, row["path"]).is_file() and sha256(portable_path(dest, row["path"])) == row["sha256"]
                for row in old.get("installed_files", [])) and old.get("installed_files"):
                return {"id": asset["id"], "status": "verified-existing"}
        raise RuntimeError(f"Refusing to overwrite unverified existing destination: {dest}")
    checked_space(root, asset["size"] * (6 if asset.get("archive") else 1))
    staging = root / "Cache/imports"
    staging.mkdir(parents=True, exist_ok=True)
    part = staging / (asset["id"] + ".part")
    total = download(asset, part, root)
    if total != asset["size"] or sha256(part) != asset["sha256"]:
        raise RuntimeError("Import checksum/size mismatch; file remains quarantined in Cache/imports")
    installed_files = []
    dest.parent.mkdir(parents=True, exist_ok=True)
    if asset.get("archive"):
        # Fresh staging directory; verify paths and expansion size before writing members.
        import tempfile
        with tempfile.TemporaryDirectory(prefix=asset["id"] + "-", dir=staging) as temp:
            work = Path(temp)
            if asset["archive"] == "zip":
                with zipfile.ZipFile(part) as z:
                    require_space(root, sum(m.file_size for m in z.infolist()))
                    for m in z.infolist():
                        portable_path(work, m.filename)
                        if (m.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError("Archive links are not permitted")
                    z.extractall(work)
            else:
                with tarfile.open(part) as tar:
                    members = tar.getmembers()
                    require_space(root, sum(m.size for m in members))
                    for m in members:
                        portable_path(work, m.name)
                        if not m.isfile() and not m.isdir() and not m.issym():
                            raise ValueError("Unsupported archive member")
                    # Copy symlink targets as regular files for Windows/NTFS portability.
                    for m in members:
                        if m.isdir():
                            continue
                        out = portable_path(work, m.name)
                        out.parent.mkdir(parents=True, exist_ok=True)
                        if m.issym():
                            portable_path(work, str(Path(m.name).parent / m.linkname))
                        with tar.extractfile(m) as source, out.open("wb") as target:
                            shutil.copyfileobj(source, target)
                        out.chmod(0o755 if m.mode & 0o111 else 0o644)
            if asset.get("payload"):
                payload = portable_path(work, asset["payload"])
            else:
                exe_name = "llama-server.exe" if asset["id"].startswith("windows") else "llama-server"
                matches = list(work.rglob(exe_name))
                if len(matches) != 1:
                    raise RuntimeError("Archive has no unique llama-server")
                payload = matches[0].parent
            for f in payload.rglob("*"):
                if f.is_file():
                    installed_files.append({"path": f.relative_to(payload).as_posix(), "sha256": sha256(f)})
            # Rename atomically on the SSD, after all contents are verified/extracted.
            if os.name == 'nt':
                from portable_permissions import grant_runtime_read_execute
                # TemporaryDirectory carries a machine-specific owner ACL.
                # Prepare a reviewed public stage before it becomes active.
                stage = dest.with_name(dest.name + '-stage')
                if stage.exists():
                    raise RuntimeError('Previous backend stage retained; review before retrying')
                os.rename(payload, stage)
                grant_runtime_read_execute(root, stage)
                os.rename(stage, dest)
            else:
                os.replace(payload, dest)
        part.unlink()
    else:
        os.replace(part, dest)
    atomic_json(receipt, {**asset, "verified": True, "installed_files": installed_files})
    return {"id": asset["id"], "status": "installed-verified", "destination": str(dest)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="Without this flag, only display size/budget")
    parser.add_argument("--only", choices=[a["id"] for a in ASSETS])
    args = parser.parse_args()
    assets = [a for a in ASSETS if not args.only or a["id"] == args.only]
    if not args.install:
        print(json.dumps({"assets": assets, "budget": require_space(ROOT, sum(a["size"] for a in assets))}, indent=2))
        return
    for a in assets:
        print(json.dumps(install(a)), flush=True)


if __name__ == "__main__":
    main()
