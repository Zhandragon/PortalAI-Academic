"""CPU-only crash, provenance, and immutable-checkpoint regression tests."""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from confirmation_store import CaseStore, digest


class ConfirmationStoreTests(unittest.TestCase):
    def setUp(self):
        self.parent = LAB / 'checkpoint-store-test-fixtures'
        self.parent.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=self.parent)).resolve()
        self.assertTrue(self.root.is_relative_to(self.parent.resolve()))
        self.path = self.root / 'state.sqlite'
        self.frozen = 'a' * 64
        self.request = {'model_sha256': 'b' * 64, 'prompt_sha256': 'c' * 64, 'seed': 123,
                        'sampling': {'temperature': 0.6, 'max_tokens': 32768}}
        self.requests = {'baseline': {'case-1': self.request}, 'candidate': {'case-1': self.request}}
        self.result = {'id': 'case-1', 'text': '\\boxed{4}', 'grading': {'correct': True},
                       'tokens': 5, 'seconds': 0.25, 'finish': 'stop'}
        self.store = CaseStore(self.path, self.frozen, create=True)

    def tearDown(self):
        self.store.close()
        self.assertTrue(self.root.resolve().is_relative_to(self.parent.resolve()))
        self.assertNotEqual(self.root.resolve(), self.parent.resolve())
        shutil.rmtree(self.root)

    def save(self):
        return self.store.save('baseline', 'case-1', self.request, self.result)

    def reopen(self):
        self.store.close()
        self.store = CaseStore(self.path, self.frozen)

    def test_crash_after_commit_before_mirror_does_not_replay_case(self):
        saved = self.save()
        self.reopen()
        rows = self.store.load(self.requests)
        self.assertEqual(rows['baseline'], {'case-1': saved})
        self.store.export(self.root)
        path = self.root / 'baseline' / (digest(b'case-1')[:20] + '.json')
        self.assertEqual(json.loads(path.read_text()), saved)
        self.store.export(self.root)
        with self.assertRaisesRegex(ValueError, 'overwritten or replayed'):
            self.save()

    def test_frozen_identity_change_refuses_resume(self):
        self.save()
        with self.assertRaisesRegex(ValueError, 'Frozen experiment changed'):
            CaseStore(self.path, 'd' * 64)

    def test_changed_seed_prompt_model_or_sampling_refuses_reuse(self):
        self.save()
        for key, value in [('seed', 124), ('prompt_sha256', 'd' * 64),
                           ('model_sha256', 'e' * 64), ('sampling', {'temperature': 0.0})]:
            with self.subTest(field=key):
                requests = copy.deepcopy(self.requests)
                requests['baseline']['case-1'][key] = value
                with self.assertRaisesRegex(ValueError, 'prompt, seed, model, or sampling changed'):
                    self.store.load(requests)

    def test_database_payload_tampering_is_detected(self):
        self.save()
        with self.store.db:
            self.store.db.execute("UPDATE cases SET payload=replace(payload, 'true', 'false')")
        with self.assertRaisesRegex(ValueError, 'checksum changed'):
            self.store.load(self.requests)

    def test_unknown_case_cannot_be_reused(self):
        self.save()
        with self.assertRaisesRegex(ValueError, 'Unplanned'):
            self.store.load({'baseline': {}, 'candidate': {}})

    def test_conflicting_mirror_is_preserved(self):
        self.save()
        folder = self.root / 'baseline'
        folder.mkdir()
        path = folder / (digest(b'case-1')[:20] + '.json')
        path.write_text('owner modified evidence')
        with self.assertRaisesRegex(ValueError, 'preserved for review'):
            self.store.export(self.root)
        self.assertEqual(path.read_text(), 'owner modified evidence')

    def test_incomplete_or_invalid_result_is_not_checkpointed(self):
        for key, value in [('grading', {'correct': 1}), ('seconds', float('nan')),
                           ('seconds', -1), ('tokens', 32769), ('tokens', True),
                           ('finish', 'interrupted'), ('id', 'wrong')]:
            with self.subTest(field=key, value=value):
                result = dict(self.result, **{key: value})
                with self.assertRaises(ValueError):
                    self.store.save('baseline', 'case-1', self.request, result)
        self.assertEqual(self.store.load(self.requests), {'baseline': {}, 'candidate': {}})

    def test_original_and_edited_results_remain_separate(self):
        self.save()
        changed = dict(self.result, grading={'correct': False}, text='wrong')
        self.store.save('candidate', 'case-1', self.request, changed)
        self.reopen()
        rows = self.store.load(self.requests)
        self.assertTrue(rows['baseline']['case-1']['grading']['correct'])
        self.assertFalse(rows['candidate']['case-1']['grading']['correct'])

    def test_create_cannot_replace_an_existing_store(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        with self.assertRaisesRegex(ValueError, 'creation/resume'):
            CaseStore(self.path, self.frozen, create=True)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
