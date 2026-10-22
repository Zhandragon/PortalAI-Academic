"""Selectable retained memory observations and exact-fragment deletion."""
import tkinter as tk


class MemoryItemsEditor:
    PAGE = 100

    def __init__(self, parent, skin, memory, sessions, on_change):
        self.memory, self.sessions, self.on_change = memory, sessions, on_change
        self.skin = skin; self.offset = 0; self.selected = None; self.show_blocked = False
        skin.label(parent, 'Select a fact or chat summary to remove it. You can also highlight a fragment below and delete just that text.', muted=True).pack(fill='x', pady=5)
        skin.label(parent, 'Deletion blocks that fact from its source chat. Summary fragments block exact text, not every paraphrase. Raw chats and other facts stay intact. Blocked items lets you allow learning again.', muted=True).pack(fill='x', pady=5)
        self.query = tk.StringVar(parent)
        self.search = skin.row(parent, 'Find retained text', lambda row: skin.entry(row, ''))
        self.search.configure(textvariable=self.query)
        colors = skin.colors
        frame = skin.frame(parent); frame.pack(fill='x', pady=6)
        self.list = tk.Listbox(frame, height=7, exportselection=False, bg=colors['panel'], fg=colors['text'],
            selectbackground=colors['gold_mid'], selectforeground=colors['text'], relief='flat', bd=0)
        self.list.pack(side='left', fill='both', expand=True)
        skin.remember(self.list, bg='panel', fg='text', selectbackground='gold_mid', selectforeground='text')
        from ornate_ui import FiligreeScrollbar
        scroll = FiligreeScrollbar(frame, command=self.list.yview, palette=colors)
        scroll.pack(side='right', fill='y'); self.list.configure(yscrollcommand=scroll.set)
        skin.scrollbars.append(scroll)
        self.list.bind('<<ListboxSelect>>', self.select)
        self.detail = tk.Text(parent, height=6, wrap='word', bg=colors['panel'], fg=colors['text'],
                              exportselection=False, relief='flat', bd=0, padx=8, pady=8)
        self.detail.pack(fill='x', pady=5); self.detail.configure(state='disabled')
        self.detail._portalai_native_selection=True
        skin.remember(self.detail, bg='panel', fg='text')
        from ui_extensions import ResponsiveFlow
        actions = ResponsiveFlow(parent, bg=colors['bg'], hgap=5, vgap=5); actions.pack(fill='x')
        actions.pack_configure(before=frame)
        skin.remember(actions, bg='bg')
        self.delete_button = skin.button(actions, 'Delete item', self.delete)
        self.fragment_button = skin.button(actions, 'Delete selected text', lambda: self.delete(fragment=True))
        self.source_button = skin.button(actions, 'Source on/off', self.toggle_source)
        self.blocked_button = skin.button(actions, 'Blocked items', self.toggle_blocked)
        for button in (self.delete_button, self.fragment_button,
                       self.source_button, self.blocked_button,
                       skin.button(actions, 'Refresh', self.refresh),
                       skin.button(actions, 'Previous', lambda: self.page(-1)),
                       skin.button(actions, 'Next', lambda: self.page(1))): actions.add(button)
        self.status = tk.StringVar(parent)
        skin.label(parent, textvariable=self.status, muted=True).pack(fill='x', pady=6)
        self.query.trace_add('write', lambda *_: self.filter())
        self.refresh()

    def refresh(self):
        self.items = self.memory.blocked_items() if self.show_blocked else self.memory.retained_items()
        self.filter()

    def toggle_blocked(self):
        self.show_blocked = not self.show_blocked
        self.blocked_button.configure(text='Retained items' if self.show_blocked else 'Blocked items')
        self.delete_button.configure(text='Allow again' if self.show_blocked else 'Delete item')
        self.refresh()

    def toggle_source(self):
        if self.selected is None: return
        try:
            source = self.selected['source']
            self.memory.set_chat_included(source, not self.memory.chat_included(source))
            self.on_change()
            self.status.set('Source contribution '+('on.' if self.memory.chat_included(source) else 'off.'))
        except Exception as exc: self.status.set('Not changed: '+str(exc))

    def filter(self):
        query = self.query.get().casefold().strip()
        self.filtered = [item for item in self.items if query in (' '.join(
            str(item.get(key) or '') for key in ('key', 'text', 'title'))).casefold()]
        self.offset = 0; self.show_page()

    def page(self, delta):
        self.offset = max(0, min(max(0, (len(self.filtered)-1)//self.PAGE*self.PAGE), self.offset+delta*self.PAGE))
        self.show_page()

    def show_page(self):
        self.visible = self.filtered[self.offset:self.offset+self.PAGE]
        self.list.delete(0, 'end')
        for item in self.visible:
            label = 'Fact' if item['kind'] == 'fact' else 'Summary'
            self.list.insert('end', f"{label} · {item['title']} · {' '.join(item['text'].split())[:160]}")
        self.selected = None
        self.detail.configure(state='normal'); self.detail.delete('1.0', 'end'); self.detail.configure(state='disabled')
        self.delete_button.configure(state='disabled'); self.fragment_button.configure(state='disabled')
        self.source_button.configure(state='disabled')
        self.status.set(f'{len(self.filtered)} retained entries · showing {self.offset+1 if self.visible else 0}–{self.offset+len(self.visible)}')

    def select(self, _event=None):
        selected = self.list.curselection()
        if not selected: return
        self.selected = self.visible[selected[0]]
        self.detail.configure(state='normal'); self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', self.selected['text']); self.detail.configure(state='disabled')
        self.delete_button.configure(state='normal'); self.fragment_button.configure(state='disabled' if self.show_blocked else 'normal')
        self.source_button.configure(state='normal' if self.selected['source'] != '__manual__' else 'disabled')
        self.status.set('Source: '+self.selected['title']+' · '+self.selected['source'])

    def delete(self, fragment=False):
        if self.selected is None: return
        try:
            if self.show_blocked:
                self.memory.allow_item(self.selected['block_id']); self.refresh(); self.on_change()
                self.status.set('Allowed again. Rebuild included to refresh from existing chats.')
                return
            span = None
            if fragment:
                if not self.detail.tag_ranges('sel'):
                    self.status.set('Highlight the text fragment to delete first.'); return
                span = (len(self.detail.get('1.0', 'sel.first')), len(self.detail.get('1.0', 'sel.last')))
            self.memory.delete_retained(self.selected, self.sessions(), span=span)
            self.refresh(); self.on_change()
            self.status.set('Selected text removed.' if fragment else 'Selected memory removed.')
        except Exception as exc:
            self.status.set('Not deleted: '+str(exc))
