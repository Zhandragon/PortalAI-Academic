"""Install pinned upstream ProteinMPNN and isolated Windows CPU Torch inside the bundle."""
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from web_tls import default_context
from runtime_policy import require_space,atomic_json
REVISION='8907e6671bfbfc92303b5f79c4b5e6ce47cdef57'
DEST=ROOT/'Runtime/ProteinDesign'


def fetch(url,limit):
    request=urllib.request.Request(url,headers={'User-Agent':'PortalAI portable biology installer'})
    with urllib.request.urlopen(request,context=default_context(),timeout=45) as response:
        if not response.geturl().startswith('https://'):raise ValueError('TLS downgrade')
        data=response.read(limit+1)
        if len(data)>limit:raise ValueError('Download size bound exceeded')
        if response.headers.get('Content-Length') and int(response.headers['Content-Length'])!=len(data):raise ValueError('Incomplete download')
        return data


def main():
    require_space(ROOT,1024**3,for_outputs=True)
    if (ROOT/'Maintenance/Imports/protein-mpnn.json').exists():raise RuntimeError('Receipt already exists; verify installed assets instead of reinstalling')
    DEST.mkdir(exist_ok=True);rows=[];assets=[]
    tree=json.loads(fetch('https://api.github.com/repos/dauparas/ProteinMPNN/git/trees/'+REVISION+'?recursive=1',4*1024**2))
    entries={e['path']:e for e in tree['tree']}
    for name in ('protein_mpnn_utils.py','protein_mpnn_run.py','LICENSE','README.md','vanilla_model_weights/v_48_020.pt','inputs/PDB_monomers/pdbs/5L33.pdb'):
        row=entries.get(name)
        if not row or row['type']!='blob' or row['size']>10*1024**2:raise ValueError('Unexpected upstream asset: '+name)
        url='https://raw.githubusercontent.com/dauparas/ProteinMPNN/'+REVISION+'/'+name
        data=fetch(url,row['size'])
        if len(data)!=row['size'] or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=row['sha']:
            raise RuntimeError('Pinned Git blob does not match')
        target=DEST/'vendor'/name;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            with target.open('xb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        assert hashlib.sha256(target.read_bytes()).hexdigest()==hashlib.sha256(data).hexdigest()
        rows.append({'path':target.relative_to(ROOT).as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        assets.append({'url':url,'git_blob':row['sha'],**rows[-1]})
    wheels=[('torch-2.9.1+cpu-cp312-cp312-win_amd64.whl',
      'https://download-r2.pytorch.org/whl/cpu/torch-2.9.1%2Bcpu-cp312-cp312-win_amd64.whl',
      'a4e06b4f441675d26b462123c8a83e77c55f1ec8ebc081203be2db1ea8054add',None)]
    for package,version in [('filelock','3.20.0'),('fsspec','2025.10.0'),('Jinja2','3.1.6'),('MarkupSafe','3.0.3')]:
        meta=json.loads(fetch('https://pypi.org/pypi/'+package+'/'+version+'/json',2*1024**2))
        matches=[r for r in meta['urls'] if r['filename'].endswith('py3-none-any.whl') or r['filename'].endswith('cp312-cp312-win_amd64.whl')]
        if len(matches)!=1:raise RuntimeError('Ambiguous wheel selection')
        r=matches[0];wheels.append((r['filename'],r['url'],r['digests']['sha256'],r['size']))
    packages=DEST/'windows-cpu';packages.mkdir(exist_ok=False)
    downloads=DEST/'downloads';downloads.mkdir(exist_ok=False)
    for name,url,expected,size in wheels:
        data=fetch(url,250*1024**2)
        if hashlib.sha256(data).hexdigest()!=expected or (size is not None and len(data)!=size):raise RuntimeError('Wheel digest/size mismatch')
        wheel=downloads/name;wheel.write_bytes(data)
        if hashlib.sha256(wheel.read_bytes()).hexdigest()!=expected:raise RuntimeError('Saved wheel mismatch')
        assets.append({'url':url,'filename':name,'bytes':len(data),'sha256':expected})
        with zipfile.ZipFile(wheel) as archive:
            if archive.testzip() is not None:raise RuntimeError('Bad wheel CRC')
            for info in archive.infolist():
                target=packages/info.filename
                if not target.resolve().is_relative_to(packages.resolve()) or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe wheel member')
                if info.is_dir():continue
                contents=archive.read(info);target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as out:out.write(contents)
                digest=hashlib.sha256(contents).hexdigest()
                if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise RuntimeError('Extracted wheel mismatch')
                rows.append({'path':target.relative_to(ROOT).as_posix(),'bytes':len(contents),'sha256':digest})
        print('Verified '+name,flush=True)
    receipt={'verified':True,'revision':REVISION,'model':'vanilla v_48_020','assets':assets,'files':rows,
             'scope':'Windows CPU Torch isolated; Linux reuses bundled CPU Torch; no host Python installation'}
    atomic_json(ROOT/'Maintenance/Imports/protein-mpnn.json',receipt)
    print(json.dumps({'verified_files':len(rows),'revision':REVISION,'asset_bytes':sum(a['bytes'] for a in assets)}))


if __name__=='__main__':main()
