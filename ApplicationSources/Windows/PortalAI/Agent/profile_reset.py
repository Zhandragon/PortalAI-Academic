"""Explicit, recoverable reset of sealed local profiles; never called on startup.

Only Private/Accounts and Private/Users are payload reset targets. Old password-
wrapped registries and encrypted vaults are retained inside the transaction until
commit, then removed after byte verification. Deletion is not guaranteed physical
SSD erasure, and copies in other backups are not erased by this operation.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from portable_fs import Path, walk
import re
import secrets
import threading
import time

from local_accounts import LocalAccounts, AuthorizationError, RecoveryRequired, _json, _uid
from profile_paths import _contained
from profile_workspace import ProfileWorkspace, _atomic_bytes

CONFIRMATION_PHRASE = "RESET ALL PRIVATE PROFILES"
_ACCOUNT_FILES = ("registry.json", "initialized.json", "registry-recovery.json")
_COMMITTED = {"committed", "cleaning", "complete"}
_ROLLBACK_CLEANING = 'rollback-cleaning'
_MAX_JOURNAL = 32 * 1024 * 1024


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class ResetCoordinator:
    def __init__(self, root, accounts=None):
        self.root = Path(root).resolve()
        self.accounts = accounts or LocalAccounts(self.root)
        if self.accounts.root != self.root: raise ValueError("Account registry belongs to another root")
        self.base = _contained(self.root, self.root / "Private/Reset")
        self.journal = self.base / "transaction.json"
        self._tokens = {}
        self._session_guard = None
        self._session_depth = 0
        self._session_mutex = threading.Lock()

    @contextmanager
    def hold_session(self):
        """Exclude every GUI login during review/reset; reusable across UI workers."""
        from mission_runner import process_lock
        with self._session_mutex:
            if self._session_guard is None:
                path = _contained(self.root,self.root/'Private/profile-runtime.lock')
                guard = process_lock(path)
                try: guard.__enter__()
                except OSError:
                    raise RuntimeError('Another PortalAI controller owns a profile; close and seal it before reset') from None
                self._session_guard = guard
            self._session_depth += 1
        try: yield
        finally:
            with self._session_mutex:
                self._session_depth -= 1
                if not self._session_depth:
                    self._session_guard.__exit__(None,None,None)
                    self._session_guard = None

    @contextmanager
    def _lock(self):
        with self.hold_session(), self._reset_lock():
            yield

    @contextmanager
    def _reset_lock(self):
        _contained(self.root, self.base); self.base.mkdir(parents=True, exist_ok=True)
        path = _contained(self.root, self.base / "reset.lock")
        with path.open("a+b") as handle:
            if not path.stat().st_size: handle.write(b"0"); handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("Another profile reset is already in progress") from None
            try: yield
            finally:
                handle.seek(0)
                if os.name == "nt": msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _atomic(self, path, value):
        _contained(self.root, path); path.parent.mkdir(parents=True, exist_ok=True)
        if path == self.journal:
            encoded = _json(value)
            if len(encoded) > _MAX_JOURNAL: raise RecoveryRequired("Reset journal exceeds the review limit")
            _atomic_bytes(path, encoded)
            return
        self.accounts._atomic(path, value)

    def _copy_verified(self, source, destination):
        _contained(self.root, source); _contained(self.root, destination)
        expected = _hash(source)
        data = source.read_bytes()
        if len(data) > 1024*1024+4096: raise RecoveryRequired("Account recovery file exceeds limit")
        self._atomic(destination, json.loads(data))
        if _hash(destination) != expected:
            # Registry serialization is canonical, so exact bytes are required.
            raise RecoveryRequired("Registry recovery copy differs from source")
        return expected

    def _closed(self, writer_check):
        if not callable(writer_check): raise RuntimeError("A writer-ownership check is required")
        result = writer_check()
        if result is not True and not (isinstance(result, dict) and result.get("quiescent") is True):
            raise RuntimeError("Profile writers have not all stopped")
        marker = _contained(self.root, self.root / "Private/active-session.json")
        if marker.exists():
            if marker.stat().st_size > 16384: raise RecoveryRequired("Invalid active-session marker")
            try: state = json.loads(marker.read_text(encoding="utf-8"))
            except Exception: raise RecoveryRequired("Invalid active-session marker") from None
            if state.get("state") not in {"closed", "locked", "sealed"}:
                raise RuntimeError("Close and seal the active account workspace before Start fresh")

    def _legacy_absent(self):
        # One classifier must define the private boundary for both migration and
        # reset, including historical logs/backups and mixed runtime leftovers.
        from profile_migration import legacy_inventory
        remaining = legacy_inventory(self.root)
        if remaining["files"]:
            raise RecoveryRequired("Legacy private data must be migrated first: " + remaining["files"][0]["source"])

    def _files(self, base, relative_prefix, exclude=()):
        rows = []
        _contained(self.root, base)
        if not base.exists(): return rows
        if not base.is_dir(): raise RecoveryRequired("Reset target is not a directory")
        for folder, dirs, files in walk(base, followlinks=False):
            for name in dirs + files: _contained(self.root, Path(folder) / name)
            for name in files:
                path = Path(folder) / name
                info = path.stat()
                if not path.is_file() or info.st_nlink != 1:
                    raise RecoveryRequired("Linked or nonregular reset target requires manual review")
                relative = path.relative_to(base).as_posix()
                if relative in exclude: continue
                digest = _hash(path); after = path.stat()
                if (info.st_size, info.st_mtime_ns, info.st_ino, info.st_nlink) != (after.st_size, after.st_mtime_ns, after.st_ino, after.st_nlink):
                    raise RecoveryRequired("Reset target changed while its inventory was checked")
                rows.append({"path": relative_prefix + "/" + relative,
                             "bytes": info.st_size, "sha256": digest})
        return sorted(rows, key=lambda row: row["path"])

    def _harvest_receipt(self, workspace):
        """Accept only a completed receipt backed by an authenticated saved plan."""
        path = _contained(self.root, workspace.base / 'harvest-last.json')
        if not path.exists(): return
        if path.stat().st_size > 16384: raise RecoveryRequired('Oversized harvest receipt requires recovery')
        try:
            receipt = json.loads(path.read_text(encoding='utf-8'))
            generation = _uid(receipt['generation'])
            if receipt['user_id'] != workspace.uid: raise ValueError('wrong profile')
            manifest = workspace.verify(generation)
            from profile_workspace import _crypto, MAGIC
            from profile_migration import SessionHarvest
            AESGCM = _crypto()[3]
            for row in manifest['files']:
                if not re.fullmatch(r'Data/ProfileMigration/harvest-[a-f0-9]{32}\.json', row['path']): continue
                if row['bytes'] > _MAX_JOURNAL: raise ValueError('oversized saved harvest plan')
                blob = workspace.blob_path(manifest, row)
                data = blob.read_bytes(); offset = len(MAGIC)
                if not data.startswith(MAGIC) or len(data) != row['bytes'] + offset + 28: raise ValueError('invalid saved plan')
                plain = AESGCM(workspace._key()).decrypt(data[offset:offset+12], data[offset+12:], workspace._aad(row['path']))
                if hashlib.sha256(plain).hexdigest() != row['sha256']: raise ValueError('saved plan mismatch')
                plan = json.loads(plain)
                if plan.get('digest') != receipt.get('digest'): continue
                state = {'version':1,'user_id':workspace.uid,'digest':receipt['digest'],'plan_path':row['path']}
                SessionHarvest(self.root, workspace.session)._validate_plan(plan,state)
                expected = {'version':1,'user_id':workspace.uid,'digest':plan['digest'],
                            'files':len(plan['files']),'bytes':plan['bytes'],'generation':generation}
                if receipt != expected: raise ValueError('receipt differs from its saved plan')
                return
            raise ValueError('authenticated harvest plan is missing')
        except Exception as exc:
            raise RecoveryRequired('Completed harvest receipt could not be verified: ' + str(exc)) from None

    def _snapshot(self, admin, writer_check):
        self._closed(writer_check); self._legacy_absent()
        with self.accounts._lock():
            data = self.accounts._read(); self.accounts._validate(admin, data, admin=True)
            if not self.accounts._recovery_current(data):
                raise RecoveryRequired('Sign in as an administrator to repair the current encrypted registry recovery copy before reset')
            users = [
                {key: slot[key] for key in ("user_id", "username", "role", "pending")}
                for slot in data["slots"].values()]
            account_rows = self._files(self.root / "Private/Accounts", "Private/Accounts", exclude=("registry.lock",))
            unexpected = [row for row in account_rows if row["path"] not in
                          {"Private/Accounts/" + name for name in _ACCOUNT_FILES}]
            if unexpected: raise RecoveryRequired("Unknown account files require review before reset")
            account_rows = [row for row in account_rows if not row["path"].endswith("/registry.lock")]
        user_base = _contained(self.root, self.root / "Private/Users")
        if user_base.exists():
            for folder in user_base.iterdir():
                _contained(self.root, folder); _uid(folder.name)
                if not folder.is_dir() or folder.name not in data["slots"]:
                    raise RecoveryRequired("Unknown private profile requires review")
                if any(path.name not in {"Workspace", "Vault", "workspace.lock", "harvest-last.json"} for path in folder.iterdir()):
                    raise RecoveryRequired("Profile recovery/unknown files must be resolved before reset")
                delegated = self.accounts.profile_session(admin, folder.name)
                try:
                    workspace = ProfileWorkspace(self.root, delegated)
                    if workspace.inventory(): raise RuntimeError("Seal every profile's plaintext workspace before reset")
                    self._harvest_receipt(workspace)
                    if workspace.vault.exists():
                        if (workspace.vault / "current.enc").exists(): workspace.verify()
                        for generation in workspace.vault.iterdir():
                            _contained(self.root, generation)
                            if generation.name == "current.enc": continue
                            if not generation.is_dir(): raise RecoveryRequired("Unknown vault file requires review")
                            _uid(generation.name); workspace.verify(generation.name)
                finally: self.accounts.logout(delegated)
        rows = sorted(account_rows + self._files(user_base, "Private/Users"), key=lambda row: row["path"])
        self._closed(writer_check)
        payload = {"version": 1, "old_instance_id": data["instance_id"], "old_revision": data["revision"],
                   "roots": ["Private/Accounts", "Private/Users"], "users": users, "files": rows,
                   "bytes": sum(row["bytes"] for row in rows), "confirmation_phrase": CONFIRMATION_PHRASE,
                   "deletion_limit": "SSD blocks and separate backups may retain old data; this is not secure physical erasure"}
        payload["digest"] = hashlib.sha256(_json(payload)).hexdigest()
        if len(_json(payload)) > _MAX_JOURNAL - 16384:
            raise RecoveryRequired("Private reset inventory exceeds the bounded review limit")
        return payload

    def plan(self, admin, *, writer_check):
        if self.journal.exists(): raise RecoveryRequired("An interrupted reset requires explicit recovery first")
        return self._snapshot(admin, writer_check)

    def _reviewed(self, admin, plan, writer_check):
        current = self._snapshot(admin, writer_check)
        if not isinstance(plan, dict) or not hmac.compare_digest(_json(current), _json(plan)):
            raise RecoveryRequired("Private reset plan changed; review a new plan before confirming")

    def request_confirmation(self, admin, plan, *, admin_password, typed_confirmation, writer_check, ttl_seconds=120):
        if typed_confirmation != CONFIRMATION_PHRASE: raise AuthorizationError("Typed reset confirmation did not match")
        self._reviewed(admin, plan, writer_check)
        token = self.accounts.request_confirmation(admin, "start-fresh", admin_password=admin_password, ttl_seconds=ttl_seconds)
        self._tokens[hashlib.sha256(token.encode()).hexdigest()] = plan["digest"]
        return token

    def _write_journal(self, state, old_master=None, new_master=None):
        payload = {key: value for key, value in state.items() if key != "auth"}
        signed = dict(payload); signed["auth"] = {}
        for name, key in (("old", old_master), ("new", new_master)):
            if key is not None: signed["auth"][name] = hmac.digest(key, _json(payload), "sha256").hex()
        self._atomic(self.journal, signed)

    def _read_journal(self):
        _contained(self.root, self.journal)
        if self.journal.stat().st_size > _MAX_JOURNAL: raise RecoveryRequired("Reset journal exceeds limit")
        try:
            state = json.loads(self.journal.read_text(encoding="utf-8")); _uid(state["transaction_id"])
            _uid(state["old_instance_id"]); _uid(state["new_instance_id"])
            if state["version"] != 1 or state["phase"] not in {"prepared", "users-staged", "swapping", _ROLLBACK_CLEANING, *_COMMITTED}:
                raise ValueError()
            if state["plan"]["roots"] != ["Private/Accounts", "Private/Users"]: raise ValueError()
            return state
        except Exception: raise RecoveryRequired("Reset journal is invalid; manual verified recovery is required") from None

    def recovery_status(self):
        if not self.journal.exists(): return {"pending": False}
        try:
            state = self._read_journal()
            return {"pending": True, "phase": state["phase"], "transaction_id": state["transaction_id"],
                    "action": "finish" if state["phase"] in _COMMITTED else "rollback", "authenticated": False}
        except Exception as exc: return {"pending": True, "action": "manual-review", "reason": str(exc)}

    def _verify_journal(self, state, side, master):
        payload = {key: value for key, value in state.items() if key != "auth"}
        signature = state.get("auth", {}).get(side, "")
        if not isinstance(signature, str) or not hmac.compare_digest(signature, hmac.digest(master, _json(payload), "sha256").hex()):
            raise RecoveryRequired("Reset journal authentication failed")

    def _tx(self, state):
        return _contained(self.root, self.base / _uid(state["transaction_id"]))

    @contextmanager
    def _recovery_admin(self, accounts, username, password, *, allow_reset=False):
        actor = accounts._login(username, password, allow_reset=allow_reset)
        try:
            if actor.role != "admin": raise AuthorizationError("Administrator authentication is required")
            yield actor
        finally:
            accounts.logout(actor)

    def _write_active_accounts(self, source_root):
        source = source_root / "Private/Accounts"
        for name in _ACCOUNT_FILES:
            path = _contained(self.root, source / name)
            self._atomic(self.root / "Private/Accounts" / name, json.loads(path.read_text(encoding="utf-8")))
            if _hash(path) != _hash(self.root / "Private/Accounts" / name):
                raise RecoveryRequired("Active registry replacement did not verify")

    def _prune_empty(self, path):
        _contained(self.root, path)
        if not path.exists(): return
        for folder, dirs, files in walk(path, topdown=False, followlinks=False):
            for name in dirs + files: _contained(self.root, Path(folder) / name)
            if files: raise RecoveryRequired("Unexpected reset recovery files remain")
            Path(folder).rmdir()

    def _cleanup(self, state):
        """Remove only unchanged files listed in the authenticated reset plan."""
        tx = self._tx(state)
        expected = {row["path"]: row for row in state["plan"]["files"]}
        for scope, base in (("Private/Users", tx / "old-users"), ("Private/Accounts", tx / "old-root/Private/Accounts")):
            actual = self._files(base, scope)
            for row in actual:
                if scope == "Private/Accounts" and row["path"] == "Private/Accounts/registry.lock":
                    continue
                if expected.get(row["path"]) != row: raise RecoveryRequired("Retired reset files changed; cleanup stopped")
            for row in actual:
                path = base / row["path"][len(scope)+1:]
                _contained(self.root, path)
                if _hash(path) != row["sha256"]: raise RecoveryRequired("Retired file changed during cleanup")
                path.unlink()
            self._prune_empty(base)
        # The verified replacement remains under the active account directory.
        new_base = tx / "new-root/Private/Accounts"
        actual = self._files(new_base, "Private/Accounts")
        for row in actual:
            name = row["path"][len("Private/Accounts/"):]
            if name == "registry.lock": continue
            if name not in _ACCOUNT_FILES or row["sha256"] != state["new_hashes"][name]:
                raise RecoveryRequired("Staged replacement registry changed")
        for row in actual:
            path = new_base / Path(row["path"]).name
            _contained(self.root, path); path.unlink()
        self._prune_empty(new_base)
        self._prune_empty(tx)

    def _restored(self, state, master):
        """Verify the active rollback copy before deleting any transaction copy."""
        with self.accounts._lock():
            restored = self.accounts._read(allow_reset=True)
            self.accounts._private(restored, master)
            if restored['instance_id'] != state['old_instance_id']:
                raise RecoveryRequired('Restored account instance differs from the original')
            actual = self._files(self.root/'Private/Accounts', 'Private/Accounts', exclude=('registry.lock',))
            actual += self._files(self.root/'Private/Users', 'Private/Users')
            if sorted(actual, key=lambda row:row['path']) != state['plan']['files']:
                raise RecoveryRequired('Restored profile bytes differ from the reviewed original plan')

    def _finish_rollback(self, state, master, writer_check):
        self._closed(writer_check)
        self._restored(state, master)
        # The restored active registry now authenticates recovery even if a
        # crash interrupts deletion of an old transaction registry envelope.
        state['phase'] = _ROLLBACK_CLEANING
        self._write_journal(state, old_master=master)
        self.accounts.logout()
        self._cleanup(state)
        self._atomic(self.base / (state['transaction_id'] + '-rolled-back.json'), {
            'version':1, 'transaction_id':state['transaction_id'], 'state':'rolled-back',
            'recovery_copies_retained':False})
        self.journal.unlink()
        return {'rolled_back':True, 'login_required':True, 'recovery_copies_retained':False}

    def execute(self, admin, plan, confirmation_token, *, admin_password, new_username, new_password,
                writer_check, pending_users=()):
        """Reset only after reviewed confirmation. Failures leave an explicit journal."""
        with self._lock():
            if self.journal.exists(): raise RecoveryRequired("An interrupted reset requires recovery first")
            self._reviewed(admin, plan, writer_check)
            token_key = hashlib.sha256(str(confirmation_token).encode()).hexdigest()
            if self._tokens.pop(token_key, None) != plan["digest"]:
                raise AuthorizationError("Confirmation was not issued for this reviewed reset plan")
            with self.accounts._lock():
                data = self.accounts._read(); self.accounts._admin(admin, data, admin_password)
                self.accounts._consume(admin, data, confirmation_token, "start-fresh", None)
                old_master = bytes(admin._master)
            transaction_id = secrets.token_hex(16)
            tx = _contained(self.root, self.base / transaction_id); tx.mkdir()
            staged = LocalAccounts(tx / "new-root")
            new_admin = staged.bootstrap(new_username, new_password, pending_users=pending_users)
            new_master = bytes(new_admin._master)
            new_data = staged._read()
            state = {"version": 1, "transaction_id": transaction_id, "phase": "prepared", "plan": plan,
                     "old_instance_id": data["instance_id"], "new_instance_id": new_data["instance_id"],
                     "new_hashes": {name: _hash(staged.base / name) for name in _ACCOUNT_FILES}}
            old_base = tx / "old-root/Private/Accounts"; old_base.mkdir(parents=True)
            for name in _ACCOUNT_FILES: self._copy_verified(self.root / "Private/Accounts" / name, old_base / name)
            # Staging must still log in with the requested password before any payload swap.
            checked = staged.login(new_username, new_password)
            if checked.role != "admin": raise RecoveryRequired("Replacement owner could not authenticate")
            staged.logout()
            self._write_journal(state, old_master, new_master)
            with self.accounts._lock():
                current = self.accounts._read(allow_reset=True); self.accounts._admin(admin, current, admin_password)
                if current["instance_id"] != state["old_instance_id"]: raise RecoveryRequired("Account registry changed during reset staging")
                current_rows = self._files(self.root / "Private/Accounts", "Private/Accounts", exclude=("registry.lock",))
                current_rows = [row for row in current_rows if not row["path"].endswith("/registry.lock")]
                if current_rows != [row for row in plan["files"] if row["path"].startswith("Private/Accounts/")]:
                    raise RecoveryRequired("Account registry changed during reset staging")
                self._closed(writer_check)
                users = _contained(self.root, self.root / "Private/Users")
                if self._files(users, "Private/Users") != [row for row in plan["files"] if row["path"].startswith("Private/Users/")]:
                    raise RecoveryRequired("Private profiles changed during reset staging")
                if users.exists(): os.replace(users, tx / "old-users")
                users.mkdir(parents=True, exist_ok=True)
                state["phase"] = "users-staged"; self._write_journal(state, old_master, new_master)
                state["phase"] = "swapping"; self._write_journal(state, old_master, new_master)
                self._write_active_accounts(tx / "new-root")
                replaced = self.accounts._read(allow_reset=True); self.accounts._private(replaced, new_master)
                if replaced["instance_id"] != state["new_instance_id"]: raise RecoveryRequired("Replacement registry identity mismatch")
                state["phase"] = "committed"; self._write_journal(state, old_master, new_master)
            self.accounts.logout()
            self._closed(writer_check)
            state["phase"] = "cleaning"; self._write_journal(state, old_master, new_master)
            self._cleanup(state)
            state["phase"] = "complete"; self._write_journal(state, new_master=new_master)
            self._atomic(self.base / "last-reset.json", {"version": 1, "transaction_id": transaction_id,
                         "completed_at": time.time(), "removed_bytes": plan["bytes"],
                         "deletion_limit": plan["deletion_limit"], "state": "complete"})
            self.journal.unlink()
            return {"reset": True, "new_username": new_username, "login_required": True,
                    "removed_bytes": plan["bytes"], "deletion_limit": plan["deletion_limit"]}

    def recover(self, username, password, *, action, writer_check):
        """Explicit authenticated rollback before commit or cleanup after commit."""
        with self._lock():
            state = self._read_journal(); tx = self._tx(state)
            self._closed(writer_check); self._legacy_absent()
            if action == "rollback" and state["phase"] not in _COMMITTED:
                if state['phase'] == _ROLLBACK_CLEANING:
                    with self._recovery_admin(self.accounts, username, password, allow_reset=True) as actor:
                        master = bytes(actor._master); self._verify_journal(state, 'old', master)
                    return self._finish_rollback(state, master, writer_check)
                source = LocalAccounts(tx / "old-root")
                with self._recovery_admin(source, username, password) as actor:
                    master = bytes(actor._master); self._verify_journal(state, "old", master)
                users = _contained(self.root, self.root / "Private/Users")
                retired = _contained(self.root, tx / "old-users")
                expected_accounts = [row for row in state['plan']['files'] if row['path'].startswith('Private/Accounts/')]
                actual_accounts = [row for row in self._files(tx / 'old-root/Private/Accounts', 'Private/Accounts')
                                   if not row['path'].endswith('/registry.lock')]
                if actual_accounts != expected_accounts:
                    raise RecoveryRequired('Old account recovery copy differs from the reviewed reset plan')
                expected_users = [row for row in state['plan']['files'] if row['path'].startswith('Private/Users/')]
                if self._files(retired if retired.exists() else users, 'Private/Users') != expected_users:
                    raise RecoveryRequired('Old profile recovery copy differs from the reviewed reset plan')
                with self.accounts._lock():
                    if retired.exists():
                        if self._files(users, "Private/Users"):
                            raise RecoveryRequired("New profile data appeared; rollback will not overwrite it")
                        self._prune_empty(users); os.replace(retired, users)
                    self._write_active_accounts(tx / "old-root")
                    restored = self.accounts._read(allow_reset=True); self.accounts._private(restored, master)
                source.logout()
                return self._finish_rollback(state, master, writer_check)
            if action == "finish" and state["phase"] in _COMMITTED:
                with self._recovery_admin(self.accounts, username, password, allow_reset=True) as actor:
                    master = bytes(actor._master); self._verify_journal(state, "new", master)
                    if self.accounts._read(allow_reset=True)["instance_id"] != state["new_instance_id"]:
                        raise RecoveryRequired("Active registry does not match committed reset")
                self._cleanup(state)
                self._atomic(self.base / "last-reset.json", {"version": 1, "transaction_id": state["transaction_id"],
                    "completed_at": time.time(), "removed_bytes": state["plan"]["bytes"],
                    "deletion_limit": state["plan"]["deletion_limit"], "state": "complete"})
                self.journal.unlink()
                return {"reset": True, "login_required": True, "deletion_limit": state["plan"]["deletion_limit"]}
            raise RecoveryRequired("Only rollback before commit or finish after commit is allowed")
