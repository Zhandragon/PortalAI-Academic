"""Saved media route choices; actual compute/memory admission stays in each job."""
from runtime_policy import ROOT, detect_hardware, load_effective_policy
from model_preferences import MEDIA_CHOICES


def choice(key, explicit=None, *, root=ROOT, policy=None):
    if explicit is None:
        policy = load_effective_policy(root) if policy is None else policy
        explicit = policy.get('media', {}).get(key, 'auto')
    if explicit not in MEDIA_CHOICES[key]:
        raise ValueError('Unknown '+key.replace('_', ' '))
    return explicit


def _scaled(key, service, scaled, explicit, root, policy, hardware):
    selected = choice(key, explicit, root=root, policy=policy)
    hw = hardware if hardware is not None else detect_hardware()
    if hw.get('system') not in ('Windows', 'Linux'):
        raise RuntimeError('Bundled media routes require Windows or Linux x64')
    windows_cuda = hw['system']=='Windows' and any(
        g.get('index', 0)==0 and g.get('backend', 'cuda')=='cuda' for g in hw.get('gpus', []))
    if selected==service and not windows_cuda:
        raise RuntimeError(service+' requires Windows with NVIDIA CUDA; select Automatic or '+scaled)
    if selected==scaled and windows_cuda:
        raise RuntimeError(scaled+' is packaged for Windows ROCm or Linux CUDA/ROCm; use '+service+' on Windows NVIDIA')
    # The bounded worker still requires its real GPU probe and fresh resources.
    return not windows_cuda if selected=='auto' else selected==scaled


def reference_video_scaled(explicit=None, *, root=ROOT, policy=None, hardware=None):
    return _scaled('reference_video_profile', 'wan22', 'vace13', explicit, root, policy, hardware)


def music_scaled(explicit=None, *, root=ROOT, policy=None, hardware=None):
    return _scaled('music_engine', 'acestep-service', 'acestep-scaled', explicit, root, policy, hardware)
