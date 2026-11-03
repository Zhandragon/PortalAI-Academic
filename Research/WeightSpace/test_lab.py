import json,sys,tempfile,unittest
from pathlib import Path
LAB=Path(__file__).parent;sys.path.insert(0,str(LAB))
import sparse_edit as edit
import benchmark
np=edit.np
class AlgebraTests(unittest.TestCase):
    def test_sparse_update_matches_dense_formula_and_preserves_other_columns(self):
        rng=np.random.default_rng(7);w=rng.normal(size=(32,128)).astype(np.float32);u=rng.normal(size=32).astype(np.float32);u/=np.linalg.norm(u)
        a,b,cols=edit.factors(w,u,8,2)
        delta=b@a;expected=np.zeros_like(w);expected[:,cols]=-2*np.outer(u,u@w[:,cols])
        np.testing.assert_allclose(delta,expected,atol=2e-6)
        self.assertEqual(np.count_nonzero(np.any(delta!=0,axis=0)),8)
        x=rng.normal(size=128).astype(np.float32)
        np.testing.assert_allclose((w+delta)@x,w@x+b@(a@x),atol=1e-5)
    def test_control_is_orthogonal_with_same_norm_and_support(self):
        rng=np.random.default_rng(8);w=rng.normal(size=(16,96)).astype(np.float32);u=np.ones(16,dtype=np.float32)/4
        a,b,_=edit.factors(w,u,8,1);ca,cb=edit.random_control(a,b,u,4)
        self.assertLess(abs(float(u@cb[:,0])),1e-6)
        np.testing.assert_allclose(np.linalg.norm(a)*np.linalg.norm(b),np.linalg.norm(ca)*np.linalg.norm(cb),rtol=1e-6)
        np.testing.assert_array_equal(a,ca)
    def test_invalid_captures_and_direction_rejected(self):
        with self.assertRaises(ValueError):edit.direction(np.zeros((3,10)),np.ones((3,10)))
        with self.assertRaises(ValueError):edit.direction(np.zeros((4,10)),np.zeros((4,10)))
        with self.assertRaises(ValueError):edit.factors(np.ones((10,20)),np.ones(10),4,1)
        with self.assertRaises(ValueError):edit.factors(np.ones((10,20)),np.ones(10)/np.sqrt(10),4,100)
    def test_adapter_roundtrip_and_original_bytes_untouched(self):
        with tempfile.TemporaryDirectory(dir=LAB) as folder:
            path=Path(folder)/'candidate.gguf';a=np.ones((1,64),np.float32);b=np.ones((32,1),np.float32)
            record=edit.save_adapter(path,'qwen3',[('blk.3.ffn_down.weight',a,b)],{})
            self.assertFalse(record['installed']);reader=edit.gguf.GGUFReader(str(path),'r')
            self.assertEqual(reader.fields['general.type'].contents(),'adapter');self.assertEqual(len(reader.tensors),2)
            np.testing.assert_array_equal(reader.tensors[0].data,a);del reader
            with self.assertRaises(FileExistsError):edit.save_adapter(path,'qwen3',[],{})
    def test_selection_and_holdout_have_distinct_ids_and_prompts(self):
        left=benchmark.cases('selection');right=benchmark.cases('heldout')
        self.assertFalse({c['id'] for c in left}&{c['id'] for c in right})
        self.assertFalse({c['prompt'] for c in left}&{c['prompt'] for c in right})
        self.assertEqual({c['area'] for c in left},{'math','coding','tool_use','reasoning'})
    def test_loop_detector_does_not_confuse_long_unique_work_with_loop(self):
        self.assertFalse(benchmark.loop_metrics(' '.join(str(i) for i in range(2048)))['repetition_suspected'])
        self.assertTrue(benchmark.loop_metrics('Let me check the same calculation once again. '*100)['repetition_suspected'])
        self.assertFalse(benchmark.loop_metrics('short short short')['repetition_suspected'])
    def test_code_grader_accepts_valid_helpers_and_rejects_wrong_or_mutating_code(self):
        case=benchmark.cases('selection')[3]
        for code,expected in [('def solve(xs):\n return list(dict.fromkeys(xs))',True),('def solve(xs):\n out=[]\n for x in xs:\n  if x not in out: out.append(x)\n return out',True),('def helper(xs):\n return []\ndef solve(xs):\n return helper(xs)',False),('def solve(xs):\n xs.clear()\n return []',False)]:
            passed,_=benchmark.score(case,{'content':code},LAB);self.assertEqual(passed,expected)
    def test_code_grader_blocks_host_io_and_dunder_access(self):
        case=benchmark.cases('selection')[3]
        for code in ('import os\ndef solve(xs):\n return []','def solve(xs):\n return open("file.txt").read()','def solve(xs):\n return xs.__class__'):
            passed,_=benchmark.score(case,{'content':code},LAB);self.assertFalse(passed)
    def test_code_grader_terminates_nonterminating_function(self):
        case=benchmark.cases('selection')[3]
        passed,detail=benchmark.score(case,{'content':'def solve(xs):\n while True: pass'},LAB)
        self.assertFalse(passed);self.assertIn('timed out',detail['reason'])
if __name__=='__main__':unittest.main(verbosity=2)
