"""Stream installed Qwen3 GGUF tensors into a disposable activation probe.

Supports the installed 1.7B/4B Qwen3 architecture only. The 27B qwen35 hybrid
architecture is explicitly rejected: it requires a different activation backend.
No model downloads, runtime upgrades, gradient calculation or weight writes.
The dequantized BF16 probe is NOT numerically identical to native GGUF inference;
any candidate must be tested on the unchanged native baseline and native adapter.
"""
import argparse,hashlib,json,os,re,sys
from pathlib import Path
LAB=Path(__file__).parent;ROOT=LAB.parents[2]
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(LAB/'hf-cache'))
os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
sys.path[:0]=[str(LAB),str(LAB/'reader-packages'),str(ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages'),str(ROOT/'Agent')]
from research_guard import require_gpu_unpaused, model_digest
import numpy as np
import gguf

def parameter_name(name):
    top={'token_embd.weight':'model.embed_tokens.weight','output_norm.weight':'model.norm.weight','output.weight':'lm_head.weight'}
    if name in top:return top[name]
    match=re.fullmatch(r'blk\.(\d+)\.(.+)\.weight',name)
    if not match:raise ValueError('Unknown tensor '+name)
    layer,key=match.groups()
    mapping={'attn_norm':'input_layernorm','ffn_norm':'post_attention_layernorm','attn_q':'self_attn.q_proj','attn_k':'self_attn.k_proj','attn_v':'self_attn.v_proj','attn_output':'self_attn.o_proj','attn_q_norm':'self_attn.q_norm','attn_k_norm':'self_attn.k_norm','ffn_gate':'mlp.gate_proj','ffn_up':'mlp.up_proj','ffn_down':'mlp.down_proj'}
    if key not in mapping:raise ValueError('Unknown projection '+name)
    return f'model.layers.{layer}.{mapping[key]}.weight'

def configuration(reader):
    from transformers import Qwen3Config
    def value(key):return reader.fields['qwen3.'+key].contents()
    if reader.fields['general.architecture'].contents()!='qwen3':raise ValueError('This probe supports qwen3 only; qwen35 needs its own backend')
    embedding=next(t for t in reader.tensors if t.name=='token_embd.weight')
    return Qwen3Config(hidden_size=value('embedding_length'),intermediate_size=value('feed_forward_length'),num_hidden_layers=value('block_count'),num_attention_heads=value('attention.head_count'),num_key_value_heads=value('attention.head_count_kv'),head_dim=value('attention.key_length'),vocab_size=int(embedding.shape[1]),rms_norm_eps=value('attention.layer_norm_rms_epsilon'),rope_theta=value('rope.freq_base'),max_position_embeddings=value('context_length'),tie_word_embeddings=not any(t.name=='output.weight' for t in reader.tensors),attention_bias=False)

def empty_model(reader):
    import torch
    from accelerate import init_empty_weights
    from transformers import Qwen3ForCausalLM
    config=configuration(reader);config._attn_implementation='sdpa'
    with init_empty_weights(include_buffers=False):model=Qwen3ForCausalLM(config)
    expected={k:tuple(v.shape) for k,v in model.named_parameters(remove_duplicate=False)}
    found={}
    for tensor in reader.tensors:
        name=parameter_name(tensor.name);shape=tuple(int(n) for n in reversed(tensor.shape))
        if name not in expected or expected[name]!=shape:raise ValueError('GGUF/HF shape mismatch: '+name)
        found[name]=shape
    if config.tie_word_embeddings:found['lm_head.weight']=found['model.embed_tokens.weight']
    if set(found)!=set(expected):raise ValueError('Incomplete tensor mapping')
    return model

def load_probe(reader):
    require_gpu_unpaused()
    import torch
    from accelerate.utils import set_module_tensor_to_device
    if not torch.cuda.is_available():raise RuntimeError('CUDA activation probe unavailable')
    model=empty_model(reader)
    required=sum(p.numel()*2 for p in model.parameters())+2*1024**3
    if torch.cuda.mem_get_info()[0]<required:raise RuntimeError('Not enough free VRAM for bounded activation probe')
    torch.set_num_threads(4)
    for tensor in reader.tensors:
        require_gpu_unpaused()
        values=gguf.quants.dequantize(tensor.data,tensor.tensor_type)
        target=parameter_name(tensor.name)
        set_module_tensor_to_device(model,target,'cuda:0',value=torch.from_numpy(np.array(values,copy=True)),dtype=torch.bfloat16)
        del values
    model.tie_weights();model.to('cuda:0');model.eval();model.requires_grad_(False)
    return model

def capture(args):
    require_gpu_unpaused()
    import torch
    from transformers import AutoTokenizer
    from service_manager import acquire_gpu_lease,release_gpu_lease
    if not args.output.resolve().is_relative_to(LAB.resolve()):raise ValueError('Captures must remain in the portable experiment folder')
    if args.pairs.stat().st_size>4*1024**2:raise ValueError('Pair input exceeds 4 MiB')
    inputs=json.loads(args.pairs.read_text(encoding='utf-8'))
    if inputs.get('split')!='selection' or len(inputs.get('pairs',[]))<4:raise ValueError('Need at least four selection-only matched cases')
    ids=[p['id'] for p in inputs['pairs']]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate pair IDs')
    model_path=args.model.resolve()
    if not model_path.is_relative_to((ROOT/'LLM/models').resolve()):raise ValueError('Use this portable root model')
    reader=gguf.GGUFReader(str(model_path),'r');configuration(reader)
    model_sha=model_digest(model_path)
    if inputs.get('model_sha256')!=model_sha:raise ValueError('Pairs were captured from a different model')
    tokenizer=AutoTokenizer.from_pretrained(str(LAB/'tokenizer-qwen3'),trust_remote_code=False,local_files_only=True)
    tokens=reader.fields['tokenizer.ggml.tokens'].contents()
    for token,index in tokenizer.get_vocab().items():
        if index>=len(tokens) or tokens[index]!=token:raise ValueError('Tokenizer differs from installed model')
    args.output.mkdir(parents=True,exist_ok=False)
    lease=acquire_gpu_lease('weight-space-activation-capture',timeout=3)
    try:
        model=load_probe(reader);residual={};writers={};handles=[]
        for i,layer in enumerate(model.model.layers):
            def residual_hook(module,inp,out,index=i):
                x=out[0] if isinstance(out,tuple) else out
                residual[index]=x[0,-32:].float().mean(0).cpu().numpy()
            def writer_hook(module,inp,index=i):writers[index]=inp[0][0,-32:].float().mean(0).cpu().numpy()
            handles.extend([layer.register_forward_hook(residual_hook),layer.mlp.down_proj.register_forward_pre_hook(writer_hook)])
        captures={i:{'productive':[],'repetitive':[],'productive_writers':[],'repetitive_writers':[]} for i in range(len(model.model.layers))}
        for pair in inputs['pairs']:
            require_gpu_unpaused()
            lengths=[len(tokenizer.encode(pair[branch],add_special_tokens=False)) for branch in ('productive','repetitive')]
            if min(lengths)<64 or max(lengths)>1.25*min(lengths):raise ValueError('Match branch token lengths within 25%, with at least 64 tokens each')
            prefix=tokenizer.apply_chat_template([{'role':'user','content':pair['prompt']}],tokenize=False,add_generation_prompt=True,enable_thinking=True)
            for branch in ('productive','repetitive'):
                require_gpu_unpaused()
                encoded=tokenizer(prefix+pair[branch],return_tensors='pt',add_special_tokens=False)
                if encoded['input_ids'].shape[-1]>4096:raise ValueError('Activation probe limited to 4096 tokens; no silent truncation')
                with torch.inference_mode():model.model(**encoded.to('cuda:0'),use_cache=False)
                require_gpu_unpaused()
                for i in captures:
                    captures[i][branch].append(residual[i]);captures[i][branch+'_writers'].append(writers[i])
            print(json.dumps({'captured':pair['id'],'layers':len(captures)}),flush=True)
        sites=[]
        for i,values in captures.items():
            destination=args.output/f'layer-{i}.npz'
            contrast=np.mean(values['repetitive_writers'],axis=0)-np.mean(values['productive_writers'],axis=0)
            np.savez(destination,productive=np.array(values['productive']),repetitive=np.array(values['repetitive']),writer_contrast=contrast)
            sites.append({'tensor':f'blk.{i}.ffn_down.weight','activations':destination.name})
        report={'split':'selection','model_sha256':model_sha,'case_ids':ids,'pair_source_sha256':hashlib.sha256(args.pairs.read_bytes()).hexdigest(),'probe':'GGUF dequantized to BF16 in portable Transformers; not bit-identical to native quantized inference','sites':sites,'selection_note':'Choose one or two sites only after causal analysis; this full capture is not directly an accepted edit.'}
        (args.output/'capture.json').write_text(json.dumps(report,indent=2))
    finally:release_gpu_lease(lease)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--pairs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    capture(p.parse_args())
