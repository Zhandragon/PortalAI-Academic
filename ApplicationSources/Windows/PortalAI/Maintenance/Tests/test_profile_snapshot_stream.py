"""Streaming snapshot integrity and commit gates, using synthetic data only."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'Maintenance/Tests')]
from profile_workspace import ProfileWorkspace, CHUNK
from test_profile_workspace import FakeSession


class SnapshotStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProfileWorkspace(self.root, FakeSession())
        self.path = self.store.workspace / 'Outputs/synthetic.bin'
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'original synthetic bytes')
        self.initial = self.store.snapshot()
        self.pointer = (self.store.vault / 'current.enc').read_bytes()
        self.path.write_bytes(b'new synthetic bytes')

    def assert_uncommitted(self):
        self.assertEqual((self.store.vault / 'current.enc').read_bytes(), self.pointer)
        self.assertTrue(self.path.exists())
        self.assertEqual(self.store.verify()['generation'], self.initial['generation'])

    def test_streamed_hash_covers_multiple_chunks_and_empty_files(self):
        for data in (b'', b'abc' * (CHUNK // 3 + 117)):
            with self.subTest(bytes=len(data)):
                self.path.write_bytes(data)
                target = self.root / ('sample-' + str(len(data)) + '.enc')
                result = self.store._encrypt_file(self.path, target, 'Outputs/synthetic.bin', self.store._key())
                expected = (len(data), hashlib.sha256(data).hexdigest())
                self.assertEqual(result, expected)
                self.assertEqual(self.store._decrypt_file(target, 'Outputs/synthetic.bin', self.store._key()), expected)

    def test_changed_snapshot_independently_verifies_once_before_pointer_publication(self):
        original = self.store._decrypt_file
        def decrypt(*args, **kwargs):
            self.assertEqual((self.store.vault / 'current.enc').read_bytes(), self.pointer)
            return original(*args, **kwargs)
        with patch.object(self.store, '_decrypt_file', side_effect=decrypt) as calls:
            report = self.store.snapshot()
        self.assertEqual(calls.call_count, 1)
        self.assertNotEqual(report['generation'], self.initial['generation'])
        self.assertEqual(self.store.verify()['generation'], report['generation'])

    def test_input_changed_before_encryption_cannot_commit(self):
        original = self.store._encrypt_file
        def encrypt(*args):
            self.path.write_bytes(b'mutated input')
            return original(*args)
        with patch.object(self.store, '_encrypt_file', side_effect=encrypt):
            with self.assertRaisesRegex(RuntimeError, 'Workspace changed'):
                self.store.snapshot()
        self.assert_uncommitted()

    def test_incorrect_stream_count_or_hash_cannot_commit(self):
        original = self.store._encrypt_file
        for broken in ('count', 'hash'):
            with self.subTest(broken=broken):
                def encrypt(*args):
                    size, sha = original(*args)
                    return (size + 1, sha) if broken == 'count' else (size, '0' * 64)
                with patch.object(self.store, '_encrypt_file', side_effect=encrypt):
                    with self.assertRaisesRegex(RuntimeError, 'Workspace changed'):
                        self.store.snapshot()
                self.assert_uncommitted()

    def test_corrupted_written_ciphertext_cannot_replace_current_generation(self):
        original = self.store._encrypt_file
        def encrypt(source, target, relative, key):
            result = original(source, target, relative, key)
            value = bytearray(target.read_bytes()); value[-1] ^= 1
            target.write_bytes(value)
            return result
        with patch.object(self.store, '_encrypt_file', side_effect=encrypt):
            with self.assertRaises(Exception): self.store.snapshot()
        self.assert_uncommitted()

    def test_input_mutation_after_stream_check_fails_final_inventory(self):
        original = self.store._encrypt_file
        def encrypt(*args):
            result = original(*args)
            self.path.write_bytes(b'changed after encryption')
            return result
        with patch.object(self.store, '_encrypt_file', side_effect=encrypt):
            with self.assertRaisesRegex(RuntimeError, 'Workspace changed'):
                self.store.snapshot()
        self.assert_uncommitted()

    def test_seal_still_verifies_ciphertext_again_before_deleting_plaintext(self):
        original = self.store.verify
        def verify(*args, **kwargs):
            self.assertTrue(self.path.exists())
            return original(*args, **kwargs)
        with patch.object(self.store, 'verify', side_effect=verify) as checks:
            result = self.store.seal(writers_stopped=True)
        self.assertEqual(checks.call_count, 2)
        self.assertTrue(result['sealed'])
        self.assertFalse(self.path.exists())
        self.assertTrue(self.store.restore()['ready'])
        self.assertEqual(self.path.read_bytes(), b'new synthetic bytes')


if __name__ == '__main__':
    unittest.main()
