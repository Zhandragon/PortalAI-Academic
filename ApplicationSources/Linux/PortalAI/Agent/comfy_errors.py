"""Bounded ComfyUI failure evidence; no recovery actions or hardware guesses."""
from __future__ import annotations


def _text(value, limit, fallback=''):
    if not isinstance(value, (str, int, float)):
        return fallback
    value = str(value).strip()
    return value[:limit] + (' ...[truncated]' if len(value) > limit else '')


class ComfyExecutionError(RuntimeError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def execution_failure(prompt_id, status):
    """Select only error metadata, never workflow inputs, tensors or prompts."""
    payload = {}
    messages = status.get('messages') or []
    for item in reversed(messages):
        if (isinstance(item, (list, tuple)) and len(item) >= 2
                and item[0] == 'execution_error' and isinstance(item[1], dict)):
            payload = item[1]
            break
    node = _text(payload.get('node_id', payload.get('node')), 96, '?')
    kind = _text(payload.get('node_type', payload.get('class_type')), 128, '?')
    error_type = _text(payload.get('exception_type'), 96, 'ExecutionError')
    message = _text(payload.get('exception_message') or payload.get('message'), 1800,
                    'ComfyUI returned no execution_error details')
    category = 'comfy_execution'
    explanation = ''
    if message.casefold() in {'hostbuf_file_reader_read failed', 'hostbuffer.read_file_slice failed'}:
        category = 'model_weight_transfer'
        explanation = (
            ' Model tensor/host-buffer transfer failed; this is not the input-image decoder. '
            'The underlying cause is unconfirmed: memory/resources, driver/runtime or model-file I/O '
            'need evidence. This error does not justify changing the image or its path separators. '
            'Preserve completed stages; do not automatically replay the job.')
    trace = payload.get('traceback') or []
    if isinstance(trace, str):
        trace = trace.splitlines()
    if not isinstance(trace, (list, tuple)):
        trace = []
    diagnostic = {
        'backend': 'ComfyUI', 'error_category': category,
        'prompt_id': _text(prompt_id, 128), 'node_id': node, 'node_type': kind,
        'exception_type': error_type,
        'traceback': [_text(line, 400) for line in trace[-12:] if isinstance(line, str)],
        'traceback_complete': len(trace) <= 12 and all(isinstance(line, str) and len(line.strip()) <= 400 for line in trace),
        'automatic_retry': False,
    }
    prefix = ('ComfyUI model-weight transfer failed (not image decoding)'
              if category == 'model_weight_transfer' else 'ComfyUI job failed')
    return ComfyExecutionError(f'{prefix}: node {node} ({kind}) {error_type}: {message}' + explanation,
                               diagnostic)


def tool_failure(command, error):
    result = {'success': False, 'tool': command, 'error': str(error)}
    if isinstance(error, ComfyExecutionError):
        result['diagnostics'] = error.diagnostics
    return result
