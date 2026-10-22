from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

VERSION = "15.103"

PROTECTED_TOP = {"Data", "Outputs", "LLM", "Generative", "Voice", "Video", "Music", "SpeechToText", "Runtime", "Agent", "ControlCenter", "Tools", "Launchers", "Workflows", "Sandbox", "SandboxClient"}
USER_DATA_TOP = {"Data", "Outputs", "Benchmarks"}
SAFE_CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".ipynb_checkpoints"}
PATCH_ZIP_PREFIXES = (
    "PortableAI_v15_", "PortableAI_ControlCenter_", "PortableAI_PortabilityFoundation_",
    "PortableAI_Video", "PortableAI_MMAudio", "PortableAI_SFX_",
)
PATCH_DIR_PREFIXES = (
    "PortableAI_v15_", "PortableAI_ControlCenter_", "PortableAI_PortabilityFoundation_",
)

@dataclass
class Candidate:
    path: str
    bytes: int
    category: str
    confidence: str
    reason: str
    action: str


def human(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(max(0, n))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.1f} {u}" if u != "B" else f"{int(x)} B"
        x /= 1024.0
    return f"{n} B"


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def dir_size(path: Path, *, skip_user_data: bool = False) -> int:
    total = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        p = Path(e.path)
                        if skip_user_data and p.name in USER_DATA_TOP and p.parent == path:
                            continue
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(p)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            continue
    return total


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def parse_venv_homes(root: Path) -> set[Path]:
    homes: set[Path] = set()
    # Avoid scanning giant caches. pyvenv.cfg files live near runtime roots.
    candidates = []
    for base in (root / "Voice", root / "Video", root / "Music", root / "Runtime", root / "Generative"):
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base):
            rel = Path(current).relative_to(root)
            # Skip model/cache/output trees where pyvenv.cfg cannot be useful.
            lower = {x.lower() for x in rel.parts}
            if lower & {"models", "checkpoints", "uv-cache", "cache", "outputs", "output"}:
                dirs[:] = []
                continue
            if "pyvenv.cfg" in files:
                candidates.append(Path(current) / "pyvenv.cfg")
            if len(rel.parts) > 6:
                dirs[:] = []
    for cfg in candidates:
        try:
            for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("home") and "=" in line:
                    raw = line.split("=", 1)[1].strip().strip('"')
                    if raw:
                        p = Path(raw)
                        if not p.is_absolute():
                            p = (cfg.parent / p)
                        homes.add(p.resolve())
        except Exception:
            pass
    return homes


def runtime_lock_paths(root: Path) -> set[Path]:
    paths: set[Path] = set()
    lock = root / "Agent" / ".runtime" / "component_runtime_locks.json"
    if not lock.exists():
        lock = root / "component_runtime_locks.json"
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        for item in (data.get("components") or {}).values():
            raw = item.get("path")
            if raw:
                p = Path(raw)
                if not p.is_absolute():
                    p = root / p
                paths.add(p.resolve())
    except Exception:
        pass
    return paths


def add_candidate(out: list[Candidate], seen: set[str], path: Path, category: str, confidence: str, reason: str, action: str):
    try:
        key = os.path.normcase(str(path.resolve()))
    except Exception:
        key = os.path.normcase(str(path))
    if key in seen or not path.exists():
        return
    seen.add(key)
    size = dir_size(path) if path.is_dir() else file_size(path)
    out.append(Candidate(str(path), size, category, confidence, reason, action))


def find_safe_candidates(root: Path) -> list[Candidate]:
    """Find high-confidence debris without recursively crawling giant model/runtime trees.

    Older builds walked every private Python environment looking for __pycache__
    directories. That produced huge reports and slow audits while reclaiming very
    little compared with the multi-GB historical trees. v15.103 limits cache
    discovery to PortableAI orchestration/bootstrap code plus obvious package
    download caches and root patch bundles.
    """
    out: list[Candidate] = []
    seen: set[str] = set()

    # Legacy browser package-download caches are pure transient content.
    for p in (root / "OpenWebUI" / "uv-cache", root / "OpenWebUI" / ".cache"):
        if p.exists():
            add_candidate(out, seen, p, "cache", "high", "Legacy OpenWebUI package cache; Native Chat does not require cached wheel/archive downloads.", "safe-delete")

    # Lightweight code/bootstrap roots only. Active model runtimes and old backups
    # are handled by the generalized cleanup planner instead of being traversed for
    # thousands of tiny cache directories.
    scan_roots = [
        root / "ControlCenter",
        root / "Agent",
        root / "Tools",
        root / "Launchers",
        root / "Services",
        root / "Workflows",
        root / "Runtime" / "BootstrapPython",
    ]
    prune_names = {x.lower() for x in SAFE_CACHE_DIR_NAMES}
    for base in scan_roots:
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base):
            cur = Path(current)
            if cur == root/'Tools':
                dirs[:] = [d for d in dirs if d.lower() != 'kicad' and not d.lower().startswith('kicad.staging-')]
            kept = []
            for d in dirs:
                dl = d.lower()
                if dl in prune_names:
                    add_candidate(out, seen, cur / d, "cache", "high", f"Regenerable {d} cache.", "safe-delete")
                else:
                    kept.append(d)
            dirs[:] = kept

    # Old patch packages copied/extracted into PortableAI root are no longer needed
    # after installation. Do not inspect component trees here.
    try:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() == ".zip" and p.name.startswith(PATCH_ZIP_PREFIXES):
                add_candidate(out, seen, p, "installer-artifact", "high", "Old PortableAI patch archive; installed payload is already copied into the live tree.", "safe-delete")
            elif p.is_dir() and p.name.startswith(PATCH_DIR_PREFIXES):
                if any((p / n).exists() for n in ("UpdatePayload", "README.txt")) or any(p.glob("Install_PortableAI*.cmd")):
                    add_candidate(out, seen, p, "installer-artifact", "high", "Extracted PortableAI patch bundle; installed payload is already copied into the live tree.", "safe-delete")
    except OSError:
        pass

    return sorted(out, key=lambda x: x.bytes, reverse=True)

def find_review_candidates(root: Path, protected: set[Path]) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()

    # Legacy frontends are no longer part of normal startup, but keep as explicit-review items.
    for name in ("OpenGUI", "OpenWebUI"):
        p = root / name
        if p.exists():
            add_candidate(out, seen, p, "legacy-frontend", "medium", f"{name} is not part of the Native Chat startup path. Remove only after confirming you no longer need the legacy fallback.", "review-delete")

    # Old backups: keep the newest three by default, report the rest.
    b = root / "Backups"
    if b.exists():
        try:
            dirs = [p for p in b.iterdir() if p.is_dir()]
            dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for p in dirs[3:]:
                add_candidate(out, seen, p, "old-backup", "medium", "Installer rollback backup older than the newest three backups.", "review-delete")
        except OSError:
            pass

    # Large private Python/runtime directories not named by current locks or a venv home.
    roots = [root / "Runtime", root / "Voice", root / "Video", root / "Music"]
    protected_norm = [p.resolve() for p in protected if p.exists()]
    for base in roots:
        if not base.exists():
            continue
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for p in children:
            if not p.is_dir():
                continue
            # Skip obvious active component roots.
            if any(is_relative_to(q, p) or is_relative_to(p, q) for q in protected_norm):
                continue
            # Only bother reporting sizeable roots.
            size = dir_size(p)
            if size >= 500 * 1024 * 1024:
                key = os.path.normcase(str(p.resolve()))
                if key not in seen:
                    seen.add(key)
                    out.append(Candidate(str(p), size, "unclassified-runtime", "low", "Large runtime directory is not referenced by current runtime locks or pyvenv.cfg homes. Inspect before deleting.", "review-only"))

    return sorted(out, key=lambda x: x.bytes, reverse=True)


def largest_top_level(root: Path) -> list[dict]:
    rows = []
    try:
        items = list(root.iterdir())
    except OSError:
        return rows
    for p in items:
        try:
            size = dir_size(p) if p.is_dir() else p.stat().st_size
        except OSError:
            continue
        rows.append({"path": str(p), "bytes": size})
    rows.sort(key=lambda x: x["bytes"], reverse=True)
    return rows[:30]


def hash_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def _duplicate_category(root: Path, files: list[Path]) -> tuple[str, str]:
    rels = []
    for p in files:
        try:
            rels.append(str(p.resolve().relative_to(root.resolve())).replace("/", "\\").lower())
        except Exception:
            rels.append(str(p).replace("/", "\\").lower())
    if rels and all(x.startswith("voice\\qwen3-tts\\") for x in rels):
        if any("\\.venv\\" in x or "\\python\\cpython-" in x for x in rels):
            return (
                "runtime-copy-overlap",
                "Identical files exist across multiple Qwen3-TTS Python/runtime trees. Do not delete individual DLLs. Use Root Reference Audit to determine whether an entire runtime tree is obsolete before removing anything.",
            )
        if all("\\models\\qwen3-tts-" in x for x in rels):
            return (
                "shared-model-assets",
                "The same model asset is intentionally present in multiple Qwen3-TTS model directories. Preserve unless the loader is explicitly reconfigured to share one canonical asset.",
            )
    if rels and all("\\models\\huggingface\\hub\\" in ("\\" + x) for x in rels):
        return (
            "huggingface-cache-layout",
            "Hugging Face blob/snapshot paths can intentionally reference identical content. This is not a safe-delete signal by itself; aliases/hardlinks/symlinks must be preserved.",
        )
    if rels and all(x.startswith("speechtotext\\models\\") for x in rels):
        return (
            "huggingface-cache-layout",
            "STT Hugging Face blob/snapshot paths can intentionally reference identical content. Preserve both names unless a reference-aware dedupe converts them safely.",
        )
    return (
        "exact-duplicate-review",
        "Exact content match only. Treat as review information, not permission to delete a path; one or more locations may be independently required.",
    )


def _physical_identity(path: Path):
    try:
        st = path.stat(follow_symlinks=False)
        ino = int(getattr(st, "st_ino", 0) or 0)
        dev = int(getattr(st, "st_dev", 0) or 0)
        if ino:
            return (dev, ino)
    except OSError:
        pass
    try:
        return ("path", os.path.normcase(str(path.resolve())))
    except Exception:
        return ("path", os.path.normcase(str(path)))


def deep_duplicates(root: Path, min_bytes: int = 128 * 1024 * 1024) -> list[dict]:
    """Find large exact-content duplicates without overstating link aliases.

    v15.101 deliberately treats this as ANALYSIS ONLY.  Symlinks are skipped and
    multiple hardlink names for the same physical file identity count as one
    physical copy, so Hugging Face cache layouts do not inflate the reclaimable
    estimate merely because one object has multiple names.
    """
    by_size: dict[int, list[Path]] = {}
    skip_dirs = {"Backups", "Data", "Outputs"}
    for current, dirs, files in os.walk(root):
        cur = Path(current)
        try:
            rel = cur.relative_to(root)
        except Exception:
            rel = Path()
        if rel.parts and rel.parts[0] in skip_dirs:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in {"uv-cache", "__pycache__"}]
        for fn in files:
            p = cur / fn
            try:
                if p.is_symlink():
                    continue
                s = p.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            if s >= min_bytes:
                by_size.setdefault(s, []).append(p)
    groups = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for p in files:
            digest = hash_file(p)
            if digest:
                by_hash.setdefault(digest, []).append(p)
        for digest, same in by_hash.items():
            if len(same) < 2:
                continue
            identities = {_physical_identity(p) for p in same}
            physical_copies = len(identities)
            wasted = size * max(0, physical_copies - 1)
            category, advice = _duplicate_category(root, same)
            groups.append({
                "sha256": digest,
                "bytes_each": size,
                "physical_copies": physical_copies,
                "path_count": len(same),
                "alias_paths": max(0, len(same) - physical_copies),
                "wasted_bytes": wasted,
                "category": category,
                "safe_delete": False,
                "advice": advice,
                "files": [str(x) for x in same],
            })
    groups.sort(key=lambda x: (x["wasted_bytes"], x["bytes_each"]), reverse=True)
    return groups


def _make_writable(path: str | os.PathLike) -> None:
    try:
        p = Path(path)
        mode = p.stat().st_mode
        p.chmod(mode | stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass


def _rmtree_retry(func, path, exc_info):
    # Windows/OneDrive trees frequently retain read-only package metadata. Clear
    # only the DOS/Python read-only bit and retry the exact failed operation; do
    # not rewrite ACLs or request elevation.
    try:
        _make_writable(path)
        func(path)
    except Exception:
        raise exc_info[1]


def delete_path(path: Path) -> tuple[bool, str]:
    try:
        if path.is_symlink() or path.is_file():
            _make_writable(path)
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, onerror=_rmtree_retry)
        return True, "deleted"
    except Exception as first:
        # One more non-elevated Windows retry after clearing recursive read-only
        # attributes. This is intentionally conservative: persistent ACL/process
        # locks remain failures and are reported rather than force-modified.
        if os.name == "nt" and path.exists():
            try:
                subprocess.run(["attrib", "-R", str(path / "*"), "/S", "/D"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if path.is_dir():
                    shutil.rmtree(path, onerror=_rmtree_retry)
                else:
                    _make_writable(path)
                    path.unlink(missing_ok=True)
                return True, "deleted after clearing read-only attributes"
            except Exception as second:
                return False, f"{second} (initial: {first})"
        return False, str(first)


def prune_old_backups(root: Path, keep: int) -> list[dict]:
    results = []
    b = root / "Backups"
    if not b.exists():
        return results
    try:
        dirs = [p for p in b.iterdir() if p.is_dir()]
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return results
    for p in dirs[max(0, keep):]:
        before = dir_size(p)
        ok, msg = delete_path(p)
        results.append({"path": str(p), "bytes": before, "ok": ok, "message": msg})
    return results


def audit(root: Path, deep: bool = False) -> dict:
    t0 = time.time()
    homes = parse_venv_homes(root)
    locks = runtime_lock_paths(root)
    protected = homes | locks
    safe = find_safe_candidates(root)
    review = find_review_candidates(root, protected)
    dupes = deep_duplicates(root) if deep else []
    return {
        "version": VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.time() - t0, 2),
        "safe_candidates": [asdict(x) for x in safe],
        "review_candidates": [asdict(x) for x in review],
        "safe_reclaimable_bytes": sum(x.bytes for x in safe),
        "review_reclaimable_bytes": sum(x.bytes for x in review),
        "protected_runtime_paths": [str(p) for p in sorted(protected, key=lambda x: str(x).lower())],
        "largest_top_level": largest_top_level(root),
        "duplicate_groups": dupes,
        "duplicate_reclaimable_bytes": sum(int(x.get("wasted_bytes", 0)) for x in dupes),
        "deep_scan": bool(deep),
    }


def _rotate_pair(latest: Path, previous: Path) -> None:
    try:
        if previous.exists():
            previous.unlink()
        if latest.exists():
            latest.replace(previous)
    except OSError:
        pass


def write_report(root: Path, report: dict, report_key: str = "storage_audit") -> tuple[Path, Path]:
    out = root / "Data" / "Maintenance"
    out.mkdir(parents=True, exist_ok=True)
    j = out / f"{report_key}_latest.json"
    t = out / f"{report_key}_latest.txt"
    pj = out / f"{report_key}_previous.json"
    pt = out / f"{report_key}_previous.txt"
    _rotate_pair(j, pj)
    _rotate_pair(t, pt)
    j.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"PortableAI storage audit v{VERSION}",
        "=" * 78,
        f"Root: {report['root']}",
        f"Elapsed: {report['elapsed_seconds']} s",
        f"Safe reclaimable: {human(report['safe_reclaimable_bytes'])}",
        f"Review reclaimable: {human(report['review_reclaimable_bytes'])}",
        f"Theoretical physical duplicate bytes: {human(report.get('duplicate_reclaimable_bytes', 0))} (analysis only; NOT a safe-delete estimate)" if report.get("deep_scan") else "Duplicate scan: not run (use --deep)",
        "",
        "Largest top-level items",
        "-" * 78,
    ]
    for row in report.get("largest_top_level", []):
        lines.append(f"{human(int(row['bytes'])):>10}  {row['path']}")
    lines += ["", "SAFE CLEANUP CANDIDATES", "-" * 78]
    for c in report.get("safe_candidates", []):
        lines.append(f"{human(int(c['bytes'])):>10}  {c['path']}\n            {c['reason']}")
    if not report.get("safe_candidates"):
        lines.append("None detected.")
    lines += ["", "REVIEW BEFORE DELETING", "-" * 78]
    for c in report.get("review_candidates", []):
        lines.append(f"{human(int(c['bytes'])):>10}  {c['path']}\n            {c['reason']}")
    if not report.get("review_candidates"):
        lines.append("None detected.")
    if report.get("deep_scan"):
        lines += ["", "LARGE EXACT DUPLICATES", "-" * 78]
        for g in report.get("duplicate_groups", []):
            lines.append(f"Physical waste {human(int(g['wasted_bytes']))} | each {human(int(g['bytes_each']))} | physical copies {g.get('physical_copies', '?')} | paths {g.get('path_count', len(g.get('files', [])))}")
            lines.append(f"    Category: {g.get('category', 'exact-duplicate-review')} | safe-delete: NO")
            lines.append(f"    {g.get('advice', 'Review only; do not delete by hash match alone.')}")
            for f in g.get("files", []):
                lines.append(f"    {f}")
        if not report.get("duplicate_groups"):
            lines.append("No exact duplicates >=128 MB were found outside Data/Outputs/Backups.")
    if report.get("cleanup"):
        cleanup_rows = list(report.get("cleanup") or [])
        ok_rows = [x for x in cleanup_rows if x.get("ok")]
        fail_rows = [x for x in cleanup_rows if not x.get("ok")]
        lines += ["", "CLEANUP RESULT", "-" * 78,
                  f"Reclaimed: {human(int(report.get('cleanup_reclaimed_bytes', 0)))}",
                  f"Deleted: {len(ok_rows)}    Failed: {len(fail_rows)}"]
        # Keep the text report useful without turning thousands of cache failures
        # into another multi-megabyte log. Full structured details remain in JSON.
        for x in fail_rows[:100]:
            lines.append(f"FAIL {human(int(x.get('bytes', 0))):>10}  {x.get('path')}  {x.get('message')}")
        if len(fail_rows) > 100:
            lines.append(f"... {len(fail_rows) - 100} additional failures are retained in the JSON report.")
    lines += ["", "Protected runtime/base paths", "-" * 78]
    for p in report.get("protected_runtime_paths", []):
        lines.append(p)
    t.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return j, t


def main() -> int:
    ap = argparse.ArgumentParser(description="PortableAI storage audit / conservative cleanup")
    ap.add_argument("--root", required=True)
    ap.add_argument("--deep", action="store_true", help="Hash large same-size files to find exact duplicates")
    ap.add_argument("--cleanup-safe", action="store_true", help="Delete only high-confidence cache/installer artifacts")
    ap.add_argument("--prune-backups", type=int, metavar="KEEP", help="Explicitly delete old Backups entries, keeping newest KEEP")
    ap.add_argument("--remove-legacy-frontends", action="store_true", help="Explicitly delete OpenGUI and OpenWebUI after audit")
    ap.add_argument("--remove-legacy", action="append", choices=("OpenGUI", "OpenWebUI", "OpenGUI-Source"), help="Explicitly delete one selected legacy frontend/source tree; may be repeated")
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 2

    report = audit(root, deep=ns.deep)
    cleanup = []
    if ns.cleanup_safe:
        for c in report.get("safe_candidates", []):
            p = Path(c["path"])
            before = int(c.get("bytes", 0))
            ok, msg = delete_path(p)
            cleanup.append({"path": str(p), "bytes": before, "ok": ok, "message": msg, "class": "safe"})
    if ns.prune_backups is not None:
        cleanup.extend({**x, "class": "backup"} for x in prune_old_backups(root, max(0, ns.prune_backups)))
    legacy_names = []
    if ns.remove_legacy_frontends:
        legacy_names.extend(("OpenGUI", "OpenWebUI"))
    legacy_names.extend(list(ns.remove_legacy or []))
    for name in dict.fromkeys(legacy_names):
        p = root / name
        if p.exists():
            before = dir_size(p)
            ok, msg = delete_path(p)
            cleanup.append({"path": str(p), "bytes": before, "ok": ok, "message": msg, "class": "legacy-frontend"})

    if cleanup:
        report["cleanup"] = cleanup
        report["cleanup_reclaimed_bytes"] = sum(int(x["bytes"]) for x in cleanup if x.get("ok"))
        # Re-audit after deletion so the visible report reflects current disk state.
        post = audit(root, deep=False)
        post["cleanup"] = cleanup
        post["cleanup_reclaimed_bytes"] = report["cleanup_reclaimed_bytes"]
        report = post

    if ns.cleanup_safe:
        report_key = "storage_cleanup"
    elif ns.remove_legacy_frontends or ns.remove_legacy:
        report_key = "legacy_frontend_cleanup"
    elif ns.prune_backups is not None:
        report_key = "backup_cleanup"
    elif ns.deep:
        report_key = "deep_duplicate_scan"
    else:
        report_key = "storage_audit"
    j, t = write_report(root, report, report_key=report_key)
    print(f"PortableAI storage audit v{VERSION}")
    print(f"Safe reclaimable: {human(int(report.get('safe_reclaimable_bytes', 0)))}")
    print(f"Review reclaimable: {human(int(report.get('review_reclaimable_bytes', 0)))}")
    if ns.deep:
        print(f"Theoretical physical duplicate bytes: {human(int(report.get('duplicate_reclaimable_bytes', 0)))} (analysis only; NOT a safe-delete estimate)")
    if report.get("cleanup"):
        reclaimed = int(report.get("cleanup_reclaimed_bytes", 0))
        rows = list(report.get("cleanup") or [])
        ok_count = sum(1 for x in rows if x.get("ok"))
        failed = [x for x in rows if not x.get("ok")]
        print(f"Cleanup reclaimed: {human(reclaimed)} | deleted {ok_count} | failed {len(failed)}")
        for x in failed[:100]:
            print(f"  FAIL {human(int(x.get('bytes', 0))):>10}  {x.get('path')}  {x.get('message')}")
        if len(failed) > 100:
            print(f"  ... {len(failed) - 100} more failures are in the JSON report")
    print(f"Report: {t}")
    print(f"JSON:   {j}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
