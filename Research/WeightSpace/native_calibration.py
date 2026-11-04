"""Causal mechanism calibration, NOT a production intelligence improvement.

Use hand-authored contrasts to validate native capture, sparse adapter algebra,
zero-scale equivalence, and dose/random controls before fitting observed loops.
No held-out task data is used or accepted-model flag written.
"""
import argparse,hashlib,json,sys,time
from pathlib import Path
LAB=Path(__file__).parent;ROOT=LAB.parents[2];sys.path[:0]=[str(LAB),str(ROOT/'Agent')]
from native_probe import NativeProbe,np
from sparse_edit import direction,factors,random_control,save_adapter,gguf
from benchmark import MODELS
from service_manager import acquire_gpu_lease,release_gpu_lease
from research_guard import require_gpu_unpaused,model_digest
p=argparse.ArgumentParser();p.add_argument('--model',choices=MODELS,required=True);p.add_argument('--output',required=True);a=p.parse_args()
output=(LAB/a.output).resolve()
if not output.is_relative_to(LAB.resolve()) or output.exists():raise ValueError('Use a new portable experiment directory')
spec=json.loads((LAB/'calibration_pairs.json').read_text());assert spec['split']=='selection' and len(spec['pairs'])==4
require_gpu_unpaused();lease=acquire_gpu_lease('weight-space-causal-calibration',timeout=3)
try:
    path=ROOT/'LLM/models'/MODELS[a.model];sha=model_digest(path)
    reader=gguf.GGUFReader(str(path),'r');arch=reader.fields['general.architecture'].contents()
    layers=int(reader.fields[arch+'.block_count'].contents());layers=min(64,layers)
    sites=sorted({int(layers*f) for f in (.35,.55,.75)})
    names=[name+str(layer) for layer in sites for name in ('l_out-','ffn_swiglu-')]
    output.mkdir();sequences=[];base=[];captures=[];records=[]
    with NativeProbe(path,capture_names=names) as probe:
        for pair in spec['pairs']:
            prefix='<|im_start|>user\n'+pair['prompt']+'<|im_end|>\n<|im_start|>assistant\n<think>\n'
            prefix_ids=probe.tokenize(prefix)
            ids={key:probe.tokenize(prefix+pair[key]) for key in ('productive','repetitive')}
            if any(tokens[:len(prefix_ids)]!=prefix_ids for tokens in ids.values()):raise RuntimeError('Prompt token boundary changed')
            count=min(len(v)-len(prefix_ids) for v in ids.values())
            if not 64<=count<=512:raise ValueError('Calibration branch length outside bounds')
            for key in ('productive','repetitive'):
                tokens=ids[key][:len(prefix_ids)+count]
                result=probe.evaluate(tokens,loss_from=len(prefix_ids))
                sequences.append({'id':pair['id'],'branch':key,'tokens':tokens,'loss_from':len(prefix_ids)})
                base.append(result['loss']);captures.append(result['activations'])
            print(json.dumps({'captured':pair['id'],'branch_tokens':count,'model':a.model}),flush=True)
        (output/'sequences.json').write_text(json.dumps(sequences))
        checks={}
        for layer in sites:
            tensor_name=f'blk.{layer}.ffn_down.weight'
            tensor=next(t for t in reader.tensors if t.name==tensor_name)
            residual=np.stack([v[f'l_out-{layer}'] for v in captures]);writers=np.stack([v[f'ffn_swiglu-{layer}'] for v in captures])
            u=direction(residual[::2],residual[1::2]);contrast=(writers[1::2]-writers[::2]).mean(0)
            w=gguf.quants.dequantize(tensor.data,tensor.tensor_type)
            fa,fb,columns=factors(w,u,64,1.,contrast);ca,cb=random_control(fa,fb,u,20261103)
            norm=float(np.linalg.norm(fa)*np.linalg.norm(fb)/np.linalg.norm(w));del w
            if norm>.15:raise ValueError('Perturbation limit exceeded')
            np.savez(output/f'layer-{layer}.npz',productive=residual[::2],repetitive=residual[1::2],writer_contrast=contrast)
            common={'base_model_sha256':sha,'base_model':path.name,'architecture':arch,'selection_case_ids':[x['id'] for x in spec['pairs']],'synthetic_calibration_only':True,'tensor':tensor_name,'relative_matrix_delta_at_scale_1':norm,'selected_columns':columns.tolist()}
            for label,aa,bb in [('candidate',fa,fb),('random-control',ca,cb)]:
                adapter=output/f'layer-{layer}-{label}.gguf';save_adapter(adapter,arch,[(tensor_name,aa,bb)],{**common,'control':label=='random-control'})
                for dose in (0.,.5,1.,2.):
                    if dose*norm>.15:raise ValueError('Scaled perturbation exceeds the 15% matrix limit')
                    probe.adapter(adapter,dose);losses=[]
                    for sequence in sequences:
                        result=probe.evaluate(sequence['tokens'],loss_from=sequence['loss_from'],capture=False)
                        losses.append(result['loss'])
                    delta=np.array(losses)-base
                    row={'layer':layer,'kind':label,'dose':dose,'productive_loss_change':float(delta[::2].mean()),'repetitive_loss_change':float(delta[1::2].mean()),'per_sequence_loss_change':delta.tolist()}
                    records.append(row);print(json.dumps(row),flush=True)
                    if dose==0 and np.max(np.abs(delta))>.002:raise RuntimeError('Zero-scale adapter differs from unchanged native model')
                probe.adapter()
        report={'model':a.model,'sha256':sha,'source':spec['source'],'baseline_losses':base,'records':records,'original_weights_modified':False,'accepted_for_production':False,'limitation':'Synthetic teacher-forced calibration only; not natural sampled pairs, no task accuracy or general intelligence conclusion.','capture_sha256':hashlib.sha256((LAB/'calibration_pairs.json').read_bytes()).hexdigest()}
        (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'complete':a.model,'evaluations':len(records)*len(sequences),'accepted_for_production':False}),flush=True)
finally:release_gpu_lease(lease)
