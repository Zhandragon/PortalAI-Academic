"""Keep borderless page canvases fixed when their content fits the viewport."""


def bind_page_scroll(canvas, content, window, *, fill_height=False):
    """Track content and viewport changes without hiding the page's scrollbar.

    A Canvas scrollregion shorter than its viewport still permits negative
    origins even while yview reports (0, 1). Pad the *range* to the viewport,
    leaving the content's natural height alone so responsive layouts can shrink.
    """
    pending=[None]
    def update_region(_event=None):
        pending[0]=None
        if not canvas.winfo_exists():
            return
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if fill_height:
            desired=max(height,content.winfo_reqheight())
            if int(float(canvas.itemcget(window,'height') or 0))!=desired:
                canvas.itemconfigure(window,height=desired)
        bounds = canvas.bbox(window)
        content_height = max(1, bounds[3] - bounds[1]) if bounds else 1
        region = (0, 0, width, max(height, content_height))
        current = tuple(map(float, canvas.tk.splitlist(canvas.cget('scrollregion'))))
        if current != region:
            canvas.configure(scrollregion=region)
        if content_height <= height:
            canvas.yview_moveto(0)

    def queue_region(_event=None):
        if not fill_height:return update_region()
        if pending[0] is None:pending[0]=canvas.after(16,update_region)

    # A fixed-height Canvas item does not emit Configure when only its natural
    # requested height changes. Watch child reflows too, so columns that become
    # shorter release their old scroll extent and return space to the lists.
    top=canvas.winfo_toplevel()
    def child_reflow(event):
        if str(event.widget).startswith(str(content)+'.'):queue_region()
    child_binding=top.bind('<Configure>',child_reflow,add='+') if fill_height else None

    def resize(event):
        canvas.itemconfigure(window, width=max(1, event.width))
        queue_region()

    content.bind('<Configure>', queue_region, add='+')
    # A shrinking window item can move entirely above the current viewport.
    # Tk unmaps it without issuing Configure until it becomes visible again.
    content.bind('<Unmap>', queue_region, add='+')
    content.bind('<Map>', queue_region, add='+')
    def cleanup(event):
        if event.widget is canvas:
            if pending[0] is not None:canvas.after_cancel(pending[0]);pending[0]=None
            if child_binding:top.unbind('<Configure>',child_binding)
    canvas.bind('<Destroy>',cleanup,add='+')
    canvas.bind('<Configure>', resize, add='+')
    update_region()

