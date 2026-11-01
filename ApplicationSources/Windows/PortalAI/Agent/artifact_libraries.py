"""Reviewed offline CommonJS bundles; code runs only inside artifact Chromium."""
import hashlib
import json
import re
import zipfile
from workspace_store import Workspace, identifier, read_json, digest
from runtime_policy import require_space

LIMIT=16*1024**2
RESERVED={'react','react-dom','react-dom/client','scheduler'}


def module_filename(value):
    return (isinstance(value,str) and re.fullmatch(r'[a-zA-Z0-9_-]+\.js',value)
            and not re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])\.js',value,re.IGNORECASE))


class Libraries(Workspace):
    def __init__(self,root,check=None):super().__init__(root,'Artifacts/Libraries',check)

    def list(self):return [self.read(i) for i in self.records('Catalog')[:100]]

    def read(self,lid):
        row=read_json(self.path('Catalog/'+identifier(lid)+'.json'),65536)
        if row.get('id')!=lid:raise ValueError('Library identity mismatch')
        if digest(row['modules'])!=row['sha256']:raise ValueError('Library manifest checksum mismatch')
        if not isinstance(row['modules'],list) or not 1<=len(row['modules'])<=32:raise ValueError('Invalid library modules')
        for module in row['modules']:
            if not isinstance(module,dict) or not module_filename(module.get('file')):raise ValueError('Invalid or reserved library filename')
            if not re.fullmatch(r'(?:@[a-z0-9_-]+/)?[a-z0-9_-]+(?:/[a-z0-9_-]+)*',str(module.get('name',''))):raise ValueError('Invalid library module name')
        return row

    def import_bundle(self,path):
        """The ZIP contains library.json and already bundled UTF-8 .js modules."""
        from pathlib import Path
        path=Path(path)
        if path.stat().st_size>LIMIT:raise ValueError('Library archive exceeds 16 MiB')
        with self.lock():
            if len(self.records('Catalog'))>=100:raise ValueError('Library catalogue limit is 100 bundles')
            with zipfile.ZipFile(path) as z:
                entries=z.infolist();names=[i.filename for i in entries]
                if len(names)>33 or len(set(n.casefold() for n in names))!=len(names):raise ValueError('Library archive has duplicate or too many files')
                if any(i.file_size>8*1024**2 or i.flag_bits&1 or (i.external_attr>>16)&0o170000==0o120000 for i in entries) or sum(i.file_size for i in entries)>LIMIT:raise ValueError('Library archive exceeds limits or contains links/encryption')
                if 'library.json' not in names or z.getinfo('library.json').file_size>65536:raise ValueError('Missing bounded library.json manifest')
                manifest=json.loads(z.read('library.json'));modules=manifest.get('modules')
                if manifest.get('version')!=1 or not isinstance(modules,list) or not 1<=len(modules)<=32:raise ValueError('Library manifest needs version 1 and 1–32 modules')
                title=manifest.get('name','')
                if not isinstance(title,str) or not 1<=len(title.strip())<=120:raise ValueError('Library needs a short name')
                seen=set();expected={'library.json'}
                for module in modules:
                    if not isinstance(module,dict) or set(module)!={'name','file','sha256'}:raise ValueError('Each module needs name, file and sha256')
                    name=module['name'];file=module['file']
                    if not isinstance(name,str) or not re.fullmatch(r'(?:@[a-z0-9_-]+/)?[a-z0-9_-]+(?:/[a-z0-9_-]+)*',name) or name in RESERVED or name in seen:raise ValueError('Invalid, duplicate or reserved module name')
                    if not module_filename(file) or file in expected:raise ValueError('Each module must use a unique, nonreserved plain .js filename')
                    if not isinstance(module['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',module['sha256']):raise ValueError('Invalid module checksum')
                    seen.add(name);expected.add(file)
                if set(names)!=expected:raise ValueError('Library files must exactly match the manifest')
                # Validate first, holding at most one 8 MiB module at a time.
                for module in modules:
                    self.check();raw=z.read(module['file']);raw.decode('utf-8')
                    if hashlib.sha256(raw).hexdigest()!=module['sha256']:raise ValueError('Library module checksum mismatch')
                require_space(self.root,LIMIT*2,for_outputs=True);lid=self.new_id()
                for module in modules:
                    self.check();target=self.path('Bundles/'+lid+'/'+module['file']);target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as output:output.write(z.read(module['file']))
                row={'id':lid,'name':title.strip(),'modules':modules,'sha256':digest(modules),'enabled':False}
                self.save('Catalog/'+lid+'.json',row);return row

    def enable(self,lid,enabled):
        with self.lock():
            row=self.read(lid);row['enabled']=bool(enabled);self.save('Catalog/'+lid+'.json',row)
        return row

    def pins(self,ids):
        if not isinstance(ids,list) or len(ids)>8 or len(set(ids))!=len(ids):raise ValueError('Choose up to eight different library IDs')
        pins=[]
        for lid in ids:
            row=self.read(lid)
            if not row['enabled']:raise PermissionError('Review and enable library '+row['name']+' before using it')
            pins.append({'id':lid,'sha256':row['sha256']})
        return pins

    def modules(self,pins):
        if not isinstance(pins,list) or len(pins)>8:raise ValueError('Too many artifact libraries')
        result=[];seen=set(RESERVED);size=0
        for pin in pins:
            row=self.read(pin['id'])
            if not row['enabled'] or pin['sha256']!=row['sha256']:raise PermissionError('Artifact library was disabled or changed; review it before previewing')
            for module in row['modules']:
                name=module['name']
                if name in seen:raise ValueError('Duplicate artifact module '+name)
                seen.add(name);path=self.path('Bundles/'+row['id']+'/'+module['file'])
                with path.open('rb') as source:raw=source.read(8*1024**2+1)
                size+=len(raw)
                if len(raw)>8*1024**2 or size>LIMIT:raise ValueError('Combined artifact libraries exceed 16 MiB')
                if hashlib.sha256(raw).hexdigest()!=module['sha256']:raise ValueError('Artifact library code changed')
                result.append({'name':name,'source':raw.decode('utf-8')});self.check()
        return result
