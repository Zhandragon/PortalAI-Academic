"""Per-installation service endpoints and same-OS-user host coordination.

Only public endpoint metadata and OS locks live on the host. Accounts, browser
state, messages and executables stay on the portable drive. A port is never
evidence of ownership. Existing service launchers retain their identity checks.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {'qwen':8080, 'comfyui':8188, 'acestep':8001, 'preview':8765, 'agents':8790, 'gateway':18080}

def host_directory():
    if os.name == 'nt':
        base = Path(os.environ['LOCALAPPDATA'])
    else:
        base = Path(os.environ.get('XDG_RUNTIME_DIR') or (Path.home()/'.cache'))
    path = base/'PortalAI'/'coordination-v1'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path

def instance_key(root=ROOT):
    return hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode()).hexdigest()[:24]

def _try_lock(handle):
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False

def _unlock(handle):
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

def _handle(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    h = path.open('a+b')
    if h.tell() == 0: h.write(b'0'); h.flush()
    return h

@contextmanager
def locked(path, timeout=20):
    h = _handle(path); deadline = time.monotonic()+timeout
    while not _try_lock(h):
        if time.monotonic() >= deadline:
            h.close(); raise TimeoutError('PortalAI coordination is busy')
        time.sleep(.05)
    try: yield
    finally: _unlock(h); h.close()

def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(value, f, indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally: tmp.unlink(missing_ok=True)

def settings(root=ROOT):
    path = Path(root)/'Agent/instance-settings.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    ports = value.get('ports', {})
    if set(ports)-set(DEFAULTS): raise ValueError('Unknown service in port settings')
    for key, number in ports.items():
        if type(number) is not int or not (number == 0 or 1024 <= number <= 65535):
            raise ValueError('Ports must be 0 (automatic) or 1024..65535')
    manual = [p for p in ports.values() if p]
    if len(set(manual)) != len(manual): raise ValueError('Service ports must differ')
    return {'name':str(value.get('name') or Path(root).name)[:80], 'ports':ports}

def save_settings(root, value):
    # Validation is performed before replacing the previous settings.
    ports = value.get('ports', {})
    if set(ports)-set(DEFAULTS) or any(type(p) is not int or not (p == 0 or 1024 <= p <= 65535) for p in ports.values()):
        raise ValueError('Ports must be 0 (automatic) or 1024..65535')
    manual = [p for p in ports.values() if p]
    if len(set(manual)) != len(manual): raise ValueError('Service ports must differ')
    atomic(Path(root)/'Agent/instance-settings.json', {'name':str(value.get('name',''))[:80], 'ports':ports})

def _active(path):
    h = _handle(path)
    try:
        if not _try_lock(h): return True
        _unlock(h); return False
    finally: h.close()

def _available(port_number):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name == 'nt': s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try: s.bind(('127.0.0.1', port_number)); return True
        except OSError: return False

def _owned_existing(root, number, service):
    if service in ('agents','gateway'):return False
    try:
        if os.name=='nt':
            from service_manager import _listening_pids, _process_image_path, _process_command_line
            pids=_listening_pids(number)
            if not pids:return False
            for pid in pids:
                image=_process_image_path(pid)
                if not image or not Path(image).resolve().is_relative_to(root):return False
                if service=='qwen' and Path(image).name.lower()!='llama-server.exe':return False
                if service!='qwen':
                    command=(_process_command_line(pid) or '').lower()
                    if not any(marker in command for marker in {'comfyui':('comfyui','main.py'),'acestep':('acestep','ace-step'),'preview':('media_server.py',)}[service]):return False
            return True
        from portable_process import listeners,identity,owned,is_llama
        rows=[identity(pid) for pid in listeners(number)]
        return bool(rows) and all(is_llama(row,root) if service=='qwen' else owned(row,root) for row in rows)
    except (OSError,RuntimeError,ValueError):return False

def endpoints(root=ROOT):
    root = Path(root).resolve()
    path = root/'Agent/.runtime/instance-endpoints.json'
    if path.exists():
        row = json.loads(path.read_text(encoding='utf-8'))
        if row.get('key') == instance_key(root) and _active(host_directory()/(row['key']+'.lease')):
            return row['ports']
    return {k:settings(root)['ports'].get(k) or v for k,v in DEFAULTS.items()}

def port(service, root=ROOT):
    return int(endpoints(root)[service])

def url(service, path='', root=ROOT):
    return 'http://127.0.0.1:'+str(port(service, root))+path

class InstanceSession:
    def __init__(self, root=ROOT, directory=None):
        self.root = Path(root).resolve(); self.directory = directory or host_directory()
        self.key = instance_key(self.root); self.handle = None

    def start(self):
        config = settings(self.root)
        with locked(self.directory/'allocation.lock'):
            h = _handle(self.directory/(self.key+'.lease'))
            if not _try_lock(h): h.close(); raise RuntimeError('This PortalAI installation already has a controller')
            self.handle = h
            try:
                claimed = set()
                for path in self.directory.glob('*.json'):
                    row = json.loads(path.read_text(encoding='utf-8'))
                    if row.get('key') != self.key and _active(self.directory/(row['key']+'.lease')):
                        if row.get('root'):
                            other=Path(row['root']).resolve()
                            if other.is_relative_to(self.root) or self.root.is_relative_to(other):
                                raise RuntimeError('Run independent installations in sibling folders, not nested inside another active PortalAI root')
                        claimed.update(row['ports'].values())
                previous_path=self.root/'Agent/.runtime/instance-endpoints.json'
                previous=json.loads(previous_path.read_text()) if previous_path.exists() else {}
                previous_ports=previous.get('ports',{}) if previous.get('key')==self.key else {}
                selected = {}
                for service, default in DEFAULTS.items():
                    requested = config['ports'].get(service, 0)
                    candidates = [requested] if requested else [previous_ports.get(service,default),default]+list(range(19000, 29000))
                    chosen = next((p for p in candidates if p not in claimed and (_available(p) or (p==previous_ports.get(service) and _owned_existing(self.root,p,service)))), None)
                    if chosen is None: raise RuntimeError(f'{service} port {requested} is in use; choose another port or automatic')
                    selected[service] = chosen; claimed.add(chosen)
                self.record = {'version':1, 'key':self.key, 'root':str(self.root), 'name':config['name'], 'ports':selected, 'pid':os.getpid()}
                atomic(self.directory/(self.key+'.json'), self.record)
                atomic(self.root/'Agent/.runtime/instance-endpoints.json', self.record)
                if 'service_manager' in sys.modules:
                    for key in ('qwen','comfyui','acestep'):sys.modules['service_manager'].SERVICES[key]['port']=selected[key]
                return self
            except BaseException: self.close(); raise

    def close(self):
        if self.handle is not None:
            _unlock(self.handle); self.handle.close(); self.handle = None

    def __enter__(self): return self.start()
    def __exit__(self, *args): self.close()

def status(root=ROOT):
    return {'instance':instance_key(root), 'configured':settings(root), 'active_ports':endpoints(root),
            'scope':'same OS user; loopback only; manual settings apply on next launch',
            'resource_policy':'independent model memory admission; host-wide GPU operation lease'}
