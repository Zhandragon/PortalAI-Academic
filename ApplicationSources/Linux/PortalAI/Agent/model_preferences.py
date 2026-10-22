"""Portable, profile-scoped model choices; public assets/reserves stay shared."""
import copy
import json
import os
import uuid
from pathlib import Path

from profile_paths import capture, private_path, ProfileLocked

RELATIVE = 'Data/Settings/model_policy.json'
CHAT_KEYS = ('selection', 'backend', 'context_tokens', 'variant_preference', 'vision_routing')
MEDIA_CHOICES = {'media_variant': ('auto', 'standard', 'uncensored'),
                 'image_profile': ('auto', 'sd15', 'klein4', 'flux'),
                 'speech_model': ('auto', 'base', 'large-v3-turbo'),
                 'voice_engine': ('auto', 'piper', 'qwen'),
                 'image_engine': ('auto', 'comfyui', 'sdcpp-vulkan', 'sdcpp-cpu'),
                 'text_video_engine': ('auto', 'sdcpp-vulkan', 'sdcpp-cpu'),
                 'reference_video_profile': ('auto', 'wan22', 'vace13'),
                 'music_engine': ('auto', 'acestep-service', 'acestep-scaled', 'musicgen-cpu')}


def personal(policy):
    from academic_policy import enforce_policy
    policy = enforce_policy(policy)
    return {'selection': policy.get('selection', 'auto'),
            'backend': policy.get('backend', 'auto'),
            'context_tokens': policy.get('context_tokens', 8192),
            'variant_preference': policy.get('variant_preference', 'standard'),
            'vision_routing': policy.get('vision_routing', 'off'),
            'media': {key: policy.get('media', {}).get(key, 'auto') for key in MEDIA_CHOICES}}


def media_variant(policy):
    """Independent of chat, including accounts saved before the split."""
    return 'standard'


def validate(saved):
    if not isinstance(saved, dict) or set(saved) - {*CHAT_KEYS, 'media', 'version'}:
        raise ValueError('Invalid personal model settings')
    if 'selection' in saved and (not isinstance(saved['selection'], str) or
            not saved['selection'] or len(saved['selection']) > 128):
        raise ValueError('Invalid model selection')
    if 'backend' in saved and saved['backend'] not in ('auto', 'cuda', 'vulkan', 'cpu'):
        raise ValueError('Unknown backend')
    if 'context_tokens' in saved and (type(saved['context_tokens']) is not int or
            saved['context_tokens'] not in (2048, 4096, 8192, 16384, 32768)):
        raise ValueError('Unsupported context size')
    if saved.get('variant_preference', 'standard') not in ('standard', 'uncensored'):
        raise ValueError('Unknown model variant preference')
    if saved.get('vision_routing', 'off') not in ('automatic', 'off'):
        raise ValueError('Unknown image vision setting')
    media = saved.get('media', {})
    if not isinstance(media, dict) or set(media) - set(MEDIA_CHOICES) or any(
            value not in MEDIA_CHOICES[key] for key, value in media.items()):
        raise ValueError('Unknown media setting')
    return saved


def merge(policy, saved):
    from academic_policy import enforce_policy
    validate(saved)
    result = copy.deepcopy(policy)
    result.update({key: saved[key] for key in CHAT_KEYS if key in saved})
    result.setdefault('media', {}).update(saved.get('media', {}))
    return enforce_policy(result)


def effective(root, baseline):
    from academic_policy import enforce_policy
    baseline = enforce_policy(baseline)
    context = capture(root)
    if context is None:
        return baseline
    path = private_path(root, RELATIVE, context=context)
    try:
        if path.stat().st_size > 16384:
            raise ValueError('Personal model settings exceed the bounded size')
        saved = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        saved = {}  # Preserve the former shared choices until this user's first save.
    if capture(root) != context:
        raise ProfileLocked('Login ended while reading model settings')
    result = merge(baseline, saved)
    result['_profile_id'] = context[0]
    return result


def save(root, changes):
    """Authenticated GUI validates Session before calling; workers require epoch."""
    from runtime_policy import load_policy, atomic_json
    root = Path(root)
    context = capture(root)
    baseline = load_policy(root)
    current = effective(root, baseline)
    saved = personal(merge(current, changes))
    validate(saved)
    if context is None:
        atomic_json(root/'Agent/hardware_profiles.json', merge(baseline, changes))
        return
    path = private_path(root, RELATIVE, context=context)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    published = None
    try:
        private_path(root, RELATIVE, context=context, hydrate=False)
        with tmp.open('x', encoding='utf-8') as output:
            json.dump({'version': 1, **saved}, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        private_path(root, RELATIVE, context=context, hydrate=False)
        published = tmp.stat()
        os.replace(tmp, path)
        private_path(root, RELATIVE, context=context, hydrate=False)
    except Exception:
        # On revocation remove only this publication, never another writer's file.
        if published is not None:
            try:
                current_stat = path.stat()
                if (current_stat.st_dev, current_stat.st_ino, current_stat.st_mtime_ns) == (
                        published.st_dev, published.st_ino, published.st_mtime_ns):
                    path.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        tmp.unlink(missing_ok=True)
