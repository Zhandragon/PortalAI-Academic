"""Bounded read-only Windows UI Automation query in an owned, timed helper."""
import json
import math
import os
from pathlib import Path
import subprocess
import time


def snapshot(root,hwnd,check):
    if os.name!='nt':raise RuntimeError('Accessibility targeting currently requires Windows')
    import hashlib
    directory=Path(root)/'Tools';executable=directory/'accessibility_snapshot.exe'
    manifest=json.loads((directory/'accessibility_snapshot.json').read_text())
    if executable.stat().st_size>128*1024 or hashlib.sha256(executable.read_bytes()).hexdigest()!=manifest['sha256']:
        raise RuntimeError('Accessibility helper integrity check failed; repair the portable installation')
    from mission_supervisor import WorkerJob
    check()
    p=subprocess.Popen([str(executable),str(hwnd)],
                       stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    job=None
    try:
        job=WorkerJob(p);deadline=time.monotonic()+8
        while True:
            check()
            if time.monotonic()>deadline:raise TimeoutError('Accessibility query timed out; use a screenshot instead')
            try:out,err=p.communicate(timeout=.1);break
            except subprocess.TimeoutExpired:continue
        if p.returncode or len(out)>128*1024:raise RuntimeError('Windows accessibility is unavailable for this window; use a screenshot')
        data=json.loads(out.decode('utf-8-sig'))
        if not isinstance(data.get('elements'),list) or len(data['elements'])>80:raise ValueError('Invalid accessibility result')
        for row in data['elements']:
            rect=row.get('rect',[])
            if len(rect)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in rect):raise ValueError('Invalid accessibility bounds')
        check();return data['elements']
    finally:
        if job:job.close()
        if p.poll() is None:p.kill()
        p.wait(timeout=5)
        for stream in (p.stdout,p.stderr):stream.close()


def point(element,observation):
    x,y,w,h=element['rect'];left,top,right,bottom=observation['rect']
    if not element.get('enabled') or w<=0 or h<=0 or not (left<=x<x+w<=right and top<=y<y+h<=bottom):
        raise ValueError('Accessible control is disabled or outside the allowed window')
    return (round((x+w/2-left)*observation['size'][0]/observation['native'][0]),
            round((y+h/2-top)*observation['size'][1]/observation['native'][1]))
