"""Expressive Nice voice using the existing SSD-local Qwen TTS runtime.

The GUI caller owns the GPU lease and healthy chat restoration. This module owns
one gated, cancellable worker and its unique staging output; inference is never
replayed or silently replaced with Piper after it starts.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import wave

INSTRUCTION = ('Speak naturally as a warm, self-assured man around thirty, with a relaxed '
    'midrange voice. Use everyday conversational pacing and easy, subtle expression. '
    'Sound composed, quietly confident and welcoming, with unforced warmth and kindness.')


# User-approved small pitch adjustment; tempo stays unchanged.
PLAYBACK_PITCH_SEMITONES = -0.5

def available(root):
    """Check installed capability, not currently free VRAM before chat release."""
    from runtime_policy import detect_hardware
    from tts_policy import qwen_preflight, with_amd_probe
    root=Path(root)
    required=('Voice/Qwen3-TTS/qwen_tts_runner.py',
              'Voice/Qwen3-TTS/models/Qwen3-TTS-12Hz-1.7B-CustomVoice/config.json',
              'Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts/__init__.py')
    if not all((root/p).is_file() for p in required):return False
    try:qwen_preflight(with_amd_probe(detect_hardware(),root))
    except RuntimeError:return False
    return True


def admit(root):
    from tts_policy import tts_plan
    return tts_plan(root,'qwen')


def synthesize(text, root, output, check):
    from media_paths import media_runtime
    from mission_runner import process_lock
    from mission_supervisor import WorkerJob
    from platform_runtime import python_path, worker_process_options
    from runtime_policy import GIB, atomic_json, portable_env, require_space
    from piper_bridge import output_path
    from tts_policy import validate_text
    from voice_bridge import VoiceBridge
    root=Path(root).resolve();validate_text(text);check();plan=admit(root)
    out=output_path(root,output);runtime=media_runtime(root);runtime.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex;request=runtime/('nice_voice_'+token+'.json');gate=request.with_suffix('.gate');logpath=request.with_suffix('.log')
    part=out.with_name(out.stem+'.'+token+'.part.wav');proc=job=None
    with process_lock(runtime/'nice-voice.lock'):
        try:
            require_space(root,32*1024**2,for_outputs=True);check();out.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(request,{'text':text,'output':str(part)})
            env=portable_env(root);env.update(PORTALAI_VOICE_GATE=str(gate),PORTALAI_TORCH_BACKEND=plan['device'],
                HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
                OMP_NUM_THREADS='4',MKL_NUM_THREADS='4')
            with logpath.open('wb') as log:
                proc=subprocess.Popen([str(python_path(root)),'-B','-I',str(root/'Agent/nice_voice.py'),'--worker',str(request)],
                    cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),**worker_process_options())
                job=WorkerJob(proc);job.limit_memory(16*GIB);check();gate.touch();started=time.monotonic();deadline=started+240
                while proc.poll() is None:
                    check();job.check()
                    if time.monotonic()>=deadline:raise TimeoutError('Expressive voice exceeded 240 seconds')
                    if logpath.stat().st_size>1024**2:raise RuntimeError('Expressive voice log exceeded its limit')
                    require_space(root,for_outputs=True);time.sleep(.1)
            check();result=VoiceBridge._payload(proc.returncode,logpath.read_text(encoding='utf-8',errors='replace'),'',plan)
            if [Path(p).resolve() for p in result['files']] != [part]:raise RuntimeError('Expressive voice output identity changed')
            with wave.open(str(part),'rb') as wav:
                if wav.getnchannels()!=1 or not wav.getnframes() or part.stat().st_size>32*1024**2:
                    raise RuntimeError('Expressive voice returned invalid audio')
            check();part.rename(out);result['files']=[str(out)];result['worker_seconds']=time.monotonic()-started;return result
        finally:
            if job:job.close()
            if proc:
                if proc.poll() is None:proc.kill()
                proc.wait(timeout=10)
            for path in (request,gate,part):path.unlink(missing_ok=True)
            if logpath.exists():
                for attempt in range(10):
                    try:os.replace(logpath,runtime/'nice-voice-last.log');break
                    except PermissionError:
                        if attempt==9:break
                        time.sleep(.1)


def worker(request):
    import runpy
    import sys
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root/'Agent'))
    gate=Path(os.environ['PORTALAI_VOICE_GATE']);deadline=time.monotonic()+15
    while not gate.exists():
        if time.monotonic()>=deadline:raise RuntimeError('Voice parent did not release startup gate')
        time.sleep(.05)
    data=json.loads(Path(request).read_text(encoding='utf-8'));admit(root)
    runner=root/'Voice/Qwen3-TTS/qwen_tts_runner.py'
    sys.argv=[str(runner),'custom','--text',data['text'],'--speaker','Ryan','--instruction',INSTRUCTION,
              '--language','English','--output',data['output']]
    runpy.run_path(str(runner),run_name='__main__')


if __name__=='__main__':
    import sys
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit('Internal voice worker')
    worker(sys.argv[2])
