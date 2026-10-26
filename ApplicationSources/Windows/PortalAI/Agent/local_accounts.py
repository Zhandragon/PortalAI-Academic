"""Portable local identities, password-wrapped profile keys and locked sessions.

Login labels are public. The registry of profile keys is AES-GCM encrypted with
an admin master key; that master is wrapped only for administrators. Guest is an
explicitly public/shared profile and its data key is public. This is application
access control and at-rest encryption, not an OS sandbox against the logged-in
host user. No password or authenticated session is written to disk.

An intact standard-user password envelope authenticates that user's profile key
independently. Damage limited to the encrypted administrator registry blocks
administrator operations but does not prevent that user recovering its own key.
Missing/malformed registry structure or a damaged user envelope fails closed.
A current checksum-verified encrypted registry mirror supports explicit admin-
password recovery. Interrupted credential updates never silently select an old
mirror; externally exported backups retain their own historical passwords.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import uuid
import weakref

ROOT = Path(__file__).resolve().parents[1]
ROLES = frozenset(("admin", "user", "guest"))
_KDF_N = 131072
_MAX_REGISTRY = 1024 * 1024
_MAX_USERS = 64
_PROFILE_ROOTS = ("Private/Users", "Private/Accounts")
_LIFECYCLE_EVIDENCE = ("Private/active-session.json", "Private/migration-pending.json", "Private/migration-complete.json")


class RecoveryRequired(RuntimeError):
    """The existing installation must be recovered, never silently initialized."""


class AuthenticationError(PermissionError):
    pass


class AuthorizationError(PermissionError):
    pass


def _crypto():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Local accounts require bundled Python 3.12")
    if os.name == "nt":relative = "Runtime/AccountPython/packages"
    elif sys.platform.startswith('linux'):relative = "Runtime/AccountPython/linux-packages"
    elif sys.platform=='darwin':relative = "Runtime/AccountPython/macos-packages"
    else:raise RuntimeError("Local accounts are supported on Windows, Linux, and macOS")
    packages = ROOT / relative
    if not (packages / "cryptography/__init__.py").is_file():
        raise RuntimeError("Bundled account cryptography is missing")
    if str(packages) not in sys.path:
        sys.path.insert(0, str(packages))
    import cryptography
    if not Path(cryptography.__file__).resolve().is_relative_to(packages.resolve()):
        raise RuntimeError("Account cryptography came from outside the portable account runtime")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return AESGCM, Scrypt


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _encode(value):
    return base64.b64encode(value).decode("ascii")


def _decode(value, length=None):
    if not isinstance(value, str) or len(value) > _MAX_REGISTRY * 2:
        raise RecoveryRequired("Malformed encrypted account value")
    try:
        result = base64.b64decode(value, validate=True)
    except Exception:
        raise RecoveryRequired("Malformed encrypted account value") from None
    if length is not None and len(result) != length:
        raise RecoveryRequired("Malformed encrypted account value length")
    return result


def _seal(key, value, aad):
    AESGCM, _ = _crypto()
    nonce = secrets.token_bytes(12)
    return {"nonce": _encode(nonce), "ciphertext": _encode(AESGCM(key).encrypt(nonce, value, aad))}


def _open(key, value, aad):
    AESGCM, _ = _crypto()
    if not isinstance(value, dict) or set(value) != {"nonce", "ciphertext"}:
        raise RecoveryRequired("Malformed encrypted account envelope")
    return AESGCM(key).decrypt(_decode(value["nonce"], 12), _decode(value["ciphertext"]), aad)


def _password(value, temporary=False):
    minimum = 1 if temporary else 12
    if not isinstance(value, str) or not minimum <= len(value) <= 1024:
        raise ValueError(f"Password must contain {minimum}..1024 characters")
    return value


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,47}", value):
        raise ValueError("Username must be 1..48 plain letters, digits, spaces, dots, underscores or hyphens")
    if value != value.strip() or value in (".", ".."):
        raise ValueError("Invalid username")
    return value


def _uid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid user ID")
    return value


def _kdf(password, salt):
    _, Scrypt = _crypto()
    return Scrypt(salt=salt, length=32, n=_KDF_N, r=8, p=1).derive(password.encode("utf-8"))


def _public(slot):
    return {key: slot[key] for key in ("user_id", "username", "role", "pending", "temporary_password")}


def _slot_aad(instance, slot, purpose):
    return b"PortalAI-local-accounts-v1:" + _json({"instance": instance, "purpose": purpose,
        **{key: slot[key] for key in ("user_id", "username", "role", "epoch", "pending", "temporary_password")}})


def _fingerprint(slot):
    return hashlib.sha256(_json(slot)).hexdigest()


def _identity_fingerprint(slot):
    # Only administrators change identity/role/enrollment. Password envelopes and
    # their epoch may be rewrapped by a user holding the existing profile key.
    return hashlib.sha256(_json({key: slot[key] for key in
        ("user_id", "username", "role", "pending", "created_at")})).hexdigest()


def _credential_mac(slot, dek):
    return hmac.digest(dek, _json({key: value for key, value in slot.items() if key != "credential_mac"}), "sha256")


class Session:
    """Memory-only handle. Constructing a lookalike does not authenticate it."""
    __slots__ = ("_store", "_token", "_user", "_dek", "_master", "_fingerprint",
                 "_expires", "_parent", "_active")

    def __init__(self, store, slot, dek, master=None, parent=None):
        self._store = weakref.ref(store)
        self._token = secrets.token_urlsafe(32)
        self._user = _public(slot)
        self._dek = bytearray(dek)
        self._master = bytearray(master) if master is not None else None
        self._fingerprint = _fingerprint(slot)
        self._expires = store.clock() + store.session_seconds if store.session_seconds is not None else None
        self._parent = parent
        self._active = True

    @property
    def user_id(self): return self._user["user_id"]
    @property
    def username(self): return self._user["username"]
    @property
    def role(self): return self._user["role"]
    @property
    def temporary_password(self): return self._user["temporary_password"]
    @property
    def recovery_warning(self):
        store = self._store()
        return store.recovery_warning if store is not None else ''
    @property
    def active(self):
        store = self._store()
        if store is None or not self._active:
            return False
        try:
            store.validate_session(self)
            return True
        except (OSError, ValueError, RuntimeError, PermissionError):
            return False
    @property
    def profile_key(self):
        store = self._store()
        if store is None:
            raise AuthenticationError("Session is locked")
        return store.data_key(self)

    def __repr__(self):
        return f"Session(user_id={self.user_id!r}, username={self.username!r}, role={self.role!r})"


class LocalAccounts:
    def __init__(self, root=ROOT, *, clock=time.time, session_seconds=None):
        self.root = Path(root).resolve()
        self.clock = clock
        if session_seconds is not None and not 60 <= session_seconds <= 24*60*60:
            raise ValueError("Session lifetime must be 60 seconds..24 hours")
        self.session_seconds = session_seconds
        self._sessions = {}
        self._confirmations = {}
        self._thread_lock = threading.RLock()
        self.base = self._safe("Private/Accounts")
        self.registry_path = self._safe("Private/Accounts/registry.json")
        self.marker_path = self._safe("Private/Accounts/initialized.json")
        self.recovery_path = self._safe("Private/Accounts/registry-recovery.json")
        self.write_pending_path = self._safe("Private/Accounts/registry-write-pending.json")
        self.recovery_warning = ''

    def _safe(self, relative):
        if not isinstance(relative, str) or "\\" in relative or relative.startswith("/") or ":" in relative:
            raise ValueError("Account path must be portable and relative")
        parts = Path(relative).parts
        if any(part in ("..", ".") for part in parts):
            raise ValueError("Account path escapes the portable root")
        path = self.root
        for part in parts:
            path = path / part
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise RecoveryRequired("Linked account/private directories are not accepted")
        if not path.resolve().is_relative_to(self.root):
            raise RecoveryRequired("Account path escapes the portable root")
        return path

    @contextmanager
    def _lock(self):
        with self._thread_lock:
            base = self._safe("Private/Accounts")
            base.mkdir(parents=True, exist_ok=True)
            path = self._safe("Private/Accounts/registry.lock")
            with path.open("a+b") as handle:
                if path.stat().st_size == 0:
                    handle.write(b"0"); handle.flush()
                deadline = time.monotonic() + 5
                while True:
                    try:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except (OSError, BlockingIOError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Local account registry is busy") from None
                        time.sleep(.05)
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt": msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _atomic(self, path, value):
        path = self._safe(path.relative_to(self.root).as_posix())
        blob = _json(value)
        limit = _MAX_REGISTRY + 4096 if path.name == 'registry-recovery.json' else _MAX_REGISTRY
        if len(blob) > limit:
            raise ValueError("Account registry exceeds its bounded size")
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(blob); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try: os.fsync(directory)
                finally: os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def private_inventory(self):
        """Read-only full content digest for explicitly reviewed legacy migration."""
        from profile_migration import legacy_inventory, _scopes
        try:
            legacy = legacy_inventory(self.root)
        except (OSError, ValueError, RuntimeError) as exc:
            raise RecoveryRequired('Legacy private inventory could not be verified: ' + str(exc)) from None
        files = [{"path": row['source'], "bytes": row['bytes'], "sha256": row['sha256']} for row in legacy['files']]
        scopes = (*_scopes(), 'Agent/.runtime', *_PROFILE_ROOTS)
        for relative in _PROFILE_ROOTS:
            base = self._safe(relative)
            if not base.exists():
                continue
            if not base.is_dir():
                raise RecoveryRequired("Private-data root is not a directory")
            for folder, dirs, names in os.walk(base, followlinks=False):
                for name in dirs:
                    self._safe((Path(folder) / name).relative_to(self.root).as_posix())
                for name in sorted(names):
                    relative_file = (Path(folder) / name).relative_to(self.root).as_posix()
                    if relative_file == "Private/Accounts/registry.lock":
                        continue
                    path = self._safe(relative_file)
                    before = path.stat()
                    if not path.is_file() or before.st_nlink != 1:
                        raise RecoveryRequired("Unsupported private-data entry")
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024*1024), b""):
                            digest.update(chunk)
                    after = path.stat()
                    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                        raise RecoveryRequired("Private data changed during migration inventory")
                    files.append({"path": relative_file, "bytes": after.st_size, "sha256": digest.hexdigest()})
                    if len(files) > 100000:
                        raise RecoveryRequired("Private-data inventory exceeds the review limit")
        files.sort(key=lambda item: item["path"])
        return {"roots": list(scopes), "files": files, "bytes": sum(row["bytes"] for row in files),
                "digest": hashlib.sha256(_json(files)).hexdigest()}

    def _read(self, *, allow_reset=False, _document=None):
        try:
            if not allow_reset and self._safe("Private/Reset/transaction.json").exists():
                raise RecoveryRequired("An interrupted profile reset requires explicit authenticated recovery")
            path = self._safe("Private/Accounts/registry.json")
            marker = self._safe("Private/Accounts/initialized.json")
            if _document is None:
                if not path.is_file() or not marker.is_file():
                    raise RecoveryRequired("Account registry or initialization marker is missing; recover the existing installation")
                if path.stat().st_size > _MAX_REGISTRY or marker.stat().st_size > 4096:
                    raise RecoveryRequired("Account registry exceeds its size limit")
                data = json.loads(path.read_text(encoding="utf-8"))
                saved_marker = json.loads(marker.read_text(encoding="utf-8"))
            else:
                data = _document
                if len(_json(data)) > _MAX_REGISTRY: raise RecoveryRequired('Recovery registry exceeds its size limit')
                saved_marker = {'version':1,'instance_id':data.get('instance_id')}
            if data.get("version") != 1 or saved_marker != {"version": 1, "instance_id": data.get("instance_id")}:
                raise RecoveryRequired("Account registry identity or version is invalid")
            _uid(data["instance_id"])
            if type(data.get("revision")) is not int or data["revision"] < 1:
                raise RecoveryRequired("Account registry revision is invalid")
            slots = data.get("slots")
            if not isinstance(slots, dict) or not 2 <= len(slots) <= _MAX_USERS:
                raise RecoveryRequired("Account registry users are invalid")
            names = set(); guests = 0; admins = 0
            for uid, slot in slots.items():
                _uid(uid)
                if not isinstance(slot, dict) or slot.get("user_id") != uid:
                    raise RecoveryRequired("Account user identity is invalid")
                name = _name(slot["username"]).casefold()
                if name in names: raise RecoveryRequired("Duplicate account name")
                names.add(name)
                if slot["role"] not in ROLES or type(slot["epoch"]) is not int or slot["epoch"] < 1:
                    raise RecoveryRequired("Account role or generation is invalid")
                if any(type(slot[key]) is not bool for key in ("pending", "temporary_password")):
                    raise RecoveryRequired("Account enrollment state is invalid")
                _decode(slot["credential_mac"], 32)
                if slot["role"] == "guest":
                    guests += 1
                    if name != "guest" or slot["pending"] or slot["temporary_password"] or "password" in slot or "master_access" in slot:
                        raise RecoveryRequired("Shared Guest record is invalid")
                    _decode(slot["public_dek"], 32)
                elif name == "guest" or "public_dek" in slot:
                    raise RecoveryRequired("Guest name/key is reserved")
                elif slot["pending"]:
                    if slot["role"] != "user" or "password" in slot or "master_access" in slot:
                        raise RecoveryRequired("Pending user has unexpected credentials")
                else:
                    password = slot["password"]
                    if password.get("kdf") != {"name": "scrypt", "n": _KDF_N, "r": 8, "p": 1, "length": 32}:
                        raise RecoveryRequired("Unsupported account password KDF")
                    _decode(password["salt"], 16); _decode(password["verifier"], 32)
                    if slot["role"] == "admin":
                        admins += 1
                        if "master_access" not in slot: raise RecoveryRequired("Admin key wrapping is missing")
                    elif "master_access" in slot:
                        raise RecoveryRequired("Non-admin has unexpected master-key access")
            if guests != 1 or admins < 1 or not isinstance(data.get("registry"), dict):
                raise RecoveryRequired("Account registry has no valid Guest/admin structure")
            return data
        except RecoveryRequired:
            raise
        except Exception:
            raise RecoveryRequired("Account registry is corrupt; recover it from a verified backup") from None

    def _read_recovery(self, *, eligible=False):
        try:
            path = self._safe('Private/Accounts/registry-recovery.json')
            if path.stat().st_size > _MAX_REGISTRY+4096: raise ValueError('oversized')
            packet = json.loads(path.read_text(encoding='utf-8'))
            if set(packet) != {'version','instance_id','sha256','registry'} or packet['version'] != 1:
                raise ValueError('invalid envelope')
            data = self._read(_document=packet['registry'])
            expected = hashlib.sha256(_json(data)).hexdigest()
            if packet['instance_id'] != data['instance_id'] or not hmac.compare_digest(packet['sha256'],expected):
                raise ValueError('checksum mismatch')
            if eligible and self.write_pending_path.exists():
                path = self._safe('Private/Accounts/registry-write-pending.json')
                if path.stat().st_size > 16384: raise ValueError('oversized pending update')
                pending = json.loads(path.read_text(encoding='utf-8'))
                if pending.get('version') != 1 or pending.get('instance_id') != data['instance_id'] or pending.get('new_sha256') != expected:
                    raise ValueError('recovery copy predates an interrupted credential update')
            return packet
        except Exception as exc:
            raise RecoveryRequired('Current encrypted registry recovery copy is unavailable: ' + str(exc)) from None

    def _recovery_current(self, data):
        try:
            packet = self._read_recovery()
            return packet['sha256'] == hashlib.sha256(_json(data)).hexdigest() and not self.write_pending_path.exists()
        except (OSError, ValueError, RuntimeError): return False

    def _sync_recovery(self, data):
        packet = {'version':1,'instance_id':data['instance_id'],
                  'sha256':hashlib.sha256(_json(data)).hexdigest(),'registry':data}
        self._atomic(self.recovery_path,packet)
        if self._read_recovery()['sha256'] != packet['sha256']:
            raise RecoveryRequired('Current registry recovery copy did not verify')
        self.write_pending_path.unlink(missing_ok=True)
        self.recovery_warning = ''

    def _commit_registry(self, data):
        """Commit primary first; a mirror fault must not misreport password rollback."""
        expected = hashlib.sha256(_json(data)).hexdigest()
        self._atomic(self.write_pending_path,{'version':1,'instance_id':data['instance_id'],'new_sha256':expected})
        try:
            self._atomic(self.registry_path,data)
        except OSError:
            # os.replace may have committed before directory fsync reported a
            # failure. Preserve the new authentication if readback proves it.
            try: changed = self.registry_path.read_bytes() == _json(data)
            except OSError: changed = False
            if not changed: raise
        if self.registry_path.read_bytes() != _json(data):
            raise RecoveryRequired('Primary registry update did not verify')
        try:
            self._sync_recovery(data)
        except (OSError, ValueError, RuntimeError):
            self.recovery_warning = ('Credentials were updated, but the current encrypted recovery copy could not be verified. '
                'Keep the drive connected and sign in as an administrator to repair it. No older recovery copy will be used automatically.')
        return self.recovery_warning

    def recover_registry(self, username, password):
        """Explicit admin-password recovery; never silently fall back or reset keys."""
        username = _name(username)
        with self._lock():
            packet = self._read_recovery(eligible=True); data = packet['registry']
            slot = next((item for item in data['slots'].values() if item['username'].casefold()==username.casefold()),None)
            if slot is None or slot['role'] != 'admin': raise AuthorizationError('Recovery requires an administrator from the current encrypted copy')
            dek = self._unlock(data,slot,password)
            master = _open(dek,slot['master_access'],_slot_aad(data['instance_id'],slot,'master'))
            self._private(data,master)
            # A different, cryptographically valid primary is newer authority;
            # recovery must not roll it back to an older password envelope.
            if self.registry_path.exists():
                try:
                    if self.registry_path.stat().st_size > _MAX_REGISTRY: raise ValueError('oversized')
                    primary = self._read(_document=json.loads(self.registry_path.read_text(encoding='utf-8')))
                except (OSError, ValueError, RuntimeError): primary = None
                if primary is not None:
                    if primary['instance_id'] != data['instance_id']:
                        raise RecoveryRequired('A different registry instance exists; explicit reset recovery is required')
                    try: self._private(primary,master)
                    except RecoveryRequired: pass
                    else:
                        if _json(primary) != _json(data):
                            raise RecoveryRequired('The primary registry is newer and valid; sign in there to repair its current mirror')
            if self.marker_path.exists():
                try:
                    if self.marker_path.stat().st_size > 16384: raise ValueError('oversized marker')
                    marker = json.loads(self.marker_path.read_text(encoding='utf-8'))
                except (OSError, ValueError): marker = None
                if isinstance(marker,dict) and marker.get('instance_id') not in (None,data['instance_id']):
                    raise RecoveryRequired('Registry marker belongs to another installation instance')
            self._atomic(self.registry_path,data)
            self._atomic(self.marker_path,{'version':1,'instance_id':data['instance_id']})
            self._private(self._read(),master)
            self._sync_recovery(data)
            self.logout()
            return {'recovered':True,'login_required':True,'instance_id':data['instance_id']}

    def status(self):
        try:
            if self._safe("Private/Reset/transaction.json").exists():
                raise RecoveryRequired("An interrupted profile reset requires explicit authenticated recovery")
            if not self.registry_path.exists() and not self.marker_path.exists():
                if any(self._safe(path).exists() for path in _LIFECYCLE_EVIDENCE):
                    raise RecoveryRequired('Profile lifecycle evidence exists without its registry; recover the existing installation')
                if not self.private_inventory()['files']:
                    return {"state": "fresh", "reason": "No private data or initialized account registry", "users": []}
                return {"state": "recovery_required", "reason": "Private data exists without an account registry; explicit reviewed migration or recovery is required", "users": []}
            with self._lock(): data = self._read()
            warning = '' if self._recovery_current(data) else 'Current encrypted registry recovery needs administrator verification.'
            return {"state": "locked", "reason": "Login required; no session is persisted", "recovery_warning":warning,
                    "users": [_public(slot) for slot in data["slots"].values()]}
        except (OSError, ValueError, RuntimeError) as exc:
            return {"state": "recovery_required", "reason": str(exc), "users": []}

    def _new_slot(self, instance, username, role, dek, master, password=None, *,
                  uid=None, epoch=1, temporary=False):
        slot = {"user_id": uid or uuid.uuid4().hex, "username": _name(username), "role": role,
                "epoch": epoch, "pending": password is None and role != "guest",
                "temporary_password": bool(temporary), "created_at": self.clock()}
        if role == "guest":
            slot["public_dek"] = _encode(dek)
        elif password is not None:
            password = _password(password, temporary)
            salt = secrets.token_bytes(16); key = _kdf(password, salt)
            aad = _slot_aad(instance, slot, "password")
            slot["password"] = {"kdf": {"name": "scrypt", "n": _KDF_N, "r": 8, "p": 1, "length": 32},
                                "salt": _encode(salt), "verifier": _encode(hmac.digest(key, aad, "sha256")),
                                "wrapped_dek": _seal(key, dek, aad)}
            if role == "admin":
                slot["master_access"] = _seal(dek, master, _slot_aad(instance, slot, "master"))
        return slot

    def _save(self, data, private, master):
        for uid, slot in data["slots"].items():
            dek = _open(master, private["users"][uid]["wrapped_dek"],
                        b"PortalAI-profile-key:" + data["instance_id"].encode() + b":" + uid.encode())
            slot["credential_mac"] = _encode(_credential_mac(slot, dek))
            private["users"][uid]["identity_hash"] = _identity_fingerprint(slot)
        private["revision"] = data["revision"]
        data["registry"] = _seal(master, _json(private), b"PortalAI-local-private-v1:" + data["instance_id"].encode())
        self._commit_registry(data)

    def _private(self, data, master):
        try:
            private = json.loads(_open(master, data["registry"], b"PortalAI-local-private-v1:" + data["instance_id"].encode()))
            if private["revision"] != data["revision"] or set(private["users"]) != set(data["slots"]):
                raise ValueError()
            if data["slots"][private["owner_id"]]["role"] != "admin": raise ValueError()
            for uid, slot in data["slots"].items():
                if not hmac.compare_digest(private["users"][uid]["identity_hash"], _identity_fingerprint(slot)): raise ValueError()
                dek = _open(master, private["users"][uid]["wrapped_dek"],
                            b"PortalAI-profile-key:" + data["instance_id"].encode() + b":" + uid.encode())
                if not hmac.compare_digest(_credential_mac(slot, dek), _decode(slot["credential_mac"], 32)): raise ValueError()
            return private
        except Exception:
            raise RecoveryRequired("Encrypted account registry authentication failed; recover a verified copy") from None

    def _initialize(self, owner, password, pending_users, temporary_password, inventory_digest):
        owner = _name(owner); _password(password, temporary_password)
        pending_users = tuple(_name(name) for name in pending_users)
        names = [owner.casefold(), "guest", *(name.casefold() for name in pending_users)]
        if len(set(names)) != len(names) or len(names) > _MAX_USERS:
            raise ValueError("Account names must be unique; Guest is reserved")
        with self._lock():
            if self._safe("Private/Reset/transaction.json").exists():
                raise RecoveryRequired("A pending profile reset cannot be replaced by initialization")
            if self.registry_path.exists() or self.marker_path.exists() or self.recovery_path.exists() or self.write_pending_path.exists():
                raise RecoveryRequired("An account registry was already initialized; initialization cannot reset it")
            if any(self._safe(path).exists() for path in _LIFECYCLE_EVIDENCE):
                raise RecoveryRequired('Profile lifecycle evidence requires recovery, not account initialization')
            inventory = self.private_inventory()
            if inventory_digest is None and inventory["files"]:
                raise RecoveryRequired("Bootstrap is allowed only on a truly fresh installation")
            if inventory_digest is not None and (not isinstance(inventory_digest, str) or
                    not hmac.compare_digest(inventory["digest"], inventory_digest)):
                raise RecoveryRequired("Reviewed private-data inventory changed; initialization was not performed")
            instance = uuid.uuid4().hex; master = secrets.token_bytes(32)
            data = {"version": 1, "instance_id": instance, "revision": 1, "slots": {}}
            private = {"revision": 1, "users": {}}
            for name, role, secret, temporary in ((owner, "admin", password, temporary_password), ("Guest", "guest", None, False),
                                                  *((name, "user", None, False) for name in pending_users)):
                dek = secrets.token_bytes(32)
                slot = self._new_slot(instance, name, role, dek, master, secret, temporary=temporary)
                uid = slot["user_id"]; data["slots"][uid] = slot
                private["users"][uid] = {"wrapped_dek": _seal(master, dek, b"PortalAI-profile-key:" + instance.encode() + b":" + uid.encode())}
                if role == "admin": private["owner_id"] = uid
            # Marker first: interruption cannot masquerade as a fresh installation.
            self._atomic(self.marker_path, {"version": 1, "instance_id": instance})
            self._save(data, private, master)
        return self.login(owner, password)

    def bootstrap(self, owner, password, *, pending_users=(), temporary_password=False):
        return self._initialize(owner, password, pending_users, temporary_password, None)

    def initialize_existing(self, owner, password, expected_inventory_digest, *, pending_users=(), temporary_password=False):
        """Explicit migration entry point; never offered by a missing-registry login UI."""
        return self._initialize(owner, password, pending_users, temporary_password, expected_inventory_digest)

    def _unlock(self, data, slot, password):
        try:
            if slot["pending"] or slot["role"] == "guest" or not isinstance(password, str) or len(password) > 1024:
                raise ValueError()
            saved = slot["password"]; key = _kdf(password, _decode(saved["salt"], 16))
            aad = _slot_aad(data["instance_id"], slot, "password")
            if not hmac.compare_digest(hmac.digest(key, aad, "sha256"), _decode(saved["verifier"], 32)):
                raise ValueError()
            dek = _open(key, saved["wrapped_dek"], aad)
            if len(dek) != 32: raise ValueError()
            if not hmac.compare_digest(_credential_mac(slot, dek), _decode(slot["credential_mac"], 32)): raise ValueError()
            return dek
        except Exception:
            raise AuthenticationError("Login failed or this user still requires administrator enrollment") from None

    def _session(self, slot, dek, master=None, parent=None):
        session = Session(self, slot, dek, master, parent)
        self._sessions[session._token] = session
        return session

    def _login(self, username, password, *, allow_reset=False):
        """Internal reset recovery may authenticate while ordinary access is locked."""
        username = _name(username)
        with self._lock():
            data = self._read(allow_reset=allow_reset)
            slot = next((slot for slot in data["slots"].values() if slot["username"].casefold() == username.casefold()), None)
            if slot is None: raise AuthenticationError("Login failed or this user still requires administrator enrollment")
            dek = self._unlock(data, slot, password); master = None
            self.recovery_warning = ''
            if slot["role"] == "admin":
                try: master = _open(dek, slot["master_access"], _slot_aad(data["instance_id"], slot, "master"))
                except Exception: raise RecoveryRequired("Admin key could not unlock the registry") from None
                self._private(data, master)
                if not allow_reset and not self._recovery_current(data):
                    try: self._sync_recovery(data)
                    except (OSError, ValueError, RuntimeError):
                        self.recovery_warning = 'Administrator authentication succeeded, but the current recovery copy still needs repair before drive removal.'
            elif not self._recovery_current(data):
                self.recovery_warning = 'Your own profile key is valid; administrator verification is needed to repair the current registry recovery copy.'
            else:
                self.recovery_warning = ''
            return self._session(slot, dek, master)

    def login(self, username, password):
        return self._login(username, password)

    def login_guest(self):
        with self._lock():
            data = self._read()
            slot = next(slot for slot in data["slots"].values() if slot["role"] == "guest")
            dek = _decode(slot["public_dek"], 32)
            if not hmac.compare_digest(_credential_mac(slot, dek), _decode(slot["credential_mac"], 32)):
                raise RecoveryRequired("Guest record authentication failed")
            return self._session(slot, dek)

    def _validate(self, session, data, *, admin=False):
        if not isinstance(session, Session) or session._store() is not self or self._sessions.get(session._token) is not session:
            raise AuthenticationError("Session is locked or belongs to another process/store")
        slot = data["slots"].get(session.user_id)
        if not session._active or (session._expires is not None and self.clock() >= session._expires) or slot is None or not hmac.compare_digest(session._fingerprint, _fingerprint(slot)):
            self.logout(session)
            raise AuthenticationError("Session expired or credentials changed; log in again")
        if session._parent is not None: self._validate(session._parent, data, admin=True)
        if admin and (session.role != "admin" or session._master is None or session._parent is not None):
            raise AuthorizationError("An authenticated administrator is required")
        if session._master is not None: self._private(data, bytes(session._master))
        return slot

    def validate_session(self, session):
        with self._lock():
            self._validate(session, self._read())
            return dict(session._user)

    def data_key(self, session):
        with self._lock():
            self._validate(session, self._read())
            return bytes(session._dek)

    def logout(self, session=None):
        with self._thread_lock:
            targets = list(self._sessions.values()) if session is None else [s for s in self._sessions.values() if s is session or s._parent is session]
            for target in targets:
                target._active = False
                target._dek[:] = b"\0" * len(target._dek)
                if target._master is not None: target._master[:] = b"\0" * len(target._master)
                self._sessions.pop(target._token, None)
            self._confirmations = {token: row for token, row in self._confirmations.items()
                                   if row["session"] in self._sessions}

    def _admin(self, session, data, password):
        slot = self._validate(session, data, admin=True)
        dek = self._unlock(data, slot, password)
        if not hmac.compare_digest(dek, bytes(session._dek)):
            raise AuthenticationError("Administrator reauthentication failed")
        return self._private(data, bytes(session._master))

    def list_users(self, admin):
        with self._lock():
            data = self._read(); self._validate(admin, data, admin=True)
            return [_public(slot) for slot in data["slots"].values()]

    def profile_session(self, admin, target_user_id):
        _uid(target_user_id)
        with self._lock():
            data = self._read(); self._validate(admin, data, admin=True)
            slot = data["slots"].get(target_user_id)
            if slot is None: raise ValueError("Unknown user")
            private = self._private(data, bytes(admin._master))
            dek = _open(bytes(admin._master), private["users"][target_user_id]["wrapped_dek"],
                        b"PortalAI-profile-key:" + data["instance_id"].encode() + b":" + target_user_id.encode())
            return self._session(slot, dek, parent=admin)

    def create_user(self, admin, username, password=None, *, role="user", admin_password):
        username = _name(username)
        if role not in {"user", "admin"} or username.casefold() == "guest":
            raise ValueError("New users must be user/admin; Guest is reserved")
        if password is not None: _password(password)
        if role == "admin" and password is None: raise ValueError("New administrators need a password")
        with self._lock():
            data = self._read(); private = self._admin(admin, data, admin_password)
            if len(data["slots"]) >= _MAX_USERS or any(row["username"].casefold() == username.casefold() for row in data["slots"].values()):
                raise ValueError("Account limit reached or username already exists")
            master = bytes(admin._master); dek = secrets.token_bytes(32)
            slot = self._new_slot(data["instance_id"], username, role, dek, master, password)
            uid = slot["user_id"]; data["slots"][uid] = slot
            private["users"][uid] = {"wrapped_dek": _seal(master, dek, b"PortalAI-profile-key:" + data["instance_id"].encode() + b":" + uid.encode())}
            data["revision"] += 1; self._save(data, private, master)
            return self._result(slot)

    def _result(self, slot):
        result = _public(slot)
        if self.recovery_warning: result['recovery_warning'] = self.recovery_warning
        return result

    def _replace_password(self, data, private, slot, dek, master, password, role=None, *, temporary_password=False):
        updated = self._new_slot(data["instance_id"], slot["username"], role or slot["role"], dek, master,
                                 password, uid=slot["user_id"], epoch=slot["epoch"] + 1,
                                 temporary=temporary_password)
        updated["created_at"] = slot["created_at"]
        data["slots"][slot["user_id"]] = updated
        data["revision"] += 1; self._save(data, private, master)
        for session in list(self._sessions.values()):
            if session.user_id == slot["user_id"]: self.logout(session)
        return updated

    def promote(self, admin, target_user_id, *, admin_password, target_password):
        _uid(target_user_id)
        with self._lock():
            data = self._read(); private = self._admin(admin, data, admin_password)
            slot = data["slots"].get(target_user_id)
            if slot is None or slot["role"] != "user" or slot["pending"]:
                raise ValueError("Only an enrolled standard user can be promoted")
            dek = self._unlock(data, slot, target_password)
            updated = self._replace_password(data, private, slot, dek, bytes(admin._master), target_password, "admin",
                                             temporary_password=slot["temporary_password"])
            return self._result(updated)

    def change_password(self, session, old_password, new_password):
        _password(new_password)
        with self._lock():
            data = self._read(); slot = self._validate(session, data)
            if slot["role"] == "guest" or session._parent is not None:
                raise AuthorizationError("Guest/delegated sessions cannot change a password")
            dek = self._unlock(data, slot, old_password)
            if not hmac.compare_digest(dek, bytes(session._dek)): raise AuthenticationError("Password verification failed")
            # A user can authenticate a new credential envelope with the same DEK.
            # Identity/role/enrollment remain authenticated by the admin-encrypted
            # registry; the admin also checks this MAC using its wrapped DEK.
            if session._master is None:
                if not self._recovery_current(data):
                    raise RecoveryRequired('An administrator must repair the current registry recovery copy before another password change')
                updated = self._new_slot(data["instance_id"], slot["username"], slot["role"], dek, None,
                                         new_password, uid=slot["user_id"], epoch=slot["epoch"] + 1)
                updated["created_at"] = slot["created_at"]
                updated["credential_mac"] = _encode(_credential_mac(updated, dek))
                data["slots"][slot["user_id"]] = updated
                self._commit_registry(data)
                for old in list(self._sessions.values()):
                    if old.user_id == slot["user_id"]: self.logout(old)
                return self._session(updated, dek)
            master = bytes(session._master); private = self._private(data, master)
            updated = self._replace_password(data, private, slot, dek, master, new_password)
            return self._session(updated, dek, master)

    def request_confirmation(self, admin, action, target_user_id=None, *, admin_password, ttl_seconds=120):
        if action not in {"password-reset", "start-fresh"} or not 1 <= ttl_seconds <= 300:
            raise ValueError("Invalid confirmation action or lifetime")
        if target_user_id is not None: _uid(target_user_id)
        with self._lock():
            data = self._read(); self._admin(admin, data, admin_password)
            if action == "password-reset" and (target_user_id not in data["slots"] or data["slots"][target_user_id]["role"] == "guest"):
                raise ValueError("Password reset needs an existing non-Guest user")
            token = secrets.token_urlsafe(32)
            self._confirmations[hashlib.sha256(token.encode()).hexdigest()] = {
                "session": admin._token, "action": action, "target_user_id": target_user_id,
                "expires": self.clock() + ttl_seconds, "revision": data["revision"],
                "target_fingerprint": _fingerprint(data["slots"][target_user_id]) if target_user_id else None}
            return token

    def _consume(self, admin, data, token, action, target_user_id):
        self._validate(admin, data, admin=True)
        if not isinstance(token, str) or len(token) > 200: raise AuthorizationError("Confirmation is invalid")
        row = self._confirmations.pop(hashlib.sha256(token.encode()).hexdigest(), None)
        target_fingerprint = _fingerprint(data["slots"][target_user_id]) if target_user_id in data["slots"] else None
        if not row or row["session"] != admin._token or row["action"] != action or row["target_user_id"] != target_user_id or row["revision"] != data["revision"] or row["target_fingerprint"] != target_fingerprint or self.clock() >= row["expires"]:
            raise AuthorizationError("Confirmation is expired, already used or no longer matches this action")
        return {"action": action, "target_user_id": target_user_id, "admin_user_id": admin.user_id,
                "authorized_at": self.clock(), "performed": False}

    def consume_confirmation(self, admin, token, action, target_user_id=None):
        """Authorize only; no destructive data operation is implemented here."""
        with self._lock(): return self._consume(admin, self._read(), token, action, target_user_id)

    def reset_password(self, admin, target_user_id, new_password, *, admin_password, confirmation_token,
                       temporary_password=False):
        if type(temporary_password) is not bool:
            raise ValueError("Temporary password selection must be a boolean")
        _uid(target_user_id); _password(new_password, temporary=temporary_password)
        with self._lock():
            data = self._read(); private = self._admin(admin, data, admin_password)
            slot = data["slots"].get(target_user_id)
            if slot is None or slot["role"] == "guest": raise ValueError("Cannot reset this user")
            self._consume(admin, data, confirmation_token, "password-reset", target_user_id)
            master = bytes(admin._master)
            dek = _open(master, private["users"][target_user_id]["wrapped_dek"],
                        b"PortalAI-profile-key:" + data["instance_id"].encode() + b":" + target_user_id.encode())
            return self._result(self._replace_password(data, private, slot, dek, master, new_password,
                                                       temporary_password=temporary_password))
