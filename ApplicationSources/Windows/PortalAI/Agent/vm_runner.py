"""Hardware-backed, offline guest command transport. Never falls back to a host shell.

The host LLM plans actions; only the shell action runs in the VM. Guest state is
an opaque bounded tar archive, never extracted or executed on the host.
"""
from __future__ import annotations
import argparse
import base64
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

from runtime_policy import ROOT, portable_path, require_space, atomic_json, memory_info

STATE_LIMIT = 12*1024**2
SERIAL_LIMIT = 20*1024**2
OUTPUT_LIMIT = 1024**2

def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def preflight(root=ROOT, verify=True):
    root = Path(root).resolve()
    _, available = memory_info()
    if available < 1536*1024**2:
        raise RuntimeError("VM mode requires at least 1.5 GiB of available host RAM")
    if os.name == "nt":
        if ctypes.windll.shell32.IsUserAnAdmin():
            raise RuntimeError("Run VM mode from a normal, non-elevated PortalAI process")
        qdir = root / "Runtime/QEMU/windows-x64"
        exe = qdir / "qemu-system-x86_64.exe"
        accel = "whpx"
        try:
            lib = ctypes.WinDLL("WinHvPlatform.dll")
            value, written = ctypes.c_uint32(), ctypes.c_uint32()
            hr = lib.WHvGetCapability(0, ctypes.byref(value), 4, ctypes.byref(written))
            if hr != 0 or value.value != 1:
                raise RuntimeError("Windows hypervisor is not active")
        except (OSError, AttributeError) as exc:
            raise RuntimeError("VM mode requires the Windows Hypervisor Platform feature and firmware virtualization") from exc
    else:
        if os.geteuid() == 0:
            raise RuntimeError("Do not run the VM transport as root")
        qdir = root / "Runtime/QEMU/linux-x64"
        exe = qdir / "bin/qemu-system-x86_64"
        accel = "kvm"
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise RuntimeError("VM mode requires accessible /dev/kvm; no emulation fallback")
    guest = root / "Runtime/VM/alpine-3.24.2"
    for p in (exe, guest / "boot/vmlinuz-virt", guest / "boot/initramfs-virt"):
        if not p.is_file():
            raise RuntimeError("VM payload is not provisioned: " + str(p))
    if verify:
        payloads=[(qdir,root/'Maintenance/Imports'/(qdir.name+'-payload.json')),
                  (guest,root/'Maintenance/Imports'/(guest.name+'-payload.json'))]
        if os.name!='nt':payloads.append((root/'Runtime/LinuxSystem/rootfs',root/'Maintenance/Imports/linux-system-payload.json'))
        for dest,receipt in payloads:
            data = json.loads(receipt.read_text(encoding="utf-8"))
            if not data.get("verified") or not data.get("files") or data.get("destination") != dest.relative_to(root).as_posix():
                raise RuntimeError("Invalid VM payload receipt")
            for row in data["files"]:
                if digest(portable_path(dest, row["path"])) != row["sha256"]:
                    raise RuntimeError("VM payload checksum mismatch: " + row["path"])
    require_space(root, 80*1024**2, for_outputs=True)
    return {"executable": str(exe), "firmware": str(qdir / "share"), "guest": str(guest),
            "accelerator": accel, "network": False, "host_mounts": [], "guest_memory_mib": 512,
            "workspace_mib": 8, "host_available_ram_bytes": available, "verified": verify}

class ProcessBudget:
    """Windows job limits the emulator's host memory and dies with its controller."""
    def __init__(self, process, memory_bytes=2*1024**3):
        self.handle = None
        self.linux=None
        if os.name != "nt":
            from mission_supervisor import WorkerJob
            self.linux=WorkerJob(process)
            try:self.linux.limit_memory(memory_bytes)
            except BaseException:self.linux.close();raise
            return
        from ctypes import wintypes as w
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount",
                        "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class LIMIT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.lib = ctypes.WinDLL("kernel32", use_last_error=True)
        self.lib.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.lib.CreateJobObjectW.restype = w.HANDLE
        self.lib.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.lib.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.lib.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.lib.CreateJobObjectW(None, None)
        info = LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x200 | 0x8  # kill on close, memory, one process
        info.BasicLimitInformation.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = info.JobMemoryLimit = memory_bytes
        if not self.handle or not self.lib.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not self.lib.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "Could not apply VM process memory/lifetime limits")

    def close(self):
        if self.linux is not None:
            self.linux.close();self.linux=None
        if self.handle:
            self.lib.CloseHandle(self.handle)
            self.handle = None

def cpio(entries):
    """Build newc initramfs records in memory, without extracting a guest archive."""
    output = bytearray()
    for i, (name, body, mode) in enumerate([*entries, ("TRAILER!!!", b"", 0)]):
        name_bytes = name.encode() + b"\0"
        fields = [i+100000, mode, 0, 0, 1, 0, len(body), 0, 0, 0, 0, len(name_bytes), 0]
        output.extend(b"070701" + b"".join(f"{v:08x}".encode() for v in fields))
        output.extend(name_bytes)
        output.extend(b"\0" * (-len(output) % 4))
        output.extend(body)
        output.extend(b"\0" * (-len(output) % 4))
    return bytes(output)

INIT = r'''#!/bin/sh
export PATH=/usr/bin:/usr/sbin:/bin:/sbin HOME=/workspace
/usr/bin/busybox --install -s /usr/bin
chmod 755 /
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /run /tmp /workspace
mount -t tmpfs -o size=20m,nosuid,nodev tmpfs /run || poweroff -f
chmod 700 /run
mount -t tmpfs -o size=8m,nosuid,nodev tmpfs /workspace || poweroff -f
mount -t tmpfs -o size=8m,nosuid,nodev tmpfs /tmp || poweroff -f
chmod 1777 /tmp
chown 1000:1000 /workspace
if [ -s /portal-state.tar ]; then
    timeout -s KILL 10 su portal -s /bin/sh -c 'tar xf /portal-state.tar -C /workspace' >/run/restore.log 2>&1 || {
        echo 'PORTALVM_RESTORE_FAILED'
        poweroff -f
    }
fi
(
    ulimit -f 1024
    ulimit -n 128
    timeout -s KILL @TIMEOUT@ su portal -s /bin/sh -c 'cd /workspace && exec /bin/sh /portal-command.sh' </dev/null
) >/run/output 2>&1
code=$?
timeout -s KILL 10 su portal -s /bin/sh -c 'cd /workspace && tar cf - .' >/run/state.tar 2>/run/state-error
state_code=$?
echo 'PORTALVM_@NONCE@_BEGIN'
echo "EXIT $code"
echo "STATE_EXIT $state_code"
echo OUTPUT
base64 /run/output
echo STATE
base64 /run/state.tar
echo 'PORTALVM_@NONCE@_END'
sync
poweroff -f
sleep 2
reboot -f
'''

def build_initramfs(base, command, nonce, state=b"", timeout=90):
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise ValueError("Invalid VM protocol nonce")
    if len(state) > STATE_LIMIT:
        raise ValueError("Guest workspace exceeds its limit")
    if not command.strip() or len(command.encode()) > 16000 or "\0" in command:
        raise ValueError("Guest command is empty or exceeds 16000 bytes")
    script = INIT.replace("@NONCE@", nonce).replace("@TIMEOUT@", str(max(1, min(90, int(timeout)))))
    entries = [("init", script.encode(), 0o100755),
               ("portal-command.sh", command.replace("\r\n", "\n").encode(), 0o100444),
               ("portal-state.tar", state, 0o100444),
               ("etc/passwd", b"root:x:0:0:root:/:/bin/sh\nportal:x:1000:1000:PortalAI:/workspace:/bin/sh\n", 0o100644),
               ("etc/group", b"root:x:0:\nportal:x:1000:\n", 0o100644)]
    # Linux accepts concatenated compressed cpio archives. Override /init only in
    # the per-action copy; the pinned upstream guest remains unchanged.
    return Path(base).read_bytes() + gzip.compress(cpio(entries), mtime=0)

def command_line(plan, initrd):
    args = [plan["executable"], "-L", plan["firmware"], "-machine", "q35", "-accel", plan["accelerator"],
            "-m", "512", "-smp", "1", "-nodefaults", "-no-user-config", "-display", "none",
            "-monitor", "none", "-serial", "stdio", "-nic", "none", "-no-reboot",
            "-kernel", str(Path(plan["guest"]) / "boot/vmlinuz-virt"), "-initrd", str(initrd),
            "-append", "console=ttyS0 quiet panic=1 rdinit=/init"]
    if plan["accelerator"] == "kvm":
        args += ["-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny"]
    return args

def decode_result(serial, nonce):
    serial = serial.replace(b"\r\n", b"\n")
    begin, end = f"PORTALVM_{nonce}_BEGIN\n".encode(), f"PORTALVM_{nonce}_END".encode()
    if serial.count(begin) != 1 or serial.count(end) != 1:
        raise RuntimeError("VM did not return a complete result: " + serial[-3000:].decode(errors="replace"))
    body = serial.split(begin, 1)[1].split(end, 1)[0]
    match = re.fullmatch(rb"EXIT ([0-9]+)\nSTATE_EXIT ([0-9]+)\nOUTPUT\n([A-Za-z0-9+/=\n]*)STATE\n([A-Za-z0-9+/=\n]*)", body)
    if not match:
        raise RuntimeError("Invalid VM result protocol")
    out = base64.b64decode(match[3].replace(b"\n", b""), validate=True)
    state = base64.b64decode(match[4].replace(b"\n", b""), validate=True)
    if len(out) > OUTPUT_LIMIT or len(state) > STATE_LIMIT or int(match[2]) != 0:
        raise RuntimeError("Guest result/workspace exceeded limits or failed to save")
    return {"exit_code": int(match[1]), "output": out.decode(errors="replace")[:12000]}, state

def run_command(command, folder, root=ROOT, timeout=120, stop=None):
    from profile_paths import private_path, resolve_reference
    root = Path(root).resolve()
    folder = resolve_reference(root, folder).resolve()
    allowed = [private_path(root, relative).resolve() for relative in ('Data/Missions', 'Data/VMTests')]
    if not any(folder.is_relative_to(base) for base in allowed):
        raise ValueError("VM state must be in Data/Missions or Data/VMTests")
    if stop and Path(stop).exists():
        raise RuntimeError("VM action stopped by user")
    plan = preflight(root)
    folder.mkdir(parents=True, exist_ok=True)
    state_path = portable_path(folder, "workspace.tar")
    if state_path.exists() and state_path.stat().st_size > STATE_LIMIT:
        raise RuntimeError("Saved guest workspace exceeds its limit")
    state = state_path.read_bytes() if state_path.exists() else b""
    nonce = uuid.uuid4().hex
    serial = bytearray()
    overflow = threading.Event()
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="vm-action-", dir=folder) as tmp:
        initrd = Path(tmp) / "initramfs"
        initrd.write_bytes(build_initramfs(Path(plan["guest"]) / "boot/initramfs-virt", command, nonce, state,
                                        timeout=max(1, min(90, timeout-20))))
        # Only OS essentials; no host credentials, cloud tokens, or inherited QEMU
        # options in the emulator environment. No network device or host mounts.
        env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC"}}
        env.update(TMP=tmp, TEMP=tmp, TMPDIR=tmp, HOME=tmp, USERPROFILE=tmp)
        command_args=command_line(plan, initrd)
        gate=None
        if os.name!='nt':
            from platform_runtime import python_path
            gate=Path(tmp)/'start.gate';request=Path(tmp)/'request.json'
            atomic_json(request,{'command':command_args,'gate':str(gate)})
            command_args=[str(python_path(root)),'-B','-I',str(root/'Agent/sdcpp_worker.py'),str(request)]
        p = subprocess.Popen(command_args, cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        budget = None
        def read():
            while True:
                block = p.stdout.read(65536)
                if not block:
                    break
                if len(serial) + len(block) > SERIAL_LIMIT:
                    overflow.set()
                    break
                serial.extend(block)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            budget = ProcessBudget(p)
            if gate:
                if stop and Path(stop).exists():raise RuntimeError('VM action stopped before launch')
                gate.touch()
            while p.poll() is None:
                if budget.linux:budget.linux.check()
                if overflow.is_set():
                    raise RuntimeError("VM exceeded its serial output budget")
                if time.monotonic()-start > max(5, min(180, timeout)):
                    raise TimeoutError("VM action timed out")
                if stop and Path(stop).exists():
                    raise RuntimeError("VM action stopped by user")
                require_space(root, 32*1024**2, for_outputs=True)
                time.sleep(.1)
            reader.join(timeout=5)
            if overflow.is_set() or reader.is_alive() or p.returncode:
                raise RuntimeError("VM process failed: " + serial[-3000:].decode(errors="replace"))
            result, new_state = decode_result(bytes(serial), nonce)
            require_space(root, len(new_state)+len(serial), for_outputs=True)
            staged = folder / ("workspace-"+nonce+".part")
            with staged.open("wb") as f:
                f.write(new_state)
                f.flush()
                os.fsync(f.fileno())
            staged.replace(state_path)
            result.update(accelerator=plan["accelerator"], network=False, host_mounts=[],
                          workspace_bytes=len(new_state), elapsed_seconds=round(time.monotonic()-start, 2))
            atomic_json(folder / "last-vm-result.json", result)
            return result
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
            reader.join(timeout=5)
            p.stdout.close()
            if budget:
                budget.close()
            (folder / "last-vm-serial.log").write_bytes(serial)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--command")
    args = parser.parse_args()
    if args.preflight:
        print(json.dumps(preflight(), indent=2))
    elif args.command:
        from profile_paths import private_path
        print(json.dumps(run_command(args.command, private_path(ROOT,'Data/VMTests/manual')), indent=2))
    else:
        parser.error("Choose --preflight or --command")
