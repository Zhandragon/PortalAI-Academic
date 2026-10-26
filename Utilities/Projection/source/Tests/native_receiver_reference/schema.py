"""Strict, bounded, inert current-view data. No HA calls or profile access."""
import json
import math
import re

PROTOCOL = 'portalai-native-state/2'
MAX_BYTES = 180000
MAX_INTEGER = 9007199254740991
MEDIA = {
    'media_variant': ('auto','standard','uncensored'),
    'image_profile': ('auto','sd15','klein4','flux'),
    'image_engine': ('auto','comfyui','sdcpp-vulkan','sdcpp-cpu'),
    'speech_model': ('auto','base','large-v3-turbo'),
    'voice_engine': ('auto','piper','qwen'),
    'text_video_engine': ('auto','sdcpp-vulkan','sdcpp-cpu'),
    'reference_video_profile': ('auto','wan22','vace13'),
    'music_engine': ('auto','acestep-service','acestep-scaled','musicgen-cpu'),
}

def fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('fields')

def text(value, limit=160):
    if not isinstance(value,str) or len(value)>limit:
        raise ValueError('text')
    # A lone surrogate is not valid UTF-8 and cannot cross this boundary.
    value.encode('utf-8')
    return value

def opaque(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value):
        raise ValueError('identifier')
    return value

def integer(value, low=0, high=MAX_INTEGER):
    if type(value) is not int or not low<=value<=high: raise ValueError('integer')

def enum(value, allowed):
    if not isinstance(value,str) or value not in allowed: raise ValueError('enum')

def boolean(value):
    if type(value) is not bool: raise ValueError('boolean')

def nullable_integer(value, low=0, high=MAX_INTEGER):
    if value is not None: integer(value,low,high)

def percentage(value):
    if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=100):
        raise ValueError('percentage')

def rows(value):
    if type(value) is not list or len(value)>100: raise ValueError('list')
    seen=set()
    for row in value:
        if type(row) is not dict: raise ValueError('row')
        key=opaque(row.get('id'))
        if key in seen: raise ValueError('duplicate_id')
        seen.add(key)
    return value

def encode(value):
    data=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    if len(data)>MAX_BYTES: raise ValueError('size')
    return data

def decode(data):
    if isinstance(data,str): data=data.encode('utf-8')
    if not isinstance(data,bytes) or len(data)>MAX_BYTES: raise ValueError('size')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate_key')
            result[key]=value
        return result
    def bad_constant(_): raise ValueError('number')
    return json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_constant=bad_constant)

def binding(value):
    fields(value,('view','epoch')); opaque(value['view']); opaque(value['epoch'])

def snapshot(value):
    if type(value) is not dict: raise ValueError('snapshot')
    base=('version','view','epoch','revision','account')
    account=value.get('account'); fields(account,('state','displayName'))
    enum(account['state'],('ready','locked','switching','closing')); text(account['displayName'])
    fields(value,base+('runtime','models','packages','chat','settings') if account['state']=='ready' else base)
    if type(value['version']) is not int or value['version']!=2: raise ValueError('version')
    opaque(value['view']); opaque(value['epoch']); integer(value['revision'])
    if account['state']!='ready':
        if account['displayName']!='': raise ValueError('private_locked_state')
        encode(value); return value
    runtime=value['runtime']; fields(runtime,('state','cpu','gpu','memory','model'))
    enum(runtime['state'],('idle','starting','ready','sleeping','stopping','unavailable'))
    for key in ('cpu','gpu','memory'): percentage(runtime[key])
    text(runtime['model'])
    for row in rows(value['models']):
        fields(row,('id','name','kind','installed','selected','state'))
        text(row['name']); text(row['kind']); boolean(row['installed']); boolean(row['selected'])
        enum(row['state'],('ready','sleeping','starting','stopped','unavailable'))
    for row in rows(value['packages']):
        fields(row,('id','name','purpose','state')); text(row['name']); text(row['purpose'],300)
        enum(row['state'],('available','unavailable','unvalidated'))
    chat=value['chat']; fields(chat,('conversations','current','messages','busy','contextUsed','contextLimit','replyCap','window'))
    conversations=rows(chat['conversations']); messages=rows(chat['messages']); boolean(chat['busy'])
    for row in conversations:
        fields(row,('id','title','updated')); text(row['title']); text(row['updated'])
    if chat['current'] is None:
        if messages or chat['busy']: raise ValueError('no_current_chat')
    else:
        opaque(chat['current'])
        if chat['current'] not in {r['id'] for r in conversations}: raise ValueError('current_chat')
    for row in messages:
        fields(row,('id','role','text','truncated')); enum(row['role'],('user','assistant'))
        text(row['text'],16000); boolean(row['truncated'])
    nullable_integer(chat['contextUsed'],0,1048576); nullable_integer(chat['contextLimit'],1,1048576)
    nullable_integer(chat['replyCap'],1,32768)
    if chat['contextUsed'] is not None and chat['contextLimit'] is not None and chat['contextUsed']>chat['contextLimit']: raise ValueError('context')
    fields(chat['window'],('conversationsComplete','messagesComplete'))
    for v in chat['window'].values(): boolean(v)
    settings=value['settings']; fields(settings,('selection','variant','backend','context','reply','effort','media'))
    opaque(settings['selection']); enum(settings['variant'],('standard','uncensored')); enum(settings['backend'],('auto','cuda','vulkan','cpu'))
    integer(settings['context'],1,32768)
    if settings['context'] not in (2048,4096,8192,16384,32768): raise ValueError('setting_context')
    integer(settings['reply'],1,32768); enum(settings['effort'],('Fast','Balanced','Deep'))
    fields(settings['media'],MEDIA)
    for key,allowed in MEDIA.items(): enum(settings['media'][key],allowed)
    encode(value)
    return value
