"""Profile-bound, read-only process and lifecycle observations for the GUI.

No listener/process is controlled here. A live process is attributed only after
its executable is located inside this portable root. Command arguments/prompts
are never published. CPU is percent of the whole host; RAM is resident memory.
"""
import ctypes
import json
import os
from pathlib import Path
import re
import time


def owned(root, executable):
    try: return Path(executable).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError, TypeError): return False


def process_stats(pid):
    if os.name != 'nt':
        base = Path('/proc')/str(pid)
        executable = os.readlink(base/'exe')
        fields = (base/'stat').read_text().rsplit(')', 1)[1].split()
        ticks = os.sysconf('SC_CLK_TCK')
        return {'exe':executable, 'identity':fields[19], 'cpu':(int(fields[11])+int(fields[12]))/ticks,
                'ram':int((base/'statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE'),
                'command':(base/'cmdline').read_bytes()[:32768].replace(b'\0', b' ').decode('utf-8', 'replace')}
    from ctypes import wintypes as w
    lib = ctypes.WinDLL('kernel32', use_last_error=True)
    lib.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]; lib.OpenProcess.restype = w.HANDLE
    lib.CloseHandle.argtypes = [w.HANDLE]
    lib.QueryFullProcessImageNameW.argtypes = [w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    lib.GetProcessTimes.argtypes = [w.HANDLE,*([ctypes.POINTER(ctypes.c_ulonglong)]*4)]
    handle = lib.OpenProcess(0x1000, False, pid)
    if not handle: raise OSError('Process unavailable')
    try:
        size = w.DWORD(32768); image = ctypes.create_unicode_buffer(size.value)
        if not lib.QueryFullProcessImageNameW(handle,0,image,ctypes.byref(size)): raise OSError('Process identity unavailable')
        created, exited, kernel, user = [ctypes.c_ulonglong() for _ in range(4)]
        if not lib.GetProcessTimes(handle,*(ctypes.byref(x) for x in (created,exited,kernel,user))): raise OSError('CPU unavailable')
        class MEMORY(ctypes.Structure):
            _fields_ = [('cb',w.DWORD),('faults',w.DWORD)]+[(name,ctypes.c_size_t) for name in
                ('peak','working','poolpeak','pool','nonpeak','non','page','pagepeak','private')]
        memory = MEMORY(); memory.cb = ctypes.sizeof(memory)
        psapi = ctypes.WinDLL('psapi'); psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE,ctypes.c_void_p,w.DWORD]
        ram = memory.working if psapi.GetProcessMemoryInfo(handle,ctypes.byref(memory),memory.cb) else None
        return {'exe':image.value,'identity':created.value,'cpu':(kernel.value+user.value)/1e7,'ram':ram}
    finally: lib.CloseHandle(handle)


def label_for(executable, command):
    # Names are bounded identifiers only; never publish argument values.
    files = re.findall(r'(?i)([a-z0-9_+.-]+\.py)(?:["\s]|$)', command or '')
    name = files[0] if files else Path(executable).name
    if name in ('ai_tools.py','web_tools.py','science_tools.py'):
        match = re.search(re.escape(name)+r'["\s]+([a-z][a-z0-9_.-]{0,60})(?:\s|$)', command or '')
        if match: return name.removesuffix('.py')+' · '+match[1]
    return {'_worker.py':'ProteinMPNN worker','llama-server.exe':'Chat model server',
            'llama-server':'Chat model server','ai_tools.py':'Media/science tool',
            'web_tools.py':'Web tool','science_tools.py':'Science tool',
            'scientific_tool_bridge.py':'Science workbench','protein_design_worker.py':'ProteinMPNN',
            'main.py':'Model service', 'ffmpeg.exe':'FFmpeg','ffmpeg':'FFmpeg'}.get(name, name)[:80]


class RuntimeActivity:
    def __init__(self, root, *, profile=None):
        from profile_context import CapturedProfile
        self.root = Path(root).resolve(); self.profile = profile or CapturedProfile(root)
        self.previous = {}; self.last_time = None; self.states = {}; self.offset = None; self.log_identity = None
        self.pending = b''

    def processes(self):
        self.profile.check()
        if os.name == 'nt':
            from portableai_common import iter_processes, process_command_line
            candidates = [pid for pid,_ in iter_processes()]
        else:
            candidates = [int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()]
            process_command_line = lambda pid: ''
        now = time.monotonic(); current = {}; rows = []; events = []
        for pid in candidates:
            try:
                data = process_stats(pid)
                if not owned(self.root,data['exe']): continue
                old = self.previous.get(pid)
                same = old and old['identity'] == data['identity']
                data['label'] = old['label'] if same else label_for(data['exe'],data.get('command') or process_command_line(pid))
                delta = now-self.last_time if self.last_time is not None else 0
                usage = max(0,min(100,100*(data['cpu']-old['cpu'])/delta/(os.cpu_count() or 1))) if same and delta > 0 else None
                current[pid] = data
                rows.append({'pid':pid,'label':data['label'],'cpu':usage,'ram':data['ram'], 'identity':str(data['identity'])})
                if not same: events.append(f"Process observed: {data['label']} · PID {pid}")
            except (OSError, ValueError, IndexError, ProcessLookupError): continue
        for pid,data in self.previous.items():
            if pid not in current: events.append(f"Process no longer observed: {data['label']} · PID {pid} (outcome not inferred)")
        self.previous = current; self.last_time = now
        self.profile.check()
        return rows, events

    def _read(self, name):
        path = self.root/'Agent/.runtime'/name
        try:
            if path.is_symlink() or path.stat().st_size > 32768: return {}
            data = json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError, ValueError): return {}

    def lifecycle(self, rows):
        self.profile.check(); pids = {row['pid'] for row in rows}; result = []; events = []
        for name, title, fields in (
            ('gpu_exclusive_owner.json','GPU lease',('owner',)),
            ('gpu_model_state.json','Declared model stage',('service','tool','models')),
        ):
            value = self._read(name)
            if value.get('pid') not in pids: value = {}
            details = ' · '.join(str(value[k])[:240] for k in fields if value.get(k)) if value else ''
            if details: result.append(title+': '+details)
            previous = self.states.get(name)
            if previous != details and (previous is not None or details):
                events.append(title+': '+(details or 'released / no current owner'))
            self.states[name] = details
        # Tail only new bounded lifecycle lines; a fresh GUI never replays old
        # handoffs as current work. Rotation/truncation resets the cursor safely.
        path = self.root/'Agent/.runtime/qwen_vram_handoff.log'
        try:
            stat = path.stat(); identity = (stat.st_dev,stat.st_ino)
            if self.offset is None or identity != self.log_identity:
                self.offset = stat.st_size; self.pending = b''
            if stat.st_size < self.offset: self.offset = 0; self.pending = b''
            with path.open('rb') as stream:
                stream.seek(max(self.offset, stat.st_size-32768)); data = stream.read(32768); self.offset = stream.tell()
            self.log_identity = identity
            pieces = (self.pending+data).split(b'\n'); self.pending = pieces.pop()[-2048:]
            for line in pieces:
                line = line.decode('utf-8','replace').rstrip('\r')
                if any(word in line for word in ('BEGIN','END','RECOVERY','FAILED','SKIP')):
                    events.append('Handoff · '+line[:500])
        except OSError: pass
        self.profile.check()
        return result, events


def format_processes(rows, gpu_processes=None, counters=None):
    lines = ['PID     CPU % host   RAM GiB   GPU % peak   VRAM GiB   Shared GiB   Component / worker']
    for row in rows:
        cpu = 'pending' if row.get('cpu') is None else f"{row['cpu']:.1f}%"
        ram = 'n/a' if row.get('ram') is None else f"{row['ram']/1024**3:.2f}"
        measured = (counters or {}).get(str(row['pid']), {}) if row.get('cpu') is not None else {}
        vram = measured.get('dedicated', (gpu_processes or {}).get(str(row['pid'])) if row.get('cpu') is not None else None)
        vram = 'n/a' if vram is None else f'{vram:.2f}'
        gpu = 'n/a' if measured.get('gpu') is None else f"{measured['gpu']:.1f}%"
        shared = 'n/a' if measured.get('shared') is None else f"{measured['shared']:.2f}"
        lines.append(f"{row['pid']:<7} {cpu:>9} {ram:>9} {gpu:>12} {vram:>10} {shared:>12}   {row['label']}")
    if not rows: lines.append('No owned processes observed in this sample.')
    return '\n'.join(lines)
