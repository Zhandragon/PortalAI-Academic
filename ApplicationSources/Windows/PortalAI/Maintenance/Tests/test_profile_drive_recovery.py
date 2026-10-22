"""Abrupt process loss and removable-storage I/O failures on synthetic profiles."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(Path(__file__).resolve().parent)]
import profile_workspace
from profile_workspace import ProfileWorkspace
from platform_runtime import python_path
from test_profile_workspace import FakeSession
from test_profile_runtime import AccountsFixture, OWNER
from profile_runtime import ProfileRuntime

CHILD = r'''
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import profile_workspace as module
import profile_lazy_state
store = module.ProfileWorkspace(Path(sys.argv[2]), SimpleNamespace(user_id='a'*32, profile_key=b'k'*32))
stage = sys.argv[3]
if stage == 'encrypt':
    def interrupted(source, target, relative, key):
        with target.open('xb') as output:
            output.write(b'uncommitted synthetic ciphertext'); output.flush(); os.fsync(output.fileno())
            os._exit(91)
    store._encrypt_file = interrupted
    store.snapshot()
elif stage == 'pointer':
    original = module._atomic_bytes
    def interrupted(path, data):
        original(path, data)
        if path.name == 'current.enc': os._exit(91)
    module._atomic_bytes = interrupted
    store.seal(writers_stopped=True)
elif stage == 'seal':
    original = module.Path.unlink
    def interrupted(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path.name == 'a.txt' and path.is_relative_to(store.workspace): os._exit(91)
    module.Path.unlink = interrupted
    store.seal(writers_stopped=True)
elif stage == 'decrypt':
    original = store._decrypt_file
    def interrupted(source, relative, key, target=None, *, created=None):
        if target is None: return original(source, relative, key)
        with target.open('xb') as output:
            created(output)
            output.write(b'partial synthetic plaintext'); output.flush(); os.fsync(output.fileno())
            os._exit(91)
    store._decrypt_file = interrupted
    store.restore()
elif stage == 'publish':
    original = profile_lazy_state.publish_no_replace
    def interrupted(source, target):
        original(source, target); os._exit(91)
    profile_lazy_state.publish_no_replace = interrupted
    store.restore()
raise AssertionError('Crash injection was not reached')
'''


class DriveRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProfileWorkspace(self.root, FakeSession())
        for name in ('a', 'b'):
            path = self.store.workspace/'Outputs'/f'{name}.txt'
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(name.encode()*4096)

    def crash(self, stage):
        result = subprocess.run([str(python_path(ROOT)), '-B', '-c', CHILD,
            str(ROOT/'Agent'), str(self.root), stage], capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 91, result.stderr)
        self.store = ProfileWorkspace(self.root, FakeSession())

    def assert_roundtrip(self, expected):
        self.assertTrue(self.store.seal(writers_stopped=True)['sealed'])
        self.assertFalse(self.store.inventory())
        self.assertTrue(self.store.restore()['ready'])
        self.assertEqual(self.store.inventory(), expected)
        self.assertFalse(list(self.store.workspace.rglob('*.part')))

    def test_crash_during_encryption_preserves_previous_commit_and_latest_plaintext(self):
        self.store.snapshot(); pointer = (self.store.vault/'current.enc').read_bytes()
        (self.store.workspace/'Outputs/a.txt').write_bytes(b'new unsaved content')
        expected = self.store.inventory(); self.crash('encrypt')
        self.assertEqual((self.store.vault/'current.enc').read_bytes(), pointer)
        self.assertEqual(self.store.inventory(), expected)
        self.assert_roundtrip(expected)

    def test_crash_after_pointer_commit_before_deletion_retains_all_files(self):
        expected = self.store.inventory(); self.crash('pointer')
        self.assertEqual(self.store.inventory(), expected)
        self.store.verify(); self.assert_roundtrip(expected)

    def test_crash_mid_seal_resumes_verified_generation_without_losing_deleted_files(self):
        expected = self.store.inventory(); self.crash('seal')
        self.assertTrue((self.store.base/'seal-pending.json').exists())
        self.assertEqual(len(self.store.inventory()), 1)
        self.assert_roundtrip(expected)

    def test_eager_restore_recovers_owned_partial_file_after_abrupt_exit(self):
        expected = self.store.inventory(); self.store.seal(writers_stopped=True); self.crash('decrypt')
        self.assertTrue((self.store.base/'restore-inflight.enc').exists())
        self.assertTrue(list(self.store.workspace.rglob('*.part')))
        self.assertTrue(self.store.restore()['ready'])
        self.assertEqual(self.store.inventory(), expected); self.assert_roundtrip(expected)

    def test_eager_restore_recovers_crash_after_exclusive_publication(self):
        expected = self.store.inventory(); self.store.seal(writers_stopped=True); self.crash('publish')
        self.assertTrue((self.store.base/'restore-inflight.enc').exists())
        self.assertTrue(self.store.restore()['ready'])
        self.assertEqual(self.store.inventory(), expected); self.assert_roundtrip(expected)

    def test_replaced_partial_file_is_preserved_and_recovery_refused(self):
        self.store.seal(writers_stopped=True); self.crash('decrypt')
        part = next(self.store.workspace.rglob('*.part'))
        replacement = part.with_name('unrelated.txt'); replacement.write_bytes(b'unrelated writer')
        os.replace(replacement, part)
        with self.assertRaisesRegex(ValueError, 'identity'): self.store.restore()
        self.assertEqual(part.read_bytes(), b'unrelated writer')
        self.assertTrue((self.store.base/'restore-inflight.enc').exists())

    def test_scan_io_failure_cannot_commit_an_incomplete_inventory(self):
        self.store.snapshot(); pointer = (self.store.vault/'current.enc').read_bytes()
        original = os.scandir
        def disconnected(path):
            if str(path).endswith('Outputs'): raise OSError(errno.EIO, 'Synthetic disconnected storage')
            return original(path)
        with patch('os.scandir', side_effect=disconnected):
            with self.assertRaises(OSError): self.store.snapshot()
        self.assertEqual((self.store.vault/'current.enc').read_bytes(), pointer)
        self.assertEqual(len(self.store.inventory()), 2)

    def test_corrupt_intent_cannot_authorize_partial_plaintext_cleanup(self):
        self.store.seal(writers_stopped=True); self.crash('decrypt')
        part = next(self.store.workspace.rglob('*.part')); before = part.read_bytes()
        intent = self.store.base/'restore-inflight.enc'
        raw = bytearray(intent.read_bytes()); raw[-1] ^= 1; intent.write_bytes(raw)
        with self.assertRaises(Exception): self.store.restore()
        self.assertEqual(part.read_bytes(), before)
        self.assertTrue(intent.exists())

    def test_lost_journal_does_not_allow_lazy_restore_or_snapshot_to_adopt_partial_data(self):
        self.store.seal(writers_stopped=True); self.crash('decrypt')
        (self.store.base/'restore-pending.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'journal is missing'): self.store.restore(lazy=True)
        with self.assertRaisesRegex(RuntimeError, 'Interrupted restoration'): self.store.snapshot()

    def test_io_failure_during_close_retains_session_journal_and_lock_for_retry(self):
        backend = AccountsFixture(); owner = backend.login(OWNER)
        runtime_root = self.root/'runtime-fixture'; runtime_root.mkdir()
        runtime = ProfileRuntime(runtime_root, backend, quiesce=lambda *_: {'stopped': True})
        with patch.dict(os.environ):
            try:
                runtime.prepare(owner)
                store = ProfileWorkspace(runtime_root, owner)
                target = store.workspace/'Outputs/keep.txt'; target.parent.mkdir(parents=True); target.write_text('keep')
                original = os.scandir
                def disconnected(path):
                    if str(path).endswith('Outputs'): raise OSError(errno.EIO, 'Synthetic disconnected storage')
                    return original(path)
                with patch('os.scandir', side_effect=disconnected):
                    with self.assertRaises(OSError): runtime.close(owner, writers_stopped=True)
                self.assertTrue(owner.active); self.assertIs(runtime.session, owner)
                self.assertIsNotNone(runtime._process_lock)
                self.assertEqual(json.loads(runtime.marker.read_text())['state'], 'closing')
                self.assertTrue(target.exists())
                self.assertTrue(runtime.close(owner, writers_stopped=True)['sealed'])
            finally:
                if runtime._process_lock is not None:
                    runtime._process_lock.__exit__(None, None, None)


if __name__ == '__main__': unittest.main()
