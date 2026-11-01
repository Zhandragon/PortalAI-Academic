"""Account-scoped Ctrl+K menu with one cancellable worker and bounded metadata."""
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from internal_sheet import InternalSheet


def install(chat):
    app = chat.app
    previous = getattr(app, '_portalai_palette_binding', None)
    if previous:
        try: app.unbind('<Control-k>', previous)
        except tk.TclError: pass
    def open_menu(_event=None):
        if chat._closing: return 'break'
        try:
            chat._check_login()
            existing = getattr(chat, '_command_palette', None)
            if existing is not None and existing.winfo_exists(): existing.entry.focus_set()
            else: chat._command_palette = Palette(chat)
        except Exception as exc: chat._notice('Search and commands', str(exc), kind='error')
        return 'break'
    app._portalai_palette_binding = app.bind('<Control-k>', open_menu, add='+')
    chat.open_command_palette = open_menu


def close(chat):
    palette = getattr(chat, '_command_palette', None)
    if palette is not None:
        try: palette.close()
        except tk.TclError: pass
    binding = getattr(chat.app, '_portalai_palette_binding', None)
    if binding:
        try: chat.app.unbind('<Control-k>', binding)
        except tk.TclError: pass
        chat.app._portalai_palette_binding = None
    toast = getattr(chat, '_completion_toast', None)
    if toast is not None:
        try: toast.destroy()
        except tk.TclError: pass


class Palette(InternalSheet):
    def __init__(self, chat):
        super().__init__(chat.app, 'Search and commands · Ctrl+K', chat.COL)
        from capability_tools import guard
        self.chat = chat; self.base_check = guard(chat.tool_runtime)
        self.cancel = threading.Event(); self.events = queue.Queue(); self.pending = queue.Queue(1)
        self.generation = 0; self.timer = None; self.closed = False; self.on_close = self.close
        self.skin.label(self.content, 'Find chats by title, projects, artifact titles, available output filenames, settings and actions. No transcript or document contents are loaded. Enter opens; Escape closes.').pack(fill='x')
        self.query = tk.StringVar(self); self.entry = self.skin.entry(self.content, '')
        self.entry.configure(textvariable=self.query); self.entry.pack(fill='x', pady=7)
        self.tree = ttk.Treeview(self.content, columns=('Kind', 'Name'), show='headings', height=12)
        self.tree.heading('Kind', text='Kind'); self.tree.heading('Name', text='Name')
        self.tree.column('Kind', width=95, stretch=False); self.tree.column('Name', width=500)
        self.tree.pack(fill='both', expand=True); self.style_tree(self.tree)
        self.status = self.skin.label(self.content, 'Loading a bounded metadata index…'); self.status.pack(fill='x')
        self.visible = []; self.entry.bind('<Return>', self.activate); self.tree.bind('<Return>', self.activate)
        self.tree.bind('<Double-1>', self.activate); self.query.trace_add('write', self.schedule)
        self.skin.button(self.content, 'Open selected', self.activate).pack(anchor='e', pady=4)
        self.entry.focus_set()
        self.chat._writer_jobs.thread(target=self.worker, name='PortalAI-CommandPalette').start()
        self.schedule(); self.after(80, self.poll)

    def check(self):
        self.base_check()
        if self.cancel.is_set() or self.chat._closing: raise RuntimeError('Search closed')

    def catalog(self):
        chat = self.chat; rows = []
        actions = [('Preferences and model settings', 'settings'), ('Memory corrections and conflicts', 'memory'),
                   ('New chat', 'new'), ('Stop current request', 'stop'), ('Toggle hands-free', 'voice'),
                   ('Toggle completion notifications', 'notifications')]
        rows.extend({'kind': 'Action', 'name': name, 'action': action} for name, action in actions)
        for page in ('Projects', 'Knowledge', 'Skills', 'Artifacts', 'Code', 'Calibration', 'Connections', 'Workflows', 'Computer', 'API', 'Compare'):
            rows.append({'kind': 'Workspace', 'name': page, 'page': page})
        self.check()
        # The chat already owns this lightweight catalog; never create a new store
        # or force reconstruction/decryption of all transcripts for a palette.
        catalog = chat.store.catalog
        with catalog.lock:
            sessions = list((catalog.rows or {}).values())
        sessions.sort(key=lambda r: float(r.get('updated') or 0), reverse=True)
        rows.extend({'kind': 'Chat', 'name': r.get('title') or 'Untitled', 'chat': r['id']} for r in sessions[:1500])
        from portable_workspace import Organization
        rows.extend({'kind': 'Project', 'name': r['name'], 'page': 'Projects', 'record': r['id']} for r in Organization(chat.root, self.check).list())
        from account_permissions import can_admin
        if can_admin(chat.root, getattr(chat.app, '_portalai_account_session', None)):
            from code_projects import CodeProjects
            rows.extend({'kind': 'Code project', 'name': r['name'], 'page': 'Code', 'record': r['id']} for r in CodeProjects(chat.root, self.check).list())
        from artifacts import Artifacts
        artifacts = Artifacts(chat.root, self.check)
        for rid in artifacts.records('Catalog')[:200]:
            self.check(); row = artifacts.metadata(rid)
            rows.append({'kind': 'Artifact', 'name': row['title'], 'page': 'Artifacts', 'record': rid})
        output = chat.store.profile.private('Outputs'); pending = [output]; count = 0; started = time.monotonic()
        while pending and count < 2000 and time.monotonic() - started < 1.5:
            self.check(); folder = pending.pop(0)
            if not folder.exists(): continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    count += 1
                    if count%32==0:self.check()
                    if count > 2000 or time.monotonic() - started >= 1.5: break
                    path = Path(entry.path)
                    if entry.is_symlink() or getattr(path, 'is_junction', lambda: False)(): continue
                    if entry.is_dir(follow_symlinks=False): pending.append(path)
                    elif entry.is_file(follow_symlinks=False): rows.append({'kind': 'Output file', 'name': path.relative_to(output).as_posix(), 'file': str(path)})
        return rows

    def worker(self):
        try:
            rows = self.catalog()
            while not self.cancel.is_set():
                try: generation, query = self.pending.get(timeout=.2)
                except queue.Empty: continue
                self.check(); terms = query.casefold().split(); matches = []
                for number,row in enumerate(rows):
                    if number%128==0:self.check()
                    label = (row['kind'] + ' ' + row['name']).casefold()
                    if all(term in label for term in terms): matches.append(row)
                    if len(matches) >= 80: break
                self.events.put((generation, matches, None))
        except Exception as exc:
            if not self.cancel.is_set(): self.events.put((self.generation, [], str(exc)))

    def schedule(self, *_):
        if self.closed: return
        self.generation += 1
        if self.timer is not None: self.after_cancel(self.timer)
        generation = self.generation
        def submit():
            self.timer = None
            try: self.pending.get_nowait()
            except queue.Empty: pass
            self.pending.put((generation, self.query.get()[:300]))
        self.timer = self.after(200, submit)

    def poll(self):
        if self.closed: return
        try:
            self.check()
            while True:
                generation, rows, error = self.events.get_nowait()
                if generation != self.generation: continue
                self.visible = rows; self.tree.delete(*self.tree.get_children())
                for i, row in enumerate(rows): self.tree.insert('', 'end', iid=str(i), values=(row['kind'], row['name']))
                if rows: self.tree.selection_set('0')
                self.status.configure(text=error or str(len(rows)) + ' results · bounded title/filename search; reopen to refresh. Archived output bytes stay on demand.')
        except queue.Empty: pass
        except Exception:
            self.close(); return
        finally:
            if not self.closed: self.after(80, self.poll)

    def activate(self, _event=None):
        try:
            self.check(); selected = self.tree.selection()
            if not selected: return 'break'
            row = self.visible[int(selected[0])]; chat = self.chat
            if chat.busy and row.get('action') != 'stop': raise ValueError('Finish or stop the active chat before opening another item')
            if 'chat' in row: self.close(); chat.load_session(row['chat'])
            elif 'page' in row:
                self.close(); panel = chat.open_workspace()
                if panel:
                    panel.page(row['page'])
                    if row.get('record'):
                        pending = [panel.pages[row['page']]]
                        while pending:
                            widget = pending.pop(); pending.extend(widget.winfo_children())
                            if isinstance(widget, ttk.Treeview) and widget.exists(row['record']): widget.selection_set(row['record']); widget.see(row['record'])
                        panel.show('Selected: ' + row['name'] + '. Use Load / View to inspect it; previews run only when opened.')
            elif 'file' in row:
                path = chat.tool_runtime.safe_path(row['file']); folder = path.parent
                if not folder.is_dir(): raise FileNotFoundError('Output folder is unavailable')
                self.close()
                # Open the containing directory, never execute the matched file.
                if os.name == 'nt': os.startfile(folder)
                else:
                    import subprocess, sys
                    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                action = row['action']; self.close()
                callbacks = {'settings': chat.open_settings, 'memory': chat.open_memory_panel, 'new': chat.new_chat,
                             'stop': chat.stop_generation, 'voice': chat.toggle_conversation_mode}
                if action == 'notifications':
                    chat.settings['completion_notifications'] = not chat.settings.get('completion_notifications', True)
                    chat.store.save_settings(); chat.model_lbl.configure(text='Completion notifications ' + ('on' if chat.settings['completion_notifications'] else 'off'))
                else: callbacks[action]()
        except Exception as exc:
            if not self.closed: self.status.configure(text=str(exc))
            else: self.chat._notice('Search and commands', str(exc), kind='error')
        return 'break'

    def close(self):
        if self.closed: return
        self.closed = True; self.cancel.set()
        if self.timer is not None: self.after_cancel(self.timer)
        self.chat._command_palette = None; self.destroy()


def notify(chat, *, cancelled=False, attention=False):
    """Main-thread, silent notification. No background service or focus change."""
    if chat._closing or not chat.settings.get('completion_notifications', True): return
    chat._check_login()
    if chat.conversation_active.is_set(): return  # No toast on every voice exchange.
    text = 'Request stopped' if cancelled else 'Request needs attention' if attention else 'Nice has replied'
    old = getattr(chat, '_completion_toast', None)
    if old is not None:
        try: old.destroy()
        except tk.TclError: pass
    host = getattr(chat.app, '_portalai_account_host', chat.app)
    toast = tk.Label(host, text=text, bg=chat.COL['panel2'], fg=chat.COL['text'], padx=14, pady=9)
    toast.place(relx=.98, rely=.02, anchor='ne'); chat._completion_toast = toast
    toast.bind('<Button-1>', lambda _: toast.destroy()); toast.after(6500, toast.destroy)
    if os.name == 'nt' and chat.app.focus_displayof() is None:
        import ctypes
        from ctypes import wintypes
        class Flash(ctypes.Structure):
            _fields_ = [('size', wintypes.UINT), ('window', wintypes.HWND), ('flags', wintypes.DWORD), ('count', wintypes.UINT), ('timeout', wintypes.DWORD)]
        api = ctypes.windll.user32; api.GetAncestor.restype = wintypes.HWND
        window = api.GetAncestor(wintypes.HWND(chat.app.winfo_id()), 2)
        record = Flash(ctypes.sizeof(Flash), window, 2, 2, 0)
        api.FlashWindowEx(ctypes.byref(record))
