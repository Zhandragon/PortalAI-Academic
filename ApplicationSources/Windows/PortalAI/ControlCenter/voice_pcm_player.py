"""One bounded PCM playback stream; preserves Nice's pitch and protected edges."""
import queue
import subprocess
import threading
import time
import wave


class PlaybackBuffer:
    """Keep a small lead for real-time producers; fully buffer slower devices.

    The first chunk includes model startup, so measure throughput only between
    subsequent arrivals. Input remains bounded by PCMPlayer's 32 MiB limit.
    """
    def __init__(self):
        self.pending = []
        self.first = None
        self.first_size = 0
        self.size = 0

    def add(self, raw, arrived):
        if self.first is None:
            self.first, self.first_size = arrived, len(raw)
        self.pending.append(raw)
        self.size += len(raw)
        duration = (self.size - self.first_size) / 48000
        return self.size >= 1.8 * 48000 and duration > 0 and (arrived - self.first) / duration < .85

    def drain(self):
        pending, self.pending = self.pending, []
        return pending


class PCMPlayer:
    def __init__(self,voice,pitch):
        from mission_supervisor import WorkerJob
        from runtime_policy import portable_env
        from chat_voice import PLAYBACK_LEAD_SECONDS,PLAYBACK_TAIL_SECONDS
        self.voice=voice;self.queue=queue.Queue(4);self.error=None;self.closed=False;self.started=None;self.samples=0;self.envelope=[];self.speaking=False
        self.lead=PLAYBACK_LEAD_SECONDS;self.tail=PLAYBACK_TAIL_SECONDS;self.proc=self.job=None;self.envelope_pending=b''
        command=[str(voice.root/'Tools/ffmpeg/bin/ffplay.exe'),'-nodisp','-autoexit','-loglevel','error','-nostats','-probesize','32','-analyzeduration','0','-f','s16le','-ar','24000','-ch_layout','mono',
                 '-af','rubberband=pitch='+format(2**(pitch/12),'.9f')+',adelay='+str(round(self.lead*1000))+':all=1,apad=pad_dur='+format(self.tail,'g'),'-i','pipe:0']
        try:
            voice.check();self.proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=portable_env(voice.root),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.job=WorkerJob(self.proc);self.thread=threading.Thread(target=self.write,name='PortalAI-PCM-writer',daemon=True);self.thread.start()
        except BaseException:self.close();raise
    def write(self):
        try:
            buffer = PlaybackBuffer()
            playing = False
            while not self.closed:
                try:item=self.queue.get(timeout=.1)
                except queue.Empty:continue
                if item is None:
                    chunks = buffer.drain()
                else:
                    raw, arrived = item
                    if not playing:
                        if not buffer.add(raw, arrived):continue
                        playing = True
                        chunks = buffer.drain()
                    else:chunks = [raw]
                for raw in chunks:
                    if self.closed:break
                    if self.started is None:self.started=time.monotonic()
                    self.proc.stdin.write(raw);self.proc.stdin.flush()
                if item is None:break
            self.proc.stdin.close()
        except Exception as exc:self.error=exc
    def tick(self):
        self.voice.check()
        if self.job:self.job.check()
        if self.error:raise RuntimeError('Incremental audio playback failed: '+str(self.error))
        if self.proc.poll() is not None and self.proc.returncode:raise RuntimeError('Incremental audio player exited: '+self.proc.stderr.read(2048).decode('utf-8','replace'))
        if self.started is not None:
            elapsed=time.monotonic()-self.started-self.lead
            if elapsed>=0 and not self.speaking:self.voice.status('speaking','Nice is speaking');self.speaking=True
            if self.voice.activity is not None:
                index=int(elapsed/.1);level=self.envelope[index] if elapsed>=0 and index<len(self.envelope) else 0
                self.voice.activity.level(level,source='speaker')
    def push(self,path):
        from voice_activity import pcm_level
        deadline=time.monotonic()+3
        while True:
            self.tick()
            try:
                with wave.open(str(path),'rb') as wav:
                    if wav.getframerate()!=24000 or wav.getnchannels()!=1 or wav.getsampwidth()!=2 or not 0<wav.getnframes()<=48000:raise ValueError('Unexpected incremental PCM format')
                    raw=wav.readframes(wav.getnframes())
                break
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(.05)
        if self.samples+len(raw)>32*1024**2:raise ValueError('PCM speech limit exceeded')
        self.envelope_pending+=raw
        while len(self.envelope_pending)>=4800:
            self.envelope.append(pcm_level(self.envelope_pending[:4800]));self.envelope_pending=self.envelope_pending[4800:]
        self.samples+=len(raw);self.put((raw,time.monotonic()))
    def put(self,raw):
        deadline=time.monotonic()+30
        while True:
            self.tick()
            if time.monotonic()>deadline:raise TimeoutError('PCM playback queue stalled')
            try:self.queue.put(raw,timeout=.05);return
            except queue.Full:pass
    def finish(self):
        if self.envelope_pending:
            from voice_activity import pcm_level
            self.envelope.append(pcm_level(self.envelope_pending));self.envelope_pending=b''
        self.put(None);deadline=time.monotonic()+self.samples/48000+self.lead+self.tail+20
        while self.proc.poll() is None:
            self.tick()
            if time.monotonic()>deadline:raise TimeoutError('Incremental playback did not finish')
            time.sleep(.05)
        self.tick()
    def close(self):
        self.closed=True
        if self.job:self.job.close();self.job=None
        if self.proc:
            if self.proc.poll() is None:self.proc.kill()
            self.proc.wait(timeout=5)
            thread=getattr(self,'thread',None)
            if thread:thread.join(2)
            for pipe in (self.proc.stdin,self.proc.stderr):
                if pipe and not pipe.closed:pipe.close()
        if self.voice.activity is not None:self.voice.activity.level(0,source='speaker')
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
