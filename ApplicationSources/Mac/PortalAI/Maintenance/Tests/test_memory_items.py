"""Selective forgetting preserves other sources and rejects stale/late writes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('ControlCenter', 'Agent')]
from native_chat import ChatStore
from persistent_memory import PersistentMemory


class MemoryItemsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.store = ChatStore(self.root)
        self.a = self.store.new_session(); self.b = self.store.new_session()
        for row in (self.a, self.b):
            row['messages'] = [{'role': 'user', 'content': 'A useful preference for this synthetic test.'}]
            self.store.save_session(row)
        self.memory = PersistentMemory(self.root)
        for row in (self.a, self.b):
            self.memory._chat_state(row['id']).update(capsule='Keep one. Remove two. Keep three.', title='Fixture', cursor=0)
        self.memory.data['facts'] = {'preference.test': {'kind': 'preference', 'observations': [
            {'session_id': self.a['id'], 'value': 'Keep blue, remove red.', 'importance': 4},
            {'session_id': self.b['id'], 'value': 'Keep green.', 'importance': 4}]}}
        self.memory.save()

    def item(self, kind): return next(i for i in self.memory.retained_items() if i['kind'] == kind)

    def test_one_observation_deleted_others_and_raw_chat_preserved(self):
        before = (self.store.sessions/f'{self.a["id"]}.json').read_bytes()
        self.memory.delete_retained(self.item('fact'), self.store.list_sessions())
        obs = self.memory.data['facts']['preference.test']['observations']
        self.assertEqual([o['value'] for o in obs], ['Keep green.'])
        self.assertEqual(self.memory._chat_state(self.a['id'])['cursor'], 1)
        self.assertEqual((self.store.sessions/f'{self.a["id"]}.json').read_bytes(), before)
        self.assertEqual(self.memory._chat_state(self.b['id'])['cursor'], 0)

    def test_exact_capsule_fragment_and_fact_fragment_preserve_other_text(self):
        for kind, fragment in (('capsule', 'Remove two. '), ('fact', 'remove red.')):
            item = self.item(kind); start = item['text'].index(fragment)
            self.memory.delete_retained(item, self.store.list_sessions(), span=(start, start+len(fragment)))
            remaining = next(i for i in self.memory.retained_items() if i['kind'] == kind and i['key'] == item['key'])
            self.assertNotIn(fragment.strip(), remaining['text'])
            self.assertIn('Keep', remaining['text'])

    def test_stale_selection_refused_instead_of_deleting_changed_observation(self):
        item = self.item('fact')
        self.memory.data['facts']['preference.test']['observations'][0]['value'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'Refresh'): self.memory.delete_retained(item, self.store.list_sessions())
        self.assertEqual(self.memory.data['facts']['preference.test']['observations'][0]['value'], 'Changed')

    def test_failed_save_restores_in_memory_state(self):
        before = copy.deepcopy(self.memory.data)
        with patch.object(self.memory, 'save', side_effect=OSError('drive disconnected')):
            with self.assertRaises(OSError): self.memory.delete_retained(self.item('fact'), self.store.list_sessions())
        self.assertEqual(self.memory.data, before)

    def test_inflight_distillation_cannot_restore_deleted_fact(self):
        entered, release = threading.Event(), threading.Event(); results = []
        def complete(*args, **kwargs):
            entered.set(); self.assertTrue(release.wait(4))
            return json.dumps({'capsule': 'Old summary', 'upserts': [
                {'key': 'preference.test', 'value': 'Resurrected', 'kind': 'preference'}]})
        with patch.object(self.memory, '_complete', side_effect=complete):
            thread = threading.Thread(target=lambda: results.append(self.memory.distill_session(self.a)))
            thread.start(); self.assertTrue(entered.wait(4))
            try: self.memory.delete_retained(self.item('fact'), self.store.list_sessions())
            finally: release.set(); thread.join(4)
        self.assertFalse(thread.is_alive()); self.assertFalse(results[0]['updated'])
        self.assertEqual([o['value'] for o in self.memory.data['facts']['preference.test']['observations']], ['Keep green.'])

    def test_fact_suppression_survives_rebuild_without_excluding_other_facts(self):
        self.memory.delete_retained(self.item('fact'), self.store.list_sessions())
        self.assertTrue(self.memory.chat_included(self.a['id']))
        self.memory.rebuild_included(self.store.list_sessions())
        answer = {'capsule': 'Fresh summary', 'upserts': [
            {'key': 'preference.test', 'value': 'Must remain blocked'},
            {'key': 'other.fact', 'value': 'Allowed new fact'}]}
        with patch.object(self.memory, '_complete', return_value=json.dumps(answer)):
            self.memory.distill_session(self.a)
        self.assertNotIn('preference.test', self.memory.data['facts'])
        self.assertIn('other.fact', self.memory.data['facts'])
        block = self.memory.blocked_items()[0]
        self.memory.allow_item(block['block_id']); self.memory.reset_chat(self.a['id'])
        with patch.object(self.memory, '_complete', return_value=json.dumps(answer)):
            self.memory.distill_session(self.a)
        self.assertIn('preference.test', self.memory.data['facts'])

    def test_bulk_contribution_and_rebuild_respect_excluded_chats(self):
        self.memory.set_chats_included([self.a['id'], self.b['id']], False)
        self.assertFalse(self.memory.chat_included(self.a['id']))
        self.memory.set_chats_included([self.a['id']], True)
        excluded = copy.deepcopy(self.memory._chat_state(self.b['id']))
        self.assertEqual(self.memory.rebuild_included(self.store.list_sessions()), 1)
        self.assertEqual(self.memory._chat_state(self.b['id']), excluded)
        self.assertEqual([o['session_id'] for o in self.memory.data['facts']['preference.test']['observations']], [self.b['id']])

    def test_staged_rebuild_failure_preserves_original(self):
        before = copy.deepcopy(self.memory.data)
        with patch.object(self.memory, '_complete', side_effect=[json.dumps({'capsule':'New','upserts':[]}), OSError('disconnected')]):
            with self.assertRaises(OSError): self.memory.regenerate_included(self.store, threading.Event())
        self.assertEqual(self.memory.data, before)

    def test_staged_rebuild_stop_and_concurrent_edit_refuse_commit(self):
        for edit in (False, True):
            cancel = threading.Event()
            def complete(*args, **kwargs):
                if edit: self.memory.set_chat_included(self.b['id'], False)
                else: cancel.set()
                return json.dumps({'capsule':'New','upserts':[]})
            with patch.object(self.memory, '_complete', side_effect=complete):
                with self.assertRaises(RuntimeError): self.memory.regenerate_included(self.store, cancel)
            self.assertEqual(self.memory._chat_state(self.a['id'])['capsule'], 'Keep one. Remove two. Keep three.')

    def test_staged_rebuild_success_preserves_excluded(self):
        self.memory.set_chat_included(self.b['id'], False)
        before = copy.deepcopy(self.memory._chat_state(self.b['id']))
        with patch.object(self.memory, '_complete', return_value=json.dumps({'capsule':'Fresh','upserts':[]})) as inference:
            result = self.memory.regenerate_included(self.store, threading.Event())
        self.assertEqual(inference.call_count, 1)
        self.assertEqual(result['rebuilt_chats'], 1)
        self.assertEqual(self.memory._chat_state(self.a['id'])['capsule'], 'Fresh')
        self.assertEqual(self.memory._chat_state(self.b['id']), before)

    def test_clear_all_can_exclude_actual_source_chats_preserving_other_settings(self):
        extra = self.store.new_session()
        self.memory.set_chat_recall_enabled(self.a['id'], False)
        self.memory.clear_for_sessions(self.store.list_sessions(), exclude_sources=True)
        self.assertFalse(self.memory.chat_included(self.a['id']))
        self.assertFalse(self.memory.chat_included(self.b['id']))
        self.assertTrue(self.memory.chat_included(extra['id']))
        self.assertFalse(self.memory.chat_recall_enabled(self.a['id']))
        self.assertEqual(self.memory.stats()['facts'], 0)


if __name__ == '__main__': unittest.main()
