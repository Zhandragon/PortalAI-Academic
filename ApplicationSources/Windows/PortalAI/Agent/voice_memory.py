"""Bounded voice admission with the existing owned-model lease and recovery."""
import time
from pathlib import Path

GIB = 1024 ** 3


class VoiceMemoryError(RuntimeError):
    """Only a pre-inference RAM rejection may enter the voice handoff fallback."""
    def __init__(self, stage, model, required, available):
        self.stage, self.model = str(stage), str(model)
        self.required, self.available = int(required), int(available)
        super().__init__(f'{self.stage} ({self.model}) needs {self.required/GIB:g} GiB available RAM '
                         f'including its safety reserve; {self.available/GIB:.2f} GiB is available. '
                         'Close another memory-heavy app or use a smaller chat model if releasing Nice is not enough.')

    def payload(self):
        return {'success': False, 'error': str(self), 'error_code': 'voice_memory_admission',
                'phase': 'admission', 'stage': self.stage, 'model': self.model,
                'required_bytes': self.required, 'available_bytes': self.available}

    @classmethod
    def from_payload(cls, data):
        if not isinstance(data, dict) or data.get('success') is not False:
            return None
        if data.get('error_code') != 'voice_memory_admission' or data.get('phase') != 'admission':
            return None
        required, available = data.get('required_bytes'), data.get('available_bytes')
        if (type(required) is not int or type(available) is not int or not 0 <= available < required
                or not isinstance(data.get('stage'), str) or not isinstance(data.get('model'), str)
                or data.get('files')):
            return None
        return cls(data['stage'], data['model'], required, available)


def run_voice_stage(root, stage, admit, operation, *, check, handoff_check=None, notify=None, require_handoff=False):
    """Keep Nice resident when possible; retry only typed pre-inference rejection.

    A successful operation, playback error, OOM or unknown worker outcome is never
    replayed. Recovery uses the original request's account/Stop fence. The caller
    owns cancellation and supplies operations whose typed rejection precedes effects.
    """
    from workload_request import request_guard
    import service_manager as service
    root = Path(root).resolve()
    if root != service.root_dir().resolve():
        raise ValueError('Voice handoff must use this portable installation')
    original = request_guard(root)
    notify = notify or (lambda phase, text: None)

    def guard():
        check()
        original()

    def guarded_handoff():
        guard()
        if handoff_check is not None:
            handoff_check()

    guard()
    if not require_handoff:
        try:
            admit()
            guard()
            result = operation(guard)
            guard()
            return result
        except VoiceMemoryError:
            pass
    # Serialize with model preparation and media workers. Short waits preserve
    # cancellation; a low-memory microphone request never waits indefinitely.
    lease = state = None
    restored = None
    deadline = time.monotonic() + 60
    notify('waiting', 'Waiting for voice memory…')
    try:
        while lease is None:
            guarded_handoff()
            if time.monotonic() >= deadline:
                raise TimeoutError('Voice is waiting for another model task. Stop that task or try again when it finishes.')
            try:
                lease = service.acquire_gpu_lease('voice-' + stage, timeout=.3)
            except TimeoutError:
                pass
        guarded_handoff()
        notify('waiting', 'Releasing Nice for ' + stage + '…')
        state = service.qwen_gpu_handoff_begin('voice-' + stage + '-memory', start_guard=guarded_handoff)
        guarded_handoff()
        # An absent/foreign model never grants process ownership. Fresh admission
        # still applies if another app happened to release memory while waiting.
        admit()  # Fresh memory, unchanged reserves, same requested speech model.
        guarded_handoff()
        result = operation(guarded_handoff)
    finally:
        try:
            if state and state.get('active'):
                notify('restoring', 'Restoring Nice…')
                restored = service.qwen_gpu_handoff_end(state)
                # Explicit Stop/newer generations intentionally suppress restart.
                # Never claim a completed handoff merely because a port opened.
                if not restored.get('ready') and not restored.get('stale_generation'):
                    raise RuntimeError('Nice did not confirm readiness after the voice task.')
        finally:
            if lease is not None:
                service.release_gpu_lease(lease)
    guard()
    if restored and restored.get('stale_generation'):
        raise RuntimeError('Voice recovery was cancelled by a newer model operation.')
    return result
