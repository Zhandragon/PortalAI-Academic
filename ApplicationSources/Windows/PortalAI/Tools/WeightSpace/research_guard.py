"""Manual, portable GPU pause for this experiment; no production policy changes.

Create GPU-PAUSED.json in this directory to block experiment starts. The file's
contents do not grant permission to resume: even malformed or empty markers
pause work. Resume requires explicitly removing the marker after the user says
resources are available. Native in-flight requests finish before the next check.
"""
import hashlib
from pathlib import Path

LAB = Path(__file__).resolve().parent


class ResearchPaused(RuntimeError):
    pass


def gpu_paused(lab=None):
    return (Path(lab) if lab is not None else LAB).joinpath('GPU-PAUSED.json').exists()


def require_gpu_unpaused(lab=None):
    if gpu_paused(lab):
        raise ResearchPaused('GPU research is paused by GPU-PAUSED.json; no automatic resume.')


def model_digest(path):
    """Interrupt long read-only model hashing at a bounded chunk boundary."""
    require_gpu_unpaused()
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            require_gpu_unpaused()
            chunk = stream.read(8 * 1024**2)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
