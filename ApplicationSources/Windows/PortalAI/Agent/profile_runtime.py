"""One process-owned login, verified workspace recovery, and stop-before-seal.

No installation is initialized or migrated here. Callers supply a fresh positive
writer-quiescence check; an OS lock prevents two controllers opening profiles.
Failure keeps the installation locked and preserves keys/evidence for recovery.
"""
from __future__ import annotations

import json
import os
from portable_fs import Path, walk, raise_walk_error
import re
import threading
import uuid

from mission_runner import process_lock
from profile_paths import UID_ENV, EPOCH_ENV, _contained
from profile_workspace import ProfileWorkspace
from runtime_policy import atomic_json

_EMPTY_DIAGNOSTICS = frozenset('ControlCenter/' + name for name in
    ('PortableAI_Crash.log', 'PortableAI_Freeze.log', 'PortableAI_Launcher.log'))


class ProfileRuntime:
    def __init__(self, root, backend, *, quiesce=None, legacy_check=None, harvest=None, on_progress=None,
                 lazy_restore=False):
        self.root = Path(root).resolve()
        self.backend = backend
        self.quiesce = quiesce
        self.legacy_check = legacy_check
        self.harvest = harvest
        self.on_progress = on_progress
        self.marker = self.root/'Private/active-session.json'
        self._process_lock = None
        self._mutex = threading.RLock()
        self.session = None
        self.epoch = None
        self._prior_sealed = False
        self._recovery_sessions = []
        self._recovery_authorizer = None
        self.lazy_restore = bool(lazy_restore)
        self._hydration = None

    def pause_hydration(self):
        from account_connections import clear_session
        clear_session()
        if self._hydration is not None:
            self._hydration.pause()

    def _close_hydration(self):
        if self._hydration is not None:
            self._hydration.close()
            self._hydration = None

    def _progress(self, stage, message):
        callback = self.on_progress
        if callable(callback):
            try: callback({'stage': stage, 'message': message})
            except Exception: pass  # Presentation never changes the login gate.

    def retains_session(self, session):
        """A failed recovery must not discard the only authenticated keys."""
        return self.session is session or self._recovery_authorizer is session or any(item is session for item in self._recovery_sessions)

    def _harvest(self, session):
        if self.harvest is None:
            return
        result = self.harvest(session)
        if not isinstance(result, dict) or result.get('verified') is not True:
            raise RuntimeError('Private diagnostic harvest did not verify; the installation remains locked.')

    def _acquire(self):
        if self._process_lock is not None:
            return
        lock_path = self.root/'Private/profile-runtime.lock'
        _contained(self.root, lock_path)
        candidate = process_lock(lock_path)
        try:
            candidate.__enter__()
        except OSError as exc:
            raise RuntimeError('Another PortalAI controller owns the account session. Close it before signing in.') from exc
        self._process_lock = candidate

    def release_closed(self):
        """Release an unused/closed controller; never release a live workspace."""
        with self._mutex:
            if self.session is not None or self._recovery_sessions or self._recovery_authorizer is not None:
                raise RuntimeError('Seal the active profile before releasing its controller lock')
            if self._process_lock is not None:
                self._process_lock.__exit__(None, None, None)
                self._process_lock = None

    def _validate(self, session):
        self.backend.validate_session(session)
        if not session.active or not isinstance(session.profile_key, bytes) or len(session.profile_key) != 32:
            raise PermissionError('A live authenticated account is required')

    def _read_marker(self):
        _contained(self.root, self.marker)
        if not self.marker.exists():
            return None
        try:
            if self.marker.stat().st_size > 16384:
                raise ValueError('oversized')
            value = json.loads(self.marker.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or value.get('state') not in ('opening', 'open', 'closing', 'closed'):
                raise ValueError('unknown state')
            if not re.fullmatch('[a-f0-9]{32}', value.get('user_id', '')) or not re.fullmatch('[a-f0-9]{32}', value.get('epoch', '')):
                raise ValueError('invalid identity')
            return value
        except (OSError, ValueError, TypeError):
            raise RuntimeError('Account runtime marker is corrupt. Explicit verified recovery is required.') from None

    def _write_marker(self, uid, epoch, state, role):
        _contained(self.root, self.marker)
        atomic_json(self.marker, {'version': 1, 'user_id': uid, 'epoch': epoch, 'state': state,
                                  'role': role, 'controller_pid': os.getpid()})

    def _clean_legacy(self):
        if callable(self.legacy_check):
            result = self.legacy_check(self.root)
            if not isinstance(result, dict) or result.get('clean') is not True:
                raise RuntimeError('Legacy private files require reviewed migration before any profile can open.')
            return
        if (self.root/'Private/migration-pending.json').exists() or (self.root/'Private/Reset/transaction.json').exists():
            raise RuntimeError('An interrupted private-data migration/reset requires explicit recovery.')
        from profile_migration import legacy_inventory
        rows = legacy_inventory(self.root)['files']
        if any(row['source'] not in _EMPTY_DIAGNOSTICS or row['bytes'] != 0 for row in rows):
            raise RuntimeError('Legacy private files remain outside profile storage. Complete reviewed migration before signing in.')

    def _has_legacy(self):
        if callable(self.legacy_check):
            result = self.legacy_check(self.root)
            return not isinstance(result, dict) or result.get('clean') is not True
        from profile_migration import legacy_inventory
        return any(row['source'] not in _EMPTY_DIAGNOSTICS or row['bytes'] != 0
                   for row in legacy_inventory(self.root)['files'])

    def _stop(self, session, marker):
        if not callable(self.quiesce):
            raise RuntimeError('A verified writer shutdown callback is required before opening or sealing a profile.')
        result = self.quiesce(session, marker)
        if not isinstance(result, dict) or result.get('stopped') is not True:
            raise RuntimeError('Owned process and GUI writer shutdown could not be verified; the installation remains locked.')

    def _residual_users(self, marker):
        users = self.root/'Private/Users'
        _contained(self.root, users)
        residual = set()
        if users.exists():
            for directory in users.iterdir():
                _contained(self.root, directory)
                if not directory.is_dir() or not re.fullmatch('[a-f0-9]{32}', directory.name):
                    raise RuntimeError('Unexpected profile storage requires explicit recovery.')
                workspace = directory/'Workspace'
                _contained(self.root, workspace)
                pending = any((directory/name).exists() for name in ('seal-pending.json', 'restore-pending.json', 'restore-inflight.enc', 'harvest-pending.json', 'hydration.enc'))
                has_files = False
                if workspace.exists():
                    for folder, names, files in walk(workspace, followlinks=False, onerror=raise_walk_error):
                        for name in names + files:
                            _contained(self.root, Path(folder)/name)
                        if files:
                            has_files = True
                            break
                if pending or has_files:
                    residual.add(directory.name)
        if marker and marker['state'] != 'closed':
            residual.add(marker['user_id'])
        return sorted(residual)

    def prepare(self, session):
        with self._mutex:
            self._validate(session)
            self._progress('authenticate-ready', 'Account authenticated; checking workspace recovery...')
            self._acquire()
            if self.session is not None or self._recovery_sessions or self._recovery_authorizer is not None:
                raise RuntimeError('This controller already owns an open profile. Log out and restart before changing accounts.')
            prior = self._read_marker()
            self._progress('inspect', 'Checking for interrupted workspaces...')
            self._prior_sealed = bool(prior and prior['state'] == 'closed')
            residual = self._residual_users(prior)
            # Global logs left by a crash belong to the marker's previous owner.
            # Authenticate that owner before moving any files or stopping jobs.
            recover = set(residual)
            if prior and callable(self.harvest) and self._has_legacy():
                recover.add(prior['user_id'])
            if any(uid != session.user_id for uid in recover) and session.role != 'admin':
                raise PermissionError('A previous owner or administrator must recover and seal the earlier workspace before this account can open.')
            if not recover:
                self._clean_legacy()
            self._progress('quiesce', 'Verifying that owned background processes have stopped...')
            self._stop(session, prior)
            if recover:
                self._recovery_authorizer = session
            for uid in sorted(recover):
                self._progress('recover', 'Recovering and sealing an interrupted workspace...')
                owner = session if uid == session.user_id else self.backend.profile_session(session, uid)
                self._recovery_sessions.append(owner)
                completed = False
                try:
                    workspace = ProfileWorkspace(self.root, owner, on_progress=self.on_progress)
                    epoch = prior['epoch'] if prior and prior['user_id'] == uid else uuid.uuid4().hex
                    self._write_marker(uid, epoch, 'closing', owner.role)
                    if (workspace.base/'seal-pending.json').exists():
                        workspace.seal(writers_stopped=True)
                    if (workspace.base/'restore-pending.json').exists():
                        workspace.recover_for_seal(writers_stopped=True)
                    elif (not (workspace.base/'hydration.enc').exists() and
                          not workspace.inventory() and (workspace.vault/'current.enc').exists()):
                        workspace.recover_for_seal(writers_stopped=True)
                    self._harvest(owner)
                    self._clean_legacy()
                    receipt = workspace.seal(writers_stopped=True)
                    if receipt.get('sealed') is not True or workspace.inventory():
                        raise RuntimeError('Previous profile sealing failed verification.')
                    self._write_marker(uid, epoch, 'closed', owner.role)
                    completed = True
                finally:
                    if completed:
                        self._recovery_sessions.remove(owner)
                        if owner is not session:
                            self.backend.logout(owner)
            self._recovery_authorizer = None
            self._clean_legacy()
            workspace = ProfileWorkspace(self.root, session, on_progress=self.on_progress)
            if not (workspace.vault/'current.enc').exists():
                if workspace.vault.exists() and any(workspace.vault.iterdir()):
                    raise RuntimeError('Profile snapshot pointer is missing; existing encrypted data requires recovery.')
                if workspace.inventory():
                    raise RuntimeError('Unexpected profile plaintext remains before opening.')
                workspace.snapshot()  # Establish a verified empty initial profile.
            epoch = uuid.uuid4().hex
            self._write_marker(session.user_id, epoch, 'opening', session.role)
            # Hold the session/lock even if restore fails: only verified recovery
            # may remove partially restored plaintext or authorize another user.
            self.session = session
            self.epoch = epoch
            receipt = workspace.restore(lazy=True) if self.lazy_restore else workspace.restore()
            if receipt.get('ready') is not True or receipt.get('user_id') != session.user_id:
                raise RuntimeError('Profile restore did not verify the requested identity.')
            self._write_marker(session.user_id, epoch, 'open', session.role)
            os.environ[UID_ENV], os.environ[EPOCH_ENV] = session.user_id, epoch
            if self.lazy_restore:
                from profile_hydration import HydrationBroker
                try:
                    self._hydration = HydrationBroker(self.root, (session.user_id, epoch),
                                                       lambda: self.session, self._validate)
                    os.environ.update(self._hydration.environment())
                except BaseException:
                    # Listener startup can succeed before environment publication
                    # fails. Close its admission immediately; keep the object and
                    # authenticated session if joining fails, so verified close
                    # can retry instead of abandoning a live recovery writer.
                    if self._hydration is not None:
                        try: self._hydration.pause()
                        except Exception: pass
                        try: self._close_hydration()
                        except Exception: pass
                    # Remove path authority even if rewriting the recovery
                    # marker fails. The session/key and process lock stay held.
                    os.environ.pop(UID_ENV, None); os.environ.pop(EPOCH_ENV, None)
                    self._write_marker(session.user_id, epoch, 'opening', session.role)
                    raise
            from account_connections import unlock_session
            unlock_session(self.root, session)
            self._progress('ready', 'Workspace verified; opening PortalAI...')
            return {'ready': True, 'user_id': session.user_id, 'epoch': epoch}

    def replace_session(self, session):
        with self._mutex:
            self._validate(session)
            if self.session is None or self.session.user_id != session.user_id:
                raise PermissionError('Replacement authentication must belong to the open profile')
            self.session = session

            from account_connections import unlock_session
            unlock_session(self.root, session)

    def close(self, session, *, writers_stopped=False):
        with self._mutex:
            self._validate(session)
            if writers_stopped is not True or self.session is None or session.user_id != self.session.user_id:
                raise RuntimeError('Closing requires the active account and explicit writer shutdown.')
            prior = self._read_marker()
            if not prior or prior['user_id'] != session.user_id or prior['epoch'] != self.epoch:
                raise RuntimeError('Runtime identity changed before profile shutdown.')
            self._close_hydration()  # Admission, cancellation and thread join precede sealing.
            from account_connections import clear_session
            clear_session()
            self._stop(session, prior)  # Recheck; a caller's old boolean is insufficient.
            self._harvest(session)
            self._clean_legacy()
            self._write_marker(session.user_id, self.epoch, 'closing', session.role)
            workspace = ProfileWorkspace(self.root, session)
            if (workspace.base/'restore-pending.json').exists():
                workspace.recover_for_seal(writers_stopped=True)
            result = workspace.seal(writers_stopped=True)
            if result.get('sealed') is not True or workspace.inventory():
                raise RuntimeError('Profile sealing did not verify an empty plaintext workspace.')
            self._write_marker(session.user_id, self.epoch, 'closed', session.role)
            for name in (UID_ENV, EPOCH_ENV):
                os.environ.pop(name, None)
            self.backend.logout(session)
            self.session = None
            self.epoch = None
            self.release_closed()
            return {'stopped': True, 'sealed': True, 'user_id': session.user_id, 'generation': result['generation']}
