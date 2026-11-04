"""Compile field offsets from the exact pinned header using bundled clang.

No native program is executed. Opaque enum/pointer aliases are ABI-equivalent
under the Windows x64 C ABI. Header structure bodies are extracted verbatim.
"""
import ctypes as C,hashlib,json,re,subprocess,sys
from pathlib import Path
LAB=Path(__file__).parent;ROOT=LAB.parents[1];sys.path.insert(0,str(LAB))
from native_probe import ModelParams,ContextParams,Batch,SamplerChainParams
provenance=json.loads((LAB/'native-api-provenance.json').read_text())
header=LAB/'native-headers/include/llama.h';raw=header.read_bytes()
assert hashlib.sha256(raw).hexdigest()==provenance['files']['include/llama.h']['sha256']
source=raw.decode();source=re.sub(r'/\*.*?\*/|//[^\n]*','',source,flags=re.S)
prefix='typedef __INT8_TYPE__ int8_t; typedef __INT32_TYPE__ int32_t; typedef __UINT32_TYPE__ uint32_t; typedef __SIZE_TYPE__ size_t; typedef _Bool bool; typedef int32_t llama_token,llama_pos,llama_seq_id; typedef void *ggml_backend_dev_t,*ggml_backend_buffer_type_t,*llama_progress_callback,*ggml_backend_sched_eval_callback,*ggml_abort_callback;\n'
parts=[prefix];mapping={'ModelParams':'llama_model_params','ContextParams':'llama_context_params','Batch':'llama_batch','SamplerChainParams':'llama_sampler_chain_params'}
for py,native in mapping.items():
    body=re.search(r'(?:typedef\s+)?struct\s+'+native+r'\s*\{(.*?)\}',source,re.S).group(1)
    body=re.sub(r'enum\s+\w+','int',body)
    parts.append('struct '+native+' {'+body+'};\n')
    parts.append(f'const unsigned long long {py}_size = sizeof(struct {native});\n')
    for field,_ in globals()[py]._fields_:parts.append(f'const unsigned long long {py}_{field} = __builtin_offsetof(struct {native}, {field});\n')
folder=LAB/'native-abi-work';folder.mkdir(exist_ok=True);c=folder/'layout.c';ll=folder/'layout.ll';c.write_text(''.join(parts))
compiler=ROOT/'Runtime/AMDPython/packages/_rocm_sdk_core/lib/llvm/bin/clang.exe'
subprocess.run([str(compiler),'-x','c','-std=c11','-ffreestanding','-target','x86_64-pc-windows-msvc','-S','-emit-llvm',str(c),'-o',str(ll)],check=True)
ir=ll.read_text();structures={}
for py in mapping:
    def value(name):return int(re.search(r'@'+name+r'\s*=.*?constant i64 (\d+)',ir).group(1))
    cls=globals()[py];offsets={name:value(py+'_'+name) for name,_ in cls._fields_}
    assert C.sizeof(cls)==value(py+'_size')
    assert all(getattr(cls,n).offset==v for n,v in offsets.items())
    structures[py]={'size':C.sizeof(cls),'offsets':offsets}
libraries={}
for name in ('llama.dll','ggml.dll','ggml-base.dll'):
    with (ROOT/'LLM/llamacpp'/name).open('rb') as stream:libraries[name]=hashlib.file_digest(stream,'sha256').hexdigest()
result={'commit':provenance['commit'],'header_sha256':hashlib.sha256(raw).hexdigest(),'compiler':str(compiler.relative_to(ROOT)),'structures':structures,'libraries':libraries,'tensor_type_offset':0}
(LAB/'native-abi.json').write_text(json.dumps(result,indent=2));print(json.dumps({'structures':structures,'libraries':libraries}))
