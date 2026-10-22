"""Bounded RAM transfer grants; no browser-controlled paths or public plaintext."""
import base64
import hashlib
import io
import os
from pathlib import Path
import queue
import threading
import time
import uuid

MAX_FILE=20*1024*1024
MAX_TOTAL=40*1024*1024


class Transfers:
    upload_protocol=2
    def __init__(self,controller):
        self.controller=controller;self.rows={};self.completed=queue.Queue(8)
        self.exports=queue.Queue(2);self.export_paths=set()
        self.timer=controller.app.after(100,self.poll)

    def clear(self):
        for row in self.rows.values():row['buffer'].close()
        self.rows.clear()
        from native_export_grants import discard
        for path in self.export_paths:discard(path)
        self.export_paths.clear()

    def expire(self):
        now=time.monotonic()
        for key in [k for k,r in self.rows.items() if r['expires']<=now]:
            self.rows.pop(key)['buffer'].close()

    def poll(self):
        c=self.controller
        if c.closed:return
        try:
            c.current();self.expire()
            for _ in range(2):
                try:job=self.exports.get_nowait()
                except queue.Empty:break
                viewer,binding,marker,name,data,path=job
                self.export_paths.discard(path)
                if c.current()[0]!=binding or c.virtual is None or c.virtual['identity']!=marker:continue
                key=uuid.uuid4().hex
                self.rows[key]={'viewer':viewer,'binding':binding,'form':None,'pending_form':marker,'size':len(data),
                    'name':name,'mime':'text/markdown' if name.endswith('.md') else 'application/zip',
                    'buffer':io.BytesIO(data),'offset':len(data),'hash':hashlib.sha256(data),'download':True,
                    'committed':True,'expires':time.monotonic()+120}
                c.virtual['nodes'].insert(0,{'id':'export_download','kind':'download','label':'Download verified export',
                    'enabled':True,'file':key,'name':name,'mime':self.rows[key]['mime']})
            for _ in range(8):
                try:done=self.completed.get_nowait()
                except queue.Empty:break
                panel,request,profile,result=done
                try:
                    profile.check();panel._check_login()
                    if getattr(panel,'_attachment_picker_pending',None) is not request:continue
                    panel._attachment_picker_pending=None
                    if request['cancel'].is_set() or not panel.session or panel.session['id']!=request['sid']:continue
                    if isinstance(result,dict):panel.pending_attachments.append(result)
                    else:panel._notice('Attachment','Native upload admission failed. Review before retrying.',kind='error')
                    panel.update_attachment_label()
                except (OSError,RuntimeError,ValueError,PermissionError):pass
        finally:
            if not c.closed:self.timer=c.app.after(100,self.poll)

    def authorized(self,key,viewer):
        self.expire();c=self.controller;binding,account=c.current();r=self.rows.get(key)
        if account['state']!='ready' or r is None or r['viewer']!=viewer or r['binding']!=binding:
            raise PermissionError('file_grant_expired')
        if (viewer,r['form']) not in c.forms:raise PermissionError('file_form_changed')
        return r

    def execute(self,p,deadline):
        c=self.controller;c.check(p,deadline);binding,account=c.current()
        if account['state']!='ready':raise PermissionError('file_account_required')
        self.expire();op=p['operation']
        if op=='file_begin':
            form=c.forms.get((p['viewer'],p['form']))
            if form is None or not form['fields'].get(p['field'],{}).get('file'):raise PermissionError('file_field_required')
            # Revalidate current modal/structure without renewing authority.
            if c.describe(p['viewer'],form['page'])['form']!=p['form']:raise PermissionError('file_form_changed')
            signature=hashlib.sha256(__import__('json').dumps(p,sort_keys=True).encode()).hexdigest()
            for key,r in self.rows.items():
                if r.get('request')==p['request_id']:
                    if r['signature']!=signature:raise PermissionError('file_request_reused')
                    return c.reply(p,transfer=key,offset=r['offset'])
            if len(self.rows)>=4 or sum(r['size'] for r in self.rows.values())+MAX_FILE*len(self.export_paths)+p['size']>MAX_TOTAL:raise RuntimeError('transfer_capacity')
            key=uuid.uuid4().hex
            self.rows[key]={'viewer':p['viewer'],'binding':binding,'form':p['form'],'size':p['size'],
                'name':p['name'],'mime':p['mime'],'buffer':io.BytesIO(),'offset':0,'last':None,
                'expires':time.monotonic()+120,'hash':hashlib.sha256(),'committed':False,
                'request':p['request_id'],'signature':signature,'download':False}
            return c.reply(p,transfer=key,offset=0)
        key=p.get('transfer',p.get('file'));r=self.authorized(key,p['viewer'])
        if op in ('file_chunk','file_chunk_v2'):
            if r['committed']:raise PermissionError('file_already_committed')
            data=base64.b64decode(p['data'],validate=True)
            if not 0<len(data)<=(1048576 if op=='file_chunk_v2' and type(p.get('protocol')) is int and p['protocol']==2 else 24576):raise ValueError('file_chunk_limit')
            identity=(p['offset'],len(data),hashlib.sha256(data).hexdigest())
            if r['last']==identity:r['expires']=time.monotonic()+120;return c.reply(p,offset=r['offset'])
            if p['offset']!=r['offset'] or r['offset']+len(data)>r['size']:raise ValueError('file_offset_or_length')
            r['buffer'].write(data);r['hash'].update(data);r['offset']+=len(data);r['last']=identity
            r['expires']=time.monotonic()+120
            return c.reply(p,offset=r['offset'])
        if op=='file_commit':
            if r['download'] or r['offset']!=r['size'] or r['hash'].hexdigest()!=p['sha256']:raise ValueError('file_integrity')
            r['committed']=True;r['expires']=time.monotonic()+120
            return c.reply(p,file=key,size=r['size'],name=r['name'],mime=r['mime'],sha256=r['hash'].hexdigest())
        if op=='file_get':
            if not r['download'] or not r['committed'] or p['offset']>r['size']:raise PermissionError('download_grant_required')
            r['buffer'].seek(p['offset']);data=r['buffer'].read(24576)
            return c.reply(p,file=key,offset=p['offset']+len(data),data=base64.b64encode(data).decode('ascii'),
                eof=p['offset']+len(data)==r['size'],size=r['size'],name=r['name'],mime=r['mime'],sha256=r['hash'].hexdigest())
        raise ValueError('file_operation')

    def grant(self,viewer,form,name,mime,data):
        c=self.controller;binding,account=c.current();self.expire()
        if account['state']!='ready' or (viewer,form) not in c.forms:raise PermissionError('download_account_required')
        if len(data)>MAX_FILE or len(self.rows)>=4 or sum(r['size'] for r in self.rows.values())+len(data)>MAX_TOTAL:raise ValueError('download_limit')
        name=Path(name).name
        if not name or any(x in name for x in ('/', '\\', '\x00', ':')):raise ValueError('download_name')
        key=uuid.uuid4().hex
        self.rows[key]={'viewer':viewer,'binding':binding,'form':form,'size':len(data),'name':name,'mime':mime,
                       'buffer':io.BytesIO(data),'offset':len(data),'hash':hashlib.sha256(data),'download':True,
                       'committed':True,'expires':time.monotonic()+120}
        return key

    def bind_form(self,viewer,root,token):
        for key,row in list(self.rows.items()):
            if isinstance(root,dict) and row.get('pending_form')==root['identity'] and row['viewer']==viewer:
                row['form']=token
            elif row['viewer']==viewer and row['form']!=token:
                self.rows.pop(key)['buffer'].close()

    def export_path(self,name):
        c=self.controller;binding,account=c.current()
        if account['state']!='ready' or c.active is None:raise PermissionError('export_account')
        self.expire()
        if len(self.rows)+len(self.export_paths)>=2:raise RuntimeError('export_capacity')
        name=Path(name).name[:180]
        ex=c.app._portalai_native_exporter;profile=ex.profile;profile.check()
        folder=profile.private('Data/Maintenance/NativeExports');folder.mkdir(parents=True,exist_ok=True)
        suffix=Path(name).suffix
        if suffix not in ('.zip','.md','.txt'):raise ValueError('export_type')
        path=folder/(uuid.uuid4().hex+suffix);marker=uuid.uuid4().hex;viewer=c.active.payload['viewer']
        from native_export_grants import register
        register(c.root,ex.session,path,profile,lambda data:self.exports.put_nowait((viewer,binding,marker,name,data,path)))
        self.export_paths.add(path)
        c.virtual={'identity':marker,'nodes':[
            {'id':'export_progress','kind':'note','label':'Preparing an authenticated export. A download appears only after verification. Maximum 20 MiB; larger exports remain available locally.','enabled':False},
            {'id':'export_close','kind':'button','label':'Close export','enabled':True,'action':'export_close'}],
            'actions':{'export_close':lambda:setattr(c,'virtual',None)}}
        return str(path)

    def attach(self,key,viewer,panel):
        row=self.authorized(key,viewer)
        if not row['committed'] or row['download']:raise PermissionError('committed_upload_required')
        panel._check_login()
        if panel.busy or not panel.session or getattr(panel,'_attachment_picker_pending',None):raise RuntimeError('chat_busy')
        profile=panel.store.profile;profile.check()
        request={'sid':str(panel.session['id']),'cancel':threading.Event()}
        data=row['buffer'].getvalue();name=row['name']
        # No submitted basename is a path component except a validated suffix.
        suffix=Path(name).suffix[:16]
        if any(ch not in '.-_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for ch in suffix):suffix=''
        panel._attachment_picker_pending=request;panel.update_attachment_label()
        def worker():
            path=None;identity=None;result=None
            try:
                from profile_hydration import materialize
                profile.check();panel._check_login()
                if request['cancel'].is_set():raise RuntimeError('cancelled')
                materialize(panel.root,'Data/Chat',recursive=False)
                folder=profile.private('Data/Chat/.native-upload');folder.mkdir(exist_ok=True)
                path=folder/(uuid.uuid4().hex+suffix)
                with path.open('xb') as stream:
                    stat=os.fstat(stream.fileno());identity=(stat.st_dev,stat.st_ino)
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                profile.check();panel._check_login()
                if request['cancel'].is_set():raise RuntimeError('cancelled')
                result=panel.store.copy_attachment(request['sid'],path)
                profile.check()
            except Exception:result=None
            finally:
                if path is not None and identity is not None:
                    try:
                        stat=path.lstat()
                        if not path.is_symlink() and (stat.st_dev,stat.st_ino)==identity:path.unlink()
                    except FileNotFoundError:pass
                self.completed.put((panel,request,profile,result))
        try:panel._thread(target=worker,name='PortalAINativeUpload',daemon=True).start()
        except BaseException:panel._attachment_picker_pending=None;request['cancel'].set();raise
        self.rows.pop(key)['buffer'].close()
