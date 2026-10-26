"""Package only the independent HA recovery receiver; never private state."""
from pathlib import Path
import ast
import hashlib
import json
import zipfile

MODULE=Path(__file__).resolve().parents[1]

def main():
    base=MODULE/'RecoveryHelper';ha=base/'ha'
    names=['configuration.example.yaml','dashboard.example.yaml']
    names += ['custom_components/portalai_recovery/'+name for name in
              ('__init__.py','receiver.py','manifest.json','services.yaml')]
    sources={'README.txt':(base/'README.txt').read_bytes()}
    for name in names:
        path=ha/name
        if path.is_symlink() or not path.resolve().is_relative_to(ha.resolve()):raise ValueError('Invalid package source')
        data=path.read_bytes()
        if path.suffix=='.py':ast.parse(data,filename=str(path))
        if path.suffix=='.json':json.loads(data)
        sources[name]=data
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in sources.items()}
    archive=base/'portalai-recovery-receiver-0.1.0.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as output:
        for name,data in sources.items():output.writestr(name,data)
        output.writestr('SHA256SUMS.json',json.dumps(hashes,indent=2))
    with zipfile.ZipFile(archive) as source:
        if source.testzip() is not None:raise RuntimeError('Archive CRC failed')
        for name,digest in hashes.items():
            if hashlib.sha256(source.read(name)).hexdigest()!=digest:raise RuntimeError('Archive hash mismatch')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (base/(archive.name+'.sha256')).write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'sha256':digest,'source_files':len(sources)}))

if __name__=='__main__':main()
