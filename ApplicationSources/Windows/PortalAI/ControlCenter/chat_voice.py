"""Turn-bound microphone transcription and cancellable, offline spoken replies.

Hands-free uses the installed English CPU voice. Model text remains unchanged;
speech omits Markdown syntax and describes code blocks instead of reading code.
No microphone samples are submitted while a reply is being spoken.
"""
from dataclasses import dataclass, field
from pathlib import Path
import os
import math
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
    def __init__(self, root, check, *, handoff_check=None, on_status=None, activity=None, voice_options=None):
        self.root = Path(root)
        self.check_context = check
        self.handoff_check = handoff_check
        self.on_status = on_status
        self.activity = activity
        self.voice_options = voice_options
        self.cancelled = threading.Event()

    def status(self, phase, text):
        if self.activity is not None: self.activity.phase(phase, text)
        if self.on_status is not None: self.on_status(phase, text)

    def _stage(self, name, admit, operation, *, require_handoff=False):
        from voice_memory import run_voice_stage
        return run_voice_stage(self.root, name, admit, operation, check=self.check,
                               handoff_check=self.handoff_check, notify=self.status, require_handoff=require_handoff)

    @staticmethod
    def _cpu_memory():
        from runtime_policy import memory_info
        total, available = memory_info()
        return {'ram_total_bytes': total, 'ram_available_bytes': available, 'gpus': []}

    def cancel(self):
        self.cancelled.set()

    def check(self):
        if self.cancelled.is_set(): raise VoiceStopped('Voice interaction stopped')
        self.check_context()

    def transcribe(self, wav):
        from stt_bridge import SttBridge
        self.check()
        from media_policy import speech_plan
        def admit(): speech_plan(self.root, device='cpu', hardware=self._cpu_memory())
        def transcribe(check):
            self.status('transcribing', 'Transcribing…')
            return SttBridge().transcribe(wav, device='cpu', check=check)
        result = self._stage('transcription', admit, transcribe)
        self.check()
        text = str(result.get('text') or result.get('transcript') or '').strip()
        if not text: raise RuntimeError('No speech was recognized; try speaking closer to the microphone')
        return text

    def speak(self, text):
        from piper_bridge import synthesize, output_path
        import nice_voice
        self.check()
        if self.voice_options is None:
            expressive = nice_voice.available(self.root)
        else:
            from voice_policy import capabilities, resolve
            settings, level = self.voice_options()
            selection = resolve(settings, level, capabilities(self.root, probe=True))
            expressive = selection['id'] == 'qwen'
        for chunk in spoken_chunks(text):
            self.check()
            path = output_path(self.root)
            try:
                from tts_policy import check_piper_memory, NICE_VOICE
                def admit():
                    if expressive: nice_voice.admit(self.root)
                    else: check_piper_memory(self._cpu_memory())
                def speak(check):
                    if expressive:
                        self.status('thinking', "Preparing Nice's expressive voice…")
                        result = nice_voice.synthesize(chunk, self.root, str(path), check)
                    else:
                        self.status('thinking', "Preparing Nice's basic CPU voice…")
                        result = synthesize(chunk, root=self.root, output=str(path), check=check, voice=NICE_VOICE)
                    if Path(result['files'][0]) != path: raise RuntimeError('Voice output identity changed')
                    check()
                    self.play(path, check=check, pitch_semitones=0 if expressive else 2.0)
                self._stage('speech', admit, speak, require_handoff=expressive)
            finally:
                # This call created a new, unique speech output. Keep the chat
                # text; do not accumulate an invisible WAV for every reply.
                path.unlink(missing_ok=True)

    def play(self, path, *, check=None, pitch_semitones=0):
        from mission_supervisor import WorkerJob
        from platform_runtime import worker_process_options
        from runtime_policy import portable_env
        self.check()
        pitch_semitones = float(pitch_semitones)
        if not math.isfinite(pitch_semitones) or abs(pitch_semitones) > 3:
            raise ValueError('Voice pitch must be within three semitones')
        if os.name == 'nt':
            player = self.root/'Tools/ffmpeg/bin/ffplay.exe'
            if not player.is_file(): raise FileNotFoundError('Bundled audio player is missing')
            command = [str(player), '-nodisp', '-autoexit', '-loglevel', 'error', '-nostats']
            if pitch_semitones:
                # Bundled FFmpeg rubberband changes pitch without accelerating speech.
                command += ['-af', 'rubberband=pitch=' + format(2 ** (pitch_semitones / 12), '.9f')]
            command.append(str(path))
        else:
            import media_devices
            command = media_devices.owned_linux_command(
                self.root, media_devices.linux_player_command(self.root, path, audio_only=True))
        from voice_activity import pcm_level
        envelope = []
        with wave.open(str(path), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
            if self.activity is not None and wav.getsampwidth() == 2:
                while data := wav.readframes(max(1, int(wav.getframerate() * .1))):
                    envelope.append(pcm_level(data))
        check = check or self.check
        check()
        self.status('speaking', 'Nice is speaking')
        proc = job = None
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=portable_env(self.root),
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                    **worker_process_options())
            job = WorkerJob(proc)
            started = time.monotonic()
            deadline = started + duration + 30
            while True:
                check()
                job.check()
                if self.activity is not None and envelope:
                    index = min(len(envelope) - 1, int((time.monotonic() - started) / .1))
                    self.activity.level(envelope[index], source='speaker')
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
            if self.activity is not None: self.activity.level(0, source='speaker')
            if job: job.close()
            if proc:
                if proc.poll() is None: proc.kill()
                proc.wait(timeout=10)
