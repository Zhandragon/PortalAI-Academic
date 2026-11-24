"""Remote native-action holds; never intercept local PortalAI desktop input."""
from contextlib import contextmanager
from time import monotonic

COMPLETED_HANDOFF_SECONDS = 2


@contextmanager
def action(manager, viewer):
    """Keep concurrent native requests held until their last acknowledgment."""
    with manager.lock:
        manager._lease(viewer)
        row = getattr(manager, "_native_hold", None)
        if row is None:
            row = {"viewer": viewer, "count": 0, "uncertain": False}
            manager._native_hold = row
        row["count"] += 1
        row["lease"] = manager.viewer
    completed = False
    try:
        yield
        completed = True
    finally:
        with manager.lock:
            row["count"] -= 1
            row["uncertain"] |= not completed
            if row["count"] == 0 and manager._native_hold is row:
                manager._native_hold = None
                # Preserve a newer legacy reservation and unknown outcomes.
                if not row["uncertain"] and manager.viewer is row["lease"]:
                    manager.viewer = (viewer, monotonic() + COMPLETED_HANDOFF_SECONDS)
