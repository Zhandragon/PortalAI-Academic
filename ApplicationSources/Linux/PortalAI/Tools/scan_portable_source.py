"""Non-executing syntax/config scan of PortalAI-owned code and shallow wrappers.

Excludes third-party runtimes, packages, models, caches and historical payload
copies. This is a static check, not proof that all runtime paths work.
"""
import argparse
import ast
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tokenize
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"Agent"), str(ROOT/"Tools")]
from runtime_policy import atomic_json
from portability_audit import collect_candidates, SKIP_ANYWHERE
from profile_paths import private_path


def scan(root=ROOT):
    root = Path(root).resolve()
    paths, incomplete, _ = collect_candidates(root, 30)
    selected = {p for p in paths if p.suffix.lower() in {".py", ".ps1", ".json"}}
    # Owned entry points inside otherwise third-party component trees.
    for relative in ('MusicUnderstanding/runtime_driver.py', 'Voice/Qwen3-TTS/qwen_tts_runner.py'):
        path = root/relative
        if path.is_file(): selected.add(path)
    for dirname in ("Scientific", "Setup", "Workflows", "Maintenance/Tests", "Installer", "SandboxClient", "SecureAgent/Updater"):
        for cur, dirs, files in os.walk(root/dirname):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_ANYWHERE]
            selected.update(Path(cur)/n for n in files if Path(n).suffix.lower() in {".py", ".ps1", ".json"})
    errors, notes, duplicates, checked = [], [], [], []
    ps_files = []
    for path in sorted(selected):
        rel = path.relative_to(root).as_posix()
        try:
            if path.suffix.lower() == ".ps1":
                ps_files.append(str(path)); continue
            if path.suffix.lower() == ".py":
                with tokenize.open(path) as f: source = f.read()
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    compile(source, rel, "exec")
                    tree = ast.parse(source, filename=rel)
                for w in caught:
                    row = {"file": rel, "line": w.lineno, "message": str(w.message)}
                    if row not in notes: notes.append(row)
                definitions = Counter(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
                duplicates.extend({"file": rel, "name": name, "count": count} for name, count in definitions.items() if count > 1)
            else:
                json.loads(path.read_text(encoding="utf-8-sig"))
            checked.append(rel)
        except Exception as exc:
            errors.append({"file": rel, "error": str(exc)})
    if ps_files:
        if os.name != "nt":
            notes.append({"message": "PowerShell parse skipped on this host"})
        else:
            command = r'''$ErrorActionPreference = 'Stop'
$paths = [Console]::In.ReadToEnd() | ConvertFrom-Json
$rows = @(foreach ($path in $paths) {
  $tokens = $null; $parseErrors = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
  foreach ($err in $parseErrors) { @{ file = $path; line = $err.Extent.StartLineNumber; error = $err.Message } }
})
ConvertTo-Json -InputObject $rows -Compress
'''
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                    input=json.dumps(ps_files), text=True, capture_output=True, timeout=60,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode: raise RuntimeError("PowerShell parser failed: " + result.stderr)
            ps_errors = json.loads(result.stdout)
            for row in ps_errors: row["file"] = Path(row["file"]).relative_to(root).as_posix()
            errors.extend(ps_errors)
            bad = {r["file"] for r in ps_errors}
            checked.extend(Path(p).relative_to(root).as_posix() for p in ps_files if Path(p).relative_to(root).as_posix() not in bad)
    report = {"passed": not errors and not incomplete, "scope": __doc__, "files_selected": len(selected),
              "checked": checked, "counts": dict(Counter(Path(p).suffix.lower() for p in checked)),
              "incomplete": incomplete, "errors": errors, "warnings": notes, "duplicate_top_level_definitions": duplicates}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--stdout', action='store_true', help='Print a read-only result without saving a report')
    args = parser.parse_args(argv)
    # Resolve the authenticated destination before scanning; locked/stale sessions
    # may inspect public source with --stdout but must not create shared reports.
    destination = None if args.stdout else private_path(args.root, 'Data/Maintenance/source-scan.json')
    report = scan(args.root)
    if destination is not None:
        atomic_json(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"checked", "scope"}}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
