"""Direct edit invariants, admission, evidence gates and durable pass accounting."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];ENGINE=ROOT/'Tools/WeightSpace';sys.path.insert(0,str(ENGINE))
from quantized_edit import Quantizer,gguf,np,materialize,sha,inventory,projection
from experiment import Ledger,paired_summary,promotion_gate

class WeightSpaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'Maintenance');self.folder=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def model(self,kind):
        path=self.folder/(kind.name+'.gguf');rng=np.random.default_rng(527)
        w=rng.normal(0,.1,(32,512)).astype(np.float32);encoder=Quantizer();raw=encoder.blocks(w,kind).reshape(32,-1)
        writer=gguf.GGUFWriter(str(path),arch='qwen3');writer.add_tensor('blk.0.ffn_down.weight',raw,raw_dtype=kind)
        writer.add_tensor('output_norm.weight',np.ones(32,dtype=np.float32))
        writer.write_header_to_file();writer.write_kv_data_to_file();writer.write_tensors_to_file();writer.close()
        u=rng.normal(size=32).astype(np.float32);u/=np.linalg.norm(u)
        site=projection(path,'blk.0.ffn_down.weight',u,columns=8)
        return path,{'base_sha256':sha(path),'method':'sparse-projection-subtraction-v1','dose':.5,'sites':[site]}
    def check_quantization(self,kind):
        model,recipe=self.model(kind);before=model.read_bytes();out=self.folder/'edited.gguf'
        receipt=materialize(model,recipe,out)
        self.assertEqual(before,model.read_bytes());self.assertNotEqual(sha(out),sha(model));self.assertEqual(out.stat().st_size,len(before))
        old=gguf.GGUFReader(str(model));new=gguf.GGUFReader(str(out));block,encoded=gguf.GGML_QUANT_SIZES[kind]
        edited=set(np.asarray(recipe['sites'][0]['columns'])//block)
        for a,b in zip(old.tensors,new.tensors):
            self.assertEqual(a.name,b.name);self.assertEqual(a.tensor_type,b.tensor_type)
            if a.name!='blk.0.ffn_down.weight':self.assertTrue(np.array_equal(a.data,b.data));continue
            ar=a.data.reshape(32,-1,encoded);br=b.data.reshape(32,-1,encoded)
            for i in set(range(512//block))-edited:self.assertTrue(np.array_equal(ar[:,i],br[:,i]))
        self.assertLess(receipt['sites'][0]['actual_relative_delta'],.15)
        del old,new,a,b,ar,br
    def test_q8_direct_edit_preserves_untouched_blocks(self):self.check_quantization(gguf.GGMLQuantizationType.Q8_0)
    def test_q4_direct_edit_preserves_untouched_blocks(self):self.check_quantization(gguf.GGMLQuantizationType.Q4_K)
    def test_zero_dose_exact_noop(self):
        model,recipe=self.model(gguf.GGMLQuantizationType.Q8_0);recipe['dose']=0
        out=self.folder/'zero.gguf';materialize(model,recipe,out);self.assertEqual(sha(model),sha(out))
    def test_model_mismatch_and_overwrite_refused(self):
        model,recipe=self.model(gguf.GGMLQuantizationType.Q8_0)
        with self.assertRaises(FileExistsError):materialize(model,recipe,model)
        recipe['base_sha256']='0'*64
        with self.assertRaises(ValueError):materialize(model,recipe,self.folder/'bad.gguf')
        self.assertFalse((self.folder/'bad.gguf.partial').exists())
    def test_frozen_tensor_refused(self):
        model,recipe=self.model(gguf.GGMLQuantizationType.Q8_0);recipe['sites'][0]['tensor']='output_norm.weight'
        with self.assertRaises(ValueError):materialize(model,recipe,self.folder/'bad.gguf')
    def test_nan_dose_refused(self):
        model,recipe=self.model(gguf.GGMLQuantizationType.Q8_0);recipe['dose']=float('nan')
        with self.assertRaises(ValueError):materialize(model,recipe,self.folder/'bad.gguf')
    def test_ledger_replay_and_crash_are_explicit(self):
        db=self.folder/'passes.sqlite';ledger=Ledger(db)
        self.assertTrue(ledger.begin('one','discovery',{'a':1}))
        with self.assertRaises(RuntimeError):ledger.begin('one','discovery',{'a':1})
        ledger.end('one',{'passed':True});ledger.close();ledger=Ledger(db)
        self.assertFalse(ledger.begin('one','discovery',{'a':1}))
        with self.assertRaises(RuntimeError):ledger.begin('one','discovery',{'a':2})
        ledger.close()
    def test_fifty_pass_budget(self):
        ledger=Ledger(self.folder/'passes.sqlite')
        for i in range(50):ledger.begin(str(i),'discovery',{'case':i});ledger.end(str(i),{})
        with self.assertRaises(RuntimeError):ledger.begin('overflow','discovery',{})
        with self.assertRaises(RuntimeError):ledger.begin('confirmation-overflow','confirmation',{})
        ledger.close()
    def test_no_promotion_for_tie_or_missing_domains(self):
        base={str(i):True for i in range(1152)};summary=paired_summary(base,base)
        self.assertFalse(promotion_gate(summary,{},latency_ratio=1)['eligible'])
    def test_pairing_is_by_id_not_order(self):
        result=paired_summary({'a':False,'b':True},{'b':False,'a':True})
        self.assertEqual(result['gain'],0);self.assertEqual(result['rescues'],1);self.assertEqual(result['regressions'],1)
    def test_original_math_grader_equivalence_and_missing_answer(self):
        from evaluation import grade
        case={'kind':'math','answer':'1/2'}
        self.assertTrue(grade(case,r'\boxed{\frac{1}{2}}')['correct'])
        self.assertFalse(grade(case,r'\boxed{\frac{1}{3}}')['correct'])
        self.assertFalse(grade(case,'<think>I am still working')['correct'])
    def test_code_grader_disallows_imports_and_mutation(self):
        from evaluation import grade
        case={'kind':'coding','checks':[[[[1,2]],[2,1]]]}
        self.assertTrue(grade(case,'def solve(xs):\n    return list(reversed(xs))')['correct'])
        self.assertFalse(grade(case,'import os\ndef solve(xs):\n    return list(reversed(xs))')['correct'])
        self.assertFalse(grade(case,'def solve(xs):\n    xs.reverse()\n    return xs')['correct'])
    def test_gui_minimum_width_controls_fit_and_campaign_persists(self):
        import tkinter as tk
        from ui import Editor
        app=tk.Tk();app.geometry('+10000+10000')
        try:
            editor=Editor(app,self.folder);app.geometry('720x560+10000+10000');app.update()
            for button in editor.buttons:
                self.assertGreater(button.winfo_width(),30)
                self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),app.winfo_rootx()+app.winfo_width())
            editor.reset_campaign();saved=editor.campaign
            self.assertEqual(json.loads((self.folder/'campaign.json').read_text())['id'],saved)
        finally:app.destroy()
    def test_owned_worker_cancel_does_not_leave_child(self):
        import ctypes,threading,time
        from run_owned import run
        script=self.folder/'waiting.py';pidfile=self.folder/'pid.txt'
        script.write_text('import sys,os,time\nif sys.stdin.readline().strip()!=\"start\":raise SystemExit(1)\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(str(os.getpid()))\nwhile True:time.sleep(.05)\n')
        cancel=threading.Event();timer=threading.Timer(.5,cancel.set);timer.start()
        try:
            with self.assertRaises(InterruptedError):run(script,[pidfile],self.folder/'worker.log',timeout=5,cancel=cancel)
        finally:timer.cancel()
        pid=int(pidfile.read_text());kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x100000,False,pid)
        if handle:
            try:self.assertEqual(kernel.WaitForSingleObject(handle,0),0)
            finally:kernel.CloseHandle(handle)

if __name__=='__main__':unittest.main(verbosity=2)
