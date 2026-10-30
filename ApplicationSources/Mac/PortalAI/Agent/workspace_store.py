"""Small shared storage boundary for account-scoped knowledge, connections and flows."""
import hashlib
import json
from pathlib import Path
import re
import uuid

from profile_paths import capture, private_path, ProfileLocked
from runtime_policy import atomic_json, require_space
from mission_runner import process_lock


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('Invalid workspace record ID')
    return value


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def read_json(path, limit=2*1024**2):
    with Path(path).open('rb') as stream:
        data=stream.read(limit+1)
    if len(data)>limit:raise ValueError('Workspace record exceeds its size limit')
    return json.loads(data)


class Workspace:
    def __init__(self, root, area, check=None):
        self.root=Path(root).resolve();self.identity=capture(self.root)
        self.area=area;self.check_callback=check

    def check(self):
        if capture(self.root)!=self.identity:raise ProfileLocked('This workspace login ended')
        if self.check_callback:self.check_callback()

    def path(self, relative=''):
        self.check()
        return private_path(self.root, 'Data/'+self.area+('/'+relative if relative else ''), context=self.identity)

    def save(self, relative, value):
        if len(encoded(value))>2*1024**2:raise ValueError('Workspace record exceeds its size limit')
        require_space(self.root, 4*1024**2, for_outputs=True)
        self.check();atomic_json(self.path(relative), value)

    def lock(self, name='workspace'):
        return process_lock(self.path(name+'.lock'))

    def records(self, directory):
        self.check()
        from profile_hydration import file_listing
        relative='Data/'+self.area+'/'+directory
        listing=file_listing(self.root, relative)
        self.check()
        result=[]
        for name in listing['names']:
            p=Path(name)
            if p.parent.as_posix()==relative and re.fullmatch('[a-f0-9]{32}\\.json',p.name):
                result.append(p.stem)
        return sorted(result)

    def new_id(self):return uuid.uuid4().hex


def portable_source(root, value):
    """Save explicit import locations relative to this SSD when possible."""
    root=Path(root).resolve();p=Path(value).resolve()
    if p.anchor.casefold()==root.anchor.casefold():
        return {'drive_relative':p.relative_to(p.anchor).as_posix()}
    return {'external':str(p)}


def source_path(root, locator):
    if set(locator)=={'drive_relative'}:
        from profile_paths import _relative
        return Path(Path(root).anchor)/_relative(locator['drive_relative'])
    if set(locator)=={'external'} and Path(locator['external']).is_absolute():return Path(locator['external'])
    raise ValueError('Invalid source location')
