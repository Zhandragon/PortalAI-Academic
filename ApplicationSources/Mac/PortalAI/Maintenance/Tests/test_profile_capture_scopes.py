"""Synthetic privacy-scope checks; never inventory or migrate production data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Agent'))
import profile_paths as paths
from profile_migration import LegacyMigration, SessionHarvest, _source_target, legacy_inventory


GATEWAY_DATA = (
    'Sandbox/Security/agent_token.txt',
    'Sandbox/Security/OPEN_GUI_CONNECTION.txt',
    'Sandbox/Security/sandbox_runtime.json',
)
DIAGNOSTICS = (
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
PRIVATE_MEDIA = ('Benchmarks/run/summary.json', 'Benchmarks/run/image.png',
                 'Patch/Videos/Clipchamp/project.clipchamp', 'Patch/Videos/Clipchamp/audio.wav')
SHARED = (
    'Patch/repair.py',
    'Patch/VideosOther/source.py',
    'Sandbox/Security/PortableAI_Secure_Agent.wsb',
    'Sandbox/Security/Sandbox_Bootstrap.ps1',
    'Sandbox/Security/secure_agent_gateway.py',
    'Cache/Bootstrap/python-installer.exe',
    'Installer/Installers/source.ps1',
    'Voice/Qwen3-TTS/hf_cache/hub/models--example/blobs/weight',
    'LLM/models/example.gguf',
)


class Session:
    user_id = 'a' * 32
    role = 'admin'
    profile_key = b'k' * 32


class CaptureScopes(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'PortableAI'
        self.root.mkdir()
        self.session = Session()
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def write(self, relative, data=b'synthetic private fixture'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def open_profile(self):
        epoch = 'b' * 32
        self.write('Private/active-session.json', json.dumps({
            'user_id': self.session.user_id, 'epoch': epoch, 'state': 'open',
        }).encode())
        os.environ.update({paths.UID_ENV: self.session.user_id, paths.EPOCH_ENV: epoch})
        return paths.workspace_root(self.root, self.session.user_id)

    def test_new_media_paths_resolve_legacy_and_moved_drive_references(self):
        workspace = self.open_profile()
        for relative in PRIVATE_MEDIA:
            with self.subTest(relative=relative):
                expected = workspace / relative
                self.assertEqual(paths.private_path(self.root, relative), expected)
                self.assertEqual(paths.resolve_reference(self.root, self.root / relative), expected)
                self.assertEqual(paths.resolve_reference(self.root, 'Z:/PortableAI/' + relative), expected)
                self.assertEqual(paths.resolve_reference(self.root, expected), expected)
        for relative in SHARED:
            self.assertFalse(paths.is_private(relative), relative)
            self.assertEqual(paths.resolve_reference(self.root, relative), self.root / relative)

    def test_media_paths_keep_legacy_behavior_but_refuse_locked_profile(self):
        for relative in PRIVATE_MEDIA:
            self.assertEqual(paths.private_path(self.root, relative), self.root / relative)
        self.open_profile()
        self.write('Private/active-session.json', json.dumps({
            'user_id': self.session.user_id, 'epoch': 'b' * 32, 'state': 'closed',
        }).encode())
        for relative in PRIVATE_MEDIA:
            with self.subTest(relative=relative), self.assertRaises(paths.ProfileLocked):
                paths.resolve_reference(self.root, relative)

    def test_historical_entries_are_exact_and_do_not_claim_adjacent_sources(self):
        for relative in GATEWAY_DATA + DIAGNOSTICS:
            with self.subTest(relative=relative):
                self.assertEqual(_source_target(relative), 'Data/LegacyRecovery/' + relative)
                self.assertFalse(paths.is_private(relative))
                with self.assertRaises(ValueError):
                    _source_target(relative + '/unexpected-child')
                with self.assertRaises(ValueError):
                    _source_target(relative + '.unreviewed')
        for relative in SHARED:
            with self.subTest(shared=relative), self.assertRaises(ValueError):
                _source_target(relative)

    def test_nonregular_exact_historical_entry_stops_inventory(self):
        self.write(GATEWAY_DATA[0] + '/unexpected-child')
        with self.assertRaisesRegex(RuntimeError, 'Historical file is not regular'):
            legacy_inventory(self.root)
        self.assertTrue((self.root / GATEWAY_DATA[0] / 'unexpected-child').exists())

    def test_verified_encrypted_migration_captures_data_and_preserves_shared_assets(self):
        expected = {}
        for index, relative in enumerate(PRIVATE_MEDIA + GATEWAY_DATA + DIAGNOSTICS):
            expected[relative] = ('synthetic private record %d' % index).encode()
            self.write(relative, expected[relative])
        for relative in SHARED:
            self.write(relative, b'shared source or asset')
        plan = legacy_inventory(self.root)
        self.assertEqual({row['source'] for row in plan['files']}, set(expected))
        migration = LegacyMigration(self.root, self.session)
        receipt = migration.run(plan['digest'], writers_stopped=True)
        self.assertTrue(receipt['sealed'])
        self.assertEqual(receipt['files'], len(expected))
        self.assertEqual(legacy_inventory(self.root)['files'], [])
        self.assertEqual(migration.store.inventory(), [])
        for relative in SHARED:
            self.assertEqual((self.root / relative).read_bytes(), b'shared source or asset')
        migration.store.restore()
        for row in plan['files']:
            self.assertFalse((self.root / row['source']).exists())
            self.assertEqual((migration.store.workspace / row['target']).read_bytes(), expected[row['source']])

    def test_new_diagnostic_harvest_preserves_existing_profile_files(self):
        self.write(DIAGNOSTICS[-1], b'synthetic late diagnostic')
        self.write(SHARED[-2], b'shared model cache')
        harvest = SessionHarvest(self.root, self.session)
        existing = harvest.store.workspace / 'Data/Chat/keep.json'
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'current private history')
        result = harvest.run(writers_stopped=True)
        self.assertTrue(result['verified'])
        self.assertFalse(result['sealed'])
        self.assertEqual(existing.read_bytes(), b'current private history')
        self.assertFalse((self.root / DIAGNOSTICS[-1]).exists())
        self.assertEqual((self.root / SHARED[-2]).read_bytes(), b'shared model cache')
        matching = [row for row in harvest.store.verify()['files'] if row['path'].endswith('/' + DIAGNOSTICS[-1])]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]['path'].startswith('Data/SessionRecovery/'))


if __name__ == '__main__':
    unittest.main()
