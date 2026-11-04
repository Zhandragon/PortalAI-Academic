"""Published math answer extraction with an external Windows process deadline.

Only the named original functions are loaded. The Windows-incompatible nested
timeout process is disabled inside this already time-bounded worker; equivalence
and boxed-answer extraction retain the original implementation.
"""
import ast,functools,hashlib,json,re,sys,threading
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE/'grader-packages'),str(ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages')]

def load(source,expected):
    raw=Path(source).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise RuntimeError('Published grader checksum mismatch')
    names={'build_prompt','answer_text','_box_at','last_boxed','extract','mv','_timeouts','_parsed','is_correct'}
    tree=ast.parse(raw);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes}!=names:raise RuntimeError('Incomplete original grading functions')
    ns={'functools':functools,'re':re,'sys':sys,'threading':threading,'_BOX_FORMS':re.compile(r'\\boxed|\\fbox'),'_MV':[],'MATHVERIFY_PKGS':str(HERE/'grader-packages')}
    ns['INSTRUCTION']=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='INSTRUCTION' for t in n.targets))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(source),'exec'),ns)
    ns['_timeouts']=lambda:None
    return ns

if __name__=='__main__':
    request=json.load(sys.stdin);ns=load(request['source'],request['sha256']);answer,boxes=ns['extract'](request['text'])
    print(json.dumps({'correct':bool(ns['is_correct'](answer,str(request['gold']))),'answer':answer,'boxes':boxes}))
