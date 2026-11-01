"""Build-only, integrity-verified extraction of specific public browser assets."""
import base64,hashlib,io,json,tarfile,urllib.request
from pathlib import Path
DEST=Path(__file__).resolve().parents[1]/'ApplicationSources/Windows/PortalAI/ControlCenter/ArtifactAssets'
PACKAGES=[('@mermaid-js/tiny','12.2.0',['dist/mermaid.tiny.js']),('@babel/standalone','8.0.10',['babel.min.js']),
          ('react','19.3.1',['cjs/react.production.js']),('react-dom','19.3.1',['cjs/react-dom.production.js','cjs/react-dom-client.production.js']),
          ('scheduler','0.28.0',['cjs/scheduler.production.js']),('marked','18.1.2',['lib/marked.umd.js']),('dompurify','3.4.17',['dist/purify.min.js'])]
def get(url,limit):
    with urllib.request.urlopen(url,timeout=30) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError('Download exceeds build limit')
    return data
def main():
    DEST.mkdir(parents=True,exist_ok=True);rows=[]
    for name,version,files in PACKAGES:
        registry='https://registry.npmjs.org/'+name.replace('/','%2f')+'/'+version
        meta=json.loads(get(registry,2*1024**2));dist=meta['dist'];raw=get(dist['tarball'],20*1024**2)
        algorithm,expected=dist['integrity'].split('-',1);assert algorithm=='sha512'
        assert base64.b64encode(hashlib.sha512(raw).digest()).decode()==expected
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
            selected=['package/'+f for f in files]
            licenses=[m.name for m in archive.getmembers() if m.name.lower() in ('package/license','package/license.md','package/license.txt')]
            assert licenses,(name,'license missing')
            for member in selected+licenses:
                info=archive.getmember(member);assert info.isfile() and info.size<10*1024**2
                data=archive.extractfile(info).read();filename=(name.replace('@','').replace('/','-')+'-'+Path(member).name)
                (DEST/filename).write_bytes(data)
                rows.append({'file':filename,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'package':name,'version':meta['version'],
                             'tarball':dist['tarball'],'tarball_integrity':dist['integrity'],'member':member,'license':meta.get('license')})
    (DEST/'manifest.json').write_text(json.dumps({'version':1,'files':rows},indent=2))
    print(json.dumps({'asset_bytes':sum(r['bytes'] for r in rows),'files':[r['file'] for r in rows]}),flush=True)
if __name__=='__main__':main()
