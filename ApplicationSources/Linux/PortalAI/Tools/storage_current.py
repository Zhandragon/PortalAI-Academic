"""Read-only storage/duplicate audits and narrowly allowlisted cache cleanup."""
import argparse
from collections import defaultdict
import hashlib
import os
from pathlib import Path
import shutil
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'Agent')]
from maintenance_reports import save
from runtime_policy import storage_budget
from root_archive import archive

FIRST_PARTY={'Agent','ControlCenter','Scientific','Tools','Launchers'}
CACHES={'__pycache__','.pytest_cache','.mypy_cache','.ruff_cache'}
SKIP={'.git','node_modules','site-packages','.venv','venv','packages','vendor','thirdparty','third_party','external'}


def linked(p):
    try:return p.is_symlink() or bool(p.lstat().st_file_attributes & 0x400) if os.name=='nt' else p.is_symlink()
    except OSError:return True


def files(root, errors):
    for base,dirs,names in os.walk(root,followlinks=False,onerror=lambda e:errors.append(str(e))):
        dirs[:]=[n for n in dirs if not linked(Path(base)/n)]
        for name in names:
            p=Path(base)/name
            if linked(p):continue
            try:
                st=p.stat()
                yield p,st
            except OSError as exc:errors.append(str(exc))


def fingerprint(st):return (st.st_size,st.st_mtime_ns,st.st_dev,st.st_ino)


def safe_candidates(root):
    root=Path(root).resolve();out=[]
    for name in sorted(FIRST_PARTY):
        base=root/name
        if not base.is_dir() or linked(base):continue
        for folder,dirs,names in os.walk(base,followlinks=False):
            dirs[:]=[n for n in dirs if n.lower() not in SKIP and not linked(Path(folder)/n)]
            if Path(folder) == root/'Tools':
                dirs[:] = [n for n in dirs if n.lower() != 'kicad' and not n.lower().startswith('kicad.staging-')]
            p=Path(folder)
            if not any(x in CACHES for x in p.relative_to(base).parts):continue
            for name in names:
                q=p/name
                # Keep user/config files, even if somebody placed them in a cache.
                if q.suffix not in ('.pyc','.pyo') or linked(q):continue
                st=q.stat();out.append({'path':q.relative_to(root).as_posix(),'bytes':st.st_size,
                                      'fingerprint':list(fingerprint(st)),'reason':'First-party compiled Python cache'})
    return out


def apply_safe(root,candidates):
    root=Path(root).resolve();current={x['path']:x for x in safe_candidates(root)};results=[];freed=0
    for x in candidates:
        try:
            if x!=current.get(x['path']):raise ValueError('Candidate changed or is not allowlisted')
            p=root/x['path']
            if not p.resolve().is_relative_to(root) or linked(p):raise ValueError('Linked/escaping path')
            if list(fingerprint(p.stat()))!=x['fingerprint']:raise ValueError('File changed since plan')
            p.unlink();freed+=x['bytes'];results.append({**x,'ok':True})
        except Exception as exc:results.append({**x,'ok':False,'error':str(exc)})
    return results,freed


def hash_file(p, sample=False):
    h=hashlib.sha256()
    with p.open('rb') as f:
        if sample:
            size=p.stat().st_size
            for off in (0,max(0,size//2-32768),max(0,size-65536)):
                f.seek(off);h.update(f.read(65536))
        else:
            for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def duplicate_groups(entries, errors):
    sizes=defaultdict(list)
    verified_hashes={}
    for p,st in entries:
        if st.st_size>=1024**2:sizes[st.st_size].append((p,st))
    groups=[]
    for size,items in sizes.items():
        if len(items)<2:continue
        samples=defaultdict(list)
        for p,st in items:
            try:samples[hash_file(p,True)].append((p,st))
            except OSError as exc:errors.append(str(exc))
        for candidates in samples.values():
            if len(candidates)<2:continue
            hashes=defaultdict(list)
            for p,st in candidates:
                try:
                    identity=(*fingerprint(st),str(p) if not st.st_ino else '')
                    digest=verified_hashes.get(identity)
                    if digest is None:digest=hash_file(p)
                    if fingerprint(p.stat())!=fingerprint(st):raise OSError(f'Changed during scan: {p}')
                    verified_hashes[identity]=digest
                    hashes[digest].append((p,st))
                except OSError as exc:errors.append(str(exc))
            for digest,matching in hashes.items():
                if len(matching)<2:continue
                identities={(st.st_dev,st.st_ino) if st.st_ino else str(p) for p,st in matching}
                groups.append({'sha256':digest,'bytes_each':size,'count':len(matching),
                               'distinct_file_identities':len(identities),'logical_duplicate_bytes':size*(len(matching)-1),
                               'separate_file_duplicate_bytes':size*(len(identities)-1),
                               'policy':'REVIEW ONLY. Hard links already share storage; duplicate content is not deletion permission.',
                               'paths':[str(p) for p,st in matching]})
    return sorted(groups,key=lambda g:g['separate_file_duplicate_bytes'],reverse=True)


def audit(root,deep=False):
    root=Path(root).resolve();errors=[];entries=list(files(root,errors));tops=defaultdict(int)
    for p,st in entries:tops[p.relative_to(root).parts[0]]+=st.st_size
    safe=safe_candidates(root);dups=duplicate_groups(entries,errors) if deep else []
    return {'root':str(root),'policy':'Models, runtimes, outputs, missions, user files and recovery archives are protected. No automatic dependency deletion.',
            'storage':storage_budget(root),'top_level':[{'name':k,'bytes':v} for k,v in sorted(tops.items(),key=lambda x:x[1],reverse=True)],
            'file_count':len(entries),'safe_candidates':safe,'safe_bytes':sum(x['bytes'] for x in safe),'duplicates':dups,
            'scan_errors':errors,'coverage':'Regular files only; junctions/symlinks skipped. Deep scan: >=1 MiB, sample filter followed by full SHA-256. Logical sizes, not physical allocation.'}


def render(data,title):
    budget=data['storage'];gib=lambda n:f'{n/1024**3:.2f} GiB'
    lines=[title,data['policy'],data['coverage'],f"Free: {gib(budget['free_bytes'])}; output reserve: {gib(budget['output_reserve_bytes'])}; floor: {gib(budget['minimum_free_bytes'])}; asset budget: {gib(budget['download_budget_bytes'])}",
           'Storage reserve policy: '+('PASS' if budget['allowed'] else 'FAIL; preserve the output reserve and free-space floor.'),
           f"Allowlisted bytecode: {data['safe_bytes']} bytes. Scan errors: {len(data['scan_errors'])}",'','Top-level logical sizes:']
    lines += [f"{gib(x['bytes']):>14}  {x['name']}" for x in data['top_level']]
    lines += ['','Allowlisted bytecode candidates:']
    lines += [f"{x['bytes']:>10} bytes  {x['path']}" for x in data['safe_candidates']]
    lines += ['','Exact duplicate groups (review only):']
    for g in data['duplicates']:
        lines.append(f"{g['count']} paths / {g['distinct_file_identities']} file identities × {gib(g['bytes_each'])}; SHA-256 {g['sha256']}")
        lines.extend('  '+p for p in g['paths'])
    lines.extend(data['scan_errors'])
    if 'cleanup_results' in data:lines.append(f"Deleted bytecode: {data['cleanup_reclaimed_bytes']} bytes; failures: {sum(not x['ok'] for x in data['cleanup_results'])}")
    return '\n'.join(lines)+'\n'


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',required=True)
    for name in ('deep','cleanup-safe','plan-safe','root-tidy','apply'):ap.add_argument('--'+name,action='store_true')
    ns=ap.parse_args();root=Path(ns.root).resolve()
    if ns.root_tidy:
        data=archive(root,ns.apply);text=__import__('json').dumps(data,indent=2)
        save(root,'root_hygiene_apply' if ns.apply else 'root_hygiene_plan',text,data,0);print(text);return 0
    data=audit(root,ns.deep)
    key='deep_duplicate_scan' if ns.deep else 'general_cleanup_plan' if ns.plan_safe else 'storage_cleanup' if ns.cleanup_safe else 'storage_audit'
    if ns.cleanup_safe:data['cleanup_results'],data['cleanup_reclaimed_bytes']=apply_safe(root,data['safe_candidates'])
    failures=len(data['scan_errors'])+sum(not x['ok'] for x in data.get('cleanup_results',[]))+int(not data['storage']['allowed'])
    data['counts']={'PASS':int(data['storage']['allowed']),'WARN':0,'FAIL':failures}
    code=1 if failures else 0
    text=render(data,key.replace('_',' ').title());save(root,key,text,data,code);print(text);return code


if __name__=='__main__':raise SystemExit(main())
