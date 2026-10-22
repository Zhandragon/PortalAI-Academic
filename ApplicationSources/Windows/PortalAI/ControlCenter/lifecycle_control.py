"""Serialize helper creation with Stop without blocking Tk during model loading."""
import threading
import json
from pathlib import Path


def startup_result(root, completed, requested_at):
    """Only this invocation can report readiness; a previous success is not evidence."""
    try:
        state = json.loads(completed.stdout or '')
    except (ValueError, TypeError):
        try:
            state = json.loads((Path(root)/'Agent/.runtime/native_startup_state.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):state = None
    current = isinstance(state, dict) and state.get('started_at') == requested_at
    ok = completed.returncode == 0 and current and bool(state.get('success'))
    if ok:
        qwen = state.get('qwen') or {}
        model = qwen.get('model') or {}
        name = model.get('label') or model.get('id') or qwen.get('profile', 'unknown')
        detail = f"Qwen READY on :{qwen.get('port',8080)} · {name}."
    else:
        detail = str(state.get('error') or '') if current else ''
        if not detail:detail = (completed.stderr or '').strip()[-12000:]
        if not detail:detail = 'Startup did not confirm the requested model. Check the Control Log.'
    return {'ok': bool(ok), 'detail': detail, 'returncode': int(completed.returncode),
            'model': model if ok else None}


class StartupGate:
    def __init__(self):
        self.lock=threading.Lock();self.generation=0

    def ticket(self):
        with self.lock:return self.generation

    def cancel(self):
        with self.lock:self.generation+=1

    def launch(self,ticket,create_process):
        with self.lock:
            if ticket!=self.generation:raise RuntimeError('Startup cancelled by Stop/Exit')
            return create_process()
