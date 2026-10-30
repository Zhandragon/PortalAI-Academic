"""One native Workspace sheet for knowledge, connections, workflows and computer use."""
import json
from pathlib import Path
import queue
import threading
from tkinter import ttk,filedialog
from internal_sheet import InternalSheet
from rounded_text import RoundedText
from account_permissions import require_user,require_admin,can_admin
from capability_tools import guard,workflow_store


def show_workspace(parent,root,colors,*,session=None,jobs=None,runtime=None):
    require_user(root,session)
    if jobs is None or not callable(getattr(jobs,'thread',None)):raise RuntimeError('Workspace requires tracked background jobs')
    if runtime is None:
        from native_chat import ToolRuntime
        runtime=ToolRuntime(Path(root),{})
        current=session() if callable(session) else session
        if current is not None:runtime.bind_account(current)
    return WorkspacePanel(parent,root,colors,session,jobs,runtime)


class WorkspacePanel(InternalSheet):
    def __init__(self,parent,root,colors,session,jobs,runtime):
        super().__init__(parent,'Workspace',colors)
        self.root=Path(root);self.session=session;self.jobs=jobs;self.runtime=runtime
        self.events=queue.Queue();self.cancelled=threading.Event();self.busy=False;self.closed=False
        self.on_close=self.close;self.base_check=guard(runtime)
        self.skin.label(self.content,'Your documents, approved connections and reusable tasks stay with your signed-in account.').pack(fill='x',pady=5)
        nav=self.skin.frame(self.content);nav.pack(fill='x');self.pages={}
        for title in ('Knowledge','Connections','Workflows','Computer'):
            self.skin.button(nav,title,lambda t=title:self.page(t)).pack(side='left',padx=3)
            self.pages[title]=self.skin.frame(self.content)
        self.status=self.skin.label(self.content,'Ready');self.status.pack(fill='x',pady=5)
        self.skin.button(self.heading,'Stop operation',self.stop).pack(side='right',padx=4)
        self.output=self.text(self.content,'',10);self.output.pack(fill='both',expand=True,pady=6)
        self.knowledge_page();self.connections_page();self.workflows_page();self.computer_page()
        self.page('Knowledge');self.after(100,self.poll)

    def check(self):
        self.base_check()
        if self.cancelled.is_set() or self.closed:raise RuntimeError('Workspace operation stopped')

    def admin(self):require_admin(self.root,self.session);self.check()

    def text(self,parent,value,height=7):
        box=RoundedText(parent,height=height,wrap='word',palette=self.skin.colors)
        box.apply_palette(self.skin.colors);box.insert('1.0',value);self.skin.remember(box);return box

    def field(self,parent,label,value=''):
        row=self.skin.frame(parent);row.pack(fill='x',pady=3)
        self.skin.label(row,label).pack(fill='x',anchor='w')
        entry=self.skin.entry(row,value);entry.pack(fill='x',expand=True);return entry

    def buttons(self,parent,items):
        from ui_extensions import ResponsiveFlow
        row=ResponsiveFlow(parent,bg=self.skin.colors['panel'],hgap=4,vgap=4);row.pack(fill='x',pady=5)
        for label,callback in items:row.add(self.skin.button(row,label,lambda fn=callback:self.invoke(fn)))
        return row

    def tree(self,parent,columns):
        frame=self.skin.frame(parent);frame.pack(fill='x',pady=4)
        tree=ttk.Treeview(frame,columns=columns,show='headings',height=4,selectmode='extended')
        for col in columns:tree.heading(col,text=col);tree.column(col,width=160,stretch=True)
        tree.pack(fill='x',expand=True);self.style_tree(tree);return tree

    def selected(self,tree):
        values=tree.selection()
        if len(values)!=1:raise ValueError('Select one record first')
        return values[0]

    def show(self,value):
        text=value if isinstance(value,str) else json.dumps(value,indent=2,ensure_ascii=False)
        self.output.delete('1.0','end');self.output.insert('1.0',text[:100000])

    def invoke(self,fn):
        try:
            if not self.busy:self.base_check=guard(self.runtime);self.cancelled.clear()
            self.check();fn()
        except Exception as exc:self.show(str(exc))

    def page(self,name):
        for frame in self.pages.values():frame.pack_forget()
        self.pages[name].pack(fill='x',before=self.status,pady=6)

    def job(self,work,done=None):
        if self.busy:raise RuntimeError('Wait for the current operation or press Stop')
        # Each explicit new operation captures the current Stop epoch.
        self.base_check=guard(self.runtime);self.cancelled.clear();self.busy=True;self.status.configure(text='Working…')
        def run():
            try:self.check();result=work();self.check();self.events.put((True,result,done))
            except Exception as exc:self.events.put((False,str(exc),None))
        try:self.jobs.thread(target=run,name='PortalAI-Workspace').start()
        except Exception:self.busy=False;raise

    def poll(self):
        if self.closed:return
        try:
            while True:
                ok,result,done=self.events.get_nowait();self.busy=False
                self.status.configure(text='Ready' if ok else 'Stopped or failed; saved results retained')
                self.show(result)
                if ok and done:done(result)
        except queue.Empty:pass
        self.after(100,self.poll)

    def stop(self):
        self.cancelled.set();self.runtime.cancel(cleanup_media=False)
        self.status.configure(text='Stopping; uncertain external effects need review')

    def close(self):
        if self.busy:self.stop()
        self.closed=True;self.destroy()

    def knowledge_page(self):
        from knowledge_base import Knowledge
        self.kb=Knowledge(self.root,self.check);p=self.pages['Knowledge']
        self.skin.label(p,'Import a folder, then Sync. PDF scans and images use local OCR; search uses local semantic and keyword retrieval.').pack(fill='x')
        self.kname=self.field(p,'Collection name');self.kfolder=self.field(p,'Folder')
        self.collections=self.tree(p,('Name','ID'))
        self.query=self.field(p,'Search')
        def browse():
            folder=filedialog.askdirectory(parent=self,title='Choose a document folder')
            if folder:self.kfolder.delete(0,'end');self.kfolder.insert(0,folder)
        def refresh():
            self.collections.delete(*self.collections.get_children())
            for row in self.kb.list():self.collections.insert('','end',iid=row['id'],values=(row['name'],row['id']))
        def add():
            row=self.kb.create(self.kname.get(),self.kfolder.get());refresh();self.collections.selection_set(row['id']);self.show(row)
        def sync():
            cid=self.selected(self.collections);self.job(lambda:self.kb.sync(cid))
        def search():
            query=self.query.get();chosen=self.collections.selection();cid=chosen[0] if len(chosen)==1 else None
            self.job(lambda:self.kb.search(query,cid))
        self.buttons(p,[('Choose folder',browse),('Add collection',add),('Refresh',refresh),('Sync selected',sync),('Search',search)])
        self.invoke(refresh)

    def connections_page(self):
        from mcp_client import Connections
        self.connections=Connections(self.root,self.check);p=self.pages['Connections']
        self.skin.label(p,'Administrator tools. Discover runs the configured server. Select individual tools, then approve access. Secrets stay in this account.').pack(fill='x')
        self.cname=self.field(p,'Connection name')
        self.config=self.text(p,json.dumps({'transport':'stdio','command':['{python}','{root}/Tools/my_mcp_server.py'],'env':{}},indent=2),5);self.config.pack(fill='x')
        self.servers=self.tree(p,('Name','Transport','Enabled'));self.grants=self.tree(p,('Tool','Description'));self.discovered={}
        def refresh():
            self.servers.delete(*self.servers.get_children())
            for row in self.connections.list():self.servers.insert('','end',iid=row['id'],values=(row['name'],row['transport'],row['enabled']))
        def create():
            self.admin();cfg=json.loads(self.config.get('1.0','end'));row=self.connections.create(self.cname.get(),**cfg)
            refresh();self.servers.selection_set(row['id']);self.show('Saved disabled. Discover its tools before granting access.')
        def discovered(value):
            cid,rows=value;self.discovered={r['name']:r for r in rows};self.discovered_server=cid;self.grants.delete(*self.grants.get_children())
            for i,row in enumerate(rows):self.grants.insert('','end',iid=str(i),values=(row['name'],str(row.get('description',''))[:300]))
        def discover():
            self.admin();cid=self.selected(self.servers);self.job(lambda:(cid,self.connections.discover(cid)),discovered)
        def approve():
            self.admin();cid=self.selected(self.servers)
            if cid!=getattr(self,'discovered_server',None):raise ValueError('Discover the selected connection first')
            rows=[self.discovered[self.grants.item(i,'values')[0]] for i in self.grants.selection()]
            if not rows:raise ValueError('Select at least one tool to approve')
            self.connections.grant(cid,rows);refresh();self.show('Only the selected tool schemas are now approved for this account.')
        def disable():
            self.admin();cid=self.selected(self.servers);self.connections.grant(cid,[],enabled=False);refresh()
        self.buttons(p,[('Create disabled',create),('Refresh',refresh),('Discover',discover),('Approve selected tools',approve),('Disable',disable)])
        self.receipt=self.field(p,'Uncertain receipt ID')
        def receipts():self.admin();self.show([r for r in self.connections.receipts() if r['state']=='pending'])
        def resolve(decision):self.admin();self.connections.resolve(self.receipt.get().strip(),decision);self.show('Review saved. No action was executed.')
        self.buttons(p,[('Uncertain calls',receipts),('Confirm completed',lambda:resolve('confirmed')),('Allow one reviewed retry',lambda:resolve('allow_retry'))])
        if can_admin(self.root,self.session):self.invoke(refresh)

    def workflows_page(self):
        from workflows import EXAMPLE
        self.flows=workflow_store(self.runtime,self.check);p=self.pages['Workflows']
        self.skin.label(p,'Saved steps with explicit inputs, forward conditions and approval points. Edit the example JSON; references preserve their data type.').pack(fill='x')
        self.templates=self.tree(p,('Name','ID'));self.editing=None
        self.editor=self.text(p,json.dumps(EXAMPLE,indent=2),9);self.editor.pack(fill='x')
        self.inputs=self.field(p,'Inputs JSON','{"question":"What do these documents say?"}')
        def refresh():
            self.templates.delete(*self.templates.get_children())
            for row in self.flows.templates():self.templates.insert('','end',iid=row['id'],values=(row['name'],row['id']))
        def load():
            self.admin();self.editing=self.selected(self.templates);row=self.flows.template(self.editing)
            self.editor.delete('1.0','end');self.editor.insert('1.0',json.dumps(row,indent=2))
        def save(new=False):
            self.admin();row=self.flows.put(json.loads(self.editor.get('1.0','end')),None if new else self.editing)
            self.editing=row['id'];refresh();self.templates.selection_set(row['id']);self.show(row)
        def run():
            self.admin();row=self.flows.start(self.selected(self.templates),json.loads(self.inputs.get()));self.run_id.delete(0,'end');self.run_id.insert(0,row['id'])
            self.job(lambda:self.flows.advance(row['id']))
        self.buttons(p,[('Refresh',refresh),('Load selected',load),('Save',save),('Save as new',lambda:save(True)),('Run selected',run)])
        self.run_id=self.field(p,'Run ID')
        self.review_result=self.field(p,'Reviewed result JSON','null')
        def status():self.admin();self.show(self.flows.run(self.run_id.get().strip()))
        def continue_run():self.admin();rid=self.run_id.get().strip();self.job(lambda:self.flows.advance(rid))
        def approve():self.admin();self.show(self.flows.approve(self.run_id.get().strip()))
        def review(decision):self.admin();self.show(self.flows.review(self.run_id.get().strip(),decision,json.loads(self.review_result.get())))
        def runs():self.admin();self.show([{'id':r['id'],'name':r['template']['name'],'state':r['state'],'cursor':r['cursor']} for r in self.flows.runs()])
        self.buttons(p,[('Saved runs',runs),('Inspect run',status),('Approve waiting step',approve),('Continue',continue_run),('Confirm uncertain result',lambda:review('confirmed')),('Allow reviewed retry',lambda:review('allow_retry'))])
        if can_admin(self.root,self.session):self.invoke(refresh)

    def computer_page(self):
        from desktop_control import desktop,revoke
        p=self.pages['Computer']
        self.skin.label(p,'Windows: allow a visible window for this login, then ask a vision-capable chat model to operate it. Stop or Ctrl+Alt+Pause revokes input. Screenshots stay in memory. Bring the target forward if Windows refuses focus.').pack(fill='x')
        self.windows=self.tree(p,('Window','Title','Allowed'))
        def refresh():
            self.admin();rows=desktop(self.root).windows();self.windows.delete(*self.windows.get_children())
            for row in rows:self.windows.insert('','end',iid=str(row['window']),values=(row['window'],row['title'],row['allowed']))
        def allow():
            self.admin();row=desktop(self.root).grant(int(self.selected(self.windows)));refresh();self.show({'allowed_for_this_login':row})
        def clear():self.admin();revoke(self.root);refresh();self.show('Desktop access revoked.')
        self.buttons(p,[('Refresh windows',refresh),('Allow selected window',allow),('Revoke all',clear)])
