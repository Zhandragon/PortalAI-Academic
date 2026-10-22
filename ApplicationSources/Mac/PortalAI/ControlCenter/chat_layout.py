"""Ornate chat surfaces and a profile-owned, responsive history divider."""
import tkinter as tk

from conversation_cards import palette_for, refresh_borders
from ornate_ui import FiligreeScrollbar


def stored_width(value):
    try:
        return max(120, min(960, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 210


def pane_limits(total):
    total = max(40, int(total))
    main = min(360, max(120, total // 2))
    maximum = max(20, total - main - 11)
    return min(140, maximum), maximum, main


class HorizontalFiligreeScrollbar(tk.Canvas):
    """Horizontal counterpart of the launcher's gold vertical scrollbar."""
    def __init__(self, parent, *, command, palette):
        super().__init__(parent, height=15, bd=0, highlightthickness=0, takefocus=True)
        self.command, self.palette = command, palette
        self.first, self.last, self.offset = 0., 1., None
        self.bind('<Configure>', lambda _e: self._draw())
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Left>', lambda _e: self._unit(-1))
        self.bind('<Right>', lambda _e: self._unit(1))
        self.bind('<Home>', lambda _e: self._move(0))
        self.bind('<End>', lambda _e: self._move(1))
        self.apply_palette(palette)

    def apply_palette(self, palette):
        self.palette = palette
        self.configure(bg=palette['bg'])
        self._draw()

    def set(self, first, last):
        self.first, self.last = max(0., float(first)), min(1., float(last))
        self._draw()

    def _geometry(self):
        width = max(32, self.winfo_width())
        start, end = 14, width - 14
        visible = max(.02, min(1., self.last - self.first))
        thumb = min(end - start, max(24, (end - start) * visible))
        travel = max(1, end - start - thumb)
        left = start + travel * self.first / max(.0001, 1 - visible) if visible < .9999 else start
        return start, end, left, left + thumb, visible, travel

    def _draw(self):
        if not self.winfo_exists(): return
        start, end, left, right, visible, travel = self._geometry()
        gold, shine = self.palette.get('gold_mid', '#A87D32'), self.palette.get('gold_shine', '#D9BE78')
        self.delete('all')
        self.create_line(start, 7, end, 7, fill=gold)
        self.create_rectangle(left, 3, right, 11, fill=gold, outline=shine)
        if right-left > 32:
            cx = (left+right)/2
            self.create_line(cx-14,7,cx-8,4,cx-4,8,cx,7,cx+4,6,cx+8,10,cx+14,7,
                             smooth=True,fill=shine,tags='filigree')
        for x in (7, self.winfo_width() - 7):
            self.create_polygon(x-3, 7, x, 4, x+3, 7, x, 10, fill=shine, outline=gold)

    def _unit(self, direction):
        self.command('scroll', direction, 'units')
        return 'break'

    def _move(self, fraction):
        self.command('moveto', fraction)
        return 'break'

    def _press(self, event):
        start, end, left, right, visible, travel = self._geometry()
        if event.x < start: return self._unit(-3)
        if event.x > end: return self._unit(3)
        if left <= event.x <= right:
            self.offset = event.x - left
        else:
            self._move(max(0., min(1. - visible, (event.x - start) / max(1, end - start) - visible / 2)))
        return 'break'

    def _drag(self, event):
        if self.offset is not None:
            start, end, left, right, visible, travel = self._geometry()
            self._move(max(0., min(1. - visible, (event.x - self.offset - start) / travel * (1. - visible))))
        return 'break'

    def _release(self, _event):
        self.offset = None
        return 'break'


class ChatLayout:
    def __init__(self, panel):
        self.panel, self.app, self.pane = panel, panel.app, panel.body_pane
        self.wanted = stored_width(panel.settings.get('history_width_px', 210))
        self.closed = self.dragging = False
        self._save_after = self._layout_after = None
        self._bindings = []
        colors = self._palette(panel.COL['panel'])
        self.history_y = FiligreeScrollbar(panel.history_list_host, command=panel.session_list.yview, palette=colors)
        self.history_y.grid(row=0, column=1, sticky='ns')
        self.history_x = HorizontalFiligreeScrollbar(panel.history_list_host, command=panel.session_list.xview, palette=colors)
        self.history_x.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(3, 0))
        panel.session_list.configure(xscrollcommand=self.history_x.set, yscrollcommand=self.history_y.set)
        # ScrolledText retains its public Text API while its default scrollbar
        # is replaced by the same artwork as the surrounding launcher.
        panel.chat.vbar.pack_forget()
        panel.chat.vbar._portalai_replaced_scrollbar = True
        panel.chat.frame.configure(bg=panel.COL['bg'])
        self.conversation_y = FiligreeScrollbar(panel.chat.frame, command=panel.chat.yview,
                                                palette=self._palette(panel.COL['bg']))
        self.conversation_y.pack(side='right', fill='y')
        panel.chat.configure(yscrollcommand=self.conversation_y.set)
        self.grip = tk.Canvas(self.pane, width=11, bd=0, highlightthickness=0,
                              cursor='sb_h_double_arrow', takefocus=True, bg=panel.COL['bg'])
        for event, callback in (('<ButtonPress-1>', self._begin), ('<B1-Motion>', self._drag),
                                ('<ButtonRelease-1>', self._release), ('<Left>', lambda _e: self._keyboard(-20)),
                                ('<Right>', lambda _e: self._keyboard(20)), ('<Home>', lambda _e: self.set_width(210))):
            self.grip.bind(event, callback)
        self._bind(self.pane, '<Configure>', self._schedule)
        self._bind(panel.history_pane, '<Configure>', self._schedule)
        self._bind(panel.main_pane, '<Configure>', self._schedule)
        self._bind(self.pane, '<ButtonPress-1>', self._native_begin)
        self._bind(self.pane, '<ButtonRelease-1>', self._release)
        self._bind(self.pane, '<B1-Motion>', self._native_motion)
        self._bind(panel.chat_outer, '<Destroy>', self._destroy)
        self._schedule()

    def _palette(self, background):
        return {**palette_for(self.panel.COL), 'bg': background, 'accent': self.panel.COL['cyan']}

    def _bind(self, widget, sequence, callback):
        self._bindings.append((widget, sequence, widget.bind(sequence, callback, add='+')))

    def _enabled(self):
        guard = getattr(self.app, '_portalai_modal_guard', None)
        return not (self.closed or getattr(self.panel, '_closing', False) or getattr(guard, 'surface', None))

    def _visible(self):
        return str(self.panel.history_pane) in {str(p) for p in self.pane.panes()}

    def _schedule(self, _event=None):
        if self.closed or self._layout_after is not None: return
        self._layout_after = self.app.after_idle(self._layout)

    def _layout(self):
        self._layout_after = None
        if self.closed: return
        if not self._visible():
            self.grip.place_forget()
            return
        minimum, maximum, main = pane_limits(self.pane.winfo_width())
        for child, values in ((self.panel.history_pane, {'minsize': minimum, 'stretch': 'never'}),
                              (self.panel.main_pane, {'minsize': main, 'stretch': 'always'})):
            for key, value in values.items():
                if str(self.pane.panecget(child, key)) != str(value):
                    self.pane.paneconfigure(child, **{key: value})
        if not self.dragging:
            target = max(minimum, min(maximum, self.wanted))
            if int(self.pane.panecget(self.panel.history_pane, 'width')) != target:
                self.pane.paneconfigure(self.panel.history_pane, width=target)
            if self.pane.sash_coord(0)[0] != target:
                self.pane.sash_place(0, target, 0)
        self._paint_grip()

    def _paint_grip(self):
        if not self._visible(): return
        x, _ = self.pane.sash_coord(0)
        self.grip.place(x=x, y=5, width=11, relheight=1, height=-10)
        self.grip.tk.call('raise', self.grip._w)
        height = max(40, self.pane.winfo_height() - 10)
        gold, shine = self.panel.COL['gold'], self.panel.COL['tool']
        self.grip.delete('all')
        self.grip.create_line(5, 12, 5, height-12, fill=gold)
        for y in (height/2 - 12, height/2, height/2 + 12):
            self.grip.create_polygon(2, y, 5, y-4, 8, y, 5, y+4, fill=shine, outline=gold)

    def _begin(self, event):
        if self._enabled() and self._visible():
            self.dragging = True
            self._drag_x, self._drag_start = event.x_root, self.pane.sash_coord(0)[0]
            self.grip.focus_set()
        return 'break'

    def _native_begin(self, event):
        if self._enabled() and self.pane.identify(event.x, event.y):
            self.dragging = True

    def _native_motion(self, _event):
        if self.dragging: self._schedule()

    def _drag(self, event):
        if self.dragging and self._enabled():
            minimum, maximum, _ = pane_limits(self.pane.winfo_width())
            self.pane.sash_place(0, max(minimum, min(maximum, self._drag_start + event.x_root - self._drag_x)), 0)
            self._paint_grip()
        return 'break'

    def _release(self, _event=None):
        if self.dragging and self._enabled() and self._visible():
            self.dragging = False
            self.set_width(self.pane.sash_coord(0)[0])

    def _keyboard(self, amount):
        if self._visible(): self.set_width(self.pane.sash_coord(0)[0] + amount)
        return 'break'

    def set_width(self, width):
        if not self._enabled(): return 'break'
        minimum, maximum, _ = pane_limits(self.pane.winfo_width())
        self.wanted = stored_width(max(minimum, min(maximum, width)))
        self.panel.settings['history_width_px'] = self.wanted
        self._schedule()
        if self._save_after is not None: self.app.after_cancel(self._save_after)
        self._save_after = self.app.after(350, self._save)
        return 'break'

    def _save(self):
        self._save_after = None
        if self._enabled(): self.panel.store.save_settings()  # Captured-profile check owns publication.

    def set_hidden(self, hidden):
        if hidden and self._visible():
            self.pane.forget(self.panel.history_pane)
        elif not hidden and not self._visible():
            self.pane.add(self.panel.history_pane, before=self.panel.main_pane, minsize=120, width=self.wanted)
        self._schedule()

    def apply_palette(self):
        for widget, color in ((self.panel.chat_outer, 'bg'), (self.panel.history_pane, 'panel'),
                              (self.panel.history_list_host, 'panel'), (self.panel.main_pane, 'bg'),
                              (self.panel.conversation_shell, 'bg'), (self.pane, 'bg')):
            widget.configure(bg=self.panel.COL[color])
        refresh_borders(self.panel.chat_outer, self.panel.COL)
        self.history_x.apply_palette(self._palette(self.panel.COL['panel']))
        self.history_y.apply_palette(self._palette(self.panel.COL['panel']))
        self.conversation_y.apply_palette(self._palette(self.panel.COL['bg']))
        self.grip.configure(bg=self.panel.COL['bg'])
        self.panel.chat.frame.configure(bg=self.panel.COL['bg'])
        self._paint_grip()

    def _destroy(self, event):
        if event.widget is self.panel.chat_outer: self.close()

    def close(self):
        if self.closed: return
        self.closed = True
        for timer in (self._save_after, self._layout_after):
            if timer is not None:
                try: self.app.after_cancel(timer)
                except tk.TclError: pass
        self._save_after = self._layout_after = None
        for widget, sequence, binding in self._bindings:
            try: widget.unbind(sequence, binding)
            except tk.TclError: pass
        self._bindings.clear()
