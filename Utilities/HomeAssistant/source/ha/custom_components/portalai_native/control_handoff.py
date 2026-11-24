"""Release completed native actions without weakening active-controller checks."""
from time import monotonic

COMPLETED_HANDOFF_SECONDS = 2


def acquire(receiver, device, viewer):
    """Share one operation hold across chat/workflow requests by the same viewer."""
    holds = getattr(receiver, "_native_control_holds", None)
    if holds is None:
        holds = receiver._native_control_holds = {}
    current = receiver.connected(device)
    row = holds.get(device)
    if row is not None and row["state"] is not current:
        holds.pop(device, None)
        row = None
    if row is not None and row["viewer"] != viewer:
        raise PermissionError("Another viewer has a native action in progress")
    # Preserve the existing authenticated controller/legacy-desktop lease.
    state = receiver.lease(device, viewer)
    if row is None:
        row = {"state": state, "viewer": viewer, "tokens": set(), "uncertain": False}
        holds[device] = row
    marker = object()
    row["tokens"].add(marker)
    row["lease"] = state["viewer"]
    return receiver, device, row, marker


def release(token, completed):
    """Unknown outcomes retain the existing bounded fallback; never auto-replay."""
    if token is None:
        return
    receiver, device, row, marker = token
    holds = receiver._native_control_holds
    if holds.get(device) is not row or marker not in row["tokens"]:
        return
    row["tokens"].remove(marker)
    row["uncertain"] |= not completed
    if row["tokens"]:
        return
    holds.pop(device, None)
    # A reconnect or newer desktop reservation must never be cleared by an
    # older completion. Acknowledgment is command completion, not AI completion;
    # the existing chat busy/account/modal guards still govern later commands.
    if (not row["uncertain"] and receiver.devices.get(device) is row["state"]
            and row["state"].get("viewer") is row["lease"]):
        row["state"]["viewer"] = (row["viewer"], monotonic() + COMPLETED_HANDOFF_SECONDS)
