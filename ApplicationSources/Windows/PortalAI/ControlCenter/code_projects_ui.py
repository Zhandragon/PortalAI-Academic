"""Explicit project registration, command grants, diffs and guarded undo."""
import json
import time
from tkinter import filedialog, messagebox
from workspace_store import identifier, read_json


def code_page(panel):
    from code_projects import CodeProjects, Edits
    from result_verification import Verifications
    store = CodeProjects(panel.root, panel.check); edits = Edits(panel.root, panel.check)
    p = panel.pages['Code']
    panel.skin.label(p, 'Administrator tools. Register a source folder, scan it incrementally, then search symbols/imports and likely tests. Nice’s direct text edits retain bounded before-images; external shell edits are not journaled.').pack(fill='x')
    name = panel.field(p, 'Project name'); folder = panel.field(p, 'Project folder'); query = panel.field(p, 'Symbol / file / topic')
    tree = panel.tree(p, ('Project', 'ID'))
    commands = panel.text(p, '{}', 4); commands.pack(fill='x')
    panel.skin.label(p, 'Optional reviewed commands JSON: {"unit":{"argv":["{python}","-m","unittest","test_example"],"inputs":["example.py","test_example.py"],"timeout":60}}. Grant makes these commands available to Nice. Tests can have side effects; no shell string parsing.').pack(fill='x')
    changes = panel.tree(p, ('Time', 'State', 'Edited path'))
    def refresh():
        panel.admin(); tree.delete(*tree.get_children()); changes.delete(*changes.get_children())
        for row in store.list(): tree.insert('', 'end', iid=row['id'], values=(row['name'], row['id']))
        for row in edits.list(): changes.insert('', 'end', iid=row['id'], values=(time.strftime('%m-%d %H:%M', time.localtime(row['created'])), row['state'], json.dumps(row['path'])))
    def browse():
        value = filedialog.askdirectory(parent=panel, title='Choose code project folder')
        if value: folder.delete(0, 'end'); folder.insert(0, value)
    def add():
        panel.admin(); row = store.add(name.get(), folder.get()); refresh(); tree.selection_set(row['id']); panel.show(row)
    def scan(restart=False):
        panel.admin(); pid = panel.selected(tree); panel.job(lambda: store.scan(pid, restart=restart))
    def search():
        panel.admin(); pid = panel.selected(tree); text = query.get(); panel.job(lambda: store.search(pid, text))
    def load_commands():
        row = store.load(panel.selected(tree)); commands.delete('1.0', 'end'); commands.insert('1.0', json.dumps(row.get('commands', {}), indent=2))
    def grant():
        panel.admin(); pid = panel.selected(tree); configs = json.loads(commands.get('1.0', 'end'))
        if not messagebox.askyesno('Approve project commands', 'Allow Nice to execute these exact named commands? They run with your administrator access and can change files.', parent=panel): return
        panel.show(store.set_commands(pid, configs))
    def diff():
        panel.admin(); ids = list(changes.selection()); panel.job(lambda: edits.preview(ids))
    def undo():
        panel.admin(); rid = panel.selected(changes)
        if not messagebox.askyesno('Undo selected edit', 'Restore the selected edit’s before-image only if the current file still matches Nice’s written bytes? A file created by that edit will be removed.', parent=panel): return
        panel.job(lambda: edits.undo(rid, panel.runtime), lambda _: refresh())
    def discard():
        panel.admin(); ids = list(changes.selection())
        if not ids: raise ValueError('Select undo records to remove')
        if not messagebox.askyesno('Remove undo records', 'Remove only these saved before-images? Current project files will stay unchanged; these edits will no longer be undoable.', parent=panel): return
        for rid in ids: edits.discard(rid)
        refresh()
    def remove_map():
        panel.admin();pid=panel.selected(tree)
        with store.lock('scan-'+pid):store.path('Indexes/'+identifier(pid)+'.json').unlink(missing_ok=True)
        panel.show('Cached source map removed. Project files and undo history are unchanged.')
    panel.buttons(p, [('Remove cached map',remove_map),('Choose folder', browse), ('Register', add), ('Refresh', refresh), ('Start fresh scan', lambda: scan(True)),
                     ('Continue scan', scan), ('Find files/tests', search), ('Load commands', load_commands), ('Approve commands', grant),
                     ('Preview selected edits', diff), ('Undo one selected edit', undo), ('Remove selected undo records', discard)])
    checks = panel.tree(p, ('Check ID', 'State', 'Project command'))
    def check_history():
        panel.admin(); checks.delete(*checks.get_children())
        for rid in store.records('Checks'):
            row = read_json(store.path('Checks/' + rid + '.json'))
            checks.insert('', 'end', iid=rid, values=(rid, row['state'], row['command']))
    def review():
        panel.admin(); rid = panel.selected(checks)
        if not messagebox.askyesno('Review uncertain test run', 'Have you inspected the command’s possible side effects? Acknowledging permits a later explicit run; it does not retry now.', parent=panel): return
        panel.show(store.review_check(rid)); check_history()
    def clear_completed():
        panel.admin(); verifier = Verifications(panel.runtime, panel.check)
        if not messagebox.askyesno('Clear completed verification history', 'Remove completed check records and verification receipts? Chat evidence remains, but old task verifications will require new checks. Uncertain executions remain blocked.', parent=panel): return
        with store.lock('commands'):
            for rid in store.records('Checks'):
                path = store.path('Checks/' + rid + '.json')
                if read_json(path)['state'] != 'pending': path.unlink()
        with verifier.lock():
            for rid in verifier.records('Runs'): verifier.path('Runs/' + rid + '.json').unlink()
        check_history()
    panel.buttons(p, [('Check history', check_history), ('Acknowledge uncertain run', review), ('Clear completed check history', clear_completed)])
    panel.invoke(refresh)
