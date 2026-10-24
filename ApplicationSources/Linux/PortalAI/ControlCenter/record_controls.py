"""Compact search and manual classification for persistence record lists."""
import tkinter as tk


class FoldPanel(tk.Frame):
    """Keep infrequent forms out of the reading area without discarding drafts."""
    def __init__(self, parent, skin, title):
        super().__init__(parent, bg=skin.colors['panel'])
        skin.remember(self, bg='panel')
        self.title, self.expanded = title, False
        self.button = skin.button(self, '▸ '+title, self.toggle)
        self.button.configure(width=0)
        self.button.pack(anchor='w', pady=(0, 2))
        self.body = skin.frame(self)

    def toggle(self):
        self.set_open(not self.expanded)

    def set_open(self, opened=True):
        self.expanded = bool(opened)
        if opened:self.body.pack(fill='x', pady=(1, 4))
        else:self.body.pack_forget()
        self.button.configure(text=('▾ ' if opened else '▸ ')+self.title)


def record_columns(parent, table, details):
    """Give details 60% of wide layouts; stack naturally at narrow widths."""
    previous = [None]
    def layout(event):
        wide = event.width >= 940
        if wide == previous[0]:return
        previous[0] = wide
        for i in range(2):
            parent.columnconfigure(i, weight=(2, 3)[i] if wide else int(i == 0), uniform='record_columns' if wide else '')
            parent.rowconfigure(i, weight=(1 if i == 0 else 0) if wide else (1, 2)[i])
        table.grid(row=0,column=0,sticky='nsew',padx=(0,10) if wide else 0,pady=(0,4))
        details.grid(row=0 if wide else 1,column=1 if wide else 0,sticky='nsew',pady=(0,4))
    parent.bind('<Configure>', layout, add='+')
    layout(type('Size', (), {'width':parent.winfo_width()})())


def record_name(record):
    """The first nonempty objective line is the existing record's display name."""
    return next((line.strip().lstrip('#').strip() for line in str(record.get('objective', '')).splitlines()
                 if line.strip().lstrip('#').strip()), '')


class RecordSort:
    """Typed heading sorting that survives refresh without rebuilding selection."""
    def __init__(self, tree, refresh):
        self.tree, self.refresh = tree, refresh
        self.column, self.descending = None, False
        self.labels = {key: tree.heading(key, 'text') for key in tree['columns']}
        for key in self.labels:
            tree.heading(key, command=lambda key=key: self.choose(key))

    def choose(self, column):
        self.descending = not self.descending if column == self.column else False
        self.column = column
        for key, label in self.labels.items():
            self.tree.heading(key, text=label + (' ▼' if self.descending else ' ▲') if key == column else label)
        self.refresh()

    def apply(self, records):
        # Stable ID ties and absent values last in both directions.
        ids = list(records)
        if self.column:
            present = sorted(key for key in ids if records[key].get(self.column) is not None)
            missing = sorted(set(ids) - set(present))
            def value(key):
                item = records[key][self.column]
                return item.casefold() if isinstance(item, str) else item
            ids = sorted(present, key=value, reverse=self.descending) + missing
        for index, key in enumerate(ids):
            self.tree.move(key, '', index)


class RecordSearch(tk.Frame):
    def __init__(self, parent, skin, refresh):
        super().__init__(parent, bg=skin.colors['panel'])
        skin.remember(self,bg='panel')
        self.query = tk.StringVar(master=self)
        self.refresh = refresh
        self.pending = None
        caption=skin.label(self, 'Search',width=0)
        caption.unbind('<Configure>')
        caption.pack(side='left', padx=(0, 6))
        self.entry = skin.entry(self, '')
        self.entry.configure(textvariable=self.query, width=20)
        self.entry.pack(side='left', fill='x', expand=True)
        clear=skin.button(self, 'Clear', lambda: self.query.set(''))
        clear.configure(width=5)
        clear.pack(side='left', padx=(6, 0))
        self.query.trace_add('write', self.changed)
        self.entry.bind('<Return>', lambda _event: self.run())
        self.bind('<Destroy>', self.close, add='+')

    def changed(self, *_):
        if self.pending is not None:
            self.after_cancel(self.pending)
        self.pending = self.after(200, self.run)

    def run(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        self.refresh()

    def close(self, event):
        if event.widget is self and self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None


class RecordClassification(tk.Frame):
    def __init__(self, parent, skin, apply, *, mission=False):
        super().__init__(parent, bg=skin.colors['panel'])
        skin.remember(self,bg='panel')
        self.choices = {'Automatic': None, 'User': 'user',
                        'Diagnostic': 'validation' if mission else 'diagnostic',
                        'Unclassified': 'unknown' if mission else 'legacy'}
        self.value = tk.StringVar(master=self, value='Automatic')
        self.current = None
        caption=skin.label(self, 'Classify',width=0)
        caption.unbind('<Configure>')
        caption.pack(side='left', padx=(0, 6))
        self.picker = skin.combo(self, self.value, list(self.choices))
        self.picker.configure(width=15, state='disabled')
        self.picker.pack(side='left', fill='x', expand=True)
        self.button = skin.button(self, 'Apply', apply)
        self.button.configure(state='disabled',width=6)
        self.button.pack(side='left', padx=(6, 0))

    def show(self, record_id=None, kind=None):
        if record_id != self.current:
            self.current = record_id
            self.value.set(next((label for label, value in self.choices.items() if value == kind), 'Automatic'))
        self.picker.configure(state='readonly' if record_id else 'disabled')
        self.button.configure(state='normal' if record_id else 'disabled')

    def chosen(self):
        return self.choices[self.value.get()]
