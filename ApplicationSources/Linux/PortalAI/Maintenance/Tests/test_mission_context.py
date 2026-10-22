import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
from mission_runner import Missions, MissionContextError
from mission_context import build_messages, rolling_index, history_page, Budget


def tokenizer(path, payload):
    if path == '/apply-template': return {'prompt': json.dumps(payload['messages'], ensure_ascii=False)}
    return {'tokens': [1]*((len(payload['content'].encode())+2)//3)}


class MissionContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store = Missions(Path(temp.name))
        (self.store.root/'Agent').mkdir()
        (self.store.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage': {
            'minimum_free_gib': 0, 'minimum_free_fraction': 0, 'output_reserve_gib': 0}}))
        self.m = self.store.create('Preserve EXACT constraints and investigate experiment ZX-731.', max_steps=100)
        self.m['history'] = [{'action': {'action': 'note', 'text': f'Experiment ZX-731 step {i} '+('界'*500)},
                              'result': 'Record saved '+str(i), 'at': i} for i in range(80)]
        self.m['steps'] = 80

    def test_compaction_preserves_full_disk_evidence_and_authoritative_state(self):
        before = copy.deepcopy(self.m)
        messages = build_messages(self.store, self.m, 'Worker rules', [], 'notes'*5000, 2048, tokenizer)
        context = json.loads(messages[1]['content'])
        self.assertEqual(context['objective'], self.m['objective'])
        self.assertEqual(context['mode'], 'observe')
        self.assertEqual(context['completed_records'], 80)
        self.assertTrue(context['context_compacted'])
        self.assertEqual(self.m, before)
        status = json.loads((self.store.folder(self.m['id'])/'context-status.json').read_text())
        self.assertLessEqual(status['input_tokens_or_upper_bound']+768+256, 2048)
        self.assertEqual(status['through'], 76)

    def test_restart_reuses_index_and_changed_history_rebuilds_it(self):
        one = rolling_index(self.store, self.m)
        two = rolling_index(Missions(self.store.root), self.m)
        self.assertEqual(one, two)
        self.m['history'][0]['result'] = 'Corrected user review'
        three = rolling_index(self.store, self.m)
        self.assertNotEqual(one['source_sha256'], three['source_sha256'])
        self.assertIn('Corrected', three['records'][0]['result'])

    def test_damaged_summary_is_rebuilt_not_used_as_execution_state(self):
        index = rolling_index(self.store, self.m)
        index['records'][0]['result'] = 'invented completion'
        p = self.store.folder(self.m['id'])/'context.json'
        p.write_text(json.dumps(index))
        self.assertNotIn('invented', rolling_index(self.store, self.m)['records'][0]['result'])

    def test_oversized_objective_and_child_state_fail_without_truncation(self):
        self.m['objective'] = 'X'*10000
        with self.assertRaises(MissionContextError):
            build_messages(self.store, self.m, 'rules', [], '', 2048, tokenizer)

    def test_unavailable_tokenizer_uses_conservative_budget(self):
        def missing(*_): raise OSError('old server')
        messages = build_messages(self.store, self.m, 'rules', [], '', 4096, missing)
        budget = Budget(4096, missing)
        self.assertLessEqual(budget.count(messages), budget.limit)
        self.assertEqual(budget.method, 'conservative-utf8-bytes')

    def test_history_is_local_and_never_executes_old_action(self):
        self.m['history'][0] = {'action': {'action': 'shell', 'command': 'old-effect'}, 'result': 'already ran'}
        with patch.object(self.store, 'model_action') as model:
            row = json.loads(self.store.execute(self.m, {'action': 'history', 'start': 1, 'count': 1, 'mission': 'another'}))
        model.assert_not_called()
        self.assertEqual(row['records'][0]['action']['command'], 'old-effect')
        self.assertEqual(row['records'][0]['step'], 1)
        for start, count in ((0,1),(1,5),('1',1),(True,1)):
            with self.assertRaises(ValueError): history_page(self.m, start, count)

    def test_pending_effect_and_stop_still_prevent_planning(self):
        self.m['pending_action'] = {'action': 'note', 'text': 'uncertain'}
        self.store.save(self.m)
        with patch('mission_context.build_messages') as compact:
            result = self.store.run(self.m['id'])
        compact.assert_not_called()
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['pending_action'], self.m['pending_action'])


if __name__ == '__main__': unittest.main()
