from pathlib import Path
import json,sys,tempfile,unittest
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('ControlCenter','Agent','Tools','Maintenance/Tests')]
import maintenance_tools as mt
import native_chat

class MaintenanceToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'ControlCenter').mkdir();(self.root/'Workspace').mkdir()
        self.file=self.root/'ControlCenter/example.py';self.file.write_text('def example():\n    return 2\n',encoding='utf-8')
        self.role='admin';self.checks=0
        self.rt=SimpleNamespace(root=self.root,boot=Path(sys.executable),_account_role=self.role_check,_working_directory=lambda:self.root/'Workspace')
    def role_check(self):
        self.checks+=1
        if self.role=='ended':raise PermissionError('Session ended')
        return self.role
    def test_environment_observes_paths_and_rechecks_account(self):
        facts=json.loads(mt.inspect_environment(self.rt));self.assertEqual(facts['application_root'],str(self.root));self.assertTrue(facts['python_exists']);self.assertGreaterEqual(self.checks,2)
    def test_user_and_guest_do_not_receive_admin_capabilities(self):
        for role in ('user','guest'):
            self.role=role;facts=json.loads(mt.inspect_environment(self.rt));self.assertFalse(facts['file_edit_allowed']);self.assertEqual(facts['public_source_roots'],[])
            with self.assertRaises(PermissionError):mt.source_search(self.rt,'example')
    def test_ended_account_cannot_publish_facts(self):
        self.role='ended'
        with self.assertRaises(PermissionError):mt.inspect_environment(self.rt)
    def test_source_hash_offset_and_text_match_actual_bytes(self):
        result=json.loads(mt.source_search(self.rt,'return',path='ControlCenter/example.py'))
        m=result['matches'][0];text=self.file.read_text();self.assertEqual(text[m['match_offset']:][:6],'return');self.assertEqual(m['line'],2);self.assertEqual(len(m['sha256']),64)
    def test_source_rejects_private_and_traversal_paths(self):
        for path in ('Private','../Private','ControlCenter/../../Private',str(self.file)):
            with self.assertRaises(PermissionError):mt.source_search(self.rt,'x',path)
    def test_search_does_not_execute_imports(self):
        self.file.write_text('raise RuntimeError("source-only")')
        self.assertEqual(len(json.loads(mt.source_search(self.rt,'RuntimeError'))['matches']),1)
    def test_oversized_files_are_reported_not_read(self):
        self.file.write_bytes(b'x'*(1024*1024+1));result=json.loads(mt.source_search(self.rt,'x'));self.assertEqual(result['matches'],[]);self.assertFalse(result['complete'])
    def test_scan_limits_and_literal_query(self):
        self.file.write_text('.*\n'*30);result=json.loads(mt.source_search(self.rt,'.*',limit=2));self.assertEqual(len(result['matches']),2);self.assertFalse(result['complete'])
        with self.assertRaises(ValueError):mt.source_search(self.rt,'')
    def test_qualified_symbol_resolves_exact_class_without_executing_source(self):
        self.file.write_text('raise RuntimeError("never execute")\nclass Other:\n    def example(self): pass\nclass Intended:\n    def example(self): return "é"\n',encoding='utf-8')
        result=json.loads(mt.source_search(self.rt,'Intended.example','ControlCenter/example.py'))
        self.assertEqual(len(result['matches']),1);match=result['matches'][0]
        self.assertEqual(match['match_kind'],'python_symbol');self.assertEqual(match['line'],5)
        self.assertTrue(self.file.read_text(encoding='utf-8')[match['match_offset']:].startswith('def example(self): return'))
        self.assertEqual(json.loads(mt.source_search(self.rt,'Intended.example','ControlCenter/example.py',offset=match['match_offset']+1))['matches'],[])
    def test_symbol_offsets_follow_universal_newline_character_offsets(self):
        self.file.write_bytes('# é\r\nclass Café:\r\n    async def méthode(self): pass\r\n'.encode('utf-8'))
        match=json.loads(mt.source_search(self.rt,'Café.méthode','ControlCenter/example.py'))['matches'][0]
        self.assertTrue(self.file.read_text(encoding='utf-8')[match['match_offset']:].startswith('async def méthode'))
        self.assertEqual(match['line'],3)
    def test_invalid_python_retains_literal_lookup(self):
        self.file.write_text('invalid python\nClass.method\n')
        match=json.loads(mt.source_search(self.rt,'Class.method','ControlCenter/example.py'))['matches'][0]
        self.assertEqual(match['match_kind'],'literal')
    def test_role_change_cannot_publish_previously_authorized_source_or_facts(self):
        for operation in (lambda:mt.source_search(self.rt,'example'),lambda:mt.inspect_environment(self.rt)):
            roles=iter(['admin','user','user'])
            self.rt._account_role=lambda:next(roles)
            with self.assertRaises(PermissionError):operation()
    def test_maintenance_scope_has_real_web_and_preserves_normal_menu(self):
        panel=SimpleNamespace(_request_tool_scope='maintenance')
        names={r['function']['name'] for r in native_chat._request_tools(panel)}
        self.assertTrue({'web','shell','source_search','inspect_environment','edit_file'}<=names)
        self.assertNotIn('media_tool',names)
        self.assertIs(native_chat._request_tools(SimpleNamespace()),native_chat.TOOLS)
    def test_maintenance_guide_does_not_override_custom_instructions(self):
        panel=SimpleNamespace(_request_tool_scope='maintenance',settings={'use_master_instructions':False},root=self.root,store=SimpleNamespace(custom_instructions=lambda:'CUSTOM TASK CONSTRAINT'))
        text=native_chat.NativeChat.system_prompt(panel);self.assertIn('CUSTOM TASK CONSTRAINT',text);self.assertIn('base-hash',text);self.assertLess(len(text),1800)

if __name__=='__main__':unittest.main()
