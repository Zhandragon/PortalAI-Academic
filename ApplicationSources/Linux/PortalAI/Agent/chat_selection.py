"""Shared size/variant mapping for the chat slider and model Settings."""
from pathlib import Path
import runtime_policy as runtime

TIERS = {
    'fast': {'standard': ('qwen1.7-q8',), 'uncensored': ('qwen1.7-abliterated-q8',)},
    'balanced': {'standard': ('qwen4-q4',), 'uncensored': ('qwen4-abliterated-q4',)},
    'deep': {'standard': ('qwen27-standard-q4',), 'uncensored': ('qwen27-q4', 'qwen27-q5')},
}


def tier_for_model(selection):
    return next((tier for tier, variants in TIERS.items()
                 if any(selection in ids for ids in variants.values())), None)


def selected_variant(policy):
    return 'standard'


def choice_changes(root, policy, *, level=None, uncensored=None, selection=None):
    """Select a cataloged installed counterpart; never silently change size/variant."""
    from academic_policy import enforce_policy, standard_selection
    policy = enforce_policy(policy)
    uncensored = False
    if selection is not None: selection = standard_selection(selection)
    current = policy.get('selection', 'auto')
    variant = selected_variant(policy) if uncensored is None else ('uncensored' if uncensored else 'standard')
    models = {m['id']: m for m in policy.get('models', [])}
    if selection is not None:
        if selection == 'auto': return {'selection': 'auto', 'variant_preference': variant}
        if selection not in models: raise ValueError('The selected chat model is not configured.')
        candidates = (selection,)
        variant = runtime.model_variant(models[selection])
    else:
        if level is None and current == 'auto':
            return {'selection': 'auto', 'variant_preference': variant}
        level = level or tier_for_model(current)
        if level not in TIERS: raise ValueError('Choose a supported chat size before changing its variant.')
        candidates = TIERS[level][variant]
        if current in candidates: candidates = (current,) + tuple(m for m in candidates if m != current)
    for model_id in candidates:
        model = models.get(model_id)
        if model is None: continue
        paths = [model['path']] + ([model['projector']] if model.get('projector') else [])
        if all(runtime.portable_path(Path(root), path).is_file() for path in paths):
            return {'selection': model_id, 'variant_preference': variant}
    raise ValueError('The requested chat size/variant is not installed (including any required vision projector).')
