"""Fail-closed process quiescence for profile recovery and sealing.

This does not pause missions, edit schedules, or claim OS isolation. The caller
holds ProfileRuntime's controller lock and must join its own writer threads.
Already detached full-host effects outside PortalAI's process/cgroup ownership
are not an application sandbox and cannot be attributed by this helper.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid


class QuiescenceError(RuntimeError):
    pass


def _contained(root, value):
    try:
        return bool(value) and Path(value).is_absolute() and Path(value).resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def _marker(root):
    from profile_paths import _contained as checked
    path = checked(root, root/'Private/active-session.json')
    if not path.exists():
        return None
    if path.stat().st_size > 16384:
        raise QuiescenceError('Oversized account runtime marker')
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('state') not in ('opening', 'open', 'closing', 'closed') or
            not re.fullmatch('[a-f0-9]{32}', value.get('user_id', '')) or
            not re.fullmatch('[a-f0-9]{32}', value.get('epoch', ''))):
        raise QuiescenceError('Invalid account runtime marker')
    return value


def _validate(root, session, marker):
    from local_accounts import Session
    if not isinstance(session, Session):
        raise PermissionError('Authenticated account session required')
    store = session._store()
    if store is None or store.root != root:
        raise PermissionError('Account session belongs to another installation')
    store.validate_session(session)
    if not session.active:
        raise PermissionError('Account session ended')
    if _marker(root) != marker:
        raise QuiescenceError('Account runtime marker changed before quiescence')
    if (marker and marker['state'] != 'closed' and marker['user_id'] != session.user_id and
            session.role != 'admin'):
        raise PermissionError('The previous owner or an administrator must recover this workspace')


def _argv(command):
    from chat_model_switch import _argv as parse
    return parse(command)


def _windows_image(pid):
    """Read kernel-recorded image paths even for protected OS processes.

    SystemProcessIdInformation is read-only; it neither requests debug privilege
    nor opens/terminates protected processes. Unsupported queries fail closed.
    """
    import ctypes
    from ctypes import wintypes as w
    class UnicodeString(ctypes.Structure):
        _fields_=[('Length',w.USHORT),('MaximumLength',w.USHORT),('Buffer',ctypes.c_void_p)]
    class ProcessImage(ctypes.Structure):
        _fields_=[('ProcessId',ctypes.c_void_p),('ImageName',UnicodeString)]
    lib=ctypes.WinDLL('ntdll')
    query=lib.NtQuerySystemInformation
    query.argtypes=(w.ULONG,ctypes.c_void_p,w.ULONG,ctypes.c_void_p);query.restype=w.LONG
    buf=ctypes.create_unicode_buffer(32768)
    record=ProcessImage(pid,UnicodeString(0,65534,ctypes.cast(buf,ctypes.c_void_p)))
    result=query(88,ctypes.byref(record),ctypes.sizeof(record),None)&0xffffffff
    if result == 0xc000000b:
        return None  # STATUS_INVALID_CID: process exited since the snapshot.
    if result:
        raise QuiescenceError(f'Kernel image identity unavailable for process {pid}')
    if not record.ImageName.Length:
        return None  # Kernel confirms no file-backed executable (e.g. Secure System).
    native=ctypes.wstring_at(record.ImageName.Buffer,record.ImageName.Length//2)
    if '\\' not in native and '/' not in native and ':' not in native:
        return None  # Kernel minimal processes have labels, not executable paths.
    if native.startswith('\\??\\'):
        return native[4:]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.QueryDosDeviceW.argtypes=(w.LPCWSTR,w.LPWSTR,w.DWORD);kernel.QueryDosDeviceW.restype=w.DWORD
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        target=ctypes.create_unicode_buffer(32768)
        if kernel.QueryDosDeviceW(letter+':',target,len(target)):
            prefix=target.value
            if native.casefold().startswith(prefix.casefold()+'\\'):
                return letter+':'+native[len(prefix):]
    raise QuiescenceError(f'Cannot map kernel image identity for process {pid}')


def _windows_snapshot():
    # A successful complete CIM response is required; an empty/failed query is
    # never converted to "no processes". Creation times defeat stale PID reuse.
    script = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$session=(Get-Process -Id $PID).SessionId
$rows=@(Get-CimInstance Win32_Process | ForEach-Object {
  $created=if ($_.CreationDate) {$_.CreationDate.ToFileTimeUtc().ToString()} else {''}
  [pscustomobject]@{pid=[int]$_.ProcessId;ppid=[int]$_.ParentProcessId;
    executable=$_.ExecutablePath;command=$_.CommandLine;name=$_.Name;
    start=$created;session=[int]$_.SessionId}
})
[pscustomobject]@{complete=$true;session=$session;rows=$rows}|ConvertTo-Json -Depth 4 -Compress
'''
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = dict(os.environ)
    env.pop('PORTALAI_ACCOUNT_UNLOCK', None)
    env.pop('PORTALAI_CONNECTION_UNLOCK', None)
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='strict',
                            timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise QuiescenceError('Windows process inventory failed')
    data = json.loads(result.stdout)
    rows = data.get('rows')
    if data.get('complete') is not True or not isinstance(rows, list) or not rows:
        raise QuiescenceError('Windows process inventory was incomplete')
    out = {}
    for row in rows:
        pid = int(row['pid'])
        if pid <= 4:
            continue  # Windows idle/System pseudo-processes cannot be bundle workers.
        if not row.get('executable'):
            row['executable'] = _windows_image(pid)
            if row['executable'] is None:
                continue
        row['argv'] = _argv(row.get('command') or '')
        row['start'] = int(row.get('start') or 0)
        if not row['start']:
            raise QuiescenceError(f'Cannot establish process creation identity ({pid})')
        # A disconnected portable image can retain its original CIM path while
        # Win32 path conversion reports ERROR_NOT_READY. Pin native image and
        # creation identity together; stopping still requires a second check on
        # the exact terminating handle. External descendants get no fallback.
        from windows_detached_image import capture
        proof = capture(row, Path(__file__).resolve().parents[1])
        if proof is not None:
            row['detached_image'] = proof
        out[pid] = row
    if os.getpid() not in out:
        raise QuiescenceError('The controller is missing from the Windows process inventory')
    return out


def _linux_snapshot():
    from linux_process import identity
    out = {}
    for base in Path('/proc').iterdir():
        if not base.name.isdecimal():
            continue
        try:
            if base.stat().st_uid != os.getuid():
                continue
            fields = (base/'stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] in ('Z', 'X'):
                continue
            ident = identity(int(base.name))
            group = next(line[3:] for line in (base/'cgroup').read_text().splitlines() if line.startswith('0::'))
            if not group.startswith('/') or '..' in Path(group).parts:
                raise QuiescenceError('Invalid process cgroup membership')
            out[ident['pid']] = {**ident, 'identity':ident, 'ppid':int(fields[1]),
                                'start':ident['start_ticks'], 'group':str(Path('/sys/fs/cgroup')/group.lstrip('/'))}
        except (FileNotFoundError, ProcessLookupError):
            # /proc is a live view; ignore only a proved exit/zombie, not a
            # missing executable while a potentially owned writer still lives.
            try:
                state = (base/'stat').read_text().rsplit(')',1)[1].split()[0]
                if state not in ('Z', 'X'):
                    raise QuiescenceError(f'Cannot inspect live process {base.name}')
            except (FileNotFoundError, ProcessLookupError):
                pass
        except (OSError, ValueError, StopIteration) as exc:
            raise QuiescenceError(f'Linux process ownership could not be read ({base.name})') from exc
    if os.getpid() not in out:
        raise QuiescenceError('The controller is missing from the Linux process inventory')
    return out


def _snapshot():
    if os.name == 'nt':
        return _windows_snapshot()
    if sys.platform.startswith('linux'):
        return _linux_snapshot()
    raise QuiescenceError('Profile process quiescence is not supported on this platform')


def _script_owned(root, row):
    """Host interpreters only qualify with a direct, absolute owned script."""
    args = row.get('argv') or []
    exe = Path(row.get('executable') or '').name.lower()
    if exe in ('powershell.exe', 'pwsh.exe', 'pwsh'):
        if any(item.lower() in ('-command','-c','-encodedcommand','-enc','-ec') for item in args[1:]):
            return False
        positions = [i+1 for i, item in enumerate(args[:-1]) if item.lower() == '-file']
    elif re.fullmatch(r'python(?:w|[0-9.]*)?(?:\.exe)?', exe):
        positions=[];index=1
        while index<len(args):
            token=args[index]
            if token in ('-c','-m') or token.startswith(('-c','-m')):
                return False
            if token in ('-W','-X'):
                index+=2;continue
            if token == '--':
                if index+1<len(args):positions=[index+1]
                break
            if not token.startswith('-'):
                positions=[index];break
            index+=1
    elif exe in ('sh', 'bash', 'dash') and len(args) > 1 and not args[1].startswith('-'):
        positions = [1]
    else:
        return False
    return any(_contained(root, args[i]) and Path(args[i]).suffix.lower() in ('.py', '.ps1', '.sh')
               and any(Path(args[i]).resolve().is_relative_to(root/part) for part in ('Agent','Launchers','ControlCenter','Scientific','Tools'))
               for i in positions)


def _same(a, b):
    return a['pid'] == b['pid'] and a['start'] == b['start'] and a['executable'] == b['executable']


def _select(root, rows, known=None):
    known = known or {}
    me = os.getpid()
    ancestors = set()
    current = rows.get(me, {})
    while current.get('ppid') in rows and current['ppid'] not in ancestors:
        parent = rows[current['ppid']]
        if parent['start'] > current['start']:
            break
        ancestors.add(parent['pid']); current = parent
    selected = {}
    for pid, row in rows.items():
        if pid == me:
            continue  # Caller joins this controller's threads separately.
        from remote_lifecycle import is_bridge
        if is_bridge(root, row):
            continue  # Independent, key-free remote login/restart controller.
        owns = _contained(root, row.get('executable')) or _script_owned(root,row)
        owns = owns or (pid in known and _same(row, known[pid]))
        if not owns:
            continue
        if pid in ancestors:
            # The root EXE is a passive launcher, not the Python controller.
            if Path(row['executable']).resolve() == root/'PortalAI.exe':
                continue
            raise QuiescenceError('Another owned ancestor remains; close its controller before recovery')
        if any(Path(arg).name.lower() in ('portableai_gui.py','control_center_bootstrap.py') for arg in row.get('argv', [])):
            raise QuiescenceError('Another PortalAI GUI remains open; close it before profile recovery')
        selected[pid] = row
    # Inherited OS-shell children belong to a proved portable parent. Start time
    # ordering prevents a reused parent PID from adopting an unrelated process.
    changed = True
    while changed:
        changed = False
        for pid, row in rows.items():
            if pid == me or pid in selected:
                continue
            parent = selected.get(row['ppid'])
            if parent and parent['start'] <= row['start']:
                selected[pid] = row; changed = True
    return selected


def _fence(root):
    # No mission/schedule file is touched. These fences only cancel stale model
    # startup and restoration. A new explicit start after recovery is permitted.
    import service_manager as service
    from profile_paths import _contained as checked
    from runtime_policy import atomic_json
    if service.root_dir().resolve() != root:
        raise QuiescenceError('Lifecycle module does not belong to this portable root')
    with service._qwen_lifecycle_mutex(timeout=30):
        now = time.time()
        base = checked(root, root/'Agent/.runtime')
        atomic_json(checked(root,base/'qwen_last_stop.json'), {'stopped_at':now,'reason':'profile-quiescence'})
        atomic_json(checked(root,base/'qwen_handoff_generation.json'),
                    {'token':'profile-close-'+uuid.uuid4().hex,'reason':'explicit-stop','stopped_at':now})


def _windows_stop(row, root):
    # Bind to an OS handle, validate its creation time and image, then terminate
    # that same handle. taskkill /PID has a PID reuse race and is not used here.
    import ctypes
    from ctypes import wintypes as w
    lib = ctypes.WinDLL('kernel32', use_last_error=True)
    lib.OpenProcess.argtypes=(w.DWORD,w.BOOL,w.DWORD);lib.OpenProcess.restype=w.HANDLE
    lib.CloseHandle.argtypes=(w.HANDLE,)
    lib.QueryFullProcessImageNameW.argtypes=(w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD))
    lib.GetProcessTimes.argtypes=(w.HANDLE,ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME))
    lib.TerminateProcess.argtypes=(w.HANDLE,w.UINT);lib.TerminateProcess.restype=w.BOOL
    lib.WaitForSingleObject.argtypes=(w.HANDLE,w.DWORD);lib.WaitForSingleObject.restype=w.DWORD
    handle = lib.OpenProcess(0x1000|0x00100000|0x0001, False, row['pid'])
    if not handle:
        if ctypes.get_last_error() == 87:
            return  # Invalid PID: already exited. The final inventory still checks.
        raise QuiescenceError(f'Cannot open owned process {row["pid"]} for verified shutdown')
    try:
        if lib.WaitForSingleObject(handle,0) == 0:
            return
        created, exited, kernel, user = (w.FILETIME() for _ in range(4))
        size=w.DWORD(32768);image=ctypes.create_unicode_buffer(size.value)
        times_ok = lib.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user))
        image_ok = times_ok and lib.QueryFullProcessImageNameW(handle,0,image,ctypes.byref(size))
        image_error = ctypes.get_last_error() if times_ok and not image_ok else None
        ticks=(created.dwHighDateTime<<32)|created.dwLowDateTime
        detached_ok = False
        if times_ok and not image_ok and image_error == 21:
            from windows_detached_image import verify
            detached_ok = verify(row, root, lib, handle, ticks)
        if not times_ok or (not image_ok and not detached_ok):
            # A descendant can finish after the first wait but before either
            # query. Only this same handle's signaled state proves that exit;
            # an unreadable live identity must still fail closed.
            if lib.WaitForSingleObject(handle,0) == 0:
                return
            raise QuiescenceError('Owned process identity cannot be rechecked')
        # CIM datetime has microsecond precision; FILETIME has 100ns precision.
        if ticks//10 != row['start']//10 or (not detached_ok and Path(image.value).resolve() != Path(row['executable']).resolve()):
            raise QuiescenceError('Process identity changed before shutdown')
        if not lib.TerminateProcess(handle,1) or lib.WaitForSingleObject(handle,8000) != 0:
            # Natural exit can also race termination or the bounded wait. Never
            # substitute a fresh PID lookup, which could refer to a replacement.
            if lib.WaitForSingleObject(handle,0) == 0:
                return
            raise QuiescenceError('Owned process did not exit after shutdown')
    finally:
        lib.CloseHandle(handle)


def _job_group(row):
    group = Path(row['group'])
    return next((p for p in (group,*group.parents) if re.fullmatch(r'portalai-job-[0-9]+-[a-f0-9]{32}',p.name)),None)


def _linux_plan(root, rows, selected):
    from linux_job import delegated_root
    jobs = {_job_group(row) for row in selected.values()} - {None}
    outside = [row for row in selected.values() if _job_group(row) not in jobs]
    if any(not _contained(root,row['executable']) for row in outside):
        raise QuiescenceError('A non-bundled descendant escaped cgroup ownership; refusing PID fallback')
    if not jobs:
        return [], outside
    base = delegated_root()  # No scope guessing, sudo, or process-group fallback.
    for group in jobs:
        if group.parent != base or group.is_symlink() or group.stat().st_uid != os.getuid():
            raise QuiescenceError('An owned worker is in a different/unverifiable delegated scope')
        if not (group/'cgroup.kill').is_file() or not os.access(group/'cgroup.kill',os.W_OK):
            raise QuiescenceError('Owned worker cancellation requires writable cgroup.kill')
        if Path(rows[os.getpid()]['group']).is_relative_to(group):
            raise QuiescenceError('Cannot cancel the current controller cgroup')
    return sorted(jobs,key=str),outside


def _stop_batch(root, rows, selected):
    if os.name == 'nt':
        # Stop controllers before descendants so they cannot launch new workers.
        ordered=sorted(selected.values(),key=lambda row:row['start'])
        for row in ordered:
            _windows_stop(row,root)
        return
    from linux_job import destroy
    from linux_process import stop
    jobs,outside = _linux_plan(root,rows,selected)
    # cgroup.kill owns the complete tree including detached host-shell children.
    for group in jobs:
        destroy(group)
    for row in sorted(outside,key=lambda item:item['start']):
        if not _contained(root,row['executable']):
            raise QuiescenceError('A non-bundled descendant escaped cgroup ownership; refusing PID fallback')
        try:
            stop(row['identity'],root)
        except (FileNotFoundError,ProcessLookupError):
            pass


def verify_stopped(root):
    """Fresh read-only proof, usable after reset has revoked authentication.

    Caller must hold the profile controller lock and stop/join its own writers.
    This grants no authority and never changes markers or terminates anything.
    """
    root=Path(root).resolve()
    for _ in range(2):
        remaining=_select(root,_snapshot())
        if remaining:
            return {'stopped':False,'remaining_owned_pids':sorted(remaining),'controller_threads':'caller-must-join'}
        time.sleep(.1)
    return {'stopped':True,'remaining_owned_pids':[],'controller_threads':'caller-must-join'}


def stop_owned(root, session, marker):
    """Stop attributable background processes; preserve durable mission policy.

    Raises on uncertainty. The authenticated caller holds the profile-runtime
    lock. No marker is reopened, private path resolver used, or data deleted.
    """
    root=Path(root).resolve()
    _validate(root,session,marker)
    known={};attempted=set();fenced=False;empty=0
    for _ in range(12):
        _validate(root,session,marker)
        rows=_snapshot();selected=_select(root,rows,known)
        if not selected:
            empty+=1
            if empty == 2:
                return {'stopped':True,'remaining_owned_pids':[],'stopped_pids':sorted(attempted),
                        'model_fenced':fenced,'mission_policy':'preserved','controller_threads':'caller-must-join'}
            time.sleep(.1)
            continue
        empty=0
        if os.name != 'nt':
            _linux_plan(root,rows,selected)  # Preflight before changing lifecycle state.
        if not fenced:
            _fence(root);fenced=True
        _validate(root,session,marker)
        known.update(selected);attempted.update(selected)
        _stop_batch(root,rows,selected)
        time.sleep(.1)
    raise QuiescenceError('Owned processes keep appearing; workspace remains locked')
