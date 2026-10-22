"""Optional Windows WDDM counters via PDH, across NVIDIA/AMD/Intel drivers.

GPU percent is the busiest engine for a process (not additive across engines).
Dedicated/shared memory can include allocations shared between processes.
Unavailable counters stay absent; no dependencies, elevation or driver changes.
"""
import ctypes as c
from ctypes import wintypes as w
import math
import re


def summarize(engines, dedicated, shared):
    processes = {}; totals = {}
    for name, value in engines:
        hit = re.match(r'pid_(\d+)_(.+)', name)
        if not hit or not math.isfinite(value) or value < 0: continue
        pid, engine = hit.groups()
        row = processes.setdefault(pid,{})
        row['gpu'] = max(row.get('gpu',0), min(100,value))
        totals[engine] = totals.get(engine,0) + value
    for rows, key in ((dedicated,'dedicated'), (shared,'shared')):
        for name, value in rows:
            hit = re.match(r'pid_(\d+)_',name)
            if not hit or not math.isfinite(value) or value < 0: continue
            row = processes.setdefault(hit[1],{})
            row[key] = row.get(key,0) + value/1024**3
    return {'processes':processes, 'gpu':min(100,max(totals.values())) if totals else None}


class WindowsGPUCounters:
    def __init__(self):
        self.lib = c.WinDLL('pdh'); self.query = w.HANDLE(); self.counters = []
        self.lib.PdhOpenQueryW.argtypes = [w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
        self.lib.PdhOpenQueryW.restype = w.DWORD
        self.lib.PdhAddEnglishCounterW.argtypes = [w.HANDLE,w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
        self.lib.PdhAddEnglishCounterW.restype = w.DWORD
        self.lib.PdhCollectQueryData.argtypes = [w.HANDLE]; self.lib.PdhCollectQueryData.restype = w.DWORD
        self.lib.PdhCloseQuery.argtypes = [w.HANDLE]
        self.lib.PdhGetFormattedCounterArrayW.argtypes = [w.HANDLE,w.DWORD,c.POINTER(w.DWORD),c.POINTER(w.DWORD),c.c_void_p]
        self.lib.PdhGetFormattedCounterArrayW.restype = w.DWORD
        if self.lib.PdhOpenQueryW(None,0,c.byref(self.query)): raise OSError('PDH unavailable')
        try:
            for path in (r'\GPU Engine(*)\Utilization Percentage',r'\GPU Process Memory(*)\Dedicated Usage',r'\GPU Process Memory(*)\Shared Usage'):
                counter = w.HANDLE()
                code = self.lib.PdhAddEnglishCounterW(self.query,path,0,c.byref(counter))
                self.counters.append(None if code else counter)
        except BaseException: self.close(); raise

    def _values(self, handle):
        if handle is None: return []
        class VALUE(c.Structure):
            _fields_ = [('status',w.DWORD),('value',c.c_double)]
        class ITEM(c.Structure):
            _fields_ = [('name',w.LPWSTR),('value',VALUE)]
        size, count = w.DWORD(), w.DWORD()
        code = self.lib.PdhGetFormattedCounterArrayW(handle,0x200,c.byref(size),c.byref(count),None)
        if code not in (0,0x800007D2) or not 0 < size.value <= 8*1024**2: return []
        buffer = c.create_string_buffer(size.value)
        if self.lib.PdhGetFormattedCounterArrayW(handle,0x200,c.byref(size),c.byref(count),buffer): return []
        if count.value*c.sizeof(ITEM) > len(buffer): return []
        items = c.cast(buffer,c.POINTER(ITEM))
        return [(items[i].name,items[i].value.value) for i in range(count.value) if items[i].value.status in (0,1)]

    def sample(self):
        if not self.query or self.lib.PdhCollectQueryData(self.query): return {'processes':{},'gpu':None}
        return summarize(*(self._values(counter) for counter in self.counters))

    def close(self):
        if self.query:
            self.lib.PdhCloseQuery(self.query); self.query = None
