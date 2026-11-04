"""Quantized forward tool: native sampling, Jinja template and bounded captures.

No training runtime. Returned activations are from the actual native graph.
"""
import ctypes as C,json,hashlib,time
from native_probe import NativeProbe,I,IP,Batch,np
from research_guard import require_gpu_unpaused
import gguf
from jinja2.sandbox import ImmutableSandboxedEnvironment

def metadata(path):
    reader=gguf.GGUFReader(str(path),'r')
    arch=reader.fields['general.architecture'].contents()
    total=reader.fields[arch+'.block_count'].contents()
    nextn_field=reader.fields.get(arch+'.nextn_predict_layers')
    nextn=nextn_field.contents() if nextn_field is not None else 0
    # The pinned llama.cpp main decoder excludes optional NextN/MTP blocks.
    # They remain present in GGUF but do not produce main-pass capture sites.
    if any(isinstance(n,(bool,np.bool_)) or not isinstance(n,(int,np.integer)) for n in (total,nextn)) or not 0<=nextn<total:
        raise ValueError('Invalid main decoder / NextN layer counts')
    return {'architecture':arch,'layers':int(total-nextn),
            'total_layers':int(total),'mtp_layers':int(nextn),
            'template':reader.fields['tokenizer.chat_template'].contents(),
            'training_context':reader.fields[arch+'.context_length'].contents()}


def render(template,messages,*,thinking=True,tools=None):
    if not isinstance(template,str) or len(template)>1024**2:raise ValueError('Invalid model chat template')
    env=ImmutableSandboxedEnvironment(trim_blocks=True,lstrip_blocks=True,extensions=['jinja2.ext.loopcontrols'])
    def fail(message):raise ValueError(str(message))
    env.globals['raise_exception']=fail
    env.filters['tojson']=lambda value,**kw:json.dumps(value,ensure_ascii=False,**kw)
    return env.from_string(template).render(messages=messages,tools=tools,add_generation_prompt=True,
        enable_thinking=thinking,bos_token='',eos_token='<|im_end|>')

def item_seed(identifier,sample=0):
    return int.from_bytes(hashlib.sha256(('portalai-takehi-v1\0'+identifier+'\0'+str(sample)).encode()).digest()[:4],'little')

class Forward(NativeProbe):
    def __init__(self,*args,**kwargs):
        self.capture_mode='tail';self.phase='prompt';self.aggregates={};self.row_window=None
        super().__init__(*args,**kwargs)

    def _capture(self,tensor,ask,data):
        if self.capture_mode=='tail':return super()._capture(tensor,ask,data)
        try:
            name=self.ggml_get_name(tensor).decode('ascii')
            if ask:return self.enabled and name in self.names
            if not self.enabled or name not in self.names:return True
            if not self.ggml_is_contiguous(tensor):raise RuntimeError('Noncontiguous capture: '+name)
            rows=self.ggml_nrows(tensor);elements=self.ggml_nelements(tensor);kind=I.from_address(tensor).value
            if rows<1 or elements%rows or kind not in (0,1,30):raise RuntimeError('Invalid native activation layout')
            width=elements//rows
            if not 1<=width<=65536:raise RuntimeError('Activation width exceeds bound')
            start,end=(max(0,rows-1),rows) if self.phase=='prompt' else (0,rows)
            if self.row_window is not None:
                start=max(start,self.row_window[0]);end=min(end,self.row_window[1])
            if end<=start:return True
            dtype=np.float32 if kind==0 else np.float16 if kind==1 else np.uint16
            values=np.empty((end-start,width),dtype=dtype)
            self.ggml_backend_tensor_get(tensor,values.ctypes.data,start*width*values.itemsize,values.nbytes)
            values=(values.astype(np.uint32)<<16).view(np.float32) if kind==30 else values.astype(np.float32)
            if not np.isfinite(values).all():raise RuntimeError('Nonfinite activations')
            key=self.phase+'/'+name
            if self.phase=='prompt':self.aggregates[key]=(values[-1].astype(np.float64),1)
            else:
                total,count=self.aggregates.get(key,(np.zeros(width,dtype=np.float64),0))
                self.aggregates[key]=(total+values.sum(axis=0,dtype=np.float64),count+len(values))
            return True
        except BaseException as exc:self.error=repr(exc);return False

    def decode_chunk(self,tokens,start,all_logits=False):
        require_gpu_unpaused()
        n=len(tokens);token=(I*n)(*tokens);positions=(I*n)(*range(start,start+n));counts=(I*n)(*([1]*n))
        seq=(I*1)(0);seqs=(IP*n)(*[C.cast(seq,IP) for _ in tokens])
        outputs=(C.c_int8*n)(*([1]*n if all_logits else [0]*(n-1)+[1]))
        status=self.llama_decode(self.ctx,Batch(n,token,None,positions,counts,seqs,outputs))
        if status!=0 or self.error:raise RuntimeError('Native decode failed: '+str(status)+' '+str(self.error))

    def piece(self,token):
        buffer=C.create_string_buffer(256)
        count=self.llama_token_to_piece(self.vocab,token,buffer,len(buffer),0,True)
        if count<0:
            if -count>65536:raise RuntimeError('Token text exceeds bound')
            buffer=C.create_string_buffer(-count)
            count=self.llama_token_to_piece(self.vocab,token,buffer,len(buffer),0,True)
        if not 0<=count<=len(buffer):raise RuntimeError('Cannot decode token text')
        return bytes(buffer[:count])

    def generate(self,prompt,*,seed,max_tokens=32768,temperature=.6,top_p=.95,top_k=20,presence_penalty=0.,capture=False,progress=None):
        if not 1<=max_tokens<=32768 or not 0<temperature<=2 or not 0<top_p<=1 or not 1<=top_k<=1000 or not 0<=presence_penalty<=2:raise ValueError('Invalid sampling settings')
        tokens=self.tokenize(prompt)
        if len(tokens)+max_tokens>self.context:raise ValueError('Prompt plus complete reply budget does not fit; refusing truncation')
        self.llama_memory_clear(self.llama_get_memory(self.ctx),True)
        self.enabled=bool(capture and self.names);self.capture_mode='aggregate';self.phase='prompt';self.aggregates={};self.error=None
        start=time.monotonic();sampler=None;generated=[];pieces=[];finish='length'
        try:
            for offset in range(0,len(tokens),self.batch):self.decode_chunk(tokens[offset:offset+self.batch],offset)
            params=self.llama_sampler_chain_default_params();params.no_perf=True
            sampler=self.llama_sampler_chain_init(params)
            if not sampler:raise RuntimeError('Cannot allocate sampler')
            stages=[]
            # Only sampled output enters this history (not the prompt). The pinned
            # native API clamps negative history to zero, disabling all penalties;
            # a positive reply-sized window retains the entire generated history.
            if presence_penalty:stages.append(self.llama_sampler_init_penalties(self.n_vocab,max_tokens,1.,0.,presence_penalty))
            stages.extend([self.llama_sampler_init_temp(temperature),self.llama_sampler_init_top_k(top_k),self.llama_sampler_init_top_p(top_p,1),self.llama_sampler_init_dist(seed)])
            for stage in stages:
                if not stage:raise RuntimeError('Cannot allocate sampling stage')
                self.llama_sampler_chain_add(sampler,stage)
            self.phase='answer'
            for index in range(max_tokens):
                require_gpu_unpaused()
                token=int(self.llama_sampler_sample(sampler,self.ctx,-1))
                if not 0<=token<self.n_vocab:raise RuntimeError('Invalid sampled token')
                generated.append(token);pieces.append(self.piece(token))
                if self.llama_vocab_is_eog(self.vocab,token):finish='stop';break
                self.enabled=bool(capture and self.names and index<8192)
                self.decode_chunk([token],len(tokens)+index)
                if progress and (index+1)%256==0:progress(index+1,time.monotonic()-start)
            if capture:
                for phase in ('prompt','answer'):
                    if generated and any(phase+'/'+name not in self.aggregates for name in self.names):raise RuntimeError('Missing requested '+phase+' activations')
            return {'text':b''.join(pieces).decode('utf-8',errors='replace'),'token_ids':generated,'prompt_tokens':len(tokens),
                    'tokens':len(generated),'finish':finish,'seconds':time.monotonic()-start,
                    'sampling_implementation':{'version':'native-generated-history-v2','presence_penalty':presence_penalty,
                        'presence_history_tokens':max_tokens if presence_penalty else 0,'prompt_in_penalty_history':False},
                    'activations':{k:(v[0]/v[1]).astype(np.float32) for k,v in self.aggregates.items()},
                    'capture_counts':{k:v[1] for k,v in self.aggregates.items()}}
        finally:
            if sampler:self.llama_sampler_free(sampler)
            self.enabled=False;self.capture_mode='tail'

    def capture_replay(self,prompt,answer_tokens,*,answer_limit=8192):
        """Teacher force the actual natural completion, retaining exact prompt/answer means."""
        tokens=self.tokenize(prompt);answer=list(answer_tokens[:answer_limit])
        if answer and self.llama_vocab_is_eog(self.vocab,answer[-1]):answer.pop()
        if len(tokens)+len(answer)>self.context:raise ValueError('Capture replay exceeds native context')
        self.llama_memory_clear(self.llama_get_memory(self.ctx),True)
        self.enabled=True;self.capture_mode='aggregate';self.aggregates={};self.error=None;self.phase='prompt'
        try:
            for offset in range(0,len(tokens),self.batch):self.decode_chunk(tokens[offset:offset+self.batch],offset,True)
            self.phase='answer'
            for offset in range(0,len(answer),self.batch):self.decode_chunk(answer[offset:offset+self.batch],len(tokens)+offset,True)
            if any(phase+'/'+name not in self.aggregates for phase in ('prompt','answer') for name in self.names):raise RuntimeError('Missing replay graph sites')
            return {k:(v[0]/v[1]).astype(np.float32) for k,v in self.aggregates.items()}
        finally:self.enabled=False;self.capture_mode='tail'
