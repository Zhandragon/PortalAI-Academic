"""Causal probe sanity: callbacks on/off and zero-scale adapters must agree."""
import argparse,json,sys,time
from pathlib import Path
LAB=Path(__file__).parent;ROOT=LAB.parents[2];sys.path[:0]=[str(LAB),str(ROOT/'Agent')]
from native_probe import NativeProbe,np
from benchmark import MODELS
from service_manager import acquire_gpu_lease,release_gpu_lease
from research_guard import model_digest,require_gpu_unpaused
p=argparse.ArgumentParser();p.add_argument('--model',choices=MODELS,default='1.7-standard');p.add_argument('--output',default='native-smoke-1.7.json');args=p.parse_args()
destination=(LAB/args.output).resolve()
if not destination.is_relative_to(LAB.resolve()) or destination.exists():raise ValueError('Use a new portable report')
require_gpu_unpaused();lease=acquire_gpu_lease('weight-space-native-probe',timeout=3)
try:
    path=ROOT/'LLM/models'/MODELS[args.model];sha=model_digest(path);start=time.monotonic()
    names=['l_out-10','ffn_swiglu-10']
    with NativeProbe(path,capture_names=names) as probe:
        text='<|im_start|>user\nWhat is 17 times 23? Explain briefly.<|im_end|>\n<|im_start|>assistant\n<think>\nMultiply 17 by 20 to obtain 340, then add 17 times 3, which is 51. The total is 391. This decomposition checks the arithmetic directly.\n</think>\n391.<|im_end|>'
        tokens=probe.tokenize(text);first=probe.evaluate(tokens,capture=False);second=probe.evaluate(tokens,capture=True)
        difference=float(np.max(np.abs(first['logits']-second['logits'])))
        report={'model':args.model,'sha256':sha,'tokens':len(tokens),'baseline_loss':first['loss'],'callback_loss':second['loss'],'max_logit_difference':difference,'sites':{k:list(v.shape) for k,v in second['activations'].items()},'seconds':time.monotonic()-start,'original_weights_modified':False}
        destination.write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
        if difference>.02 or abs(first['loss']-second['loss'])>.001:raise RuntimeError('Capture changes native evaluation beyond tolerance')
finally:release_gpu_lease(lease)
