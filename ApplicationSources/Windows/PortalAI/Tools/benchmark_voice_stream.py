"""Bounded synthetic Qwen streaming measurement; never uses an account workspace."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(ROOT/'Tools')]


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--preload', action='store_true')
    parser.add_argument('--playback', action='store_true')
    parser.add_argument('--cancel-prepared', action='store_true')
    args = parser.parse_args()
    if not args.label.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Use a simple benchmark label')
    from validation_artifacts import ValidationArtifacts
    artifacts = ValidationArtifacts(ROOT, ROOT/'Maintenance/Validation/VoiceStreaming_20261121')
    base = artifacts.path(args.label)
    if args.worker:
        import runpy
        runner = runpy.run_path(str(ROOT/'Voice/Qwen3-TTS/qwen_tts_runner.py'))
        import torch
        torch.set_num_threads(args.threads)
        torch.manual_seed(7)
        prepared = None
        if args.preload:
            prepared = runner['_load']('custom', device='cpu')
            if torch.cuda.is_initialized():
                raise AssertionError('CPU preparation initialized CUDA')
            if prepared.device.type != 'cpu' or prepared.model.speech_tokenizer.device.type != 'cpu':
                raise AssertionError('Preparation allocated GPU memory')
            (base/'prepared.json').write_text(json.dumps({'ready_at': time.time(), 'cuda_initialized': False}))
            deadline = time.monotonic()+15
            while not (base/'activate.gate').exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('Benchmark activation gate was not released')
                time.sleep(.025)
        from qwen_voice_stream import generate
        from nice_voice import INSTRUCTION
        generate(ROOT, {'text': 'Hello there. I am ready to help you today. We can take this one step at a time and work through it together.',
                        'output': str(base/'speech.wav'), 'stream_dir': str(base/'chunks')}, INSTRUCTION, preloaded=prepared)
        return
    from runtime_policy import detect_hardware, GIB
    from tts_policy import tts_plan
    from mission_supervisor import WorkerJob
    import service_manager as service
    plan = tts_plan(ROOT, 'qwen', hardware=detect_hardware(), policy={})
    if service._listener_identity().get('portable_qwen'):
        raise RuntimeError('Close the owned chat model before this isolated benchmark')
    base.mkdir(exist_ok=False)
    (base/'chunks').mkdir()
    (base/'received').mkdir()
    # Synthetic artifacts have their own cache; never impersonate a login.
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('PORTALAI_') or key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
            env.pop(key, None)
    cache = base/'cache'
    cache.mkdir()
    for key in ('TEMP', 'TMP', 'TMPDIR', 'HF_HOME', 'XDG_CACHE_HOME', 'TORCH_HOME'):
        env[key] = str(cache)
    env.update(PORTALAI_TORCH_BACKEND=plan['device'], OMP_NUM_THREADS='4', MKL_NUM_THREADS='4',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    lease = service.acquire_gpu_lease('voice-stream-benchmark', timeout=1)
    rows = []
    started = time.monotonic()
    proc = job = player = None
    try:
        if args.playback:
            import shutil
            from types import SimpleNamespace
            from voice_pcm_player import PCMPlayer
            # A disposable relocated playback root with the real bundled binary.
            playback_root = base/'relocated player'
            binary = playback_root/'Tools/ffmpeg/bin/ffplay.exe'
            binary.parent.mkdir(parents=True)
            shutil.copy2(ROOT/'Tools/ffmpeg/bin/ffplay.exe', binary)
            os.environ['SDL_AUDIODRIVER'] = 'dummy'
            voice = SimpleNamespace(root=playback_root, check=lambda: None, activity=None,
                                    status=lambda phase, text: print(json.dumps({'phase':phase, 'at':time.monotonic()-started}), flush=True))
            player = PCMPlayer(voice, -.5)
        with (base/'worker.log').open('wb') as log:
            proc = subprocess.Popen([sys.executable, '-B', '-I', __file__, '--label', args.label, '--threads', str(args.threads), '--worker'] + (['--preload'] if args.preload else []),
                                    cwd=ROOT, env=env, stdout=log, stderr=log,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            job = WorkerJob(proc)
            job.limit_memory((8 if args.preload else 16)*GIB)
            activated = False
            while True:
                job.check()
                if args.preload and not activated and (base/'prepared.json').exists():
                    if args.cancel_prepared:
                        job.close()
                        proc.wait(timeout=5)
                        if (base/'speech.wav').exists():
                            raise AssertionError('Cancelled preparation produced speech')
                        (base/'cancelled.json').write_text(json.dumps({'worker_exited':True, 'audio_published':False}))
                        print('Prepared worker cancellation passed', flush=True)
                        return
                    job.limit_memory(16*GIB)
                    (base/'activate.gate').touch()
                    activated = True
                for path in sorted((base/'chunks').glob('*.wav')):
                    try:
                        with wave.open(str(path), 'rb') as wav:
                            duration = wav.getnframes()/wav.getframerate()
                        path.rename(base/'received'/path.name)
                    except PermissionError:
                        break
                    row = {'chunk': path.name, 'arrival': round(time.monotonic()-started, 3), 'duration': duration}
                    rows.append(row)
                    if player:
                        player.push(base/'received'/path.name)
                    print(json.dumps(row), flush=True)
                if proc.poll() is not None:
                    break
                if time.monotonic()-started > 240:
                    raise TimeoutError('Synthetic voice benchmark exceeded 240 seconds')
                time.sleep(.025)
        result = {'returncode': proc.returncode, 'elapsed': time.monotonic()-started, 'chunks': rows}
        if player:
            player.finish()
            result['playback'] = {'started': player.started-started, 'finished': time.monotonic()-started,
                                  'bytes': player.samples, 'returncode': player.proc.returncode}
        if (base/'prepared.json').exists():
            result['preparation'] = json.loads((base/'prepared.json').read_text())
        (base/'timing.json').write_text(json.dumps(result, indent=2))
        print((base/'worker.log').read_text(errors='replace'), flush=True)
        if proc.returncode:
            raise RuntimeError('Synthetic voice worker failed')
    finally:
        if player:
            player.close()
        if job:
            job.close()
        if proc:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
        service.release_gpu_lease(lease)


if __name__ == '__main__':
    main()
