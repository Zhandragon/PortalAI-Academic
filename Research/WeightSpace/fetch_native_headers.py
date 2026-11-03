"""Pin small upstream C-API source files to the installed b10935 runtime."""
import hashlib,json,sys,urllib.request
from pathlib import Path
lab=Path(__file__).parent;sys.path.insert(0,str(lab.parents[2]/'Agent'))
from web_tls import default_context
ctx=default_context()
def get(url,limit=2*1024**2):
    req=urllib.request.Request(url,headers={'User-Agent':'PortalAI-research-provenance'})
    with urllib.request.urlopen(req,context=ctx,timeout=35) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError('Source exceeds bounded size')
    return data
ref=json.loads(get('https://api.github.com/repos/ggml-org/llama.cpp/git/ref/tags/b10935'))['object']
if ref['type']=='tag':ref=json.loads(get('https://api.github.com/repos/ggml-org/llama.cpp/git/tags/'+ref['sha']))['object']
commit=ref['sha'];assert commit.startswith('8e330954a'),commit
folder=lab/'native-headers';folder.mkdir(exist_ok=True)
files=['include/llama.h','ggml/include/ggml.h','ggml/include/ggml-backend.h','src/models/qwen3.cpp','src/models/qwen35.cpp','src/llama-graph.cpp','LICENSE']
pins={}
for path in files:
    raw=get('https://raw.githubusercontent.com/ggml-org/llama.cpp/'+commit+'/'+path)
    target=folder/path;target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():assert target.read_bytes()==raw
    else:target.write_bytes(raw)
    pins[path]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
(lab/'native-api-provenance.json').write_text(json.dumps({'tag':'b10935','commit':commit,'files':pins},indent=2))
print(json.dumps({'commit':commit,'files':len(pins),'bytes':sum(p['bytes'] for p in pins.values())}),flush=True)
