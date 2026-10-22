"""Sequential, bounded reference-motion dialogue for ROCm and Linux CUDA.

The caller owns ONE existing GPU lease/handoff for the entire pipeline.  This
module never enters another lease or substitutes text-only/still-frame video.
Production CPU/Vulkan dialogue is unavailable until image-conditioned motion
and MuseTalk have admitted production backends for those devices.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

from media_paths import media_output, media_reference
from profile_paths import ProfileLocked, _contained, capture, private_path
from platform_runtime import ffmpeg_path, python_path
from runtime_policy import atomic_json, memory_info, portable_env, require_space

from dialogue_timing import MAX_SECONDS, options as timing_options, target as timing_target, motion_chunks, lip_chunks


def prepare(root, options):
    """Validate source, explicit options and destination before chat unload."""
    from tts_policy import validate_text
    from vace_reference import prepare as prepare_reference
    root = Path(root).resolve()
    requested_at = time.time()
    context = capture(root)
    get = options.get if isinstance(options, dict) else lambda key, default=None: getattr(options, key, default)
    timing = timing_options(get('duration'), get('dialogue_start', 0.), get('motion_plan'))
    dialogue = validate_text(get('dialogue'))
    fps = get('fps', 16)
    seed = get('seed')
    seed = secrets.randbelow(2**63) if seed is None else seed
    motion = prepare_reference(root, get('input'), get('motion'), width=get('width'), height=get('height'),
                               frames=5, fps=fps, seed=seed, uncensored=bool(get('uncensored', False)))
    language = get('language', 'English')
    if not isinstance(language, str) or not language.strip() or len(language) > 100:
        raise ValueError('Dialogue language is invalid')
    reference = get('reference_audio')
    reference = str(media_reference(root, reference)) if reference else None
    if reference and not Path(reference).is_file():
        raise FileNotFoundError('Reference voice audio is missing')
    if reference and get('speaker'):
        raise ValueError('Choose reference-audio or speaker, not both')
    if get('ref_text') and not reference:
        raise ValueError('--ref-text requires --reference-audio')
    music_prompt = get('music_prompt')
    if music_prompt is not None:
        from music_amd_bridge import validate_request
        validate_request(music_prompt, get('music_lyrics') or '', max(10., timing['duration'] or 10.), seed % 2**31)
    volume = float(get('music_volume', .25))
    if not math.isfinite(volume) or not 0 <= volume <= 4:
        raise ValueError('Music volume must be finite and between 0 and 4')
    output = media_output(root, get('output')) if get('output') else (
        private_path(root, 'Outputs/Videos', context=context) / ('dialogue_' + uuid.uuid4().hex + '.mp4'))
    if output.suffix.lower() != '.mp4':
        raise ValueError('Dialogue output must be an MP4')
    if output.exists():
        raise FileExistsError('Dialogue output already exists; choose a new filename')
    return {'timing': timing, 'motion': motion, 'dialogue': dialogue, 'language': language, 'reference_audio': reference,
            'ref_text': get('ref_text'), 'speaker': get('speaker'), 'voice_description': get('voice_description'),
            'music_prompt': music_prompt, 'music_lyrics': get('music_lyrics') or '',
            'music_instrumental': bool(get('music_instrumental', False)), 'music_volume': volume,
            'duck_music': not bool(get('no_duck_music', False)), 'output': str(output),
            'profile_context': context, 'requested_at': requested_at}


def check_request(request, *, root):
    """The same request fence applies before waiting/acquiring a lease and later."""
    from chat_model_switch import _guard
    root = Path(root).resolve()
    if capture(root) != request['profile_context']:
        raise ProfileLocked('Dialogue generation login ended before publication')
    _guard(root, request['requested_at'])


def frame_chunks(seconds, fps):
    """Enough genuine generated frames for speech, within each VACE 17-frame cap."""
    if not math.isfinite(seconds) or not .2 <= seconds <= MAX_SECONDS:
        raise ValueError('Dialogue supports 0.2..120 seconds; split longer requests into videos. Speech was not truncated.')
    if type(fps) is not int or not 4 <= fps <= 30:
        raise ValueError('Scaled dialogue FPS must be 4..30')
    remaining = math.ceil(seconds * fps)
    result = []
    while remaining > 0:
        requested = min(17, remaining)
        frames = max(5, ((requested - 1 + 3) // 4) * 4 + 1)
        result.append(frames)
        remaining -= frames
    return result


def _voice(request, destination, root):
    from voice_bridge import VoiceBridge
    bridge = VoiceBridge()
    if Path(bridge.root).resolve() != Path(root).resolve():
        raise RuntimeError('Voice bridge belongs to another portable root')
    common = {'text': request['dialogue'], 'language': request['language'], 'output': str(destination)}
    if request['reference_audio']:
        return bridge.clone(**common, reference_audio=request['reference_audio'], ref_text=request['ref_text'])
    if request['speaker']:
        return bridge.custom(**common, speaker=request['speaker'], instruction=request['voice_description'])
    return bridge.design(**common, description=request['voice_description'] or
                         'Natural adult speaking voice, conversational, realistic, understated')


def _run(root, argv, work, check, timeout=120):
    """Gate finite FFmpeg/probe work before assigning a bounded owned job."""
    from mission_supervisor import WorkerJob
    token = uuid.uuid4().hex
    request, gate, stdout, stderr = [work / (token + suffix) for suffix in ('.json', '.gate', '.stdout', '.stderr')]
    check()
    atomic_json(request, {'command': list(map(str, argv)), 'gate': str(gate)})
    process = job = None
    try:
        with stdout.open('xb') as out, stderr.open('xb') as err:
            process = subprocess.Popen([str(python_path(root)), '-B', '-I', str(root / 'Agent/sdcpp_worker.py'), str(request)],
                cwd=root, env=portable_env(root), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            job = WorkerJob(process)
            job.limit_memory(2 * 1024**3)
            check()
            gate.touch()
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                check(); job.check()
                if time.monotonic() > deadline:
                    raise TimeoutError('Dialogue media processing timed out')
                if memory_info()[1] < 2 * 1024**3:
                    raise RuntimeError('Dialogue processing stopped at the free-RAM reserve')
                if stdout.stat().st_size + stderr.stat().st_size > 2 * 1024**2:
                    raise RuntimeError('Dialogue media processing log exceeded its limit')
                require_space(root, for_outputs=True)
                time.sleep(.1)
        check()
        if stdout.stat().st_size + stderr.stat().st_size > 2 * 1024**2:
            raise RuntimeError('Dialogue media processing log exceeded its limit')
        if process.returncode:
            raise RuntimeError('Dialogue media processing failed: ' + stderr.read_text(encoding='utf-8', errors='replace')[-1500:])
        return stdout.read_text(encoding='utf-8', errors='strict')
    finally:
        if job:
            job.close()
        if process and process.poll() is None:
            process.kill(); process.wait(timeout=10)
        for path in (request, gate, stdout, stderr):
            path.unlink(missing_ok=True)


def _probe(root, path, work, check):
    text = _run(root, [ffmpeg_path(root, True), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
                work, check, timeout=45)
    value = json.loads(text)
    duration = float(value.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError('Dialogue media has no finite positive duration')
    return value, duration


def _remove_owned(root, path, identity):
    """After revocation, remove only the exact new regular file we recorded."""
    try:
        _contained(root, path)
        current = path.lstat()
        if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
            path.unlink()
    except (FileNotFoundError, PermissionError):
        pass


def _adopt(result, root, folder, prefix, owned):
    files = result.get('files') or []
    if len(files) != 1:
        raise RuntimeError('Dialogue stage did not produce exactly one file')
    path = Path(files[0])
    _contained(root, path)
    if path.parent != folder or not path.name.startswith(prefix):
        raise RuntimeError('Dialogue stage returned a file outside its owned output namespace')
    current = path.lstat()
    if not stat.S_ISREG(current.st_mode):
        raise RuntimeError('Dialogue stage output is not a regular file')
    owned.append((path, (current.st_dev, current.st_ino)))
    return path


def _publish(root, source, destination, check):
    from profile_lazy_state import publish_no_replace
    check()
    destination = media_output(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError('Dialogue output already exists; it was not overwritten')
    require_space(root, source.stat().st_size, for_outputs=True)
    pending = destination.with_name(destination.stem + '.' + uuid.uuid4().hex + '.part.mp4')
    identity = published_identity = None
    try:
        with pending.open('xb') as writer, source.open('rb') as reader:
            current = os.fstat(writer.fileno()); identity = (current.st_dev, current.st_ino)
            shutil.copyfileobj(reader, writer, 1024**2)
            writer.flush(); os.fsync(writer.fileno())
        check()
        publish_no_replace(pending, destination)
        published_identity = identity
        check()
        return destination
    except BaseException:
        if published_identity:
            _remove_owned(root, destination, published_identity)
        raise
    finally:
        if identity:
            _remove_owned(root, pending, identity)


def generate(request, *, root, progress=None):
    """Caller must hold _exclusive_pipeline; all model stages are synchronous."""
    from musetalk_amd_bridge import plan as lip_plan, generate as lip_generate
    from music_amd_bridge import plan as music_plan, generate as music_generate
    from radeon_edit import plan as motion_plan
    from tts_policy import tts_plan
    from vace_reference import generate as reference_generate
    root = Path(root).resolve()
    context = request['profile_context']
    def check():
        check_request(request, root=root)
    def stage(name):
        check()
        if progress:
            progress(name)
    check()
    if media_output(root, request['output']).exists():
        raise FileExistsError('Dialogue output already exists; choose a new filename')
    # Reject a missing production stage before voice generation. Re-admit each
    # stage against fresh free memory after its predecessor has exited.
    motion_plan('video-edit', root=root)
    lip_plan(root=root)
    tts_plan(root, 'qwen', language=request['language'])
    if request['music_prompt']:
        music_plan(root=root)
    require_space(root, 512 * 1024**2, for_outputs=True)
    base = private_path(root, 'Cache/MediaWorkers', context=context) / 'Dialogue'
    base.mkdir(parents=True, exist_ok=True)
    owned = []
    try:
        with tempfile.TemporaryDirectory(prefix='job_', dir=base) as temporary:
            work = _contained(root, Path(temporary))
            voice = work / 'voice.wav'
            stage('voice')
            tts_plan(root, 'qwen', language=request['language'])
            voice_result = _voice(request, voice, root)
            check()
            if list(map(str, voice_result.get('files') or [])) != [str(voice)] or not voice.is_file():
                raise RuntimeError('Voice stage did not return its requested private audio file')
            voice_info, duration = _probe(root, voice, work, check)
            if not any(row.get('codec_type') == 'audio' for row in voice_info.get('streams', [])):
                raise RuntimeError('Voice stage produced no audio stream')
            speech_seconds = duration
            timing = request.get('timing') or timing_options()
            duration = timing_target(speech_seconds, timing)
            if request['music_prompt']:
                from music_amd_bridge import validate_request
                validate_request(request['music_prompt'], request['music_lyrics'], max(10., duration), request['motion']['seed'] % 2**31)
            original_voice = voice
            if timing['dialogue_start'] or abs(duration - speech_seconds) > .001:
                voice = work / 'aligned_voice.wav'
                _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-i', original_voice,
                    '-af', f"aresample=48000,adelay={round(timing['dialogue_start'] * 48000)}S:all=1,apad",
                    '-t', str(duration), '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', voice], work, check)
            motion = dict(request['motion'])
            pieces = motion_chunks(duration, motion['fps'], 17, motion['prompt'], timing['motion_plan'])
            chunks = [piece['frames'] for piece in pieces]
            videos = private_path(root, 'Outputs/Videos', context=context)
            paths = []
            for index, frames in enumerate(chunks):
                stage(f'motion {index + 1}/{len(chunks)}')
                profile = motion_plan('video-edit', root=root)
                piece = {**motion, 'prompt': pieces[index]['prompt'], 'frames': frames, 'seed': (request['motion']['seed'] + index) % 2**63}
                result = reference_generate(piece, profile, root=root)
                generated = _adopt(result, root, videos, 'VACE_reference_', owned)
                check()
                local = work / f'clip_{index:03}.mp4'
                if pieces[index]['keep_frames'] == frames:
                    shutil.copy2(generated, local)
                else:
                    _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-i', generated,
                        '-an', '-frames:v', str(pieces[index]['keep_frames']), '-c:v', 'libx264',
                        '-threads', '2', '-pix_fmt', 'yuv420p', local], work, check)
                paths.append(local)
                if index + 1 < len(chunks):
                    reference = work / f'reference_{index:03}.png'
                    _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-i', local,
                        '-vf', f"select=eq(n\\,{pieces[index]['keep_frames'] - 1})", '-fps_mode', 'passthrough', '-frames:v', '1',
                        '-threads', '2', reference], work, check)
                    if not reference.is_file():
                        raise RuntimeError('Generated motion has no continuation reference; no still-image fallback was used')
                    motion['source'] = str(reference)
            playlist = work / 'clips.txt'
            playlist.write_text(''.join("file '" + path.name + "'\n" for path in paths), encoding='utf-8')
            aligned = work / 'motion.mp4'
            stage('align motion')
            _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-f', 'concat', '-safe', '1',
                '-i', playlist, '-an', '-t', str(duration), '-r', str(motion['fps']), '-c:v', 'libx264',
                '-threads', '2', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', aligned], work, check)
            _, aligned_duration = _probe(root, aligned, work, check)
            if aligned_duration + .025 < duration:
                raise RuntimeError('Generated motion is shorter than speech; refusing a frozen-frame substitute')
            lip_paths = []
            segments = list(lip_chunks(duration, motion['fps']))
            for index, (start, length) in enumerate(segments):
                stage(f'lip sync {index + 1}/{len(segments)}')
                segment_video, segment_voice = aligned, voice
                if len(segments) > 1:
                    segment_video, segment_voice = work / f'lip_input_{index}.mp4', work / f'lip_voice_{index}.wav'
                    first, last = round(start * motion['fps']), math.ceil(round((start + length) * motion['fps'], 8))
                    _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-i', aligned,
                        '-vf', f"trim=start_frame={first}:end_frame={last},setpts=N/({motion['fps']}*TB)",
                        '-frames:v', str(last-first), '-r', str(motion['fps']), '-an', '-c:v', 'libx264',
                        '-threads', '2', '-pix_fmt', 'yuv420p', segment_video], work, check)
                    _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-ss', str(start), '-i', voice,
                        '-t', str(length), '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', segment_voice], work, check)
                lips = lip_generate(lip_plan(root=root), segment_video, segment_voice, root=root)
                generated = _adopt(lips, root, videos / 'MuseTalk', 'musetalk_', owned)
                check()
                local = work / f'lip_{index}.mp4'
                _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-i', generated,
                    '-an', '-t', str(length), '-vf', f"fps={motion['fps']},scale={motion['width']}:{motion['height']}",
                    '-c:v', 'libx264', '-threads', '2', '-pix_fmt', 'yuv420p', local], work, check)
                lip_paths.append(local)
            lip_video = lip_paths[0]
            if len(lip_paths) > 1:
                lip_list = work / 'lip_clips.txt'
                lip_list.write_text(''.join("file '" + path.name + "'\n" for path in lip_paths), encoding='utf-8')
                lip_video = work / 'lips.mp4'
                _run(root, [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-f', 'concat', '-safe', '1',
                    '-i', lip_list, '-an', '-c:v', 'copy', lip_video], work, check)
            music = None
            if request['music_prompt']:
                stage('music')
                music_result = music_generate(music_plan(root=root), request['music_prompt'],
                    lyrics=request['music_lyrics'], duration=max(10., duration), instrumental=request['music_instrumental'],
                    seed=request['motion']['seed'] % 2**31, root=root)
                music = _adopt(music_result, root, private_path(root, 'Outputs/Music', context=context), 'acestep_', owned)
                check()
            stage('finalize')
            final = work / 'final.mp4'
            command = [ffmpeg_path(root), '-v', 'error', '-nostdin', '-n', '-i', lip_video, '-i', voice]
            if music:
                command += ['-i', music]
                volume = request['music_volume']
                filters = f'[1:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][side];[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={volume}[music];'
                if request['duck_music']:
                    filters += '[music][side]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=350[bed];'
                else:
                    filters += '[side]anullsink;[music]anull[bed];'
                filters += '[voice][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[audio]'
                command += ['-filter_complex', filters, '-map', '0:v:0', '-map', '[audio]']
            else:
                command += ['-map', '0:v:0', '-map', '1:a:0']
            command += ['-t', str(duration), '-vf', f'fps={motion["fps"]},scale={motion["width"]}:{motion["height"]}:flags=lanczos', '-c:v', 'libx264', '-threads', '2',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', final]
            _run(root, command, work, check)
            info, actual = _probe(root, final, work, check)
            stream = next((row for row in info.get('streams', []) if row.get('codec_type') == 'video'), {})
            try:
                numerator, denominator = map(float, stream['avg_frame_rate'].split('/'))
                rate = numerator / denominator
            except (ValueError, KeyError, ZeroDivisionError) as exc:
                raise RuntimeError('Dialogue output frame rate is invalid') from exc
            if (not any(row.get('codec_type') == 'audio' for row in info.get('streams', []))
                    or not math.isfinite(rate) or abs(rate - motion['fps']) > .01
                    or abs(actual - duration) > max(.1, 1 / motion['fps'] + .05)
                    or (stream.get('width'), stream.get('height')) != (motion['width'], motion['height'])):
                raise RuntimeError('Dialogue output failed dimensions, duration, frame-rate or audio validation')
            output = _publish(root, final, request['output'], check)
            return {'success': True, 'tool': 'dialogue-video', 'backend': 'Qwen3-TTS + VACE 1.3B reference + MuseTalk 1.5',
                    'files': [str(output)], 'speech_seconds': speech_seconds, 'target_seconds': duration,
                    'dialogue_start': timing['dialogue_start'], 'motion_plan': timing['motion_plan'], 'lip_sync_segments': len(segments),
                    'output_duration_seconds': actual, 'fps': motion['fps'], 'resolution': [motion['width'], motion['height']],
                    'motion_chunks': chunks, 'source': request['motion']['source'], 'motion_prompt': request['motion']['prompt'],
                    'seed': request['motion']['seed'],
                    'conditioning': 'reference-image with generated-frame continuation', 'dialogue_sync': 'duration-validated',
                    'voice_device': voice_result.get('device'), 'model_variant': 'wan-vace-1.3b-reference',
                    'music_generated_seconds': max(10., duration) if music else None,
                    'limitations': '0.2..120 seconds with bounded motion and <=8s lip-sync segments; generated reference continuity and lip-sync quality require physical-device validation. No exact first-frame guarantee.',
                    'physical_hardware_validated': False}
    finally:
        for path, identity in owned:
            _remove_owned(root, path, identity)
