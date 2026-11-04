"""Bounded native GGUF activation/loss probe, pinned to installed llama.cpp ABI.

Research only: no production server, account, model overwrite or downloads.
The caller must hold the portable GPU lease. Capture callbacks keep at most
32 rows per requested tensor. No ctypes pointer crosses a model lifetime.
"""
import ctypes as C,hashlib,json,os,re,sys,subprocess
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[1]
sys.path[:0]=[str(LAB),str(LAB/'reader-packages'),str(ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages')]
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
import numpy as np
from research_guard import require_gpu_unpaused
P=C.c_void_p;I=C.c_int32;U=C.c_uint32;F=C.c_float;B=C.c_bool
IP=C.POINTER(I);FP=C.POINTER(F)

class ModelParams(C.Structure):
    _fields_=[('devices',P),('tensor_buft_overrides',P),('n_gpu_layers',I),('split_mode',I),('load_mode',I),('lazy_mode',I),('main_gpu',I),('tensor_split',P),('progress_callback',P),('progress_callback_user_data',P),('kv_overrides',P)]+[(n,B) for n in ('vocab_only','check_tensors','use_extra_bufts','no_host','no_alloc','load_mtp')]

class ContextParams(C.Structure):
    _fields_=[(n,U) for n in ('n_ctx','n_batch','n_ubatch','n_seq_max','n_rs_seq','n_outputs_max','n_outputs_max_per_seq')]+[(n,I) for n in ('n_threads','n_threads_batch','ctx_type','rope_scaling_type','pooling_type','attention_type','flash_attn_type')]+[(n,F) for n in ('rope_freq_base','rope_freq_scale','yarn_ext_factor','yarn_attn_factor','yarn_beta_fast','yarn_beta_slow')]+[('yarn_orig_ctx',U),('defrag_thold',F),('cb_eval',P),('cb_eval_user_data',P),('type_k',I),('type_v',I),('abort_callback',P),('abort_callback_data',P)]+[(n,B) for n in ('embeddings','offload_kqv','no_perf','op_offload','swa_full','kv_unified')]+[('samplers',P),('n_samplers',C.c_size_t),('ctx_other',P)]

class Batch(C.Structure):
    _fields_=[('n_tokens',I),('token',IP),('embd',FP),('pos',IP),('n_seq_id',IP),('seq_id',C.POINTER(IP)),('logits',C.POINTER(C.c_int8))]

class SamplerChainParams(C.Structure):
    _fields_=[('no_perf',B)]

def validate_abi():
    proof=json.loads((LAB/'native-abi.json').read_text())
    if proof.get('commit')!='8e330954adb6e86c329c9d7e338f01f93ffe4b88':raise RuntimeError('Unsupported native ABI')
    for cls in (ModelParams,ContextParams,Batch,SamplerChainParams):
        expected=proof['structures'][cls.__name__]
        if C.sizeof(cls)!=expected['size']:raise RuntimeError('Native structure size differs: '+cls.__name__)
        for name,_ in cls._fields_:
            if getattr(cls,name).offset!=expected['offsets'][name]:raise RuntimeError('Native field offset differs: '+name)
    if C.sizeof(P)!=8 or os.name!='nt':raise RuntimeError('This probe is pinned to Windows x64')
    return proof

class NativeProbe:
    def __init__(self,model,*,capture_names=(),context=4096,batch=64):
        require_gpu_unpaused();proof=validate_abi()
        model=Path(model).resolve()
        if not model.is_file() or model.suffix.lower()!='.gguf':raise ValueError('Select an existing GGUF model')
        available=float(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True,timeout=15).splitlines()[0])
        if available<model.stat().st_size/1024**2+1800:raise RuntimeError('Insufficient free VRAM for native probe')
        self.model=self.ctx=None;self.adapters=[];self.error=None;self.keep={};self.enabled=bool(capture_names)
        self.names=frozenset(capture_names);self.batch=batch;self.context=context
        if not 1<=batch<=512 or not 128<=context<=40960 or len(self.names)>161:raise ValueError('Probe limits exceeded')
        folder=ROOT/'LLM/llamacpp';self.directory=os.add_dll_directory(str(folder))
        for name,digest in proof['libraries'].items():
            with (folder/name).open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:raise RuntimeError('Pinned library changed: '+name)
        self.base=C.CDLL(str(folder/'ggml-base.dll'));self.ggml=C.CDLL(str(folder/'ggml.dll'));self.llama=C.CDLL(str(folder/'llama.dll'))
        def bind(lib,name,restype,*args):
            fun=getattr(lib,name);fun.restype=restype;fun.argtypes=list(args);setattr(self,name,fun)
        bind(self.ggml,'ggml_backend_load_all_from_path',None,C.c_char_p)
        bind(self.ggml,'ggml_backend_load',P,C.c_char_p)
        bind(self.ggml,'ggml_backend_dev_count',C.c_size_t)
        bind(self.ggml,'ggml_backend_dev_get',P,C.c_size_t)
        bind(self.base,'ggml_backend_dev_type',I,P)
        for name,restype,args in [
            ('llama_backend_init',None,()),('llama_backend_free',None,()),
            ('llama_model_default_params',ModelParams,()),('llama_context_default_params',ContextParams,()),
            ('llama_model_load_from_file',P,(C.c_char_p,ModelParams)),('llama_init_from_model',P,(P,ContextParams)),
            ('llama_model_free',None,(P,)),('llama_free',None,(P,)),('llama_model_get_vocab',P,(P,)),
            ('llama_vocab_n_tokens',I,(P,)),('llama_tokenize',I,(P,C.c_char_p,I,IP,I,B,B)),
            ('llama_decode',I,(P,Batch)),('llama_get_logits_ith',FP,(P,I)),('llama_get_memory',P,(P,)),
            ('llama_memory_clear',None,(P,B)),('llama_adapter_lora_init',P,(P,C.c_char_p)),
            ('llama_adapter_lora_free',None,(P,)),('llama_set_adapters_lora',I,(P,C.POINTER(P),C.c_size_t,FP)),
            ('llama_sampler_chain_default_params',SamplerChainParams,()),
            ('llama_sampler_chain_init',P,(SamplerChainParams,)),('llama_sampler_chain_add',None,(P,P)),
            ('llama_sampler_init_dist',P,(U,)),('llama_sampler_init_top_k',P,(I,)),
            ('llama_sampler_init_top_p',P,(F,C.c_size_t)),('llama_sampler_init_temp',P,(F,)),
            ('llama_sampler_init_penalties',P,(I,I,F,F,F)),('llama_sampler_sample',I,(P,P,I)),
            ('llama_sampler_free',None,(P,)),('llama_vocab_is_eog',B,(P,I)),
            ('llama_token_to_piece',I,(P,I,P,I,I,B)),
        ]:bind(self.llama,name,restype,*args)
        for name,restype,args in [('ggml_get_name',C.c_char_p,(P,)),('ggml_nelements',C.c_int64,(P,)),('ggml_nrows',C.c_int64,(P,)),('ggml_is_contiguous',B,(P,)),('ggml_backend_tensor_get',None,(P,P,C.c_size_t,C.c_size_t))]:bind(self.base,name,restype,*args)
        self.native_warnings=[]
        def native_log(level,message,data):
            if level in (3,4):
                text=message.decode('utf-8',errors='replace')[:2048]
                self.native_warnings.append(text)
                self.native_warnings=self.native_warnings[-64:]
                sys.stderr.write(text)
        self.log_callback=C.CFUNCTYPE(None,I,C.c_char_p,P)(native_log)
        bind(self.base,'ggml_log_set',None,P,P)
        bind(self.llama,'llama_log_set',None,P,P)
        self.ggml_log_set(C.cast(self.log_callback,P),None)
        self.llama_log_set(C.cast(self.log_callback,P),None)
        self.callback=C.CFUNCTYPE(B,P,B,P)(self._capture)
        self.progress=C.CFUNCTYPE(B,F,P)(self._loading)
        try:
            # Native LoadLibrary does not inherit Python's DLL search flags.
            # Preload the existing portable dependencies by absolute path.
            self.cuda_libraries=[C.CDLL(str(folder/name)) for name in ('cudart64_12.dll','cublasLt64_12.dll','cublas64_12.dll','ggml-cuda.dll')]
            if not self.ggml_backend_load(os.fsencode(folder/'ggml-cuda.dll')):raise RuntimeError('CUDA backend could not load; refusing CPU fallback')
            self.ggml_backend_load_all_from_path(os.fsencode(folder));self.llama_backend_init()
            if not any(self.ggml_backend_dev_type(self.ggml_backend_dev_get(i))==1 for i in range(self.ggml_backend_dev_count())):raise RuntimeError('No native GPU device; refusing CPU fallback')
            params=self.llama_model_default_params();params.n_gpu_layers=99;params.load_mtp=False
            params.progress_callback=C.cast(self.progress,P)
            self.model=self.llama_model_load_from_file(os.fsencode(model),params)
            if not self.model:raise RuntimeError('Native model load failed')
            require_gpu_unpaused();params=self.llama_context_default_params()
            params.n_ctx=context;params.n_batch=batch;params.n_ubatch=batch;params.n_seq_max=1
            params.n_threads=params.n_threads_batch=4;params.flash_attn_type=1
            if self.names:params.cb_eval=C.cast(self.callback,P)
            self.ctx=self.llama_init_from_model(self.model,params)
            if not self.ctx:raise RuntimeError('Native context load failed')
            self.vocab=self.llama_model_get_vocab(self.model);self.n_vocab=self.llama_vocab_n_tokens(self.vocab)
            if not 1000<=self.n_vocab<=1000000:raise RuntimeError('Invalid native vocabulary')
        except BaseException:self.close();raise

    def _loading(self,progress,data):
        try:require_gpu_unpaused();return True
        except BaseException as exc:self.error=str(exc);return False

    def _capture(self,tensor,ask,data):
        try:
            name=self.ggml_get_name(tensor).decode('ascii')
            if ask:return self.enabled and name in self.names
            if not self.enabled or name not in self.names:return True
            if not self.ggml_is_contiguous(tensor):raise RuntimeError('Noncontiguous capture tensor: '+name)
            rows=self.ggml_nrows(tensor);elements=self.ggml_nelements(tensor)
            if rows<1 or elements%rows:raise RuntimeError('Invalid capture shape')
            width=elements//rows;count=min(32,rows);kind=I.from_address(tensor).value
            if kind not in (0,1,30) or not 1<=width<=65536:raise RuntimeError('Unsupported capture dtype/width')
            dtype=np.float32 if kind==0 else (np.float16 if kind==1 else np.uint16)
            values=np.empty((count,width),dtype=dtype)
            self.ggml_backend_tensor_get(tensor,values.ctypes.data,(rows-count)*width*values.itemsize,values.nbytes)
            values=(values.astype(np.uint32)<<16).view(np.float32) if kind==30 else values.astype(np.float32)
            if not np.isfinite(values).all():raise RuntimeError('Nonfinite activations')
            previous=self.keep.get(name)
            self.keep[name]=values[-32:].copy() if previous is None else np.concatenate((previous,values))[-32:].copy()
            return True
        except BaseException as exc:self.error=repr(exc);return False

    def tokenize(self,text):
        raw=text.encode('utf-8');needed=self.llama_tokenize(self.vocab,raw,len(raw),None,0,True,True)
        if not -self.context<=needed<0:raise ValueError('Tokenized input exceeds native context')
        tokens=(I*(-needed))();size=self.llama_tokenize(self.vocab,raw,len(raw),tokens,len(tokens),True,True)
        if size!=len(tokens):raise RuntimeError('Native token count changed')
        return list(tokens)

    def adapter(self,path=None,scale=1.):
        require_gpu_unpaused()
        if path is None:handles=(P*0)();scales=(F*0)()
        else:
            resolved=Path(path).resolve()
            if not resolved.is_file() or resolved.suffix.lower()!='.gguf' or not np.isfinite(scale) or not 0<=scale<=6:raise ValueError('Invalid research adapter')
            pointer=self.llama_adapter_lora_init(self.model,os.fsencode(resolved))
            if not pointer:raise RuntimeError('Native adapter load failed')
            self.adapters.append(pointer);handles=(P*1)(pointer);scales=(F*1)(scale)
        if self.llama_set_adapters_lora(self.ctx,handles,len(handles),scales)!=0:raise RuntimeError('Native adapter apply failed')

    def evaluate(self,tokens,*,loss_from=1,capture=True):
        """Teacher-forced NLL, tail activations and final logits; <=8192 tokens."""
        if not 2<=len(tokens)<=self.context or not 1<=loss_from<len(tokens):raise ValueError('Invalid teacher-forced sequence')
        if any(type(t) is not int or not 0<=t<self.n_vocab for t in tokens):raise ValueError('Invalid token ID')
        self.keep={};self.error=None;self.enabled=capture and bool(self.names);losses=[]
        self.llama_memory_clear(self.llama_get_memory(self.ctx),True)
        for start in range(0,len(tokens),self.batch):
            require_gpu_unpaused();chunk=tokens[start:start+self.batch];n=len(chunk)
            token=(I*n)(*chunk);positions=(I*n)(*range(start,start+n));counts=(I*n)(*([1]*n))
            seq=(I*1)(0);seqs=(IP*n)(*[C.cast(seq,IP) for _ in chunk]);outputs=(C.c_int8*n)(*([1]*n))
            batch=Batch(n,token,None,positions,counts,seqs,outputs)
            status=self.llama_decode(self.ctx,batch)
            if status!=0 or self.error:raise RuntimeError('Native decode failed: '+str(status)+' '+str(self.error))
            for i in range(n):
                pointer=self.llama_get_logits_ith(self.ctx,i)
                if not pointer:raise RuntimeError('Missing requested native logits')
                logits=np.ctypeslib.as_array(pointer,shape=(self.n_vocab,))
                next_index=start+i+1
                if loss_from<=next_index<len(tokens):
                    maximum=float(logits.max());loss=float(np.log(np.exp(logits-maximum).sum(dtype=np.float64))+maximum-logits[tokens[next_index]])
                    if not np.isfinite(loss):raise RuntimeError('Nonfinite native loss')
                    losses.append(loss)
            final=logits.copy()
        if capture and self.names!=self.keep.keys():raise RuntimeError('Requested graph sites were not all captured: '+str(self.names-self.keep.keys()))
        return {'loss':float(np.mean(losses)),'loss_tokens':len(losses),'tokens':len(tokens),'logits':final,'activations':{k:v.mean(0) for k,v in self.keep.items()}}

    def close(self):
        if self.ctx:self.llama_free(self.ctx);self.ctx=None
        for adapter in self.adapters:self.llama_adapter_lora_free(adapter)
        self.adapters=[]
        if self.model:self.llama_model_free(self.model);self.model=None
        if hasattr(self,'llama_backend_free'):self.llama_backend_free()
        if hasattr(self,'ggml_log_set'):self.ggml_log_set(None,None)
        if hasattr(self,'llama_log_set'):self.llama_log_set(None,None)
        if hasattr(self,'directory'):self.directory.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
