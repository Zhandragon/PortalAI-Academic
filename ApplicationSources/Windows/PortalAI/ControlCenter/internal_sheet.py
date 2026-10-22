"""Scrollable application sheets inside the launcher; no secondary OS window."""
import tkinter as tk
from tkinter import ttk
from ui_style_cache import cached_style
from settings_style import SettingsSkin
from ornate_ui import ConnectedBorder


class InternalSheet(tk.Frame):
    def __init__(self, parent, title, colors, *, embedded=False, framed=True):
        host = parent if embedded else getattr(parent, '_portalai_account_host', parent)
        self.colors = {'bg':'#EFE8DC', 'panel':'#F8F3EA', 'panel2':'#E9E0D2',
            'text':'#202224', 'muted':'#6E665E', 'accent':'#3E91A2', **colors}
        super().__init__(host, bg=self.colors['bg' if framed else 'panel'], bd=0)
        self.title = title
        self.embedded=embedded
        self.trees = []
        self.on_close = self.destroy
        if embedded:self.pack(fill='both',expand=True)
        else:self.place(x=0, y=0, relwidth=1, relheight=1); self.lift()
        self.skin = skin = SettingsSkin(self, self.colors)
        card = skin.frame(self, surface='panel')
        card.pack(fill='both', expand=True, padx=10 if framed else 0, pady=8 if framed else 0)
        if framed:skin.borders.append(ConnectedBorder(card, skin.colors, radius=18))
        inset = skin.frame(card, surface='panel'); inset.pack(fill='both', expand=True, padx=12 if framed else 0, pady=(8 if embedded else 12) if framed else 0)
        head = skin.frame(inset, surface='panel2'); head.pack(fill='x')
        self.heading = head
        heading_border = ConnectedBorder(head, skin.colors, radius=12, simple=True, filigree=False)
        heading_border.simple_radius = 12
        skin.borders.append(heading_border)
        skin.label(head, title, heading=True, surface='panel2').pack(side='left', fill='x', expand=True, padx=16, pady=6 if embedded else 8)
        if not embedded:skin.button(head, '✕', lambda: self.on_close()).pack(side='right', padx=4)
        self.content = skin.scrolling_body(inset)
        for widget, roles in skin.widgets:
            if widget is self.content:
                roles['bg'] = 'panel'
                skin._paint(widget, roles)
        self._escape = None if embedded else self.winfo_toplevel().bind('<Escape>', lambda event: self._escape_close(), add='+')
        if not embedded:self.focus_set()

    def _escape_close(self):
        children = [c for c in self.winfo_children() if isinstance(c, InternalSheet)]
        if children: children[-1].on_close()
        else: self.on_close()
        return 'break'

    def style_tree(self, tree):
        self.trees.append(tree)
        self._tree_palette(tree)
        from chat_layout import HorizontalFiligreeScrollbar
        scrollbar = HorizontalFiligreeScrollbar(tree.master,command=tree.xview,palette=self.skin.colors)
        scrollbar.pack(fill='x',after=tree)
        tree.configure(xscrollcommand=scrollbar.set)
        from ornate_ui import FiligreeScrollbar
        vertical=FiligreeScrollbar(tree.master,command=tree.yview,palette=self.skin.colors,height=1)
        vertical.pack(side='right',fill='y',before=tree)
        tree.configure(yscrollcommand=vertical.set);self.skin.scrollbars.append(vertical)

    def _tree_palette(self, tree):
        p = self.skin.colors
        from rounded_controls import image_element
        field = image_element(tree,p['panel2'],p['gold_mid'],radius=10,border=(11,11,11,11))
        def build(style, name):
            if 'PortalSheet.Treeview.field' not in style.element_names():
                style.element_create('PortalSheet.Treeview.field','from','clam','Treeview.field')
            for element in ('cell','border'):
                if 'PortalSheet.Treeheading.'+element not in style.element_names():
                    style.element_create('PortalSheet.Treeheading.'+element,'from','clam','Treeheading.'+element)
            style.layout(name+'.Heading',[
                ('PortalSheet.Treeheading.cell',{'sticky':'nswe'}),
                ('PortalSheet.Treeheading.border',{'sticky':'nswe','children':[
                    ('Treeheading.padding',{'sticky':'nswe','children':[
                        ('Treeheading.image',{'side':'right','sticky':''}),('Treeheading.text',{'sticky':'we'})]})]})])
            style.layout(name,[(field,{'sticky':'nswe','children':[
                ('Treeview.padding',{'sticky':'nswe','children':[('Treeview.treearea',{'sticky':'nswe'})]})]})])
            style.configure(name, background=p['panel2'], fieldbackground=p['panel2'], foreground=p['text'], rowheight=24,
                            bordercolor=p['gold_mid'],lightcolor=p['gold_mid'],darkcolor=p['gold_mid'],borderwidth=1)
            style.configure(name+'.Heading', background=p['panel'], foreground=p['text'],bordercolor=p['gold_mid'],
                            lightcolor=p['panel'],darkcolor=p['panel'])
        signature = (field,p['panel2'],p['gold_mid'],p['text'],p['panel'])
        name = cached_style(tree, 'Sheet.Treeview', signature, build)
        if tree.cget('style') != name: tree.configure(style=name)

    def apply_palette(self, colors):
        self.colors.update(colors); self.configure(bg=colors['bg'])
        self.skin.apply_palette(colors)
        for tree in self.trees:
            if tree.winfo_exists(): self._tree_palette(tree)
        from chat_layout import HorizontalFiligreeScrollbar
        def walk(widget):
            for child in widget.winfo_children():
                # Text fields and trees retain their own native scrolling. Other
                # descendants scroll this sheet, not the launcher behind it.
                if not isinstance(child,(tk.Text,ttk.Treeview,ttk.Combobox,ttk.Entry,tk.Entry)):
                    for event in ('<MouseWheel>','<Button-4>','<Button-5>'):
                        child.bind(event,self.skin._wheel)
                if isinstance(child, HorizontalFiligreeScrollbar): child.apply_palette(colors)
                if isinstance(child, InternalSheet): child.apply_palette(colors)
                else: walk(child)
        walk(self)

    def finish(self):
        """Constrain plain legacy labels and style fields without changing actions."""
        registered = {widget for widget, _roles in self.skin.widgets}
        def palette_role(widget, option, candidates):
            value = widget.winfo_rgb(widget.cget(option))
            return next((key for key in candidates
                         if value == widget.winfo_rgb(self.skin.colors[key])), None)
        def walk(widget):
            for child in widget.winfo_children():
                if not isinstance(child,(tk.Text,ttk.Treeview,ttk.Combobox,ttk.Entry,tk.Entry)):
                    for event in ('<MouseWheel>','<Button-4>','<Button-5>'):child.bind(event,self.skin._wheel)
                if isinstance(child,tk.Label) and not isinstance(child,ttk.Label):
                    if child.cget('wraplength'):
                        parent=child.master
                        parent.bind('<Configure>',lambda event,w=child:w.configure(wraplength=max(100,event.width-30)) if w.winfo_exists() else None,add='+')
                # Legacy sheet builders use plain Tk labels and responsive frames.
                # Remember their existing color roles so a theme change reaches
                # those surfaces too, while custom controls keep their own painter.
                if isinstance(child, (tk.Frame, tk.Label)) and child not in registered:
                    roles = {}
                    background = palette_role(child, 'bg', ('panel', 'panel2', 'bg'))
                    if background: roles['bg'] = background
                    if isinstance(child, tk.Label):
                        foreground = palette_role(child, 'fg', ('text', 'accent', 'muted'))
                        if foreground: roles['fg'] = foreground
                    if roles:
                        self.skin.remember(child, **roles)
                        registered.add(child)
                if isinstance(child,tk.Text):
                    child.configure(bg=self.skin.colors['panel2'],fg=self.skin.colors['text'],
                                    insertbackground=self.skin.colors['text'],bd=0,highlightthickness=0,highlightbackground=self.skin.colors['gold_mid'])
                    from rounded_text import RoundedText
                    if isinstance(child,RoundedText):
                        child.apply_palette(self.skin.colors)
                        if child not in self.skin.gold_controls:self.skin.gold_controls.append(child)
                    elif child not in registered:
                        self.skin.remember(child, bg='panel2', fg='text', insertbackground='text', highlightbackground='gold_mid')
                        registered.add(child)
                walk(child)
        walk(self.content)

    def destroy(self):
        if self._escape:
            self.winfo_toplevel().unbind('<Escape>', self._escape); self._escape = None
        super().destroy()
