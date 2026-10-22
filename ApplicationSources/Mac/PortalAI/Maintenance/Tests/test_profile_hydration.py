"""Real loopback/cross-process lazy restoration, synthetic accounts only."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'Maintenance/Tests')]
from profile_runtime import ProfileRuntime
from profile_workspace import ProfileWorkspace
from profile_paths import private_path, resolve_reference, ProfileLocked
import profile_hydration as hydration
from platform_runtime import python_path
from test_profile_runtime import AccountsFixture, OWNER


class HydrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in ('PORTALAI_PROFILE_ID', 'PORTALAI_PROFILE_EPOCH', hydration.PORT_ENV,
                    hydration.TOKEN_ENV, hydration.OWNER_ENV):
            os.environ.pop(key, None)
        self.backend = AccountsFixture()
        self.session = self.backend.login(OWNER)
        self.store = ProfileWorkspace(self.root, self.session)
        for relative, value in (('Outputs/old.txt', b'old media'), ('Outputs/nested/second.txt', b'second media'),
                                ('Data/Chat/one.json', b'{}'), ('Data/LegacyRecovery/archive.bin', b'old recovery')):
            path = self.store.workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        self.store.seal(writers_stopped=True)
        self.runtime = ProfileRuntime(self.root, self.backend, lazy_restore=True,
                                      quiesce=Mock(return_value={'stopped': True}),
                                      legacy_check=lambda _root: {'clean': True})
        self.runtime.prepare(self.session)

    def tearDown(self):
        try:
            if self.runtime.session is not None:
                self.runtime.close(self.runtime.session, writers_stopped=True)
        finally:
            if self.runtime._hydration is not None:
                self.runtime._hydration.close()
            if self.runtime._process_lock is not None:
                self.runtime._process_lock.__exit__(None, None, None)
            self.env.stop()
            self.temp.cleanup()

    def test_login_keeps_operational_data_ready_and_exact_reference_hydrates_old_path(self):
        self.assertTrue((self.store.workspace / 'Data/Chat/one.json').is_file())
        self.assertFalse((self.store.workspace / 'Outputs/old.txt').exists())
        self.assertEqual(private_path(self.root, 'Outputs/old.txt').read_bytes(), b'old media')
        self.assertFalse((self.store.workspace / 'Outputs/nested/second.txt').exists())
        self.assertFalse((self.store.workspace / 'Data/LegacyRecovery/archive.bin').exists())

    def test_path_construction_does_not_restore_entire_output_folder(self):
        private_path(self.root, 'Outputs')
        self.assertFalse((self.store.workspace / 'Outputs/old.txt').exists())
        folder = resolve_reference(self.root, 'Outputs')
        self.assertEqual((folder / 'old.txt').read_bytes(), b'old media')
        self.assertEqual((folder / 'nested/second.txt').read_bytes(), b'second media')
        self.assertFalse((self.store.workspace / 'Data/LegacyRecovery/archive.bin').exists())

    def test_actual_child_restores_using_capability_without_account_key(self):
        child_env = dict(os.environ)
        self.assertNotIn(self.session.profile_key.hex(), json.dumps(child_env))
        script = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                  'from profile_paths import resolve_reference; '
                  'print(resolve_reference(Path(sys.argv[2]),"Outputs/old.txt").read_text())')
        result = subprocess.run([str(python_path(ROOT)), '-B', '-c', script, str(ROOT / 'Agent'), str(self.root)],
                                env=child_env, capture_output=True, text=True, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'old media')

    def request(self, token=None, origin=None, **changes):
        broker = self.runtime._hydration
        body = {'user_id': OWNER, 'epoch': self.runtime.epoch, 'relative': 'Outputs/old.txt', 'recursive': False}
        body.update(changes)
        headers = {'Content-Type': 'application/json', 'X-PortalAI-Capability': token or broker.token}
        if origin is not None:
            headers['Origin'] = origin
        connection = http.client.HTTPConnection('127.0.0.1', broker.port, timeout=5)
        try:
            connection.request('POST', '/materialize', json.dumps(body), headers)
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def test_wrong_capability_origin_epoch_other_user_and_path_escape_are_rejected(self):
        for kwargs in ({'token': 'incorrect'}, {'origin': 'https://example.com'}, {'epoch': 'f' * 32},
                       {'user_id': '2' * 32}, {'relative': '../other'}, {'relative': 'Private/Accounts'}):
            with self.subTest(kwargs=kwargs):
                self.assertNotEqual(self.request(**kwargs), 200)
                self.assertFalse((self.store.workspace / 'Outputs/old.txt').exists())

    def test_paused_broker_cannot_restore_and_close_still_preserves_deferred_data(self):
        self.runtime.pause_hydration()
        with self.assertRaises(ProfileLocked):
            hydration.materialize(self.root, 'Outputs/old.txt')
        self.runtime.close(self.session, writers_stopped=True)
        fresh = self.backend.login(OWNER)
        saved = ProfileWorkspace(self.root, fresh).verify()
        self.assertIn('Outputs/old.txt', [row['path'] for row in saved['files']])

    def test_pause_cancels_and_joins_an_admitted_request_before_sealing(self):
        entered = threading.Event(); release = threading.Event(); failures = []
        original = ProfileWorkspace.materialize
        def controlled(store, *args, **kwargs):
            entered.set()
            if not release.wait(5): raise RuntimeError('test worker did not release')
            kwargs['check']()
            return original(store, *args, **kwargs)
        def worker():
            try: hydration.materialize(self.root, 'Outputs/old.txt')
            except Exception as error: failures.append(error)
        with patch.object(ProfileWorkspace, 'materialize', controlled):
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(entered.wait(5))
            self.runtime.pause_hydration()
            release.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(failures)
        self.assertFalse((self.store.workspace / 'Outputs/old.txt').exists())
        self.assertTrue(self.runtime.close(self.session, writers_stopped=True)['sealed'])

    def test_missing_controller_never_misreports_deferred_file_as_absent(self):
        broker = self.runtime._hydration
        broker.close(); self.runtime._hydration = None
        with self.assertRaisesRegex(ProfileLocked, 'controller'):
            hydration.materialize(self.root, 'Outputs/old.txt')

    def test_materialized_deletion_is_not_resurrected_but_untouched_media_survives(self):
        path = resolve_reference(self.root, 'Outputs/old.txt')
        path.unlink()
        self.runtime.close(self.session, writers_stopped=True)
        fresh = self.backend.login(OWNER)
        rows = ProfileWorkspace(self.root, fresh).verify()['files']
        self.assertNotIn('Outputs/old.txt', [row['path'] for row in rows])
        self.assertIn('Outputs/nested/second.txt', [row['path'] for row in rows])


if __name__ == '__main__':
    unittest.main()
