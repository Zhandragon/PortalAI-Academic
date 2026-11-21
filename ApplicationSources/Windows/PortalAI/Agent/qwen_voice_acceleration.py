"""Optional CUDA graph for Qwen's fixed fifteen residual codec predictions.

Only the installed single-speaker, default-sampling predictor call is accelerated.
The main talker, voice, weights and sampling parameters remain unchanged. Other
calls/backends use the package implementation. Graphs live only in this worker.
"""
from contextlib import contextmanager
from types import SimpleNamespace


@contextmanager
def accelerate(model):
    import torch
    predictor = model.model.talker.code_predictor
    original = predictor.generate
    graph = static_input = static_output = graph_inputs = None
    unavailable = False
    statistics = {'replays': 0, 'fallback': None}

    def generate(*args, **kwargs):
        nonlocal graph, static_input, static_output, graph_inputs, unavailable
        values = kwargs.get('inputs_embeds')
        expected = {'inputs_embeds', 'max_new_tokens', 'do_sample', 'top_p', 'top_k',
                    'temperature', 'output_hidden_states', 'return_dict_in_generate'}
        supported = (not args and set(kwargs) == expected and values is not None
                     and values.is_cuda and not torch.version.hip and values.shape[:2] == (1, 2)
                     and kwargs['max_new_tokens'] == 15 and kwargs['do_sample'] is True
                     and kwargs['top_p'] == 1.0 and kwargs['top_k'] == 50
                     and kwargs['temperature'] == .9 and kwargs['return_dict_in_generate'] is True
                     and predictor.config.num_code_groups == 16
                     and predictor.config.num_hidden_layers == 5
                     and not predictor.model.has_sliding_layers
                     and predictor.generation_config.eos_token_id is None
                     and predictor.generation_config.repetition_penalty == 1.0
                     and predictor.generation_config.num_beams == 1
                     and predictor.generation_config.typical_p == 1.0
                     and not predictor.generation_config.suppress_tokens
                     and not predictor.generation_config.bad_words_ids)
        if unavailable or not supported:
            return original(*args, **kwargs)
        if graph is None:
            try:
                from transformers.cache_utils import DynamicCache
                static_input = values.clone()
                positions = [torch.arange(2, device=values.device)] + [
                    torch.tensor([i + 1], device=values.device) for i in range(1, 15)]
                first_mask = torch.zeros((1, 1, 2, 2), device=values.device, dtype=values.dtype)
                first_mask[..., 0, 1] = torch.finfo(values.dtype).min
                masks = [first_mask] + [torch.zeros((1, 1, 1, i + 2), device=values.device,
                                                   dtype=values.dtype) for i in range(1, 15)]
                # Graphs retain addresses, not Python references to input tensors.
                # Keep these alive for every replay, alongside the static prompt.
                graph_inputs = (positions, masks)

                def predict():
                    cache = DynamicCache()
                    token = None
                    tokens = []
                    for i in range(15):
                        result = predictor(inputs_embeds=static_input if i == 0 else None,
                                           input_ids=token, past_key_values=cache,
                                           attention_mask={'full_attention': masks[i]},
                                           position_ids=positions[i].unsqueeze(0), cache_position=positions[i],
                                           generation_steps=i, use_cache=True, output_hidden_states=False,
                                           return_dict=True)
                        scores = result.logits[:, -1, :].float() / .9
                        scores = scores.masked_fill(scores < torch.topk(scores, 50)[0][..., -1, None], -float('inf'))
                        token = torch.multinomial(torch.softmax(scores, dim=-1), 1)
                        tokens.append(token)
                    return torch.cat(tokens, dim=-1)

                # Warm-up/capture use a private RNG scope and never produce speech.
                with torch.random.fork_rng(devices=[values.device.index or 0]), torch.inference_mode():
                    stream = torch.cuda.Stream(device=values.device)
                    stream.wait_stream(torch.cuda.current_stream(values.device))
                    with torch.cuda.stream(stream):
                        for _ in range(2):
                            predict()
                    torch.cuda.current_stream(values.device).wait_stream(stream)
                    torch.cuda.synchronize(values.device)
                    candidate = torch.cuda.CUDAGraph()
                    with torch.cuda.graph(candidate):
                        static_output = predict()
                    graph = candidate
            except (RuntimeError, TypeError, AttributeError, ValueError) as exc:
                # Optimization failure precedes inference; do not retry emitted audio.
                unavailable = True
                statistics['fallback'] = type(exc).__name__
                graph = static_input = static_output = graph_inputs = None
                return original(*args, **kwargs)
        static_input.copy_(values)
        graph.replay()
        statistics['replays'] += 1
        return SimpleNamespace(sequences=static_output.clone())

    predictor.generate = generate
    try:
        yield statistics
    finally:
        predictor.generate = original
