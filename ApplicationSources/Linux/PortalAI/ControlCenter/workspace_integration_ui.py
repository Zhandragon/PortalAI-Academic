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
        from application_api import APIState,SCOPES
        p=self.pages['API'];self.application_api=None
        self.skin.label(p,'Administrator: opt-in loopback API v1. It runs while this Workspace is open. Stop, sign-out or closing Workspace stops requests and jobs. API chats are separate plain-text conversations.').pack(fill='x')
        endpoint=self.field(p,'Live API URL','Stopped')
        name=self.field(p,'Token name','My application')
        scopes=self.field(p,'Scopes (comma-separated)','chats:read,chats:write,artifacts:read,artifacts:write,structured:generate')
        hours=self.field(p,'Token lifetime in hours (1–720)','24')
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
            self.admin();result=state.issue(name.get(),[s.strip() for s in scopes.get().split(',')],int(hours.get()));refresh();self.show(result)
        def revoke():self.admin();state.revoke(self.selected(tokens));refresh();self.show('Token revoked; its jobs stop at their next cancellation check.')
        self.buttons(p,[('Start API',start),('Stop API',stop),('Issue token',issue),('Refresh tokens',refresh),('Revoke selected',revoke),('Supported scopes',lambda:self.show(sorted(SCOPES)))])
        receipt=self.field(p,'Uncertain receipt ID');result=self.field(p,'Reviewed result JSON','null')
        def pending():self.admin();self.show(state.pending())
        def review(decision):self.admin();self.show(state.resolve(receipt.get().strip(),decision,json.loads(result.get())))
        self.buttons(p,[('Uncertain requests',pending),('Confirm result',lambda:review('confirmed')),('Allow reviewed retry',lambda:review('allow_retry'))])
        if can_admin(self.root,self.session):self.invoke(refresh)

    def artifacts_page(self):
        from artifacts import Artifacts
        p=self.pages['Artifacts'];self.preview=None;store=Artifacts(self.root,self.check)
        self.artifact_id=None;self.artifact_head=None
        self.skin.label(p,'HTML, SVG or chart JSON. Save creates an immutable revision. Preview runs scripts offline in an isolated browser; exporting produces the original file.').pack(fill='x')
        items=self.tree(p,('Title','Kind','Revision'));history=self.tree(p,('Revision','Created'))
        title=self.field(p,'Title','My artifact');kind=self.field(p,'Kind: html, svg or chart','html')
        editor=self.text(p,EXAMPLE_HTML,7);editor.pack(fill='x')
        def refresh():
            items.delete(*items.get_children())
            for r in store.list():items.insert('','end',iid=r['id'],values=(r['title'],r['kind'],r['head']))
        def display(row):
            self.artifact_id=row['artifact'];self.artifact_head=store.metadata(row['artifact'])['head']
            for widget,value in ((title,row['title']),(kind,row['kind'])):widget.delete(0,'end');widget.insert(0,value)
            editor.delete('1.0','end');editor.insert('1.0',row['content']);history.delete(*history.get_children())
            for r in store.history(row['artifact']):history.insert('','end',iid=r['id'],values=(r['id'],r['created']))
            history.selection_set(row['id']);self.show({'artifact':row['artifact'],'loaded_revision':row['id'],'current_head':self.artifact_head})
        def load():display(store.read(self.selected(items)))
        def revision():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            display(store.read(self.artifact_id,self.selected(history)))
        def save(new=False):
            row=store.save(title.get(),kind.get().strip(),editor.get('1.0','end-1c'),artifact=None if new else self.artifact_id,expected_revision=None if new else self.artifact_head)
            refresh();items.selection_set(row['id']);display(store.read(row['id']))
        def restore():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            row=store.restore(self.artifact_id,self.selected(history),self.artifact_head);refresh();display(store.read(row['id']))
        def diff():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            self.show(store.compare(self.artifact_id,self.selected(history),self.artifact_head))
        def export():
            if not self.artifact_id:raise ValueError('Load an artifact first')
            self.show(store.export(self.artifact_id,self.selected(history)))
        def preview():
            from artifact_preview import Preview
            if self.preview:self.preview.close()
            self.preview=Preview(self.runtime,guard(self.runtime))
            t=title.get();k=kind.get().strip();c=editor.get('1.0','end-1c')
            revision={'title':t,'kind':k,'content':c,'artifact':self.artifact_id or 'unsaved','id':'editor'}
            preview_worker=self.preview
            self.job(lambda:preview_worker.open(revision))
        def close_preview():
            if self.preview:self.preview.close();self.preview=None
        self.buttons(p,[('Refresh',refresh),('Load selected',load),('Save revision',save),('Save as new',lambda:save(True)),('Load revision',revision),('Compare with head',diff),('Restore revision',restore),('Export revision',export),('Preview editor',preview),('Close preview',close_preview)])
        self.invoke(refresh)

    def close_integrations(self):
        if getattr(self,'application_api',None):self.application_api.close();self.application_api=None
        if getattr(self,'preview',None):self.preview.close();self.preview=None
