"""Strict native v2 read-only presentation wire data. No UI, I/O or authority."""
import json
import math
import re

PROTOCOL = 'portalai-native-state/2'
MAX_FRAME = 180000
LEASE_MS = 2000
MEDIA = {
    'media_variant': ('auto', 'standard', 'uncensored'),
    'image_profile': ('auto', 'sd15', 'klein4', 'flux'),
    'speech_model': ('auto', 'base', 'large-v3-turbo'),
    'voice_engine': ('auto', 'piper', 'qwen'),
    'image_engine': ('auto', 'comfyui', 'sdcpp-vulkan', 'sdcpp-cpu'),
    'text_video_engine': ('auto', 'sdcpp-vulkan', 'sdcpp-cpu'),
    'reference_video_profile': ('auto', 'wan22', 'vace13'),
    'music_engine': ('auto', 'acestep-service', 'acestep-scaled', 'musicgen-cpu'),
}


def encode(value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_FRAME:
        raise ValueError('frame_limit')
    return data


def decode(data):
    if len(data) > MAX_FRAME:
        raise ValueError('frame_limit')
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError('duplicate_key')
            out[key] = value
        return out
    def invalid(_):
        raise ValueError('nonfinite')
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)


def fields(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise ValueError('fields')


def text(value, limit=160):
    if type(value) is not str or len(value.encode('utf-16-le')) // 2 > limit:
        raise ValueError('text')


def identifier(value, *, model=False):
    pattern = r'[A-Za-z0-9_.-]{1,128}' if model else r'[A-Za-z0-9_-]{1,80}'
    if type(value) is not str or not re.fullmatch(pattern, value):
        raise ValueError('identifier')


def integer(value, low=0, high=9007199254740991, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not int or not low <= value <= high:
        raise ValueError('integer')


def choice(value, values):
    if type(value) is not str or value not in values:
        raise ValueError('choice')


def boolean(value):
    if type(value) is not bool:
        raise ValueError('boolean')


def rows(value, *, model=False):
    if type(value) is not list or len(value) > 100:
        raise ValueError('list_limit')
    ids = set()
    for row in value:
        if type(row) is not dict:
            raise ValueError('row')
        identifier(row.get('id'), model=model)
        if row['id'] in ids:
            raise ValueError('duplicate_id')
        ids.add(row['id'])
    return ids


def validate_snapshot(s):
    original=s
    if type(s) is not dict:
        raise ValueError('snapshot')
    fields(s.get('account'), 'state displayName')
    a = s['account']
    choice(a['state'], ('ready', 'locked', 'switching', 'closing'))
    text(a['displayName'])
    keys = 'version view epoch revision account'
    fields(s, keys + (' runtime models packages chat settings' if a['state'] == 'ready' else ''))
    if type(s['version']) is not int or s['version'] != 2:
        raise ValueError('version')
    identifier(s['view']); identifier(s['epoch']); integer(s['revision'])
    if a['state'] != 'ready':
        if a['displayName']:
            raise ValueError('private_locked_state')
        encode(s)
        return s
    r = s['runtime']; fields(r, 'state cpu gpu memory model')
    choice(r['state'], ('idle', 'starting', 'ready', 'sleeping', 'stopping', 'unavailable'))
    text(r['model'])
    for key in ('cpu', 'gpu', 'memory'):
        n = r[key]
        if n is not None and (type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 100):
            raise ValueError('percentage')
    rows(s['models'], model=True)
    for r in s['models']:
        fields(r, 'id name kind installed selected state')
        text(r['name']); text(r['kind']); boolean(r['installed']); boolean(r['selected'])
        choice(r['state'], ('ready', 'sleeping', 'starting', 'stopped', 'unavailable', 'unknown'))
    rows(s['packages'], model=True)
    for r in s['packages']:
        fields(r, 'id name purpose state'); text(r['name']); text(r['purpose'], 300)
        choice(r['state'], ('available', 'unavailable', 'unvalidated'))
    c = s['chat']; fields(c, 'conversations current messages busy contextUsed contextLimit replyCap window')
    boolean(c['busy']); ids = rows(c['conversations'])
    for r in c['conversations']:
        fields(r, 'id title updated'); text(r['title']); text(r['updated'])
    rows(c['messages'])
    for r in c['messages']:
        fields(r, 'id role text truncated'); choice(r['role'], ('user', 'assistant'))
        text(r['text'], 16000); boolean(r['truncated'])
    if c['current'] is None:
        if c['messages'] or c['busy']:
            raise ValueError('empty_chat')
    else:
        identifier(c['current'])
        if c['current'] not in ids:
            raise ValueError('unknown_conversation')
    integer(c['contextUsed'], high=1048576, nullable=True)
    integer(c['contextLimit'], 1, 1048576, nullable=True)
    integer(c['replyCap'], 1, 32768, nullable=True)
    if c['contextUsed'] is not None and c['contextLimit'] is not None and c['contextUsed'] > c['contextLimit']:
        raise ValueError('context_budget')
    fields(c['window'], 'conversationsComplete messagesComplete')
    for v in c['window'].values(): boolean(v)
    s = s['settings']; fields(s, 'selection variant backend context reply effort media')
    identifier(s['selection'], model=True)
    choice(s['variant'], ('standard', 'uncensored')); choice(s['backend'], ('auto', 'cuda', 'vulkan', 'cpu'))
    integer(s['context'])
    if s['context'] not in (2048,4096,8192,16384,32768): raise ValueError('context_setting')
    integer(s['reply'], 1, 32768); choice(s['effort'], ('Fast', 'Balanced', 'Deep'))
    fields(s['media'], ' '.join(MEDIA))
    for k, values in MEDIA.items(): choice(s['media'][k], values)
    encode(original)
    return original


def validate_envelope(value):
    fields(value, 'protocol generation kind snapshot')
    if value['protocol'] != PROTOCOL or value['kind'] != 'snapshot':
        raise ValueError('protocol')
    identifier(value['generation'])
    validate_snapshot(value['snapshot'])
    encode(value)
    return value
