from __future__ import annotations

"""Conservative destructive-maintenance helpers for PortableAI.

Only allowlisted data paths are touched. Model/runtime/source trees are never
recursively deleted by this module.
"""

from pathlib import Path
import os
import shutil
from profile_context import CapturedProfile


WEB_DIR_NAMES = {
    "web", "webcache", "web-cache", "web_cache", "webtools", "web-tools",
    "webdownloads", "web-downloads", "web_downloads", "webimages",
    "web-images", "web_images", "internetcache", "internet-cache",
}


def _reject_links(root: Path, path: Path) -> None:
    """A cache-named junction must never redirect cleanup into a model tree."""
    root=root.resolve()
    try:parts=path.absolute().relative_to(root).parts
    except ValueError as exc:raise RuntimeError('Cleanup path escapes root') from exc
    current=root
    for part in parts:
        current=current/part
        if current.is_symlink() or (os.name=='nt' and current.is_junction()):
            raise RuntimeError(f'Refusing linked cleanup path: {current}')


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _human_size(n: int) -> str:
    x = float(max(0, int(n)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024.0 or unit == "TB":
            return f"{x:.0f} {unit}" if unit == "B" else f"{x:.1f} {unit}"
        x /= 1024.0
    return f"{x:.1f} TB"


def _web_targets(root: Path, profile=None) -> list[Path]:
    profile = profile or CapturedProfile(root)
    if profile.identity is not None:
        roots = [profile.private('Data'), profile.private('Outputs')]
        explicit = [profile.private(relative) for relative in
                    ('Cache/Web', 'Cache/WebTests', 'Data/WebCache', 'Outputs/Web', 'Outputs/WebImages', 'Outputs/WebDownloads')]
    else:
        roots = [root / "Cache", root / "PortableCache", root / "Outputs", root / "Data", root / "Agent"]
        explicit = [
        root / "Data" / "WebCache",
        root / "Outputs" / "Web",
        root / "Outputs" / "WebImages",
        root / "Outputs" / "WebDownloads",
        root / "Agent" / ".webcache",
        root / "Agent" / "WebCache",
        ]
    found = set(p for p in explicit if p.exists())
    for base in roots:
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if child.is_dir() and child.name.casefold() in WEB_DIR_NAMES:
                    found.add(child)
                elif child.is_file():
                    low = child.name.casefold()
                    if low.startswith(("web_", "web-", "search_", "search-", "downloaded_web_")):
                        found.add(child)
        except OSError:
            pass
    return sorted(found, key=lambda p: str(p).casefold())


def targets_for(root: str | Path, kind: str, *, profile=None) -> list[Path]:
    root = Path(root).resolve()
    profile = profile or CapturedProfile(root)
    profile.check()
    k = str(kind or "").strip().casefold()
    if profile.identity is not None and k in ('outputs', 'webcache'):
        from profile_hydration import materialize
        # Discovery supports legacy web-named directories and individual output
        # files too. Materialize Outputs before scanning, without loading Data's
        # unrelated historical archives. Deletion then leaves ledger tombstones.
        materialize(root, 'Outputs', recursive=True)
        profile.check()
    if k == "webcache":
        targets = _web_targets(root, profile)
    elif k == "outputs":
        targets = [profile.private('Outputs')]
    elif k == "conversations":
        if profile.identity is not None:
            from profile_hydration import materialize
            for relative in ('Data/Chat/Sessions', 'Data/Chat/Attachments', 'Data/Chat/Recordings',
                             'Data/Chat/Thumbnails'):
                materialize(root, relative, recursive=True)
                profile.check()
        targets = [profile.private(relative) for relative in
                   ('Data/Chat/Sessions', 'Data/Chat/Attachments', 'Data/Chat/Recordings',
                    'Data/Chat/Thumbnails', 'Data/Chat/MediaCache', 'Data/Memory',
                    'Data/Chat/session_catalog.json')]
    else:
        raise ValueError(f"Unknown cleanup kind: {kind}")
    safe = []
    for p in targets:
        profile.check()
        p = Path(p)
        _reject_links(root,p)
        if not _inside(root, p):
            raise RuntimeError(f"Refusing cleanup outside PortableAI root: {p}")
        safe.append(p)
    return safe


def _scan_path(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return 1, path.stat().st_size
        except OSError:
            return 1, 0
    files = 0
    size = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                files += 1
                size += p.stat().st_size
        except OSError:
            pass
    return files, size


def preview_cleanup(root: str | Path, kind: str) -> dict:
    root = Path(root).resolve()
    profile = CapturedProfile(root)
    rows = []
    total_files = 0
    total_bytes = 0
    for p in targets_for(root, kind, profile=profile):
        profile.check()
        files, size = _scan_path(p)
        if p.exists() or files:
            rows.append({"path": str(p), "files": files, "bytes": size})
        total_files += files
        total_bytes += size
    return {
        "kind": kind,
        "targets": rows,
        "files": total_files,
        "bytes": total_bytes,
        "human_bytes": _human_size(total_bytes),
    }


def _empty_dir(path: Path, errors: list[str], guard=lambda: None) -> tuple[int, int]:
    guard()
    deleted = 0
    freed = 0
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return deleted, freed
    if path.is_file():
        try:
            freed = path.stat().st_size
        except OSError:
            freed = 0
        try:
            path.unlink()
            deleted = 1
        except Exception as exc:
            errors.append(f"{path}: {exc}")
        return deleted, freed
    # Delete children rather than the allowlisted root itself so callers can
    # continue using the directory immediately after cleanup.
    children = list(path.iterdir())
    for child in children:
        guard()
        try:
            if child.is_dir() and not child.is_symlink():
                f, b = _scan_path(child)
                shutil.rmtree(child)
                deleted += f
                freed += b
            else:
                try:
                    b = child.stat().st_size
                except OSError:
                    b = 0
                child.unlink()
                deleted += 1
                freed += b
        except Exception as exc:
            errors.append(f"{child}: {exc}")
    path.mkdir(parents=True, exist_ok=True)
    return deleted, freed


def execute_cleanup(root: str | Path, kind: str) -> dict:
    root = Path(root).resolve()
    profile = CapturedProfile(root)
    errors: list[str] = []
    deleted = 0
    freed = 0
    touched = []
    for p in targets_for(root, kind, profile=profile):
        profile.check()
        if not p.exists() and kind == "webcache":
            continue
        _reject_links(root,p)
        # Refuse an entire target containing reparse points before deleting any
        # children, even when the link points elsewhere within the portable root.
        if p.is_dir():
            for base, dirs, names in os.walk(p,followlinks=False):
                for name in dirs+names:_reject_links(root,Path(base)/name)
        d, b = _empty_dir(p, errors, profile.check)
        deleted += d
        freed += b
        touched.append(str(p))
    return {
        "kind": kind,
        "deleted_files": deleted,
        "freed_bytes": freed,
        "human_freed": _human_size(freed),
        "targets": touched,
        "errors": errors,
        "success": not errors,
    }


human_size = _human_size
