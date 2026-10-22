"""MuseTalk's relocatable Python 3.10 + existing cp310 package layer."""
from pathlib import Path
import importlib
import json
import os
import subprocess
import sys

PYTHON = 'Runtimes/Python310/cpython-3.10.21-windows-x86_64-none/python.exe'
PACKAGES = 'Video/MuseTalk/.venv/Lib/site-packages'
MODULES = ('torch', 'torchvision', 'cv2', 'mmcv.ops', 'mmpose',
           'diffusers', 'transformers', 'librosa', 'omegaconf', 'musetalk.utils.face_detection')


def resolve(root):
    root = Path(root).resolve()
    py, packages = root / PYTHON, root / PACKAGES
    if not py.is_file() or not (packages / 'torch/__init__.py').is_file():
        raise FileNotFoundError('MuseTalk requires bundled Python 3.10 and its local package layer')
    return py, packages


def environment(root):
    root = Path(root).resolve()
    py, _ = resolve(root)
    import sys
    sys.path.insert(0, str(root/'Agent'))
    from runtime_policy import portable_env
    from profile_paths import private_path
    env = portable_env(root)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', '__PYVENV_LAUNCHER__'):
        env.pop(key, None)
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8:backslashreplace',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1')
    for key, rel in {'TEMP':'Cache/tmp', 'TMP':'Cache/tmp', 'TMPDIR':'Cache/tmp',
                     'HF_HOME':'Cache/HuggingFace', 'TORCH_HOME':'Cache/torch',
                     'NUMBA_CACHE_DIR':'Cache/numba', 'MPLCONFIGDIR':'Cache/matplotlib'}.items():
        folder = private_path(root, rel) if key in ('TEMP', 'TMP', 'TMPDIR') else root / rel
        folder.mkdir(parents=True, exist_ok=True)
        env[key] = str(folder)
    env['PATH'] = os.pathsep.join((str(root/'Tools/ffmpeg/bin'), str(py.parent), env.get('PATH', '')))
    return env


def activate(root):
    if sys.version_info[:2] != (3, 10):
        raise RuntimeError('MuseTalk packages require bundled Python 3.10; refusing another ABI')
    root = Path(root).resolve()
    _, packages = resolve(root)
    sys.path[:0] = [str(packages), str(root/'Video/MuseTalk')]


def probe(root, timeout=90):
    root = Path(root).resolve()
    py, _ = resolve(root)
    cp = subprocess.run([str(py), '-B', '-I', '-X', 'utf8', str(root/'Agent/musetalk_runtime.py'), '--probe'],
                        cwd=root, env=environment(root), capture_output=True, text=True,
                        encoding='utf-8', errors='replace', timeout=timeout,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    detail = (cp.stdout + '\n' + cp.stderr).strip()
    return {'ok': cp.returncode == 0, 'returncode': cp.returncode, 'detail': detail}


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    activate(root)
    rows = []
    for name in MODULES:
        try:
            module = importlib.import_module(name)
            origin = Path(module.__file__).resolve()
            rows.append({'module': name, 'origin': str(origin), 'ok': origin.is_relative_to(root)})
        except Exception as exc:
            rows.append({'module': name, 'ok': False, 'error': str(exc)})
    print(json.dumps({'interpreter': sys.executable, 'python': sys.version.split()[0], 'rows': rows}))
    raise SystemExit(0 if all(row['ok'] for row in rows) else 1)
