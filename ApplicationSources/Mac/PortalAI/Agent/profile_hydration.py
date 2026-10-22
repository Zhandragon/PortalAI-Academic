"""Session-owned on-demand restoration without passing encryption keys to tools.

Only the authenticated controller holds the key. Child tools use a random,
in-memory loopback capability bound to this root, user and login epoch. This is
application privacy, not isolation from the operating-system account owner.
"""
from __future__ import annotations

import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time

from profile_paths import capture, workspace_root, _contained, _relative, is_private, ProfileLocked

PORT_ENV = 'PORTALAI_HYDRATION_PORT'
TOKEN_ENV = 'PORTALAI_HYDRATION_CAPABILITY'
OWNER_ENV = 'PORTALAI_HYDRATION_OWNER'
_BROKERS = {}
_BROKERS_LOCK = threading.RLock()


class _BoundedServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def _identity(root):
    return os.path.normcase(str(Path(root).resolve()))


class HydrationBroker:
    def __init__(self, root, context, session_getter, validate):
        self.root = Path(root).resolve()
        self.context = tuple(context)
        self.session_getter = session_getter
        self.validate = validate
        self.token = secrets.token_urlsafe(32)
        self.accepting = True
        self._condition = threading.Condition()
        self._operation = threading.Lock()
        self._active = 0
        self._closed = False
        broker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_POST(self):
                try:
                    if (self.path != '/materialize' or self.headers.get('Origin') is not None or
                            self.headers.get('Transfer-Encoding') is not None or
                            self.headers.get('Content-Type') != 'application/json'):
                        raise PermissionError('Invalid hydration request')
                    supplied = self.headers.get('X-PortalAI-Capability', '')
                    if not hmac.compare_digest(supplied, broker.token):
                        raise PermissionError('Invalid hydration capability')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= length <= 8192:
                        raise ValueError('Invalid hydration request size')
                    payload = json.loads(self.rfile.read(length))
                    result = broker.request(payload)
                    data = json.dumps(result).encode('ascii')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    # Do not expose filenames, account keys or internal errors
                    # to unauthenticated local HTTP clients.
                    self.send_error(409, 'Profile restoration unavailable or login ended')

        self.server = _BoundedServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .1}, daemon=True,
                                       name='PortalAI-profile-hydration')
        with _BROKERS_LOCK:
            if _identity(self.root) in _BROKERS:
                self.server.server_close()
                raise RuntimeError('A hydration controller already owns this root')
            _BROKERS[_identity(self.root)] = self
        try:
            self.thread.start()
        except BaseException:
            with _BROKERS_LOCK:
                if _BROKERS.get(_identity(self.root)) is self:
                    del _BROKERS[_identity(self.root)]
            self.server.server_close()
            raise

    def environment(self):
        return {PORT_ENV: str(self.port), TOKEN_ENV: self.token, OWNER_ENV: str(os.getpid())}

    def check(self):
        with self._condition:
            if not self.accepting:
                raise ProfileLocked('Account is closing; file restoration has stopped')
        if capture(self.root) != self.context:
            raise ProfileLocked('File restoration belongs to an ended login')
        session = self.session_getter()
        self.validate(session)
        if session.user_id != self.context[0]:
            raise ProfileLocked('File restoration account changed')
        return session

    def request(self, payload):
        if (not isinstance(payload, dict) or set(payload) not in (
                {'user_id', 'epoch', 'relative', 'recursive'},
                {'user_id', 'epoch', 'relative', 'recursive', 'listing'}) or
                (payload['user_id'], payload['epoch']) != self.context or
                type(payload['recursive']) is not bool or type(payload.get('listing', False)) is not bool):
            raise ProfileLocked('Invalid file restoration identity')
        relative = payload['relative']
        if relative is not None:
            if not isinstance(relative, str):
                raise ValueError('Invalid restoration path')
            relative = _relative(relative)
            if not is_private(relative):
                raise ValueError('Restoration requires a private workspace path')
        with self._condition:
            if not self.accepting or self._active >= 4:
                raise ProfileLocked('File restoration is closing or busy; retry while signed in')
            self._active += 1
        try:
            with self._operation:
                session = self.check()
                from profile_workspace import ProfileWorkspace
                if payload.get('listing'):
                    if relative is None: raise ValueError('Listing requires a scoped path')
                    listing = ProfileWorkspace(self.root, session).file_names(relative, check=self.check, metadata=True)
                    self.check()
                    return {'ready': True, **listing}
                result = ProfileWorkspace(self.root, session).materialize(
                    relative, recursive=payload['recursive'], check=self.check)
                self.check()
                return {'ready': True, 'materialized': int(result.get('materialized', 0)),
                        'pending_files': int(result.get('pending_files', 0))}
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def pause(self):
        """Immediate admission stop; safe to call on the Tk thread."""
        with self._condition:
            self.accepting = False

    def close(self, timeout=60):
        if self._closed:
            return
        self.pause()
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('File restoration has not stopped; profile must remain locked')
                self._condition.wait(min(.2, remaining))
        self.server.shutdown()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError('File restoration listener has not stopped')
        self.server.server_close()
        with _BROKERS_LOCK:
            if _BROKERS.get(_identity(self.root)) is self:
                del _BROKERS[_identity(self.root)]
        for key, value in self.environment().items():
            if os.environ.get(key) == value:
                os.environ.pop(key, None)
        self._closed = True


def materialize(root, relative=None, *, recursive=False, _listing=False):
    """Restore a requested private file/tree into its historical physical path.

    Ordinary path construction does not hydrate directories. Explicit read,
    folder-browse, export and unrestricted-shell boundaries can request a tree.
    Older/eager profiles have no hydration ledger and need no broker.
    """
    root = Path(root).resolve()
    root.stat()  # A disconnected drive is never an empty history listing.
    context = capture(root)
    if context is None or (_listing and not _contained(root, workspace_root(root, context[0]).parent/'hydration.enc').exists()):
        if _listing:
            from profile_paths import private_path
            folder = private_path(root, relative, hydrate=False)
            from portable_fs import walk, raise_walk_error
            names = []
            if folder.is_dir():
                for directory, dirs, files in walk(folder, followlinks=False, onerror=raise_walk_error):
                    for name in dirs + files: _contained(root, Path(directory)/name)
                    names.extend(relative.rstrip('/')+'/'+(Path(directory)/name).relative_to(folder).as_posix() for name in files)
            if capture(root) != context: raise ProfileLocked('File listing belongs to an ended login')
            return {'ready': True, 'names': sorted(names), 'pending_hashes': {}}
        return {'ready': True, 'materialized': 0, 'pending_files': 0}
    if relative is not None:
        relative = _relative(relative)
    workspace = workspace_root(root, context[0])
    ledger = _contained(root, workspace.parent / 'hydration.enc')
    if not ledger.exists():
        return {'ready': True, 'materialized': 0, 'pending_files': 0}
    if relative is not None and not recursive and not _listing:
        from profile_workspace import is_deferred_path
        if not is_deferred_path(relative):
            return {'ready': True, 'materialized': 0}
        candidate = _contained(root, workspace / relative)
        if candidate.is_dir():
            return {'ready': True, 'materialized': 0}
    payload = {'user_id': context[0], 'epoch': context[1], 'relative': relative, 'recursive': bool(recursive)}
    if _listing: payload['listing'] = True
    with _BROKERS_LOCK:
        broker = _BROKERS.get(_identity(root))
    if broker is not None:
        result = broker.request(payload)
    else:
        try:
            port = int(os.environ.get(PORT_ENV, '0'))
            token = os.environ.get(TOKEN_ENV, '')
            owner = int(os.environ.get(OWNER_ENV, '0'))
            marker = root / 'Private/active-session.json'
            _contained(root, marker)
            active = json.loads(marker.read_text(encoding='utf-8'))
            if not (1 <= port <= 65535 and len(token) >= 32 and owner == active.get('controller_pid')):
                raise ValueError()
        except (ValueError, OSError):
            raise ProfileLocked('The signed-in controller is required to restore this file') from None
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=300)
        try:
            connection.request('POST', '/materialize', body=json.dumps(payload).encode('ascii'),
                               headers={'Content-Type': 'application/json', 'X-PortalAI-Capability': token})
            response = connection.getresponse()
            limit = 16*1024*1024 if _listing else 8192
            body = response.read(limit+1)
            if response.status != 200 or len(body) > limit:
                raise ProfileLocked('File restoration failed or this login ended')
            result = json.loads(body)
            if result.get('ready') is not True:
                raise ProfileLocked('File restoration did not verify')
        except (OSError, http.client.HTTPException, ValueError):
            raise ProfileLocked('The signed-in file restoration service is unavailable') from None
        finally:
            connection.close()
    if capture(root) != context:
        raise ProfileLocked('File restoration belongs to an ended login')
    return result


def file_names(root, relative):
    """List an account-owned tree including encrypted dormant files."""
    relative = _relative(relative)
    if not is_private(relative): raise ValueError('Listing requires a private path')
    return file_listing(root, relative)['names']


def file_listing(root, relative):
    relative = _relative(relative)
    if not is_private(relative): raise ValueError('Listing requires a private path')
    return materialize(root, relative, _listing=True)
