"""Static privacy routing review; reads owned source only, never user contents.

This is a candidate catalog, not a proof of confinement. It does not import or
execute scanned modules, inspect third-party runtimes, migrate data or delete it.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import datetime
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from profile_paths import private_path, _contained
SCOPES=('Agent','ControlCenter','Launchers','Scientific','Tools')
EXTRA_SOURCES=('MusicUnderstanding/runtime_driver.py','Voice/Qwen3-TTS/qwen_tts_runner.py')
PRIVATE=('Data','Outputs','User Folder','PortableCache','Cache/MediaWorkers',
         'Cache/MuseTalk','Cache/Web','Cache/MediaEdit','Cache/MAFFT',
         'Cache/ComfyWorkers','Cache/LinuxWorkers','Cache/tmp','Cache/Temp',
         'Cache/Whisper/runtime','SpeechToText/.runtime','MusicUnderstanding/cache/demucs',
         'Generative/ComfyUI_windows_portable/ComfyUI/input',
         'Generative/ComfyUI_windows_portable/ComfyUI/output',
         'Generative/ComfyUI_windows_portable/ComfyUI/temp',
         'Generative/ComfyUI_windows_portable/ComfyUI/user')
ROUTED={'private_path','media_runtime','media_reference','media_output','media_temp',
        'resolve_reference','workspace_root','comfy_directory_args'}
WRITERS={'write_text','write_bytes','mkdir','makedirs','rename','replace','unlink',
         'rmtree','copy','copy2','copyfile','move','atomic_json','_write_json','write_json'}
READERS={'read_text','read_bytes','glob','rglob','iterdir'}


def call_name(node):
    if isinstance(node,ast.Name):return node.id
    if isinstance(node,ast.Attribute):return node.attr
    return ''


def uses_router(node):
    return any(isinstance(child,ast.Call) and call_name(child.func) in ROUTED for child in ast.walk(node))


def literal_path(node):
    if isinstance(node,ast.Constant) and isinstance(node.value,str):
        return node.value.replace('\\','/')
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):
        left=literal_path(node.left);right=literal_path(node.right)
        return '/'.join(x.strip('/') for x in (left,right) if x)
    return ''


def source_review(path,root):
    source=path.read_text(encoding='utf-8-sig')
    tree=ast.parse(source,filename=str(path))
    parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    findings=[];operations=[];seen=set()
    def add(node,kind,detail):
        key=(node.lineno,kind)
        if key in seen:return
        seen.add(key)
        findings.append({'line':node.lineno,'kind':kind,'detail':detail})
    for node in ast.walk(tree):
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):
            if isinstance(parents.get(node),ast.BinOp):continue
            value=literal_path(node)
            if not uses_router(node) and any(value==p or value.startswith(p+'/') for p in PRIVATE):
                add(node,'unrouted-private-literal',value)
            elif not uses_router(node) and value.startswith('Agent/.runtime'):
                add(node,'shared-runtime-review',value)
        if not isinstance(node,ast.Call):continue
        name=call_name(node.func)
        if name in WRITERS|READERS|{'open','connect'}:
            mode='read' if name in READERS else 'write-or-mutation' if name in WRITERS else 'inspect-call-mode'
            if name=='open':
                modes=[arg.value for arg in node.args[1:] if isinstance(arg,ast.Constant) and isinstance(arg.value,str)]
                modes += [kw.value.value for kw in node.keywords if kw.arg=='mode' and isinstance(kw.value,ast.Constant)]
                mode='write-or-mutation' if any(any(c in str(value) for c in 'wax+') for value in modes) else 'read-or-dynamic-mode'
            operations.append({'line':node.lineno,'operation':name,'mode':mode,'router_in_expression':uses_router(node)})
        if name in {'TemporaryDirectory','mkdtemp','mkstemp','NamedTemporaryFile'} and not any(kw.arg=='dir' for kw in node.keywords):
            add(node,'ambient-temp-review','Temporary file uses process temp environment; verify portable per-profile env before this call')
        if name=='Path' and node.args and not uses_router(parents.get(node,node)):
            expr=ast.unparse(node.args[0])
            if re.search(r'\b(output|output_dir|input_path|reference_audio|video|audio|mask)\b',expr):
                add(node,'explicit-media-reference-review',expr[:200])
    return {'path':path.relative_to(root).as_posix(),'findings':findings,'io_operations':operations}


def audit(root=ROOT):
    root=Path(root).resolve();files=[];errors=[]
    for folder in SCOPES:
        for path in sorted((root/folder).rglob('*.py')):
            rel=path.relative_to(root)
            if any(p in {'__pycache__','LegacyDiagnosis','Archive','.venv','venv','.runtime','Data','Private','Cache','Outputs'} for p in rel.parts):continue
            if path==Path(__file__).resolve():continue
            if path.stat().st_size>2*1024**2:
                errors.append({'path':rel.as_posix(),'error':'source larger than 2MiB; not scanned'});continue
            try:files.append(source_review(path,root))
            except (OSError,UnicodeError,SyntaxError) as exc:
                errors.append({'path':rel.as_posix(),'error':type(exc).__name__})
    for relative in EXTRA_SOURCES:
        path=root/relative
        if not path.is_file():continue
        try:files.append(source_review(path,root))
        except (OSError,UnicodeError,SyntaxError) as exc:
            errors.append({'path':relative,'error':type(exc).__name__})
    counts=Counter(row['kind'] for file in files for row in file['findings'])
    return {'scope':'Static first-party source only; review candidates, not a security proof',
            'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scanned_files':len(files),'finding_counts':dict(counts),
            'io_operation_count':sum(len(file['io_operations']) for file in files),
            'limitations':['No private files, archived contents, third-party runtime trees or secrets inspected.',
                          'Dynamic/aliased paths and upstream side effects need manual or synthetic integration tests.',
                          'Tools includes maintenance/install/test code; a match does not establish an active leak.',
                          'Shared runtime state may be intentional ownership metadata; never move it blindly.'],
            'files':files,'errors':errors}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--stdout',action='store_true',help='Print the source review without saving a report')
    args=parser.parse_args(argv)
    if args.stdout and args.output:
        parser.error('--stdout and --output cannot be combined')
    path=None
    if not args.stdout:
        base=private_path(ROOT,'Data/Maintenance')
        path=args.output.absolute() if args.output else base/('profile-routing-audit-'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
        if path.parent!=base:
            parser.error('Report must stay in the authenticated profile Data/Maintenance folder')
        _contained(ROOT,path)
    report=audit()
    if path is None:
        print(json.dumps(report,indent=2))
        return 1 if report['errors'] else 0
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as handle:
        json.dump(report,handle,indent=2)
    print(json.dumps({'report':str(path),'scanned_files':report['scanned_files'],
                      'finding_counts':report['finding_counts'],'errors':len(report['errors'])}))
    return 1 if report['errors'] else 0


if __name__=='__main__':raise SystemExit(main())
