"""Narrow quick-chat actions on the Tk thread; never a native-v2 write API."""
import hashlib
import json
import math
import re
import threading
import time


def validate(payload):
    if not isinstance(payload, dict): raise ValueError('native_chat_payload')
    op = payload.get('operation')
    fields = {'request_id', 'viewer', 'operation', 'binding', 'conversation'}
    if op == 'send': fields.add('text')
    if op == 'send' and 'include_pending_attachments' in payload:
        if payload['include_pending_attachments'] is not True: raise ValueError('native_chat_attachment_opt_in')
        fields.add('include_pending_attachments')
    if op not in ('send', 'stop') or set(payload) != fields: raise ValueError('native_chat_fields')
    for key in ('request_id', 'viewer'):
        if not isinstance(payload[key], str) or not re.fullmatch('[0-9a-f]{32}', payload[key]):
            raise ValueError('native_chat_identity')
    binding = payload['binding']
    if not isinstance(binding, dict) or set(binding) != {'view', 'epoch'}:
        raise ValueError('native_chat_binding')
    if any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{32}', v) for v in binding.values()):
        raise ValueError('native_chat_binding')
    sid = payload['conversation']
    if not isinstance(sid, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', sid):
        raise ValueError('native_chat_conversation')
    if op == 'send':
        text = payload['text']
        if not isinstance(text, str) or not text.strip() or len(text) > 8192:
            raise ValueError('native_chat_text')
        try: size = len(text.encode('utf-8'))
        except UnicodeError: raise ValueError('native_chat_text') from None
        if size > 32768: raise ValueError('native_chat_text')
    return payload


class Receipt:
    """Acknowledge an admitted worker, then recheck Tk authority before inference.

    Model loading can take minutes; it must not consume the four-second input
    acknowledgement window. Acceptance is not a claim of completed inference.
    """
    def __init__(self, controller, payload, deadline):
        self.controller = controller
        self.payload = {k: v for k, v in payload.items() if k != 'text'}
        self.deadline = deadline
        self.ready = threading.Event()
        self.decided = threading.Event()
        self.failed = threading.Event()
        self.finished = threading.Event()
        self.prepared = threading.Event()
        self.inference_decided = threading.Event()
        self.inference_allowed = False
        self.result = None
        self.error = None
        self.cancel_event = controller.exporter.chat.cancel_event

    def worker_ready(self, cancel):
        self.ready.set()
        while not self.decided.wait(.02):
            if time.monotonic() >= self.deadline or cancel.is_set():
                self.failed.set()
                return False
        return self.result is not None and not cancel.is_set()

    def can_prepare(self, cancel):
        return not cancel.is_set() and not self.decided.is_set() and time.monotonic() < self.deadline

    def worker_prepared(self, cancel):
        """No inference until Tk rechecks the original binding after loading."""
        if self.result is None or cancel.is_set() or self.finished.is_set(): return False
        self.prepared.set()
        deadline = time.monotonic() + 4
        while not self.inference_decided.wait(.02):
            if time.monotonic() >= deadline or cancel.is_set():
                cancel.set()
                return False
        return self.inference_allowed and not cancel.is_set()

    def worker_finished(self):
        self.finished.set()
        if not self.decided.is_set(): self.failed.set()

    def _monitor_preparation(self):
        # Runs only on Tk, and stops before another request can reuse the panel's
        # cancel event. Authentication, modal, conversation and reconnect guards
        # remain live throughout loading, without extending delivery authority.
        if self.finished.is_set() or self.inference_decided.is_set(): return
        with self.controller.exporter.lock:
            try:
                if self.cancel_event.is_set(): raise RuntimeError('native_chat_cancelled')
                self.controller.check_current(self.payload)
                if self.prepared.is_set():
                    self.inference_allowed = True
                    self.inference_decided.set()
                    return
                self.controller.exporter.app.after(250, self._monitor_preparation)
            except Exception:
                self.cancel_event.set()
                self.inference_decided.set()

    def refuse(self):
        if not self.decided.is_set(): self.cancel_event.set()
        self.error = 'native_chat_admission_failed_or_expired; do not replay automatically'
        self.decided.set()

    def poll(self):
        with self.controller.exporter.lock:
            return self._poll_locked()

    def _poll_locked(self):
        if self.error: raise RuntimeError(self.error)
        if self.result is not None: return self.result
        try:
            self.controller.check(self.payload, self.deadline)
            if self.failed.is_set() or self.cancel_event.is_set(): raise RuntimeError('native_chat_admission_failed')
            if not self.ready.is_set(): return None
            self.result = {'accepted': True, 'request_id': self.payload['request_id'], 'operation': 'send'}
            self.decided.set()
            self._monitor_preparation()
            return self.result
        except Exception:
            self.refuse()
            raise RuntimeError(self.error) from None


class Controller:
    attachment_protocol = 1
    def __init__(self, exporter):
        self.exporter = exporter
        self.receipts = {}

    def check(self, payload, deadline):
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or time.monotonic() >= deadline:
            raise TimeoutError('native_chat_expired')
        self.check_current(payload)

    def check_current(self, payload):
        ex = self.exporter
        if threading.get_ident() != ex.thread_id: raise RuntimeError('native_chat_Tk_thread_required')
        if not ex.allowed(authenticate=True) or ex.mode != 'ready': raise PermissionError('native_chat_account_locked')
        if any(not d.closed for d in getattr(ex.app,'_portalai_account_dialogs',())):
            raise PermissionError('native_chat_account_dialog')
        if payload['binding'] != {'view': ex.view, 'epoch': ex.epoch}: raise PermissionError('native_chat_stale_binding')
        panel = ex.chat
        if (getattr(panel, '_session_load_request', None) is not None or not panel.session
                or panel.session.get('id') != payload['conversation']):
            raise PermissionError('native_chat_stale_conversation')
        if (ex.app.grab_current() is not None or getattr(panel, '_sheet_overlay', None) is not None
                or getattr(panel, '_inline_edit_frame', None) is not None):
            raise PermissionError('native_chat_modal')
        panel._check_login()

    def execute(self, payload, deadline):
        validate(payload)
        ex = self.exporter
        # Account lock/rebind cannot race the final effect boundary.
        with ex.lock:
            self.check(payload, deadline)
            identity = (ex.session.user_id, ex.profile.identity, ex.view, ex.epoch)
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).digest()
            key = payload['request_id']
            old = self.receipts.get(key)
            if old is not None:
                if old[0] != (identity, digest): raise PermissionError('native_chat_conflicting_duplicate')
                result = old[1]
                if isinstance(result, str): raise RuntimeError(result)
                return result
            if len(self.receipts) >= 256:
                # Retire the binding before forgetting receipts, so evicted IDs
                # cannot be replayed under their original authority.
                ex.invalidate()
                self.receipts.clear()
                raise RuntimeError('native_chat_fresh_binding_required')
            self.receipts[key] = ((identity, digest), 'native_chat_failed; do not replay automatically')
            panel = ex.chat
            if payload['operation'] == 'stop':
                self.check(payload, deadline)
                panel.stop_generation()
                result = {'accepted': True, 'request_id': key, 'operation': 'stop'}
            else:
                if panel.busy: raise RuntimeError('native_chat_busy_or_stopping')
                if (getattr(panel, '_attachment_picker_pending', None) is not None
                        or (panel.pending_attachments and payload.get('include_pending_attachments') is not True)):
                    raise RuntimeError('native_chat_pending_attachments')
                result = Receipt(self, payload, deadline)
                self.check(payload, deadline)
                if panel.submit(remote_text=payload['text'], remote_admission=result) is not True:
                    result.refuse()
                    raise RuntimeError('native_chat_submission_refused')
            self.receipts[key] = ((identity, digest), result)
            return result


def install(exporter, adapter):
    adapter.native_chat = Controller(exporter)
    adapter.publish_endpoint()
