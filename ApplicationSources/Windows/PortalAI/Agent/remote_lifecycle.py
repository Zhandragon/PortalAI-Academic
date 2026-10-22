"""Public, key-free lifecycle fences for the optional Home Assistant bridge."""
from pathlib import Path
import json
import os
import uuid


def is_bridge(root, row):
    """Exempt only the exact bundled bridge invocation, never a name substring."""
    root = Path(root).resolve()
    try:
        executable = Path(row.get('executable') or '').resolve()
        return executable in {root/'Runtime/BootstrapPython/python.exe', root/'Runtime/BootstrapPython/pythonw.exe'} and row.get('argv') == [str(executable), '-B', '-I', str(root/'HomeAssistant/portalai_bridge.py')]
    except (OSError, ValueError, TypeError):
        return False


def stop_epoch(root):
    from runtime_policy import portable_path
    path = portable_path(Path(root).resolve(), 'HomeAssistant/state/forced-stop.json')
    if not path.exists():
        return 'initial'
    if path.stat().st_size > 4096:
        raise ValueError('Invalid remote Stop fence')
    value = json.loads(path.read_text(encoding='utf-8'))['epoch']
    if not isinstance(value, str) or uuid.UUID(hex=value).hex != value:
        raise ValueError('Invalid remote Stop epoch')
    return value


def force_fence(root):
    from runtime_policy import atomic_json, portable_path
    path = portable_path(Path(root).resolve(), 'HomeAssistant/state/forced-stop.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {'epoch': uuid.uuid4().hex, 'reason': 'Explicit unsafe remote shutdown'})
    stop_epoch(root)  # Read back before terminating any process.


def clean_environment():
    # The management process and a fresh login must never inherit profile keys
    # or an old profile epoch from a launching controller.
    return {k:v for k,v in os.environ.items() if not k.startswith('PORTALAI_')}
