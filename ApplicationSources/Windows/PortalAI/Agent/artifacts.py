"""Immutable, account-private HTML/SVG/chart revisions with explicit export."""
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import time
from workspace_store import Workspace,identifier,read_json,encoded

KINDS={'html':'.html','svg':'.svg','chart':'.json'}
LIMIT=512*1024


def validate_content(kind,content):
    if kind not in KINDS or not isinstance(content,str) or not content.strip() or len(content.encode())>LIMIT:
        raise ValueError('Artifact must be HTML, SVG or chart JSON, with 1..512 KiB of source')
    if kind=='chart':
        chart=json.loads(content)
        if not isinstance(chart,dict) or set(chart)-{'title','labels','series','style'}:raise ValueError('Chart fields: title, labels, series, style')
        labels=chart.get('labels');series=chart.get('series')
        if not isinstance(labels,list) or not 1<=len(labels)<=1000 or any(not isinstance(v,str) or len(v)>200 for v in labels):raise ValueError('Chart needs 1..1000 short labels')
        if not isinstance(series,list) or not 1<=len(series)<=16:raise ValueError('Chart needs 1..16 series')
        if chart.get('style','line') not in ('line','bar'):raise ValueError('Chart style must be line or bar')
        if not isinstance(chart.get('title',''),str) or len(chart.get('title',''))>300:raise ValueError('Invalid chart title')
        for row in series:
            if not isinstance(row,dict) or set(row)!={'name','values'} or not isinstance(row['name'],str) or len(row['name'])>200:raise ValueError('Series needs a name and values')
            values=row['values']
            if not isinstance(values,list) or len(values)!=len(labels) or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e100 for v in values):raise ValueError('Series values must be finite numbers matching labels')
    return content


class Artifacts(Workspace):
    def __init__(self,root,check=None):super().__init__(root,'Artifacts',check)

    def list(self):
        ids=self.records('Catalog')
        if len(ids)>2000:raise ValueError('Artifact catalogue exceeds 2000 entries')
        return sorted((self.metadata(i) for i in ids),key=lambda r:r['updated'],reverse=True)

    def metadata(self,aid):return read_json(self.path('Catalog/'+identifier(aid)+'.json'))

    def read(self,aid,revision=None):
        meta=self.metadata(aid);revision=identifier(revision or meta['head'])
        value=read_json(self.path('Versions/'+identifier(aid)+'/'+revision+'.json'))
        if value.get('artifact')!=aid or value.get('id')!=revision:raise ValueError('Artifact revision identity mismatch')
        if hashlib.sha256(value['content'].encode()).hexdigest()!=value['sha256']:raise ValueError('Artifact revision checksum mismatch')
        self.check();return value

    def save(self,title,kind,content,*,artifact=None,expected_revision=None):
        validate_content(kind,content)
        if not isinstance(title,str) or not title.strip() or len(title)>160:raise ValueError('Title must contain 1..160 characters')
        aid=identifier(artifact) if artifact else self.new_id()
        with self.lock(aid):
            previous=self.metadata(aid) if artifact else None
            if previous and previous['head']!=expected_revision:raise RuntimeError('Artifact changed; reload before saving another revision')
            if previous and previous['kind']!=kind:raise ValueError('Save a different artifact kind as a new artifact')
            if previous and previous['revision_count']>=256:raise ValueError('Artifact has 256 revisions; save as a new artifact')
            revision=self.new_id();now=time.time()
            value={'version':1,'id':revision,'artifact':aid,'parent':previous['head'] if previous else None,
                   'title':title.strip(),'kind':kind,'content':content,'sha256':hashlib.sha256(content.encode()).hexdigest(),'created':now}
            # An interrupted head publication leaves an inert, retained revision.
            # It never overwrites the previous committed head or historical bytes.
            super().save('Versions/'+aid+'/'+revision+'.json',value)
            meta={'id':aid,'title':title.strip(),'kind':kind,'head':revision,'revision_count':previous['revision_count']+1 if previous else 1,'updated':now}
            super().save('Catalog/'+aid+'.json',meta)
            return meta

    def history(self,aid):
        row=self.read(aid);result=[];seen=set()
        while row:
            if row['id'] in seen or len(result)>=256:raise ValueError('Invalid artifact revision history')
            seen.add(row['id']);result.append({k:v for k,v in row.items() if k!='content'})
            row=self.read(aid,row['parent']) if row.get('parent') else None
        return result

    def restore(self,aid,revision,expected_revision):
        old=self.read(aid,revision)
        return self.save(old['title'],old['kind'],old['content'],artifact=aid,expected_revision=expected_revision)

    def compare(self,aid,before,after):
        a=self.read(aid,before);b=self.read(aid,after)
        return ''.join(difflib.unified_diff(a['content'].splitlines(True),b['content'].splitlines(True),fromfile=before,tofile=after))[:200000]

    def export(self,aid,revision=None):
        from profile_paths import private_path
        from runtime_policy import require_space
        from profile_lazy_state import publish_no_replace
        row=self.read(aid,revision);relative='Outputs/Artifacts/'+aid+'/'+row['id']+KINDS[row['kind']]
        path=private_path(self.root,relative,context=self.identity);data=row['content'].encode()
        require_space(self.root,len(data)*2,for_outputs=True);self.check()
        if path.exists():
            if path.read_bytes()!=data:raise RuntimeError('An exported revision was modified; existing output retained')
        else:
            path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.'+self.new_id()+'.part')
            try:
                with temporary.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                self.check();publish_no_replace(temporary,path)
            finally:temporary.unlink(missing_ok=True)
        self.check();return {'path':relative,'bytes':len(data),'sha256':row['sha256'],'artifact':aid,'revision':row['id']}
