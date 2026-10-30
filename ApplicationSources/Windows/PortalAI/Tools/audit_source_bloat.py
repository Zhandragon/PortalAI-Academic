"""Read-only first-party source audit; never scans accounts or deletes assets."""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path

AREAS=('Agent','ControlCenter','Scientific','Tools','Maintenance/Tests')
EXCLUDE={'vendor','__pycache__','packages','.git','node_modules','site-packages',
         'kicad','portablegit','lib','lib64','python','python_embeded','.venv',
         'runtime','cache','backups'}


def source_files(root):
    for area in AREAS:
        base=root/area
        if base.is_symlink() or base.is_junction():continue
        for current,dirs,names in os.walk(base,followlinks=False):
            folder=Path(current)
            dirs[:]=sorted(d for d in dirs if d.casefold() not in EXCLUDE
                          and not (folder/d).is_symlink() and not (folder/d).is_junction())
            for name in sorted(names):
                file=folder/name
                if file.suffix=='.py' and not file.is_symlink():yield file


def audit(root):
    root=Path(root).resolve();rows=[];hashes=defaultdict(list);definitions=[];imports=[];errors=[]
    for file in source_files(root):
        rel=file.relative_to(root)
        data=file.read_bytes();name=rel.as_posix();rows.append({'path':name,'bytes':len(data),'lines':len(data.splitlines())})
        hashes[hashlib.sha256(data).hexdigest()].append(name)
        try:tree=ast.parse(data,filename=name)
        except (SyntaxError,ValueError) as exc:errors.append({'path':name,'error':str(exc)});continue
        top=defaultdict(list)
        for node in tree.body:
            if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):top[node.name].append(node.lineno)
        for symbol,lines in top.items():
            if len(lines)>1:definitions.append({'path':name,'symbol':symbol,'lines':lines,'review':'May be intentional layered GUI patching; find callers before consolidation.'})
        used={node.id for node in ast.walk(tree) if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load)}
        for node in tree.body:
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                if isinstance(node,ast.ImportFrom) and node.module=='__future__':continue
                for alias in node.names:
                    local=alias.asname or (alias.name.split('.')[0] if isinstance(node,ast.Import) else alias.name)
                    if local!='*' and local not in used:imports.append({'path':name,'line':node.lineno,'name':local,'review':'Candidate only: imports may be reexports or have initialization effects.'})
    sizes={row['path']:row['bytes'] for row in rows}
    duplicates=[{'paths':paths,'bytes_each':sizes[paths[0]],'potential_bytes':sizes[paths[0]]*(len(paths)-1)} for paths in hashes.values() if len(paths)>1 and sizes[paths[0]]>0]
    return {'scope':'First-party Python in one platform tree; no profiles, models, archives or vendor code inspected. Read-only; no deletion authorized by this report.',
            'files':len(rows),'bytes':sum(r['bytes'] for r in rows),'lines':sum(r['lines'] for r in rows),
            'largest':sorted(rows,key=lambda x:x['bytes'],reverse=True)[:20],
            'identical_files':sorted(duplicates,key=lambda x:x['potential_bytes'],reverse=True),
            'redefined_top_level_symbols':definitions,'possibly_unused_imports':imports,'parse_errors':errors,
            'limitations':'Static evidence does not establish safe removal. Platform copies, recovery archives and layered overrides are not inherently unused.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    print(json.dumps(audit(args.root),indent=2))
