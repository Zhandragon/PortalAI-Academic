"""Account sheets inside the existing launcher, with no secondary Tk windows."""
from pathlib import Path
import tkinter as tk
from portal_frontend_v15136 import portal_display_font
from tkinter import ttk

from elegant_native_ui import ElegantButton
from ornate_ui import ConnectedBorder, heading_font
from modal_backdrop import snapshot_host, DimBackdrop, dim_color
from modal_guard import set_modal_surface


def prepare_login_shell(app, root, colors):
    """Only public branding is constructed before authentication."""
    app._portalai_account_root = Path(root)
    if getattr(app, '_portalai_shell_ready', False):
        # The real launcher has already created its permanent ornate chrome.
        # Do not reset its title, geometry, mapping or native window style.
        return
    app.title('PortalAI · Sign in')
    app.configure(bg=colors.get('bg', '#EFE8DC'))
    app.minsize(500, 400)
    width = min(1260, max(860, int(app.winfo_screenwidth()*.76)))
    height = min(820, max(620, int(app.winfo_screenheight()*.76)))
    app.geometry(f'{width}x{height}+{max(0,(app.winfo_screenwidth()-width)//2)}+{max(0,(app.winfo_screenheight()-height)//2)}')
    icon = Path(root)/'ControlCenter/PortableAI.ico'
    if icon.is_file():
        try: app.iconbitmap(default=str(icon))
        except tk.TclError: pass
    app.deiconify()


def refresh_account_theme(app, colors):
    for dialog in list(getattr(app, '_portalai_account_dialogs', ())):
        if not dialog.closed:
            dialog.apply_palette(colors)


def lock_account_surfaces(app, colors):
    """Freeze the last view and block input while preserving launcher chrome."""
    host = getattr(app, '_portalai_login_host', app)
    cover = getattr(app, '_portalai_account_lock_cover', None)
    if cover is None or not cover.winfo_exists():
        dialogs = [d for d in getattr(app, '_portalai_account_dialogs', ()) if not d.closed]
        snapshot = dialogs[0].surface.snapshot if dialogs else snapshot_host(app, host, colors)
        app._portalai_account_lock_snapshot = snapshot
        cover = tk.Frame(app, bg=colors.get('bg', '#EFE8DC'))
        cover._backdrop = DimBackdrop(cover, snapshot, colors)
        app._portalai_account_lock_cover = cover
        def layout(_event=None):
            cover.place(x=host.winfo_rootx()-app.winfo_rootx(), y=host.winfo_rooty()-app.winfo_rooty(),
                        width=host.winfo_width(),height=host.winfo_height())
        cover._layout_binding=app.bind('<Configure>',lambda e:layout() if e.widget is app else None,add='+')
        cover._layout=layout
    cover._layout()
    cover.lift()
    # Shutdown can begin from the notification area. Show only the opaque
    # cover, never an uncovered private window while bringing it back.
    app.deiconify()
    app.lift()
    cover.focus_set()
    # Before the shutdown sheet exists, no content widget is allowed input.
    from types import SimpleNamespace
    set_modal_surface(app, SimpleNamespace(card=cover, on_close=lambda:None))
    dialogs = [dialog for dialog in getattr(app, '_portalai_account_dialogs', ()) if not dialog.closed]
    if dialogs:
        dialogs[-1].surface.show_locked()


class AccountSurface:
    """Opaque ornate card over an inert dimmed view, below permanent chrome."""
    def __init__(self, parent, title, colors, *, startup=False):
        self.app = parent.winfo_toplevel()
        self.startup = startup
        login_host = getattr(self.app, '_portalai_login_host', None) if startup else None
        self.full_window = startup and login_host is None
        self.palette = dict(colors)
        self.on_close = lambda: None
        try:
            self.previous_focus = self.app.focus_get()
        except (KeyError, tk.TclError):
            # Tk owns combobox popdown widgets that have no Python wrapper.
            self.previous_focus = None
        self.host = getattr(self.app, '_portalai_login_host', None) or login_host or getattr(self.app, '_portalai_account_host', self.app)
        dialogs = [d for d in getattr(self.app, '_portalai_account_dialogs', ()) if not d.closed]
        if hasattr(self.app, '_portalai_account_lock_snapshot'):
            self.snapshot = self.app._portalai_account_lock_snapshot
        elif dialogs:
            self.snapshot = dialogs[0].surface.snapshot
        else:
            self.snapshot = snapshot_host(self.app, self.host, colors)
        self.overlay = tk.Frame(self.app, bg=colors.get('bg', '#EFE8DC'), bd=0, takefocus=0, cursor='arrow')
        self.backdrop = DimBackdrop(self.overlay, self.snapshot, colors)
        self.card = tk.Frame(self.overlay, bg=colors.get('panel', '#F8F3EA'), bd=0)
        self.border = ConnectedBorder(self.card, colors, radius=18, shine=True, filigree=True)
        self.inset = tk.Frame(self.card, bg=colors.get('panel', '#F8F3EA'))
        self.inset.pack(fill='both', expand=True, padx=12, pady=12)
        self.head = tk.Frame(self.inset, bg=colors.get('panel2', '#E9E0D2'))
        self.head.pack(fill='x')
        self.head_border = ConnectedBorder(self.head,colors,radius=11,simple=True,filigree=False)
        self.head_border.simple_radius = 11
        self.title = tk.Label(self.head, text=title, anchor='w',
                              bg=colors.get('panel2', '#E9E0D2'), fg=colors.get('text', '#202224'),
                              font=(portal_display_font(self.app), 12, 'bold'), padx=4, pady=5)
        self.title.pack(side='left', fill='x', expand=True,padx=(8,0),pady=4)
        self.close_button = ElegantButton(self.head, text='Close', command=lambda:self.on_close(),
            bg=colors.get('button', '#E6DCCB'), fg=colors.get('text', '#202224'), padx=10, pady=5, bd=0, cursor='hand2')
        self.close_button.pack(side='right', padx=8, pady=4)
        self.content = tk.Frame(self.inset, bg=colors.get('panel', '#F8F3EA'))
        self.content.pack(fill='both', expand=True)
        self.images = []
        if startup:
            self.brand = tk.Frame(self.content, bg=colors.get('panel', '#F8F3EA'))
            self.brand.pack(fill='x', padx=14, pady=(12, 4))
            root = getattr(self.app, '_portalai_account_root', Path(__file__).resolve().parents[1])
            for name, side in (('PortableAI_Header_72.png', 'right'),
                               ('PortalAI_Wordmark_Welcome_320.png', 'left')):
                try:
                    photo = tk.PhotoImage(master=self.app, file=str(Path(root)/'ControlCenter/Branding'/name))
                except (OSError, tk.TclError):
                    continue
                self.images.append(photo)
                label=tk.Label(self.brand, image=photo, bg=colors.get('panel', '#F8F3EA'), bd=0)
                label.pack(side=side, padx=4)
                if side=='left':
                    try:
                        small=tk.PhotoImage(master=self.app,file=str(Path(root)/'ControlCenter/Branding/PortalAI_Wordmark_Welcome_240.png'))
                        self.images.append(small)
                        self.brand.bind('<Configure>',lambda event,w=label,large=photo,small=small:
                                        w.configure(image=small if event.width<460 else large))
                    except (OSError,tk.TclError):pass
            if not self.images:
                tk.Label(self.brand, text='PortalAI', font=(portal_display_font(self.app), 28, 'bold'),
                         bg=colors.get('panel', '#F8F3EA'), fg=colors.get('text', '#202224')).pack()
        self.moved = None
        self._drag = None
        if not startup:
            for widget in (self.head, self.title, self.head_border.canvas):
                widget.configure(cursor='fleur')
                widget.bind('<ButtonPress-1>', self._drag_start)
                widget.bind('<B1-Motion>', self._drag_move)
        self._layout_binding = self.app.bind('<Configure>', self._layout_event, add='+')
        self._escape_binding = self.app.bind('<Escape>', self._escape, add='+')
        self.layout()
        self.overlay.lift()

    def _escape(self, _event):
        dialogs = [d for d in getattr(self.app, '_portalai_account_dialogs', ()) if not d.closed]
        if dialogs and dialogs[-1].surface is self:
            self.on_close()
            return 'break'

    def _layout_event(self, event):
        if event.widget in (self.app, self.host):
            self.layout()

    def layout(self):
        if not self.overlay.winfo_exists(): return
        if self.full_window or self.host is self.app:
            x = y = 0; width = self.app.winfo_width(); height = self.app.winfo_height()
        else:
            x = self.host.winfo_rootx()-self.app.winfo_rootx()
            y = self.host.winfo_rooty()-self.app.winfo_rooty()
            width = self.host.winfo_width(); height = self.host.winfo_height()
        self.overlay.place(x=x, y=y, width=max(1,width), height=max(1,height))
        card_width = min(690 if self.startup else 720, max(1, width-32))
        card_height = min(getattr(self, "preferred_height", 740), max(1, height-28))
        left, top = self.moved or ((width-card_width)//2, (height-card_height)//2)
        left = max(8, min(left, max(8,width-card_width-8)))
        top = max(8, min(top, max(8,height-card_height-8)))
        self.card.place(x=left,y=top,width=card_width,height=card_height)

    def _drag_start(self, event):
        self._drag = (event.x_root, event.y_root, self.card.winfo_x(), self.card.winfo_y())

    def _drag_move(self, event):
        if self._drag is None:return
        x,y,left,top = self._drag
        self.moved = (left+event.x_root-x, top+event.y_root-y)
        self.layout()

    def show_locked(self):
        self.layout()
        self.overlay.lift()
        self.app.deiconify()
        set_modal_surface(self.app, self)
        self.card.focus_set()

    def palette_changed(self, colors):
        self.palette = dict(colors)
        self.overlay.configure(bg=dim_color(colors.get('bg','#202123')))
        self.border.apply_palette(colors)
        self.head_border.apply_palette(colors)
        self.backdrop.apply_palette(colors)
        style=ttk.Style(self.app)
        # Windows' native read-only field ignores fieldbackground. Reuse Tk's
        # bundled clam field/arrow elements only for these account selectors.
        if 'PortalAccount.field' not in style.element_names():
            style.element_create('PortalAccount.field','from','clam','Combobox.field')
            style.element_create('PortalAccount.downarrow','from','clam','Combobox.downarrow')
        style.layout('PortalAccount.TCombobox',[
            ('PortalAccount.field',{'sticky':'nswe','children':[
                ('PortalAccount.downarrow',{'side':'right','sticky':'ns'}),
                ('Combobox.padding',{'expand':1,'sticky':'nswe','children':[
                    ('Combobox.textarea',{'sticky':'nswe'})]})]})])
        style.configure('PortalAccount.TCombobox',
            fieldbackground=colors.get('panel2','#E9E0D2'), background=colors.get('button','#E6DCCB'),
            foreground=colors.get('text','#202224'), arrowcolor=colors.get('accent','#3E91A2'),
            bordercolor=colors.get('border','#7B5A22'),padding=5)
        style.map('PortalAccount.TCombobox',
            fieldbackground=[('readonly',colors.get('panel2','#E9E0D2'))],
            foreground=[('readonly',colors.get('text','#202224'))])

    def destroy(self):
        for event, binding in (('<Configure>',self._layout_binding),('<Escape>',self._escape_binding)):
            try:self.app.unbind(event,binding)
            except tk.TclError:pass
        self.backdrop.close()
        self.snapshot = None
        self.overlay.destroy()
        dialogs = [d for d in getattr(self.app, '_portalai_account_dialogs', ()) if not d.closed]
        if dialogs:
            dialogs[-1].win.lift(); set_modal_surface(self.app, dialogs[-1].surface)
        elif getattr(self.app, '_portalai_account_lock_cover', None) is not None:
            from types import SimpleNamespace
            set_modal_surface(self.app, SimpleNamespace(card=self.app._portalai_account_lock_cover, on_close=lambda:None))
        else:
            set_modal_surface(self.app, None)
        if not dialogs and self.previous_focus is not None:
            try:self.previous_focus.focus_set()
            except tk.TclError:pass
