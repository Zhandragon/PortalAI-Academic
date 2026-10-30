"""Turn-bound microphone transcription and cancellable, offline spoken replies.

Hands-free uses the installed English CPU voice. Model text remains unchanged;
speech omits Markdown syntax and describes code blocks instead of reading code.
No microphone samples are submitted while a reply is being spoken.
"""
from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import subprocess
import threading
import time
import wave


class VoiceStopped(RuntimeError):
    pass


@dataclass
class VoiceTurn:
    session_id: str
    text: str
    done: threading.Event = field(default_factory=threading.Event)
    request_index: int = -1
    reply: str = ''
    failed: bool = False

    def finish(self, session, cancelled=False):
        self.failed |= cancelled or not session or session.get('id') != self.session_id
        if not self.failed and self.request_index >= 0:
            messages = session.get('messages', [])[self.request_index + 1:]
            for row in reversed(messages):
                if row.get('role') == 'user':
                    self.failed = True
                    break
                if row.get('role') == 'assistant' and not row.get('tool_calls'):
                    if not any(row.get(k) for k in ('incomplete', 'cancelled', 'tool_validation_error')):
                        self.reply = str(row.get('content') or '')
                    break
        self.done.set()


def spoken_chunks(text, limit=1800):
    """Bound every UTF-8 request without dropping the remainder of long replies."""
    text = re.sub(r'```[\s\S]*?```', ' Code is shown in the chat. ', str(text))
    text = re.sub(r'!\[([^]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|>\s*)', '', text)
    text = re.sub(r'[`*_~]', '', text).replace('\x00', '')
    text = re.sub(r'\s+', ' ', text).strip()
    chunk = ''
    for word in text.split(' '):
        for char in ((' ' if chunk else '') + word):
            if len((chunk + char).encode('utf-8')) > limit:
                if chunk.strip(): yield chunk.strip()
                chunk = ''
            chunk += char
    if chunk.strip(): yield chunk.strip()


class VoiceIO:
    def __init__(self, root, check):
        self.root = Path(root)
        self.check_context = check
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def check(self):
        if self.cancelled.is_set(): raise VoiceStopped('Voice interaction stopped')
        self.check_context()

    def transcribe(self, wav):
        from stt_bridge import SttBridge
        self.check()
        # Whisper's own policy checks available RAM. CPU dictation does not
        # evict the conversational model or take an unrelated GPU workload.
        result = SttBridge().transcribe(wav, device='cpu', check=self.check)
        self.check()
        text = str(result.get('text') or result.get('transcript') or '').strip()
        if not text: raise RuntimeError('No speech was recognized; try speaking closer to the microphone')
        return text

    def speak(self, text):
        from piper_bridge import synthesize, output_path
        for chunk in spoken_chunks(text):
            self.check()
            path = output_path(self.root)
            try:
                result = synthesize(chunk, root=self.root, output=str(path), check=self.check)
                if Path(result['files'][0]) != path: raise RuntimeError('Voice output identity changed')
                self.check()
                self.play(path)
            finally:
                # This call created a new, unique speech output. Keep the chat
                # text; do not accumulate an invisible WAV for every reply.
                path.unlink(missing_ok=True)

    def play(self, path):
        from mission_supervisor import WorkerJob
        from platform_runtime import worker_process_options
        from runtime_policy import portable_env
        self.check()
        if os.name == 'nt':
            player = self.root/'Tools/ffmpeg/bin/ffplay.exe'
            if not player.is_file(): raise FileNotFoundError('Bundled audio player is missing')
            command = [str(player), '-nodisp', '-autoexit', '-loglevel', 'error', '-nostats', str(path)]
        else:
            import media_devices
            command = media_devices.owned_linux_command(
                self.root, media_devices.linux_player_command(self.root, path, audio_only=True))
        with wave.open(str(path), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
        proc = job = None
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=portable_env(self.root),
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                    **worker_process_options())
            job = WorkerJob(proc)
            deadline = time.monotonic() + duration + 30
            while True:
                self.check()
                job.check()
                if time.monotonic() > deadline: raise TimeoutError('Audio playback timed out')
                try:
                    _, error = proc.communicate(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
            self.check()
            if proc.returncode:
                raise RuntimeError('Audio playback failed: ' + error.decode('utf-8', 'replace')[-600:])
        finally:
            if job: job.close()
            if proc:
                if proc.poll() is None: proc.kill()
                proc.wait(timeout=10)
