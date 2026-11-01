"""Regression source for the implementation-only patch; not run during gaming."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ControlCenter'), str(ROOT / 'Agent')]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / 'Agent').mkdir()
        (self.root / 'Agent/hardware_profiles.json').write_text(json.dumps({'storage': {
            'minimum_free_gib': 1, 'minimum_free_fraction': .0001, 'output_reserve_gib': 0}}))
        from profile_context import CapturedProfile
        def safe(value):
            target = (self.root / value).resolve()
            if not target.is_relative_to(self.root): raise PermissionError('Outside fixture')
            return target
        self.runtime = SimpleNamespace(root=self.root, safe_path=safe, _account_role=lambda: 'admin',
                                       profile=CapturedProfile(self.root), _cancel_epoch=0)


class VerificationTests(Fixture):
    def test_json_predicate_and_changed_file_invalidate_receipt(self):
        from result_verification import Verifications
        path = self.root / 'result.json'; path.write_text('{"count":3,"ready":true}')
        verifier = Verifications(self.runtime)
        row = verifier.run([{'kind': 'json_value', 'path': str(path), 'pointer': ['count'], 'expected': 3}])
        self.assertTrue(row['success']); self.assertTrue(verifier.read(row['id'], fresh=True)['success'])
        path.write_text('{"count":4}')
        with self.assertRaisesRegex(ValueError, 'changed'): verifier.read(row['id'], fresh=True)

    def test_duplicate_keys_and_syntax_fail_without_execution(self):
        from result_verification import Verifications
        path = self.root / 'bad.json'; path.write_text('{"x":1,"x":2}')
        row = Verifications(self.runtime).run([{'kind': 'file', 'path': str(path)}])
        self.assertFalse(row['success']); self.assertIn('Duplicate', row['results'][0]['error'])
        code = self.root / 'program.py'; code.write_text('raise RuntimeError("must not execute")\n')
        self.assertTrue(Verifications(self.runtime).run([{'kind': 'file', 'path': str(code)}])['success'])

    def test_nested_json_boolean_is_not_integer(self):
        from result_verification import Verifications
        path = self.root / 'result.json'; path.write_text('{"ok":[true]}')
        self.assertFalse(Verifications(self.runtime).run([{'kind': 'json_value', 'path': str(path), 'expected': {'ok': [1]}}])['success'])

    def test_final_audit_detects_file_change_and_uncertain_dispatch(self):
        from result_verification import begin_request, after_write, completion_audit
        chat = SimpleNamespace(tool_runtime=self.runtime, _check_login=lambda: None, cancel_event=threading.Event(),
                               session={'messages': [{'role': 'user', 'content': 'Write file'}]})
        path = self.root / 'ok.py'; path.write_text('x = 1\n'); begin_request(self.runtime)
        after_write(self.runtime, path, None); path.write_text('x = 2\n')
        self.assertFalse(completion_audit(chat)[1])
        begin_request(self.runtime)
        chat.session['messages'].append({'role': 'tool', 'execution': {'dispatched': True, 'effectful': True, 'outcome': 'uncertain'}})
        self.assertIn('uncertain', completion_audit(chat)[0])
        chat.session['messages'][-1]['execution']['effectful']=False
        self.assertTrue(completion_audit(chat)[1])


class ProjectTests(Fixture):
    def test_conflicting_undo_preserves_new_user_edit(self):
        from code_projects import write_tracked, Edits
        path = self.root / 'app.py'; path.write_bytes(b'x = 1\n')
        result = json.loads(write_tracked(self.runtime, path, 'x = 2\n', path.read_bytes()))
        path.write_bytes(b'x = 3\n')
        with self.assertRaisesRegex(ValueError, 'changed'): Edits(self.root).undo(result['undo'], self.runtime)
        self.assertEqual(path.read_bytes(), b'x = 3\n')

    def test_before_image_restores_exact_bytes_and_new_file_undo(self):
        from code_projects import write_tracked, Edits
        path = self.root / 'app.py'; before = b'x = 1\r\n'; path.write_bytes(before)
        row = json.loads(write_tracked(self.runtime, path, 'x = 2\n', before))
        self.assertTrue(Edits(self.root).undo(row['undo'], self.runtime)['success'])
        self.assertEqual(path.read_bytes(), before)
        created = self.root / 'new.py'; row = json.loads(write_tracked(self.runtime, created, 'x = 1\n', None))
        Edits(self.root).undo(row['undo'], self.runtime); self.assertFalse(created.exists())

    def test_incremental_map_excludes_dependencies_and_finds_tests(self):
        from code_projects import CodeProjects
        folder = self.root / 'project'; folder.mkdir(); (folder / 'node_modules').mkdir()
        (folder / 'core.py').write_text('def answer():\n    return 42\n')
        (folder / 'test_core.py').write_text('from core import answer\ndef test_answer():\n    assert answer() == 42\n')
        (folder / 'node_modules/skip.py').write_text('must not parse !')
        projects = CodeProjects(self.root); pid = projects.add('Example', folder)['id']
        for _ in range(10):
            if projects.scan(pid)['complete']: break
        result = projects.search(pid, 'answer')
        self.assertTrue(result['complete']); self.assertIn('test_core.py', result['suggested_tests'])
        self.assertNotIn('node_modules/skip.py', [r['file'] for r in projects.search(pid)['results']])

    def test_unapproved_test_command_cannot_execute(self):
        from code_projects import CodeProjects
        folder = self.root / 'project'; folder.mkdir(); projects = CodeProjects(self.root); pid = projects.add('Example', folder)['id']
        with patch('code_projects.subprocess.Popen') as process:
            with self.assertRaises(PermissionError): projects.run_command(pid, 'not-granted', self.runtime)
            process.assert_not_called()


class MemoryTests(unittest.TestCase):
    def test_source_chronology_not_backfill_time_and_conflict_is_visible(self):
        from memory_resolution import eligible
        memory = SimpleNamespace(chat_included=lambda _: True)
        record = {'observations': [
            {'session_id': 'new', 'source_at': 200, 'updated': 250, 'value': 'Blue'},
            {'session_id': 'old', 'source_at': 100, 'updated': 999, 'value': 'Red'}]}
        result = eligible(memory, record, '')
        self.assertTrue(result['value'].startswith('Blue')); self.assertTrue(result['conflict'])

    def test_expiry_and_supersession_do_not_revive_old_fact(self):
        from memory_resolution import eligible
        memory = SimpleNamespace(chat_included=lambda _: True)
        record = {'observations': [{'session_id': 'old', 'value': 'Old', 'superseded_at': 1},
                                   {'session_id': '__manual__', 'value': 'Temporary', 'expires_at': time.time() - 1}]}
        self.assertIsNone(eligible(memory, record, ''))

    def test_correction_rejects_stale_selection_and_retains_history(self):
        from persistent_memory import PersistentMemory
        from memory_resolution import correct
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Agent').mkdir()
            (root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':1,'minimum_free_fraction':.0001,'output_reserve_gib':0}}))
            memory = PersistentMemory(root); memory.data['facts'] = {'color': {'kind': 'preference', 'observations': [{'session_id': 'a', 'value': 'Red'}]}}
            item = memory.retained_items()[0]; correct(memory, item, 'Blue')
            with self.assertRaises(ValueError): correct(memory, item, 'Green')
            self.assertEqual(memory._eligible_observation(memory.data['facts']['color'], '')['value'], 'Blue')
            self.assertEqual(memory.data['facts']['color']['corrections'][0]['previous'], 'Red')


class RetrievalTests(unittest.TestCase):
    def test_long_tail_heading_and_table_header_survive_chunking(self):
        from retrieval_quality import chunks
        text = '# Costs\n| Item | Cost |\n| --- | --- |\n' + ''.join('| row%03d | %d |\n' % (i, i) for i in range(180))
        rows = list(chunks([('text', text)])); joined = '\n'.join(r[2] for r in rows)
        for i in range(180): self.assertIn('row%03d' % i, joined)
        self.assertTrue(all('Costs' in row[0] for row in rows))
        self.assertIn('Table header:', rows[-1][2]); self.assertIn('Item', rows[-1][2])

    def test_duplicate_suppression_and_insufficient_evidence_notice(self):
        from retrieval_quality import diverse
        rows = [{'text': 'cats are small', 'score': 1, 'semantic_similarity': .1},
                {'text': 'cats are small', 'score': .9, 'semantic_similarity': .1}]
        selected, hint = diverse(rows, 6, 'reactor temperature')
        self.assertEqual(len(selected), 1); self.assertEqual(hint['status'], 'insufficient_matches')

    def test_rebuild_retires_old_citation_and_neighbors_preserve_locations(self):
        from knowledge_base import Knowledge
        class Embeddings:
            fingerprint = 'synthetic-only'
            def encode(self, texts, check=lambda: None): return [[1., 0.] for _ in texts]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'Agent').mkdir()
            (root / 'Agent/hardware_profiles.json').write_text(json.dumps({'storage': {'minimum_free_gib': 1, 'minimum_free_fraction': .0001, 'output_reserve_gib': 0}}))
            source = root / 'docs'; source.mkdir(); (source / 'guide.md').write_text('# Heading\n' + 'A bounded source paragraph.\n' * 180)
            kb = Knowledge(root, embedder=Embeddings()); cid = kb.create('Example', source)['id']; kb.sync(cid)
            citation = kb.search('source')['results'][0]['citation']; row = kb.read(citation, neighbors=1)
            self.assertTrue(row['neighbors']); self.assertIn('Heading', row['neighbors'][0]['location'])
            with self.assertRaises(ValueError): kb.read(citation, neighbors=3)
            # Simulate the legacy source-hash chunk ID, then explicitly rebuild.
            import sqlite3
            key=citation.split(':',2)[2];doc,_,number=key.split(':')
            legacy=doc+':'+row['source_sha256'][:16]+':'+number
            with sqlite3.connect(kb._dbpath(cid)) as db:
                db.execute('UPDATE chunks SET id=? WHERE id=?',(legacy,key))
                db.execute('UPDATE search SET chunk=? WHERE chunk=?',(legacy,key))
            kb.sync(cid,rebuild=True)
            with self.assertRaises(ValueError):kb.read('kb:'+cid+':'+legacy)


if __name__ == '__main__': unittest.main()
