"""Training-free masked flow matching and exact localized PCM composition.

MMAudio's local flow_matching.py uses x_t=(1-t)*noise+t*data (min_sigma=0).
Project observed context onto that path before EVERY Euler evaluation and once
at t=1. This is experimental posterior conditioning, not an inpaint-trained model.
"""
import math


def masked_euler(flow, noise, source, keep, steps):
    if type(steps) is not int or not 1 <= steps <= 50:
        raise ValueError('Inpainting steps must be 1..50')
    if noise.shape != source.shape or keep.shape != source.shape:
        raise ValueError('Inpainting tensor shapes differ')
    x = noise * 1
    for index in range(steps):
        t = index / steps
        observed = (1 - t) * noise + t * source
        x = keep * observed + (1 - keep) * x
        x = x + flow(t, x) / steps
    return keep * source + (1 - keep) * x


def mask_span(start, end, sample_rate, latent_hop, length, expand=8):
    if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
        raise ValueError('Invalid inpainting interval')
    if type(expand) is not int or not 0 <= expand <= 32:
        raise ValueError('Latent mask expansion must be 0..32')
    left = max(0, math.floor(start * sample_rate / latent_hop) - expand)
    right = min(length, math.ceil(end * sample_rate / latent_hop) + expand)
    if left >= right or (left == 0 and right == length):
        raise ValueError('Inpainting needs observed audio context outside the expanded interval')
    return left, right


def blend_region(original, generated, fade_frames):
    """Only the selected PCM region is blended; caller copies all other bytes."""
    import numpy as np
    if original.shape != generated.shape or original.ndim != 2:
        raise ValueError('Generated region has unexpected channels or sample count')
    if not np.isfinite(generated).all():
        raise ValueError('Generated audio contains non-finite samples')
    count = len(original)
    fade = min(max(0, int(fade_frames)), count // 4)
    generated = generated.astype(np.float64)
    if fade:
        weights = np.linspace(0, 1, fade, endpoint=True)[:, None]
        generated[:fade] = original[:fade] * (1-weights) + generated[:fade] * weights
        generated[-fade:] = original[-fade:] * weights + generated[-fade:] * (1-weights)
    return np.clip(np.rint(generated), -32768, 32767).astype('<i2')
