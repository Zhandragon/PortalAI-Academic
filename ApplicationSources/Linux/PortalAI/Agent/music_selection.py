"""Admission before any music inference; Automatic may choose CPU instrumentals."""
import time
from pathlib import Path
from media_defaults import choice, music_scaled
from runtime_policy import ROOT, GIB, detect_hardware
from profile_paths import capture, ProfileLocked


def request_guard(root=ROOT):
    root = Path(root).resolve(); requested_at = time.time(); context = capture(root)
    def check():
        from chat_model_switch import _guard
        if capture(root) != context: raise ProfileLocked('Music request login ended')
        _guard(root, requested_at)
    return check


def admit(explicit=None, *, prompt, lyrics, duration, instrumental, root=ROOT, policy=None, hardware=None):
    """Call only after the owned chat handoff. No inference retry/fallback here."""
    selected = choice('music_engine', explicit, root=root, policy=policy)
    hw = hardware if hardware is not None else detect_hardware()
    from music_cpu import plan as cpu_plan, validate_request as cpu_validate
    if selected == 'musicgen-cpu':
        cpu_validate(prompt, lyrics, duration, instrumental)
        return cpu_plan(root, hw)
    scaled = music_scaled(selected, root=root, policy=policy, hardware=hw)
    try:
        if scaled:
            from music_amd_bridge import plan, validate_request
            validate_request(prompt, lyrics, duration, 42)
            profile = plan(root, hw if hardware is not None else None)
            return {**profile, 'engine':'acestep-scaled'}
        gpu = next((g for g in hw.get('gpus', []) if g.get('index', 0) == 0 and g.get('backend', 'cuda') == 'cuda'), {})
        if gpu.get('free_bytes', 0) < 8*GIB or hw.get('ram_available_bytes', 0) < 8*GIB:
            raise RuntimeError('ACE-Step service needs 8 GiB free CUDA memory and 8 GiB free RAM after chat unload')
        if not 1 <= duration <= 480: raise ValueError('ACE-Step service supports 1..480 seconds; request was not truncated')
        return {'engine':'acestep-service', 'backend':'cuda', 'profile':'acestep-full'}
    except (RuntimeError, ValueError) as exc:
        if isinstance(exc, ProfileLocked) or selected != 'auto': raise
        # Only a valid, explicitly instrumental request can use the CPU fallback.
        cpu_validate(prompt, lyrics, duration, instrumental)
        return {**cpu_plan(root, hw), 'selection_note':'Automatic chose CPU before inference: '+str(exc)}
