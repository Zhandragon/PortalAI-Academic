"""Account-bound native workflows over the existing outbound projection lane."""
import hashlib
import json
import re
import time

UPLOAD_PROTOCOL=2

PAGES={'welcome','accounts','controls','chat','activity','runtime','installed','settings','persistence','maintenance','help'}
KINDS={'heading','note','text','secret','textarea','number','select','checkbox','button','table','file','download'}
def opaque(v):
    if not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',v): raise ValueError('Invalid workflow identity')
def bounded(v,n=8192):
    if not isinstance(v,str) or len(v)>n: raise ValueError('Invalid workflow text')
    v.encode('utf-8')
def size(v,limit=56000):
    if len(json.dumps(v,ensure_ascii=False).encode('utf-8'))>limit: raise ValueError('Workflow message too large')
def validate_request(v):
    if type(v) is not dict: raise ValueError('Invalid workflow request')
    op=v.get('operation'); common={'request_id','viewer','operation'}
    extra={'describe':{'page'},'invoke':{'binding','form','action','values'},
           'file_begin':{'binding','form','field','name','size','mime'},
           'file_chunk':{'binding','transfer','offset','data'},
           'file_chunk_v2':{'protocol','binding','transfer','offset','data'},
           'file_commit':{'binding','transfer','sha256'},
           'file_get':{'binding','file','offset'}}
    if op not in extra or set(v)!=common|extra[op]: raise ValueError('Unsupported workflow request')
    for k in ('request_id','viewer'):
        if not isinstance(v[k],str) or not re.fullmatch('[0-9a-f]{32}',v[k]): raise ValueError('Invalid request identity')
    if op=='describe':
        if v['page'] not in PAGES: raise ValueError('Unknown native page')
    else:
        if type(v['binding']) is not dict or set(v['binding'])!={'view','epoch'}: raise ValueError('Invalid workflow binding')
        for x in v['binding'].values(): opaque(x)
        for k in ('form','action','field','transfer','file'):
            if k in v: opaque(v[k])
    if op=='invoke':
        if type(v['values']) is not dict or len(v['values'])>120: raise ValueError('Too many form fields')
        for k,x in v['values'].items():
            opaque(k)
            if isinstance(x,str): bounded(x,16000)
            elif type(x) not in (bool,int,float) or (isinstance(x,float) and (x!=x or abs(x)==float('inf'))): raise ValueError('Invalid field value')
    if op=='file_begin':
        bounded(v['name'],200); bounded(v['mime'],120)
        if not v['name'] or any(c in v['name'] for c in ('/','\\','\x00')): raise ValueError('Invalid file name')
        if type(v['size']) is not int or not 0<=v['size']<=20*1024*1024: raise ValueError('File limit is 20 MiB')
    if op in ('file_chunk','file_chunk_v2','file_get') and (type(v['offset']) is not int or not 0<=v['offset']<=20*1024*1024): raise ValueError('Invalid file offset')
    if op in ('file_chunk','file_chunk_v2'):
        import base64
        bulk=op=='file_chunk_v2'
        if bulk and (type(v['protocol']) is not int or v['protocol']!=2): raise ValueError('Invalid upload protocol')
        bounded(v['data'],1398104 if bulk else 32768)
        if not 0<len(base64.b64decode(v['data'],validate=True))<=(1048576 if bulk else 24576): raise ValueError('Invalid file chunk')
    if op=='file_commit' and (not isinstance(v['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',v['sha256'])): raise ValueError('Invalid file digest')
    size(v,1400000 if op=='file_chunk_v2' else 56000); return json.loads(json.dumps(v))

def validate_model(m):
    if type(m) is not dict or set(m)!={'protocol','view','epoch','form','revision','page','title','account','nodes','message','truncated'}: raise ValueError('Invalid workflow model')
    if type(m['protocol']) is not int or m['protocol']!=1 or m['page'] not in PAGES: raise ValueError('Invalid workflow protocol')
    for k in ('view','epoch','form'): opaque(m[k])
    if type(m['revision']) is not int or not 0<=m['revision']<2**53: raise ValueError('Invalid workflow revision')
    if type(m['truncated']) is not bool: raise ValueError('Invalid workflow bounds')
    bounded(m['title'],160);bounded(m['message'],1000)
    a=m['account']
    if type(a) is not dict or set(a)!={'state','displayName'} or a['state'] not in ('ready','locked','switching','closing'): raise ValueError('Invalid account state')
    bounded(a['displayName'],160)
    if a['state']!='ready' and a['displayName']: raise ValueError('Private locked state')
    if type(m['nodes']) is not list or len(m['nodes'])>120: raise ValueError('Too many native controls')
    seen=set()
    for n in m['nodes']:
        if type(n) is not dict or not {'id','kind','label','enabled'}<=set(n) or set(n)-{'id','kind','label','enabled','value','options','action','on_change','min','max','step','columns','rows','accept','file','name','mime'}: raise ValueError('Invalid native control')
        opaque(n['id'])
        if n['id'] in seen: raise ValueError('Duplicate native control')
        seen.add(n['id'])
        if n['kind'] not in KINDS or type(n['enabled']) is not bool: raise ValueError('Invalid native control kind')
        bounded(n['label'],1000)
        for k in ('action','on_change','file'):
            if k in n: opaque(n[k])
        for k in ('name','mime','accept'):
            if k in n: bounded(n[k],200)
        if n['kind']=='secret' and n.get('value') not in (None,''): raise ValueError('Secret values must never be exported')
        if 'value' in n:
            if isinstance(n['value'],str): bounded(n['value'],16000)
            elif type(n['value']) not in (bool,int,float): raise ValueError('Invalid control value')
        if 'options' in n:
            if type(n['options']) is not list or len(n['options'])>100: raise ValueError('Invalid options')
            for o in n['options']:
                if type(o) is not dict or set(o)!={'value','label'}: raise ValueError('Invalid option')
                bounded(o['value'],160);bounded(o['label'],300)
        if 'rows' in n or 'columns' in n:
            columns=n.get('columns',[]);rows=n.get('rows',[])
            if type(columns) is not list or len(columns)>12 or type(rows) is not list or len(rows)>100: raise ValueError('Invalid native table')
            for c in columns: bounded(c,160)
            for row in rows:
                if type(row) is not list or len(row)!=len(columns): raise ValueError('Invalid native row')
                for cell in row: bounded(cell,2000)
        for k in ('min','max','step'):
            if k in n and (type(n[k]) not in (int,float) or not -1e12<=n[k]<=1e12): raise ValueError('Invalid numeric control')
    size(m,60000);return m

