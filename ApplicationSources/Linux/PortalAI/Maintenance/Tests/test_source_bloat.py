"""An installed distribution's bundled applications are not original source."""
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Tools'))
from audit_source_bloat import audit


class SourceScope(unittest.TestCase):
    def test_vendor_trees_are_pruned_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ('Agent/original.py','Tools/KiCad/bin/vendor.py','Tools/demo/PACKAGES/vendor.py','Tools/demo/Lib/vendor.py'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('value=1\n' if name.startswith('Agent/') else 'invalid third party syntax !\n')
            report=audit(root)
            self.assertEqual(report['files'],1)
            self.assertEqual(report['largest'][0]['path'],'Agent/original.py')
            self.assertFalse(report['parse_errors'])


if __name__=='__main__':unittest.main()
