"""Bounded scalar phase timings: no model imports, samples, identifiers or files."""
from contextlib import contextmanager
import json
import sys
import time


class PhaseTimings:
    def __init__(self, clock=None):
        self.clock=clock or time.perf_counter
        self.seconds={}

    @contextmanager
    def phase(self, name):
        if name not in self.seconds and len(self.seconds)>=32:
            raise ValueError('Too many timing phases')
        start=self.clock()
        try:
            yield
        finally:
            self.seconds[name]=self.seconds.get(name,0.0)+max(0.0,self.clock()-start)

    def snapshot(self):
        return {name:round(value,6) for name,value in self.seconds.items()}

    def emit(self):
        # Timing output must never replace a successful result or suppress a
        # lifecycle failure. stderr is already captured by the owned worker.
        try:
            print('PORTALAI_MEDIA_TIMING '+json.dumps({'version':1,'seconds':self.snapshot()},
                  separators=(',',':')),file=sys.stderr,flush=True)
        except Exception:
            pass
