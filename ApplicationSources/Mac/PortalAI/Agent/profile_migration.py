"""Reviewed, verified migration of legacy private files into one owner profile.

No migration runs on import. Callers must stop all GUI/tool/mission writers and
approve the exact inventory digest. Every original remains until its encrypted
recovery copy has been decrypted and checked byte-for-byte.
"""
from __future__ import annotations

import hashlib
import json
import os
from portable_fs import Path, walk
import re
import shutil
import uuid

from profile_paths import PRIVATE_PREFIXES, _contained, _relative
from profile_workspace import ProfileWorkspace, digest
from runtime_policy import atomic_json, require_space

HISTORICAL_ROOTS = ('Backups', 'Maintenance/Reports', 'Maintenance/Archive', 'Maintenance/Endurance')
HISTORICAL_FILES = tuple('ControlCenter/' + name for name in
                        ('PortableAI_Crash.log', 'PortableAI_Freeze.log', 'PortableAI_Launcher.log')) + (
    'Maintenance/Repair/Repair_MusicUnderstanding_v15_40b.log',
    'Maintenance/Repair/Repair_MusicUnderstanding_v15_40c.log',
    # Legacy host-gateway secrets are recovery data. Its source/config remain
    # shared, and are never run or reactivated by account migration.
    'Sandbox/Security/agent_token.txt',
    'Sandbox/Security/OPEN_GUI_CONNECTION.txt',
    'Sandbox/Security/sandbox_runtime.json',
    # Exact diagnostic files only; adjacent installers/model caches stay shared.
    'Cache/Bootstrap/python-3.12.10-install.log',
    'Cache/Bootstrap/python-3.12.10-install_000_exe_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_001_dev_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_002_test_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_003_doc_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_004_tcltk_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_005_pip_JustForMe.log',
    'Installer/Install_MusicUnderstanding_v15_40d.log',
    'Installer/Install_OpenWebUI_Remote_v15_42.log',
    'Installer/Installers/logs/opengui_dist_win_v15_38.log',
    'Installer/Installers/logs/opengui_pnpm_install_v15_38.log',
    'OpenWebUI/Installer/Install_OpenWebUI_Remote_v15_42b.log',
    'SecureAgent/Updater/SecureAgent_Parity_v15_43.log',
    'Voice/Qwen3-TTS/hf_cache/xet/logs/xet_20260913T125417684-0400_4652.log',
)
RUNTIME_PUBLIC = frozenset(('qwen_last_stop.json', 'qwen_handoff_generation.json',
    'qwen_launch_command.txt', 'qwen_launch_executable.txt', 'hardware_launch_plan.json',
    'component_runtime_locks.json', 'control_center_theme.json', 'comfy_vram_profile.txt'))
PLAN_PATH = 'Data/ProfileMigration/legacy-plan.json'


def _source_target(relative):
    """Validate the exact legacy scope before any copy or removal."""
    if not isinstance(relative, str) or _relative(relative) != relative:
        raise ValueError('Noncanonical migration source')
    if relative in HISTORICAL_FILES or any(
            relative == scope or relative.startswith(scope + '/') for scope in HISTORICAL_ROOTS):
        return 'Data/LegacyRecovery/' + relative
    if any(relative == scope or relative.startswith(scope + '/') for scope in PRIVATE_PREFIXES):
        return relative
    if relative.startswith('Agent/.runtime/'):
        tail = relative[len('Agent/.runtime/'):]
        if '/' not in tail and (tail in RUNTIME_PUBLIC or tail.endswith('.lock')):
            raise ValueError('Shared runtime state is outside the migration scope')
        return 'Data/LegacyRecovery/' + relative
    raise ValueError('Source is outside the declared private migration scope')


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


def _scopes():
    values = sorted(set(PRIVATE_PREFIXES) | set(HISTORICAL_ROOTS) | set(HISTORICAL_FILES))
    return [value for value in values if not any(value.startswith(other + '/') for other in values if other != value)]


def legacy_inventory(root):
    """Return paths/hashes only. Do not write this potentially private list to logs."""
    root = Path(root).resolve(); files = {}
    def add(path, relative, target=None):
        _contained(root, path)
        stat = path.stat()
        if not path.is_file() or stat.st_nlink != 1:
            raise RuntimeError('Linked/nonregular legacy files require review: ' + relative)
        sha = digest(path); after = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Legacy data changed during inventory')
        if target is None:
            target = _source_target(relative)
        row = {'source': relative, 'target': target, 'bytes': stat.st_size, 'sha256': sha}
        if relative in files and files[relative] != row:
            raise ValueError('Overlapping migration scopes')
        files[relative] = row
    for scope in _scopes():
        path = root / scope; _contained(root, path)
        if not path.exists(): continue
        if scope in HISTORICAL_FILES and not path.is_file():
            raise RuntimeError('Historical file is not regular and requires review: ' + scope)
        if path.is_file(): add(path, scope); continue
        for directory, names, names_files in walk(path, followlinks=False):
            for name in names: _contained(root, Path(directory) / name)
            for name in names_files:
                source = Path(directory) / name
                add(source, source.relative_to(root).as_posix())
    # Mixed runtime metadata stays shared, but request/log/trace leftovers are
    # owner data. Old installer evidence is archived as data, never executed.
    runtime = root / 'Agent/.runtime'; _contained(root, runtime)
    if runtime.exists():
        for directory, names, names_files in walk(runtime, followlinks=False):
            for name in names: _contained(root, Path(directory) / name)
            for name in names_files:
                source = Path(directory) / name
                relative = source.relative_to(root).as_posix()
                if relative in files: continue
                if source.parent == runtime and (name in RUNTIME_PUBLIC or name.endswith('.lock')): continue
                add(source, relative, 'Data/LegacyRecovery/' + relative)
    rows = sorted(files.values(), key=lambda row: row['source'])
    targets = [row['target'].casefold() for row in rows]
    if len(set(targets)) != len(targets): raise ValueError('Migration destinations collide')
    return {'version': 1, 'files': rows, 'bytes': sum(row['bytes'] for row in rows),
            'digest': hashlib.sha256(_encoded(rows)).hexdigest()}


def _windows_clear_readonly_empty_directory(root, directory, before):
    """Clear only READONLY on the same empty, contained Windows directory."""
    if os.name != 'nt': return False
    import ctypes
    from ctypes import wintypes
    import stat
    def checked_attributes():
        _contained(root, directory)
        current = directory.stat(follow_symlinks=False)
        attributes = getattr(current, 'st_file_attributes', 0)
        if ((current.st_dev, current.st_ino) != (before.st_dev, before.st_ino) or
                not stat.S_ISDIR(current.st_mode) or attributes & 0x400):
            raise RuntimeError('Private directory identity changed; recovery remains pending')
        if next(directory.iterdir(), None) is not None:
            raise RuntimeError('A writer created data in a read-only directory; recovery remains pending')
        return attributes
    attributes = checked_attributes()
    if not attributes & 0x1: return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetFileAttributesW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    kernel.SetFileAttributesW.restype = wintypes.BOOL
    # Recheck immediately before changing only this directory's READONLY bit.
    attributes = checked_attributes()
    if not attributes & 0x1: return False
    if not kernel.SetFileAttributesW(str(directory), attributes & ~0x1):
        raise ctypes.WinError(ctypes.get_last_error())
    if checked_attributes() & 0x1:
        raise RuntimeError('Private directory remains read-only; recovery remains pending')
    return True


def _remove_empty_legacy_directories(root):
    """Remove only empty descendants of declared directory scopes.

    The caller has verified every file's encrypted recovery copy and stopped all
    writers. Keep the declared roots, mixed runtime metadata and historical-file
    parents. rmdir can never remove a new file; a new writer leaves recovery
    pending. Missing directories are harmless after an interrupted cleanup.
    """
    root = Path(root).resolve()
    roots = {root / scope for scope in PRIVATE_PREFIXES + HISTORICAL_ROOTS}
    candidates = set()
    def walk_error(error):
        raise error
    # Validate the complete empty tree before removing any folder names. Check
    # children before descending so links/junctions are never followed.
    for scope in sorted(roots):
        _contained(root, scope)
        if not scope.exists(): continue
        if not scope.is_dir():
            raise RuntimeError('Private directory scope changed during commit; recovery remains pending')
        for directory, names, files in walk(scope, topdown=True, onerror=walk_error, followlinks=False):
            directory = Path(directory)
            _contained(root, directory)
            for name in names + files:
                _contained(root, directory / name)
            if files:
                raise RuntimeError('A writer created new shared private data during directory cleanup; recovery remains pending')
            if directory not in roots:
                candidates.add(directory)
    for directory in sorted(candidates, key=lambda path: (-len(path.parts), str(path))):
        _contained(root, directory)
        try:
            before = directory.stat(follow_symlinks=False)
            try:
                directory.rmdir()
            except PermissionError:
                if not _windows_clear_readonly_empty_directory(root, directory, before):
                    raise
                _contained(root, directory)
                directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError('Private directory cleanup could not verify an empty folder; recovery remains pending') from error


class LegacyMigration:
    seal_on_commit = True
    def __init__(self, root, session, *, before_remove=None):
        self.root = Path(root).resolve(); self.session = session
        self.before_remove = before_remove
        if session.role != 'admin': raise PermissionError('An administrator must own the legacy migration')
        self.store = ProfileWorkspace(self.root, session)
        self.journal = self.root / 'Private/migration-pending.json'
        self.complete = self.root / 'Private/migration-complete.json'
        _contained(self.root, self.journal); _contained(self.root, self.complete)

    def _plan_path(self, state):
        if self.seal_on_commit:
            if state.get('plan_path', PLAN_PATH) != PLAN_PATH:
                raise ValueError('Invalid migration recovery plan path')
            return PLAN_PATH
        path = state.get('plan_path', '')
        if not re.fullmatch(r'Data/ProfileMigration/harvest-[a-f0-9]{32}\.json', path):
            raise ValueError('Invalid diagnostic recovery plan path')
        return path

    def _validate_plan(self, plan, state):
        self.session.profile_key
        if state.get('user_id') != self.session.user_id or state.get('version') != 1:
            raise ValueError('Migration recovery identity mismatch')
        plan_path = self._plan_path(state)
        if not isinstance(plan, dict) or plan.get('version') != 1 or not isinstance(plan.get('files'), list):
            raise ValueError('Invalid migration plan')
        token = plan_path.removeprefix('Data/ProfileMigration/harvest-').removesuffix('.json')
        seen, targets = set(), set()
        for row in plan['files']:
            if not isinstance(row, dict): raise ValueError('Invalid migration file')
            source = row.get('source'); expected = _source_target(source)
            if not self.seal_on_commit: expected = 'Data/SessionRecovery/' + token + '/' + source
            if (row.get('target') != expected or source.casefold() in seen or expected.casefold() in targets or
                    expected == plan_path or type(row.get('bytes')) is not int or row['bytes'] < 0 or
                    not isinstance(row.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', row['sha256'])):
                raise ValueError('Invalid or duplicate migration entry')
            seen.add(source.casefold()); targets.add(expected.casefold())
            _contained(self.root, self.root/source)
            _contained(self.root, self.store.workspace/expected)
        if (plan['files'] != sorted(plan['files'], key=lambda row:row['source']) or
                plan.get('bytes') != sum(row['bytes'] for row in plan['files']) or
                plan.get('digest') != hashlib.sha256(_encoded(plan['files'])).hexdigest() or
                plan['digest'] != state.get('digest')):
            raise ValueError('Migration plan digest or totals mismatch')
        if any((target + '.portal-copy-part').casefold() in targets for target in targets):
            raise ValueError('Migration staging names collide with existing data')
        return plan_path

    def _check_survivors(self, plan):
        expected = {row['source']:row for row in plan['files']}
        for row in legacy_inventory(self.root)['files']:
            saved = expected.get(row['source'])
            if saved is None or (saved['bytes'], saved['sha256']) != (row['bytes'], row['sha256']):
                raise RuntimeError('New or changed shared private data requires review; originals preserved')

    def _copy_one(self, row):
        source = self.root/row['source']; target = self.store.workspace/row['target']
        temporary = target.with_name(target.name + '.portal-copy-part')
        for path in (source,target,temporary): _contained(self.root,path)
        if source.stat().st_nlink != 1 or digest(source) != row['sha256']:
            raise RuntimeError('Legacy source changed before copy')
        if target.exists():
            if target.stat().st_nlink != 1 or digest(target) != row['sha256']:
                raise RuntimeError('Existing destination differs; no file overwritten')
            if temporary.exists(): raise RuntimeError('Unexpected simultaneous copy and staging file')
            return
        if temporary.exists():
            # Only an exact prefix of this reviewed source may be an interrupted
            # staging copy. Never delete an unknown or edited staging file.
            if temporary.stat().st_nlink != 1 or temporary.stat().st_size > row['bytes']:
                raise RuntimeError('Unexpected migration staging file requires review')
            with source.open('rb') as src, temporary.open('rb') as part:
                while block := part.read(1024**2):
                    if src.read(len(block)) != block: raise RuntimeError('Changed migration staging file requires review')
            temporary.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, temporary.open('xb') as dst:
            shutil.copyfileobj(src,dst,1024**2); dst.flush(); os.fsync(dst.fileno())
        if digest(temporary) != row['sha256'] or digest(source) != row['sha256']:
            raise RuntimeError('Legacy copy failed verification')
        if target.exists(): raise RuntimeError('Another writer created a migration destination')
        # Writers have been stopped; the verified staging file is now published.
        temporary.rename(target)

    def run(self, expected_digest, *, writers_stopped=False):
        if writers_stopped is not True: raise RuntimeError('Verified writer shutdown is required for migration')
        self.session.profile_key  # Validate the live authenticated administrator.
        with self.store.transaction():
            if self.complete.exists(): raise RuntimeError('Legacy migration was already completed')
            if self.journal.exists(): raise RuntimeError('An interrupted migration requires explicit recovery')
            if self.store.inventory(): raise RuntimeError('Owner workspace must be empty before legacy import')
            plan = legacy_inventory(self.root)
            if not isinstance(expected_digest, str) or expected_digest != plan['digest']:
                raise RuntimeError('Reviewed migration inventory changed; no files moved')
            if (self.root/'Agent/hardware_profiles.json').exists():
                require_space(self.root, plan['bytes'] * 2 + 8*1024**2, for_outputs=True)
            state = {'version': 1, 'user_id': self.session.user_id, 'digest': plan['digest'], 'phase': 'copying'}
            self._validate_plan(plan,state)
            atomic_json(self.journal, state)
            if any(row['target'] == PLAN_PATH for row in plan['files']):
                raise RuntimeError('Reserved migration plan path is already occupied')
            atomic_json(self.store.workspace / PLAN_PATH, plan)
            for row in plan['files']: self._copy_one(row)
            snapshot = self.store.snapshot()
            self.store.verify(snapshot['generation'])
            state.update(phase='verified', generation=snapshot['generation'])
            atomic_json(self.journal, state)
            return self._commit(plan, state)

    def _commit(self, plan, state, *, seal_workspace=True):
        self._validate_plan(plan,state)
        manifest = self.store.verify(state['generation'])
        self._check_survivors(plan)
        rows = {row['path']: row for row in manifest['files']}
        # Validate ALL surviving sources before unlinking any. An interrupted
        # commit may already have removed some; the full encrypted snapshot stays.
        for row in plan['files']:
            saved = rows.get(row['target'])
            if saved is None or (saved['bytes'], saved['sha256']) != (row['bytes'], row['sha256']):
                raise RuntimeError('Migration file is absent from encrypted recovery')
            path = self.root / row['source']; _contained(self.root, path)
            if path.exists() and (path.stat().st_nlink != 1 or digest(path) != row['sha256']):
                raise RuntimeError('Legacy data changed; original file preserved')
        backup=getattr(self,'before_remove',None)
        if backup is not None:
            receipt=backup(plan,state)
            if not isinstance(receipt,dict) or receipt.get('verified') is not True:
                raise RuntimeError('External recovery did not verify; original files retained')
            self._check_survivors(plan)
        state['phase'] = 'committing'; atomic_json(self.journal, state)
        for row in plan['files']:
            path = self.root / row['source']; _contained(self.root, path)
            if not path.exists(): continue
            if path.stat().st_nlink != 1 or digest(path) != row['sha256']:
                raise RuntimeError('Legacy data changed during commit; original preserved')
            path.unlink()
        if legacy_inventory(self.root)['files']:
            raise RuntimeError('A writer created new shared private data during commit; recovery remains pending')
        _remove_empty_legacy_directories(self.root)
        if legacy_inventory(self.root)['files']:
            raise RuntimeError('A writer created new shared private data after directory cleanup; recovery remains pending')
        # Reuse the already verified complete generation, including the encrypted
        # migration plan. The seal recovery protocol never replaces a complete
        # snapshot with only the files left after interruption.
        if seal_workspace:
            atomic_json(self.store.base/'seal-pending.json', {'version':1,'user_id':self.session.user_id,
                                                            'generation':state['generation']})
            self.store.seal(writers_stopped=True)
        if legacy_inventory(self.root)['files']:
            raise RuntimeError('A writer created new shared private data before completion; recovery remains pending')
        atomic_json(self.complete, {'version':1,'user_id':self.session.user_id,'digest':state['digest'],
                                   'files':len(plan['files']),'bytes':plan['bytes'],'generation':state['generation']})
        self.journal.unlink()
        return {'migrated':True,'sealed':seal_workspace,'verified':True,'files':len(plan['files']),'bytes':plan['bytes'],
                'user_id':self.session.user_id,'digest':state['digest']}

    def recover_verified(self, *, writers_stopped=False):
        if writers_stopped is not True: raise RuntimeError('Verified writer shutdown is required for recovery')
        with self.store.transaction():
            state = json.loads(self.journal.read_text(encoding='utf-8'))
            if state.get('user_id') != self.session.user_id or state.get('phase') not in ('verified','committing'):
                raise RuntimeError('Incomplete copy needs reviewed recovery; no original files were removed by that phase')
            manifest = self.store.verify(state['generation'])
            plan_path = self._plan_path(state)
            row = next(row for row in manifest['files'] if row['path'] == plan_path)
            # The plan is authenticated inside the owner's encrypted generation.
            if row['bytes'] > 32*1024**2: raise ValueError('Migration plan exceeds recovery limit')
            key = self.session.profile_key
            from profile_workspace import _crypto, MAGIC
            Cipher, algorithms, modes, _ = _crypto()
            data = self.store.blob_path(manifest, row).read_bytes()
            if not data.startswith(MAGIC): raise ValueError('Invalid recovery plan format')
            offset = len(MAGIC)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(data[offset:offset+12], data[-16:])).decryptor()
            decryptor.authenticate_additional_data(self.store._aad(plan_path))
            plain = decryptor.update(data[offset+12:-16]) + decryptor.finalize()
            if hashlib.sha256(plain).hexdigest() != row['sha256']: raise ValueError('Recovery plan hash mismatch')
            plan = json.loads(plain)
            if hashlib.sha256(_encoded(plan['files'])).hexdigest() != state['digest']:
                raise ValueError('Recovery plan digest mismatch')
            self._validate_plan(plan,state)
            return self._commit(plan, state, seal_workspace=self.seal_on_commit)

    def recover_copy(self, expected_digest, *, writers_stopped=False):
        """Resume reviewed copies, retaining every original until verification."""
        if writers_stopped is not True: raise RuntimeError('Verified writer shutdown is required for recovery')
        with self.store.transaction():
            state = json.loads(self.journal.read_text(encoding='utf-8'))
            if state.get('user_id') != self.session.user_id or state.get('phase') != 'copying':
                raise RuntimeError('This is not an interrupted copy phase')
            plan_path = self._plan_path(state)
            saved_plan=self.store.workspace/plan_path
            _contained(self.root,saved_plan)
            if not saved_plan.exists():
                # A crash may occur after the journal but before its plan. The
                # original files remain authoritative only if the exact reviewed
                # digest still matches; never guess a changed inventory.
                plan=legacy_inventory(self.root)
                if not self.seal_on_commit:
                    token=plan_path.removeprefix('Data/ProfileMigration/harvest-').removesuffix('.json')
                    for row in plan['files']:row['target']='Data/SessionRecovery/'+token+'/'+row['source']
                    plan['digest']=hashlib.sha256(_encoded(plan['files'])).hexdigest()
                self._validate_plan(plan,state)
                if plan['digest']!=expected_digest:raise RuntimeError('Reviewed inventory changed before plan recovery')
                atomic_json(saved_plan,plan)
            else:
                plan = json.loads(saved_plan.read_text(encoding='utf-8'))
            self._validate_plan(plan,state)
            original = legacy_inventory(self.root)
            actual = [(row['source'],row['bytes'],row['sha256']) for row in original['files']]
            expected_sources = [(row['source'],row['bytes'],row['sha256']) for row in plan['files']]
            if actual != expected_sources or plan['digest'] != expected_digest:
                raise RuntimeError('Original migration inventory changed; review is required')
            expected = {row['target']:row for row in plan['files']}
            staged = {path+'.portal-copy-part' for path in expected}
            harvest_prefix = ('Data/SessionRecovery/' + plan_path.removeprefix('Data/ProfileMigration/harvest-').removesuffix('.json') + '/')
            for row in self.store.inventory():
                path=row['path']
                if path == plan_path or path in staged: continue
                if path in expected:
                    if (row['bytes'],row['sha256']) != (expected[path]['bytes'],expected[path]['sha256']):
                        raise RuntimeError('Changed copied file needs review; originals remain intact')
                elif self.seal_on_commit or path.startswith(harvest_prefix):
                    raise RuntimeError('Unexpected copied file needs review; originals remain intact')
            for row in plan['files']: self._copy_one(row)
            snapshot = self.store.snapshot()
            state.update(phase='verified',generation=snapshot['generation'])
            atomic_json(self.journal,state)
            return self._commit(plan,state,seal_workspace=self.seal_on_commit)


class SessionHarvest(LegacyMigration):
    """Seal known shared diagnostic leftovers into their authenticated owner.

    This transitional compatibility step runs only after verified shutdown and
    before releasing a login. It never assigns old plaintext to a new guest.
    """
    seal_on_commit = False
    def __init__(self, root, session):
        self.root=Path(root).resolve();self.session=session
        self.store=ProfileWorkspace(self.root,session)
        self.journal=self.store.base/'harvest-pending.json'
        self.complete=self.store.base/'harvest-last.json'
        _contained(self.root,self.journal);_contained(self.root,self.complete)

    def run(self, *, writers_stopped=False):
        if writers_stopped is not True: raise RuntimeError('Verified writer shutdown is required for harvest')
        self.session.profile_key
        with self.store.transaction():
            if self.journal.exists():
                state=json.loads(self.journal.read_text(encoding='utf-8'))
                if state.get('phase') == 'copying':
                    return self.recover_copy(state.get('digest'),writers_stopped=True)
                return self.recover_verified(writers_stopped=True)
            plan=legacy_inventory(self.root)
            if not plan['files']:return {'verified':True,'files':0,'user_id':self.session.user_id}
            token=uuid.uuid4().hex
            for row in plan['files']:
                row['target']='Data/SessionRecovery/'+token+'/'+row['source']
            plan['digest']=hashlib.sha256(_encoded(plan['files'])).hexdigest()
            plan_path='Data/ProfileMigration/harvest-'+token+'.json'
            if (self.root/'Agent/hardware_profiles.json').exists():
                require_space(self.root,plan['bytes']*2+8*1024**2,for_outputs=True)
            state={'version':1,'user_id':self.session.user_id,'phase':'copying','digest':plan['digest'],'plan_path':plan_path}
            self._validate_plan(plan,state)
            atomic_json(self.journal,state)
            atomic_json(self.store.workspace/plan_path,plan)
            for row in plan['files']:self._copy_one(row)
            snapshot=self.store.snapshot()
            state.update(phase='verified',generation=snapshot['generation'])
            atomic_json(self.journal,state)
            return self._commit(plan,state,seal_workspace=False)
