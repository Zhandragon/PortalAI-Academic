"""Native project and skill management, sharing the existing Workspace sheet."""
import json
from pathlib import Path
from tkinter import filedialog
from portable_workspace import Organization, Skills


class PortableWorkspaceUI:
    def projects_page(self):
        p = self.pages['Projects']; store = Organization(self.root, self.check)
        self.skin.label(p, 'Group chats with shared instructions and knowledge. Removing a project keeps its chats and documents.').pack(fill='x')
        projects = self.tree(p, ('Project', 'ID'))
        name = self.field(p, 'Project name')
        instructions = self.text(p, '', 4); instructions.pack(fill='x')
        self.skin.label(p, 'Project instructions · up to 4,000 characters').pack(fill='x')
        collections = self.tree(p, ('Knowledge collection', 'ID'))
        from knowledge_base import Knowledge
        for r in Knowledge(self.root, self.check).list():
            collections.insert('', 'end', iid=r['id'], values=(r['name'], r['id']))
        chats = self.tree(p, ('Chat', 'Project'))
        editing = [None]
        def refresh():
            state = store.state(); projects.delete(*projects.get_children()); chats.delete(*chats.get_children())
            for row in store.list(): projects.insert('', 'end', iid=row['id'], values=(row['name'], row['id']))
            from native_chat import ChatStore
            chat_store = getattr(self.chat, 'store', None) or ChatStore(self.root)
            for row in chat_store.list_sessions()[:500]:
                project = state['projects'].get(state['chats'].get(row['id']), {})
                chats.insert('', 'end', iid=row['id'], values=(row['title'], project.get('name', 'Unfiled')))
        def load():
            pid = self.selected(projects); row = store.state()['projects'][pid]; editing[0] = pid
            name.delete(0, 'end'); name.insert(0, row['name'])
            instructions.delete('1.0', 'end'); instructions.insert('1.0', row['instructions'])
            collections.selection_set([c for c in row['collections'] if collections.exists(c)])
        def save(new=False):
            row = store.put(name.get(), instructions.get('1.0', 'end-1c'), list(collections.selection()), None if new else editing[0])
            editing[0] = row['id']; refresh(); projects.selection_set(row['id']); self.show('Project saved. Its instructions apply to future turns of assigned chats.')
        def assign(current=False, clear=False):
            if current:
                if not self.chat or self.chat.busy: raise ValueError('Open an idle chat first')
                ids = [self.chat.session['id']]
            else: ids = list(chats.selection())
            store.assign(ids, None if clear else self.selected(projects)); refresh()
        def open_chat():
            if not self.chat: raise ValueError('Open Workspace from Chat to open a conversation')
            if self.chat.busy: raise ValueError('Finish or stop the active chat first')
            sid = self.selected(chats); self.close(); self.chat.load_session(sid)
        def remove():
            pid = self.selected(projects); store.remove(pid); editing[0] = None; refresh()
            self.show('Project removed. All conversations and knowledge collections were retained.')
        def new_chat():
            if not self.chat or self.chat.busy:raise ValueError('Open an idle chat first')
            pid=self.selected(projects);self.chat.new_chat();store.assign([self.chat.session['id']],pid);self.close()
        self.buttons(p, [('Refresh', refresh), ('Load project', load), ('Save project', save), ('Save as new', lambda: save(True)),
                         ('Assign selected chats', assign), ('Assign current chat', lambda: assign(True)),
                         ('Unfile selected chats', lambda: assign(clear=True)), ('Open selected chat', open_chat), ('New chat in project',new_chat), ('Remove project', remove)])
        self.invoke(refresh)

    def skills_page(self):
        from skill_packs import SkillPacks
        p = self.pages['Skills']; store = SkillPacks(self.root, self.check); editing = [None]
        self.skin.label(p, 'Task guides and portable bundles, loaded when relevant. Imports start disabled. Scripts need a separate administrator grant; bundled wheels stay inside the skill.').pack(fill='x')
        items = self.tree(p, ('Skill', 'Enabled'))
        name = self.field(p, 'Name'); description = self.field(p, 'When should Nice use this skill?')
        body = self.text(p, '', 6); body.pack(fill='x')
        def refresh():
            items.delete(*items.get_children())
            for row in store.list(): items.insert('', 'end', iid=row['id'], values=(row['name'], 'Yes' if row['enabled'] else 'No'))
        def display(row):
            editing[0] = row['id']
            for widget, value in ((name, row['name']), (description, row['description'])):
                widget.delete(0, 'end'); widget.insert(0, value)
            body.delete('1.0', 'end'); body.insert('1.0', row['body']); refresh(); items.selection_set(row['id'])
        def load(): display(store.load(self.selected(items)))
        def lesson():
            from task_notebook import request_index
            session=getattr(self.chat,'session',None) or {}
            plan=session.get('task_notebooks',{}).get(str(request_index(session)))
            if not plan or not plan.get('all_verified'):raise ValueError('Finish a task notebook with linked evidence before drafting a reusable lesson')
            text='Historical procedure from chat '+session['id']+'. Recheck current inputs and permissions; previous evidence is not proof for a new task.\n\n'
            for step in plan['steps']:text+='- '+step['goal']+'\n  Verify: '+step['check']+'\n  Historical evidence messages: '+', '.join(map(str,step['evidence']))+'\n'
            display(store.put('Reviewed task lesson','Replace this with the specific situations where this procedure helps.',text,enabled=False))
            self.show('Lesson draft saved disabled. Edit the name, relevance description and procedure before enabling it.')
        def save(new=False, enabled=None):
            sid = None if new else editing[0]
            active = bool(sid and store.load(sid)['enabled']) if enabled is None else enabled
            display(store.put(name.get(), description.get(), body.get('1.0', 'end-1c'), skill=sid, enabled=active))
        def import_file():
            path = filedialog.askopenfilename(parent=self, title='Import a skill', filetypes=[('Skill guide or bundle', '*.md *.txt *.zip')])
            if path:
                def done(row):display(row);self.show('Imported disabled. Review instructions and bundle contents before enabling; importing runs no code.')
                self.job(lambda:store.import_pack(path) if Path(path).suffix.lower()=='.zip' else store.import_file(path),done)
        def bundle():
            from internal_sheet import InternalSheet
            from tkinter import ttk,messagebox
            from workspace_store import read_json
            sid=self.selected(items);row=store.load(sid)
            if not row.get('pack'):raise ValueError('This skill contains only its text guide')
            sheet=InternalSheet(self,'Review skill bundle',self.skin.colors);skin=sheet.skin;area=sheet.content
            skin.label(area,'Scripts run with your administrator access, not in an OS sandbox. Review their source and dependencies before granting execution.').pack(fill='x')
            files=ttk.Treeview(area,columns=('path','bytes'),show='headings',height=6,selectmode='browse')
            for key in ('path','bytes'):files.heading(key,text=key)
            files.pack(fill='both',expand=True);sheet.style_tree(files)
            for name,info in row['pack']['files'].items():files.insert('','end',iid=name,values=(name,info['bytes']))
            preview=self.text(area,'',8);preview.pack(fill='both',expand=True)
            def inspect(event=None):
                selection=files.selection()
                if not selection:return
                name=selection[0];info=row['pack']['files'][name]
                text=json.dumps(info,indent=2)
                if info['bytes']<=65536:
                    try:text=store.path('Packs/'+sid+'/'+name).read_text(encoding='utf-8-sig')
                    except (UnicodeError,OSError):pass
                preview.delete('1.0','end');preview.insert('1.0',text)
            files.bind('<<TreeviewSelect>>',inspect)
            def grant(enabled):
                self.admin()
                if enabled and not messagebox.askyesno('Grant skill scripts','Allow the reviewed scripts in this bundle to read and change files or use the network with your account access?',parent=sheet):return
                store.allow_code(sid,enabled);self.show('Skill script execution '+('granted.' if enabled else 'revoked.'))
            calls=ttk.Treeview(area,columns=('script','state'),show='headings',height=3,selectmode='browse')
            for key in ('script','state'):calls.heading(key,text=key)
            calls.pack(fill='x');sheet.style_tree(calls)
            for rid in store.records('Calls'):
                receipt=read_json(store.path('Calls/'+rid+'.json'))
                if receipt.get('skill')==sid and receipt['state']=='pending':calls.insert('','end',iid=rid,values=(receipt['script'],'Outcome uncertain'))
            def review(confirmed):
                self.admin();selected=calls.selection()
                if not selected:raise ValueError('Choose an uncertain execution receipt')
                if not messagebox.askyesno('Review execution','Mark the action as confirmed complete?' if confirmed else 'Allow a deliberate retry? The previous execution may already have changed files or external state.',parent=sheet):return
                store.review_call(selected[0],confirmed);calls.delete(selected[0])
            self.buttons(area,[('Grant script execution',lambda:grant(True)),('Revoke script execution',lambda:grant(False)),('Confirm completed action',lambda:review(True)),('Allow explicit retry',lambda:review(False))])
        def export():
            row = store.load(self.selected(items))
            import os
            from profile_lazy_state import publish_no_replace
            # Use the account-owned output boundary and refuse overwriting exports.
            from profile_paths import private_path
            target = private_path(self.root, 'Outputs/Skills/'+row['id']+'.md',context=store.identity)
            data = '---\nname: '+json.dumps(row['name'])+'\ndescription: '+json.dumps(row['description'])+'\n---\n\n'+row['body']+'\n'
            from runtime_policy import require_space
            require_space(self.root, len(data.encode())*2, for_outputs=True); self.check(); target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists(): raise ValueError('An export already exists; preserve or rename it before exporting again')
            temporary=target.with_name(target.name+'.'+store.new_id()+'.part')
            try:
                with temporary.open('xb') as stream:
                    stream.write(data.encode('utf-8'));stream.flush();os.fsync(stream.fileno())
                store.check();publish_no_replace(temporary,target)
            finally:temporary.unlink(missing_ok=True)
            self.show(str(target))
        self.buttons(p, [('Refresh', refresh), ('Load selected', load), ('Import skill', import_file), ('Review bundle',bundle), ('Draft lesson from chat',lesson),
                         ('Save', save), ('Save as new', lambda: save(True)), ('Save and enable', lambda: save(enabled=True)),
                         ('Save and disable', lambda: save(enabled=False)), ('Export selected', export)])
        self.invoke(refresh)
