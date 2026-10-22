import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('profile_routing_audit',ROOT/'Tools/audit_profile_routing.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class StaticAudit(unittest.TestCase):
    def test_catalogs_unrouted_writer_without_executing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'Agent/example.py';path.parent.mkdir()
            path.write_text("raise RuntimeError('never execute this module')\n(root/'Outputs'/'Science'/'result.txt').write_text('synthetic')\nprivate_path(root,'Outputs/Science/result.txt').write_text('synthetic')\n")
            result=audit.audit(root)
            findings=result['files'][0]['findings']
            self.assertEqual([x['line'] for x in findings if x['kind']=='unrouted-private-literal'],[2])
            self.assertEqual(result['io_operation_count'],2)
            self.assertFalse(result['errors'])

    def test_skips_runtime_data_and_reports_syntax_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'Agent/.runtime';runtime.mkdir(parents=True)
            (runtime/'private.py').write_bytes(b'not valid source or public content')
            (root/'Agent/broken.py').write_text('def broken(:')
            result=audit.audit(root)
            self.assertEqual(result['scanned_files'],0)
            self.assertEqual(result['errors'],[{'path':'Agent/broken.py','error':'SyntaxError'}])


if __name__=='__main__':unittest.main()
