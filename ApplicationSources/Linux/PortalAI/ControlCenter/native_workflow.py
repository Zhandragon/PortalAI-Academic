"""Account-bound typed forms for the existing launcher controls.

Only server-registered widget objects/callbacks are callable. Browser strings
never become Python names, Tk paths, Tcl, executable code or filesystem paths.
All Tk inspection and final admissions run on the existing GUI event thread.
"""
from collections import OrderedDict
import hashlib
import json
import math
import re
from pathlib import Path
import threading
import time
import uuid
import tkinter as tk
from tkinter import ttk

from native_workflow_protocol import validate_request, validate_model, PAGES

PRIORITY={'controls_stop','controls_exit','chat_stop','account_close'}
LOCAL_RECOVERY='Encrypted recovery export requires a verified backup on a different physical drive. Complete that export on the Aoostar, then return to this form. No reset safeguard is bypassed.'

_TK_VARIABLE = re.compile(r'^PY_VAR_?\d+$')

def resolve_tk_value(widget, value):
    """Replace leaked Tk StringVar handles with their local value before UI publication."""
    if not isinstance(value, str) or not _TK_VARIABLE.fullmatch(value):
        return value
    getter = getattr(widget, 'getvar', None)
    if not callable(getter):
        return value
    try:
        resolved = getter(value)
    except (tk.TclError, AttributeError, TypeError):
        return ''
    if isinstance(resolved, (tuple, list)):
        try:
            return str(widget.tk.call('join', resolved, ' '))
        except (tk.TclError, AttributeError, TypeError):
            return ' '.join(map(str, resolved))
    return str(resolved)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()


def exists(widget):
    try:return bool(widget.winfo_exists())
    except (AttributeError,tk.TclError):return False


def enabled(widget):
    if not exists(widget):return False
    try:
        if str(widget.cget('state'))=='disabled':return False
        if hasattr(widget,'instate') and widget.instate(('disabled',)):return False
    except tk.TclError:pass
    return True


def option(widget,key,default=''):
    try:return widget.cget(key)
    except (tk.TclError,AttributeError):return default


class Admission:
    """A bounded GUI callback admission, never a claim that its job succeeded."""
    def __init__(self,controller,payload,deadline,callback):
        self.controller=controller;self.payload=payload;self.deadline=deadline
        self.callback=callback;self.result=None;self.error=False;self.done=False;self.entered=False
        controller.app.after(0,self.run)

    def run(self):
        if self.error:return
        c=self.controller
        try:
            c.check(self.payload,self.deadline)
            self.entered=True
            previous=c.active;c.active=self
            try:self.callback()
            finally:c.active=previous
            self.done=True
        except Exception:
            self.error=True
        # No submitted values (especially passwords) retained by receipts.
        self.callback=None;self.payload={k:v for k,v in self.payload.items() if k!='values'}

    def refuse(self):
        if self.result is None:
            self.error=True;self.callback=None
            self.payload={k:v for k,v in self.payload.items() if k!='values'}

    def poll(self):
        if self.result is not None:return self.result
        if self.error:raise RuntimeError('native_action_failed_or_uncertain; do not replay automatically')
        c=self.controller
        if time.monotonic()>=self.deadline:self.refuse();raise TimeoutError('native_action_expired; do not replay automatically')
        # A real GUI modal is an admitted operation. Its confirmation remains
        # a separate current-form action, including nested Tk wait loops.
        if self.done or (self.entered and c.modal() is not None):
            extra={}
            binding,_=c.current()
            if self.payload.get('binding')=={'view':binding[0],'epoch':binding[1]}:
                page=c.views.get(self.payload['viewer'],{}).get('page','accounts')
                extra['model']=c.describe(self.payload['viewer'],page)
            self.result=c.reply(self.payload,message='GUI action admitted. The form reports its actual result.',**extra)
            return self.result
        return None


class Controller:
    # Set only after the complete action/field inventory passes the activation
    # audit. A source handoff or a partially constructed GUI is not support.
    complete=True
    def __init__(self,app,root,adapter):
        self.app=app;self.root=Path(root).resolve();self.adapter=adapter
        self.thread=threading.get_ident();self.pages={};self.callbacks={};self.chat=None;self.settings=None
        self.context=None;self.active=None;self.forms={};self.receipts=OrderedDict()
        self.authority=None;self.public=(uuid.uuid4().hex,uuid.uuid4().hex);self.serial=0
        self.views={};self.overrides={};self.virtual=None;self.closed=False
        self.tabs={}
        from native_workflow_files import Transfers
        self.files=Transfers(self)
        # Advertise only when both the schema and transfer implementation accept v2.
        import native_workflow_protocol as protocol
        self.file_upload_protocol=2 if getattr(protocol,'UPLOAD_PROTOCOL',None)==2 and getattr(self.files,'upload_protocol',None)==2 else 1
        self.app.bind('<Destroy>',self.destroy,add='+')

    def configure(self,pages,callbacks,chat,settings,context=None):
        if (set(pages)!=PAGES or not {'controls_startup','controls_stop','controls_exit','chat_stop'}<=set(callbacks)
                or any(not callable(row[1]) for row in callbacks.values()) or chat is None or settings is None):
            self.complete=False;self.adapter.publish_endpoint()
            raise RuntimeError('native_action_registration_incomplete')
        self.pages=dict(pages);self.callbacks=dict(callbacks);self.chat=chat;self.settings=settings;self.context=context

    def destroy(self,event):
        if event.widget is self.app:
            self.closed=True;self.files.clear();self.forms.clear();self.receipts.clear()

    def current(self):
        if threading.get_ident()!=self.thread:raise RuntimeError('GUI_thread_required')
        if self.closed:raise PermissionError('closed')
        ex=getattr(self.app,'_portalai_native_exporter',None)
        if ex is not None and ex.allowed(authenticate=True) and ex.mode=='ready':
            identity=(ex.session.user_id,ex.profile.identity,ex.view,ex.epoch)
            state='ready';name=ex.session.username;binding=(ex.view,ex.epoch)
        else:
            gate=getattr(ex,'gate',None)
            state=getattr(ex,'mode','locked')
            if state not in ('locked','switching','closing'):state='locked'
            identity=('public',state,id(getattr(self.app,'_portalai_login_dialog',None)))
            name='';binding=self.public
        if identity!=self.authority:
            self.files.clear();self.forms.clear();self.receipts.clear();self.views.clear();self.overrides.clear()
            self.virtual=None;self.authority=identity
            self.tabs.clear()
            if state!='ready':self.public=(uuid.uuid4().hex,uuid.uuid4().hex);binding=self.public
        return binding,{'state':state,'displayName':name[:160]}

    def retire(self):
        ex=getattr(self.app,'_portalai_native_exporter',None)
        if ex is not None:
            with ex.lock:ex._rotate('locked')
        self.public=(uuid.uuid4().hex,uuid.uuid4().hex);self.authority=None
        self.current()

    def modal(self):
        if self.virtual is not None:return self.virtual
        dialogs=[d for d in getattr(self.app,'_portalai_account_dialogs',()) if not d.closed and exists(d.win)]
        if dialogs:return dialogs[-1].surface.card
        launcher=getattr(self,'launcher_modal',lambda:None)()
        if exists(launcher):return launcher
        if self.chat is not None:
            for key in ('_sheet_overlay','_inline_edit_frame'):
                widget=getattr(self.chat,key,None)
                if exists(widget):return widget
        guard=getattr(self.app,'_portalai_modal_guard',None)
        surface=getattr(guard,'surface',None)
        if surface is not None and exists(surface.card):return surface.card
        # Explicitly constructed internal sheets, not arbitrary OS windows.
        from internal_sheet import InternalSheet
        todo=[self.app];sheets=[]
        while todo:
            w=todo.pop();todo.extend(w.winfo_children())
            if isinstance(w,InternalSheet) and not w.embedded and w.winfo_manager():sheets.append(w)
        return sheets[-1] if sheets else None

    def check(self,payload,deadline):
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or time.monotonic()>=deadline:
            raise TimeoutError('native_action_expired')
        binding,account=self.current()
        if payload.get('operation')!='describe' and payload.get('binding')!={'view':binding[0],'epoch':binding[1]}:
            raise PermissionError('stale_account')
        return account

    @staticmethod
    def reply(payload,**extra):
        return {'accepted':True,'request_id':payload['request_id'],'operation':payload['operation'],**extra}

    def response_current(self,reply):
        if reply.get('operation','').startswith('rich_'):
            reader=getattr(self,'rich',None)
            return reader is not None and reader.current(reply.get('rich',{}))
        model=reply.get('model')
        if model is None:
            if reply.get('operation','').startswith('file_'):
                key=reply.get('file',reply.get('transfer'))
                # Chunk acknowledgements contain no private bytes. Downloads
                # and commits must still belong to the live account at write.
                if key is None:return True
                row=self.files.rows.get(key);ex=getattr(self.app,'_portalai_native_exporter',None)
                return (row is not None and row['expires']>time.monotonic() and ex is not None
                        and row['binding']==(ex.view,ex.epoch) and ex.allowed(authenticate=True))
            return True
        if model['account']['state']=='ready':
            ex=getattr(self.app,'_portalai_native_exporter',None)
            return ex is not None and ex.response_current({'snapshot':model})
        return (model['view'],model['epoch'])==self.public

    def execute(self,payload,deadline):
        if isinstance(payload,dict) and str(payload.get('operation','')).startswith('rich_'):
            from native_rich_chat import Controller as RichChat
            ex=getattr(self.app,'_portalai_native_exporter',None)
            if ex is None:raise PermissionError('rich_account_unavailable')
            if getattr(getattr(self,'rich',None),'ex',None) is not ex:self.rich=RichChat(ex)
            return self.rich.execute(payload,deadline)
        p=validate_request(payload);account=self.check(p,deadline)
        if p['operation']=='describe':return self.reply(p,model=self.describe(p['viewer'],p['page']))
        if p['operation'].startswith('file_'):return self.files.execute(p,deadline)
        key=p['request_id'];signature=digest(p);prior=self.receipts.get(key)
        if prior is not None:
            if prior[0]!=signature:raise PermissionError('request_identity_reused')
            if isinstance(prior[1],Exception):raise RuntimeError('prior_failed_or_uncertain; do not replay automatically')
            return prior[1]
        if len(self.receipts)>=512:
            self.retire();raise PermissionError('receipt_authority_retired; refresh_before_acting')
        # Reserve a tombstone before any field trace, callback or operation.
        self.receipts[key]=(signature,RuntimeError('reserved'))
        form=self.forms.get((p['viewer'],p['form']))
        if form is None:raise PermissionError('form_expired')
        # Refresh structure and real authority before looking up opaque IDs.
        urgent=p['action'] in PRIORITY
        if urgent:
            if form['context']!=self.action_context(form['page']):raise PermissionError('action_context_changed')
            if p['action']=='account_close' and self.modal() is not form['modal']:raise PermissionError('account_form_changed')
        else:
            fresh=self.describe(p['viewer'],form['page'])
            if fresh['form']!=p['form']:raise PermissionError('form_changed')
        # Keep the rendered field baselines. Replacing them with the refresh
        # would hide a concurrent desktop edit from conflict detection.
        action=form['actions'].get(p['action'])
        if action is None:raise PermissionError('action_not_registered')
        if account['state']!='ready' and not form['public']:raise PermissionError('sign_in_required')
        writes=[]
        # Safety/lifecycle controls never commit the form's pending edits.
        for field,value in (() if urgent else p['values'].items()):
            descriptor=form['fields'].get(field)
            if descriptor is None:raise ValueError('field_not_registered')
            writes.append(descriptor['prepare'](value))
        if p['action']=='controls_startup' and self.settings is not None and self.settings.dirty('chat'):
            self.notice('Desktop settings contain pending drafts. Close this notice, review Settings, and explicitly Save settings before Startup. Startup did not save or overwrite those drafts.')
            raise RuntimeError('Desktop settings contain pending drafts. Review and explicitly save Settings before Startup.')
        # Callback captures current objects only, not their browser identities.
        def apply():
            self.check(p,deadline)
            if not urgent and self.modal() is not form['modal']:raise PermissionError('modal_changed')
            if not urgent and self.describe(p['viewer'],form['page'])['form']!=p['form']:
                raise PermissionError('form_changed_before_effect')
            for write in writes:
                self.check(p,deadline);write()
            writes.clear();write=None
            p['values']={}
            self.check(p,deadline)
            if p['action']=='controls_startup' and self.settings is not None and self.settings.dirty('chat'):
                raise RuntimeError('settings_draft_conflict; review Settings before Startup')
            action()
        result=Admission(self,p,deadline,apply)
        self.receipts[key]=(signature,result)
        return result

    def navigate(self,page):
        if self.active is None:return False
        viewer=self.active.payload['viewer'];self.views[viewer]={'page':page,'offset':0}
        self.overrides.pop(viewer,None)
        return True

    def notice(self,message):
        marker=uuid.uuid4().hex
        self.virtual={'identity':marker,'nodes':[
            {'id':'notice','kind':'note','label':message[:1000],'enabled':False},
            {'id':'notice_close','kind':'button','label':'Close','enabled':True,'action':'notice_close'}],
            'actions':{'notice_close':lambda:setattr(self,'virtual',None)}}

    def action_context(self,page):
        if page=='chat' and self.chat is not None:
            return (self.chat.session or {}).get('id'),id(getattr(self.chat,'_session_load_request',None))
        return None

    def select_tab(self,tabs,key):
        if key not in tabs.pages:raise ValueError('tab_not_registered')
        self.tabs[(self.active.payload['viewer'],id(tabs))]=key

    def tree(self,root,viewer):
        # Hidden top-level pages may be read without packing/focus. Inside that
        # root only managed controls participate; hidden conditional actions do
        # not become remotely callable just because they still exist in Tcl.
        pending=[root];count=0
        while pending:
            widget=pending.pop();count+=1
            if count>12000:raise RuntimeError('GUI_inventory_limit')
            tab=getattr(widget,'_portalai_native_tab',None)
            if tab is not None:
                owner,key=tab
                if self.tabs.get((viewer,id(owner)),owner.selected)!=key:continue
            elif widget is not root and not widget.winfo_manager():continue
            yield widget
            pending.extend(reversed(widget.winfo_children()))

    def describe(self,viewer,page):
        binding,account=self.current();self.files.expire()
        modal=self.modal()
        if account['state']!='ready':
            dialogs=[d for d in getattr(self.app,'_portalai_account_dialogs',()) if not d.closed]
            # The ordinary startup/sign-in/recovery stack alone is public.
            public=bool(dialogs and any(getattr(d.surface,'startup',False) or getattr(d,'native_public_recovery',False) for d in dialogs))
            root=modal if public else None
        else:public=False;root=modal or self.pages.get(page)
        selection=self.views.setdefault(viewer,{'page':page,'offset':0})
        if selection['page']!=page:selection.update(page=page,offset=0);self.overrides.pop(viewer,None)
        override=self.overrides.get(viewer)
        if modal is None and override is not None and exists(override):root=override
        nodes=[];fields={};actions={};structure=[]
        def node(kind,label,*,key=None,**extra):
            ident=key or 'n'+hashlib.sha256(str((id(root),len(nodes),kind)).encode()).hexdigest()[:24]
            label=resolve_tk_value(root,str(label))
            if isinstance(extra.get('value'),str):extra['value']=resolve_tk_value(root,extra['value'])
            if kind=='select' and isinstance(extra.get('options'),(list,tuple)):
                extra['options']=[{**item,'label':resolve_tk_value(root,str(item.get('label','')))}
                                  if isinstance(item,dict) else item for item in extra['options']]
            n={'id':ident,'kind':kind,'label':str(label)[:1000],'enabled':True,**extra}
            nodes.append(n);return ident
        def button(label,callback,key=None,available=True):
            ident=key or 'a'+hashlib.sha256(str((id(root),len(nodes),label)).encode()).hexdigest()[:24]
            node('button',label,key=ident,action=ident,enabled=available)
            if available:actions[ident]=callback
        def move(delta):
            selection['offset']=max(0,selection['offset']+delta)
        history = self.chat is not None and root is self.chat.history_pane and modal is None and override is root
        if page=='chat' and modal is None and account['state']=='ready' and not history and 'chat_history' in self.callbacks:
            label,callback,_=self.callbacks['chat_history'];button(label,callback,key='chat_history')
        if history:
            from native_history import render
            render(self,node,button,fields,structure,viewer)
        elif isinstance(root,dict):
            for n in root['nodes']:nodes.append(dict(n))
            fields.update(root.get('fields',{}));actions.update(root['actions']);structure.append(root['identity'])
        elif root is not None:
            self.widgets(root,node,button,fields,actions,structure,viewer)
        if root is None:
            node('note','Wait for the ordinary PortalAI account screen or normal shutdown to finish.',enabled=False)
        if account['state']=='ready' and modal is None:
            for ident,(label,callback,pages) in self.callbacks.items():
                if page in pages and ident!='chat_history' and (not history or ident=='chat_stop'):button(label,callback,key=ident)
            if page=='chat' and not history:self.chat_controls(node,button,fields,actions,viewer)
            if page=='settings' and self.settings is not None:
                for key,widget in self.settings.tabs.pages.items():
                    button('Open '+str(self.settings.tabs.buttons[key].cget('text')),
                           lambda w=widget:self.overrides.__setitem__(viewer,w))
        if account['state']=='ready' and modal is not None:
            # Retain Stop/Exit behind a modal only when the actual account gate
            # permits it. Never provide an alternate force shutdown path.
            for ident in ('controls_stop','controls_exit','chat_stop'):
                if ident in self.callbacks:
                    label,callback,_=self.callbacks[ident];button(label,callback,key=ident)
        if public and getattr(self.app,'_portalai_login_dialog',None) is not None:
            dialog=self.app._portalai_login_dialog
            # Invoke the real close button/protocol, which refuses while busy.
            button('Close account screen',lambda:self.app.tk.call(self.app.protocol('WM_DELETE_WINDOW')),
                   key='account_close',available=not dialog.busy)
        elif modal is not None:
            dialogs=[d for d in getattr(self.app,'_portalai_account_dialogs',()) if not d.closed]
            if dialogs and modal is dialogs[-1].surface.card:
                dialog=dialogs[-1]
                button('Close account form',dialog.surface.on_close,key='account_close',available=not dialog.busy)
        # Structural fingerprints exclude ordinary changing values/status.
        signature=digest([binding,page,self.action_context(page),id(modal),id(root),structure,
                          [(n['id'],n['kind'],n['enabled'],n.get('action'),n.get('options')) for n in nodes]])
        previous=next((f for (v,_),f in self.forms.items() if v==viewer and f['signature']==signature),None)
        token=previous['token'] if previous else uuid.uuid4().hex
        # Bound the node/UTF-8 budget with actual paging, not silent truncation.
        chunks=[];chunk=[];budget=0
        for n in nodes:
            amount=len(json.dumps(n,ensure_ascii=False).encode())
            if amount>52000:raise RuntimeError('Control requires a paged adapter')
            if chunk and (len(chunk)>=75 or budget+amount>52000):chunks.append(chunk);chunk=[];budget=0
            chunk.append(n);budget+=amount
        chunks.append(chunk)
        index=min(selection['offset'],len(chunks)-1);selection['offset']=index
        visible=list(chunks[index]);allfields=fields;visiblefields={n['id'] for n in visible}
        actions={k:v for k,v in actions.items() if k in {n.get('action') for n in visible} | {n.get('on_change') for n in visible}}
        fields={k:v for k,v in allfields.items() if k in visiblefields}
        for label,delta,show in [('Previous controls',-1,index>0),('Next controls',1,index+1<len(chunks))]:
            if show:
                ident='page_previous' if delta<0 else 'page_next'
                visible.append({'id':ident,'kind':'button','label':label,'enabled':True,'action':ident})
                actions[ident]=lambda d=delta:move(d)
        # The visible slice is part of form identity, including pagination.
        signature=digest([signature,index])
        previous=next((f for (v,_),f in self.forms.items() if v==viewer and f['signature']==signature),None)
        token=previous['token'] if previous else uuid.uuid4().hex
        for key in [key for key in self.forms if key[0]==viewer]:self.forms.pop(key)
        if len(self.forms)>=16:self.retire();raise RuntimeError('native_view_capacity; refresh')
        self.forms[(viewer,token)]={'token':token,'signature':signature,'page':page,'modal':modal,
            'public':public,'actions':actions,'fields':fields,'at':time.monotonic(),'context':self.action_context(page)}
        self.files.bind_form(viewer,root,token)
        self.serial+=1
        model={'protocol':1,'view':binding[0],'epoch':binding[1],'form':token,'revision':self.serial,
            'page':page,'title':'PortalAI — '+('Account' if public else page.title()),'account':account,
            'nodes':visible,'message':f'Controls {index+1} of {len(chunks)}. Operations retain their ordinary GUI checks.','truncated':False}
        validate_model(model)
        return model

    def widgets(self,root,node,button,fields,actions,structure,viewer):
        label='';read_offsets=self.views[viewer].setdefault('read_offsets',{})
        for w in self.tree(root,viewer):
            cls=w.winfo_class();wid='w'+hashlib.sha256(str(w).encode()).hexdigest()[:24]
            text=str(option(w,'text',''))
            if cls in ('Label','TLabel','Message') and text:
                label=text
                offset=read_offsets.get(wid,0)
                for i in range(offset,min(len(text),offset+8000),1000):node('note',text[i:i+1000],enabled=False)
                if offset:button('Previous label text',lambda k=wid,o=offset:read_offsets.__setitem__(k,max(0,o-8000)))
                if offset+8000<len(text):button('Next label text',lambda k=wid,o=offset:read_offsets.__setitem__(k,o+8000))
                if w.bind('<Button-1>'):
                    button('Open / toggle '+text[:120],lambda w=w:w.event_generate('<Button-1>',when='now'),key=wid+'_click')
            elif cls in ('Button','TButton'):
                if not option(w,'command'):continue
                if w in getattr(self,'fixed_widgets',{}):continue
                structure.append((wid,str(option(w,'command'))))
                button(text or 'Action',lambda w=w:self.invoke_widget(w),key=wid,available=enabled(w))
            elif cls in ('Radiobutton','TRadiobutton'):
                selected=str(w.getvar(str(w.cget('variable'))))==str(w.cget('value'))
                button((text or label)+(' (selected)' if selected else ''),lambda w=w:self.invoke_widget(w),key=wid,available=enabled(w))
            elif w.__class__.__module__=='help_topics' and w.__class__.__name__=='TopicList':
                for index,title in enumerate(w.items):
                    button(title,lambda index=index,w=w:w._select(index),key=wid+'_'+str(index))
            elif cls in ('Entry','TEntry','TCombobox','Spinbox','TSpinbox','Text','Scale','TScale','Checkbutton','TCheckbutton','Radiobutton','TRadiobutton','Listbox','Treeview'):
                self.field(w,cls,wid,text or label or 'Value',node,button,fields,actions,structure,read_offsets)

    @staticmethod
    def invoke_widget(widget):
        if not enabled(widget):raise PermissionError('control_disabled')
        widget.invoke()

    def field(self,w,cls,wid,label,node,button,fields,actions,structure,offsets):
        can=enabled(w);secret=bool(option(w,'show'))
        istext=cls=='Text';readonly=str(option(w,'state')) in ('disabled','readonly') and cls!='TCombobox'
        get=None;setvalue=None;choices=None;event=None
        if cls in ('Checkbutton','TCheckbutton','Radiobutton','TRadiobutton'):
            variable=str(option(w,'variable'))
            on=str(option(w,'onvalue','1')) if 'Radiobutton' not in cls else str(option(w,'value'))
            get=lambda:str(w.getvar(variable))==on
            def setvalue(v):
                if get()!=v:w.invoke()
            kind='checkbox';convert=lambda v:v if type(v) is bool else self.invalid()
        elif cls in ('Listbox','Treeview'):
            items=list(w.get_children('')) if cls=='Treeview' else list(range(w.size()))
            start=offsets.get(wid,0);start=min(start,max(0,len(items)-1));page=items[start:start+20]
            selected=set(w.selection()) if cls=='Treeview' else set(w.curselection())
            structure.append((wid,digest(items),sorted(selected,key=str)))
            structure.append((wid,[(i,w.item(i) if cls=='Treeview' else str(w.get(i))) for i in page]))
            for i in page:
                vals=w.item(i) if cls=='Treeview' else None
                title=(' | '.join([str(vals.get('text','')),*map(str,vals.get('values',()))]) if vals else str(w.get(i)))
                fid=wid+'_'+str(start+page.index(i));base=i in selected
                node('checkbox',title,key=fid,value=base,enabled=can,on_change=fid+'_change')
                def prepare(v,i=i,base=base):
                    if type(v) is not bool or not enabled(w):raise ValueError('selection_value')
                    def write():
                        if cls=='Treeview':
                            if v and str(w.cget('selectmode'))=='browse':w.selection_set(())
                            (w.selection_add if v else w.selection_remove)(i)
                            if v:w.focus(i)
                            w.event_generate('<<TreeviewSelect>>',when='now')
                        else:
                            if v and str(w.cget('selectmode')) in ('single','browse'):w.selection_clear(0,'end')
                            (w.selection_set if v else w.selection_clear)(i)
                            w.event_generate('<<ListboxSelect>>',when='now')
                    return write if v!=base else lambda:None
                fields[fid]={'prepare':prepare}
                actions[fid+'_change']=lambda:None
                if self.chat is not None and w is getattr(self.chat,'session_list',None):
                    def open_one(i=i):
                        w.selection_clear(0,'end');w.selection_set(i)
                        w.event_generate('<<ListboxSelect>>',when='now')
                    button('Open chat · '+title,open_one,key=fid+'_open',available=can and not self.chat.busy and not self.chat.pending_attachments)
            if start:button('Previous list items',lambda:offsets.__setitem__(wid,max(0,start-20)))
            if start+20<len(items):button('Next list items',lambda:offsets.__setitem__(wid,start+20))
            if not items:node('note',label+' — no items',enabled=False)
            return
        elif cls=='TCombobox':
            choices=[str(resolve_tk_value(w,str(value))) for value in w.cget('values')];start=offsets.get(wid,0)
            choices=choices[start:start+80]
            lookup={str(i):v for i,v in enumerate(choices)}
            get=lambda:str(w.get());setvalue=lambda v:w.set(v)
            raw_current=get();current=str(resolve_tk_value(w,raw_current))
            selected=next((k for k,v in lookup.items() if v==current),'')
            opts=[{'value':k,'label':v[:300]} for k,v in lookup.items()]
            node('select',label,key=wid,value=selected,options=opts,enabled=can,on_change=wid+'_change')
            baseline=digest(raw_current)
            def prepare(v):
                if v==selected:return lambda:None
                if v not in lookup or not enabled(w):raise ValueError('choice_not_registered')
                if digest(get())!=baseline:raise RuntimeError('desktop_draft_conflict')
                def write():setvalue(lookup[v]);w.event_generate('<<ComboboxSelected>>',when='now')
                return write
            fields[wid]={'prepare':prepare};actions[wid+'_change']=lambda:None
            structure.append((wid,list(lookup.values()),current))
            if start:button('Previous choices',lambda:offsets.__setitem__(wid,max(0,start-80)))
            if start+80<len(w.cget('values')):button('Next choices',lambda:offsets.__setitem__(wid,start+80))
            return
        elif cls in ('Scale','TScale'):
            get=lambda:float(w.get());setvalue=lambda v:w.set(v);kind='number'
            low=float(w.cget('from'));high=float(w.cget('to'))
            convert=lambda v:float(v) if type(v) in (float,int) and math.isfinite(v) and min(low,high)<=v<=max(low,high) else self.invalid()
        elif istext:
            counted=w.count('1.0','end-1c','chars')
            total=int(counted[0]) if counted else 0;start=offsets.get(wid,0)
            value=w.get(f'1.0+{start}c',f'1.0+{start+8000}c')
            if total>8000:
                node('note',label+f' — characters {start+1}–{min(total,start+8000)} of {total}',enabled=False)
                if start:button('Previous text',lambda:offsets.__setitem__(wid,max(0,start-8000)))
                if start+8000<total:button('Next text',lambda:offsets.__setitem__(wid,start+8000))
            get=lambda:w.get(f'1.0+{start}c',f'1.0+{start+8000}c')
            def setvalue(v):w.delete(f'1.0+{start}c',f'1.0+{start+len(value)}c');w.insert(f'1.0+{start}c',v)
            kind='textarea';convert=lambda v:v if isinstance(v,str) and len(v)<=8000 else self.invalid()
            if getattr(w,'_portalai_native_selection',False):
                structure.append((wid,digest(w.get('1.0','end-1c'))))
                selection={'start':0,'end':0}
                for which in ('start','end'):
                    sid=wid+'_selection_'+which
                    node('number','Selection '+which+' (character offset)',key=sid,value=0,min=0,max=total,step=1)
                    def prepare_selection(v,which=which):
                        if type(v) is not int or not 0<=v<=total:raise ValueError('selection_range')
                        return lambda:selection.__setitem__(which,v)
                    fields[sid]={'prepare':prepare_selection}
                def apply_selection():
                    if selection['end']<=selection['start']:raise ValueError('Select a nonempty range')
                    w.tag_remove('sel','1.0','end')
                    w.tag_add('sel',f"1.0+{selection['start']}c",f"1.0+{selection['end']}c")
                button('Select text range',apply_selection,key=wid+'_select')
        else:
            get=lambda:str(w.get());kind='secret' if secret else 'text'
            def setvalue(v):w.delete(0,'end');w.insert(0,v)
            convert=lambda v:v if isinstance(v,str) and len(v)<=16000 else self.invalid()
        value=get();baseline=digest(value)
        node(kind,label,key=wid,value='' if secret else value,enabled=can and not readonly)
        structure.append((wid,kind,readonly))
        if can and not readonly:
            def prepare(v):
                v=convert(v)
                if not enabled(w):raise PermissionError('field_disabled')
                now=get()
                if secret and not v and now:raise RuntimeError('Enter credentials explicitly in this form')
                if digest(now)!=baseline and v!=now:raise RuntimeError('desktop_draft_conflict')
                if v==now:return lambda:None
                def write():
                    if not enabled(w) or digest(get())!=baseline:raise RuntimeError('desktop_draft_conflict')
                    setvalue(v)
                return write
            fields[wid]={'prepare':prepare}

    @staticmethod
    def invalid():raise ValueError('invalid_field_value')

    def chat_controls(self,node,button,fields,actions,viewer):
        if self.chat is None:return
        # This field uses only opaque transfer grants. The existing store copies
        # it after its normal session/attachment checks; no browser path API.
        fid='chat_attachment'
        node('file','Attach a file (20 MiB maximum)',key=fid,value='',enabled=not self.chat.busy)
        selected={'token':None}
        def prepare(value):
            if not isinstance(value,str):raise ValueError('file_token')
            if not value:return lambda:None
            self.files.authorized(value,viewer)
            return lambda:selected.__setitem__('token',value)
        fields[fid]={'prepare':prepare,'file':True}
        def attach():
            if not selected['token']:raise ValueError('Upload and commit the attachment first')
            self.files.attach(selected['token'],viewer,self.chat)
        button('Add uploaded attachment',attach,key='chat_attach_uploaded',available=not self.chat.busy)


def install_public(app,root,adapter):
    controller=Controller(app,root,adapter);adapter.native_ui=controller
    app._portalai_native_workflow=controller
    from native_workflow_dialogs import install
    install()
    adapter.publish_endpoint()
    return controller


def configure(app,**kwargs):
    controller=getattr(app,'_portalai_native_workflow',None)
    if controller is not None:controller.configure(**kwargs)
    return controller
