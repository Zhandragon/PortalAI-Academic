"""Restricted pure-function check in a parent-owned, memory/time-limited process.

This is not a general code sandbox. The benchmark permits no imports, file/network
APIs, dunder access, dynamic evaluation, classes, generators or arbitrary attributes.
"""
import ast,copy,json,re,sys
def main():
    data=json.loads(sys.stdin.buffer.read(100000))
    source=data['source'];blocks=re.findall(r'```(?:python)?\s*\n(.*?)```',source,re.S)
    source=blocks[0] if blocks else source.strip()
    if len(source)>16000:raise ValueError('Source exceeds limit')
    tree=ast.parse(source)
    safe_names={'abs','all','any','bool','dict','enumerate','float','int','len','list','max','min','range','reversed','set','sorted','str','sum','tuple','zip'}
    safe_attrs={'append','extend','pop','get','items','keys','values','add','remove','sort','copy','count','index','strip','lower','upper','startswith','endswith','fromkeys','setdefault','update','clear','join','split','isdigit','isalpha'}
    forbidden=(ast.Import,ast.ImportFrom,ast.ClassDef,ast.Global,ast.Nonlocal,ast.With,ast.AsyncWith,ast.Await,ast.Yield,ast.YieldFrom,ast.AsyncFunctionDef,ast.Delete)
    functions={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    for n in ast.walk(tree):
        if isinstance(n,forbidden):raise ValueError('Unsupported Python construct')
        if isinstance(n,ast.Name) and n.id.startswith('__'):raise ValueError('Private name access')
        if isinstance(n,ast.Attribute) and n.attr not in safe_attrs:raise ValueError('Unsupported attribute')
        if isinstance(n,ast.Call) and not isinstance(n.func,(ast.Name,ast.Attribute)):raise ValueError('Indirect call')
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id not in safe_names|functions:raise ValueError('Unsupported call')
    import builtins
    ns={'__builtins__':{n:getattr(builtins,n) for n in safe_names}}
    exec(compile(tree,'<model-pure-function>','exec'),ns)
    if not callable(ns.get('solve')):raise ValueError('Missing solve function')
    for args,expected in data['checks']:
        actual_args=copy.deepcopy(args);got=ns['solve'](*actual_args)
        if got!=expected or actual_args!=args:return {'passed':False,'reason':'Wrong result or mutated input'}
    return {'passed':True,'checks':len(data['checks'])}
try:print(json.dumps(main()))
except BaseException as exc:print(json.dumps({'passed':False,'reason':type(exc).__name__+': '+str(exc)[:180]}))
