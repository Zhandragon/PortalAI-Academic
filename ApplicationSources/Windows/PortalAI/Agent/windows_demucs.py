"""Pinned offline Windows vocal separation; no Hub/cache model lookup."""
import hashlib
import math
import os
from pathlib import Path
import stat

MODEL = 'MusicUnderstanding/models/HTDemucs/955717e8.safetensors'
MODEL_BYTES = 84025440
MODEL_SHA256 = 'd9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd'
MODEL_REVISION = 'cbc8a9b1a87023b7fd74e7b3412e6321c0eab003'
MAX_SECONDS = 300


def model_path(root, *, verify=True):
    from profile_paths import _contained
    path = _contained(Path(root).resolve(), Path(root).resolve()/MODEL)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != MODEL_BYTES:
        raise RuntimeError('Pinned offline Demucs model is missing or incomplete')
    if verify:
        with path.open('rb') as source:
            identity = os.fstat(source.fileno())
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
            after = os.fstat(source.fileno())
        current = path.stat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if (digest != MODEL_SHA256 or signature(info) != signature(identity) or
                signature(identity) != signature(after) or signature(after) != signature(current)):
            raise RuntimeError('Pinned offline Demucs model failed integrity verification')
    return path


def select_device(requested, torch):
    if requested not in ('cpu', 'cuda', 'auto'):
        raise ValueError('Demucs device must be cpu, cuda or auto')
    if requested == 'cpu': return 'cpu'
    available = torch.cuda.is_available()
    if requested == 'cuda' and not available:
        raise RuntimeError('Explicit Demucs CUDA device is unavailable')
    return 'cuda' if available else 'cpu'


def decode_audio(root, source, samplerate, channels):
    """Bound the complete input before allocation; never silently trim a clip."""
    import numpy as np
    import soundfile as sf
    try:
        info = sf.info(source)
    except (RuntimeError, OSError):
        info = None
    if info is not None:
        if (info.samplerate <= 0 or info.channels not in (1, 2) or
                not 0 < info.frames <= MAX_SECONDS*info.samplerate):
            raise ValueError('Demucs accepts complete mono/stereo clips up to 300 seconds')
        audio, rate = sf.read(source, dtype='float32', always_2d=True)
        if audio.shape != (info.frames, info.channels) or rate != info.samplerate:
            raise RuntimeError('Demucs input changed while decoding')
        if rate != samplerate:
            from scipy.signal import resample_poly
            divisor = math.gcd(rate, samplerate)
            audio = resample_poly(audio, samplerate//divisor, rate//divisor, axis=0).astype('float32')
        if channels == 2 and audio.shape[1] == 1: audio = np.repeat(audio, 2, axis=1)
        elif channels == 1 and audio.shape[1] == 2: audio = audio.mean(axis=1, keepdims=True)
    else:
        import json
        import subprocess
        from platform_runtime import ffmpeg_path
        options = dict(capture_output=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result = subprocess.run([str(ffmpeg_path(root, True)), '-v', 'error', '-show_entries',
            'format=duration', '-of', 'json', str(source)], timeout=30, **options)
        duration = float(json.loads(result.stdout)['format']['duration'])
        if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
            raise ValueError('Demucs accepts complete clips up to 300 seconds')
        result = subprocess.run([str(ffmpeg_path(root)), '-v', 'error', '-nostdin', '-i', str(source),
            '-t', '300.1', '-vn', '-ac', str(channels), '-ar', str(samplerate), '-f', 'f32le',
            '-acodec', 'pcm_f32le', 'pipe:1'], timeout=90, **options)
        limit = int(300.1*samplerate)*channels*4
        if not result.stdout or len(result.stdout)>limit or len(result.stdout)%(channels*4):
            raise RuntimeError('Demucs decoder returned an invalid or oversized stream')
        audio = np.frombuffer(result.stdout, dtype='<f4').copy().reshape(-1, channels)
        if len(audio)>MAX_SECONDS*samplerate:
            raise ValueError('Decoded Demucs audio exceeds 300 seconds; input was not trimmed')
    if (audio.ndim != 2 or audio.shape[1] != channels or not 0<len(audio)<=MAX_SECONDS*samplerate
            or not np.isfinite(audio).all()):
        raise RuntimeError('Demucs input is empty, oversized or non-finite')
    return audio


def infer(root, source, requested, check_current):
    """Return a complete stem; the caller owns epoch-checked private publication."""
    check_current()
    path = model_path(root)
    check_current()
    import numpy as np
    import torch
    from demucs.apply import apply_model
    from demucs.hf import load_safetensors_model
    from runtime_policy import require_space
    device = select_device(requested, torch)
    # This loader reads only the already-hashed safetensors, never get_hf_model.
    model = load_safetensors_model(path).to(device).eval()
    check_current()
    audio = decode_audio(root, source, model.samplerate, model.audio_channels)
    check_current()
    require_space(root, audio.nbytes*3+8*1024**2, for_outputs=True)
    wav = torch.from_numpy(audio.T.copy())
    reference = wav.mean(0); mean = reference.mean(); std = reference.std()
    if not torch.isfinite(std) or std < 1e-8: std = torch.tensor(1.)
    with torch.inference_mode():
        stems = apply_model(model, ((wav-mean)/std)[None], device=device,
            shifts=1, split=True, overlap=.25, segment=4, num_workers=0, progress=False)[0]
        vocals = (stems[model.sources.index('vocals')]*std+mean).cpu().T.numpy()
    check_current()
    if vocals.shape != audio.shape or not np.isfinite(vocals).all():
        raise RuntimeError('Demucs returned an invalid vocal stem')
    return vocals, model.samplerate, device
