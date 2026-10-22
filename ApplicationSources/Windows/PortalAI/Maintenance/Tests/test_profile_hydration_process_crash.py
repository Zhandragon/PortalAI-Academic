"""Abrupt child exits during synthetic hydration; no production keys or paths."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(Path(__file__).resolve().parent)]
from platform_runtime import python_path
from profile_workspace import ProfileWorkspace
from test_profile_workspace import FakeSession

CHILD = r'''
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import profile_lazy_state
from profile_workspace import ProfileWorkspace
store = ProfileWorkspace(Path(sys.argv[2]), SimpleNamespace(user_id='a'*32, profile_key=b'k'*32))
if sys.argv[3] == 'during-write':
    def interrupted(source, relative, key, target=None, *, created=None):
        with target.open('xb') as output:
            created(output)
            output.write(b'synthetic interrupted plaintext')
            output.flush(); os.fsync(output.fileno())
            os._exit(91)
    store._decrypt_file = interrupted
else:
    original = profile_lazy_state.publish_no_replace
    def interrupted(source, target):
        original(source, target)
        os._exit(92)
    profile_lazy_state.publish_no_replace = interrupted
store.materialize('Outputs/fixture.bin')
raise AssertionError('Crash injection did not execute')
'''


class ProcessCrashTests(unittest.TestCase):
    def run_crash(self, stage, code):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileWorkspace(Path(folder), FakeSession())
            data = b'synthetic payload'*100
            target = store.workspace/'Outputs/fixture.bin'
            target.parent.mkdir(parents=True)
            target.write_bytes(data)
            store.seal(writers_stopped=True)
            store.restore(lazy=True)
            manifest = store.manifest()
            blob = store.blob_path(manifest, manifest['files'][0])
            ciphertext = blob.read_bytes()
            result = subprocess.run([str(python_path(ROOT)), '-B', '-c', CHILD,
                                     str(ROOT/'Agent'), folder, stage],
                                    capture_output=True, text=True, timeout=20,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, code, result.stderr)
            # Fresh instance reacquires the OS lock after an ungraceful exit.
            recovered = ProfileWorkspace(Path(folder), FakeSession())
            recovered.materialize('Outputs/fixture.bin')
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(blob.read_bytes(), ciphertext)
            self.assertFalse(list(store.workspace.rglob('*.part')))
            self.assertEqual(recovered.pending()['files'], 0)
            recovered.seal(writers_stopped=True)
            self.assertFalse(recovered.inventory())
            recovered.restore(lazy=True)
            recovered.materialize('Outputs/fixture.bin')
            self.assertEqual(target.read_bytes(), data)

    def test_abrupt_exit_with_partial_plaintext_is_reconciled(self):
        self.run_crash('during-write', 91)

    def test_abrupt_exit_after_publication_before_ledger_commit_is_reconciled(self):
        self.run_crash('after-publish', 92)


if __name__ == '__main__':
    unittest.main()
