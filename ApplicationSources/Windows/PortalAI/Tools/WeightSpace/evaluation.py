"""Explicit, deterministic task graders; tool choices are never executed."""
import json,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_supervisor import WorkerJob

def bounded_grader(script,payload,timeout=15):
    proc=subprocess.Popen([sys.executable,'-B','-I',str(HERE/script)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    job=None
    try:
        job=WorkerJob(proc);job.limit_memory(512*1024**2)
        out,err=proc.communicate(json.dumps(payload).encode(),timeout=timeout)
        if proc.returncode:raise RuntimeError('Grader failed: '+err.decode('utf-8',errors='replace')[-500:])
        return json.loads(out)
    finally:
        if job:job.close()
        elif proc.poll() is None:proc.kill()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Owned grader did not stop after termination; evaluation halted.') from exc

def final_text(text):
    return text.rsplit('</think>',1)[-1].replace('<|im_end|>','').replace('<|endoftext|>','').strip()

def grade(case,text):
    content=final_text(text);kind=case['kind']
    if kind=='math':
        source=HERE/'published/mathqa.py';pin=json.loads((source.parent/'provenance.json').read_text())
        return bounded_grader('math_grade.py',{'source':str(source),'sha256':pin['sha256'],'text':text,'gold':case['answer']})
    if kind=='coding':
        try:
            result=bounded_grader('code_check.py',{'source':content,'checks':case['checks']},5)
        except subprocess.TimeoutExpired:
            # The owned grader has already stopped its worker in finally.
            # A non-terminating model answer is wrong; infrastructure errors still raise.
            result={'passed':False,'timed_out':True,
                    'reason':'Model program exceeded the five-second code execution budget; owned worker stopped.'}
        return {'correct':bool(result['passed']),'detail':result}
    if kind=='tool':
        from tool_call_format import parse_tool_calls,same_value
        try:calls=parse_tool_calls(content,case.get('tools',()))
        except (ValueError,TypeError,RecursionError):
            return {'correct':False,'reason':'Malformed or unsupported tool call','tools_executed':False,'grader_version':'qwen-tool-formats-v2'}
        wanted=case['calls']
        return {'correct':same_value(calls,wanted),'observed_calls':calls,'tools_executed':False,'grader_version':'qwen-tool-formats-v2'}
    if kind=='exact':return {'correct':content==case['answer'],'observed':content[:500]}
    if kind=='json':
        try:got=json.loads(content)
        except ValueError:return {'correct':False,'reason':'Expected only valid JSON'}
        return {'correct':got==case['answer'],'observed':got}
    raise ValueError('Unknown task grader: '+str(kind))

def read_cases(path):
    path=Path(path)
    if path.stat().st_size>16*1024**2:raise ValueError('Case file exceeds 16 MiB')
    rows=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(rows,list) or not 1<=len(rows)<=256:raise ValueError('A pass needs 1 to 256 unique cases')
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in seen:raise ValueError('Each case needs a unique text ID')
        if row.get('kind') not in ('math','coding','tool','exact','json'):raise ValueError('Unsupported task grader')
        if not isinstance(row.get('prompt'),str) or len(row['prompt'])>65536:raise ValueError('Invalid task prompt')
        seen.add(row['id'])
    return rows
