"""Native web layers shared by the Full and Academic package builders."""
import ast
import hashlib
import json
from pathlib import Path

PLATFORMS={'Windows':('windows-x64',),'Linux':('linux-x64',),'Mac':('macos-x64','macos-arm64')}
CERTIFICATES=('Runtime/Certificates/cacert.pem','Runtime/Certificates/LICENSE.certifi')

def native_web_path(name,system):
    return name in ('PortalAI/'+p for p in CERTIFICATES) or any(name.startswith('PortalAI/Runtime/Web/'+p+'/') for p in PLATFORMS[system])

def certificate_files(root):
    """Ship the exact roots pinned by the web client, without executing it."""
    root=Path(root)
    pins={}
    for node in ast.parse((root/'Agent/web_tls.py').read_bytes()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            key=node.targets[0].id
            if key in ('BUNDLE_RELATIVE','BUNDLE_BYTES','BUNDLE_SHA256'):pins[key]=ast.literal_eval(node.value)
    path=root/CERTIFICATES[0]
    data=path.read_bytes()
    if pins.get('BUNDLE_RELATIVE')!=CERTIFICATES[0] or len(data)!=pins.get('BUNDLE_BYTES') or hashlib.sha256(data).hexdigest()!=pins.get('BUNDLE_SHA256'):
        raise RuntimeError('Pinned web certificate bundle differs')
    for name in CERTIFICATES:
        path=root/name
        if not path.is_file():raise RuntimeError('Web certificate asset missing: '+name)
        yield 'PortalAI/'+name,path

def files(root,system):
    yield from certificate_files(root)
    for platform in PLATFORMS[system]:
        layer=Path(root)/'Runtime/Web'/platform
        manifest=json.loads((layer/'manifest.json').read_text())
        with (layer/'browser.zip').open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=manifest['browser']['sha256']:
                raise RuntimeError('Pinned browser differs: '+platform)
        if platform=='linux-x64':
            for row in json.loads((layer/'linux-system-manifest.json').read_text())['files']:
                with (layer/'system'/row['path']).open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=row['sha256']:
                        raise RuntimeError('Linux browser library differs: '+row['path'])
        for path in sorted(layer.rglob('*')):
            relative=path.relative_to(layer)
            if not path.is_file() or relative.parts[0]=='browser' or '__pycache__' in relative.parts:continue
            if path.name in ('extract.lock','linux-relocated.json','run-node') or path.name.endswith('.relocating'):continue
            yield 'PortalAI/'+path.relative_to(root).as_posix(),path
