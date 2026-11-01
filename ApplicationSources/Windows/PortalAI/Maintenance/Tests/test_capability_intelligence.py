"""Regression checks for bounded capability intelligence and its lifecycle."""
import json
import os
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


class WorkspacePublicationTests(Fixture):
    @unittest.skipUnless(os.name=='nt','Windows file sharing semantics')
    def test_active_reader_does_not_lose_the_completed_record(self):
        from workspace_store import Workspace,read_json
        store=Workspace(self.root,'Publication');store.save('job.json',{'state':'running'})
        path=store.path('job.json');opened=threading.Event()
        def reader():
            with path.open('rb') as stream:
                opened.set();time.sleep(.08);stream.read()
        worker=threading.Thread(target=reader);worker.start();self.assertTrue(opened.wait(1))
        try:store.save('job.json',{'state':'complete','result':7})
        finally:worker.join(2)
        self.assertEqual(read_json(path),{'state':'complete','result':7})

    def test_revocation_during_publication_retry_prevents_late_write(self):
        from workspace_store import Workspace,read_json
        store=Workspace(self.root,'Publication');store.save('job.json',{'state':'running'})
        path=store.path('job.json')
        def fail(*args):
            store.check_callback=lambda: (_ for _ in ()).throw(RuntimeError('login ended'))
            raise PermissionError('reader holds file')
        with patch('workspace_store.atomic_json',side_effect=fail) as publish,patch('workspace_store.os',SimpleNamespace(name='nt')),patch('workspace_store.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'login ended'):store.save('job.json',{'state':'complete'})
            self.assertEqual(publish.call_count,1)
        self.assertEqual(read_json(path),{'state':'running'})


class VerificationTests(Fixture):
    def test_flat_model_check_and_legacy_batch_share_receipt_semantics(self):
        from capability_tools import dispatch
        from tool_protocol import read_only_tool_attempt
        path=self.root/'result.json';path.write_text('{"total":10}')
        spec={'kind':'json_value','path':str(path),'pointer':['total'],'expected_json':'10'}
        first=dispatch(self.runtime,'verify',{'action':'run',**spec})
        second=dispatch(self.runtime,'verify',{'action':'run','checks':[spec]})
        self.assertTrue(first['success']);self.assertTrue(second['success'])
        self.assertEqual(self.runtime._verification_receipts,[second['id']])
        self.assertTrue(read_only_tool_attempt('verify',{'action':'run',**spec},self.root))
        self.assertFalse(read_only_tool_attempt('verify',{'action':'run','kind':'test'},self.root))
        with self.assertRaises(ValueError):dispatch(self.runtime,'verify',{'action':'run','checks':[spec],**spec})

    def test_model_facing_expected_json_preserves_types_and_rejects_ambiguity(self):
        from result_verification import Verifications
        path=self.root/'result.json';path.write_text('{"items":[true,10,{"x":3}]}')
        v=Verifications(self.runtime)
        spec={'kind':'json_value','path':str(path),'pointer':['items','1'],'expected_json':'10'}
        self.assertTrue(v.run([spec])['success'])
        for changes in ({'expected':10},{'expected_json':'"10"'},{'expected_json':'NaN'},{'expected_json':'{"x":3,"x":3}'}):
            self.assertFalse(v.run([{**spec,**changes}])['success'])
        self.assertFalse(v.run([{**spec,'pointer':['items','0'],'expected_json':'1'}])['success'])
        self.assertTrue(v.run([{**spec,'pointer':['items','2'],'expected_json':'{"x":3}'}])['success'])

    def test_api_revocation_and_stop_fence_new_capabilities(self):
        from capability_tools import guard
        from unittest.mock import Mock
        self.runtime._operation_check=Mock()
        check=guard(self.runtime);check()
        self.runtime._operation_check.side_effect=PermissionError('grant revoked')
        with self.assertRaisesRegex(PermissionError,'revoked'):check()
        self.runtime._operation_check.side_effect=None
        self.runtime._cancel_epoch+=1
        with self.assertRaises(RuntimeError):check()

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
    def test_log_cleanup_waits_for_windows_handles_without_masking_timeout(self):
        from code_projects import remove_worker_log
        from unittest.mock import Mock
        path=Mock();path.unlink.side_effect=[PermissionError('child closing'),PermissionError('child closing'),None]
        with patch('code_projects.time.sleep'):
            self.assertTrue(remove_worker_log(path));self.assertEqual(path.unlink.call_count,3)
            path.unlink.side_effect=PermissionError('still locked')
            self.assertFalse(remove_worker_log(path))

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


class MenuTests(Fixture):
    def test_hidden_tk_menu_filters_routes_to_lazy_pages_and_stop_closes_worker(self):
        import tkinter as tk
        from unittest.mock import Mock
        from writer_jobs import WriterJobs
        from command_palette import install, close
        from workspace_panel import WorkspacePanel
        app=tk.Tk();app.withdraw();jobs=WriterJobs();panels=[]
        colors={'bg':'#EFE8DC','panel':'#F8F3EA','panel2':'#E9E0D2','text':'#202224','muted':'#6E665E','accent':'#3E91A2'}
        chat=SimpleNamespace(app=app,root=self.root,COL=colors,tool_runtime=self.runtime,_writer_jobs=jobs,
            _closing=False,_check_login=lambda:None,_notice=Mock(),busy=False,
            store=SimpleNamespace(profile=self.runtime.profile,catalog=SimpleNamespace(lock=threading.RLock(),rows={})))
        def workspace():
            panel=WorkspacePanel(app,self.root,colors,None,jobs,self.runtime,chat=None);panels.append(panel);return panel
        chat.open_workspace=workspace
        def pump(predicate):
            end=time.monotonic()+4
            while not predicate() and time.monotonic()<end:app.update();time.sleep(.01)
            self.assertTrue(predicate())
        try:
            install(chat);self.assertTrue(app.bind('<Control-k>'))
            chat.open_command_palette();palette=chat._command_palette
            self.assertIsNotNone(palette);palette.query.set('Calibration')
            pump(lambda:len(palette.visible)==1)
            self.assertEqual(palette.visible[0]['page'],'Calibration')
            palette.activate();self.assertIsNone(chat._command_palette)
            self.assertTrue(panels[0].pages['Calibration'].winfo_children())
            panels[0].page('Code');self.assertTrue(panels[0].pages['Code'].winfo_children())
            panels[0].close()
            chat.open_command_palette();palette=chat._command_palette
            self.runtime._cancel_epoch+=1;pump(lambda:palette.closed)
            self.assertIsNone(chat._command_palette);chat._notice.assert_not_called()
        finally:
            close(chat)
            for panel in panels:
                if panel.winfo_exists():panel.close()
            jobs.close();self.assertTrue(jobs.wait(3)['stopped']);app.destroy()


class CalibrationTests(Fixture):
    def test_only_complete_current_successful_fast_reports_can_recommend(self):
        from model_calibration import Calibration, CASES, SUITE
        from workspace_store import digest
        store=Calibration(self.root)
        row={'id':store.new_id(),'created':time.time(),'suite':SUITE,'suite_sha256':digest(CASES),
             'state':'complete','machine':'machine','models':['tiny'], 'identities':{'tiny':'identity'},
             'plans':{'tiny':{'backend':'cuda'}}, 'results':[{'model':'tiny','domain':d,'passed':True,'seconds':.5} for d,_,_,_ in CASES]}
        path='Runs/'+row['id']+'.json';store.save(path,row)
        with patch('runtime_policy.detect_hardware',return_value={}),patch('model_calibration.machine_identity',return_value='machine'),patch('model_calibration.model_identity',return_value='identity'),patch('runtime_policy.load_effective_policy',return_value={'selection':'manual-model'}):
            result=store.recommend();self.assertEqual(result['recommendation'],'tiny')
            self.assertEqual(result['current_selection'],'manual-model')
            row['state']='running';store.save(path,row)
            self.assertEqual(store.read(row['id'])['state'],'unfinished');self.assertIsNone(store.recommend()['recommendation'])
            row['state']='complete';row['created']=time.time()-91*86400;store.save(path,row)
            self.assertIsNone(store.recommend()['recommendation'])
            row['created']=time.time();row['identities']['tiny']='changed';store.save(path,row)
            self.assertIsNone(store.recommend()['recommendation'])
            row['identities']['tiny']='identity'
            for r in row['results']:r['seconds']=31
            store.save(path,row);self.assertIsNone(store.recommend()['recommendation'])
            for r in row['results']:r.update(seconds=.5,passed=False)
            store.save(path,row);self.assertIsNone(store.recommend()['recommendation'])


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
            from contextlib import closing
            with closing(sqlite3.connect(kb._dbpath(cid))) as db:
                with db:
                    db.execute('UPDATE chunks SET id=? WHERE id=?',(legacy,key))
                    db.execute('UPDATE search SET chunk=? WHERE chunk=?',(legacy,key))
            with self.assertRaisesRegex(ValueError, 'explicit manual'):
                kb.sync(cid,automatic=True,rebuild=True)
            kb.sync(cid,rebuild=True)
            with self.assertRaises(ValueError):kb.read('kb:'+cid+':'+legacy)


if __name__ == '__main__': unittest.main()
