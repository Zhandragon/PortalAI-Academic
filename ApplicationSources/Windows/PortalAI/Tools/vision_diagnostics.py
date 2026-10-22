"""Public small-vision inventory, routing and optional checksum verification.

No account data, model loading, prompts, downloads, settings writes or inference.
"""
import hashlib
import json
from pathlib import Path
import stat
import sys

VARIANTS = ('qwen-vl2-q4','qwen-vl2-abliterated-q4','qwen-vl4-q4','qwen-vl4-abliterated-q4')


def rows(root, *, verify=False):
    root=Path(root).resolve();result=[]
    def add(status,label,detail):result.append({'status':status,'label':label,'detail':detail})
    try:
        sys.path.insert(0,str(root/'Agent'))
        from runtime_policy import load_policy
        from chat_vision_policy import candidates
        policy=load_policy(root);models={m['id']:m for m in policy['models']}
        pins=json.loads((root/'Agent/small_vision_assets.json').read_text(encoding='utf-8'))
        indexed={p['path']:p for p in pins}
        if len(indexed)!=8:raise ValueError('Expected eight pinned model/projector assets')
        for name in VARIANTS:
            model=models.get(name)
            if model is None or not model.get('vision_only') or not model.get('projector'):
                add('FAIL',name,'Missing vision-only model or projector registration');continue
            for kind in ('path','projector'):
                rel=model[kind];pin=indexed.get(rel)
                if pin is None:
                    add('FAIL',name+' '+kind,'No pinned size and SHA-256');continue
                path=root/rel
                try:
                    if not path.resolve().is_relative_to(root):raise ValueError('Asset outside installation')
                    before=path.lstat()
                    if not stat.S_ISREG(before.st_mode) or path.is_symlink() or getattr(before,'st_file_attributes',0)&0x400:
                        raise ValueError('Asset is not a regular local file')
                    if before.st_size!=pin['bytes']:raise ValueError('Size does not match pinned asset')
                    if verify:
                        digest=hashlib.sha256()
                        with path.open('rb') as stream:
                            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
                        after=path.stat()
                        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                            raise ValueError('Asset changed while verifying')
                        if digest.hexdigest()!=pin['sha256']:raise ValueError('SHA-256 does not match pinned asset')
                    add('PASS',name+' '+kind,rel+(' · SHA-256 verified' if verify else ' · size checked; checksum not run'))
                except FileNotFoundError:
                    add('WARN',name+' '+kind,rel+' · not installed; automatic routing cannot use this pair')
                except (OSError,ValueError) as exc:add('FAIL',name+' '+kind,str(exc))
        # Exercise routing using synthetic policy only. No account policy is read or written.
        for variant in ('standard','uncensored'):
            probe={**policy,'selection':'auto','variant_preference':variant,'vision_routing':'automatic'}
            for level,size in (('fast','2'),('balanced','4')):
                got=candidates(level,probe)
                expected=f'qwen-vl{size}'+('-abliterated' if variant=='uncensored' else '')+'-q4'
                add('PASS' if got and got[0]==expected else 'FAIL',f'Image routing · {variant} {level}',str(got)+' · policy check only; no inference')
    except Exception as exc:add('FAIL','Small vision diagnostics',str(exc))
    return result
