"""Keep borderless page canvases fixed when their content fits the viewport."""


def bind_page_scroll(canvas, content, window):
    """Track content and viewport changes without hiding the page's scrollbar.

    A Canvas scrollregion shorter than its viewport still permits negative
    origins even while yview reports (0, 1). Pad the *range* to the viewport,
    leaving the content's natural height alone so responsive layouts can shrink.
    """
    def update_region(_event=None):
        if not canvas.winfo_exists():
            return
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        bounds = canvas.bbox(window)
        content_height = max(1, bounds[3] - bounds[1]) if bounds else 1
        region = (0, 0, width, max(height, content_height))
        current = tuple(map(float, canvas.tk.splitlist(canvas.cget('scrollregion'))))
        if current != region:
            canvas.configure(scrollregion=region)
        if content_height <= height:
            canvas.yview_moveto(0)

    def resize(event):
        canvas.itemconfigure(window, width=max(1, event.width))
        update_region()

    content.bind('<Configure>', update_region, add='+')
    # A shrinking window item can move entirely above the current viewport.
    # Tk unmaps it without issuing Configure until it becomes visible again.
    content.bind('<Unmap>', update_region, add='+')
    content.bind('<Map>', update_region, add='+')
    canvas.bind('<Configure>', resize, add='+')
    update_region()

