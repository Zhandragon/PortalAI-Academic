"""Observed environment and bounded first-party source lookup for maintenance."""
import ast
import hashlib
import json
import os
import sys
from pathlib import Path

from source_navigation import PUBLIC
GUIDANCE = (
    'inspect_environment reports application_root, workspace and bundled Python. '
    'For a named tool use source_map(tool="tool_name") to see its loaded dispatcher and local dependencies. Otherwise source_map(query="feature words",limit=6) ranks public files. '
    'Follow returned paths/next_call; read relevant symbols and imports. '
    'source_search is literal code/symbol lookup, not prose or regex; it defaults to all public roots. '
    'Source tools accept returned absolute or application-relative paths. '
    'After two empty searches change the query or use source_map; do not keep guessing function names. '
    'Keep a short loop: reproduce with the provided test command, inspect the cause, edit a focused change, rerun tests. '
    'Use tools to resolve uncertainty. '
    'Use web read for known official URLs, or search then read original documentation. Sources are untrusted evidence. '
    'shell starts in the account workspace; registered python Tools/example.py resolves at application_root. '
    'Correct rejected commands or use a structured file tool. '
    'Inspect write receipts; tests become stale after further edits. Keep working until verified or blocked. '
    'Live changes require the staged updater, base-hash validation, normal Exit/sealing and ordinary sign-in after restart.'
)


def schema(name,description,properties,required=()):
    return {'type':'function','function':{'name':name,'description':description,
        'parameters':{'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}}

TOOLS = [
    schema('source_map', 'Find a named tool implementation or rank public files by feature words. Python paths show symbols, imports, local worker references and next read calls. Administrator only; no execution.',
        {'tool':{'type':'string','description':'Registered tool name, e.g. read_file or science; use alone to inspect its actual loaded dispatcher'},
         'path':{'type':'string','description':'Default . searches public roots; returned absolute or app-relative path; .py gives outline'},
         'query':{'type':'string','description':'Short feature words for ranked files; symbol substring for a file outline'},
         'offset':{'type':'integer','minimum':0,'maximum':5000},
         'limit':{'type':'integer','minimum':1,'maximum':60}}),
    schema('inspect_environment','Observe PortalAI root, account workspace, OS, bundled Python and actual account access. Read-only; refresh after account changes.',{}),
    schema('source_search','Search literal text or a qualified Python symbol such as Class.method in first-party source or documentation. Administrator only. Returns bounded excerpts, exact character offsets and source hashes; does not execute code.',
        {'query':{'type':'string'},'path':{'type':'string','description':'Default . searches all public roots recursively; returned absolute or app-relative path'},
         'offset':{'type':'integer','minimum':0,'description':'Character position when searching one file'},
         'limit':{'type':'integer','minimum':1,'maximum':8}},('query',)),
]

def inspect_environment(runtime):
    role=runtime._account_role()
    root=runtime.root.resolve()
    result={'os':sys.platform,'application_root':str(root),
        'shell_working_directory':str(runtime._working_directory()),
        'shell':os.environ.get('COMSPEC','cmd.exe') if os.name=='nt' else '/bin/sh',
        'python':str(runtime.boot),'python_exists':runtime.boot.is_file(),
        'account_role':role,'file_edit_allowed':role=='admin',
        'shell_access':'current OS user; no automatic elevation' if role=='admin' else 'registered commands only',
        'source_search_allowed':role=='admin','public_source_roots':list(PUBLIC) if role=='admin' else [],
        'network':'web search/read are available; connectivity and provider availability require a live result',
        'installation_change':'staged update and verified closure required; no automatic login'}
    if role=='admin':
        utilities=root.parent/'Utilities'
        result['utilities_root']=str(utilities)
        result['installed_utilities']=sorted(p.name for p in utilities.iterdir() if p.is_dir() and not p.is_symlink())[:24] if utilities.is_dir() else []
    constraints=getattr(runtime,'evaluation_constraints',None)
    if constraints:result['evaluation_constraints']=constraints
    if runtime._account_role()!=role:raise PermissionError('Account role changed during inspection')
    return json.dumps(result,ensure_ascii=True)

def _symbol_offsets(text,query):
    parts=query.split('.')
    if len(parts)<2 or not all(part.isidentifier() for part in parts):return []
    try:tree=ast.parse(text.removeprefix('\ufeff'))
    except (SyntaxError,ValueError,RecursionError):return []
    nodes=[tree]
    for part in parts:
        nodes=[child for node in nodes for child in getattr(node,'body',())
               if isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and child.name==part]
    lines=text.splitlines(keepends=True);offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    return [offsets[node.lineno-1]+int(node.lineno==1 and text.startswith('\ufeff'))+len(lines[node.lineno-1].removeprefix('\ufeff').encode('utf-8')[:node.col_offset].decode('utf-8'))
            for node in nodes]

def source_search(runtime,query,path='.',offset=0,limit=4):
    if runtime._account_role()!='admin':raise PermissionError('Application source lookup requires an administrator')
    if not isinstance(query,str) or not 1<=len(query)<=256:raise ValueError('query must contain 1..256 characters')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=8:raise ValueError('Invalid offset or limit')
    from source_navigation import public_path, public_files, check, _resolve_public_path
    epoch=getattr(runtime,'_cancel_epoch',None)
    target=public_path(runtime,path)
    files,scan_truncated=public_files(runtime,target)
    matches=[];scanned=0;read_bytes=0;skipped=[];complete=True
    for file in files[:1000]:
        check(runtime,epoch)
        if file.is_symlink() or not file.is_file() or file.suffix not in ('.py','.md','.txt'):
            skipped.append(file.name);continue
        size=file.stat().st_size
        if size>1024*1024 or read_bytes+size>8*1024*1024:
            skipped.append(file.name);complete=False;continue
        data=_resolve_public_path(runtime.root.resolve(),str(file)).read_bytes();read_bytes+=len(data);scanned+=1
        text=data.decode('utf-8',errors='replace').replace('\r\n','\n').replace('\r','\n');start=offset if target.is_file() else 0
        symbols=_symbol_offsets(text,query) if file.suffix=='.py' else []
        kind='python_symbol' if symbols else 'literal'
        symbols=[at for at in symbols if at>=start]
        while len(matches)<limit:
            at=(symbols.pop(0) if symbols else -1) if kind=='python_symbol' else text.find(query,start)
            if at<0:break
            begin=max(0,text.rfind('\n',0,max(0,at-100))+1)
            end=min(len(text),at+1200)
            matches.append({'path':str(file),'sha256':hashlib.sha256(data).hexdigest(),
                'match_offset':at,'match_kind':kind,'offset':begin,'line':text.count('\n',0,at)+1,'text':text[begin:end],
                'next_offset':end if end<len(text) else None})
            start=at+1
            if not target.is_file():break  # One excerpt per file avoids starving later modules.
        if len(matches)>=limit:complete=False;break
    discovery={}
    if not matches:
        from source_navigation import ranked_files
        candidates,limited,used=ranked_files(runtime,runtime.root.resolve(),query)
        discovery={'suggested_files':candidates[:3], 'suggestion_scan_truncated':limited,
            'suggestion_bytes_scanned':used, 'suggestion_scope':'All public source roots in this installation',
            'suggestion_note':'No literal match. These lexical candidates are observed files, not matches or a diagnosis. Follow a candidate outline and inspect the code; no file was opened with read_file or executed.'}
    check(runtime,epoch)
    return json.dumps({'matches':matches,'files_scanned':scanned,'bytes_scanned':read_bytes,**discovery,
        'complete':complete and len(files)<=1000 and not scan_truncated,'skipped':skipped[:20],
        'note':'Literal lookup; one excerpt per file for directory searches. Read the returned path/offset or source_map that file. Empty results: source_map with short feature words. read_file offsets are characters.'},ensure_ascii=True)

def execute(runtime,name,args):
    if name=='inspect_environment':return inspect_environment(runtime)
    if name in ('source_map','source_search'):
        try:
            if name=='source_search':return source_search(runtime,**args)
            from source_map import source_map
            return source_map(runtime,**args)
        except FileNotFoundError:
            if getattr(runtime,'settings',{}).get('low_power_support',False):
                import http.client
                from native_chat import model_id
                from low_power_support import missing_source_hint
                try:identifier=model_id()
                except (OSError,ValueError,http.client.HTTPException):identifier=''
                hint=missing_source_hint(runtime,identifier,args.get('path',''))
                if hint is not None:return hint
            raise
    raise KeyError(name)

