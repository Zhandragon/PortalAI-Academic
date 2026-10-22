"""Image-only companion selection; never persist a temporary model choice."""
import runtime_policy as runtime

MODES = ('automatic', 'off')
VISION_MODELS = {
    'standard': {'small': 'qwen-vl2-q4', 'balanced': 'qwen-vl4-q4'},
    'uncensored': {'small': 'qwen-vl2-abliterated-q4', 'balanced': 'qwen-vl4-abliterated-q4'},
}


def candidates(level, policy):
    """Preserve an explicit vision model and the saved Standard/Uncensored choice."""
    from academic_policy import enforce_policy
    policy = enforce_policy(policy)
    from chat_selection import selected_variant
    selection = policy.get('selection', 'auto')
    models = {m['id']: m for m in policy.get('models', [])}
    current = models.get(selection)
    if current and current.get('projector'):
        return (selection,)
    if selection != 'auto' and current is None:
        raise RuntimeError('The saved chat model is not configured. Choose an installed model in Settings.')
    if policy.get('vision_routing', 'off') != 'automatic':
        raise RuntimeError('This chat contains an image. Enable Automatic image vision in Settings, '
                           'or select a vision-capable model. Your attachments remain saved.')
    variant = selected_variant(policy)
    pair = VISION_MODELS[variant]
    choices = (pair['small'],) if level == 'fast' else (pair['balanced'], pair['small'])
    if level == 'deep' and selection == 'auto':
        large = ('qwen27-standard-q4',) if variant == 'standard' else ('qwen27-q4', 'qwen27-q5')
        choices = large + choices
    return tuple(name for name in choices if name in models and models[name].get('projector')
                 and runtime.model_variant(models[name]) == variant)


def select(level, root, hardware, backend, policy):
    """Use existing free-memory admission after owned unload; no downloads or replay."""
    from academic_policy import enforce_policy
    policy = enforce_policy(policy)
    names = candidates(level, policy)
    requested = int(policy.get('context_tokens', 8192))
    if not 512 <= requested <= 32768:
        raise ValueError('context_tokens must be between 512 and 32768')
    explicit = policy.get('selection') in names
    failures = []
    for name in names:
        model = next(m for m in policy['models'] if m['id'] == name)
        context = min(requested, int(model.get('max_context_tokens', 32768)))
        contexts = [context] if explicit else [context] + [n for n in (4096, 2048) if n < context]
        for limit in contexts:
            try:
                selected = runtime.select_model(root, hardware, backend,
                    {**policy, 'selection': name, 'context_tokens': limit})['selected']
                selected['vision_reason'] = ('Selected vision model' if explicit else
                    'Automatic image vision; saved text model unchanged')
                return selected
            except RuntimeError as exc:
                failures.append(str(exc))
    raise RuntimeError('No installed matching vision model fits the available RAM/VRAM and reserves. '
                       'The text model and attachments were preserved. ' +
                       (failures[-1] if failures else 'Install a matching Standard vision model using the Academic installer; alternate models are unavailable.'))
