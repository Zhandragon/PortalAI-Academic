"""Pinned official DWPose export for portable MuseTalk preprocessing."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space,atomic_json

REV='1a7144101628d69ee7a3768d1ee3a094070dc388'
SHA='724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843'
SIZE=134399116

def main():
    path=ROOT/'Video/MuseTalk/models/dwpose/dw-ll_ucoco_384.onnx'
    url=f'https://huggingface.co/yzd-v/DWPose/resolve/{REV}/{path.name}'
    require_space(ROOT,SIZE*2)
    with urllib.request.urlopen(f'https://huggingface.co/api/models/yzd-v/DWPose/revision/{REV}?blobs=true',timeout=45) as r:
        metadata=json.load(r)
    row=next(x for x in metadata['siblings'] if x['rfilename']==path.name)
    if metadata['sha']!=REV or row['lfs']['sha256']!=SHA or row['lfs']['size']!=SIZE:
        raise RuntimeError('Official model metadata does not match the reviewed revision')
    if not path.exists():
        part=path.with_suffix('.part');total=0
        with urllib.request.urlopen(url,timeout=45) as source,part.open('wb') as out:
            for block in iter(lambda:source.read(1024**2),b''):
                total+=len(block)
                if total>SIZE:raise RuntimeError('Model download exceeded declared size')
                out.write(block)
        with part.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if total!=SIZE or actual!=SHA:raise RuntimeError('Model size/hash mismatch')
        part.rename(path)
    with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    if path.stat().st_size!=SIZE or actual!=SHA:raise RuntimeError('Installed ONNX differs from official asset')
    result={'repo':'yzd-v/DWPose','revision':REV,'url':url,'bytes':SIZE,'sha256':SHA,
            'path':path.relative_to(ROOT).as_posix(),'verified':True}
    atomic_json(ROOT/'Maintenance/Imports/musetalk-onnx.json',result)
    print(json.dumps(result))

if __name__=='__main__':main()
