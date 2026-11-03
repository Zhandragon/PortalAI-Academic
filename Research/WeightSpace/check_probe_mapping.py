import json,sys
from pathlib import Path
lab=Path(__file__).parent;sys.path.insert(0,str(lab))
import capture_qwen3 as probe
from benchmark import MODELS
report=[]
for key,name in MODELS.items():
    reader=probe.gguf.GGUFReader(str(probe.ROOT/'LLM/models'/name),'r')
    if key.startswith('27'):
        try:probe.configuration(reader)
        except ValueError:report.append({'model':key,'unsupported_architecture_rejected':True});continue
        raise AssertionError('Hybrid model must not use Qwen3 loader')
    model=probe.empty_model(reader)
    report.append({'model':key,'mapping_verified':True,'tensors':len(reader.tensors),'gpu_allocated':False})
    del model,reader
(lab/'probe-mapping-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
