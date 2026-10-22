# PORTABLEAI_BACKUP_RETENTION_v15_127B
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

# Python -I intentionally removes the script directory from sys.path. PortableAI
# maintenance tools run isolated, so add only this trusted Tools directory back.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import storage_audit
import root_reference_audit
import dependency_probe

VERSION = "15.106"

# The generalized cleanup engine is intentionally conservative. It only auto-deletes
# categories that are either regenerable/transient, bounded rollback history, or
# top-level historical/build trees that the reference audit classifies REVIEW-DELETE.
# Cache roots that may be dynamically resolved remain visible as HELD/INSPECT items.
BUILD_STAGING_NAMES = (
    "Installer",
    "Raw Files",
    "Patch",
    "PatchPayload",
    "Payload",
    "_UpdatePayload",
    "UpdatePayload",
    "OpenGUI-Source",
)
LEGACY_FRONTEND_NAMES = ("OpenGUI", "OpenWebUI")
HELD_CACHE_NAMES = ("PortableCache", "Cache")
DYNAMIC_PROBE_NAMES = ("Models", "PortableCache", "Cache")

# These files were only useful to the retired frontend branches. They are eligible
# only when the corresponding frontend tree is gone and the current GUI no longer
# references that branch.
LEGACY_SUPPORT_FILES = (
    "Launchers/Start_OpenGUI_Qwen.bat",
    "Launchers/Start_OpenGUI_Watched.ps1",
    "Launchers/Start_Legacy_OpenWebUI.cmd",
    "Tools/openwebui_legacy.py",
)

CATEGORIES = (
    "safe",
    "backups",
    "build-staging",
    "legacy",
    "maintenance-history",
    "frontend-support",
    "root-hygiene",
    "confirmed-unused",
)

RECOMMENDED = set(CATEGORIES)
SAFE_ONLY = {"safe", "maintenance-history"}


@dataclass
class PlanItem:
    path: str
    bytes: int
    category: str
    action: str
    reason: str
    confidence: str = "high"
    selected_by_default: bool = True
    exists: bool = True
    destination: str | None = None


def human(n: int) -> str:
    return storage_audit.human(int(n or 0))


def _norm(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except Exception:
        return os.path.normcase(str(path))


def _under_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_dir():
        return storage_audit.dir_size(path)
    return storage_audit.file_size(path)


def _add(items: list[PlanItem], seen: set[str], root: Path, path: Path, *, category: str,
         action: str, reason: str, confidence: str = "high", selected: bool = True,
         destination: Path | None = None) -> None:
    if not _under_root(root, path):
        return
    key = _norm(path)
    if key in seen:
        return
    seen.add(key)
    items.append(PlanItem(
        path=str(path),
        bytes=_path_size(path),
        category=category,
        action=action,
        reason=reason,
        confidence=confidence,
        selected_by_default=selected,
        exists=path.exists(),
        destination=str(destination) if destination is not None else None,
    ))




ROOT_KEEP_NAMES = {
    "PortableAI Launcher.vbs",
    "README.txt",
}

_INSTALL_RE = re.compile(r"^install_(?:portableai|portability)_v.*\.(?:cmd|bat|ps1)$", re.I)
_REPAIR_RE = re.compile(r"^(?:resolve|repair|fix|hotfix|patch)_.*\.(?:cmd|bat|ps1|py)$", re.I)
_TEST_RE = re.compile(r"^test(?:_|.*_v\d).*\.(?:cmd|bat|ps1|py)$", re.I)
_AUDIT_RE = re.compile(r"^(?:portableai|portability)_audit_.*\.(?:json|md|txt)$", re.I)
_MASTER_RE = re.compile(r"^PortableAI_Master_Instructions_v(\d+)\.(?:txt|md)$", re.I)
_PACKAGE_RE = re.compile(r"^PortableAI_v\d+(?:[._-].*)?\.zip$", re.I)

def _safe_move_target(dest: Path, src: Path) -> Path:
    """Choose a destination without overwriting a different existing file."""
    if not dest.exists():
        return dest
    try:
        if src.is_file() and dest.is_file() and src.stat().st_size == dest.stat().st_size:
            # Byte compare is cheap here because root-hygiene files are small.
            if src.read_bytes() == dest.read_bytes():
                return dest
    except OSError:
        pass
    stem, suffix = dest.stem, dest.suffix
    for i in range(1, 1000):
        cand = dest.with_name(f"{stem}_legacy{i}{suffix}")
        if not cand.exists():
            return cand
    return dest.with_name(f"{stem}_{int(time.time())}{suffix}")

def _root_hygiene_candidates(root: Path) -> list[PlanItem]:
    """Return root-only clutter actions. Never recurse through component trees.

    Root hygiene is intentionally cosmetic/organizational: old installer wrappers are
    deleted, while still-useful diagnostics/history are moved under bounded maintenance
    folders. The active launcher, README and newest master-instructions file stay at root.
    """
    items: list[PlanItem] = []
    seen: set[str] = set()
    try:
        entries = [p for p in root.iterdir() if p.is_file()]
    except OSError:
        return items

    masters=[]
    for p in entries:
        m=_MASTER_RE.match(p.name)
        if m:
            masters.append((int(m.group(1)), p))
    newest_master = max(masters, default=(None, None), key=lambda x: x[0])[1]

    legacy_tools = root / "Data" / "Maintenance" / "LegacyTools"
    legacy_reports = root / "Data" / "Maintenance" / "LegacyReports"
    instruction_history = root / "Data" / "Maintenance" / "InstructionHistory"
    test_archive = root / "ControlCenter" / "LegacyDiagnosis" / "RootMigrated"
    launchers = root / "Launchers"
    package_archive = root / "Data" / "Maintenance" / "InstallPackages"

    active_installer = os.environ.get("PORTABLEAI_ACTIVE_INSTALLER", "").strip()
    active_installer_norm = _norm(Path(active_installer)) if active_installer else ""

    for p in entries:
        name=p.name
        low=name.lower()
        if name in ROOT_KEEP_NAMES or p == newest_master:
            continue
        if active_installer_norm and _norm(p) == active_installer_norm:
            # The installer wrapper may still be executing. The batch wrapper removes
            # itself after the Python helper exits, so do not race the running script.
            continue
        if _INSTALL_RE.match(name):
            _add(items, seen, root, p, category="root-hygiene", action="DELETE",
                 reason="Obsolete one-shot installer wrapper; installed files live in their canonical PortableAI locations.",
                 confidence="high", selected=True)
            continue
        if _AUDIT_RE.match(name):
            dest=_safe_move_target(legacy_reports / name, p)
            _add(items, seen, root, p, category="root-hygiene", action="MOVE", destination=dest,
                 reason="Legacy audit artifact moved out of the project root; current/previous maintenance reports live under Data/Maintenance.",
                 confidence="high", selected=True)
            continue
        if _MASTER_RE.match(name) and p != newest_master:
            dest=_safe_move_target(instruction_history / name, p)
            _add(items, seen, root, p, category="root-hygiene", action="MOVE", destination=dest,
                 reason=f"Older master-instructions revision archived; newest revision remains at root: {newest_master.name if newest_master else 'unknown'}.",
                 confidence="high", selected=True)
            continue
        if low == "launch_portablechat.cmd":
            dest=_safe_move_target(launchers / name, p)
            _add(items, seen, root, p, category="root-hygiene", action="MOVE", destination=dest,
                 reason="Secondary Native Chat launcher belongs under Launchers; PortableAI Launcher.vbs remains the root entry point.",
                 confidence="high", selected=True)
            continue
        if _TEST_RE.match(name) or low == "testimage.jpg":
            dest=_safe_move_target(test_archive / name, p)
            _add(items, seen, root, p, category="root-hygiene", action="MOVE", destination=dest,
                 reason="Historical/manual diagnostic asset moved under ControlCenter/LegacyDiagnosis instead of cluttering the root.",
                 confidence="high", selected=True)
            continue
        if _REPAIR_RE.match(name):
            dest=_safe_move_target(legacy_tools / name, p)
            _add(items, seen, root, p, category="root-hygiene", action="MOVE", destination=dest,
                 reason="One-off repair/patch helper archived under Data/Maintenance/LegacyTools.",
                 confidence="high", selected=True)
            continue
        if _PACKAGE_RE.match(name):
            dest=_safe_move_target(package_archive / name, p)
            _add(items, seen, root, p, category="root-hygiene", action="MOVE", destination=dest,
                 reason="PortableAI update package moved out of the project root.",
                 confidence="high", selected=True)
            continue
        if low.endswith((".tmp", ".temp", ".bak", ".old")) or low.startswith("~"):
            _add(items, seen, root, p, category="root-hygiene", action="DELETE",
                 reason="Root-level temporary/backup debris.", confidence="high", selected=True)

    return items

def _trim_root_archives(root: Path) -> list[dict]:
    """Bound organizational archives so root cleanup never becomes long-term bloat."""
    results=[]
    policies=(
        (root / "Data" / "Maintenance" / "LegacyReports", 4),
        (root / "Data" / "Maintenance" / "InstructionHistory", 2),
        (root / "Data" / "Maintenance" / "InstallPackages", 2),
    )
    for folder, keep in policies:
        if not folder.exists():
            continue
        try:
            files=[p for p in folder.iterdir() if p.is_file()]
            files.sort(key=lambda p:p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for p in files[keep:]:
            b=_path_size(p)
            ok,msg=storage_audit.delete_path(p)
            results.append({"path":str(p),"bytes":b,"category":"root-hygiene","ok":ok,"message":f"archive trim: {msg}"})
    return results


def _backup_family(name: str) -> str | None:
    """Return a conservative rollback family; unknown names are never auto-pruned."""
    low = str(name or "").strip().casefold()
    if not low:
        return None
    if re.match(r"^v\d+(?:[._-]\d+)*(?:[a-z])?(?:_|$)", low):
        return "core-update"
    m = re.match(r"^(?P<prefix>[a-z0-9][a-z0-9_-]*?)_v\d", low)
    if m:
        prefix = re.sub(r"[^a-z0-9]+", "-", m.group("prefix")).strip("-")
        return prefix or None
    m = re.match(r"^(?P<prefix>[a-z0-9][a-z0-9_-]*?)_before_(?:install|repair|apply|patch)(?:_|$)", low)
    if m:
        prefix = re.sub(r"[^a-z0-9]+", "-", m.group("prefix")).strip("-")
        return prefix or None
    # Timestamped named rollback such as MMAudio_Source_incomplete_20260917_024437.
    m = re.match(r"^(?P<prefix>.+?)_20\d{6}(?:_\d{6}(?:_\d+)?)?$", low)
    if m:
        prefix = re.sub(r"[^a-z0-9]+", "-", m.group("prefix")).strip("-")
        return prefix or None
    return None


def _backup_candidates(root: Path, keep: int) -> list[Path]:
    """Keep the newest N rollbacks PER identifiable component/family.

    Ambiguous backup names are preserved instead of being guessed into a family.
    This prevents a burst of unrelated GUI patches from evicting the last useful
    rollback for a runtime or media subsystem.
    """
    base = root / "Backups"
    if not base.exists():
        return []
    try:
        dirs = [p for p in base.iterdir() if p.is_dir()]
    except OSError:
        return []
    groups: dict[str, list[Path]] = {}
    for p in dirs:
        family = _backup_family(p.name)
        if family is None:
            continue
        groups.setdefault(family, []).append(p)
    out: list[Path] = []
    for rows in groups.values():
        try:
            rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        out.extend(rows[max(0, int(keep)):])
    return out


def _reference_rows(root: Path, names: Iterable[str]) -> dict[str, dict]:
    paths = [root / name for name in names if (root / name).exists()]
    if not paths:
        return {}
    refs = root_reference_audit.scan_references(root, paths)
    protected = root_reference_audit.runtime_lock_paths(root) | root_reference_audit.parse_venv_homes(root)
    out: dict[str, dict] = {}
    for p in paths:
        out[p.name] = root_reference_audit.classify(root, p, protected, refs.get(p.name, []))
    return out


def _maintenance_history_candidates(root: Path) -> list[Path]:
    """Return stale report generations while preserving current + previous.

    v15.100+ uses <key>_latest and <key>_previous. Historical timestamped reports
    from older builds are safe to remove because the two bounded generations are
    the supported history surface now.
    """
    base = root / "Data" / "Maintenance"
    if not base.exists():
        return []
    keep_suffixes = ("_latest.txt", "_latest.json", "_previous.txt", "_previous.json")
    out: list[Path] = []
    try:
        for p in base.iterdir():
            if not p.is_file():
                continue
            low = p.name.lower()
            if low == "dependency_probe_journal.json":
                # Crash-recovery state, not report history. Never prune while a
                # candidate tree might still be quarantined.
                continue
            if low.endswith(keep_suffixes):
                continue
            if low.endswith((".txt", ".json", ".log")):
                out.append(p)
    except OSError:
        return []
    return out


def _frontend_support_candidates(root: Path) -> list[Path]:
    # Do not prune support files while either retired frontend directory remains.
    # Once both frontend trees are gone, the current GUI hides their controls/status cards,
    # so their dedicated launch helpers are dead code and can be removed.
    if any((root / n).exists() for n in LEGACY_FRONTEND_NAMES):
        return []
    return [root / rel for rel in LEGACY_SUPPORT_FILES if (root / rel).exists()]


def _validated_dependency_probe(root: Path) -> tuple[dict[str, dict], list[dict]]:
    """Return full-probe confirmed-unused rows whose tree is still byte-metadata identical.

    The dynamic probe temporarily quarantines Models/Cache/PortableCache and restores them.
    General Cleanup only trusts a FULL, cleanly-restored report for the exact current tree.
    """
    path = root / "Data" / "Maintenance" / "dependency_probe_latest.json"
    confirmed: dict[str, dict] = {}
    held: list[dict] = []
    report = None
    if path.exists():
        try:
            report = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            report = None
    for name in DYNAMIC_PROBE_NAMES:
        p = root / name
        if not p.exists():
            continue
        base = {
            "name": name, "path": str(p), "bytes": _path_size(p),
            "category": "dynamic-dependency", "reference_count": 0, "references": [],
        }
        if not isinstance(report, dict):
            held.append({**base, "action": "DEPENDENCY-PROBE", "confidence": "low",
                         "reason": "No current empirical dependency-probe report. Run Installed > Dependency Probe before deleting this ambiguous tree."})
            continue
        if str(report.get("root") or "") != str(root) or report.get("suite") != "full" or not report.get("finished_cleanly"):
            held.append({**base, "action": "REPROBE", "confidence": "low",
                         "reason": "Latest dependency probe is not a FULL clean-restored probe for this exact PortableAI root."})
            continue
        row = next((x for x in (report.get("candidates") or []) if x.get("name") == name), None)
        if not isinstance(row, dict) or row.get("status") not in {"CONFIRMED_UNUSED", "CONFIRMED_REGENERABLE"}:
            held.append({**base, "action": str((row or {}).get("status") or "DEPENDENCY-PROBE"), "confidence": "low",
                         "reason": str((row or {}).get("reason") or "Dependency probe did not confirm this tree as disposable.")})
            continue
        expected = (row.get("manifest_after_restore") or row.get("manifest_before") or {}).get("sha256")
        current = dependency_probe.manifest_digest(p)
        if not expected or current.get("sha256") != expected:
            held.append({**base, "bytes": int(current.get("bytes") or 0), "action": "REPROBE", "confidence": "high",
                         "reason": "Tree contents changed since dependency probe; confirmation is stale and cannot authorize deletion."})
            continue
        confirmed[name] = {**row, "current_manifest": current}
    return confirmed, held


def build_plan(root: Path, keep_backups: int = 3) -> dict:
    t0 = time.time()
    root = root.resolve()
    items: list[PlanItem] = []
    held: list[dict] = []
    seen: set[str] = set()

    # 1) Fast safe-transient scan. storage_audit v15.103 deliberately avoids
    # crawling giant model/runtime/backup trees for tiny pycache wins.
    for c in storage_audit.find_safe_candidates(root):
        _add(items, seen, root, Path(c.path), category="safe", action="DELETE",
             reason=c.reason, confidence=c.confidence, selected=True)

    # 2) Bounded rollback history.
    for p in _backup_candidates(root, keep_backups):
        _add(items, seen, root, p, category="backups", action="DELETE",
             reason=f"Rollback backup older than the newest {keep_backups} for its component/family; ambiguous backup names are preserved.",
             confidence="high", selected=True)

    # 3) Historical build/staging and retired frontend trees, gated by the same
    # reference + runtime protection logic used by Root Reference Audit.
    names = tuple(dict.fromkeys(BUILD_STAGING_NAMES + LEGACY_FRONTEND_NAMES + HELD_CACHE_NAMES))
    ref_rows = _reference_rows(root, names)
    for name in BUILD_STAGING_NAMES:
        row = ref_rows.get(name)
        if not row:
            continue
        if row.get("action") == "REVIEW-DELETE":
            _add(items, seen, root, root / name, category="build-staging", action="DELETE",
                 reason=str(row.get("reason") or "Unreferenced historical build/staging tree."),
                 confidence=str(row.get("confidence") or "medium"), selected=True)
        else:
            held.append(row)
    for name in LEGACY_FRONTEND_NAMES:
        row = ref_rows.get(name)
        if not row:
            continue
        if row.get("action") == "REVIEW-DELETE":
            _add(items, seen, root, root / name, category="legacy", action="DELETE",
                 reason=str(row.get("reason") or "Retired frontend tree with no active references."),
                 confidence=str(row.get("confidence") or "medium"), selected=True)
        else:
            held.append(row)

    # PortableCache / Cache (and Models) are never promoted by name or text grep.
    # A FULL empirical dependency probe can promote the exact unchanged tree.
    for name in HELD_CACHE_NAMES:
        row = ref_rows.get(name)
        if row:
            held.append(row)

    confirmed_dynamic, dynamic_held = _validated_dependency_probe(root)
    # For these three ambiguous dynamic roots, the empirical-probe state is more
    # informative than the old text-reference INSPECT row. Replace, don't duplicate.
    held = [x for x in held if Path(str(x.get("path") or x.get("name") or "")).name not in set(DYNAMIC_PROBE_NAMES)]
    if confirmed_dynamic:
        for name, row in confirmed_dynamic.items():
            _add(items, seen, root, root / name, category="confirmed-unused", action="DELETE",
                 reason=("FULL empirical dependency probe passed with this tree quarantined; exact tree manifest still matches. "
                         + ("Consumers recreated disposable cache data in an empty placeholder." if row.get("status") == "CONFIRMED_REGENERABLE" else "No tested local capability required its contents.")),
                 confidence="high", selected=True)
    held.extend(dynamic_held)

    # 4) Bounded maintenance history.
    for p in _maintenance_history_candidates(root):
        _add(items, seen, root, p, category="maintenance-history", action="DELETE",
             reason="Obsolete maintenance-report generation; Current + Previous are retained.",
             confidence="high", selected=True)

    # 5) Retired frontend launcher/helper leftovers after the frontend trees and
    # current GUI references are gone.
    for p in _frontend_support_candidates(root):
        _add(items, seen, root, p, category="frontend-support", action="DELETE",
             reason="Retired frontend support file is no longer referenced by the current Native Chat Control Center.",
             confidence="high", selected=True)

    # 6) Root hygiene: remove one-shot installers and organize historical helpers
    # without touching active component directories. This is a root-only scan and
    # therefore essentially instantaneous even on a multi-hundred-GB installation.
    for x in _root_hygiene_candidates(root):
        key=_norm(Path(x.path))
        if key not in seen:
            seen.add(key); items.append(x)

    items.sort(key=lambda x: x.bytes, reverse=True)
    by_category: dict[str, int] = {k: 0 for k in CATEGORIES}
    for item in items:
        by_category[item.category] = by_category.get(item.category, 0) + int(item.bytes)

    return {
        "version": VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.time() - t0, 2),
        "keep_backups": int(keep_backups),
        "items": [asdict(x) for x in items],
        "held_items": held,
        "category_bytes": by_category,
        "recommended_reclaimable_bytes": sum(int(x.bytes) for x in items if x.selected_by_default and str(x.action).upper() == "DELETE"),
        "organizational_move_bytes": sum(int(x.bytes) for x in items if x.selected_by_default and str(x.action).upper() == "MOVE"),
        "largest_top_level": storage_audit.largest_top_level(root),
    }


def build_root_hygiene_plan(root: Path) -> dict:
    """Build only the deterministic root-file hygiene plan.

    This never walks component/runtime/model trees, never hashes files, and never runs
    the reference audit. It is safe to run during installation or startup without
    making the launcher feel hung.
    """
    t0 = time.time()
    root = root.resolve()
    items = _root_hygiene_candidates(root)
    items.sort(key=lambda x: x.bytes, reverse=True)
    return {
        "version": VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.time() - t0, 3),
        "keep_backups": 3,
        "items": [asdict(x) for x in items],
        "held_items": [],
        "category_bytes": {"root-hygiene": sum(int(x.bytes) for x in items)},
        "recommended_reclaimable_bytes": sum(int(x.bytes) for x in items if str(x.action).upper() == "DELETE"),
        "organizational_move_bytes": sum(int(x.bytes) for x in items if str(x.action).upper() == "MOVE"),
        # Intentionally omitted in fast root mode: recursive top-level sizing can take
        # tens of seconds on a hundreds-of-GB OneDrive-backed PortableAI tree.
        "largest_top_level": [],
    }


def apply_root_hygiene_plan(root: Path, plan: dict) -> dict:
    """Apply only root-hygiene items without rebuilding the expensive full plan."""
    root = root.resolve()
    results = []
    reclaimed = 0
    changed = failed = absent = 0

    for original in plan.get("items", []):
        item = dict(original)
        p = Path(str(item.get("path") or ""))
        if not _under_root(root, p):
            results.append({**item, "ok": False, "message": "refused: path is outside PortableAI root"})
            failed += 1
            continue
        if not p.exists() and not p.is_symlink():
            results.append({**item, "ok": True, "message": "already absent"})
            absent += 1
            continue

        before = _path_size(p)
        action = str(item.get("action") or "DELETE").upper()
        if action == "MOVE":
            dest_raw = str(item.get("destination") or "").strip()
            dest = Path(dest_raw) if dest_raw else None
            if dest is None or not _under_root(root, dest):
                ok, msg = False, "refused: invalid move destination"
            else:
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        try:
                            same = p.is_file() and dest.is_file() and p.stat().st_size == dest.stat().st_size and p.read_bytes() == dest.read_bytes()
                        except OSError:
                            same = False
                        if same:
                            ok, msg = storage_audit.delete_path(p)
                            msg = "destination already had identical file; removed root duplicate" if ok else msg
                        else:
                            dest = _safe_move_target(dest, p)
                            shutil.move(str(p), str(dest))
                            item["destination"] = str(dest)
                            ok, msg = True, f"moved to {dest}"
                    else:
                        shutil.move(str(p), str(dest))
                        ok, msg = True, f"moved to {dest}"
                except Exception as exc:
                    ok, msg = False, str(exc)
        else:
            ok, msg = storage_audit.delete_path(p)

        results.append({**item, "bytes": before, "ok": ok, "message": msg})
        if ok:
            changed += 1
            if action == "DELETE":
                reclaimed += before
        else:
            failed += 1

    trim_results = _trim_root_archives(root)
    results.extend(trim_results)
    for row in trim_results:
        if row.get("ok"):
            reclaimed += int(row.get("bytes") or 0)
            changed += 1
        else:
            failed += 1

    post = build_root_hygiene_plan(root)
    post.update({
        "applied": True,
        "selected_categories": ["root-hygiene"],
        "results": results,
        "reclaimed_bytes": reclaimed,
        "deleted_count": changed,
        "failed_count": failed,
        "absent_count": absent,
    })
    return post


def _rotate(latest: Path, previous: Path) -> None:
    try:
        if previous.exists():
            previous.unlink()
        if latest.exists():
            latest.replace(previous)
    except OSError:
        pass


def write_report(root: Path, report: dict, key: str) -> tuple[Path, Path]:
    out = root / "Data" / "Maintenance"
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"{key}_latest.json"
    tp = out / f"{key}_latest.txt"
    pjp = out / f"{key}_previous.json"
    ptp = out / f"{key}_previous.txt"
    _rotate(jp, pjp)
    _rotate(tp, ptp)
    jp.write_text(json.dumps(report, indent=2), encoding="utf-8")

    applied = bool(report.get("applied"))
    lines = [
        f"PortableAI generalized cleanup v{VERSION}",
        "=" * 84,
        f"Root: {report.get('root')}",
        f"Generated: {report.get('generated_at')}",
        f"Mode: {'APPLIED' if applied else 'PLAN / DRY RUN'}",
        f"Keep newest backups per family: {report.get('keep_backups', 3)}",
        f"Selected categories: {', '.join(report.get('selected_categories') or []) or '(plan only / none recorded)'}",
        f"Recommended reclaimable: {human(int(report.get('recommended_reclaimable_bytes', 0)))}",
        f"Move-only root organization: {human(int(report.get('organizational_move_bytes', 0)))}",
    ]
    if applied:
        lines.append(f"Actually reclaimed: {human(int(report.get('reclaimed_bytes', 0)))}")
        lines.append(f"Deleted: {report.get('deleted_count', 0)}    Failed: {report.get('failed_count', 0)}    Already absent: {report.get('absent_count', 0)}")
    lines += ["", "CANDIDATES", "-" * 84]
    for x in report.get("items", []):
        action=x.get('action','DELETE')
        dest=x.get('destination')
        suffix=f" -> {dest}" if dest else ""
        lines.append(f"{x.get('category','?'):<20} {human(int(x.get('bytes',0))):>10}  {action:<6} {x.get('path')}{suffix}")
        lines.append(f"    {x.get('confidence','')} | {x.get('reason','')}")
    if not report.get("items"):
        lines.append("No generalized cleanup candidates were found.")

    held = report.get("held_items") or []
    lines += ["", "HELD / NOT AUTO-DELETED", "-" * 84]
    if held:
        for x in held:
            lines.append(f"{x.get('action','INSPECT'):<13} {human(int(x.get('bytes',0))):>10}  {x.get('path')}")
            lines.append(f"    {x.get('reason','')} refs={x.get('reference_count',0)}")
    else:
        lines.append("None.")

    if applied:
        lines += ["", "APPLY RESULTS", "-" * 84]
        for x in report.get("results", []):
            state = "OK" if x.get("ok") else "FAIL"
            lines.append(f"{state:<5} {human(int(x.get('bytes',0))):>10}  {x.get('path')}  [{x.get('category')}] {x.get('message')}")

    lines += ["", "LARGEST TOP-LEVEL ITEMS AFTER PLAN/APPLY", "-" * 84]
    for row in report.get("largest_top_level", []):
        lines.append(f"{human(int(row.get('bytes',0))):>10}  {row.get('path')}")

    tp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jp, tp


def apply_plan(root: Path, plan: dict, include: set[str]) -> dict:
    root = root.resolve()
    results = []
    reclaimed = 0
    deleted = failed = absent = 0

    for item in plan.get("items", []):
        category = str(item.get("category") or "")
        if category not in include:
            continue
        p = Path(str(item.get("path") or ""))
        if not _under_root(root, p):
            results.append({**item, "ok": False, "message": "refused: path is outside PortableAI root"})
            failed += 1
            continue
        if not p.exists() and not p.is_symlink():
            results.append({**item, "ok": True, "message": "already absent"})
            absent += 1
            continue
        before = _path_size(p)
        action=str(item.get("action") or "DELETE").upper()
        if action == "MOVE":
            dest_raw=str(item.get("destination") or "").strip()
            dest=Path(dest_raw) if dest_raw else None
            if dest is None or not _under_root(root, dest):
                ok, msg = False, "refused: invalid move destination"
            else:
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        try:
                            same=(p.is_file() and dest.is_file() and p.stat().st_size==dest.stat().st_size and p.read_bytes()==dest.read_bytes())
                        except OSError:
                            same=False
                        if same:
                            ok, msg = storage_audit.delete_path(p)
                            msg = "destination already had identical file; removed root duplicate" if ok else msg
                        else:
                            dest=_safe_move_target(dest, p)
                            shutil.move(str(p), str(dest))
                            item["destination"]=str(dest)
                            ok, msg=True, f"moved to {dest}"
                    else:
                        shutil.move(str(p), str(dest))
                        ok, msg=True, f"moved to {dest}"
                except Exception as exc:
                    ok, msg=False, str(exc)
        else:
            ok, msg = storage_audit.delete_path(p)
        results.append({**item, "bytes": before, "ok": ok, "message": msg})
        if ok:
            if action == "DELETE":
                reclaimed += before
            deleted += 1
        else:
            failed += 1

    if "root-hygiene" in include:
        trim_results=_trim_root_archives(root)
        results.extend(trim_results)
        for row in trim_results:
            if row.get("ok"):
                reclaimed += int(row.get("bytes") or 0)
                deleted += 1
            else:
                failed += 1

    post = build_plan(root, keep_backups=int(plan.get("keep_backups", 3)))
    post.update({
        "applied": True,
        "selected_categories": sorted(include),
        "results": results,
        "reclaimed_bytes": reclaimed,
        "deleted_count": deleted,
        "failed_count": failed,
        "absent_count": absent,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return post


def parse_categories(ns) -> set[str]:
    if ns.include:
        include = set(ns.include)
    elif ns.preset == "safe":
        include = set(SAFE_ONLY)
    else:
        include = set(RECOMMENDED)
    include -= set(ns.exclude or [])
    return include


def main() -> int:
    ap = argparse.ArgumentParser(description="PortableAI generalized cleanup engine")
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true", help="Actually delete selected plan items. Without this flag the command is a dry-run plan.")
    ap.add_argument("--preset", choices=("safe", "recommended"), default="recommended")
    ap.add_argument("--keep-backups", type=int, default=3)
    ap.add_argument("--root-only", action="store_true", help="Fast root hygiene only; never scans component/model/runtime trees.")
    ap.add_argument("--include", action="append", choices=CATEGORIES, help="Include only this cleanup category; may be repeated")
    ap.add_argument("--exclude", action="append", choices=CATEGORIES, help="Exclude this cleanup category; may be repeated")
    ns = ap.parse_args()

    root = Path(ns.root).resolve()
    if not root.exists():
        print(f"ERROR: PortableAI root not found: {root}")
        return 2

    if ns.root_only:
        include = {"root-hygiene"}
        plan = build_root_hygiene_plan(root)
        if ns.apply:
            report = apply_root_hygiene_plan(root, plan)
            key = "root_hygiene_apply"
        else:
            report = plan
            report["applied"] = False
            report["selected_categories"] = ["root-hygiene"]
            key = "root_hygiene_plan"
    else:
        include = parse_categories(ns)
        plan = build_plan(root, keep_backups=max(0, ns.keep_backups))
        if ns.apply:
            report = apply_plan(root, plan, include)
            key = "general_cleanup_apply"
        else:
            report = plan
            report["applied"] = False
            report["selected_categories"] = sorted(include)
            key = "general_cleanup_plan"

    j, t = write_report(root, report, key)
    print(f"PortableAI generalized cleanup v{VERSION}")
    print(f"Mode: {'APPLY' if ns.apply else 'PLAN'}")
    print(f"Selected categories: {', '.join(sorted(include)) or '(none)'}")
    print(f"Recommended reclaimable: {human(int(report.get('recommended_reclaimable_bytes', 0)))}")
    print(f"Move-only root organization: {human(int(report.get('organizational_move_bytes', 0)))}")
    if ns.apply:
        print(f"Actually reclaimed: {human(int(report.get('reclaimed_bytes', 0)))}")
        print(f"Deleted {report.get('deleted_count',0)} | failed {report.get('failed_count',0)} | already absent {report.get('absent_count',0)}")
    print(f"Report: {t}")
    print(f"JSON:   {j}")
    return 0 if int(report.get("failed_count", 0)) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
