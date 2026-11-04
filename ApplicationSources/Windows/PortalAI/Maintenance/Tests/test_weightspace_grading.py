"""A non-terminating model answer must not abort independent comparisons."""
import subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools/WeightSpace'))
import evaluation

class WeightSpaceGradingTests(unittest.TestCase):
    def test_infinite_model_answer_is_wrong_and_worker_stops(self):
        workers=[];original=subprocess.Popen
        def spawn(*args,**kwargs):
            worker=original(*args,**kwargs);workers.append(worker);return worker
        with patch.object(evaluation.subprocess,'Popen',side_effect=spawn):
            result=evaluation.grade({'kind':'coding','checks':[[[],1]]},'def solve():\n    while True:\n        pass')
        self.assertFalse(result['correct']);self.assertTrue(result['detail']['timed_out'])
        self.assertEqual(len(workers),1);self.assertIsNotNone(workers[0].poll())
        self.assertTrue(evaluation.grade({'kind':'coding','checks':[[[],1]]},'def solve():\n    return 1')['correct'])
    def test_infrastructure_errors_remain_errors(self):
        for error in (RuntimeError('grader failed'),ValueError('invalid response'),OSError('launch failed')):
            with self.subTest(error=type(error).__name__),patch.object(evaluation,'bounded_grader',side_effect=error):
                with self.assertRaises(type(error)):evaluation.grade({'kind':'coding','checks':[]},'def solve(): return 1')
    def test_non_coding_timeout_remains_error(self):
        with patch.object(evaluation,'bounded_grader',side_effect=subprocess.TimeoutExpired('fixture',1)):
            with self.assertRaises(subprocess.TimeoutExpired):evaluation.grade({'kind':'math','answer':'1'},'1')
    def test_ordinary_incorrect_answer_keeps_details(self):
        result=evaluation.grade({'kind':'coding','checks':[[[],1]]},'def solve():\n    return 2')
        self.assertFalse(result['correct']);self.assertFalse(result['detail'].get('timed_out',False))

if __name__=='__main__':unittest.main(verbosity=2)
