"""Static locations behind an already loaded runtime's named tool dispatch.

This reads public source but never imports or executes inspected modules.
Observed imports/references are navigation evidence, not a claim of execution.
"""
import ast
import hashlib
import inspect
import re
from pathlib import Path
from source_navigation import PUBLIC, check, check_cancel, public_path, outline


def _read(runtime, path):
    path=public_path(runtime,str(path))
    if not path.is_file() or path.suffix!='.py' or path.stat().st_size>1024*1024:
        raise ValueError('Source route requires a public Python file no larger than 1 MiB')
    raw=path.read_bytes()
    text=raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
    return path,text,ast.parse(text.removeprefix('\ufeff')),hashlib.sha256(raw).hexdigest()


def _modules(runtime, module):
    if len(module)>200 or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',module):return []
    result=[]
    for folder in PUBLIC:
        for suffix in (module.replace('.','/')+'.py',module.replace('.','/')+'/__init__.py'):
            path=runtime.root.resolve()/folder/suffix
            try:path=public_path(runtime,str(path))
            except PermissionError:continue
            if path.is_file():result.append(path)
    return result


def references(runtime, text, limit=16):
    """Observed local script paths and imports, useful for following worker hops."""
    epoch=getattr(runtime,'_cancel_epoch',None);check(runtime,epoch)
    tree=ast.parse(text.removeprefix('\ufeff'));rows=[];seen=set()
    def add(path,kind,line,**extra):
        key=str(path)
        if key in seen:return
        seen.add(key)
        rows.append({'path':path.relative_to(runtime.root.resolve()).as_posix(),
            'kind':kind,'line':line,**extra,'next_call':{'name':'source_map','arguments':{'path':str(path)}}})
    # An explicit worker script often leads forward while imports also include
    # shared infrastructure. Order by evidence kind, never by benchmark keywords.
    for node in ast.walk(tree):
        check_cancel(runtime,epoch)
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            value=node.value.replace('\\','/')
            if not value.endswith('.py') or not any(value.startswith(p+'/') for p in PUBLIC):continue
            try:path=public_path(runtime,value)
            except (PermissionError,ValueError):continue
            if path.is_file():add(path,'literal_script_reference',getattr(node,'lineno',None))
    for node in ast.walk(tree):
        check_cancel(runtime,epoch)
        modules=[]
        if isinstance(node,ast.ImportFrom) and not node.level and node.module:modules=[node.module]
        elif isinstance(node,ast.Import):modules=[item.name for item in node.names]
        for module in modules:
            paths=_modules(runtime,module)
            for path in paths:add(path,'local_import',node.lineno,module=module,ambiguous=len(paths)>1)
    check(runtime,epoch)
    return rows[:limit],len(rows)>limit


def _matches(test, name):
    if not isinstance(test,ast.Compare) or len(test.ops)!=1 or len(test.comparators)!=1:return False
    if not isinstance(test.left,ast.Name) or test.left.id!='name':return False
    value=test.comparators[0]
    if isinstance(test.ops[0],ast.Eq):return isinstance(value,ast.Constant) and value.value==name
    if isinstance(test.ops[0],ast.In) and isinstance(value,(ast.Tuple,ast.List,ast.Set)):
        return any(isinstance(item,ast.Constant) and item.value==name for item in value.elts)
    return False


def tool_entrypoint(runtime, name):
    epoch=getattr(runtime,'_cancel_epoch',None);check(runtime,epoch)
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z_0-9]{0,63}',name):
        raise ValueError('tool must be a named tool identifier')
    selected=None
    # Evaluation adapters may wrap the real class outside public source. Find
    # the own-install implementation already loaded in its MRO; import nothing.
    for cls in type(runtime).__mro__:
        method=cls.__dict__.get('execute')
        if method is None:continue
        try:filename=inspect.getsourcefile(method)
        except TypeError:continue
        if not filename:continue
        try:path,text,tree,digest=_read(runtime,Path(filename))
        except (PermissionError,ValueError,FileNotFoundError):continue
        first_line=getattr(getattr(method,'__code__',None),'co_firstlineno',None)
        class_nodes=[n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name==cls.__name__]
        dispatch=next((n for c in class_nodes for n in c.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
                       and n.name=='execute' and n.lineno==first_line),None)
        if dispatch is not None:selected=(path,text,dispatch,digest,cls.__name__);break
    if selected is None:raise ValueError('No own-install Python tool dispatcher was observed')
    path,text,dispatch,digest,clsname=selected
    branch=next((node for node in ast.walk(dispatch) if isinstance(node,ast.If) and _matches(node.test,name)),None)
    if branch is None:
        known=set()
        for node in ast.walk(dispatch):
            if not isinstance(node,ast.If):continue
            for literal in ast.walk(node.test):
                if isinstance(literal,ast.Constant) and isinstance(literal.value,str) and _matches(node.test,literal.value):
                    known.add(literal.value)
        check(runtime,epoch)
        return {'mode':'tool_entrypoint','tool':name,'path':str(path),'sha256':digest,'items':[],
            'observed_tools':sorted(known)[:32],
            'note':'No literal dispatch branch was observed for this identifier. Dynamic dispatch is not resolved. observed_tools lists code branches, not permissions; choose an existing tool or use ordinary source discovery.'}
    lines=text.splitlines(keepends=True);starts=[0]
    for line in lines:starts.append(starts[-1]+len(line))
    start=starts[branch.lineno-1];end=starts[branch.end_lineno]
    # Extract only this branch, dedenting so its imports can be parsed as code.
    import textwrap
    fragment=textwrap.dedent(text[start:end])
    bindings,_=references(runtime,fragment)
    rows=[]
    for item in bindings:
        target=runtime.root.resolve()/item['path']
        _,body,_,pin=_read(runtime,target)
        symbols=outline(body)[1]
        imported=[]
        for node in ast.walk(branch):
            if isinstance(node,ast.ImportFrom) and node.module==item.get('module'):
                imported.extend(a.name for a in node.names)
        for symbol in symbols:
            if symbol['symbol'] in imported:
                rows.append({'path':item['path'],'symbol':symbol['symbol'],'offset':symbol['offset'],
                    'end_offset':symbol['end_offset'],'sha256':pin,'kind':'dispatch_import','ambiguous':item.get('ambiguous',False),
                    'next_call':{'name':'source_map','arguments':{'path':str(target),'query':symbol['symbol']}}})
    for node in ast.walk(branch):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='self':
            qualified=clsname+'.'+node.func.attr
            for symbol in outline(text)[1]:
                if symbol['symbol']==qualified:
                    rows.append({'path':path.relative_to(runtime.root.resolve()).as_posix(),'symbol':qualified,
                        'offset':symbol['offset'],'end_offset':symbol['end_offset'],'sha256':digest,'kind':'dispatch_method',
                        'next_call':{'name':'read_file','arguments':{'path':str(path),'offset':symbol['offset'],'max_chars':min(6000,symbol['end_offset']-symbol['offset'])}}})
    check(runtime,epoch)
    return {'mode':'tool_entrypoint','tool':name,'path':str(path),'sha256':digest,'items':rows[:32],
        'total_items':len(rows),'scan_truncated':len(rows)>32,
        'dispatch_symbol':clsname+'.execute','dispatch_offset':start,'dispatch_end_offset':end,
        'next_call':{'name':'read_file','arguments':{'path':str(path),'offset':start,'max_chars':min(6000,end-start)}},
        'local_references':bindings,
        'note':'Observed branch in the already loaded own-install dispatcher. Imported symbols and references are static navigation evidence, not proof of the full call graph. Nothing was invoked.'}
