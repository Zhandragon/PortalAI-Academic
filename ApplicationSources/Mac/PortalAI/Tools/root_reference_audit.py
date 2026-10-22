# PORTABLEAI_DOCUMENTATION_PROTECTION_v15_127B
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

VERSION = "15.106"

# These are the top-level directories that are structurally part of the current
# Native Chat / media stack. They may still contain internal caches, but the
# directories themselves are not cleanup candidates.
PROTECTED_TOP = {
    "Data", "Outputs", "LLM", "Generative", "Voice", "Video", "Music",
    "SpeechToText", "Runtime", "Runtimes", "Models", "Agent", "ControlCenter",
    "Tools", "Launchers", "Workflows", "Services", "Sandbox", "SandboxClient",
    "MusicUnderstanding",
    "Documentation",
}

# Known historical/build trees that are worth reviewing even when not enormous.
KNOWN_REVIEW = {
    "OpenGUI": ("legacy-frontend", "Legacy OpenGUI runtime; Native Chat is the primary frontend."),
    "OpenWebUI": ("legacy-frontend", "Legacy OpenWebUI runtime; Native Chat is the primary frontend."),
    "OpenGUI-Source": ("legacy-source", "Source tree for the retired OpenGUI frontend; not required by Native Chat runtime."),
    "Installer": ("build-artifact", "Historical installer/build staging tree. Keep only if current launch/install code references it."),
    "Raw Files": ("build-artifact", "Historical raw/build staging tree. Review references before deleting."),
    "Patch": ("build-artifact", "Historical patch staging tree. Review references before deleting."),
    "PatchPayload": ("build-artifact", "Historical patch payload staging tree; installed payloads should live in canonical component paths."),
    "Payload": ("build-artifact", "Historical installer/update payload staging tree; not part of normal Native Chat runtime."),
    "_UpdatePayload": ("build-artifact", "Historical update staging tree. Installed payloads should normally be copied into live locations."),
    "UpdatePayload": ("build-artifact", "Historical update staging tree. Installed payloads should normally be copied into live locations."),
    "PortableCache": ("cache-review", "Large PortableAI cache tree; inspect active references before deleting."),
    "Cache": ("cache-review", "Large cache tree; inspect active references before deleting."),
    "Backups": ("rollback-history", "Rollback history. Keep the newest few backups; older entries can be pruned explicitly."),
}

TEXT_EXTS = {
    ".py", ".pyw", ".bat", ".cmd", ".ps1", ".vbs", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".txt", ".md", ".xml", ".js", ".ts", ".html", ".css",
}
MAX_TEXT_FILE = 4 * 1024 * 1024

# Maintenance/UI code necessarily names cleanup candidates while describing or
# deleting them. Those bookkeeping references are not runtime dependencies and
# must not block cleanup.
REFERENCE_AUDIT_SELF_FILES = {
    "Tools/storage_audit.py",
    "Tools/root_reference_audit.py",
    "Tools/general_cleanup.py",
    "Tools/dependency_probe.py",
    "ControlCenter/PortableAI_GUI.py",
}


def human(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(max(0, n))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.1f} {u}" if u != "B" else f"{int(x)} B"
        x /= 1024.0
    return f"{n} B"


def dir_size(path: Path) -> int:
    total = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def runtime_lock_paths(root: Path) -> set[Path]:
    out: set[Path] = set()
    for lock in (root / "Agent" / ".runtime" / "component_runtime_locks.json", root / "component_runtime_locks.json"):
        if not lock.exists():
            continue
        try:
            data = json.loads(lock.read_text(encoding="utf-8", errors="replace"))
            for item in (data.get("components") or {}).values():
                raw = item.get("path")
                if raw:
                    p = Path(raw)
                    if not p.is_absolute():
                        p = root / p
                    out.add(p.resolve())
        except Exception:
            pass
        break
    return out


def parse_venv_homes(root: Path) -> set[Path]:
    homes: set[Path] = set()
    for base_name in ("Voice", "Video", "Music", "Runtime", "Generative", "Runtimes"):
        base = root / base_name
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base):
            cur = Path(current)
            try:
                rel = cur.relative_to(root)
            except Exception:
                rel = Path()
            if len(rel.parts) > 7:
                dirs[:] = []
                continue
            lower = {x.lower() for x in rel.parts}
            if lower & {"models", "checkpoints", "uv-cache", "cache", "outputs", "output"}:
                dirs[:] = []
                continue
            if "pyvenv.cfg" in files:
                cfg = cur / "pyvenv.cfg"
                try:
                    for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.lower().startswith("home") and "=" in line:
                            raw = line.split("=", 1)[1].strip().strip('"')
                            if raw:
                                p = Path(raw)
                                if not p.is_absolute():
                                    p = cfg.parent / p
                                homes.add(p.resolve())
                except Exception:
                    pass
    return homes


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def candidate_dirs(root: Path) -> list[Path]:
    out = []
    try:
        items = list(root.iterdir())
    except OSError:
        return out
    for p in items:
        if not p.is_dir():
            continue
        if p.name in KNOWN_REVIEW:
            out.append(p)
            continue
        if p.name in PROTECTED_TOP:
            continue
        # Unknown large top-level trees are worth identifying even if they are
        # not on the historical-name allowlist.
        size = dir_size(p)
        if size >= 64 * 1024 * 1024:
            out.append(p)
    return out


def iter_reference_files(root: Path, candidates: list[Path]):
    candidate_roots = {os.path.normcase(str(p.resolve())) for p in candidates}
    skip_top = {"Backups", "Data", "Outputs"}
    for current, dirs, files in os.walk(root):
        cur = Path(current)
        try:
            rel = cur.relative_to(root)
        except Exception:
            rel = Path()
        if rel.parts and rel.parts[0] in skip_top:
            dirs[:] = []
            continue
        if rel.parts and rel.parts[0].startswith(("PortableAI_v15_", "PortableAI_ControlCenter_", "PortableAI_PortabilityFoundation_")):
            # Extracted update bundles are themselves cleanup candidates and must
            # not create false "active reference" hits for historical staging trees.
            dirs[:] = []
            continue
        try:
            cur_res = os.path.normcase(str(cur.resolve()))
        except Exception:
            cur_res = os.path.normcase(str(cur))
        # Never scan inside the candidate itself when deciding whether the rest
        # of PortableAI references it.
        if any(cur_res == c or cur_res.startswith(c + os.sep) for c in candidate_roots):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in {"__pycache__", "uv-cache", ".git", "node_modules"}]
        for fn in files:
            p = cur / fn
            try:
                rel_file = str(p.relative_to(root)).replace("\\", "/")
            except Exception:
                rel_file = ""
            if rel_file in REFERENCE_AUDIT_SELF_FILES:
                continue
            if p.suffix.lower() not in TEXT_EXTS:
                continue
            try:
                if p.stat().st_size > MAX_TEXT_FILE:
                    continue
            except OSError:
                continue
            yield p


def reference_patterns(name: str) -> list[re.Pattern]:
    esc = re.escape(name)
    # Use quoted-name and path-segment forms to avoid treating generic words
    # such as "Cache" as references merely because they appear in prose.
    return [
        re.compile(rf"[\\/]\s*{esc}(?:[\\/]|['\"])", re.I),
        re.compile(rf"['\"]{esc}['\"]", re.I),
        re.compile(rf"root\s*/\s*['\"]{esc}['\"]", re.I),
        re.compile(rf"root\s*\\\s*['\"]{esc}['\"]", re.I),
    ]


def scan_references(root: Path, candidates: list[Path]) -> dict[str, list[dict]]:
    names = {p.name: reference_patterns(p.name) for p in candidates}
    hits: dict[str, list[dict]] = {p.name: [] for p in candidates}
    for p in iter_reference_files(root, candidates):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pats in names.items():
            if len(hits[name]) >= 20:
                continue
            match = None
            for pat in pats:
                match = pat.search(text)
                if match:
                    break
            if not match:
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            line = text.splitlines()[line_no - 1].strip() if text.splitlines() else ""
            try:
                rel = str(p.relative_to(root))
            except Exception:
                rel = str(p)
            hits[name].append({"file": rel, "line": line_no, "text": line[:500]})
    return hits


def classify(root: Path, candidate: Path, protected_paths: set[Path], refs: list[dict]) -> dict:
    size = dir_size(candidate)
    protected_inside = []
    for q in protected_paths:
        if is_relative_to(q, candidate) or is_relative_to(candidate, q):
            protected_inside.append(str(q))
    category, base_reason = KNOWN_REVIEW.get(candidate.name, ("unclassified-root", "Large unclassified top-level directory."))
    if protected_inside:
        action = "KEEP"
        confidence = "high"
        reason = "Contains or overlaps an active runtime/base path. Do not delete the directory as a whole."
    elif refs:
        action = "INSPECT"
        confidence = "medium"
        reason = f"Referenced by {len(refs)} active script/config file(s); inspect the references before deleting."
    elif candidate.name == "Backups":
        action = "PRUNE-OLD"
        confidence = "high"
        reason = "Keep the newest rollback backups; older entries can be pruned explicitly."
    elif candidate.name in {"OpenGUI", "OpenWebUI", "OpenGUI-Source"}:
        action = "REVIEW-DELETE"
        confidence = "medium-high"
        reason = base_reason + " No active external references were found by this scan."
    elif candidate.name in {"Installer", "Raw Files", "Patch", "PatchPayload", "Payload", "_UpdatePayload", "UpdatePayload"}:
        action = "REVIEW-DELETE"
        confidence = "medium"
        reason = base_reason + " No active external references were found by this scan."
    elif candidate.name in {"PortableCache", "Cache"}:
        action = "INSPECT"
        confidence = "low"
        reason = base_reason + " No direct script/config reference was found, but cache consumers may resolve these paths dynamically."
    else:
        action = "INSPECT"
        confidence = "low"
        reason = base_reason + " No direct references were found; absence of a textual reference is not sufficient for automatic deletion."
    return {
        "name": candidate.name,
        "path": str(candidate),
        "bytes": size,
        "category": category,
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "protected_paths": protected_inside,
        "reference_count": len(refs),
        "references": refs,
    }


def _rotate(latest: Path, previous: Path) -> None:
    try:
        if previous.exists():
            previous.unlink()
        if latest.exists():
            latest.replace(previous)
    except OSError:
        pass


def write_report(root: Path, report: dict) -> tuple[Path, Path]:
    out = root / "Data" / "Maintenance"
    out.mkdir(parents=True, exist_ok=True)
    j = out / "root_reference_audit_latest.json"
    t = out / "root_reference_audit_latest.txt"
    pj = out / "root_reference_audit_previous.json"
    pt = out / "root_reference_audit_previous.txt"
    _rotate(j, pj); _rotate(t, pt)
    j.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"PortableAI root reference audit v{VERSION}",
        "=" * 78,
        f"Root: {report['root']}",
        f"Elapsed: {report['elapsed_seconds']} s",
        f"Candidates: {len(report['candidates'])}",
        "",
        "This is a reference/planning report, not an automatic deletion list.",
        "Runtime locks and pyvenv base paths always override a no-reference result.",
        "",
    ]
    for row in report["candidates"]:
        lines.append(f"{row['action']:<13} {human(int(row['bytes'])):>10}  {row['path']}")
        lines.append(f"    {row['category']} | confidence {row['confidence']} | refs {row['reference_count']}")
        lines.append(f"    {row['reason']}")
        for r in row.get("protected_paths", [])[:8]:
            lines.append(f"    PROTECTED: {r}")
        for r in row.get("references", [])[:8]:
            lines.append(f"    REF: {r['file']}:{r['line']}  {r['text']}")
        lines.append("")
    t.write_text("\n".join(lines), encoding="utf-8")
    return j, t


def main() -> int:
    ap = argparse.ArgumentParser(description="PortableAI reference-aware top-level bloat audit")
    ap.add_argument("--root", required=True)
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    if not root.exists():
        print(f"ERROR: root not found: {root}")
        return 2
    t0 = time.time()
    candidates = candidate_dirs(root)
    refs = scan_references(root, candidates)
    protected = runtime_lock_paths(root) | parse_venv_homes(root)
    rows = [classify(root, p, protected, refs.get(p.name, [])) for p in candidates]
    rows.sort(key=lambda x: int(x["bytes"]), reverse=True)
    report = {
        "version": VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.time() - t0, 2),
        "protected_runtime_paths": [str(x) for x in sorted(protected, key=lambda x: str(x).lower())],
        "candidates": rows,
    }
    j, t = write_report(root, report)
    print(f"PortableAI root reference audit v{VERSION}")
    print(f"Candidates: {len(rows)}")
    for row in rows:
        print(f"{row['action']:<13} {human(int(row['bytes'])):>10}  {row['name']}  refs={row['reference_count']}")
    print(f"Report: {t}")
    print(f"JSON:   {j}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
