"""Workspace controls for structured output, API grants and artifact revisions."""
import json
from account_permissions import require_admin,can_admin
from capability_tools import guard

EXAMPLE_SCHEMA={'type':'object','properties':{'summary':{'type':'string'},'items':{'type':'array','items':{'type':'string'},'maxItems':8}},'required':['summary','items']}
EXAMPLE_HTML='<!doctype html><h1>My artifact</h1><button onclick="this.textContent=\'It works\'">Try me</button>'


class IntegrationUI:
    def structured_page(self):
        p=self.pages['Structured']
        self.skin.label(p,'Start a local chat model, then extract JSON using a supported schema. Invalid or truncated results are rejected.').pack(fill='x')
        question=self.field(p,'Question','Summarize the source and list its key points.')
        context=self.text(p,'Paste source text here.',3);context.pack(fill='x')
        schema=self.text(p,json.dumps(EXAMPLE_SCHEMA,indent=2),5);schema.pack(fill='x')
        def generate():
            from structured_generation import generate
            q=question.get();c=context.get('1.0','end');s=json.loads(schema.get('1.0','end'))
            self.job(lambda:generate(self.root,q,c,s,self.check))
        self.buttons(p,[('Generate JSON',generate)])

    def api_page(self):
        from application_api import APIState,SCOPES,AGENT_TOOLS
        p=self.pages['API'];self.application_api=None
        self.skin.label(p,'Administrator: opt-in loopback API v1, active while Workspace is open. Stop/sign-out closes it. Plain chat remains available; agent:execute enables Nice’s harness only with the individual tool grants below.').pack(fill='x')
        endpoint=self.field(p,'Live API URL','Stopped')
        name=self.field(p,'Token name','My application')
        scopes=self.field(p,'Scopes (comma-separated)','chats:read,chats:write,artifacts:read,artifacts:write,structured:generate')
        hours=self.field(p,'Token lifetime in hours (1–720)','24')
        tool_grants=self.field(p,'Agent tool grants (comma-separated; empty grants no external tools)','')
        tokens=self.tree(p,('Name','Scopes','Revoked'));state=APIState(self.root,self.admin)
        def refresh():
            self.admin();tokens.delete(*tokens.get_children())
            for r in state.tokens():tokens.insert('','end',iid=r['id'],values=(r['name'],', '.join(r['scopes']),r['revoked']))
        def start():
            self.admin()
            if self.application_api:self.application_api.close()
            from application_api_runtime import ApplicationAPI
            captured=guard(self.runtime)
            def check():
                captured();require_admin(self.root,self.session)
                if self.closed:raise RuntimeError('Workspace closed')
            self.application_api=ApplicationAPI(self.runtime,self.jobs,check)
            result=self.application_api.start();endpoint.delete(0,'end');endpoint.insert(0,result['base_url']);self.show(result)
        def stop():
            if self.application_api:self.application_api.close();self.application_api=None
            endpoint.delete(0,'end');endpoint.insert(0,'Stopped');self.show('API stopped; saved records retained.')
        def issue():
            self.admin();result=state.issue(name.get(),[s.strip() for s in scopes.get().split(',')],int(hours.get()),tools=[s.strip() for s in tool_grants.get().split(',') if s.strip()]);refresh();self.show(result)
        def revoke():self.admin();state.revoke(self.selected(tokens));refresh();self.show('Token revoked; its jobs stop at their next cancellation check.')
        self.buttons(p,[('Start API',start),('Stop API',stop),('Issue token',issue),('Refresh tokens',refresh),('Revoke selected',revoke),('Supported scopes',lambda:self.show(sorted(SCOPES))),('Available agent tools',lambda:self.show(sorted(AGENT_TOOLS)))])
        receipt=self.field(p,'Uncertain receipt ID');result=self.field(p,'Reviewed result JSON','null')
        def pending():self.admin();self.show(state.pending())
        def review(decision):self.admin();self.show(state.resolve(receipt.get().strip(),decision,json.loads(result.get())))
        self.buttons(p,[('Uncertain requests',pending),('Confirm result',lambda:review('confirmed')),('Allow reviewed retry',lambda:review('allow_retry'))])
        if can_admin(self.root,self.session):self.invoke(refresh)

    def artifacts_page(self):
        from artifacts import Artifacts
        p=self.pages['Artifacts'];self.preview=None;store=Artifacts(self.root,self.check)
        self.artifact_id=None;self.artifact_head=None
        self.skin.label(p,'HTML, SVG, chart JSON, Markdown, Mermaid or React. Preview stays offline in an isolated browser. React: export a default component or define App; React/ReactDOM and your reviewed library bundles are available.').pack(fill='x')
        items=self.tree(p,('Title','Kind','Revision'));history=self.tree(p,('Revision','Created'))
        title=self.field(p,'Title','My artifact');kind=self.field(p,'Kind: html, svg, chart, markdown, mermaid or react','html')
        libraries=self.field(p,'Reviewed library IDs (comma-separated; React only)','')
        editor=self.text(p,EXAMPLE_HTML,7);editor.pack(fill='x')
        def refresh():
            items.delete(*items.get_children())
            for r in store.list():items.insert('','end',iid=r['id'],values=(r['title'],r['kind'],r['head']))
        def display(row):
            self.artifact_id=row['artifact'];self.artifact_head=store.metadata(row['artifact'])['head']
            for widget,value in ((title,row['title']),(kind,row['kind']),(libraries,', '.join(pin['id'] for pin in row.get('dependencies',[])))):widget.delete(0,'end');widget.insert(0,value)
            editor.delete('1.0','end');editor.insert('1.0',row['content']);history.delete(*history.get_children())
            for r in store.history(row['artifact']):history.insert('','end',iid=r['id'],values=(r['id'],r['created']))
            history.selection_set(row['id']);self.show({'artifact':row['artifact'],'loaded_revision':row['id'],'current_head':self.artifact_head})
        def load():display(store.read(self.selected(items)))
        def revision():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            display(store.read(self.artifact_id,self.selected(history)))
        def save(new=False):
            values=(title.get(),kind.get().strip(),editor.get('1.0','end-1c'));aid=None if new else self.artifact_id;head=None if new else self.artifact_head
            deps=[s.strip() for s in libraries.get().split(',') if s.strip()]
            def done(row):refresh();items.selection_set(row['id']);display(store.read(row['id']))
            self.job(lambda:store.save(*values,artifact=aid,expected_revision=head,dependencies=deps),done)
        def restore():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            row=store.restore(self.artifact_id,self.selected(history),self.artifact_head);refresh();display(store.read(row['id']))
        def diff():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            self.show(store.compare(self.artifact_id,self.selected(history),self.artifact_head))
        def export():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            aid=self.artifact_id;rid=self.selected(history);self.job(lambda:store.export(aid,rid))
        def preview(embedded=True):
            from artifact_preview import Preview
            from artifact_libraries import Libraries
            if self.busy:raise RuntimeError('Wait for the current operation or press Stop')
            if self.preview:self.preview.close()
            self.preview=Preview(self.runtime,guard(self.runtime))
            t=title.get();k=kind.get().strip();c=editor.get('1.0','end-1c')
            revision={'title':t,'kind':k,'content':c,'artifact':self.artifact_id or 'unsaved','id':'editor'}
            deps=[s.strip() for s in libraries.get().split(',') if s.strip()]
            preview_worker=self.preview
            hwnd=None;notice=None
            if embedded:
                from internal_sheet import InternalSheet
                sheet=InternalSheet(self,'Artifact preview',self.skin.colors,fill_height=True)
                notice=sheet.skin.label(sheet.content,'Loading preview…');notice.pack(fill='x')
                host=sheet.skin.frame(sheet.content);host.configure(height=580);host.pack(fill='both',expand=True);host.pack_propagate(False)
                sheet.skin.label(sheet.content,'If this display cannot embed Chromium, close this sheet and use Separate preview.').pack(fill='x')
                def close():preview_worker.close();sheet.destroy()
                sheet.on_close=close;sheet.finish();host.update_idletasks();hwnd=host.winfo_id()
            def open_preview():
                try:
                    revision['dependencies']=Libraries(self.root,self.check).pins(deps)
                    return preview_worker.open(revision,parent_hwnd=hwnd)
                except Exception as exc:return {'ready':False,'error':str(exc)}
            def ready(result):
                self.show(result)
                if notice is not None and notice.winfo_exists():notice.configure(text='Offline preview ready' if result.get('ready') else 'Preview could not open: '+result.get('error','Unknown error').splitlines()[-1][:400])
            self.job(open_preview,ready)
        def close_preview():
            if self.preview:self.preview.close();self.preview=None
        self.buttons(p,[('Refresh',refresh),('Load selected',load),('Save revision',save),('Save as new',lambda:save(True)),('Load revision',revision),('Compare with head',diff),('Restore revision',restore),('Export revision',export),('Preview editor',preview),('Separate preview',lambda:preview(False)),('Close preview',close_preview),('Review libraries',lambda:self.artifact_libraries())])
        self.invoke(refresh)

    def artifact_libraries(self):
        from tkinter import filedialog,messagebox
        from internal_sheet import InternalSheet
        from artifact_libraries import Libraries
        store=Libraries(self.root,self.check);sheet=InternalSheet(self,'Reviewed artifact libraries',self.skin.colors);p=sheet.content
        sheet.skin.label(p,'Import a local ZIP containing library.json and pre-bundled CommonJS .js files. No installers run. Review the source before enabling it; libraries execute only inside an opened offline artifact preview.').pack(fill='x')
        items=self.tree(p,('Library','Enabled','ID'));module=self.field(p,'Module name to inspect');offset=self.field(p,'Source offset','0')
        code=self.text(p,'',12);code.pack(fill='both',expand=True)
        def refresh():
            items.delete(*items.get_children())
            for row in store.list():items.insert('','end',iid=row['id'],values=(row['name'],row['enabled'],row['id']))
        def imported(row):
            if sheet.winfo_exists():refresh();items.selection_set(row['id']);code.delete('1.0','end');code.insert('1.0',json.dumps(row,indent=2))
        def import_zip():
            path=filedialog.askopenfilename(parent=sheet,title='Import artifact library',filetypes=[('Reviewed library ZIP','*.zip')])
            if path:self.job(lambda:store.import_bundle(path),imported)
        def inspect():
            lid=self.selected(items);name=module.get().strip();start=int(offset.get())
            if start<0:raise ValueError('Offset must be nonnegative')
            def read():
                row=store.read(lid)
                if not name:return json.dumps(row,indent=2)
                entry=next((v for v in row['modules'] if v['name']==name),None)
                if entry is None:raise ValueError('Choose a module name from the manifest')
                with store.path('Bundles/'+lid+'/'+entry['file']).open('rb') as source:source.seek(start);raw=source.read(16384)
                return raw.decode('utf-8',errors='replace')+'\n\n[Next source offset: '+str(start+len(raw))+']'
            def done(value):
                if sheet.winfo_exists():code.delete('1.0','end');code.insert('1.0',value)
            self.job(read,done)
        def enable(value):
            lid=self.selected(items)
            if value and not messagebox.askyesno('Enable reviewed library','Have you reviewed this bundle’s source? Its code will run in your offline artifact previews.',parent=sheet):return
            store.enable(lid,value);refresh()
        self.buttons(p,[('Import ZIP',import_zip),('Inspect manifest/source',inspect),('Enable reviewed',lambda:enable(True)),('Disable',lambda:enable(False)),('Refresh',refresh)])
        refresh();sheet.finish()

    def close_integrations(self):
        if getattr(self,'application_api',None):self.application_api.close();self.application_api=None
        if getattr(self,'preview',None):self.preview.close();self.preview=None
