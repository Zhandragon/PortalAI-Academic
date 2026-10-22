"""Immutable login capture for GUI stores and jobs; no user hot-swapping."""
import os
from pathlib import Path
import sys

_AGENT = str(Path(__file__).resolve().parents[1]/'Agent')
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)
import profile_paths


class CapturedProfile:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.identity = profile_paths.capture(self.root)

    def check(self):
        if profile_paths.capture(self.root) != self.identity:
            raise profile_paths.ProfileLocked('This job belongs to an ended login. Reopen PortalAI to sign in again.')

    def private(self, relative):
        self.check()
        return profile_paths.private_path(self.root, relative, context=self.identity)

    def resolve(self, value, *, allow_external=False, hydrate=True):
        self.check()
        if self.identity is None:
            path = Path(value)
            return (path if path.is_absolute() else self.root/path).resolve()
        if str(value) in ('.', ''):
            return self.root
        path = profile_paths.resolve_reference(self.root, value, allow_external=allow_external, hydrate=hydrate)
        self.check()
        return path

    def environment(self, environ):
        self.check()
        env = dict(environ)
        for key in (profile_paths.UID_ENV, profile_paths.EPOCH_ENV):
            env.pop(key, None)
        if self.identity is not None:
            env[profile_paths.UID_ENV], env[profile_paths.EPOCH_ENV] = self.identity
        return env
