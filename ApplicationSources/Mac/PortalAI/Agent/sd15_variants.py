"""Named SD1.5 checkpoints shared by native and ComfyUI image routes.

DreamShaper is a community fine-tune with publisher-described NSFW support,
not an abliterated SD1.5 release or a guarantee about generated content.
"""
import copy
from pathlib import Path
from runtime_policy import portable_path

MODELS = 'Generative/ComfyUI_windows_portable/ComfyUI/models/checkpoints/'
STANDARD = 'v1-5-pruned-emaonly.safetensors'
ALTERNATE = 'DreamShaper_8_pruned.safetensors'
ALTERNATE_BYTES = 2132625894


def normalize_variant(variant):
    return 'standard'


def checkpoint(root, variant):
    alternate = normalize_variant(variant) == 'uncensored'
    path = portable_path(Path(root), MODELS + (ALTERNATE if alternate else STANDARD))
    if not path.is_file() or (alternate and path.stat().st_size != ALTERNATE_BYTES):
        raise RuntimeError('SD1.5 ' + ('DreamShaper 8 alternate' if alternate else 'standard') +
                           ' checkpoint missing/incomplete. Run Tools/import_media_assets.py --install with the bundled Python.')
    return path


def select_plan(plan, root, variant):
    """Preserve the admitted backend, dimensions and memory limits."""
    if plan.get('profile') != 'sd15':
        raise ValueError('SD1.5 variant selection requires the sd15 image profile')
    selected = normalize_variant(variant)
    path = checkpoint(root, selected)
    return {**plan, 'model_variant': selected,
            'checkpoint': path.relative_to(Path(root).resolve()).as_posix(),
            'model_name': 'DreamShaper 8' if selected == 'uncensored' else 'Stable Diffusion 1.5'}


def configure_workflow(workflow, root, variant):
    """Change only the single SD1.5 checkpoint; never mutate the saved graph."""
    path = checkpoint(root, variant)
    result = copy.deepcopy(workflow)
    loaders = [node for node in result.values() if node.get('class_type') == 'CheckpointLoaderSimple']
    if len(loaders) != 1 or loaders[0].get('inputs', {}).get('ckpt_name') != STANDARD:
        raise RuntimeError('Expected exactly one standard SD1.5 checkpoint loader')
    loaders[0]['inputs']['ckpt_name'] = path.name
    return result
