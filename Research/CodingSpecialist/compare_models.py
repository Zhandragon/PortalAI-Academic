"""Frozen, bounded local coding comparison; public weights, no user chat data."""
import argparse, ast, collections, hashlib, json, os, re, socket, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = [
 ('merge_intervals', 'Implement merge_intervals(intervals): merge closed integer intervals that overlap or touch at an endpoint. Return sorted [start,end] lists. Do not mutate input. Reject an interval with start > end with ValueError.',
  "assert f([])==[]\nassert f([[1,3],[2,6],[8,10],[10,12]])==[[1,6],[8,12]]\nassert f([[-5,-2],[-3,0],[4,4]])==[[-5,0],[4,4]]\nx=[[5,7],[1,2]]; assert f(x)==[[1,2],[5,7]] and x==[[5,7],[1,2]]\ntry: f([[4,1]])\nexcept ValueError: pass\nelse: raise AssertionError('invalid interval')"),
 ('toposort', 'Implement toposort(nodes, edges). Nodes are unique strings; edges are (source,target) pairs. Return lexicographically smallest topological ordering. Include isolated nodes; ignore duplicate edges. Raise ValueError for a cycle or an edge referencing an unknown node.',
  "assert f(['b','a','c'],[])==['a','b','c']\nassert f(['a','b','c','d'],[('a','c'),('b','c'),('a','c')])==['a','b','c','d']\nassert f([],[])==[]\nfor nodes,edges in [(['a','b'],[('a','b'),('b','a')]),(['a'],[('a','z')]),(['a'],[('a','a')])]:\n try: f(nodes,edges)\n except ValueError: pass\n else: raise AssertionError('must reject')"),
 ('json_pointer', 'Implement json_pointer(doc, pointer) for RFC6901 JSON pointers. Empty pointer returns doc. Nonempty pointer must start /. Decode ~1 to slash and ~0 to tilde, rejecting other ~ escapes with ValueError. Dict keys are literal strings. List indices must be nonnegative decimal without leading zeros (except 0); reject - or out of range with ValueError. Missing dict keys and traversal through scalars raise ValueError.',
  "d={'a/b':{'~key':[10,20]},'':5,'~1':42}; assert f(d,'') is d\nassert f(d,'/a~1b/~0key/1')==20\nassert f(d,'/')==5\nassert f(d,'/~01')==42\nfor p in ['bad','/~2','/missing','/a~1b/~0key/01','/a~1b/~0key/-1','/a~1b/~0key/2','/a~1b/~0key/-','/a~1b/~0key/0/x']:\n try: f(d,p)\n except ValueError: pass\n else: raise AssertionError(p)"),
 ('shortest_path', 'Implement shortest_path(n, edges, source, target) for a directed graph with vertices 0..n-1 and nonnegative numeric weights. Return shortest distance, or None when unreachable. Reject negative weights with ValueError even in unreachable components. Duplicate edges are allowed; zero weights allowed. Use an efficient priority queue approach.',
  "assert f(4,[(0,1,9),(0,2,1),(2,1,1),(1,3,2)],0,3)==4\nassert f(3,[(0,1,0),(0,1,5),(1,2,0)],0,2)==0\nassert f(3,[],0,2) is None\nassert f(1,[],0,0)==0\ntry: f(4,[(2,3,-1)],0,1)\nexcept ValueError: pass\nelse: raise AssertionError('negative')"),
 ('split_quoted', 'Implement split_quoted(line) for one CSV-like row: comma delimiters, double-quoted fields may contain commas, doubled double-quotes inside quoted fields mean a literal quote. Unquoted fields cannot contain quotes; nothing except comma or end may follow a closing quote. Preserve whitespace. Empty line is one empty field. Reject malformed quoting with ValueError. Do not use the csv module.',
  "assert f('')==['']\nassert f('a,,b,')==['a','','b','']\nassert f('\"a,b\",\"he said \"\"hi\"\"\", c')==['a,b','he said \"hi\"',' c']\nassert f('\"\"')==['']\nfor s in ['\"abc','a\"b','\"a\"x','\"a\" ']:\n try: f(s)\n except ValueError: pass\n else: raise AssertionError(s)"),
 ('longest_unique', 'Fix and implement longest_unique(text): return the length of the longest substring without repeated Unicode characters in O(n) time. A previous implementation moved its left boundary backwards on repeated characters outside the current window. Handle empty strings, repeated characters and non-ASCII correctly.',
  "assert f('')==0\nassert f('abba')==2\nassert f('tmmzuxt')==5\nassert f('abcabcbb')==3\nassert f('bbbbb')==1\nassert f('pwwkew')==3\nassert f('你好世界你')==4\nassert f('a'*100000)==1"),
]

def request(port, route, data=None, timeout=30):
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+route,
         data=json.dumps(data).encode() if data is not None else None, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)

def grade(name, output, assertions):
    blocks=re.findall(r'```(?:python|py)?\s*\n(.*?)```',output,re.S)
    code='\n'.join(blocks) if blocks else output.strip()
    try:
        tree=ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                names=[a.name.split('.')[0] for a in node.names] if isinstance(node,ast.Import) else [node.module]
                if any(n not in ('heapq','collections','re','math','typing') for n in names): raise ValueError('unsupported import')
            if isinstance(node,ast.Attribute) and node.attr.startswith('_'): raise ValueError('private attribute')
            if isinstance(node,ast.Name) and (node.id.startswith('__') or node.id in ('exec','eval','open','compile','globals','locals','getattr','setattr','delattr','input','breakpoint')): raise ValueError('unsupported builtin')
        path=HERE/'tmp'/('grade-'+name+'.py')
        path.write_text(code+'\nf='+name+'\n'+assertions,encoding='utf-8')
        run=subprocess.run([sys.executable,'-I','-S',str(path)],cwd=HERE/'tmp',capture_output=True,text=True,timeout=3,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return run.returncode==0,run.stderr[-1000:]
    except Exception as exc:return False,str(exc)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--label',required=True);a=p.parse_args()
    sys.dont_write_bytecode=True;sys.path.insert(0,str(a.root/'Agent'))
    import service_manager as service
    from runtime_policy import portable_env
    (HERE/'tmp').mkdir(exist_ok=True)
    frozen={'tasks':TASKS,'seed':46,'temperature':0.6,'top_p':0.95,'top_k':20,'max_tokens':4096,'context':8192,'thinking':True,'reasoning_effort':'xhigh'}
    pin=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
    fixture=HERE/'comparison-protocol.json'
    if fixture.exists():assert json.loads(fixture.read_text())==json.loads(json.dumps(frozen)), 'Frozen protocol changed'
    else: fixture.write_text(json.dumps(frozen,indent=2),encoding='utf-8')
    report=HERE/('comparison-'+a.label+'.json')
    if report.exists(): raise RuntimeError('Existing result; do not rerun blindly')
    lease=service.acquire_gpu_lease('coding-specialist-validation',timeout=3)
    proc=None
    try:
        # Do not evict a running chat or game; only launch when this test fits.
        free=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).splitlines()[0])
        if free<21500: raise RuntimeError('At least 21 GiB free VRAM required; test deferred')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        cmd=[str(a.root/'LLM/llamacpp/llama-server.exe'),'-m',str(a.model),'-ngl','99','-c','8192','--parallel','1','--jinja','--metrics','--host','127.0.0.1','--port',str(port),'--device','CUDA0']
        rows=[]; started=time.monotonic()
        with (HERE/('server-'+a.label+'.log')).open('wb') as log:
            env=portable_env(a.root,before_login=True)
            env.update(TEMP=str(HERE/'tmp'),TMP=str(HERE/'tmp'),TMPDIR=str(HERE/'tmp'))
            proc=subprocess.Popen(cmd,cwd=a.root,env=env,stdout=log,stderr=log,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(600):
                if proc.poll() is not None:raise RuntimeError('Server exited; see log')
                try:
                    if request(port,'/health',timeout=1).get('status')=='ok':break
                except Exception:pass
                time.sleep(.5)
            else:raise TimeoutError('Server startup')
            load=time.monotonic()-started
            request(port,'/v1/chat/completions',{'messages':[{'role':'user','content':'Reply with OK.'}],'max_tokens':4,'chat_template_kwargs':{'enable_thinking':False}},120)
            for name,prompt,assertions in TASKS:
                data={'messages':[{'role':'system','content':'You are a careful Python coding assistant. Return the requested implementation in a single Python code block. Use the Python standard library only.'},{'role':'user','content':prompt}],
                      'seed':46,'temperature':.6,'top_p':.95,'top_k':20,'max_tokens':4096,'chat_template_kwargs':{'enable_thinking':True,'reasoning_effort':'xhigh'}}
                start=time.monotonic();out=request(port,'/v1/chat/completions',data,timeout=600);elapsed=time.monotonic()-start
                choice=out['choices'][0];message=choice['message'];answer=message.get('content') or '';reasoning=message.get('reasoning_content') or message.get('reasoning') or ''
                passed,error=grade(name,answer,assertions)
                words=(reasoning+' '+answer).split();spans=[' '.join(words[i:i+48]) for i in range(0,max(0,len(words)-47),16)]
                repeats=sum(n-1 for n in collections.Counter(spans).values() if n>1)
                row={'task':name,'passed':passed,'error':error,'seconds':elapsed,'usage':out.get('usage'), 'timings':out.get('timings'),'finish_reason':choice.get('finish_reason'),'repeated_48_word_spans':repeats,'response':message}
                rows.append(row);report.write_text(json.dumps({'label':a.label,'model':str(a.model),'protocol_sha256':pin,'load_seconds':load,'complete':len(rows)==len(TASKS),'rows':rows},indent=2),encoding='utf-8')
                print(json.dumps({k:row[k] for k in ('task','passed','seconds','usage','finish_reason','repeated_48_word_spans')}),flush=True)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        service.release_gpu_lease(lease)

if __name__=='__main__':main()
