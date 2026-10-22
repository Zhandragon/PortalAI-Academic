"""Read-only host/self-process telemetry check; starts no compute workload."""
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent')]


def rows():
    from activity_monitor import Sampler
    from runtime_activity import process_stats
    sampler = Sampler()
    try:
        sampler.sample(); time.sleep(1); data = sampler.sample()
        result = []
        for key in ('cpu','ram','gpu','vram'):
            value = data.get(key)
            available = isinstance(value,(int,float)) and math.isfinite(value) and 0 <= value <= 100
            result.append({'status':'PASS' if available else 'WARN', 'label':'Live '+key.upper()+' counter',
                           'detail':f'{value:.1f}% observed; read-only counters, no inference test.' if available else
                                    'Counter unavailable on this host/driver; no activity value inferred.'})
        try:
            own = process_stats(os.getpid())
            ok = bool(own['identity']) and own['ram'] is not None
            result.append({'status':'PASS' if ok else 'WARN','label':'Live self-process counters',
                           'detail':'Current bundled interpreter identity/CPU time/resident memory observed; no other process arguments recorded.' if ok else 'Self-process counters incomplete.'})
        except OSError as exc:
            result.append({'status':'WARN','label':'Live self-process counters','detail':str(exc)})
        result.append({'status':'PASS' if data.get('process_counters') else 'WARN','label':'Live per-process GPU counter availability',
                       'detail': 'Driver exposed process GPU/memory counters; no model attribution or inference validation.' if data.get('process_counters') else
                                 'Per-process GPU counters unavailable in this sample; GUI shows n/a.'})
        return result
    finally:
        sampler.close()
