"""A local drag handle for expanded thinking/tool text; no transcript rebuild."""
import tkinter as tk
from tkinter import font as tkfont


def install_trace_resizer(body, text, transcript, colors):
    handle = tk.Label(body, text='\u22ef  Drag to resize  \u22ef', bg=colors['card'],
                      fg=colors['muted'], cursor='sb_v_double_arrow',
                      font=('Segoe UI', 8), takefocus=1, pady=2)
    handle.pack(side='bottom', fill='x', padx=8, pady=(1, 2))
    state = {}

    def allowed():
        guard = getattr(transcript.winfo_toplevel(), '_portalai_modal_guard', None)
        return not getattr(guard, 'surface', None)

    def resize(rows):
        if not allowed():
            return 'break'
        anchor = transcript.index('@0,0')
        text.configure(height=max(3, min(50, round(rows))))
        transcript.yview(anchor)
        return 'break'

    def begin(event):
        if allowed():
            state.update(y=event.y_root, rows=int(text.cget('height')))
        return 'break'

    def drag(event):
        if state and allowed():
            line = max(1, tkfont.Font(root=text, font=text.cget('font')).metrics('linespace'))
            resize(state['rows'] + (event.y_root - state['y']) / line)
        return 'break'

    def end(_event):
        state.clear()
        return 'break'

    handle.bind('<ButtonPress-1>', begin)
    handle.bind('<B1-Motion>', drag)
    handle.bind('<ButtonRelease-1>', end)
    handle.bind('<Up>', lambda _e: resize(int(text.cget('height')) - 1))
    handle.bind('<Down>', lambda _e: resize(int(text.cget('height')) + 1))
    # An explicit callable also gives synthetic tests an OS-focus-free route.
    handle._portalai_resize_rows = resize
    return handle
