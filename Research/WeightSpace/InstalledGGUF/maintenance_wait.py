"""A bounded inter-model validation slot; never interrupt an experiment pass."""
import json,os,time
from pathlib import Path
LAB=Path(__file__).resolve().parent
def wait_if_requested(model):
    request=LAB/'MAINTENANCE-SLOT.json'
    if not request.exists():return
    from experiment import atomic_json
    from research_guard import require_gpu_unpaused
    marker=json.loads(request.read_text());deadline=time.monotonic()+1800
    atomic_json(LAB/'MAINTENANCE-READY.json',{'nonce':marker['nonce'],'waiting_before_model':model,'pid':os.getpid()})
    while request.exists():
        require_gpu_unpaused(LAB)
        if time.monotonic()>deadline:raise TimeoutError('Inter-model validation slot needs review')
        time.sleep(.5)
