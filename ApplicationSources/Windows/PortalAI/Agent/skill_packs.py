"""Reviewed portable skill bundles with immutable files and isolated dependencies.

Import never runs code. Script execution requires an explicit per-skill grant
and the existing administrator role; this is not an OS security sandbox.
"""
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from portable_workspace import Skills,parse_skill
from workspace_store import identifier,read_json,digest,encoded

MAX_PACK=128*1024**2
MAX_EXPANDED=256*1024**2


def relative(value):
    if not isinstance(value,str) or not value or len(value)>200 or '\\' in value or ':' in value or '\0' in value:
        raise ValueError('Invalid bundle path')
    p=PurePosixPath(value)
    if p.is_absolute() or any(x in ('..','.') or x.endswith(('.', ' ')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',x) for x in p.parts):raise ValueError('Bundle path escapes or aliases its directory')
    if p.as_posix()!=value:raise ValueError('Bundle paths must be canonical')
    return value


def inventory(archive,maximum=MAX_EXPANDED):
    rows={};folded=set();total=0
    for row in archive.infolist():
        if row.is_dir():continue
        name=relative(row.filename)
        if name.casefold() in folded or stat.S_ISLNK(row.external_attr>>16) or row.flag_bits&1:raise ValueError('Duplicate, encrypted or linked bundle entry')
        total+=row.file_size
        if total>maximum or len(rows)>=2048:raise ValueError('Bundle exceeds its expanded-size/file limit')
        rows[name]=row;folded.add(name.casefold())
    return rows


def wheel_files(raw):
    """Install only compatible prebuilt wheels; never run installers or .pth code."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        rows=inventory(z);metadata=[n for n in rows if n.endswith('.dist-info/WHEEL')]
        if len(metadata)!=1:raise ValueError('Dependency must be a valid wheel')
        text=z.read(metadata[0]).decode();cp='cp'+str(sys.version_info.major)+str(sys.version_info.minor)
        tags=[line[5:].strip() for line in text.splitlines() if line.startswith('Tag: ')]
        supported=lambda t:t in ('py3-none-any',cp+'-none-any',cp+'-'+cp+'-win_amd64') or t=='py2.py3-none-any'
        if not any(supported(t) for t in tags):raise ValueError('Wheel is incompatible with the portable Python runtime')
        # Keep original member names separate from the installed library path.
        result={};seen=set()
        for original in rows:
            if original.lower().endswith('.pth'):raise ValueError('Executable .pth dependency hooks are not supported')
            parts=original.split('/');name=original
            if parts[0].endswith('.data'):
                if len(parts)<3 or parts[1] not in ('purelib','platlib'):continue
                name='/'.join(parts[2:])
            key=relative(name)
            if key.casefold() in seen:raise ValueError('Dependency entries collide')
            seen.add(key.casefold())
            result[key]=z.read(original)
        return result


class SkillPacks(Skills):
    def import_pack(self,path):
        from runtime_policy import require_space
        path=Path(path)
        if path.stat().st_size>MAX_PACK:raise ValueError('Skill archive exceeds 128 MiB')
        with zipfile.ZipFile(path) as z:
            rows=inventory(z)
            if 'skill.json' not in rows or rows['skill.json'].file_size>65536:raise ValueError('A skill pack needs a bounded skill.json manifest')
            manifest=json.loads(z.read('skill.json'))
            if set(manifest)-{'version','instructions','files','scripts','wheels'} or manifest.get('version')!=1:raise ValueError('Unsupported skill manifest')
            files=manifest.get('files',{})
            if not isinstance(files,dict) or set(files)!=set(rows)-{'skill.json'}:raise ValueError('Manifest must hash every bundled file exactly once')
            if any(n.casefold().split('/')[0]=='dependencies' for n in files):raise ValueError('dependencies/ is reserved for isolated wheels')
            instructions=relative(manifest.get('instructions','SKILL.md'));scripts=manifest.get('scripts',{});wheels=manifest.get('wheels',[])
            if not isinstance(scripts,dict) or len(scripts)>32 or any(not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,39}',k) or relative(v) not in files or not v.endswith('.py') for k,v in scripts.items()):raise ValueError('Scripts must name bundled Python files')
            if not isinstance(wheels,list) or len(wheels)>32 or any(relative(w) not in files or not w.endswith('.whl') for w in wheels):raise ValueError('Dependencies must be bundled, pinned wheels')
            payload={};libraries={};expanded=0
            for name,expected in files.items():
                data=z.read(name);self.check()
                if not isinstance(expected,str) or hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Skill bundle checksum mismatch: '+name)
                payload[name]=data;expanded+=len(data)
                if name in wheels:
                    for key,value in wheel_files(data).items():
                        if key.casefold() in {k.casefold() for k in libraries}:raise ValueError('Dependency packages collide')
                        libraries[key]=value;expanded+=len(value)
                if expanded>MAX_EXPANDED:raise ValueError('Expanded skill and dependencies exceed 256 MiB')
            if instructions not in payload:raise ValueError('Skill instructions are missing')
            guide=parse_skill(payload[instructions].decode('utf-8-sig'),path.stem)
        require_space(self.root,expanded*2+4*1024**2,for_outputs=True)
        with self.lock():
            if len(self.records('Items'))>=128:raise ValueError('Skill library limit reached')
            sid=self.new_id();folder=self.path('Packs/'+sid);folder.mkdir(parents=True,exist_ok=False)
            try:
                hashes={}
                for name,data in {**payload,**{'dependencies/'+k:v for k,v in libraries.items()}}.items():
                    self.check();target=folder/relative(name);target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                    hashes[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                row={**guide,'id':sid,'version':2,'enabled':False,'code_enabled':False,'updated':time.time(),
                    'pack':{'files':hashes,'scripts':scripts,'wheels':wheels,'expanded_bytes':expanded}}
                self.save('Items/'+sid+'.json',row);return row
            except Exception:
                self.check()
                assert folder.resolve().is_relative_to(self.path('Packs').resolve())
                shutil.rmtree(folder);raise

    def allow_code(self,sid,enabled):
        with self.lock():
            row=self.load(sid)
            if not row.get('pack'):raise ValueError('This is a text-only skill')
            row['code_enabled']=bool(enabled);self.save('Items/'+identifier(sid)+'.json',row);return row

    def assets(self,sid):
        row=self.load(sid)
        if not row['enabled']:raise PermissionError('Enable the skill first')
        return {'files':row.get('pack',{}).get('files',{}),'scripts':row.get('pack',{}).get('scripts',{}),'code_enabled':row.get('code_enabled',False)}

    def file(self,sid,name,offset=0):
        row=self.load(sid);relative(name)
        if not row['enabled']:raise PermissionError('Enable the skill first')
        info=row.get('pack',{}).get('files',{}).get(name)
        if not info or name.startswith('dependencies/'):raise ValueError('Choose a bundled guide or supporting file')
        if type(offset) is not int or offset<0 or info['bytes']>2*1024**2:raise ValueError('File is not a bounded text resource')
        data=self.path('Packs/'+identifier(sid)+'/'+name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=info['sha256']:raise ValueError('Skill file changed; reimport and review it')
        content=data.decode('utf-8-sig');end=min(len(content),offset+4000)
        return {'path':name,'content':content[offset:end],'next_offset':end if end<len(content) else None,'sha256':info['sha256']}

    def run(self,sid,script,arguments,runtime):
        if runtime._account_role()!='admin':raise PermissionError('Skill scripts require the existing administrator role')
        if not isinstance(arguments,list) or any(not isinstance(v,str) or '\0' in v for v in arguments) or len(encoded(arguments))>8192:raise ValueError('Script arguments must be a bounded text array')
        from mission_supervisor import WorkerJob
        from platform_runtime import python_path,worker_process_options
        from runtime_policy import portable_env,require_space,GIB
        with self.lock('script-calls'):
            row=self.load(sid);pack=row.get('pack',{})
            if not row['enabled'] or not row.get('code_enabled') or script not in pack.get('scripts',{}):raise PermissionError('Review, enable and grant this skill script in Workspace')
            action={'skill':sid,'script':script,'arguments':arguments};signature=digest(action)
            receipts=self.records('Calls')
            if len(receipts)>=1000:raise ValueError('Review skill execution history before more calls')
            for rid in receipts:
                previous=read_json(self.path('Calls/'+rid+'.json'))
                if previous.get('state')=='pending' and previous['signature']==signature:raise RuntimeError('An earlier skill action has an uncertain outcome; review it before retrying')
            folder=self.path('Packs/'+identifier(sid))
            for name,info in pack['files'].items():
                self.check();path=folder/relative(name)
                if path.stat().st_size!=info['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Skill files changed; reimport and review')
            require_space(self.root,16*1024**2,for_outputs=True);rid=self.new_id();record={**action,'id':rid,'signature':signature,'state':'pending','started':time.time()}
            self.save('Calls/'+rid+'.json',record);log=self.path('Calls/'+rid+'.log');proc=job=None
            try:
                entry=folder/pack['scripts'][script]
                code='import sys,runpy;assert sys.stdin.buffer.readline(8)==b"go\\n";sys.path[:0]=[sys.argv[1],sys.argv[2]];sys.argv=sys.argv[3:];runpy.run_path(sys.argv[0],run_name="__main__")'
                with log.open('xb') as out:
                    current=self.load(sid)
                    if not current['enabled'] or not current.get('code_enabled') or runtime._account_role()!='admin':raise PermissionError('Skill execution grant was revoked')
                    self.check();proc=subprocess.Popen([str(python_path(self.root)),'-B','-I','-c',code,str(folder/'dependencies'),str(entry.parent),str(entry),*arguments],cwd=folder,
                        stdin=subprocess.PIPE,stdout=out,stderr=out,env=portable_env(self.root),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),**worker_process_options())
                    job=WorkerJob(proc);job.limit_memory(2*GIB);job.check();self.check()
                    proc.stdin.write(b'go\n');proc.stdin.flush();proc.stdin.close();deadline=time.monotonic()+120
                    while proc.poll() is None:
                        self.check();job.check();require_space(self.root,for_outputs=True)
                        if time.monotonic()>deadline:raise TimeoutError('Skill script exceeded 120 seconds; outcome needs review')
                        if log.stat().st_size>65536:raise RuntimeError('Skill output exceeded 64 KiB; outcome needs review')
                        time.sleep(.05)
                self.check()
                with log.open('rb') as stream:output=stream.read(65537)
                if len(output)>65536:raise ValueError('Skill output limit exceeded; outcome needs review')
                result={'exit_code':proc.returncode,'output':output.decode('utf-8','replace'),'receipt':rid}
                record.update(state='complete',result=result);self.save('Calls/'+rid+'.json',record);return result
            finally:
                if job:job.close()
                if proc:
                    if proc.poll() is None:proc.kill()
                    proc.wait(timeout=10)
                log.unlink(missing_ok=True)

    def review_call(self,rid,confirmed):
        with self.lock('script-calls'):
            path='Calls/'+identifier(rid)+'.json';row=read_json(self.path(path))
            if row['state']!='pending':raise ValueError('This receipt does not need review')
            row.update(state='reviewed',review='confirmed' if confirmed else 'explicit_retry_allowed',reviewed=time.time());self.save(path,row)
