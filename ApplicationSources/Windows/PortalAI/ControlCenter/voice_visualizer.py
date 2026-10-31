"""PortalAI's turquoise-to-gold hands-free card, rendered by the Tk thread."""
import math
import time
import tkinter as tk
from elegant_native_ui import ElegantButton, ui_font
from ornate_ui import ConnectedBorder


def blend(first, second, amount):
    amount = max(0.0, min(1.0, amount))
    return '#' + ''.join(f'{round(int(first[i:i+2],16)*(1-amount)+int(second[i:i+2],16)*amount):02x}'
                         for i in (1,3,5))


class VoiceVisualizer(tk.Frame):
    def __init__(self, parent, palette, *, on_end=None):
        super().__init__(parent, bg=palette['panel'], bd=0)
        self.palette = dict(palette)
        self.activity = None
        self._after = None
        self._visible = False
        self._smooth = 0.0
        self._orb_angle = 0.0
        self._orb_at = None
        self._items = []
        self._cursor = 0
        self._last_display = None
        self._animating = False
        self._title_font = (ui_font(self), 9, 'bold')
        from voice_logo import cached_logo
        try: self.logo = cached_logo(self)
        except (OSError, tk.TclError): self.logo = None
        self.border = ConnectedBorder(self, self.palette, radius=16)
        self.canvas = tk.Canvas(self, height=92, bd=0, highlightthickness=0, bg=palette['panel'], takefocus=True)
        self.canvas.pack(fill='x', padx=12, pady=(8, 0))
        row = tk.Frame(self, bg=palette['panel']); row.pack(fill='x', padx=16, pady=(0, 10))
        self.caption = tk.Label(row, text='Listening', bg=palette['panel'], fg=palette['text'],
                                anchor='w', font=(ui_font(self), 9), width=1)
        self.caption.pack(side='left', fill='x', expand=True)
        self.mute = ElegantButton(row, text='Mute microphone', command=self.toggle_mute,
                                  bg=palette['panel2'], fg=palette['text'], padx=9, pady=4, bd=0)
        self.mute.pack(side='right', padx=(6, 0))
        self.end = None
        if on_end is not None:
            self.end = ElegantButton(row, text='End hands-free', command=on_end,
                                     bg=palette['panel2'], fg=palette['text'], padx=9, pady=4, bd=0)
            self.end.pack(side='right', padx=(6, 0))
        self.canvas.bind('<Button-1>', lambda event: self.toggle_mute() if event.x < 105 else None)
        self.canvas.bind('<space>', self.toggle_mute)
        self.canvas.bind('<Return>', self.toggle_mute)
        self.bind('<Destroy>', self._destroyed, add='+')

    def show(self, activity, *, before=None):
        self.hide()
        self.activity = activity
        options = dict(side='bottom', fill='x', padx=12, pady=(0, 10))
        if before is not None: options['before'] = before
        self.pack(**options)
        self._visible = True
        self._tick()

    def hide(self):
        self._visible = False
        if self._after is not None:
            try: self.after_cancel(self._after)
            except tk.TclError: pass
            self._after = None
        self.activity = None
        self._last_display = None
        try: self.pack_forget()
        except tk.TclError: pass

    def _destroyed(self, event):
        if event.widget is self: self.hide()

    def toggle_mute(self, _event=None):
        if self.activity is not None:
            self.activity.toggle_mute()
            self._paint()
        return 'break'

    def apply_palette(self, palette):
        self.palette = dict(palette)
        self.configure(bg=palette['panel'])
        self.canvas.configure(bg=palette['panel'])
        self.caption.master.configure(bg=palette['panel'])
        self.caption.configure(bg=palette['panel'], fg=palette['text'])
        self.mute.configure(bg=palette['panel2'], fg=palette['text'])
        if self.end is not None: self.end.configure(bg=palette['panel2'], fg=palette['text'])
        self.border.apply_palette(palette)
        self._last_display = None
        if self._visible: self._paint()

    def _tick(self):
        self._after = None
        if not self._visible or not self.winfo_exists(): return
        self._paint()
        self._after = self.after(50 if self._animating else 150, self._tick)

    def _draw(self, kind, *coords, **options):
        """Reuse bounded canvas items; send only changed geometry/style to Tcl."""
        index = self._cursor; self._cursor += 1
        if index < len(self._items):
            old_kind, item, old_coords, old_options = self._items[index]
            if old_kind != kind:
                self.canvas.delete(item)
                item = getattr(self.canvas, 'create_'+kind)(*coords, **options)
            else:
                if coords != old_coords: self.canvas.coords(item, *coords)
                if options != old_options: self.canvas.itemconfigure(item, **options)
            self._items[index] = (kind, item, coords, options)
        else:
            item = getattr(self.canvas, 'create_'+kind)(*coords, **options)
            self._items.append((kind, item, coords, options))

    def _paint(self):
        if self.activity is None: return
        value = self.activity.snapshot()
        self._smooth = .58 * self._smooth + .42 * value['level']
        if self._smooth < .002: self._smooth = 0.0
        level, phase, muted = self._smooth, value['phase'], value['muted']
        palette = self.palette
        gold = palette.get('gold', palette.get('gold_mid', '#A88446'))
        turquoise = palette.get('cyan', '#58B7C7')
        orb_black, orb_white = '#111314', '#F6F2E9'
        ink, dim = palette['text'], palette['muted']
        c = self.canvas
        width = max(240, c.winfo_width()); now = time.monotonic()
        active = phase in ('listening', 'hearing', 'speaking')
        self._animating = level > 0 or not active
        display = (width, phase, muted, value['text'], level)
        if not self._animating and display == self._last_display:
            self._orb_at = now
            return
        self._last_display = display
        self._cursor = 0
        orb_level = level if phase == 'speaking' else 0.0
        elapsed = 0.0 if self._orb_at is None else max(0.0, min(.2, now-self._orb_at))
        self._orb_at = now
        if orb_level > .025:
            self._orb_angle = (self._orb_angle + elapsed * (1.8 + orb_level*.8)) % math.tau
        cx, cy = 44, 45
        if self.logo is not None:
            self._draw('image',cx,cy,image=str(self.logo.base),tags=('voice','orb','logo-frame'))
            self._draw('image',cx,cy,image=str(self.logo.frame(self._orb_angle)),tags=('voice','orb','logo-center'))
        else:
            # A damaged/missing optional brand asset must not break voice controls.
            self._draw('oval',cx-29,cy-29,cx+29,cy+29,fill=orb_black,outline=gold,width=2,tags=('voice','orb'))
            self._draw('text',cx,cy,text='N',fill=orb_white,font=self._title_font,tags=('voice','orb'))
        if muted:
            self._draw('line',cx-14, cy+16, cx+14, cy-16, fill=orb_white, width=3, tags=('voice','orb'))
        self._draw('text',106, 15, text='NICE \u00b7 VOICE', anchor='w', fill=gold,
                      font=self._title_font, tags='voice')
        count = max(12, min(48, int((width-120)/10)))
        for index in range(count):
            x=108 + index * max(4, (width-124)/max(1,count-1))
            shape=(.28+.72*abs(math.sin(index*.63+now*4))) * math.sin(math.pi*(index+1)/(count+1))
            amplitude=2+level*26*shape if active else 2+3*abs(math.sin(index*.28-now*2))
            if muted and phase in ('listening','hearing'): amplitude=2
            color = blend(gold, turquoise, min(1.0, level*(.8+shape))) if active else gold
            self._draw('line',x, 51-amplitude, x, 51+amplitude, fill=color,
                          width=3, capstyle='round', tags='voice')
        text=value['text']
        if muted: text='Microphone muted' if phase in ('listening','hearing') else text+' Â· mic muted'
        while len(self._items) > self._cursor:
            self.canvas.delete(self._items.pop()[1])
        if self.caption.cget('text') != text: self.caption.configure(text=text)
        button_text = 'Unmute microphone' if muted else 'Mute microphone'
        if self.mute.cget('text') != button_text: self.mute.configure(text=button_text)
