"""Public wheelhouse compatibility and fail-closed repair boundaries.

Only disposable roots and synthetic wheel contents are used. No account is opened.
"""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'Tools')]
import repair_account_runtime as repair
import import_amd_runtime as wheel_validator


def fixture_wheel(path, name, bad_record=False):
    content = b'PUBLIC SYNTHETIC WHEEL\n'
    member = name.replace('-', '_') + '/__init__.py'
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()
    record = io.StringIO()
    csv.writer(record).writerow([member, 'sha256=' + ('0' * 43 if bad_record else digest), len(content)])
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(member, content)
        archive.writestr(name.replace('-', '_') + '-1.0.dist-info/RECORD', record.getvalue())


class AccountRepairPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='portalai-public-repair-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'Agent').mkdir()
        (self.root / 'Agent/hardware_profiles.json').write_text(json.dumps({'storage': {
            'minimum_free_gib': 50, 'minimum_free_fraction': .10, 'output_reserve_gib': 100}}))
        self.addCleanup(patch.stopall)
        patch.object(wheel_validator, 'ROOT', self.root).start()

    def make_receipt(self, directory='Runtime/AccountPython/wheelhouse', bad_record=False):
        rows = []
        for name in ('cryptography', 'eth-account'):
            path = self.root / directory / (name.replace('-', '_') + '-1.0-py3-none-any.whl')
            fixture_wheel(path, name, bad_record)
            rows.append({'name': name, 'wheel': path.relative_to(self.root).as_posix(),
                         'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        self.write_receipt(rows)
        return rows

    def write_receipt(self, rows):
        receipt = self.root / 'Maintenance/Imports/account-runtime-lock.json'
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({'assets': rows}), encoding='utf-8')

    def test_clean_public_wheelhouse_verifies_real_record(self):
        rows = self.make_receipt()
        self.assertEqual(repair.verified_assets(self.root), rows)
        self.assertFalse((self.root / 'Private').exists())

    def test_legacy_exact_wheelhouse_remains_supported(self):
        rows = self.make_receipt('Cache/account-runtime-wheelhouse')
        self.assertEqual(repair.verified_assets(self.root), rows)

    def test_unreviewed_paths_remain_rejected(self):
        rows = self.make_receipt()
        for value in ('../outside.whl', 'Runtime/AccountPython/wheelhouse/sub/a.whl',
                      'Runtime/AccountPython/packages/a.whl', 'Private/a.whl',
                      'Cache/other/a.whl', 'Runtime/AccountPython/wheelhouse/../a.whl',
                      str(self.root / 'Runtime/AccountPython/wheelhouse/a.whl')):
            with self.subTest(path=value):
                self.write_receipt([{**rows[0], 'wheel': value}, rows[1]])
                with self.assertRaises(ValueError):
                    repair.verified_assets(self.root)

    def test_corrupt_public_wheel_rejected_before_staging(self):
        rows = self.make_receipt()
        path = self.root / rows[0]['wheel']
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with self.assertRaisesRegex(ValueError, 'verified receipt'):
            repair.verified_assets(self.root)
        self.assertFalse((self.root / 'Runtime/AccountPython/packages-stage').exists())

    def test_bad_record_rejected_even_with_matching_archive_hash(self):
        self.make_receipt(bad_record=True)
        with self.assertRaisesRegex(RuntimeError, 'Wheel member verification failed'):
            repair.verified_assets(self.root)

    def test_missing_wheel_does_not_create_any_replacement(self):
        rows = self.make_receipt()
        (self.root / rows[0]['wheel']).unlink()
        with self.assertRaises(FileNotFoundError):
            repair.verified_assets(self.root)
        self.assertFalse((self.root / 'Runtime/AccountPython/packages-stage').exists())

    def test_hardlinked_wheel_rejected(self):
        rows = self.make_receipt()
        os.link(self.root / rows[0]['wheel'], self.root / 'link')
        with self.assertRaisesRegex(ValueError, 'verified receipt'):
            repair.verified_assets(self.root)

    def test_case_insensitive_duplicate_wheel_rejected(self):
        rows = self.make_receipt()
        duplicate = dict(rows[0])
        name = Path(duplicate['wheel']).name.upper().replace('.WHL', '.whl')
        duplicate['wheel'] = 'Runtime/AccountPython/wheelhouse/' + name
        self.write_receipt([rows[0], duplicate, rows[1]])
        with self.assertRaisesRegex(ValueError, 'unreviewed package'):
            repair.verified_assets(self.root)

    def test_incomplete_account_dependencies_rejected(self):
        rows = self.make_receipt()
        self.write_receipt(rows[:1])
        with self.assertRaisesRegex(ValueError, 'receipt is incomplete'):
            repair.verified_assets(self.root)

    @unittest.skipUnless(os.name == 'nt', 'Windows repair gate')
    def test_fresh_root_cannot_be_initialized_by_repair(self):
        import profile_shutdown
        self.make_receipt()
        with patch.object(profile_shutdown, '_snapshot', return_value={}), \
             patch.object(profile_shutdown, '_select', return_value=[]), \
             patch.object(repair.subprocess, 'run', side_effect=AssertionError('No install')):
            with self.assertRaisesRegex(RuntimeError, 'existing account installation'):
                repair.repair(self.root)
        self.assertFalse((self.root / 'Private').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows repair gate')
    def test_owned_process_prevents_repair(self):
        import profile_shutdown
        self.make_receipt()
        with patch.object(profile_shutdown, '_snapshot', return_value={}), \
             patch.object(profile_shutdown, '_select', return_value=[123]), \
             patch.object(repair.subprocess, 'run', side_effect=AssertionError('No install')):
            with self.assertRaisesRegex(RuntimeError, 'Close PortalAI'):
                repair.repair(self.root)
        self.assertFalse((self.root / 'Private').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows profile lock')
    def test_locked_profile_prevents_repair_and_preserves_evidence(self):
        import profile_shutdown
        from mission_runner import process_lock
        self.make_receipt()
        lock = self.root / 'Private/profile-runtime.lock'
        lock.parent.mkdir()
        lock.write_bytes(b'0')
        sentinel = lock.parent / 'synthetic-sealed-evidence'
        sentinel.write_bytes(b'SYNTHETIC RETAINED EVIDENCE')
        with patch.object(profile_shutdown, '_snapshot', return_value={}), \
             patch.object(profile_shutdown, '_select', return_value=[]), \
             patch.object(repair.subprocess, 'run', side_effect=AssertionError('No install')), \
             process_lock(lock):
            with self.assertRaises((RuntimeError, PermissionError)):
                repair.repair(self.root)
        self.assertEqual(sentinel.read_bytes(), b'SYNTHETIC RETAINED EVIDENCE')
        self.assertFalse((self.root / 'Runtime/AccountPython/packages-stage').exists())


if __name__ == '__main__':
    unittest.main()
