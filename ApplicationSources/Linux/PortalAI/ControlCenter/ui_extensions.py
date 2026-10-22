# PORTABLEAI_CAPABILITY_HELP_SYNC_v15_128E
from __future__ import annotations

import re
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Iterable

VERSION = "15.123"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


from help_catalog import TOPICS, CATEGORIES, canonical_topic, filtered_topic_keys


def topic_for_text(text: str, fallback: str = "quick_start") -> str:
    n = _norm(text)
    if not n:
        return fallback
    best = None
    best_score = -1
    words = set(n.split())
    for key, rec in TOPICS.items():
        for alias in [rec.get("title", ""), *(rec.get("aliases") or [])]:
            a = _norm(alias)
            if not a:
                continue
            if n == a:
                return key
            if a in n or n in a:
                score = min(len(a), len(n)) + 40
            else:
                score = len(words & set(a.split())) * 8
            if score > best_score:
                best, best_score = key, score
    return best if best_score > 0 else fallback


class ResponsiveFlow(tk.Frame):
    """Small native-Tk wrapping container. It only manages geometry."""

    def __init__(self, master, *, bg=None, hgap=6, vgap=6, **kw):
        if bg is not None:
            kw.setdefault("bg", bg)
        super().__init__(master, **kw)
        self._items = []
        self._hgap = int(hgap)
        self._vgap = int(vgap)
        self._after = None
        self._last = None
        self.bind("<Configure>", self._queue, add="+")

    def add(self, widget):
        if widget not in self._items:
            self._items.append(widget)
        self._queue()
        return widget

    def _queue(self, _event=None):
        try:
            if self._after is not None:
                self.after_cancel(self._after)
        except Exception:
            pass
        self._after = self.after_idle(self._reflow)

    def _reflow(self):
        self._after = None
        if not self.winfo_exists():
            return
        width = max(40, int(self.winfo_width()))
        signature = (width, tuple((w.winfo_reqwidth(), w.winfo_reqheight()) for w in self._items if w.winfo_exists()))
        if signature == self._last:
            return
        self._last = signature
        x = y = row_h = 0
        for w in self._items:
            if not w.winfo_exists():
                continue
            ww, wh = max(1, w.winfo_reqwidth()), max(1, w.winfo_reqheight())
            if x and x + ww > width:
                x = 0
                y += row_h + self._vgap
                row_h = 0
            w.place(x=x, y=y, width=ww, height=wh)
            x += ww + self._hgap
            row_h = max(row_h, wh)
        needed = max(1, y + row_h)
        if int(self.cget("height") or 0) != needed:
            self.configure(height=needed)


def bind_responsive_wrap(label: tk.Widget, *, padding=24, minimum=260):
    parent = label.master
    def update(event=None):
        try:
            w = int((event.width if event is not None else parent.winfo_width()) - padding)
            label.configure(wraplength=max(minimum, w))
        except Exception:
            pass
    parent.bind("<Configure>", update, add="+")
    parent.after_idle(update)


class DocumentationPanel:
    def __init__(self, parent, palette: dict):
        self.parent = parent
        self.palette = palette
        self.current_topic = "quick_start"
        self.topics = TOPICS
        self.root = tk.Frame(parent, bg=palette["bg"])
        self.root.pack(fill="both", expand=True, padx=16, pady=16)
        head = tk.Frame(self.root, bg=palette["bg"])
        self.header = head
        head.pack(fill="x", padx=8, pady=(6, 6))
        self.title_lbl = tk.Label(head, text="Documentation & Help", bg=palette["bg"], fg=palette["text"],
                                  font=("Segoe UI Variable Display", 14, "bold"), anchor="w")
        self.title_lbl.pack(side="left")
        self.search_label = tk.Label(head, text="Search", bg=palette["bg"], fg=palette["muted"])
        self.search_label.pack(side="left", padx=(20, 8))
        self.search_var = tk.StringVar(value="")
        self.search = tk.Entry(head, textvariable=self.search_var, bg=palette["panel2"], fg=palette["text"],
                               insertbackground=palette["text"], relief="flat", bd=0,
                               font=("Segoe UI Variable Text", 9))
        self.search.pack(side="right", fill="x", expand=True, ipady=5)
        self.search_var.trace_add("write", lambda *_: self._refill())

        filters = tk.Frame(self.root, bg=palette["bg"])
        filters.pack(fill="x", padx=8, pady=(0, 8))
        self.filter_label = tk.Label(filters, text="Browse category", bg=palette["bg"], fg=palette["text"])
        self.filter_label.pack(side="left", padx=(0, 8))
        from rounded_controls import RoundedCombobox
        self.category_var = tk.StringVar(value="All topics")
        self.category = RoundedCombobox(filters, palette=palette, textvariable=self.category_var,
            values=("All topics", *CATEGORIES), state="readonly", width=30)
        self.category.pack(side="left")
        self.category_var.trace_add("write", lambda *_: self._refill())
        self.filter_hint = tk.Label(filters, text="Search above · A–Z topics", bg=palette["bg"], fg=palette["muted"])
        self.filter_hint.pack(side="left", padx=10)
        self.filter_frame = filters

        pane = tk.PanedWindow(self.root, orient="horizontal", sashwidth=5, bg=palette["bg"], bd=0)
        pane.pack(fill="both", expand=True)
        left = tk.Frame(pane, bg=palette["panel"])
        right = tk.Frame(pane, bg=palette["bg"])
        from ornate_ui import ConnectedBorder
        self.rounded_borders=[ConnectedBorder(frame,palette,radius=14,filigree=False) for frame in (left,right)]
        self.help_frames=(left,right)
        pane.add(left, minsize=170, width=230)
        pane.add(right, minsize=320)
        from help_topics import TopicList
        from ornate_ui import FiligreeScrollbar
        self.listbox=TopicList(left,palette)
        self.topic_scroll=FiligreeScrollbar(left,command=self.listbox.yview,palette=palette,height=1)
        self.topic_scroll.pack(side='right',fill='y',padx=(0,7),pady=12)
        self.listbox.configure(yscrollcommand=self.topic_scroll.set)
        self.listbox.pack(fill="both", expand=True, padx=12, pady=12)
        self.listbox._portalai_rounded_container=True
        self.listbox.configure(highlightthickness=0)
        self.listbox.bind("<<ListboxSelect>>", self._selected)
        self.text = ScrolledText(right, bg=palette["bg"], fg=palette["text"], wrap="word",
                                 relief="flat", bd=0, padx=16, pady=12,
                                 font=("Segoe UI Variable Text", 10), state="disabled")
        self.text.pack(fill="both", expand=True,padx=12,pady=12)
        self.text._portalai_rounded_container=True
        self.text.configure(highlightthickness=0)
        self.title_rule=None
        self.text.bind('<Configure>',lambda event:self.title_rule.configure(width=max(40,event.width-36)) if self.title_rule is not None and self.title_rule.winfo_exists() else None,add='+')
        self.keys = []
        self._refill()
        self.show_topic("quick_start")
        self.root.after_idle(lambda:self.listbox.see(self.keys.index(self.current_topic))
                             if self.current_topic in self.keys else None)

    def _refill(self):
        keys = filtered_topic_keys(self.search_var.get(), self.category_var.get())
        self.keys = keys
        self.listbox.delete(0, "end")
        for key in keys:
            self.listbox.insert("end", TOPICS[key]["title"])
        if self.current_topic in keys:
            self.listbox.selection_set(keys.index(self.current_topic))
        self.filter_hint.configure(text=f"{len(keys)} topics · A–Z · Search above" if keys else "No matching topics")
        self.listbox.yview_moveto(0)

    def _selected(self, _event=None):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.keys):
            self.show_topic(self.keys[sel[0]], select=False)

    def show_topic(self, topic: str, *, select=True):
        topic = canonical_topic(topic)
        key = topic if topic in TOPICS else topic_for_text(topic)
        self.current_topic = key
        rec = TOPICS.get(key, TOPICS["quick_start"])
        self.text.configure(state="normal")
        if self.title_rule is not None:self.title_rule.destroy()
        self.text.delete("1.0", "end")
        self.text.insert("end", rec["category"] + "\n\n", "category")
        self.text.insert("end", rec["title"] + "\n", "title")
        self.title_rule=tk.Frame(self.text,height=2,width=max(40,self.text.winfo_width()-36),bg=self.palette.get('gold_mid','#A87D32'))
        self.text.window_create('end',window=self.title_rule,pady=9)
        self.text.insert('end','\n\n')
        self.text.insert("end", rec["body"].strip() + "\n")
        self.text.tag_config("title", font=("Segoe UI Variable Display", 13, "bold"), foreground=self.palette.get('muted',self.palette["text"]))
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)
        if select:
            if key not in self.keys:
                self.category_var.set(rec["category"])
                self.search_var.set("")
            if key in self.keys:
                i = self.keys.index(key)
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(i)
                self.listbox.activate(i)
                self.listbox.see(i)

    def apply_palette(self, palette: dict):
        self.palette = palette
        try:
            self.root.configure(bg=palette["bg"])
            self.header.configure(bg=palette["bg"])
            self.filter_frame.configure(bg=palette["bg"])
            self.filter_label.configure(bg=palette["bg"], fg=palette["text"])
            self.filter_hint.configure(bg=palette["bg"], fg=palette["muted"])
            self.category.apply_palette(palette)
            self.title_lbl.configure(bg=palette["bg"], fg=palette["text"])
            self.search_label.configure(bg=palette["bg"], fg=palette["muted"])
            self.search.configure(bg=palette["panel2"], fg=palette["text"], insertbackground=palette["text"])
            self.listbox.apply_palette(palette);self.topic_scroll.apply_palette(palette)
            self.text.configure(bg=palette["bg"], fg=palette["text"], insertbackground=palette["text"])
            self.text.tag_configure('title',foreground=palette.get('muted',palette['text']))
            if self.title_rule is not None:self.title_rule.configure(bg=palette.get('gold_mid','#A87D32'))
            for frame in self.help_frames: frame.configure(bg=palette["panel"])
            for border in self.rounded_borders: border.apply_palette(palette)
        except Exception:
            pass


class ContextHelpManager:
    def __init__(self, root: tk.Misc, palette: dict, show_help: Callable[[str], None],
                 *, default_topic: Callable[[], str] | None = None,
                 actions_provider: Callable[[tk.Widget, str, str], Iterable[tuple[str, Callable]]] | None = None):
        self.root = root
        self.palette = palette
        self.show_help = show_help
        self.default_topic = default_topic or (lambda: "quick_start")
        self.actions_provider = actions_provider
        self._installed = False

    def install(self):
        if self._installed:
            return
        self._installed = True
        self.root.bind_all("<Button-3>", self._popup, add="+")

    def apply_palette(self, palette: dict):
        self.palette = palette

    def _text(self, widget) -> str:
        w = widget
        pieces = []
        for _ in range(4):
            if w is None:
                break
            try:
                txt = w.cget("text")
                if txt:
                    pieces.append(str(txt))
            except Exception:
                pass
            try:
                w = w.master
            except Exception:
                break
        return " ".join(pieces)

    def _editable_actions(self, widget):
        cls = str(widget.winfo_class()) if widget is not None else ""
        actions = []
        if cls in {"Entry", "TEntry", "Text"}:
            actions.append(("Copy", lambda w=widget: w.event_generate("<<Copy>>")))
            try:
                state = str(widget.cget("state"))
            except Exception:
                state = "normal"
            if state not in {"disabled", "readonly"}:
                actions.append(("Cut", lambda w=widget: w.event_generate("<<Cut>>")))
                actions.append(("Paste", lambda w=widget: w.event_generate("<<Paste>>")))
            actions.append(("Select all", lambda w=widget: (w.tag_add("sel", "1.0", "end") if cls == "Text" else w.selection_range(0, "end"))))
        return actions

    def _popup(self, event):
        widget = event.widget
        text = self._text(widget)
        fallback = self.default_topic() or "quick_start"
        topic = topic_for_text(text, fallback=fallback)
        rec = TOPICS.get(topic, TOPICS["quick_start"])
        menu = tk.Menu(self.root, tearoff=False,
                       bg=self.palette.get("panel", "#EFE8DC"), fg=self.palette.get("text", "#24211D"),
                       activebackground=self.palette.get("accent", "#3D97AA"), activeforeground="#ffffff", bd=1)
        actions = self._editable_actions(widget)
        if self.actions_provider is not None:
            try:
                actions.extend(list(self.actions_provider(widget, text, topic) or []))
            except Exception:
                pass
        seen = set()
        for label, callback in actions:
            if not label or not callable(callback) or label in seen:
                continue
            seen.add(label)
            menu.add_command(label=label, command=callback)
        if seen:
            menu.add_separator()
        menu.add_command(label=f"Help: {rec['title']}", command=lambda k=topic: self.show_help(k))
        menu.add_command(label="Documentation & Help", command=lambda: self.show_help("quick_start"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"


def adaptive_columns(parent, widgets, *, minimum=850, stretch=False):
    """Two equal columns when useful, preserving reading order when stacked."""
    previous=[None]
    def layout(event):
        cols=2 if event.width>=minimum else 1
        if previous[0]==cols:return
        previous[0]=cols
        if stretch:
            for row in range(len(widgets)):parent.rowconfigure(row,weight=1 if row<(len(widgets)+cols-1)//cols else 0)
        for column in range(2):parent.columnconfigure(column,weight=1 if column<cols else 0,uniform='pair' if column<cols else '')
        for index,widget in enumerate(widgets):
            widget.grid(row=index//cols,column=index%cols,sticky='nsew',padx=(0,10) if cols==2 and index%2==0 else 0,pady=(0,4))
    parent.bind('<Configure>',layout,add='+')
    layout(type('Size',(),{'width':parent.winfo_width()})())


class ResponsiveGrid(tk.Frame):
    """Equal-width adaptive button grid with balanced final rows.

    Geometry only: children remain their original native Tk/ttk widgets and keep
    their own event handling/commands. The grid coalesces resize events with
    after_idle, so it does not run work in mouse callbacks.
    """
    def __init__(self, master, *, bg=None, min_cell_width=84, max_columns=4, hgap=4, vgap=4, **kw):
        if bg is not None:
            kw.setdefault("bg", bg)
        super().__init__(master, **kw)
        self._items=[]
        self._min_cell=max(42,int(min_cell_width))
        self._max_cols=max(1,int(max_columns))
        self._hgap=max(0,int(hgap)); self._vgap=max(0,int(vgap))
        self._after=None; self._last=None
        self.bind("<Configure>", self._queue, add="+")

    def add(self, widget):
        if widget not in self._items:
            self._items.append(widget)
        self._queue()
        return widget

    def _queue(self, _event=None):
        try:
            if self._after is not None:
                self.after_cancel(self._after)
        except Exception:
            pass
        self._after=self.after_idle(self._reflow)

    @staticmethod
    def _balanced_columns(n, maxfit):
        if n <= 1: return 1
        maxfit=max(1,min(int(maxfit),int(n)))
        best=1; best_score=10**9
        for cols in range(1,maxfit+1):
            rows=(n+cols-1)//cols
            rem=n%cols
            ragged=0.0 if rem==0 else (cols-rem)/cols
            # Row count dominates; ragged last rows break ties strongly enough
            # to avoid unattractive 5+2/6+1 layouts when 4+3 is available.
            score=rows + ragged*0.75
            if score < best_score - 1e-9 or (abs(score-best_score)<1e-9 and cols>best):
                best, best_score=cols, score
        return best

    def _reflow(self):
        self._after=None
        live=[w for w in self._items if w.winfo_exists()]
        if not live or not self.winfo_exists():
            return
        width=max(40,int(self.winfo_width()))
        maxfit=max(1,(width+self._hgap)//(self._min_cell+self._hgap))
        cols=self._balanced_columns(len(live), min(self._max_cols,maxfit))
        signature=(width,cols,len(live))
        if signature==self._last:
            return
        self._last=signature
        for w in live:
            try: w.grid_forget()
            except Exception: pass
        from math import lcm
        remainder=len(live)%cols or cols
        units=lcm(cols,remainder)
        for c in range(max(getattr(self,'_grid_units',0),units)):
            self.grid_columnconfigure(c,weight=1 if c<units else 0,uniform='portableai_rg' if c<units else '')
        self._grid_units=units
        for idx,w in enumerate(live):
            r,c=divmod(idx,cols)
            row_count=remainder if r==(len(live)-1)//cols else cols
            span=units//row_count
            w.grid(row=r,column=c*span,columnspan=span,sticky="ew",padx=(0,self._hgap if c<row_count-1 else 0),pady=(0,self._vgap))
