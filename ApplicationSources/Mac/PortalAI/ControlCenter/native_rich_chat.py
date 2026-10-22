"""Account-bound conversation records; no prompts, tool execution or URL fetches."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from native_rich_protocol import validate_request,validate_reply,LIMIT,CHUNK,BATCH_CHUNK

def opaque(*parts):return hashlib.sha256(':'.join(map(str,parts)).encode()).hexdigest()[:32]
def clipped(v,n=16000):return str(v or '')[:n].encode('utf-8','replace').decode('utf-8')
SENSITIVE=re.compile(r'(?i)(password|passwd|secret|token|authorization|cookie|api[_-]?key|private[_-]?key|credential|^env(?:ironment)?$)')
def sanitize(value):
    # Only conversation evidence enters here, never process environments or prompts.
    def clean(v,depth=0):
        if depth>12:return '[depth limit]'
        if isinstance(v,dict):return {str(k):'[redacted]' if SENSITIVE.search(str(k)) else clean(x,depth+1) for k,x in list(v.items())[:200]}
        if isinstance(v,list):return [clean(x,depth+1) for x in v[:200]]
        return v
    raw=clipped(value,50000)
    try:raw=json.dumps(clean(json.loads(raw)),ensure_ascii=False,indent=2)
    except (ValueError,TypeError):
        # Truncated JSON and plain logs must not defeat structured-key redaction.
        raw=re.sub(r'''(?im)^.*["']?\b(?:password|passwd|secret|token|authorization|cookie|api[_-]?key|private[_-]?key|credential|env|environment)["']?\s*[:=].*$''','[redacted sensitive field]',raw)
    raw=re.sub(r'(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)','[redacted key]',raw)
    raw=re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9_+/=.\-]+',r'\1 [redacted]',raw)
    raw=re.sub(r'(?i)((?:password|passwd|secret|token|api[_-]?key|authorization|cookie)\s*[=:]\s*)([^\s,;]+)',r'\1[redacted]',raw)
    return raw

def observe(panel,kind,data):
    """Tk's already-delivered stream only; bounded RAM and no disk/network work."""
    if kind=='assistant_start':
        panel._native_rich_live={'session':panel.session,'index':data.get('index',len(panel.session.get('messages',[]))) if isinstance(data,dict) else len(panel.session.get('messages',[])), 'reasoning':'','length':0}
    elif kind=='reasoning':
        live=getattr(panel,'_native_rich_live',None)
        if live and live['session'] is panel.session:
            value=str(data);live['length']+=len(value);live['reasoning']=(live['reasoning']+value[:16000])[:16000]
    elif kind=='done':panel._native_rich_live=None

class MediaRead:
    def __init__(self,controller,p,deadline,record):
        self.controller=controller;self.payload=p;self.deadline=deadline;self.result=None
        self.error=False;self.done=threading.Event();self.value=None;self.record=record
        # NativeChat closes and joins this existing group before profile sealing.
        def read():
            try:self.value=controller.read_media(record,p,deadline)
            except Exception:self.error=True
            finally:self.done.set()
        controller.ex.chat._thread(target=read,name='PortalAI-rich-media-read').start()
    def refuse(self):self.error=True;self.value=None
    def poll(self):
        self.controller.check(self.payload,self.deadline)
        if self.error:raise RuntimeError('rich_media_unavailable_or_too_large')
        if not self.done.is_set():return None
        self.controller.inventory(self.payload)
        if self.payload['block'] not in self.controller.records or not self.controller.record_current(self.record):raise PermissionError('rich_media_record_changed')
        self.result=self.controller.reply(self.payload,**self.value);self.value=None
        return self.result

class Controller:
    def __init__(self,exporter):
        from native_chat_command import Controller as AccountCheck
        self.ex=exporter;self.guard=AccountCheck(exporter);self.scope=None;self.records={};self.refs={};self.pending=[]
        self.sequence=0
    def check(self,p,deadline):
        self.guard.check(p,deadline)
        scope=(self.ex.view,self.ex.epoch,p['conversation'],id(self.ex.chat.session))
        if scope!=self.scope:
            self.records.clear();self.refs.clear();self.scope=scope
        return scope
    def current(self,r):
        # HTTP thread never calls Tk. Recheck real account and current conversation.
        ex=self.ex
        with ex.lock:
            record=self.records.get(r.get('block'))
            return (ex.allowed(authenticate=True) and ex.mode=='ready' and r['binding']=={'view':ex.view,'epoch':ex.epoch}
                    and not getattr(ex.chat,'_session_load_request',None) and ex.chat.session
                    and ex.chat.session.get('id')==r['conversation'] and self.scope is not None
                    and id(ex.chat.session)==self.scope[3]
                    and ('block' not in r or record is not None and (record[0]!='media' or self.record_current(record[1]))))
    def record_current(self,record):
        panel=self.ex.chat;row=record['row'];entry=record['entry']
        return (any(x is row for x in panel.session.get('messages',[])[-100:])
                and any(x is entry for x in row.get('attachments' if record['attachment'] else 'media',[]))
                and entry.get('path')==record['reference'])
    def reply(self,p,**extra):
        reply={'accepted':True,'request_id':p['request_id'],'operation':p['operation'],
               'rich':{'protocol':p['protocol'],'binding':p['binding'],'conversation':p['conversation'],**extra}}
        return validate_reply(reply,p)
    def inventory(self,p):
        ex=self.ex;panel=ex.chat;rows=panel.session.get('messages',[]);start=max(0,len(rows)-100)
        blocks=[];records={};calls={};truncated=start>0
        def add(index,key,kind,title,status,source):
            nonlocal truncated
            if len(blocks)>=120:truncated=True;return
            # Object identity distinguishes edits/replaced turns at the same index.
            ref=rows[index] if index<len(rows) else getattr(panel,'_native_rich_live',None)
            old=self.refs.get((index,key))
            transition=(old is not None and key=='thinking' and isinstance(old[0],dict)
                        and old[0].get('session') is panel.session and isinstance(ref,dict) and ref.get('role')=='assistant')
            if transition:old=(ref,old[1]);self.refs[index,key]=old
            if old is None or old[0] is not ref:
                self.sequence+=1;old=(ref,self.sequence);self.refs[index,key]=old
            block=opaque(ex.epoch,p['conversation'],index,key,old[1]);mid=opaque(ex.epoch,p['conversation'],index)
            blocks.append({'id':block,'message':mid,'kind':kind,'title':clipped(title,120),'status':status})
            if len(json.dumps(blocks,ensure_ascii=False).encode('utf-8'))>45000:
                blocks.pop();truncated=True;return
            records[block]=(kind,source)
            return block
        for index in range(start,len(rows)):
            row=rows[index]
            if not isinstance(row,dict):continue
            role=row.get('role')
            if role not in ('user','assistant','tool'):continue
            if role=='assistant':
                state='cancelled' if row.get('cancelled') else 'incomplete' if row.get('incomplete') else 'saved'
                if row.get('reasoning'):add(index,'thinking','thinking','Thinking',state,lambda row=row:row.get('reasoning',''))
                for n,call in enumerate((row.get('tool_calls') or [])[:32]):
                    if not isinstance(call,dict) or not isinstance(call.get('function'),dict):continue
                    fun=call['function'];cid=call.get('id');result=next((r for r in rows[index+1:index+101] if isinstance(r,dict) and r.get('role')=='tool' and r.get('tool_call_id')==cid),None)
                    state='returned' if result else 'pending' if panel.busy else 'incomplete'
                    def detail(fun=fun,result=result):
                        return 'Arguments\n'+sanitize(fun.get('arguments',''))+'\n\nResult\n'+(sanitize(result.get('content','')) if result else 'No result recorded yet.')
                    add(index,'tool'+str(n),'tool','Tool · '+str(fun.get('name') or 'tool'),state,detail)
                    if cid:calls[cid]=index
            if role=='tool':owner=calls.get(row.get('tool_call_id'))
            else:owner=index
            if owner is None:continue
            for n,media in enumerate((row.get('attachments',[]) if role=='user' else row.get('media',[])) or []):
                if n>=12:truncated=True;break
                if not isinstance(media,dict) or not isinstance(media.get('path'),str):continue
                name=Path(media['path']).name
                add(owner,'media'+str(index)+'_'+str(n),'media',media.get('name') or name,'available',{'reference':media['path'],'attachment':role=='user','conversation':p['conversation'],'row':row,'entry':media})
        live=getattr(panel,'_native_rich_live',None)
        if live and live['session'] is panel.session and panel.busy and live['reasoning'] and live['index']>=len(rows):
            add(live['index'],'thinking','thinking','Thinking','streaming',lambda:live['reasoning'])
        self.records=records
        self.refs={k:v for k,v in self.refs.items() if k[0]>=start and k[0]<=len(rows)}
        return blocks,truncated
    def execute(self,p,deadline):
        validate_request(p)
        with self.ex.lock:
            self.check(p,deadline);blocks,truncated=self.inventory(p)
            if p['operation']=='rich_index':return self.reply(p,blocks=blocks,truncated=truncated)
            row=self.records.get(p['block'])
            if row is None:raise PermissionError('rich_block_expired')
            kind,source=row
            if p['operation']=='rich_detail':
                if kind=='media':raise ValueError('rich_detail_kind')
                value=sanitize(source());text=clipped(value).encode('utf-8')[:48000].decode('utf-8','ignore')
                live=getattr(self.ex.chat,'_native_rich_live',None)
                cut=len(value)>len(text) or bool(live and live['length']>16000 and any(b['id']==p['block'] and b['status']=='streaming' for b in blocks))
                return self.reply(p,block=p['block'],text=text,truncated=cut)
            if kind!='media':raise ValueError('rich_media_kind')
            self.pending=[x for x in self.pending if not x.done.is_set()]
            if len(self.pending)>=2:raise RuntimeError('rich_media_capacity')
            job=MediaRead(self,p,deadline,source);self.pending.append(job);return job
    def read_media(self,record,p,deadline):
        ex=self.ex;profile=ex.profile
        def check():
            if time.monotonic()>=deadline or not self.current({'binding':p['binding'],'conversation':p['conversation']}):raise PermissionError('rich_revoked')
            profile.check()
            if not self.record_current(record):raise PermissionError('rich_media_record_changed')
        check()
        # Resolve only an already-recorded reference. No external URLs/paths from callers.
        path=profile.resolve(record['reference'],hydrate=False)
        import profile_paths
        allowed=['Data/Chat/Attachments/'+record['conversation']] if record['attachment'] else ['Outputs','User Folder','Data/Chat/Recordings']
        roots=[profile_paths.private_path(ex.root,x,context=profile.identity,hydrate=False) for x in allowed]
        if not any(path.is_relative_to(r) for r in roots):raise PermissionError('rich_media_scope')
        path=profile.resolve(record['reference'],hydrate=True);check()
        profile_paths._contained(ex.root,path)
        before=path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or getattr(before,'st_file_attributes',0)&0x400:raise PermissionError('rich_media_link')
        if before.st_size>LIMIT:raise ValueError('rich_media_too_large_20_MiB')
        identity=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
        # Windows path stat and fstat can expose different ctime meanings
        # (creation versus change time). Compare the common file identity
        # across APIs, then retain each API's full before/after change check.
        same_file=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
        if p['offset']>before.st_size:raise ValueError('rich_media_offset')
        with path.open('rb') as stream:
            opened=os.fstat(stream.fileno())
            if same_file(opened)!=same_file(before):raise PermissionError('rich_media_replaced')
            head=stream.read(32);mime=media_type(head,path.suffix.lower())
            if mime.startswith('image/'):
                try:
                    stream.seek(0);width,height=image_dimensions(stream.read(262144),mime)
                    if min(width,height)<1 or width*height>20000000 or max(width,height)>16384:mime='application/octet-stream'
                except Exception:mime='application/octet-stream'
            chunk_limit=BATCH_CHUNK if p['operation']=='rich_media_batch' else CHUNK
            if p['operation']=='rich_preview':
                data=b'';mime_preview='application/octet-stream'
                if mime.startswith('image/'):
                    import subprocess
                    python=ex.root/'Runtime/BootstrapPython/python.exe'
                    if not python.is_file():python=ex.root/'Runtime/LinuxPython/run-python'
                    stream.seek(0);raw=stream.read(LIMIT+1);check()
                    try:
                        result=subprocess.run([str(python),'-I','-B',str(ex.root/'ControlCenter/native_thumbnail.py')],
                            input=raw,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                            timeout=max(.05,min(3,deadline-time.monotonic()-.1)),
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=ex.root)
                        if result.returncode==0 and 0<len(result.stdout)<=CHUNK and result.stdout.startswith(b'\xff\xd8\xff'):
                            data=result.stdout;mime_preview='image/jpeg'
                    except (OSError,subprocess.TimeoutExpired):pass
                    del raw
            else:
                stream.seek(p['offset']);data=stream.read(min(chunk_limit,before.st_size-p['offset']))
            if identity(os.fstat(stream.fileno()))!=identity(opened):raise PermissionError('rich_media_changed')
        check();profile_paths._contained(ex.root,path)
        if identity(path.lstat())!=identity(before):raise PermissionError('rich_media_changed')
        name=re.sub(r'[/\\:\x00-\x1f]','_',path.name)[:160] or 'download'
        if p['operation']=='rich_preview':
            return {'block':p['block'],'offset':0,'next':len(data),'size':len(data),'mime':mime_preview,
                    'name':'preview.jpg','data':base64.b64encode(data).decode('ascii'),'eof':True,
                    'identity':opaque(*identity(before),*identity(opened),'preview')}
        return {'block':p['block'],'offset':p['offset'],'next':p['offset']+len(data),'size':before.st_size,'mime':mime,'name':name,
                'data':base64.b64encode(data).decode('ascii'),'eof':p['offset']+len(data)==before.st_size,'identity':opaque(*identity(before),*identity(opened))}

def media_type(h,ext):
    if h.startswith(b'\x89PNG\r\n\x1a\n') and ext=='.png':return 'image/png'
    if h.startswith(b'\xff\xd8\xff') and ext in ('.jpg','.jpeg'):return 'image/jpeg'
    if h[:6] in (b'GIF87a',b'GIF89a') and ext=='.gif':return 'image/gif'
    if h[:4]==b'RIFF' and h[8:12]==b'WEBP' and ext=='.webp':return 'image/webp'
    if h[:4]==b'RIFF' and h[8:12]==b'WAVE' and ext=='.wav':return 'audio/wav'
    if (h[:3]==b'ID3' or len(h)>1 and h[0]==255 and h[1]&224==224) and ext=='.mp3':return 'audio/mpeg'
    if h[:4]==b'OggS' and ext in ('.ogg','.opus'):return 'audio/ogg'
    if h[:4]==b'fLaC' and ext=='.flac':return 'audio/flac'
    if h[4:8]==b'ftyp' and ext in ('.mp4','.m4v','.mov'):return 'video/mp4'
    if h[:4]==b'\x1aE\xdf\xa3' and ext=='.webm':return 'video/webm'
    # Includes SVG/HTML and unknown/mismatched media: download only, never embed.
    return 'application/octet-stream'

def image_dimensions(h,mime):
    """Bounded header inspection without an image decoder or new dependency."""
    if mime=='image/png':return int.from_bytes(h[16:20],'big'),int.from_bytes(h[20:24],'big')
    if mime=='image/gif':return int.from_bytes(h[6:8],'little'),int.from_bytes(h[8:10],'little')
    if mime=='image/webp':
        if h[12:16]==b'VP8X':return 1+int.from_bytes(h[24:27],'little'),1+int.from_bytes(h[27:30],'little')
        if h[12:16]==b'VP8 ' and h[23:26]==b'\x9d\x01\x2a':return int.from_bytes(h[26:28],'little')&16383,int.from_bytes(h[28:30],'little')&16383
        if h[12:16]==b'VP8L' and h[20]==47:
            n=int.from_bytes(h[21:25],'little');return (n&16383)+1,((n>>14)&16383)+1
    if mime=='image/jpeg':
        i=2
        while i+9<=len(h):
            if h[i]!=255:raise ValueError('jpeg_marker')
            while i<len(h) and h[i]==255:i+=1
            marker=h[i];i+=1
            if marker in (0xD8,0xD9,0x01) or 0xD0<=marker<=0xD7:continue
            length=int.from_bytes(h[i:i+2],'big')
            if length<2:break
            if marker in (0xC0,0xC1,0xC2):return int.from_bytes(h[i+5:i+7],'big'),int.from_bytes(h[i+3:i+5],'big')
            i+=length
    raise ValueError('image_header_unavailable')
