from __future__ import annotations
import argparse, json, shutil
from pathlib import Path

VERSION = "15.125"

def resolve_root(value: str | None) -> Path:
    return (Path(value).expanduser().resolve() if value else Path(__file__).resolve().parents[1])

def ensure_inside(root: Path, path: Path) -> Path:
    root=root.resolve(); path=path.resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise RuntimeError(f"Refusing path outside PortableAI root: {path}") from exc
    return path

def size_bytes(path: Path) -> int:
    try:
        if path.is_file() or path.is_symlink(): return path.stat().st_size
        return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
    except Exception: return 0

def empty_dir(root: Path, directory: Path, apply: bool) -> dict:
    directory=ensure_inside(root,directory)
    before=size_bytes(directory) if directory.exists() else 0
    entries=list(directory.iterdir()) if directory.exists() else []
    errors=[]; removed=0
    if apply:
        directory.mkdir(parents=True,exist_ok=True)
        for p in entries:
            try:
                if p.is_dir() and not p.is_symlink(): shutil.rmtree(p)
                else: p.unlink(missing_ok=True)
                removed += 1
            except Exception as exc: errors.append(f"{p}: {type(exc).__name__}: {exc}")
        directory.mkdir(parents=True,exist_ok=True)
    return {"path":str(directory),"bytes_before":before,"entries":len(entries),"removed_entries":removed,"errors":errors}

def remove_file(root: Path, path: Path, apply: bool) -> dict:
    path=ensure_inside(root,path); before=size_bytes(path) if path.exists() else 0; existed=path.exists(); error=None
    if apply and existed:
        try: path.unlink(missing_ok=True)
        except Exception as exc: error=f"{type(exc).__name__}: {exc}"
    return {"path":str(path),"bytes_before":before,"existed":existed,"removed":bool(apply and existed and not path.exists()),"error":error}

def run(root: Path, kind: str, apply: bool=False) -> dict:
    root=root.resolve()
    # Legacy compatibility only. Account-aware cleanup lives in the guarded GUI
    # and understands deferred private files; this script must not scan/delete
    # obsolete shared paths when the bundle has local accounts.
    import sys
    agent=str(Path(__file__).resolve().parents[1]/'Agent')
    if agent not in sys.path:sys.path.insert(0,agent)
    from profile_paths import enabled
    if enabled(root):
        raise PermissionError('Account-enabled cleanup must use the signed-in Control Center')
    if not (root/'ControlCenter'/'native_chat.py').exists(): raise RuntimeError(f"Not a PortableAI root: {root}")
    results=[]; preserved=[]
    if kind=='webcache':
        results=[empty_dir(root,root/'Outputs'/'WebImages',apply)]
        scope='Downloaded web images only'
    elif kind=='outputs':
        results=[empty_dir(root,root/'Outputs',apply)]
        scope='All PortableAI output artifacts'
    elif kind=='conversations':
        chat=root/'Data'/'Chat'
        for name in ('Sessions','Attachments','Recordings','Thumbnails','MediaCache'):
            results.append(empty_dir(root,chat/name,apply))
        results.append(remove_file(root,root/'Data'/'Memory'/'memory_index.json',apply))
        results.append(remove_file(root,root/'Data'/'Memory'/'memory_index.json.tmp',apply))
        preserved=[str(chat/'settings.json'),str(chat/'custom_instructions.txt')]
        scope='Saved conversations, chat-owned media, and distilled cross-chat memory'
    else: raise ValueError(kind)
    errors=[]; total=0
    for r in results:
        total += int(r.get('bytes_before') or 0)
        errors.extend(r.get('errors') or [])
        if r.get('error'): errors.append(f"{r['path']}: {r['error']}")
    return {"success":not errors,"version":VERSION,"kind":kind,"applied":apply,"scope":scope,"bytes_before":total,"results":results,"preserved":preserved,"errors":errors}

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('kind',choices=('webcache','outputs','conversations')); ap.add_argument('--root'); ap.add_argument('--apply',action='store_true'); ns=ap.parse_args()
    payload=run(resolve_root(ns.root),ns.kind,ns.apply); print(json.dumps(payload,ensure_ascii=False,indent=2)); return 0 if payload['success'] else 1

if __name__=='__main__': raise SystemExit(main())
