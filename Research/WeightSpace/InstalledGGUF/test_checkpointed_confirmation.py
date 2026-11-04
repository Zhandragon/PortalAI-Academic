"""Small fake-engine integration checks; never open real confirmation data."""
import argparse
import contextlib
import json
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
import checkpointed_confirmation as worker
from confirmation_store import CaseStore
from experiment import atomic_json, sha


class CheckpointedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.parent = LAB / 'checkpoint-worker-test-fixtures'
        self.parent.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=self.parent)).resolve()
        self.assertTrue(self.root.is_relative_to(self.parent.resolve()))
        self.folder = self.root / 'fixture'
        self.out = self.folder / '005-independent-confirmation'
        self.out.mkdir(parents=True)
        self.model = self.root / 'original.gguf'
        self.model.write_bytes(b'fixture original; not a model')
        self.candidate = self.out / 'candidate.gguf'
        self.candidate.write_bytes(b'fixture candidate; not a model')
        self.ids = ['fixture-' + str(i) for i in range(3)]
        self.rows = {key: {'id': key, 'problem': key, 'answer': '4', 'source': 'fake'} for key in self.ids}
        self.spec = {'sampling': {'temperature': 0.6, 'max_tokens': 32768, 'thinking': True}}
        self.frozen = {'base_sha256': sha(self.model), 'candidate_sha256': sha(self.candidate),
                       'sampling': self.spec['sampling'], 'recipe': {'fixture': True}}
        atomic_json(self.out / 'frozen.json', self.frozen)
        store = CaseStore(self.out / 'completed-cases.sqlite', sha(self.out / 'frozen.json'), create=True)
        store.close()
        self.clock = 0
        self.advance = 61
        self.generated = []
        self.leases = []
        self.released = []
        test = self

        class FakeForward:
            def __init__(self, path, **kwargs):
                self.arm = 'baseline' if path == test.model else 'candidate'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def generate(self, prompt, **kwargs):
                test.generated.append((self.arm, prompt.splitlines()[0]))
                test.clock += test.advance
                return {'text': '\\boxed{4}', 'tokens': 3, 'seconds': 1.0, 'finish': 'stop',
                        'activations': {}, 'token_ids': [1, 2, 3], 'capture_counts': {}}

        def lease(*args, **kwargs):
            value = object()
            self.leases.append(value)
            return value

        self.modules = {
            'native_forward': types.SimpleNamespace(Forward=FakeForward, metadata=lambda p: {'template': 'fake'},
                render=lambda template, messages: messages[0]['content'], item_seed=lambda key: sum(key.encode())),
            'quantized_edit': types.SimpleNamespace(materialize=lambda *args: self.fail('Fake model already exists')),
            'evaluation': types.SimpleNamespace(grade=lambda case, text: {'correct': True}),
            'service_manager': types.SimpleNamespace(acquire_gpu_lease=lease, release_gpu_lease=self.released.append)}

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(self.parent.resolve()))
        self.assertNotEqual(self.root.resolve(), self.parent.resolve())
        shutil.rmtree(self.root)

    def run_fake(self, *, resume=False, work_seconds=60):
        args = argparse.Namespace(model='fixture', resume=resume, work_seconds=work_seconds)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, self.modules))
            stack.enter_context(patch.object(worker, 'validate', return_value=(self.out, self.frozen, self.ids, self.rows)))
            stack.enter_context(patch.object(worker.time, 'monotonic', side_effect=lambda: self.clock))
            stack.enter_context(patch.object(worker.research_guard, 'LAB', self.root))
            stack.enter_context(worker.worker_lock(self.out))
            return worker.locked_worker(args, self.folder, self.out, self.model, self.spec)

    def finish(self):
        self.clock = 0
        self.advance = 0
        self.assertEqual(self.run_fake(resume=True, work_seconds=18000), 'complete')
        expected = {(arm, key) for arm in ('baseline', 'candidate') for key in self.ids}
        self.assertEqual(set(self.generated), expected)
        self.assertEqual(len(self.generated), len(expected), 'A completed inference was replayed')
        self.assertEqual(self.leases, self.released)
        self.assertFalse(self.candidate.exists())
        self.assertEqual(sha(self.model), self.frozen['base_sha256'])
        summary = json.loads((self.out / 'summary.json').read_text())
        self.assertEqual(summary['paired']['n'], 3)
        self.assertFalse(summary['production_model_changed'])
        self.assertFalse(summary['eligible_for_separate_final_benchmarks'])
        record = json.loads(next((self.out / 'baseline').glob('*.json')).read_text())
        self.assertEqual(record['text'], '\\boxed{4}')
        self.assertEqual(record['tokens'], 3)
        self.assertNotIn('token_ids', record)
        self.assertTrue(record['token_ids_omitted_from_checkpoint'])
        self.assertEqual(record['token_ids_sha256'], worker.request_digest([1, 2, 3]))

    def test_checkpoint_then_resume_skips_completed_cases_and_accounts_restart(self):
        self.assertEqual(self.run_fake(), 'checkpointed')
        self.assertEqual(self.generated, [('baseline', self.ids[0])])
        self.assertEqual(self.leases, self.released)
        self.finish()
        with contextlib.closing(sqlite3.connect(self.folder / 'ledger.sqlite')) as db:
            rows = db.execute("SELECT status FROM runs WHERE phase='confirmation'").fetchall()
        self.assertEqual(rows.count(('interrupted',)), 1)
        self.assertEqual(rows.count(('complete',)), 2)

    def test_committed_case_survives_export_failure_and_dead_owner_reconciliation(self):
        original = CaseStore.export
        failed = []

        def crash_after_commit(store, destination, *, only=None):
            if only and not failed:
                failed.append(only)
                raise RuntimeError('simulated crash after committed result')
            return original(store, destination, only=only)

        with patch.object(CaseStore, 'export', crash_after_commit):
            with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
                self.run_fake()
        self.assertEqual(self.generated, [('baseline', self.ids[0])])
        # Simulate the state of an abruptly terminated process, which could not
        # mark its scientific pass interrupted. The request and case persist.
        with contextlib.closing(sqlite3.connect(self.folder / 'ledger.sqlite')) as db:
            with db:
                db.execute("UPDATE runs SET status='running' WHERE phase='confirmation'")
        self.finish()
        with contextlib.closing(sqlite3.connect(self.folder / 'ledger.sqlite')) as db:
            evidence = json.loads(db.execute("SELECT evidence FROM runs WHERE status='interrupted'").fetchone()[0])
        self.assertTrue(evidence['interrupted_owner_reconciled_under_exclusive_lock'])

    def test_changed_request_stops_before_loading_another_model(self):
        self.assertEqual(self.run_fake(), 'checkpointed')
        self.rows[self.ids[0]]['problem'] = 'changed after checkpoint'
        with self.assertRaisesRegex(ValueError, 'prompt, seed, model, or sampling changed'):
            self.run_fake(resume=True)
        self.assertEqual(len(self.leases), 1)
        self.assertTrue(self.candidate.exists())

    def test_manual_pause_prevents_start_before_data_or_model_access(self):
        (self.root / 'GPU-PAUSED.json').write_text('{}')
        with patch.object(worker.research_guard, 'LAB', self.root):
            with self.assertRaises(worker.research_guard.ResearchPaused):
                worker.run_worker(argparse.Namespace(model='fixture', resume=False, work_seconds=60))
        self.assertEqual(self.generated, [])

    def test_second_worker_cannot_claim_same_experiment(self):
        with worker.worker_lock(self.out):
            with self.assertRaisesRegex(RuntimeError, 'Another confirmation worker'):
                with worker.worker_lock(self.out):
                    self.fail('Second worker entered the locked phase')


if __name__ == '__main__':
    unittest.main(verbosity=2)
