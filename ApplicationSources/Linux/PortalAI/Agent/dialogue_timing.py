"""Explicit dialogue timelines; bounded model calls never change spoken words."""
from __future__ import annotations
import json
import math

MAX_SECONDS = 120.0


def options(duration=None, dialogue_start=0., motion_plan=None):
    def number(value, label, low, high):
        if isinstance(value, bool):
            raise ValueError(label + ' must be a finite number')
        value = float(value)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{label} must be {low}..{high} seconds')
        return value
    duration = None if duration is None else number(duration, '--duration', .2, MAX_SECONDS)
    start = number(dialogue_start, '--dialogue-start', 0, MAX_SECONDS)
    if duration is not None and start >= duration:
        raise ValueError('--dialogue-start must be before --duration')
    beats = json.loads(motion_plan) if isinstance(motion_plan, str) else motion_plan
    if beats is not None:
        if duration is None:
            raise ValueError('--motion-plan requires --duration')
        if not isinstance(beats, list) or not 1 <= len(beats) <= 32:
            raise ValueError('--motion-plan must be a JSON array of 1..32 {seconds, prompt} objects')
        checked = []
        for row in beats:
            if not isinstance(row, dict) or set(row) != {'seconds', 'prompt'}:
                raise ValueError('Each motion-plan item needs exactly seconds and prompt')
            seconds = number(row['seconds'], 'motion beat', .2, MAX_SECONDS)
            prompt = row['prompt']
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
                raise ValueError('Each motion beat needs a prompt of 1..4000 characters')
            checked.append({'seconds': seconds, 'prompt': prompt})
        if abs(sum(row['seconds'] for row in checked) - duration) > .001:
            raise ValueError('Motion-plan seconds must sum to --duration')
        beats = checked
    return {'duration': duration, 'dialogue_start': start, 'motion_plan': beats}


def target(speech_seconds, timing):
    if not math.isfinite(speech_seconds) or speech_seconds <= 0:
        raise ValueError('Speech has no valid duration')
    end = timing['dialogue_start'] + speech_seconds
    duration = timing['duration'] if timing['duration'] is not None else max(.2, end)
    if end > duration + .001:
        raise ValueError(f'Dialogue ends at {end:.3f}s but --duration is {duration:.3f}s. '
                         'Increase duration, move dialogue earlier, or request shorter dialogue; speech was not cut or sped up.')
    if duration > MAX_SECONDS:
        raise ValueError('Dialogue timeline exceeds 120 seconds; split into separate videos. Speech was not truncated.')
    return duration


def motion_chunks(seconds, fps, max_frames, prompt, beats=None):
    """Round timeline boundaries to frames; only graph padding is discarded."""
    if type(fps) is not int or not 4 <= fps <= 30:
        raise ValueError('Dialogue FPS must be 4..30')
    total = math.ceil(seconds * fps)
    result = []; start_frame = 0; elapsed = 0.
    for beat in beats or [{'seconds': seconds, 'prompt': prompt}]:
        elapsed += beat['seconds']
        end_frame = min(total, math.ceil(round(elapsed * fps, 8)))
        while start_frame < end_frame:
            count = min(max_frames, end_frame - start_frame)
            graph_frames = max(5, ((count - 1 + 3) // 4) * 4 + 1)
            result.append({'start': start_frame / fps, 'seconds': count / fps,
                           'frames': graph_frames, 'keep_frames': count, 'prompt': beat['prompt']})
            start_frame += count
    return result


def lip_chunks(seconds, fps):
    """Every speech-driven model invocation remains at most eight seconds."""
    count = math.ceil(seconds * fps); start = 0
    # Balance segments so a tiny tail never falls below the model's 0.2s minimum.
    per_segment = math.ceil(count / math.ceil(seconds / 8))
    while start < count:
        frames = min(per_segment, count - start)
        yield start / fps, min(frames / fps, seconds - start / fps)
        start += frames


def capability():
    return {'command': 'dialogue-video', 'duration_seconds': [.2, MAX_SECONDS],
        'duration': '--duration sets the final video length; omitted means speech length plus dialogue-start.',
        'dialogue_start': '--dialogue-start places natural-speed speech within the video (default 0). Silence fills the rest. Speech must fit.',
        'motion_plan': '--motion-plan is a JSON array of {seconds, prompt} beats summing to --duration; optional --motion describes the whole shot.',
        'execution': 'Sequential generated motion with last-frame continuation; bounded lip-sync segments. No frozen-frame extension. Stop remains available.',
        'hardware': 'Requires admitted Windows CUDA or Radeon/Linux GPU reference motion and lip sync; CPU/Vulkan-only dialogue unavailable. Radeon music limited to 30s.',
        'quality': 'Timing is validated; character continuity, action accuracy and lip-sync quality depend on models and hardware.',
        'example': {'command': 'dialogue-video', 'arguments': ['Data/Chat/Attachments/example/photo.png',
            'The exact words to speak.', '--duration', '20', '--dialogue-start', '5', '--motion-plan',
            '[{"seconds":5,"prompt":"The character approaches the doorway."},{"seconds":8,"prompt":"The character speaks and opens the door."},{"seconds":7,"prompt":"The character runs through the doorway."}]']}}
