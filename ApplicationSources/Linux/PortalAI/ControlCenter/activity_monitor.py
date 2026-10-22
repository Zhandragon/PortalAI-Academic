"""Read-only host telemetry and bounded Tk charts; no model or GPU compute probes."""
from collections import deque
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import time
import tkinter as tk


def cpu_times():
    if os.name == 'nt':
        idle, kernel, user = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise OSError('CPU counters unavailable')
        return kernel.value + user.value, idle.value
    values = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def cpu_percent(previous, current):
    if previous is None: return None
    total, idle = current[0]-previous[0], current[1]-previous[1]
    if total <= 0 or idle < 0: return None
    return max(0., min(100., 100*(total-idle)/total))


class Sampler:
    def __init__(self):
        self.previous = None; self.last_gpu = -float('inf'); self.gpu = {}
        self.windows = None; self.windows_attempted = False

    def sample_gpu(self):
        # One adapter, explicitly named. Never invent usage for unsupported drivers.
        command = shutil.which('nvidia-smi')
        if command:
            try:
                proc = subprocess.run([command, '--query-gpu=name,memory.used,memory.total,utilization.gpu',
                    '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=1.8,
                    creationflags=0x08000000 if os.name == 'nt' else 0)
                name, used, total, busy = [x.strip() for x in proc.stdout.splitlines()[0].rsplit(',', 3)]
                used, total = float(used)/1024, float(total)/1024
                processes = {}
                try:
                    running = subprocess.run([command, '--query-compute-apps=pid,used_gpu_memory',
                        '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=1.8,
                        creationflags=0x08000000 if os.name == 'nt' else 0)
                    for line in running.stdout.splitlines():
                        try:
                            pid, memory = line.split(','); processes[str(int(pid))] = float(memory)/1024
                        except ValueError: continue  # WDDM often reports N/A.
                except (OSError, subprocess.SubprocessError): pass
                return {'gpu': float(busy), 'vram': 100*used/total if total else None,
                        'vram_used':used, 'vram_total':total, 'adapter':name, 'gpu_processes':processes}
            except (OSError, ValueError, IndexError, subprocess.SubprocessError): pass
        if os.name != 'nt':
            for device in sorted(Path('/sys/class/drm').glob('card[0-9]*/device')):
                try:
                    busy = float((device/'gpu_busy_percent').read_text())
                    used = int((device/'mem_info_vram_used').read_text())/1024**3
                    total = int((device/'mem_info_vram_total').read_text())/1024**3
                    return {'gpu':busy, 'vram':100*used/total if total else None,
                            'vram_used':used, 'vram_total':total, 'adapter':device.parent.name+' (DRM)'}
                except (OSError, ValueError): continue
        return {'gpu':None, 'vram':None, 'adapter':'GPU counters unavailable on this driver'}

    def sample(self):
        from runtime_policy import memory_info
        result = {'cpu':None, 'ram':None}
        try:
            current = cpu_times(); result['cpu'] = cpu_percent(self.previous, current); self.previous = current
        except (OSError, ValueError): self.previous = None
        try:
            total, available = memory_info()
            if total: result.update(ram=100*(total-available)/total, ram_used=(total-available)/1024**3, ram_total=total/1024**3)
        except (OSError, ValueError): pass
        if time.monotonic()-self.last_gpu >= 15:
            self.gpu = self.sample_gpu(); self.last_gpu = time.monotonic()
        process_counters = {}
        if os.name == 'nt':
            if not self.windows_attempted:
                self.windows_attempted = True
                try:
                    from windows_gpu_counters import WindowsGPUCounters
                    self.windows = WindowsGPUCounters()
                except (OSError, AttributeError): pass
            if self.windows is not None:
                counters = self.windows.sample(); process_counters = counters['processes']
                if self.gpu.get('gpu') is None and counters['gpu'] is not None:
                    result.update(gpu=counters['gpu'], adapter='Windows WDDM · busiest GPU engine')
        merged = {**self.gpu, **result}
        # CPU/RAM result has no GPU key unless WDDM supplied a fallback.
        return {**merged, 'process_counters':process_counters, 'at':time.monotonic()}

    def close(self):
        if self.windows is not None: self.windows.close(); self.windows = None


class ActivityCharts(tk.Frame):
    def __init__(self, parent, palette):
        super().__init__(parent, bd=0)
        self.palette = palette; self.samples = deque(maxlen=60); self.labels = {}; self.canvases = {}
        self.cells = []; self.borders=[]
        from ornate_ui import ConnectedBorder
        for key, title in (('cpu','CPU'), ('ram','RAM'), ('gpu','GPU'), ('vram','VRAM')):
            cell = tk.Frame(self, bd=0); self.cells.append(cell)
            border=ConnectedBorder(cell,palette,radius=12,filigree=True,shine=True)
            self.borders.append(border)
            label = tk.Label(cell, text=title+' · waiting', anchor='w', font=('Segoe UI', 9, 'bold'))
            label.pack(fill='x', padx=10, pady=(9, 2)); self.labels[key] = label
            canvas = tk.Canvas(cell, height=62, bd=0, highlightthickness=0)
            canvas.pack(fill='x', padx=10, pady=(0, 9)); self.canvases[key] = canvas
            canvas.bind('<Configure>', lambda _e: self.redraw(), add='+')
        self.bind('<Configure>', self.reflow, add='+'); self.apply_palette(palette)

    def reflow(self, event):
        cols = 4 if event.width >= 850 else 2 if event.width >= 430 else 1
        for col in range(4): self.columnconfigure(col, weight=1 if col < cols else 0)
        for index, cell in enumerate(self.cells): cell.grid(row=index//cols, column=index%cols, sticky='ew', padx=3, pady=3)

    def update_sample(self, data):
        self.samples.append(dict(data))
        for key, label in self.labels.items():
            value = data.get(key)
            text = key.upper()+' · '+('unavailable' if value is None else f'{value:.0f}%')
            if data.get(key+'_total') is not None: text += f" · {data[key+'_used']:.1f}/{data[key+'_total']:.1f} GiB"
            label.configure(text=text)
        self.redraw()

    def apply_palette(self, palette):
        self.palette = dict(palette); self.configure(bg=palette['panel'])
        for cell in self.cells: cell.configure(bg=palette['panel2'])
        for label in self.labels.values(): label.configure(bg=palette['panel2'], fg=palette['text'])
        for canvas in self.canvases.values(): canvas.configure(bg=palette['panel2'])
        for border in self.borders: border.apply_palette(palette)
        self.redraw()

    def redraw(self):
        p = self.palette
        for key, canvas in self.canvases.items():
            canvas.delete('all'); w = max(10, canvas.winfo_width()); h = 56
            for percent in (0, 50, 100):
                y = 3 + h*(1-percent/100)
                canvas.create_line(2,y,w-2,y,fill=p.get('border', '#786747'), dash=(2,4))
            points = []
            def draw_segment():
                if len(points) >= 4: canvas.create_line(*points, fill=p.get('accent', '#3E91A2'), width=2)
            now = self.samples[-1]['at'] if self.samples else 0
            for sample in self.samples:
                value = sample.get(key)
                if value is None or now-sample['at'] > 300:
                    draw_segment(); points = []; continue
                points.extend((2+(w-4)*(1-(now-sample['at'])/300), 3+h*(1-max(0,min(100,value))/100)))
            draw_segment()
