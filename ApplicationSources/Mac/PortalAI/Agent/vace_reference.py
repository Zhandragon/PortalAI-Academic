"""Bounded VACE reference-conditioned generation; caller holds the GPU lease.

This is reference-image conditioning, not a guarantee of an identical first
frame. Unlike video editing, no source video/control tensor enters the graph.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from media_paths import media_reference, media_output
from profile_paths import private_path, capture, ProfileLocked
from platform_runtime import ffmpeg_path


def _probe(root, path, *, count_frames=False):
    args = [str(ffmpeg_path(root, True)), '-v', 'error', '-select_streams', 'v:0']
    if count_frames:
        args += ['-count_frames']
    args += ['-show_entries', 'stream=width,height,nb_read_frames,avg_frame_rate,duration:format=duration',
             '-of', 'json', str(path)]
    result = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Cannot inspect VACE reference/result: ' + result.stderr[-1000:])
    data = json.loads(result.stdout)
    streams = data.get('streams') or []
    if not streams:
        raise ValueError('Reference/result has no visual stream')
    return streams[0], data.get('format') or {}


def prepare(root, source, prompt, *, width=None, height=None, frames=None, fps=None,
            seed=42, uncensored=False):
    """Validate semantics and profile paths before unloading the chat model."""
    uncensored = False
    source = media_reference(root, source)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}:
        raise ValueError('Scaled video requires a PNG/JPEG/WebP/BMP reference image')
    if uncensored:
        raise ValueError('VACE has no separate uncensored weights configured. Its local graph has no separate content filter; use --official for the existing reference-conditioned route. video-small is a distinct text-only alternative.')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ValueError('Video prompt must contain 1..4000 characters')
    frames = 17 if frames is None else frames
    fps = 8 if fps is None else fps
    if type(frames) is not int or frames not in {1, 5, 9, 13, 17}:
        raise ValueError('Scaled reference video length must be 1, 5, 9, 13 or 17 frames; use video-range-edit for longer footage')
    if type(fps) is not int or not 4 <= fps <= 30:
        raise ValueError('Scaled reference video FPS must be 4..30')
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('Invalid video seed')
    for side in (width, height):
        if side is not None and (type(side) is not int or not 128 <= side <= 320 or side % 16):
            raise ValueError('Scaled reference video dimensions must be multiples of 16 between 128 and 320')
    stream, _ = _probe(root, source)
    source_w, source_h = int(stream.get('width', 0)), int(stream.get('height', 0))
    if min(source_w, source_h) < 1:
        raise ValueError('Reference image dimensions are unavailable')
    if width is None and height is None:
        scale = min(1., 320 / max(source_w, source_h))
        width, height = max(128, int(source_w * scale) // 16 * 16), max(128, int(source_h * scale) // 16 * 16)
    elif width is None:
        width = max(128, round(height * source_w / source_h / 16) * 16)
    elif height is None:
        height = max(128, round(width * source_h / source_w / 16) * 16)
    if max(width, height) > 320:
        raise ValueError('Requested aspect ratio exceeds the scaled 320-pixel profile; provide both dimensions')
    return {'source': str(source), 'prompt': prompt.strip(), 'width': width, 'height': height,
            'frames': frames, 'fps': fps, 'seed': seed, 'conditioning': 'reference-image'}


def configure(bridge, request, reference_name):
    """Use native VACE reference conditioning with no retained-video input."""
    from radeon_edit import small_vace
    if not reference_name:
        raise ValueError('VACE generation requires an explicit image reference')
    workflow = bridge.workflow_file('Workflows/API/Wan2.1_VACE_14B_V2V_API.json')
    bridge.configure_vace_video_edit(workflow, video_name='unused-reference-generation',
        prompt=request['prompt'], seed=request['seed'], width=request['width'], height=request['height'],
        length=request['frames'], fps=request['fps'], strength=1., fast=False,
        reference_image_name=reference_name)
    small_vace(workflow)
    workflow.pop('8')
    workflow.pop('9')
    workflow['10']['inputs'].pop('control_video')
    workflow['10']['inputs'].pop('control_masks', None)
    return workflow


def validate_output(root, path, request):
    if not path.is_file() or path.stat().st_size < 128:
        raise RuntimeError('VACE produced no usable video')
    stream, fmt = _probe(root, path, count_frames=True)
    try:
        num, den = str(stream['avg_frame_rate']).split('/')
        rate = float(num) / float(den)
        duration = float(stream.get('duration') or fmt.get('duration'))
        count = int(stream['nb_read_frames'])
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise RuntimeError('VACE result has invalid timing metadata') from exc
    if ((int(stream.get('width', 0)), int(stream.get('height', 0))) != (request['width'], request['height'])
            or count != request['frames'] or not math.isfinite(rate) or abs(rate - request['fps']) > .01
            or not math.isfinite(duration) or abs(duration - count / rate) > .025):
        raise RuntimeError('VACE result dimensions, frame count or duration do not match the requested clip')
    return duration


def generate(request, profile, *, root):
    """Run inside a bounded owned Comfy job; exceptions/cancellation never publish."""
    from bounded_comfy import session
    from comfy_bridge import ComfyBridge
    from runtime_policy import require_space
    context = capture(root)
    def check_profile():
        if capture(root) != context:
            raise ProfileLocked('The video generation login ended before publication')
    if (profile.get('engine') != 'wan-vace-1.3b' or profile.get('backend') not in {'rocm', 'cuda'}
            or profile.get('cpu_validation') or profile.get('max_memory_bytes', 0) <= 0):
        raise ValueError('Reference video requires an admitted, memory-bounded GPU profile')
    source = media_reference(root, request['source'])
    base = private_path(root, 'Cache/MediaWorkers', context=context) / 'VaceReference'
    base.mkdir(parents=True, exist_ok=True)
    staged = None
    with tempfile.TemporaryDirectory(prefix='job_', dir=base) as temporary:
        try:
            check_profile()
            with session(profile, root=root):
                bridge = ComfyBridge()
                bridge.ccfg = {**bridge.ccfg, 'min_free_ram_bytes': profile['min_free_ram_bytes'],
                               'history_timeout_seconds': 2}
                reference, staged = bridge.stage_input_file(source, 'portalai_vace_reference')
                workflow = configure(bridge, request, reference)
                result = bridge.run(workflow, Path(temporary))
                files = result.get('files') or []
                if len(files) != 1:
                    raise RuntimeError('VACE reference generation did not produce exactly one video')
                generated = Path(files[0]).resolve()
                if not generated.is_relative_to(Path(temporary).resolve()):
                    raise RuntimeError('VACE output escaped this generation workspace')
                actual_duration = validate_output(root, generated, request)
            check_profile()
            outputs = private_path(root, 'Outputs/Videos', context=context)
            outputs.mkdir(parents=True, exist_ok=True)
            destination = media_output(root, outputs / ('VACE_reference_' + uuid.uuid4().hex + '.mp4'))
            require_space(root, generated.stat().st_size, for_outputs=True)
            pending = destination.with_suffix('.part.mp4')
            published = False
            identity = None
            try:
                check_profile()
                shutil.copy2(generated, pending)
                validate_output(root, pending, request)
                check_profile()
                stat = pending.stat(); identity = (stat.st_dev, stat.st_ino)
                pending.replace(destination)
                published = True
                check_profile()
                return {'files': [str(destination)], 'backend': 'Wan2.1 VACE 1.3B ' + profile['backend'].upper(),
                        'model_variant': 'wan-vace-1.3b-reference', 'conditioning': 'reference-image',
                        'variant_reason': 'Bounded reference-conditioned generation, no source-video control',
                        'hardware_profile': profile, 'resolution': [request['width'], request['height']],
                        'frames': request['frames'], 'fps': request['fps'], 'seed': request['seed'],
                        'output_duration_seconds': actual_duration, 'generated_audio': 'silent'}
            except BaseException:
                pending.unlink(missing_ok=True)
                if published and destination.is_file():
                    stat = destination.stat()
                    if (stat.st_dev, stat.st_ino) == identity:
                        destination.unlink()
                raise
        finally:
            if staged is not None:
                ComfyBridge.cleanup_staged_file(staged)
