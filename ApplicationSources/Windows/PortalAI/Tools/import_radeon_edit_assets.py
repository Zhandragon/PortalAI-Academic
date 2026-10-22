"""Import pinned instruction editing and small VACE assets, with publisher hashes."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space,atomic_json


def import_files(repo,revision,names,destination):
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true',timeout=45) as r:meta=json.load(r)
    if meta['sha']!=revision:raise RuntimeError('Unexpected model revision')
    rows={r['rfilename']:r for r in meta['siblings']};assets=[]
    for name,relative in names.items():
        row=rows[name];size=row.get('lfs',{}).get('size',row.get('size'))
        if not isinstance(size,int):raise RuntimeError('Missing publisher byte count')
        dest=destination/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        require_space(ROOT,size*2)
        url=f'https://huggingface.co/{repo}/resolve/{revision}/{name}'
        path=dest if dest.exists() else dest.with_suffix(dest.suffix+'.part')
        if not dest.exists():
            with urllib.request.urlopen(url,timeout=60) as r,path.open('wb') as f:
                total=0
                for block in iter(lambda:r.read(4*1024**2),b''):
                    total+=len(block)
                    if total>size:raise RuntimeError('Asset exceeds expected bytes')
                    f.write(block)
        if path.stat().st_size!=size:raise RuntimeError('Asset byte mismatch')
        with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if row.get('lfs'):
            if digest!=row['lfs']['sha256']:raise RuntimeError('Asset SHA256 mismatch')
        else:
            blob=path.read_bytes()
            if hashlib.sha1(b'blob '+str(size).encode()+b'\0'+blob).hexdigest()!=row['blobId']:
                raise RuntimeError('Config Git blob mismatch')
        if path!=dest:path.rename(dest)
        assets.append({'source':name,'path':dest.relative_to(ROOT).as_posix(),'bytes':size,'sha256':digest})
        print(json.dumps({'verified':name,'bytes':size}),flush=True)
    return {'repo':repo,'revision':revision,'assets':assets,'verified':True}


def main():
    ip='31519b5cb02a7fd89b906d88731cd4d6a7bbf88d'
    names=['model_index.json','scheduler/scheduler_config.json','text_encoder/config.json',
           'text_encoder/model.fp16.safetensors','tokenizer/merges.txt','tokenizer/special_tokens_map.json',
           'tokenizer/tokenizer_config.json','tokenizer/vocab.json','unet/config.json',
           'unet/diffusion_pytorch_model.fp16.safetensors','vae/config.json','vae/diffusion_pytorch_model.fp16.safetensors']
    result=import_files('timbrooks/instruct-pix2pix',ip,{n:n for n in names},ROOT/'Models/InstructionEdit')
    atomic_json(ROOT/'Maintenance/Imports/instruction-edit.json',result)
    name='split_files/diffusion_models/wan2.1_vace_1.3B_fp16.safetensors'
    result=import_files('Comfy-Org/Wan_2.1_ComfyUI_repackaged','123acf1cc74bccbb9bfff8ac1ee72edc08c2341d',
                        {name:Path(name).name},ROOT/'Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models')
    atomic_json(ROOT/'Maintenance/Imports/vace-small.json',result)

if __name__=='__main__':main()
