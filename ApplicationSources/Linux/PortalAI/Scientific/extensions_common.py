"""Bounds and owned-worker support for portable science extensions."""
import hashlib,json,math,os,subprocess,time,uuid
from pathlib import Path

def number(value,name,low=-1e100,high=1e100):
    if isinstance(value,bool):raise ValueError(name+' must be a number')
    value=float(value)
    if not math.isfinite(value) or not low<=value<=high:raise ValueError(name+' out of range')
    return value

def integer(value,name,low,high):
    n=number(value,name,low,high)
    if n!=int(n):raise ValueError(name+' must be an integer')
    return int(n)

def keys(p,allowed):
    unknown=set(p)-set(allowed)-{'export','output_dir'}
    if unknown:raise ValueError('Unsupported arguments: '+', '.join(sorted(unknown)))

def read(context,value,limit=16*1024**2):
    from media_paths import media_reference
    context.check();path=media_reference(context.root,str(value))
    with path.open('rb') as f:
        a=os.fstat(f.fileno());data=f.read(limit+1);b=os.fstat(f.fileno())
    sig=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if sig(a)!=sig(b) or a.st_ctime_ns!=b.st_ctime_ns or sig(b)!=sig(path.stat()):raise RuntimeError('Input changed while being read')
    if len(data)>limit:raise ValueError('Input exceeds '+str(limit)+' bytes')
    context.check();return data

def sha(data):return hashlib.sha256(data).hexdigest()

def asset(context,relative):
    from profile_paths import _contained
    row=next((r for r in json.loads((context.root/'Maintenance/Imports/science-expansion.json').read_text())['files'] if r['path']==relative),None)
    if row is None:raise RuntimeError('Missing public science asset receipt: '+relative)
    path=_contained(context.root,context.root/relative)
    if path.stat().st_size!=row['bytes']:raise RuntimeError('Science asset size mismatch')
    with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual!=row['sha256']:raise RuntimeError('Science asset checksum mismatch: '+relative)
    context.check();return path

def worker(context,operation,request,inputs=None,timeout=90,memory=2*1024**3):
    """Isolated owned process; Stop/account/time/memory gates. No shell dispatch."""
    from profile_paths import private_path,_contained
    from platform_runtime import python_path
    from runtime_policy import portable_env,memory_info,require_space
    from mission_supervisor import WorkerJob
    root=context.root;context.check();require_space(root,64*1024**2,for_outputs=True)
    if memory_info()[1]<memory+768*1024**2:raise RuntimeError('Insufficient free RAM for bounded science worker')
    folder=private_path(root,'Cache/tmp',context=context.identity)/('science_'+uuid.uuid4().hex)
    _contained(root,folder);folder.mkdir(parents=True);owned={};proc=job=None;success=False
    def write(name,data):
        if Path(name).name!=name:raise ValueError('Worker filename must be a basename')
        p=_contained(root,folder/name);context.check()
        with p.open('xb') as f:
            s=os.fstat(f.fileno());owned[name]=(s.st_dev,s.st_ino);f.write(data);f.flush();os.fsync(f.fileno())
        return p
    try:
        for name,data in (inputs or {}).items():write(name,data)
        request=dict(request,operation=operation,root=str(root))
        req=write('request.json',json.dumps(request,allow_nan=False).encode())
        gate=folder/'gate'
        launch=write('launch.json',json.dumps({'command':[str(python_path(root)),'-B','-I',str(root/'Scientific/science_worker.py'),str(req)],'gate':str(gate)}).encode())
        log=write('log.txt',b'');env=portable_env(root);env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
        start=time.monotonic()
        with log.open('ab') as f:
            proc=subprocess.Popen([str(python_path(root)),'-B','-I',str(root/'Agent/sdcpp_worker.py'),str(launch)],cwd=folder,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            job=WorkerJob(proc);job.limit_memory(memory);context.check();write('gate',b'')
            while proc.poll() is None:
                context.check();job.check()
                if time.monotonic()-start>timeout:raise TimeoutError('Science worker exceeded its time budget')
                if log.stat().st_size>1024**2:raise RuntimeError('Science worker log limit exceeded')
                time.sleep(.1)
        context.check()
        if proc.returncode:raise RuntimeError('Science worker failed: '+log.read_text(errors='replace')[-1800:])
        contents={};result=None
        for p in folder.iterdir():
            if p.name in owned:continue
            if p.name not in ('result.json','poses.pdbqt','print.3mf','print.gcode','annotated.gb','features.csv','feature-map.svg'):raise RuntimeError('Unexpected science worker output: '+p.name)
            if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400:raise RuntimeError('Linked worker output refused')
            s=p.stat();owned[p.name]=(s.st_dev,s.st_ino)
            if s.st_size>16*1024**2:raise RuntimeError('Science worker output exceeds 16 MiB')
            data=p.read_bytes()
            if (p.stat().st_dev,p.stat().st_ino)!=owned[p.name]:raise RuntimeError('Worker output replaced')
            if p.name=='result.json':result=json.loads(data)
            else:contents[p.name]=data
        if result is None:raise RuntimeError('Worker returned no result')
        context.check();success=True;return result,contents
    finally:
        if job:job.close()
        if proc and proc.poll() is None:proc.kill();proc.wait(timeout=10)
        # Failed jobs retain bounded evidence; successful cleanup only owns recorded identities.
        if success:
            for name,identity in owned.items():
                p=_contained(root,folder/name)
                if p.exists():
                    s=p.lstat()
                    if (s.st_dev,s.st_ino)!=identity:raise RuntimeError('Science cleanup refused a replaced file')
                    p.unlink()
            folder.rmdir()
