"""Explicit rich-chat/1 read extension carried by native_ui; v2 stays unchanged."""
import base64
import json
import re

LIMIT=20*1024*1024
CHUNK=24576
BATCH_CHUNK=262144
BATCH_REPLY=360000
OPS={'rich_index','rich_detail','rich_media','rich_media_batch','rich_preview'}
def ident(v):
    if type(v) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,80}',v):raise ValueError('rich_identity')
def fields(v,keys):
    if type(v) is not dict or set(v)!=set(keys.split()):raise ValueError('rich_fields')
def text(v,n):
    if type(v) is not str or len(v)>n:raise ValueError('rich_text')
def number(v,hi):
    if type(v) is not int or not 0<=v<=hi:raise ValueError('rich_number')
def validate_request(p):
    op=p.get('operation') if type(p) is dict else None
    extra={'rich_index':'','rich_detail':' block','rich_media':' block offset','rich_media_batch':' block offset','rich_preview':' block offset'}.get(op)
    if extra is None:raise ValueError('rich_operation')
    fields(p,'request_id viewer operation protocol binding conversation'+extra)
    if type(p['protocol']) is not int or p['protocol']!=(2 if op=='rich_media_batch' else 1):raise ValueError('rich_version')
    for k in ('request_id','viewer'):
        if type(p[k]) is not str or not re.fullmatch('[0-9a-f]{32}',p[k]):raise ValueError('rich_identity')
    fields(p['binding'],'view epoch')
    for v in p['binding'].values():ident(v)
    ident(p['conversation'])
    if op!='rich_index':ident(p['block'])
    if op in ('rich_media','rich_media_batch'):number(p['offset'],LIMIT)
    if op=='rich_preview' and (type(p['offset']) is not int or p['offset']!=0):raise ValueError('preview_offset')
    return p
def validate_reply(reply,p):
    fields(reply,'accepted request_id operation rich')
    if reply['accepted'] is not True or reply['request_id']!=p['request_id'] or reply['operation']!=p['operation']:raise ValueError('rich_ack')
    r=reply['rich'];extra={'rich_index':'blocks truncated','rich_detail':'block text truncated','rich_media':'block offset next size mime name data eof identity','rich_media_batch':'block offset next size mime name data eof identity','rich_preview':'block offset next size mime name data eof identity'}[p['operation']]
    fields(r,'protocol binding conversation '+extra)
    if type(r['protocol']) is not int or r['protocol']!=p['protocol'] or r['binding']!=p['binding'] or r['conversation']!=p['conversation']:raise ValueError('rich_binding')
    if p['operation']=='rich_index':
        if type(r['blocks']) is not list or len(r['blocks'])>120 or type(r['truncated']) is not bool:raise ValueError('rich_index')
        seen=set()
        for b in r['blocks']:
            fields(b,'id message kind title status')
            ident(b['id']);ident(b['message']);text(b['title'],120)
            if b['id'] in seen or b['kind'] not in ('thinking','tool','media') or b['status'] not in ('saved','streaming','pending','returned','cancelled','incomplete','available'):raise ValueError('rich_block')
            seen.add(b['id'])
    else:
        if r['block']!=p['block']:raise ValueError('rich_block')
        if p['operation']=='rich_detail':
            text(r['text'],16000)
            if type(r['truncated']) is not bool:raise ValueError('rich_detail')
        else:
            for k in ('offset','next','size'):number(r[k],LIMIT)
            chunk_limit=BATCH_CHUNK if p['operation']=='rich_media_batch' else CHUNK
            text(r['name'],160);text(r['mime'],80);ident(r['identity']);text(r['data'],((chunk_limit+2)//3)*4)
            if not r['name'] or any(c in r['name'] for c in '/\\:\x00') or r['mime'] not in ('image/png','image/jpeg','image/gif','image/webp','audio/wav','audio/mpeg','audio/ogg','audio/flac','video/mp4','video/webm','application/octet-stream'):raise ValueError('rich_media_type')
            if p['operation']=='rich_preview' and (r['size']>CHUNK or not r['eof'] or r['mime'] not in ('image/jpeg','application/octet-stream')):raise ValueError('preview_limit')
            data=base64.b64decode(r['data'],validate=True)
            if (type(r['eof']) is not bool or len(data)>chunk_limit or r['offset']!=p['offset'] or r['next']!=r['offset']+len(data) or r['next']>r['size'] or r['eof']!=(r['next']==r['size']) or not data and not r['eof']):raise ValueError('rich_chunk')
    if len(json.dumps(reply,ensure_ascii=False).encode('utf-8'))>(BATCH_REPLY if p['operation']=='rich_media_batch' else 63000):raise ValueError('rich_limit')
    return reply
