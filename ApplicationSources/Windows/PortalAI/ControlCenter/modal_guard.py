"""Tk-only modal input shield; window chrome remains usable."""
import tkinter as tk


class ModalGuard:
    EVENTS = ('<ButtonPress>', '<ButtonRelease>', '<Motion>', '<Enter>', '<Leave>',
              '<KeyPress>', '<KeyRelease>', '<MouseWheel>', '<FocusIn>')

    def __init__(self, app):
        self.app = app
        self.surface = None
        self.tag = 'PortalModal' + str(id(self))
        self.tail = self.tag + 'Tail'
        self.paths = set()
        self.map_binding = None
        self.prior_grab = None
        self.binding_ids = []

    def allowed(self, path):
        for widget in (self.surface.card, getattr(self.app, '_portalai_chrome_widget', None)):
            if widget is not None and (path == str(widget) or path.startswith(str(widget)+'.')):
                return True
        return False

    def event(self, event):
        if self.surface is None: return
        if self.allowed(str(event.widget)): return
        if str(event.type) in ('9', 'FocusIn'):
            self.app.after_idle(self.focus)
        return 'break'

    def tail_event(self, event):
        # Card widgets keep their class bindings, but cannot invoke launcher
        # shortcuts through the toplevel/all bindtags behind the modal.
        if self.surface is None: return
        path = str(event.widget)
        if self.allowed(path):
            key=getattr(event,'keysym','')
            if str(event.type) in ('2','KeyPress'):
                if key=='Escape':self.surface.on_close()
                elif key in ('Tab','ISO_Left_Tab'):
                    self.advance_focus(path,reverse=key=='ISO_Left_Tab' or bool(event.state & 1))
            if path == str(self.surface.card) or path.startswith(str(self.surface.card)+'.'):
                canvas=getattr(self.surface,'scroll_canvas',None)
                if canvas is not None and str(event.type) in ('38','MouseWheel','4','ButtonPress'):
                    delta=getattr(event,'delta',0)
                    number=getattr(event,'num',None)
                    amount=(-max(1,abs(delta)//120) if delta>0 else max(1,abs(delta)//120)) if delta else (-1 if number==4 else 1 if number==5 else 0)
                    if amount and event.widget.winfo_class()!='TCombobox':canvas.yview_scroll(amount*3,'units')
            return 'break'

    def advance_focus(self, path, *, reverse=False):
        # Tk's normal Tab handler lives on `all`, which is intentionally
        # shielded. Retain traversal without visiting the locked background.
        command='tk_focusPrev' if reverse else 'tk_focusNext'
        candidate=path
        for _ in range(len(self.paths)+1):
            candidate=str(self.app.tk.call(command,candidate))
            if not candidate or candidate==path:return
            if self.allowed(candidate):
                self.app.tk.call('focus',candidate)
                return

    def install(self, path):
        try:
            tags = list(self.app.tk.splitlist(self.app.tk.call('bindtags', path)))
            tags = [tag for tag in tags if tag not in (self.tag, self.tail)]
            # Preserve widget/class handling, intercept before toplevel/all.
            split = min(2, len(tags))
            self.app.tk.call('bindtags', path, (self.tag, *tags[:split], self.tail, *tags[split:]))
            self.paths.add(str(path))
            for child in self.app.tk.splitlist(self.app.tk.call('winfo', 'children', path)):
                self.install(child)
        except tk.TclError: pass

    def focus(self):
        if self.surface is None: return
        try:
            focused = str(self.app.tk.call("focus"))
            if focused and self.allowed(focused): return
            self.surface.card.focus_set()
        except tk.TclError: pass

    def set(self, surface):
        first = self.surface is None
        self.surface = surface
        if first:
            self.prior_grab = self.app.grab_current()
            for event in self.EVENTS:
                self.binding_ids.append((self.tag,event,self.app.bind_class(self.tag,event,self.event)))
                self.binding_ids.append((self.tail,event,self.app.bind_class(self.tail,event,self.tail_event)))
            self.map_binding = self.app.bind('<Map>', lambda event:self.install(str(event.widget)), add='+')
            # ttk popdowns are Tcl widgets and use a different toplevel tag.
            self.all_map = self.app.bind_all('<Map>', lambda event:self.install(str(event.widget))
                                           if str(event.widget).startswith(str(self.surface.card)+'.') else None, add='+')
        self.install(str(self.app))
        self.app.grab_set()
        self.focus()

    def clear(self):
        if self.surface is None:return
        self.surface = None
        for path in self.paths:
            try:
                tags = self.app.tk.splitlist(self.app.tk.call('bindtags', path))
                self.app.tk.call('bindtags', path, tuple(t for t in tags if t not in (self.tag, self.tail)))
            except tk.TclError: pass
        self.paths.clear()
        for tag,event,binding in self.binding_ids:
            self.app._unbind(('bind',tag,event),binding)
        self.binding_ids.clear()
        if self.map_binding: self.app.unbind('<Map>', self.map_binding)
        if getattr(self, 'all_map', None): self.app._unbind(('bind', 'all', '<Map>'), self.all_map)
        self.map_binding=self.all_map=None
        try:
            if self.app.grab_current() is self.app: self.app.grab_release()
            if self.prior_grab is not None and self.prior_grab.winfo_exists(): self.prior_grab.grab_set()
        except tk.TclError: pass


def set_modal_surface(app, surface):
    guard = getattr(app, '_portalai_modal_guard', None)
    if guard is None:
        guard = app._portalai_modal_guard = ModalGuard(app)
    if surface is None: guard.clear()
    else: guard.set(surface)
