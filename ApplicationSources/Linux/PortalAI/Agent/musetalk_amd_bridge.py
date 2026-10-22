"""Bounded Radeon MuseTalk, using the shared cancellation gate and GPU lease caller."""
import json
import math
from pathlib import Path
import shutil
import subprocess

from runtime_policy import ROOT,GIB,detect_hardware
from platform_runtime import python_path,ffmpeg_path
from sdcpp_bridge import run_generation
from media_paths import media_reference, media_output


def plan(root=ROOT,hardware=None,cpu_validation=False):
    hw=hardware or detect_hardware()
    if hw['system'] not in ('Windows','Linux'):raise RuntimeError('MuseTalk requires Windows/Linux x64')
    if cpu_validation:needed=14*GIB;gpu={}
    else:
        from amd_runtime import probe
        from linux_ml import media_compute
        gpu=media_compute(root,hw,hardware is not None)
        if not gpu or not gpu.get('available') or not gpu.get('compute_ok'):raise RuntimeError('MuseTalk needs a successful Radeon compute probe')
        if gpu.get('free_bytes',0)<6*GIB:raise RuntimeError('MuseTalk needs 6 GiB free GPU memory after chat unload')
        needed=(20 if gpu.get('shared_memory',True) else 12)*GIB
    if hw['ram_available_bytes']<needed:raise RuntimeError(f'MuseTalk requires {needed/GIB:g} GiB available RAM after chat unload')
    for path in ('Video/MuseTalk/models/dwpose/dw-ll_ucoco_384.onnx',('Runtime/AMDMusic/api-packages/diffusers/__init__.py' if hw['system']=='Windows' else 'Runtime/LinuxPackages/media/diffusers/__init__.py')):
        if not (Path(root)/path).is_file():raise RuntimeError('Missing portable MuseTalk dependency: '+path)
    return {'backend':'rocm-cpu-validation' if cpu_validation else gpu.get('backend','rocm'),'engine':'musetalk-1.5-rocm',
            'cpu_validation':cpu_validation,'min_free_ram_bytes':4*GIB,'max_memory_bytes':12*GIB,
            'max_seconds':8,'max_dimension':512,'physical_radeon_validated':False}


def generate(profile,video,audio,output=None,root=ROOT,validation_fps=25):
    root=Path(root).resolve();video=media_reference(root,video);audio=media_reference(root,audio)
    destination=media_output(root,output) if output is not None else None
    if not video.is_file() or not audio.is_file():raise FileNotFoundError('MuseTalk input video/audio is missing')
    def inspect(path):
        cp=subprocess.run([str(ffmpeg_path(root,True)),'-v','error','-show_streams','-show_format','-of','json',str(path)],
                          capture_output=True,check=True,timeout=30)
        return json.loads(cp.stdout)
    data=inspect(audio);duration=float(data['format'].get('duration',0))
    if not math.isfinite(duration) or not .2<=duration<=8:raise ValueError('Radeon MuseTalk accepts 0.2..8 seconds; split longer dialogue into shots')
    def command(part):
        cmd=[str(python_path(root)),'-B','-I','-X','utf8',str(root/'Agent/musetalk_amd_entry.py'),
             '--video',str(video),'--audio',str(audio),'--output',str(part)]
        if profile.get('cpu_validation'):cmd+=['--cpu-validation','--validation-fps',str(validation_fps)]
        elif validation_fps!=25:raise ValueError('Reduced FPS is diagnostic-only')
        return cmd
    def validate(part):
        if not part.is_file() or not 1024<part.stat().st_size<256*1024**2:raise RuntimeError('MuseTalk did not produce a bounded MP4')
        data=inspect(part);streams=data['streams'];v=next(x for x in streams if x['codec_type']=='video')
        if max(v['width'],v['height'])>512 or not any(x['codec_type']=='audio' for x in streams):raise RuntimeError('MuseTalk output stream validation failed')
        if abs(float(data['format']['duration'])-duration)>.3:raise RuntimeError('MuseTalk audio/video duration mismatch')
    result=run_generation(profile,command,validate,root=root,timeout=1800,kind='musetalk')
    if destination is not None:
        destination=media_output(root,destination);destination.parent.mkdir(parents=True,exist_ok=True)
        if destination!=Path(result['files'][0]):shutil.copy2(result['files'][0],destination)
        result['files']=[str(destination)]
    return {**result,'backend':profile['backend'],'hardware_profile':profile,'fresh_output':True}
