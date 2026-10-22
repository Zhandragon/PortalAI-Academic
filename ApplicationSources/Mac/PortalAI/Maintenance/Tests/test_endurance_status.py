import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'Agent')]
import mission_endurance as endurance


class EnduranceStatusTests(unittest.TestCase):
    def test_stale_running_report_is_interrupted_without_rewriting_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'report.json'
            path.write_text(json.dumps({'status':'running','observed_seconds':60,'passed':False}))
            before=path.read_bytes();result=endurance.status(root)
            self.assertEqual(result['status'],'interrupted')
            self.assertFalse(result['controller_running'])
            self.assertFalse(result['multi_day_completed'])
            self.assertEqual(path.read_bytes(),before)

    def test_live_controller_keeps_running_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'report.json').write_text('{"status":"running"}')
            with patch.object(endurance,'process_lock',side_effect=OSError('locked')):
                result=endurance.status(root)
            self.assertTrue(result['controller_running'])
            self.assertEqual(result['status'],'running')

    def test_completed_evidence_is_not_reclassified_as_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'report.json').write_text('{"status":"complete","passed":true}')
            result=endurance.status(root)
            self.assertEqual(result['status'],'complete')
            self.assertTrue(result['passed'])


if __name__=='__main__':unittest.main()
