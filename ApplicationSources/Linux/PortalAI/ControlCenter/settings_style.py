"""Shared ornamental settings surfaces; no settings or account policy changes."""
import itertools
import tkinter as tk
from portal_frontend_v15136 import portal_display_font
from tkinter import ttk
from ui_style_cache import cached_style

from elegant_native_ui import ElegantButton, ui_font
from ornate_ui import ConnectedBorder, FiligreeScrollbar, heading_font
from rounded_controls import RoundedCombobox, RoundedEntry

_STYLE_IDS = itertools.count()


def settings_palette(colors):
    return {**colors,
            'gold_mid': colors.get('gold_mid', colors.get('gold', '#A87D32')),
            'gold_shine': colors.get('gold_shine', '#D9BE78'),
            'accent': colors.get('accent', colors.get('cyan', '#3E91A2')),
            'button': colors.get('button', colors.get('panel2', '#E9E0D2')),
            'panel3': colors.get('panel3', colors.get('panel2', '#E9E0D2')),
            'shadow': colors.get('shadow', '#2B2419')}


class SettingsSkin:
    """Explicit palette roles avoid global ttk or unrelated-widget restyling."""
    def __init__(self, host, colors, *, section_subtitles=False, row_connectors=False, compact=False, section_padx=10):
        self.host = host
        self.section_subtitles=section_subtitles
        self.row_connectors=row_connectors
        self.compact=compact;self.section_padx=section_padx
        self.colors = settings_palette(colors)
        self.widgets = []
        self.borders = []
        self.scrollbars = []
        self.combos = []
        self.tabsets = []
        self.gold_controls = []
        self.canvas = None
        self.combo_style = f'PortalSettings{next(_STYLE_IDS)}.TCombobox'
        self.scroll_style = self.combo_style.replace('TCombobox', 'Vertical.TScrollbar')
        self.popup_style = self.combo_style.replace('TCombobox', 'TFrame')
        self._style_selectors()

    def remember(self, widget, **roles):
        self.widgets.append((widget, roles))
        self._paint(widget, roles)
        if self.canvas is not None:
            widget.bind('<MouseWheel>', self._wheel, add='+')
            widget.bind('<Button-4>', self._wheel, add='+')
            widget.bind('<Button-5>', self._wheel, add='+')
        return widget

    def _paint(self, widget, roles):
        widget.configure(**{option: self.colors[key] for option, key in roles.items()})

    def frame(self, parent, *, surface='panel', **options):
        return self.remember(tk.Frame(parent, bd=0, **options), bg=surface)

    def label(self, parent, text='', *, muted=False, heading=False, surface='panel', **options):
        font=options.pop('font',(portal_display_font(parent) if heading else ui_font(parent),
                                12 if heading else 9, 'bold' if heading else 'normal'))
        widget = tk.Label(parent, text=text, anchor='w', justify='left', width=options.pop('width',1),font=font,**options)
        self.remember(widget, bg=surface, fg='muted' if muted else 'text')
        widget.bind('<Configure>', lambda event: widget.configure(wraplength=max(40, event.width-4)), add='+')
        return widget

    def section(self, parent, title):
        card = self.frame(parent)
        card.pack(fill='x', padx=self.section_padx, pady=(4, 6) if self.compact else (6, 8))
        border = ConnectedBorder(card, self.colors, radius=15, filigree=True)
        self.borders.append(border)
        content = self.frame(card)
        content.pack(fill='both', expand=True, padx=15, pady=8 if self.compact else 12)
        if self.section_subtitles:
            caption=self.label(content,title,font=(ui_font(parent),10,'bold'))
            self.remember(caption,fg='accent')
        else:caption=self.label(content,title,heading=True)
        caption.pack(fill='x',pady=(1,8))
        return content

    def row(self, parent, title, field):
        row = self.frame(parent)
        row.pack(fill='x', pady=2 if self.compact else 4)
        row.columnconfigure(0, weight=3, minsize=90)
        row.columnconfigure(1, weight=2, minsize=90)
        if self.row_connectors:
            caption=self.frame(row)
            text=self.label(caption,title,muted=True,width=0,font=(ui_font(row),9,'bold'))
            text.pack(side='left')
            line=self.frame(caption,surface='gold_mid',height=1)
            line.pack(side='left',fill='x',expand=True,padx=(12,0))
        else:caption = self.label(row, title)
        # Build the input inside its actual row, so both columns own their size.
        widget = field(row)
        layout = [None]
        def reflow(event):
            stacked = event.width < 430
            if layout[0] == stacked:
                return
            layout[0] = stacked
            if self.row_connectors:
                if stacked:line.pack_forget()
                else:line.pack(side='left',fill='x',expand=True,padx=(12,0))
            caption.grid(row=0, column=0, columnspan=2 if stacked else 1,
                         sticky='ew', padx=(0, 0 if stacked else 12), pady=(0, 3 if stacked else 0))
            widget.grid(row=1 if stacked else 0, column=0 if stacked else 1,
                        columnspan=2 if stacked else 1, sticky='ew', ipady=0 if self.compact else 3)
        row.bind('<Configure>', reflow, add='+')
        reflow(type('Size', (), {'width': max(1, parent.winfo_width())})())
        return widget

    def entry(self, parent, value):
        widget = RoundedEntry(parent,width=10,palette=self.colors)
        self.gold_controls.append(widget);self.remember(widget)
        widget.insert(0, str(value))
        return widget

    def combo(self, parent, variable, options):
        widget = RoundedCombobox(parent, textvariable=variable, values=options, state='readonly',
                                 width=10, palette=self.colors)
        self._paint_popup(widget)
        self.combos.append(widget)
        self.remember(widget)
        return widget

    def number(self, parent, variable, *, maximum, minimum=0, step=1):
        """One value, with a stepped slider and an editable increment selector."""
        import math
        row = self.frame(parent)
        slider_value = tk.DoubleVar(row, value=float(variable.get()))
        from gold_controls import GoldScale,GoldSpinbox
        scale = GoldScale(row,from_=minimum,to=maximum,resolution=step,variable=slider_value,palette=self.colors)
        scale.pack(side='left', fill='x', expand=True)
        entry = GoldSpinbox(row,from_=minimum,to=maximum,increment=step,textvariable=variable,width=7,palette=self.colors)
        self.gold_controls.extend((scale,entry))
        entry.pack(side='right', padx=(6, 0), ipady=0 if self.compact else 4)
        updating = [False]
        def text_changed(*_):
            if updating[0]: return
            try: value = float(variable.get())
            except ValueError: return
            if math.isfinite(value) and minimum <= value <= maximum:
                updating[0] = True
                slider_value.set(value); updating[0] = False
        def slid(*_):
            if updating[0]: return
            updating[0] = True
            variable.set(f'{slider_value.get():g}'); updating[0] = False
        trace = variable.trace_add('write', text_changed)
        slider_value.trace_add('write', slid)
        row.bind('<Destroy>', lambda event: variable.trace_remove('write', trace) if event.widget is row else None, add='+')
        return row

    def button(self, parent, text, command, *, state='normal'):
        return self.remember(ElegantButton(parent, text=text, command=command, state=state,
                            padx=13, pady=7, bd=0, cursor='hand2'),
                             bg='button', fg='text', activebackground='panel3', activeforeground='text')

    def ornate_button(self, parent, text, command):
        frame=self.frame(parent,surface='panel2')
        self.borders.append(ConnectedBorder(frame,self.colors,radius=12))
        self.button(frame,text,command).pack(padx=7,pady=7)
        return frame

    def check(self, parent, text, variable):
        widget = self.remember(tk.Checkbutton(parent, text=text, variable=variable, anchor='w',
                               justify='left', bd=0, highlightthickness=0), bg='panel', fg='text',
                               selectcolor='panel2', activebackground='panel', activeforeground='text')
        widget.pack(fill='x', pady=3)
        widget.bind('<Configure>', lambda event: widget.configure(wraplength=max(40,event.width-32)), add='+')
        return widget

    def actions(self, parent, factories):
        row = self.frame(parent)
        row.pack(fill='x', pady=5)
        buttons = [factory(row) for factory in factories]
        for index, widget in enumerate(buttons):
            widget.grid(row=0, column=index, sticky='w', padx=(0, 7), pady=3)
        previous = [None]
        def reflow(event):
            limit = max(1, event.width)
            positions = []
            line = col = used = 0
            for widget in buttons:
                width = widget.winfo_reqwidth()+7
                if used and used+width > limit:
                    line += 1; col = used = 0
                positions.append((line,col)); used += width; col += 1
            if previous[0] != positions:
                previous[0] = positions
                for widget, (line,col) in zip(buttons, positions):
                    widget.grid_configure(row=line, column=col)
        row.bind('<Configure>', reflow, add='+')
        return buttons

    def scrolling_body(self, body):
        shell = self.frame(body, surface='bg')
        shell.pack(fill='both', expand=True)
        canvas = tk.Canvas(shell, bd=0, highlightthickness=0)
        self.canvas = canvas
        self.remember(canvas, bg='bg')
        scrollbar = FiligreeScrollbar(shell, command=canvas.yview, palette=self.colors, width=15)
        self.scrollbars.append(scrollbar)
        inner = self.frame(canvas, surface='bg')
        window = canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        from page_scroll import bind_page_scroll
        bind_page_scroll(canvas, inner, window)
        return inner

    def _wheel(self, event):
        if self.canvas is None or not self.canvas.winfo_exists():
            return
        delta = getattr(event, 'delta', 0)
        direction = -1 if getattr(event, 'num', 0) == 4 or delta > 0 else 1
        units = max(1, int(abs(delta)/120)) if delta else 1
        self.canvas.yview_scroll(direction*units, 'units')
        return 'break'

    def _style_selectors(self):
        p = self.colors
        signature = tuple(p[key] for key in ('panel2','text','button','gold_mid','accent','panel','gold_shine'))
        self.combo_style = cached_style(self.host, 'Settings.TCombobox', signature, self._build_selector_styles)
        self.scroll_style = self.combo_style.replace('TCombobox', 'Vertical.TScrollbar')
        self.popup_style = self.combo_style.replace('TCombobox', 'TFrame')

    def _build_selector_styles(self, style, name):
        scroll_name = name.replace('TCombobox', 'Vertical.TScrollbar')
        popup_name = name.replace('TCombobox', 'TFrame')
        if 'PortalSettings.field' not in style.element_names():
            style.element_create('PortalSettings.field', 'from', 'clam', 'Combobox.field')
            style.element_create('PortalSettings.downarrow', 'from', 'clam', 'Combobox.downarrow')
            for part in ('trough', 'thumb', 'uparrow', 'downarrow'):
                element_name = 'Vertical.Scrollbar.'+part
                style.element_create('PortalSettings.'+element_name, 'from', 'clam', element_name)
        style.layout(name, [('PortalSettings.field', {'sticky':'nswe','children':[
            ('PortalSettings.downarrow', {'side':'right','sticky':'ns'}),
            ('Combobox.padding', {'expand':1,'sticky':'nswe','children':[
                ('Combobox.textarea', {'sticky':'nswe'})]})]})])
        p = self.colors
        style.configure(name, fieldbackground=p['panel2'], foreground=p['text'],
                        background=p['button'], arrowcolor=p['gold_mid'], bordercolor=p['gold_mid'],
                        lightcolor=p['gold_mid'], darkcolor=p['gold_mid'], padding=5)
        style.map(name, fieldbackground=[('readonly',p['panel2'])],
                  foreground=[('readonly',p['text'])], selectbackground=[('readonly',p['accent'])],
                  selectforeground=[('readonly',p['text'])])
        # The popup list belongs to Tcl's combobox, not our Python widget tree.
        style.layout(scroll_name, [('PortalSettings.Vertical.Scrollbar.trough', {'sticky':'ns', 'children':[
            ('PortalSettings.Vertical.Scrollbar.uparrow', {'side':'top','sticky':''}),
            ('PortalSettings.Vertical.Scrollbar.downarrow', {'side':'bottom','sticky':''}),
            ('PortalSettings.Vertical.Scrollbar.thumb', {'expand':1,'sticky':'nswe'})]})])
        style.configure(scroll_name, background=p['gold_mid'], troughcolor=p['panel'],
                        arrowcolor=p['gold_shine'], bordercolor=p['gold_mid'],
                        lightcolor=p['gold_shine'], darkcolor=p['gold_mid'])
        style.configure(popup_name, background=p['panel'], bordercolor=p['gold_mid'], relief='solid', borderwidth=1)

    def _paint_popup(self, combo):
        combo.apply_palette(self.colors)
        popdown = combo.tk.call('ttk::combobox::PopdownWindow', str(combo))
        p = self.colors
        combo.tk.call(str(popdown)+'.f.l', 'configure', '-background', p['panel2'], '-foreground', p['text'],
                      '-selectbackground', p['accent'], '-selectforeground', p['text'],
                      '-highlightbackground', p['gold_mid'])
        combo.tk.call(str(popdown)+'.f.sb', 'configure', '-style', self.scroll_style)

    def apply_palette(self, colors):
        self.colors = settings_palette(colors)
        self._style_selectors()
        for widget, roles in self.widgets:
            if widget.winfo_exists(): self._paint(widget, roles)
        for border in self.borders: border.apply_palette(self.colors)
        for scrollbar in self.scrollbars: scrollbar.apply_palette(self.colors)
        for combo in self.combos:
            if combo.winfo_exists(): self._paint_popup(combo)
        for tabs in self.tabsets: tabs.refresh()
        for control in self.gold_controls:
            if control.winfo_exists():control.apply_palette(self.colors)


class SettingsTabs:
    """Wrapping, keyboard-accessible tabs sharing one scroll area and footer."""
    def __init__(self, parent, skin):
        from ui_extensions import ResponsiveFlow
        self.skin = skin
        skin.tabsets.append(self)
        self.bar = ResponsiveFlow(parent, bg=skin.colors['bg'], hgap=4, vgap=4)
        skin.remember(self.bar, bg='bg')
        self.bar.pack(fill='x', padx=10, pady=(8, 4))
        self.content = skin.scrolling_body(parent)
        self.content._portalai_native_tabs=self
        self.pages = {}; self.buttons = {}; self.selected = None

    def add(self, key, title):
        page = self.skin.frame(self.content, surface='bg')
        self.pages[key] = page
        page._portalai_native_tab=(self,key)
        button = self.skin.button(self.bar, title, lambda: self.select(key))
        button.configure(font=(portal_display_font(self.bar),9,'bold'))
        self.buttons[key] = button; self.bar.add(button)
        if self.selected is None: self.select(key)
        return page

    def select(self, key):
        controller=getattr(self.bar.winfo_toplevel(),'_portalai_native_workflow',None)
        if self.selected is not None and controller is not None and controller.active is not None:
            controller.select_tab(self,key)
            return
        if self.selected is not None: self.pages[self.selected].pack_forget()
        self.selected = key
        self.pages[key].pack(fill='x')
        self.refresh()
        self.skin.canvas.yview_moveto(0)

    def refresh(self):
        for name, button in self.buttons.items():
            if button.winfo_exists():
                button.configure(bg=self.skin.colors['gold_mid'] if name == self.selected else self.skin.colors['button'],
                                 fg=self.skin.colors['text'])
