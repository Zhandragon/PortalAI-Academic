"""Saved references follow migrated data without granting access to other users."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
import profile_paths as paths
from profile_migration import HISTORICAL_FILES, RUNTIME_PUBLIC, _source_target


class HistoricalReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'PortableAI'
        self.root.mkdir()
        self.uid, self.epoch = 'a' * 32, 'b' * 32
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop(paths.UID_ENV, None)
        os.environ.pop(paths.EPOCH_ENV, None)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def activate(self):
        marker = self.root / 'Private/active-session.json'
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'user_id': self.uid, 'epoch': self.epoch, 'state': 'open'}))
        os.environ[paths.UID_ENV] = self.uid
        os.environ[paths.EPOCH_ENV] = self.epoch
        return self.root / 'Private/Users' / self.uid / 'Workspace'

    def test_saved_relative_absolute_and_moved_drive_reports_follow_same_file(self):
        workspace = self.activate()
        relative = 'Maintenance/Reports/media/output.mp4'
        expected = workspace / 'Data/LegacyRecovery' / relative
        for value in (relative, self.root / relative, 'Z:\\PortableAI\\' + relative.replace('/', '\\')):
            with self.subTest(value=str(value)):
                self.assertEqual(paths.resolve_reference(self.root, value), expected)

    def test_all_reviewed_historical_scopes_and_exact_files_use_classifier(self):
        workspace = self.activate()
        samples = ['Backups/snapshot/Data/Chat/old.json',
                   'Maintenance/Archive/past/media.wav',
                   'Maintenance/Endurance/case/trace.json',
                   'Agent/.runtime/old_job_result.json', *HISTORICAL_FILES]
        for relative in samples:
            with self.subTest(relative=relative):
                self.assertEqual(paths.resolve_reference(self.root, relative),
                                 workspace / _source_target(relative))

    def test_windows_scope_case_and_drive_letter_preserve_saved_filename(self):
        workspace = self.activate()
        pairs = [('z:\\portableai\\maintenance\\REPORTS\\Rendered.MP4',
                  'Data/LegacyRecovery/Maintenance/Reports/Rendered.MP4'),
                 ('BACKUPS/snapshot/Old.PNG', 'Data/LegacyRecovery/Backups/snapshot/Old.PNG'),
                 ('controlcenter/portableai_crash.LOG',
                  'Data/LegacyRecovery/ControlCenter/PortableAI_Crash.log'),
                 ('agent/.RUNTIME/JobTrace.json', 'Data/LegacyRecovery/Agent/.runtime/JobTrace.json'),
                 ('outputs/Rendered.PNG', 'Outputs/Rendered.PNG')]
        for value, target in pairs:
            with self.subTest(value=value):
                self.assertEqual(paths.resolve_reference(self.root, value), workspace / target)

    def test_legacy_installation_keeps_historical_shared_paths(self):
        for relative in ('Maintenance/Reports/media.mp4', 'Backups/snapshot/report.json',
                         'Agent/.runtime/old_job_result.json'):
            with self.subTest(relative=relative):
                self.assertEqual(paths.resolve_reference(self.root, relative), self.root / relative)
        with self.assertRaises(paths.ProfileLocked):
            paths.resolve_reference(self.root, 'Z:/PortableAI/Maintenance/Reports/media.mp4')

    def test_locked_alias_never_returns_unmigrated_shared_plaintext(self):
        self.activate()
        relative = 'Maintenance/Reports/media.mp4'
        shared = self.root / relative
        shared.parent.mkdir(parents=True)
        shared.write_bytes(b'old private output')
        os.environ.pop(paths.UID_ENV)
        os.environ.pop(paths.EPOCH_ENV)
        for value in (relative, shared, 'Z:/PortableAI/' + relative):
            with self.subTest(value=str(value)):
                with self.assertRaises(paths.ProfileLocked):
                    paths.resolve_reference(self.root, value, allow_external=True)
        self.assertEqual(shared.read_bytes(), b'old private output')

    def test_closed_marker_and_cross_user_paths_stay_rejected(self):
        workspace = self.activate()
        suffix = 'Data/LegacyRecovery/Maintenance/Reports/media.mp4'
        self.assertEqual(paths.resolve_reference(self.root, workspace / suffix), workspace / suffix)
        for other in (self.root / 'Private/Users' / ('c' * 32) / 'Workspace' / suffix,
                      'Z:/PortableAI/Private/Users/' + 'c' * 32 + '/Workspace/' + suffix):
            with self.subTest(other=str(other)):
                with self.assertRaises(paths.ProfileLocked):
                    paths.resolve_reference(self.root, other, allow_external=True)
        marker = self.root / 'Private/active-session.json'
        marker.write_text(json.dumps({'user_id': self.uid, 'epoch': self.epoch, 'state': 'closed'}))
        with self.assertRaises(paths.ProfileLocked):
            paths.resolve_reference(self.root, 'Maintenance/Reports/media.mp4')

    def test_public_assets_and_lifecycle_metadata_remain_shared_even_while_locked(self):
        self.activate()
        os.environ.pop(paths.UID_ENV)
        os.environ.pop(paths.EPOCH_ENV)
        samples = ['Agent/.runtime/' + name for name in RUNTIME_PUBLIC]
        samples += ['agent/.RUNTIME/QWEN_LAST_STOP.JSON', 'Agent/.runtime/worker.LOCK',
                    'LLM/models/model.gguf', 'Runtime/BootstrapPython/python.exe',
                    'Cache/Bootstrap/python-3.12.10.exe', 'ControlCenter/account_ui.py',
                    'Patch/script.py', 'Maintenance/Tests/test_profile_paths.py']
        for relative in samples:
            with self.subTest(relative=relative):
                self.assertEqual(paths.resolve_reference(self.root, relative), self.root / relative)

    def test_historical_alias_does_not_admit_traversal_or_unrelated_external_paths(self):
        self.activate()
        for value in ('Maintenance/Reports/../../Private/other',
                      'Z:/PortableAI/Backups/../Private/other',
                      'Z:/OtherBundle/Maintenance/Reports/media.mp4'):
            with self.subTest(value=value):
                with self.assertRaises((ValueError, paths.ProfileLocked)):
                    paths.resolve_reference(self.root, value)


if __name__ == '__main__':
    unittest.main()
