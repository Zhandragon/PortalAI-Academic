"""Observed dispatcher navigation using unrelated synthetic features."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('ControlCenter','Agent','Tools')]
from source_routes import tool_entrypoint,references
from source_map import source_map
from source_evidence import project_source


class RouteTests(unittest.TestCase):
    def fixture(self,root):
        for folder in ('Agent','ControlCenter','Tools','Documentation','Private'):(root/folder).mkdir()
        code='''class LiveRuntime:
    def execute(self,name,args):
        if name == "archive":
            from odd_codec import Extractor
            raise RuntimeError("MUST NOT EXECUTE")
        if name in ("read_file", "read_alias"):
            return self.read_file(args)
    def read_file(self,args):
        raise RuntimeError("MUST NOT EXECUTE")
'''
        p=root/'ControlCenter/active_runtime.py';p.write_text(code)
        namespace={};exec(compile(code,str(p),'exec'),namespace)
        rt=namespace['LiveRuntime']();rt.root=root;rt._account_role=lambda:'admin';rt._cancel_epoch=0
        (root/'Agent/odd_codec.py').write_text('raise RuntimeError("NEVER IMPORT")\nclass Extractor: pass\n')
        return rt

    def test_actual_unexpected_implementation_is_found_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rt=self.fixture(root);row=json.loads(source_map(rt,tool='archive'))
            self.assertEqual(row['items'][0]['path'],'Agent/odd_codec.py')
            self.assertEqual(row['items'][0]['symbol'],'Extractor')
            text=(root/'ControlCenter/active_runtime.py').read_text()
            self.assertIn('if name == "archive"',text[row['dispatch_offset']:row['dispatch_end_offset']])
            self.assertNotIn('odd_codec',sys.modules)

    def test_method_and_literal_alias_resolve_same_observed_method(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=self.fixture(Path(folder))
            for name in ('read_file','read_alias'):
                self.assertEqual(tool_entrypoint(rt,name)['items'][0]['symbol'],'LiveRuntime.read_file')

    def test_unknown_dynamic_tool_is_reported_without_guessed_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=self.fixture(Path(folder));row=tool_entrypoint(rt,'unknown')
            self.assertEqual(row['items'],[]);self.assertIn('not resolved',row['note'])
            self.assertEqual(row['observed_tools'],['archive','read_alias','read_file'])
            with self.assertRaises(ValueError):source_map(rt,tool='archive',query='guessed')
            with self.assertRaises(ValueError):tool_entrypoint(rt,'../Private')

    def test_large_memory_only_ast_walk_checks_role_before_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=self.fixture(Path(folder))
            import source_routes
            original=source_routes.check_cancel;count=0
            def revoke(runtime,epoch):
                nonlocal count
                count+=1
                if count==20:runtime._account_role=lambda:'guest'
                original(runtime,epoch)
            with patch('source_routes.check_cancel',side_effect=revoke),self.assertRaises(PermissionError):
                references(rt,'x=1\n'*100)

    def test_test_script_references_do_not_include_other_maintenance_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rt=self.fixture(root)
            for rel in ('Maintenance/Tests/test_packet.py','Maintenance/Validation/record.py'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('x=1')
            rows,_=references(rt,'a="Maintenance/Tests/test_packet.py"\nb="Maintenance/Validation/record.py"')
            self.assertEqual([r['path'] for r in rows],['Maintenance/Tests/test_packet.py'])

    def test_local_worker_reference_precedes_shared_imports_and_private_is_omitted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rt=self.fixture(root)
            (root/'Agent/background.py').write_text('x=1');(root/'Private/secret.py').write_text('x=2')
            rows,limited=references(rt,'import odd_codec\np="Agent/background.py"\nq="Private/secret.py"\nr="Agent/../Private/secret.py"\n')
            self.assertEqual(rows[0]['path'],'Agent/background.py')
            self.assertEqual(len(rows),2);self.assertFalse(limited)
            self.assertFalse(any('Private' in p['path'] for p in rows))

    def test_ambiguous_import_is_labeled_and_not_silently_resolved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rt=self.fixture(root)
            (root/'Tools/odd_codec.py').write_text('x=1')
            rows,_=references(rt,'import odd_codec')
            self.assertEqual(len(rows),2);self.assertTrue(all(r['ambiguous'] for r in rows))

    def test_role_and_stop_are_rechecked_before_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=self.fixture(Path(folder));rt._account_role=lambda:'guest'
            with self.assertRaises(PermissionError):tool_entrypoint(rt,'archive')
            rt._account_role=lambda:'admin'
            from source_routes import _read
            def stop(*args):
                result=_read(*args);rt._cancel_epoch+=1;return result
            for name in ('archive','unknown'):
                with patch('source_routes._read',side_effect=stop),self.assertRaisesRegex(RuntimeError,'cancelled'):
                    tool_entrypoint(rt,name)

    def test_adapter_outside_installation_falls_back_to_loaded_public_base(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rt=self.fixture(root)
            class Adapter(type(rt)):
                def execute(self,name,args):raise RuntimeError('NEVER CALL')
            rt.__class__=Adapter
            self.assertEqual(tool_entrypoint(rt,'archive')['items'][0]['path'],'Agent/odd_codec.py')

    def test_dispatch_and_worker_paths_survive_small_context_projection(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=self.fixture(Path(folder));row=tool_entrypoint(rt,'archive')
            view=json.loads(project_source({'name':'source_map','content':json.dumps(row)},5,750))
            self.assertEqual(view['items'][0]['path'],'Agent/odd_codec.py')
            self.assertEqual(view['items'][0]['symbol'],'Extractor')
            self.assertLessEqual(len(json.dumps(view,separators=(',',':'))),750)
            body='p="Agent/odd_codec.py"\nclass Receiver:\n    def receive(self): pass\n'
            (rt.root/'Agent/receiver.py').write_text(body)
            source=json.loads(source_map(rt,path='Agent/receiver.py'))
            compact=json.loads(project_source({'name':'source_map','content':json.dumps(source)},8,1000))
            self.assertEqual(compact['local_references'][0]['path'],'Agent/odd_codec.py')


if __name__=='__main__':unittest.main(verbosity=2)
