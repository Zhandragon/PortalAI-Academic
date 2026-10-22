"""Targeted diagnostics chooser rendered inside the existing application window.

Keep the native combobox value/options contract for the HA form adapter, but do
not post a transient OS popup for local interaction. Selection does not run work.
"""
import tkinter as tk
from tkinter import ttk

from internal_sheet import InternalSheet
from rounded_controls import RoundedCombobox


class DiagnosticSelector(RoundedCombobox):
    def __init__(self, parent, *, chooser_parent, **kwargs):
        self.chooser_parent = chooser_parent
        self.chooser = None
        self._filter_trace = None
        super().__init__(parent, **kwargs)
        for event in ('<ButtonPress-1>', '<Down>', '<Alt-Down>', '<space>', '<Return>', '<F4>'):
            self.bind(event, self.open_choices)

    def apply_palette(self, palette):
        super().apply_palette(palette)
        if self.chooser is not None and self.chooser.winfo_exists():
            self.chooser.apply_palette(palette)

    def open_choices(self, _event=None):
        if self.instate(['disabled']):
            return 'break'
        if self.chooser is not None and self.chooser.winfo_exists():
            self.search.focus_set()
            return 'break'
        self._choices = tuple(map(str, self['values']))
        sheet = self.chooser = InternalSheet(self.chooser_parent, 'Choose a diagnostic', self.palette)
        sheet.on_close = self.close_choices
        skin = sheet.skin
        skin.label(sheet.content, 'Choose a component, then use Run selected on the Maintenance page.',
                   muted=True).pack(fill='x', pady=(4, 8))
        skin.label(sheet.content, 'Search diagnostics').pack(fill='x')
        self.query = tk.StringVar(sheet)
        self.search = skin.entry(sheet.content, '')
        self.search.configure(textvariable=self.query)
        self.search.pack(fill='x', pady=(4, 8))
        box = skin.frame(sheet.content)
        box.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(box, show='tree', selectmode='browse', height=12)
        self.tree.column('#0', width=320, minwidth=140, stretch=True)
        self.tree.pack(fill='both', expand=True)
        sheet.style_tree(self.tree)
        self.count = skin.label(sheet.content, '', muted=True)
        self.count.pack(fill='x', pady=(6, 4))
        # Keep the actions above the scroll body so they remain reachable even
        # in a short window or with a long filtered list.
        self.choose_button = skin.button(sheet.heading, 'Use selection', self.choose)
        self.choose_button.pack(side='right', padx=4)
        skin.button(sheet.heading, 'Cancel', self.close_choices).pack(side='right', padx=4)
        self.tree.bind('<<TreeviewSelect>>', self._selection_changed)
        self.tree.bind('<Double-Button-1>', self.choose)
        self.tree.bind('<Return>', self.choose)
        self.search.bind('<Down>', self._focus_results)
        self._filter_trace = self.query.trace_add('write', self._filter)
        self._filter()
        sheet.finish()
        self.search.focus_set()
        return 'break'

    def _filter(self, *_args):
        needle = self.query.get().strip().casefold()
        selected = self.tree.selection()
        prior = self.tree.item(selected[0], 'text') if selected else self.get()
        self.tree.delete(*self.tree.get_children())
        for index, label in enumerate(self._choices):
            if needle in label.casefold():
                key = str(index)
                self.tree.insert('', 'end', iid=key, text=label)
                if label == prior:
                    self.tree.selection_set(key)
                    self.tree.focus(key)
        self.tree.yview_moveto(0)
        self.count.configure(text=f'{len(self.tree.get_children())} of {len(self._choices)} diagnostics')
        self._selection_changed()

    def _selection_changed(self, _event=None):
        self.choose_button.configure(state='normal' if self.tree.selection() else 'disabled')

    def _focus_results(self, _event=None):
        children = self.tree.get_children()
        if children:
            if not self.tree.selection():
                self.tree.selection_set(children[0])
                self.tree.focus(children[0])
            self.tree.focus_set()
        return 'break'

    def choose(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return 'break'
        value = self.tree.item(selected[0], 'text')
        # A catalog change while this sheet is open cannot commit a stale value.
        if value not in tuple(map(str, self['values'])) or self.instate(['disabled']):
            return 'break'
        self.set(value)
        self.close_choices()
        self.event_generate('<<ComboboxSelected>>')
        return 'break'

    def close_choices(self):
        sheet, self.chooser = self.chooser, None
        if self._filter_trace is not None:
            self.query.trace_remove('write', self._filter_trace)
            self._filter_trace = None
        if sheet is not None and sheet.winfo_exists():
            sheet.destroy()
        if self.winfo_exists() and self.winfo_ismapped():
            self.focus_set()

    def _destroyed(self, event):
        if event.widget is self:
            self.close_choices()
        super()._destroyed(event)
