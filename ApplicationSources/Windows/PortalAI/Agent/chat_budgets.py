"""Inference-only effort budgets; never admit or reload a model.

The context passed here must come from an already admitted model. Output tokens
include reasoning and the visible answer, not just the visible answer.
"""
from __future__ import annotations


def generation_options(profile, context_tokens):
    if profile not in ('fast', 'balanced', 'deep'):
        raise ValueError('Unknown chat effort')
    context = int(context_tokens)
    if not 512 <= context <= 32768:
        raise ValueError('Invalid admitted context size')
    target = {'fast': 1024, 'balanced': 4096, 'deep': 8192}[profile]
    if profile == 'balanced' and context <= 8192:
        target = 2048
    template = {'enable_thinking': profile != 'fast'}
    if profile != 'fast':
        # The deployed 27B template defaults to xhigh if omitted. The smaller
        # Qwen3 template ignores this key but honors enable_thinking.
        template['reasoning_effort'] = 'low' if profile == 'balanced' else 'xhigh'
    return {'max_tokens': min(target, context // 2), 'chat_template_kwargs': template}


def response_limits(settings, output_tokens, *, profile=None, slow=False, image=False):
    """Bounded waits scale with generation allowance, never network/tool waits."""
    idle = max(30, min(1800, float(settings.get('model_idle_timeout_seconds', 180))))
    configured = max(idle, min(1800, float(settings.get('model_response_timeout_seconds', 600))))
    if image:
        configured = max(idle, min(configured, float(settings.get('image_response_timeout_seconds', 240))))
    if profile is not None:
        # Advisory timing, not a performance promise. Useful deltas still reset
        # only the idle deadline; the per-response wall-clock cap remains finite.
        rate = 4 if slow else 12
        configured = max(configured, min(1800, 120 + int(output_tokens) / rate))
    if slow or profile == 'deep':
        idle = max(idle, 300)
        configured = max(configured, 600)
    return idle, min(1800, max(idle, configured))
