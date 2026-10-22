"""Keep the original login and Stop fence while a workload waits for admission."""
from pathlib import Path
import time

from profile_paths import capture, ProfileLocked


def request_guard(root):
    root=Path(root).resolve()
    requested_at=time.time()
    context=capture(root)
    def check():
        from chat_model_switch import _guard
        if capture(root) != context:
            raise ProfileLocked('Workload request login ended')
        _guard(root,requested_at)
    return check
