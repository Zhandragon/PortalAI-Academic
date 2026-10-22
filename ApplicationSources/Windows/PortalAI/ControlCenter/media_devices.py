"""Portable desktop media I/O; capture endpoints are checked when opened.

Linux uses the bundled FFmpeg/FFplay and the desktop's PulseAudio (including
PipeWire's PulseAudio service) or ALSA. No host Python or audio utility is needed.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import wave


def ffmpeg_path(root):
    root = Path(root)
    return (root / 'Tools/ffmpeg/bin/ffmpeg.exe' if os.name == 'nt'
            else root / 'Runtime/FFmpeg/linux-x64/bin/ffmpeg')


def desktop_env(root):
    env = os.environ.copy()
    for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
        env.pop(key, None)
    root = Path(root)
    config = root / 'Runtime/LinuxSystem/rootfs/usr/share/alsa/alsa.conf'
    if config.is_file():
        env['ALSA_CONFIG_PATH'] = str(config)
        env['ALSA_CONFIG_DIR'] = str(config.parent)
        # Do not load a recipient distribution's ALSA plugins into bundled glibc.
        env['ALSA_PLUGIN_DIR'] = str(root / 'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/alsa-lib')
    return env


def open_external(root, path):
    path = Path(path).resolve()
    from profile_paths import capture, workspace_root
    context = capture(root)
    if context is not None:
        workspace = workspace_root(root, context[0])
        if path.is_relative_to(workspace) and path != workspace:
            from profile_hydration import materialize
            materialize(root, path.relative_to(workspace).as_posix(), recursive=True)
            if capture(root) != context:
                raise PermissionError('Login ended before opening the file')
        elif path == workspace:
            from profile_hydration import materialize
            materialize(root, None, recursive=True)
            if capture(root) != context:
                raise PermissionError('Login ended before opening the folder')
    if not path.exists():
        raise FileNotFoundError(path)
    if os.name == 'nt':
        os.startfile(str(path))
        return
    opener = shutil.which('xdg-open')
    if not opener:
        raise RuntimeError('This Linux desktop has no xdg-open file handler. Open the displayed path in your file manager.')
    # xdg-open is part of the recipient desktop, not an inference dependency.
    # An absolute path prevents filenames beginning with '-' becoming options.
    proc = subprocess.Popen([opener, str(path)], cwd=str(root), env=desktop_env(root),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=proc.wait, name='PortalAIFileOpener', daemon=True).start()
    return proc


def linux_player_command(root, path, *, audio_only=False):
    root = Path(root).resolve()
    lib = root / 'Runtime/LinuxSystem/rootfs/usr/lib'
    binary = root / 'Runtime/LinuxSystem/rootfs/usr/bin/ffplay'
    loader = lib / 'x86_64-linux-gnu/ld-linux-x86-64.so.2'
    if not binary.is_file() or not loader.is_file():
        raise RuntimeError('Bundled Linux FFplay or its dynamic loader is missing; use Open externally.')
    libraries = ':'.join(str(p) for p in (
        lib / 'x86_64-linux-gnu', lib / 'x86_64-linux-gnu/blas',
        lib / 'x86_64-linux-gnu/lapack', lib, lib / 'pulseaudio',
        lib / 'x86_64-linux-gnu/pulseaudio'))
    args = [str(loader), '--library-path', libraries, str(binary), '-hide_banner',
            '-loglevel', 'error', '-autoexit', '-window_title', 'PortalAI media']
    if audio_only:
        args += ['-nodisp']
    return [*args, str(Path(path).resolve())]


def owned_linux_command(root, command):
    root = Path(root)
    return [str(root / 'Runtime/LinuxPython/run-python'), '-I',
            str(root / 'ControlCenter/linux_media_exec.py'), str(os.getpid()), *command]


@lru_cache(maxsize=8)
def capture_formats(root):
    ff = ffmpeg_path(root)
    if not ff.is_file():
        return ()
    try:
        result = subprocess.run([str(ff), '-hide_banner', '-devices'], cwd=str(root),
                                env=desktop_env(root), capture_output=True, text=True,
                                errors='replace', timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode:
        return ()
    available = set()
    for line in (result.stdout + result.stderr).splitlines():
        fields = line.split()
        if len(fields) >= 2 and 'D' in fields[0] and fields[1] in ('pulse', 'alsa'):
            available.add(fields[1])
    return tuple(fmt for fmt in ('pulse', 'alsa') if fmt in available)


def microphone_candidates(root, configured='auto'):
    formats = capture_formats(str(Path(root).resolve()))
    configured = str(configured or 'auto').strip()
    if configured.lower() in ('', 'auto'):
        return [{'backend': fmt, 'device_id': 'default', 'name': f'{fmt}:default'}
                for fmt in formats]
    backend, separator, device = configured.partition(':')
    if separator and backend in formats and device.strip():
        return [{'backend': backend, 'device_id': device.strip(), 'name': configured}]
    raise RuntimeError('Linux microphone selection must be auto, pulse:<source>, or alsa:<device>. '
                       'This portable FFmpeg supports: ' + (', '.join(formats) or 'no Linux capture backend'))


def capture_command(root, candidate):
    backend = str(candidate.get('backend', ''))
    device = str(candidate.get('device_id') or 'default')
    if backend not in ('pulse', 'alsa') or '\x00' in device:
        raise ValueError('Unsupported Linux microphone selection')
    return [str(ffmpeg_path(root)), '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-f', backend, '-i', device, '-ac', '1', '-ar', '16000',
            '-f', 's16le', '-acodec', 'pcm_s16le', 'pipe:1']


class LinuxPCMStream:
    """One bounded, continuously drained capture pipe for manual or rolling VAD.

    Only the child started here is stopped. Readers never block the GUI waiting
    for a failed microphone, and queued audio cannot grow while inference runs.
    """
    sample_rate = 16000
    channels = 1

    def __init__(self, root, candidate):
        self._chunks = queue.Queue(maxsize=20)
        self._errors = deque(maxlen=16)
        self._closed = threading.Event()
        self._process = subprocess.Popen(owned_linux_command(root, capture_command(root, candidate)), cwd=str(root),
                                         env=desktop_env(root), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._reader = threading.Thread(target=self._read, name='PortalAILinuxMic', daemon=True)
        self._error_reader = threading.Thread(target=self._read_errors, name='PortalAILinuxMicErrors', daemon=True)
        self._reader.start()
        self._error_reader.start()
        time.sleep(0.15)
        if self._process.poll() is not None:
            self.close()
            raise RuntimeError(self._error_message())

    def _error_message(self):
        return ''.join(self._errors)[-1800:].strip() or 'Linux microphone capture ended; check desktop audio input permissions and device availability.'

    def _read_errors(self):
        while True:
            chunk = self._process.stderr.read(512)
            if not chunk:
                return
            self._errors.append(chunk.decode('utf-8', errors='replace'))

    def _read(self):
        while not self._closed.is_set():
            data = self._process.stdout.read(3200)
            if not data:
                return
            if self._chunks.full():
                try:
                    self._chunks.get_nowait()
                except queue.Empty:
                    pass
            self._chunks.put_nowait(data)

    def read_chunk(self, timeout=0.35):
        try:
            return self._chunks.get(timeout=timeout)
        except queue.Empty:
            if not self._closed.is_set() and self._process.poll() is not None:
                raise RuntimeError(self._error_message())
            return b''

    def drain_pending(self):
        while True:
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                return

    def write_wav(self, path, stop):
        # Manual dictation is bounded to ten minutes (~19 MiB), on the SSD.
        deadline = time.monotonic() + 600
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(self.channels)
            output.setsampwidth(2)
            output.setframerate(self.sample_rate)
            while not stop.is_set() and not self._closed.is_set():
                if time.monotonic() >= deadline:
                    raise RuntimeError('Microphone recording reached its ten-minute limit; stop recording to transcribe it.')
                output.writeframesraw(self.read_chunk())

    def close(self):
        self._closed.set()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1.5)
        for thread in (self._reader, self._error_reader):
            if thread is not threading.current_thread():
                thread.join(timeout=0.5)
        for pipe in (self._process.stdout, self._process.stderr):
            pipe.close()
