"""Short-lived receiver hints; never authentication or permission to act."""
import threading
import time

LEASE_SECONDS = 5


class ViewerDemand:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.until = 0.
        self.supported = False
        self.flags = {'screen': False, 'native': False}
        self.generations = {'screen': 0, 'native': 0}

    def _set(self, screen=False, native=False):
        for kind, active in (('screen', screen), ('native', native)):
            if self.flags[kind] != active:
                self.generations[kind] += 1
                self.flags[kind] = active

    def reset(self):
        with self.lock:
            self._set()
            self.until = 0.
            self.supported = False

    def update(self, value, requested_at):
        """Count lease from request start, never extend it by network delay."""
        with self.lock:
            if value is None:
                self.reset()
                return
            if (type(value) is not dict or set(value) != {'version', 'screen', 'native', 'lease_seconds'}
                    or type(value['version']) is not int or value['version'] != 1
                    or type(value['screen']) is not bool or type(value['native']) is not bool
                    or type(value['lease_seconds']) is not int or value['lease_seconds'] != LEASE_SECONDS):
                self.reset()
                raise ValueError('Invalid viewer demand')
            self._expire()
            self.supported = True
            self.until = requested_at + LEASE_SECONDS
            self._set(value['screen'], value['native'])
            self._expire()

    def _expire(self):
        if self.clock() >= self.until:
            self._set()

    def token(self, kind):
        with self.lock:
            self._expire()
            return self.generations[kind] if self.flags[kind] else None

    def active(self, kind):
        return self.token(kind) is not None

    def valid(self, kind, token):
        return token is not None and self.token(kind) == token

    def status(self):
        with self.lock:
            self._expire()
            if not self.supported:
                return 'receiver_update_required'
            if self.clock() >= self.until:
                return 'waiting_for_receiver'
            return 'active' if any(self.flags.values()) else 'standby'
