"""Wait for asynchronous record displays in real Tk fixtures, with a deadline."""
import time


def readers(widget):
    yield from getattr(widget, '_record_refreshes', ())
    for child in widget.winfo_children():
        yield from readers(child)


def settle_records(app, timeout=8):
    deadline = time.monotonic() + timeout
    quiet = 0
    while time.monotonic() < deadline:
        app.update()
        if all(not r.running and r.results.empty() for r in readers(app)):
            quiet += 1
            if quiet >= 3:
                return
        else:
            quiet = 0
        time.sleep(.02)
    raise AssertionError('Record display did not settle before the fixture deadline')
