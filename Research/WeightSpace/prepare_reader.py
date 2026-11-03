"""Fetch a pinned small GGUF reader wheel into this experiment only, no pip.

Reuses the portable NumPy layer. Every downloaded byte is verified against
the package registry digest; no model weights, dependencies or host changes.
"""
import hashlib,json,sys,urllib.request,zipfile,io
from pathlib import Path
lab=Path(__file__).parent;root=lab.parents[2];sys.path.insert(0,str(root/'Agent'))
from web_tls import default_context
context=default_context()
def fetch(url,limit):
    with urllib.request.urlopen(url,context=context,timeout=45) as r:
        data=r.read(limit+1)
        if len(data)>limit:raise ValueError('Download exceeds bounded size')
        return data
meta=json.loads(fetch('https://pypi.org/pypi/gguf/0.19.0/json',2*1024**2))
row=next(r for r in meta['urls'] if r['filename'].endswith('py3-none-any.whl'))
assert row['digests']['sha256']=='70bcd10edfe697fb2dad6e40af2234b9d8ece9a41a99761405121ebda1c3c1cd'
raw=fetch(row['url'],2*1024**2)
assert len(raw)==row['size'] and hashlib.sha256(raw).hexdigest()==row['digests']['sha256']
dest=lab/'reader-packages';dest.mkdir(exist_ok=True)
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    for entry in z.infolist():
        target=dest/entry.filename
        assert target.resolve().is_relative_to(dest.resolve())
        if not entry.is_dir():target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(entry))
record={k:row[k] for k in ('filename','url','size','digests')};record['version']=meta['info']['version'];record['dependencies_installed']=False
(lab/'reader-provenance.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
