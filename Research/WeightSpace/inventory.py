"""Read GGUF metadata/tensor shapes by memory map; never load full weights."""
import json,sys,shutil
from pathlib import Path
lab=Path(__file__).parent;root=lab.parents[2]
sys.path[:0]=[str(lab/'reader-packages'),str(root/'Voice/Qwen3-TTS/.venv/Lib/site-packages'),str(lab)]
import gguf
from benchmark import MODELS
output=[]
for key,name in MODELS.items():
    reader=gguf.GGUFReader(str(root/'LLM/models'/name),'r')
    fields={}
    for name2,field in reader.fields.items():
        if name2 in ('general.architecture','general.name','general.file_type') or name2.endswith(('.block_count','.embedding_length','.feed_forward_length','.context_length')):
            fields[name2]=field.contents()
    tensors=[{'name':t.name,'shape':t.shape.tolist(),'type':str(t.tensor_type),'bytes':t.n_bytes} for t in reader.tensors if t.name.endswith('ffn_down.weight')]
    counterpart=Path(('E' if root.drive.upper()=='D:' else 'D')+':/PortalAI Windows/LLM/models')/name
    output.append({'model':key,'filename':name,'fields':fields,'down_projection_tensors':tensors,'tensor_count':len(reader.tensors),'counterpart_same_size':counterpart.stat().st_size==(root/'LLM/models'/name).stat().st_size if counterpart.is_file() else None})
    print(json.dumps({'model':key,'fields':fields,'down_projections':len(tensors)}),flush=True)
    del reader
(lab/'gguf-inventory.json').write_text(json.dumps(output,indent=2))
print(json.dumps({'free_gib':{drive:round(shutil.disk_usage(drive+':/').free/1024**3,2) for drive in ('D','E')}}))
