"""Explicit offline factory reset of the adjacent portable installation.

No passwords are read, no vault is decrypted, and no process is stopped. The
host filesystem owner explicitly discards all local account data. Ordinary
PortalAI authentication, profile sealing and HA pairing code are unchanged.
Imports, opening the confirmation window, and Cancel never write data.
"""
from __future__ import annotations
import contextlib
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import stat
import sys
import threading
import time

VERSION = '1.1.0'
CONFIRMATION = 'CONFIRM'
JOURNAL_KIND = 'portalai-offline-factory-reset-v1'
# Data-only scopes. Never widen these to the portable root, models or runtimes.
PRIVATE_SCOPES = (
    'Private', 'Data', 'Outputs', 'User Folder', 'Logs', 'Benchmarks', 'Patch/Videos',
    'Cache/MuseTalk', 'Cache/Web', 'Cache/WebTests', 'Cache/Gradio', 'Cache/tmp',
    'Cache/Temp', 'Cache/ScaledEditValidation', 'Cache/MediaEdit', 'Cache/MAFFT',
    'Cache/ComfyWorkers', 'Cache/LinuxWorkers', 'Cache/Whisper/runtime',
    'Cache/MediaWorkers', 'PortableCache/Qwen3-TTS/Temp', 'PortableCache/Science',
    'Music/ACE-Step-1.5/.cache', 'Music/ACE-Step-1.5/gradio_outputs',
    'MusicUnderstanding/cache/demucs', 'OpenWebUI/data', 'OpenWebUI/.runtime',
    'SpeechToText/.runtime', 'Agent/.runtime/dialogue', 'Agent/.runtime/mmaudio_jobs',
    'Agent/.runtime/video_range_edit', 'Agent/.runtime/tmp',
    'Generative/ComfyUI_windows_portable/ComfyUI/input',
    'Generative/ComfyUI_windows_portable/ComfyUI/output',
    'Generative/ComfyUI_windows_portable/ComfyUI/temp',
    'Generative/ComfyUI_windows_portable/ComfyUI/user',
    'Backups', 'Maintenance/Reports', 'Maintenance/Archive', 'Maintenance/Endurance',
    'Maintenance/Validation', 'Maintenance/Patches', 'Maintenance/AccountSmoke',
    'Maintenance/Diagnostics', 'Maintenance/RootOrganization', 'Maintenance/Rollback',
    'Cache/ProfileShutdownTests', 'Cache/LinuxValidation', 'Runtime/LinuxValidation',
    'HomeAssistant/pairing', 'HomeAssistant/state', 'ControlCenter/LegacyDiagnosis',
    'ControlCenter/PortableAI_Crash.log', 'ControlCenter/PortableAI_Freeze.log',
    'ControlCenter/PortableAI_Launcher.log',
    'Sandbox/Security/agent_token.txt', 'Sandbox/Security/OPEN_GUI_CONNECTION.txt',
    'Sandbox/Security/sandbox_runtime.json',
    'Maintenance/Repair/Repair_MusicUnderstanding_v15_40b.log',
    'Maintenance/Repair/Repair_MusicUnderstanding_v15_40c.log',
    'Cache/Bootstrap/python-3.12.10-install.log',
    'Cache/Bootstrap/python-3.12.10-install_000_exe_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_001_dev_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_002_test_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_003_doc_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_004_tcltk_JustForMe.log',
    'Cache/Bootstrap/python-3.12.10-install_005_pip_JustForMe.log',
    'Installer/Install_MusicUnderstanding_v15_40d.log',
    'Installer/Install_OpenWebUI_Remote_v15_42.log',
    'Installer/Installers/logs/opengui_dist_win_v15_38.log',
    'Installer/Installers/logs/opengui_pnpm_install_v15_38.log',
    'OpenWebUI/Installer/Install_OpenWebUI_Remote_v15_42b.log',
    'SecureAgent/Updater/SecureAgent_Parity_v15_43.log',
    'Voice/Qwen3-TTS/hf_cache/xet/logs/xet_20260913T125417684-0400_4652.log',
)
COMPANION_SCOPES = ('Connections', 'state', 'Recovery', 'Handoffs', 'Tests/Validation')
RUNTIME_KEEP = frozenset((
    'qwen_last_stop.json', 'qwen_handoff_generation.json',
    'component_runtime_locks.json', 'control_center_theme.json', 'comfy_vram_profile.txt',
))

class ResetError(RuntimeError): pass

def native(path):
    text = str(path)
    return '\\\\?\\'+text if os.name == 'nt' and not text.startswith('\\\\?\\') else text

def file_id(st): return (st.st_dev, st.st_ino)
def identity(st): return (*file_id(st), st.st_size, st.st_mtime_ns)

def safe_path(base, path):
    base, path = Path(base), Path(path)
    if not base.is_absolute() or not path.is_relative_to(base) or '..' in path.parts:
        raise ResetError('A reset path escapes the selected installation.')
    # Check all ancestors, including the drive and the package root.
    for current in [*reversed(path.parents), path]:
        try: st = os.lstat(native(current))
        except FileNotFoundError: continue
        if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
            raise ResetError('Linked folders/files are refused. No link target will be reset.')
    if path.resolve() != path:
        raise ResetError('The selected installation resolves to another location.')
    return path

def processes():
    """Read process ownership using Windows APIs, without a shell or elevation."""
    if os.name != 'nt': raise ResetError('This reset launcher supports Windows only.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR*260)]
    kernel.CreateToolhelp32Snapshot.argtypes=(wintypes.DWORD,wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=(wintypes.HANDLE,ctypes.POINTER(Entry))
    kernel.Process32NextW.argtypes=(wintypes.HANDLE,ctypes.POINTER(Entry))
    kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=(wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    snap=kernel.CreateToolhelp32Snapshot(2,0)
    if snap in (None,ctypes.c_void_p(-1).value):raise ResetError('Cannot inventory running processes.')
    result=[]
    try:
        entry=Entry();entry.dwSize=ctypes.sizeof(entry)
        more=kernel.Process32FirstW(snap,ctypes.byref(entry))
        if not more:raise ResetError('Cannot read running process inventory.')
        while more:
            pid=entry.th32ProcessID;name=entry.szExeFile
            handle=kernel.OpenProcess(0x1000,False,pid)
            image=None
            if handle:
                try:
                    buf=ctypes.create_unicode_buffer(32768);n=wintypes.DWORD(len(buf))
                    if kernel.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(n)):image=buf.value
                finally:kernel.CloseHandle(handle)
            result.append((pid,image,name))
            more=kernel.Process32NextW(snap,ctypes.byref(entry))
    finally:kernel.CloseHandle(snap)
    return result

@contextlib.contextmanager
def windows_mutex(name):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR)
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    handle=kernel.CreateMutexW(None,False,name);error=ctypes.get_last_error()
    if not handle or error==183:
        if handle:kernel.CloseHandle(handle)
        raise ResetError('PortalAI or another reset is open for this folder. Close it normally first.')
    try:yield
    finally:kernel.CloseHandle(handle)

@contextlib.contextmanager
def byte_lock(path):
    import msvcrt
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(native(path),'a+b') as f:
        if not f.tell():f.write(b'0');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as e:raise ResetError('PortalAI/projection still owns this folder. Close it normally.') from e
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

class FactoryReset:
    def __init__(self, root):
        self.root=Path(root).absolute()
        self.peer=self.root.parent/'PortalAI-Projection'
        self.volume_ids=None
        self.guard=self.root/'Private/Reset/transaction.json'
        self.skips={self.root/'Private/profile-runtime.lock',self.peer/'state/projection.lock',self.guard}

    def validate_roots(self):
        if self.root.name!='PortalAI' or self.root.parent==self.root:
            raise ResetError('The main portable application folder must be named PortalAI.')
        candidates=[]
        for relative in ('PortalAI-Projection','Utilities/PortalAI-Projection'):
            candidate=safe_path(self.root.parent,self.root.parent/relative)
            if candidate.exists():candidates.append(candidate)
        if len(candidates)!=1:
            raise ResetError('Keep exactly one PortalAI-Projection folder: at the portable root or inside Utilities.')
        peer=candidates[0]
        if self.volume_ids is not None and peer!=self.peer:
            raise ResetError('The projection folder moved during reset. Reset stopped.')
        self.peer=peer
        self.skips={self.root/'Private/profile-runtime.lock',self.peer/'state/projection.lock',self.guard}
        for root in (self.root,self.peer):
            safe_path(root,root)
            if not root.is_dir():raise ResetError('The PortalAI and projection folders must be complete portable folders.')
        for relative in ('PortalAI.exe','Runtime/BootstrapPython/pythonw.exe','ControlCenter/control_center_bootstrap.py'):
            p=safe_path(self.root,self.root/relative)
            if not p.is_file():raise ResetError('The expected portable application files are missing.')
        for relative in ('app/projection_ui.py','Runtime/Python/pythonw.exe'):
            p=safe_path(self.peer,self.peer/relative)
            if not p.is_file():raise ResetError('The expected projection companion files are missing.')
        ids=tuple(file_id(os.stat(native(p))) for p in (self.root,self.peer))
        if self.volume_ids is not None and ids!=self.volume_ids:
            raise ResetError('The drive or folder identity changed. Reset stopped.')
        self.volume_ids=ids

    def require_closed(self):
        allowed={os.getpid()}
        launchers={self.root.parent/'PortalAIFullReset.exe',
            self.root.parent/'Utilities/PortalAI-Reset/PortalAIFullReset.exe'}
        for pid,image,name in processes():
            if pid in allowed:continue
            if pid==os.getppid() and image and Path(image) in launchers:continue
            if image:
                p=Path(image)
                if p.is_relative_to(self.root) or p.is_relative_to(self.peer) or p==self.root.parent/'PortalAI.exe':
                    raise ResetError('Close PortalAI and its projection companion normally, then retry. No process was stopped.')
            elif name.lower() in ('python.exe','pythonw.exe','portalai.exe'):
                raise ResetError('A possible PortalAI process could not be identified. Close it normally before resetting.')

    @contextlib.contextmanager
    def guards(self):
        self.validate_roots();self.require_closed()
        h=14695981039346656037
        for c in str(self.root).lower():h=((h^ord(c))*1099511628211)&((1<<64)-1)
        with windows_mutex(f'Local\\PortalAI.GUI.{h>>32:08x}{h&0xffffffff:08x}'):
            with byte_lock(safe_path(self.root,self.root/'Private/profile-runtime.lock')):
                with byte_lock(safe_path(self.peer,self.peer/'state/projection.lock')):
                    self.require_closed();yield

    def scopes(self):
        values=[(self.root,self.root/s) for s in PRIVATE_SCOPES]
        values += [(self.peer,self.peer/s) for s in COMPANION_SCOPES]
        runtime=safe_path(self.root,self.root/'Agent/.runtime')
        if runtime.exists():
            values += [(self.root,p) for p in runtime.iterdir()
                if p.name not in RUNTIME_KEEP and not p.name.endswith('.lock')]
        unique=sorted(set(values),key=lambda row:str(row[1]))
        return [(b,p) for b,p in unique if not any(p!=other and p.is_relative_to(other) for _,other in unique)]

    def inventory(self):
        files={};dirs={}
        def add(base,p):
            safe_path(base,p)
            if p in self.skips:return
            st=os.lstat(native(p))
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:
                raise ResetError('A linked or nonregular data file needs manual review.')
            files[p]=(base,identity(st))
        def error(e):raise e
        for base,scope in self.scopes():
            safe_path(base,scope)
            if not scope.exists():continue
            if scope.is_file():add(base,scope);continue
            for d,ns,fs in os.walk(native(scope),onerror=error,followlinks=False):
                path=Path(d.removeprefix('\\\\?\\'));safe_path(base,path)
                dirs[path]=(base,file_id(os.lstat(native(path))))
                for n in ns:safe_path(base,path/n)
                for n in fs:add(base,path/n)
        return files,dirs

    def mark_pending(self):
        safe_path(self.root,self.guard)
        if self.guard.exists():
            if self.guard.stat().st_size>4096:raise ResetError('An existing account recovery transaction needs review.')
            data=json.loads(self.guard.read_text(encoding='utf-8'))
            if data.get('kind')!=JOURNAL_KIND or data.get('identity')!=[list(i) for i in self.volume_ids]:
                raise ResetError('An existing account recovery transaction needs review; it was preserved.')
            return
        self.guard.parent.mkdir(parents=True,exist_ok=True)
        with self.guard.open('x',encoding='utf-8') as f:
            json.dump({'kind':JOURNAL_KIND,'identity':self.volume_ids,'started':time.time()},f)
            f.flush();os.fsync(f.fileno())

    def remove_file(self,path,base,expected):
        self.validate_roots();safe_path(base,path)
        st=os.lstat(native(path))
        if identity(st)!=expected or st.st_nlink!=1:raise ResetError('A data file changed during reset.')
        if getattr(st,'st_file_attributes',0)&1:
            os.chmod(native(path),stat.S_IWRITE)
            if identity(os.lstat(native(path)))!=expected:raise ResetError('File identity changed.')
        os.unlink(native(path))

    def reset(self, confirmation, progress=lambda text:None):
        if confirmation!=CONFIRMATION:raise ResetError('Type CONFIRM exactly. Nothing was reset.')
        with self.guards():
            files,dirs=self.inventory()
            # Leave a gate that ordinary login already refuses if reset is interrupted.
            self.mark_pending()
            total=len(files)
            for i,(path,(base,expected)) in enumerate(sorted(files.items(),key=lambda row:str(row[0])),1):
                self.remove_file(path,base,expected)
                if i%50==0 or i==total:progress(f'Removing personal data: {i:,} / {total:,} files')
            for path,(base,expected) in sorted(dirs.items(),key=lambda row:-len(row[0].parts)):
                if any(skip.is_relative_to(path) for skip in self.skips):continue
                safe_path(base,path);st=os.lstat(native(path))
                if file_id(st)!=expected:raise ResetError('A data folder changed during reset.')
                with os.scandir(native(path)) as entries:
                    if next(entries,None) is not None:raise ResetError('New data appeared during reset.')
                if getattr(st,'st_file_attributes',0)&1:os.chmod(native(path),stat.S_IWRITE)
                os.rmdir(native(path))
            self.validate_roots();self.require_closed()
            if self.inventory()[0]:raise ResetError('Personal data remains; reset was not marked complete.')
            safe_path(self.root,self.guard)
            self.guard.unlink()
            self.guard.parent.rmdir()
            progress('Reset complete. The next launch will create a new account and a new HA connection.')
            return {'files_removed':total,'fresh':True,'unpaired':True}

def main():
    import tkinter as tk
    from tkinter import ttk
    root=Path(__file__).absolute().parents[1]
    engine=FactoryReset(root)
    app=tk.Tk();app.title('PortalAI Full Reset');app.geometry('660x550');app.resizable(False,False)
    body=ttk.Frame(app,padding=22);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Reset this PortalAI installation',font=('Segoe UI',16,'bold')).pack(anchor='w')
    ttk.Label(body,text=str(root.parent),font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(8,12))
    message=('Permanently remove ALL PortalAI accounts, passwords, chats, memory, uploaded files, '
        'generated media, saved Home Assistant connections, and copied recovery/test data from this installation.\n\n'
        'Application files, installed models, runtimes, artwork and creator credit stay. '
        'Other drives and the separate Abliterator are untouched. No backup is created by this reset. '
        'This is ordinary file deletion, not forensic secure erasure. '
        'Files manually saved outside managed PortalAI data folders are not included.\n\n'
        'Close PortalAI and projection normally first. Type CONFIRM, then click Confirm.')
    ttk.Label(body,text=message,wraplength=590,justify='left').pack(anchor='w')
    value=tk.StringVar();entry=ttk.Entry(body,textvariable=value,width=32);entry.pack(anchor='w',pady=(15,10));entry.focus_set()
    status=tk.StringVar(value='Cancel closes this window without changing files.')
    ttk.Label(body,textvariable=status,wraplength=590).pack(anchor='w',pady=(0,8))
    buttons=ttk.Frame(body);buttons.pack(side='bottom',fill='x')
    busy=False;finished=False;messages=queue.Queue()
    def close():
        if not busy:app.destroy()
    def update(*args):
        confirm.configure(state='normal' if value.get()==CONFIRMATION and not busy and not finished else 'disabled')
    def perform():
        nonlocal busy
        if busy or finished or value.get()!=CONFIRMATION:return
        busy=True;entry.configure(state='disabled');confirm.configure(state='disabled');cancel.configure(state='disabled')
        status.set('Checking this installation and closed-process ownership...')
        def worker():
            try:
                engine.reset(value_at_click,lambda text:messages.put(('progress',text)))
                messages.put(('done','Reset complete. Open PortalAI to create the new administrator account.'))
            except Exception as e:messages.put(('error',str(e)))
        value_at_click=value.get()
        threading.Thread(target=worker,name='PortalAIFullReset',daemon=False).start()
    confirm=ttk.Button(buttons,text='Confirm',command=perform,state='disabled');confirm.pack(side='right')
    cancel=ttk.Button(buttons,text='Cancel',command=close);cancel.pack(side='right',padx=10)
    value.trace_add('write',update);app.protocol('WM_DELETE_WINDOW',close)
    def poll():
        nonlocal busy,finished
        try:
            while True:
                kind,text=messages.get_nowait();status.set(text)
                if kind in ('done','error'):
                    busy=False;finished=kind=='done';cancel.configure(state='normal',text='Close' if finished else 'Cancel')
                    if not finished:entry.configure(state='normal');value.set('');update()
        except queue.Empty:pass
        app.after(100,poll)
    app.after(100,poll);app.mainloop()

if __name__=='__main__':
    if len(sys.argv)!=1:raise SystemExit('This tool has no unattended reset mode.')
    main()
