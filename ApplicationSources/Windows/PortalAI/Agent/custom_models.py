"""Bounded GGUF admission for user-supplied text models; no repository code.

The initial compatibility boundary is single-file dense Qwen3 GGUF chat models.
Header/tensor validation is not a quality benchmark; the selected backend still
owns loading and inference. Vision, MoE and media replacements need separate
workflow contracts and are deliberately not relabeled as compatible here.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import struct

_QUANT = {0:(1,4), 1:(1,2), 2:(32,18), 3:(32,20), 6:(32,22),
          7:(32,24), 8:(32,34), 9:(32,40), 10:(256,84),
          11:(256,110), 12:(256,144), 13:(256,176), 14:(256,210),
          15:(256,292), 30:(1,2)}
_SCALAR = {0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
_inspected = {}
_verified = set()


def inspect_gguf(path):
    """Check architecture, template, metadata bounds and every tensor extent."""
    path = Path(path)
    size = path.stat().st_size
    if not 1024 <= size <= 512 * 1024**3:
        raise ValueError('Custom model size is outside supported limits')
    with path.open('rb') as f:
        def raw(n):
            if n < 0 or f.tell() + n > size or f.tell() + n > 64 * 1024**2:
                raise ValueError('Invalid or excessive GGUF metadata')
            b = f.read(n)
            if len(b) != n:
                raise ValueError('Truncated GGUF header')
            return b
        def number(fmt):
            return struct.unpack('<'+fmt, raw(struct.calcsize('<'+fmt)))[0]
        def string(keep=True):
            n = number('Q')
            if n > 1024**2:
                raise ValueError('GGUF string exceeds supported length')
            value = raw(n)
            return value.decode('utf-8') if keep else None
        def value(kind, keep, array=False):
            if kind == 8:
                return string(keep)
            if kind in _SCALAR:
                v = number(_SCALAR[kind])
                return v if keep else None
            if kind == 9 and not array:
                subtype, count = number('I'), number('Q')
                if count > 2000000 or subtype == 9:
                    raise ValueError('Unsupported GGUF array')
                for _ in range(count):
                    value(subtype, False, True)
                return None
            raise ValueError('Unsupported GGUF metadata type')
        if raw(4) != b'GGUF' or number('I') != 3:
            raise ValueError('Choose a little-endian GGUF v3 model')
        tensors, entries = number('Q'), number('Q')
        if not 3 <= tensors <= 100000 or not 1 <= entries <= 10000:
            raise ValueError('Invalid GGUF table sizes')
        meta = {}
        for _ in range(entries):
            key = string()
            if key in meta:
                raise ValueError('Duplicate GGUF metadata key')
            kind = number('I')
            keep = (key.startswith('general.') or key.startswith('qwen3.') or
                    key in ('split.count', 'tokenizer.chat_template', 'tokenizer.ggml.model'))
            meta[key] = value(kind, keep)
        if meta.get('general.architecture') != 'qwen3' or meta.get('split.count', 1) != 1:
            raise ValueError('Custom chat downloads currently support single-file dense Qwen3 GGUF models')
        if meta.get('general.type', 'model') != 'model':
            raise ValueError('Adapters and projectors are not complete chat models')
        if not isinstance(meta.get('tokenizer.chat_template'), str) or not meta['tokenizer.chat_template'].strip():
            raise ValueError('The model needs an embedded chat template')
        if meta.get('tokenizer.ggml.model') != 'gpt2':
            raise ValueError('Unsupported Qwen3 tokenizer')
        def integer(key, low, high):
            v = meta.get(key)
            if type(v) is not int or not low <= v <= high:
                raise ValueError('Invalid custom model metadata: '+key)
            return v
        layers = integer('qwen3.block_count', 1, 256)
        context = integer('qwen3.context_length', 512, 1048576)
        embedding = integer('qwen3.embedding_length', 128, 32768)
        heads = integer('qwen3.attention.head_count', 1, 256)
        kv_heads = integer('qwen3.attention.head_count_kv', 1, heads)
        key_length = meta.get('qwen3.attention.key_length', embedding // heads)
        if type(key_length) is not int or not 16 <= key_length <= 1024:
            raise ValueError('Unsupported attention dimensions')
        alignment = meta.get('general.alignment', 32)
        if type(alignment) is not int or not 1 <= alignment <= 4096 or alignment & (alignment-1):
            raise ValueError('Invalid GGUF tensor alignment')
        ranges, names = [], set()
        for _ in range(tensors):
            name = string()
            if name in names:
                raise ValueError('Duplicate GGUF tensor')
            names.add(name)
            dimensions = number('I')
            if not 1 <= dimensions <= 4:
                raise ValueError('Invalid GGUF tensor dimensions')
            shape = [number('Q') for _ in range(dimensions)]
            if any(d < 1 or d > 2**24 for d in shape):
                raise ValueError('Invalid GGUF tensor shape')
            quant, offset = number('I'), number('Q')
            if quant not in _QUANT:
                raise ValueError('Unsupported GGUF quantization; choose F16/BF16, Q4/Q5/Q8 or a K quant')
            block, width = _QUANT[quant]
            if shape[0] % block or offset % alignment:
                raise ValueError('Invalid GGUF quantization block or offset')
            ranges.append((offset, offset + math.prod(shape)//block*width))
        required = {'token_embd.weight', 'output_norm.weight'} | {
            'blk.'+str(i)+'.attn_q.weight' for i in range(layers)}
        if not required <= names:
            raise ValueError('Incomplete Qwen3 model tensor inventory')
        start = (f.tell() + alignment - 1) // alignment * alignment
        end = 0
        for lo, hi in sorted(ranges):
            if lo < end or start + hi > size:
                raise ValueError('Overlapping or truncated GGUF tensor data')
            end = hi
    kv_gib = 2 * layers * kv_heads * key_length * 2 * 8192 / 1024**3
    return dict(layers=layers, max_context_tokens=min(context,32768),
                buffer_base_gib=2.0, buffer_per_8192_gib=max(1.0, kv_gib*1.25),
                architecture='qwen3', vision=False, automatic=False,
                automatic_uncensored=False, cpu_auto=False)


def _identity(path):
    s = path.stat()
    return (str(path.resolve()), s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def register_installed(root, policy):
    root = Path(root).resolve()
    directory = root / 'Maintenance/Imports'
    for receipt in sorted(directory.glob('custom-*.json')):
        if receipt.stat().st_size > 32768:
            continue
        try:
            data = json.loads(receipt.read_text('utf-8'))
            request = data['request']; pin = request['sha256']
            if (data.get('kind') != 'portalai-custom-model' or data.get('verified') is not True or
                    request.get('accepted') is not True or not re.fullmatch('[0-9a-f]{64}', pin)):
                continue
            relative = 'LLM/custom/'+pin+'.gguf'
            path = root / relative
            if data['path'] != relative or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            if request['variant'] not in ('standard', 'uncensored') or path.stat().st_size != request['bytes']:
                continue
            if (root/'Agent/academic_policy.py').exists():
                from academic_policy import require_asset
                require_asset(request)
            key = _identity(path)
            if key not in _inspected:
                _inspected[key] = inspect_gguf(path)
            model = dict(_inspected[key], id='custom-'+pin, path=relative,
                         label=str(request['label'])[:100]+' (custom)', variant=request['variant'],
                         priority=0, sha256=pin, custom_sha256=pin, custom_bytes=request['bytes'])
            if model['id'] not in {m['id'] for m in policy['models']}:
                policy['models'].append(model)
        except (OSError, ValueError, TypeError, KeyError):
            # A bad optional record must not break the built-in model catalog.
            continue


def verify_selected(path, model):
    """Full hash on first admission and after a file changes, before loading."""
    if not model.get('custom_sha256'):
        return
    path = Path(path)
    key = (_identity(path), model['custom_sha256'])
    if key in _verified:
        return
    if path.stat().st_size != model['custom_bytes']:
        raise ValueError('Custom model size changed; install and review it again')
    with path.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != model['custom_sha256']:
            raise ValueError('Custom model checksum changed; install and review it again')
    inspect_gguf(path)
    _verified.add(key)
