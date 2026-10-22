"""Release a synthetic Tcl interpreter on its creating thread after writers join."""
import gc
import threading
import tkinter as tk


def finish_tk_fixture(app, *, jobs=(), threads=()):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Synthetic Tk cleanup must run on the main thread')
    for group in jobs:
        group.close()
        if group.wait(5).get('stopped') is not True:
            raise AssertionError('Synthetic account writers did not stop before Tk cleanup')
    for thread in threads:
        thread.join(5)
        if thread.is_alive():
            raise AssertionError('Synthetic lifecycle worker did not stop before Tk cleanup')
    interpreter = app.tk
    def destroy_widgets():
        try: exists = app.winfo_exists()
        except tk.TclError: exists = False
        if not exists: return
        for dialog in reversed(list(getattr(app, '_portalai_account_dialogs', ()))):
            dialog.busy = False
            dialog.close()
        app.update_idletasks()
        # A timer may belong to a child widget. Cancelling through app.after_cancel
        # deletes its Tcl callback from the wrong widget's bookkeeping; that child's
        # destroy then tries to delete it twice. Let widget destruction own commands.
        for timer in app.tk.call('after', 'info'): app.tk.call('after', 'cancel', timer)
        app.destroy()
    destroy_widgets()
    for name in tuple(vars(app)):
        if name.startswith(('_portalai_', '_portableai_')):
            delattr(app, name)
    # Fixture callback recorders can capture the TestCase, which points back to
    # the root. Tk.destroy removes Tcl commands but not Python-only attributes.
    if 'report_callback_exception' in vars(app): del app.report_callback_exception
    # The visual skin caches styles/images for a production interpreter's full
    # lifetime. Synthetic tests create many interpreters in one Python process;
    # remove only this fixture's cache entries before collecting widget cycles.
    import elegant_native_ui as skin
    skin._STYLE_REFS.pop(id(interpreter), None)
    for key in tuple(skin._IMAGE_CACHE):
        if key[0] == id(interpreter): skin._IMAGE_CACHE.pop(key)
    gc.collect()
    return sum(isinstance(value, tk.Variable) and value._tk is interpreter for value in gc.get_objects())
