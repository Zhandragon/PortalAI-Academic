"""The launcher's connected gold artwork for inline chat cards only."""
import tkinter as tk
from ornate_ui import ConnectedBorder, FiligreeScrollbar


def palette_for(colors):
    return {'bg': colors['bg'], 'panel': colors['card'],
            'gold_mid': colors.get('gold', '#A87D32'),
            'gold_shine': colors.get('tool', '#D9BE78'), 'shadow': '#2B2419'}


def ornate_frame(parent, colors, *, surface='card', radius=14, filigree=False):
    frame = tk.Frame(parent, bg=colors[surface], bd=0, highlightthickness=0)
    frame._portalai_conversation_border = ConnectedBorder(
        frame, palette_for(colors), radius=radius, filigree=filigree, shine=True)
    return frame


def preview_label(parent, image, colors):
    frame = ornate_frame(parent, colors)
    frame.pack(anchor='w', padx=10, pady=(0, 9))
    label = tk.Label(frame, image=image, bg=colors['card'], bd=0)
    label.pack(padx=9, pady=9)
    return label


def refresh_borders(widget, colors):
    if isinstance(widget, FiligreeScrollbar):
        widget.apply_palette({**palette_for(colors), 'bg':widget.master.cget('bg'), 'accent':colors.get('cyan', '#3E91A2')})
    border = getattr(widget, '_portalai_conversation_border', None)
    if border is not None:
        border.apply_palette(palette_for(colors))
    for child in widget.winfo_children():
        refresh_borders(child, colors)


def trace_presentation(block):
    """Collapsed traces have one quiet outline; expanded traces keep the artwork."""
    expanded = bool(block['expanded'])
    frame, head = block['frame'], block['head']
    outer = frame._portalai_conversation_border
    inner = head._portalai_conversation_border
    inner.simple = True
    outer.simple = not expanded
    frame.configure(bg=block['body'].cget('bg') if expanded else head.cget('bg'))
    if expanded:
        inner.canvas.place(x=0, y=0, relwidth=1, relheight=1)
    else:
        inner.canvas.place_forget()
    head.pack_configure(padx=7 if expanded else 5, pady=7 if expanded else 4)
    block['toggle'].pack_configure(padx=(7, 3) if expanded else (3, 3), pady=5 if expanded else 2)
    outer.apply_palette(); inner.apply_palette()
