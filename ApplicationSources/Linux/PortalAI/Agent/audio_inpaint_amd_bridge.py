"""Bounded Radeon/Linux localized audio repair with preserved source context.

General/SFX uses experimental masked MMAudio flow; music uses ACE-Step repaint.
Explicit speech retains the existing experimental spectrogram route and is never
described as a speech-trained or exact-word replacement model.
"""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import stat as stat_module
import tempfile
import time
import uuid
import wave

from runtime_policy import ROOT,GIB,require_space,memory_info
from platform_runtime import python_path,ffmpeg_path
from profile_paths import capture,ProfileLocked,private_path,_contained
from profile_lazy_state import publish_no_replace
from media_paths import media_reference,media_output,media_temp
from sdcpp_bridge import run_generation
from chat_model_switch import _guard


def request(total, instruction, *, start=0, end=None, duration=None, context=1, crossfade=.04,
            mode='auto', seed=None, expand=8):
    if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>4000:
        raise ValueError('Audio repair needs an instruction of 1..4000 characters')
    mode=(mode or 'auto').lower()
    if mode not in ('auto','general','music','speech'): raise ValueError('Unknown audio repair mode')
    mode='general' if mode=='auto' else mode
    if mode=='music' and len(instruction)>512: raise ValueError('Music repaint instruction exceeds 512 characters')
    start=0 if start is None else float(start)
    if end is not None and duration is not None: raise ValueError('Choose end or duration, not both')
    if end is None and duration is None: raise ValueError('An explicit repair end or duration is required')
    end=float(end) if end is not None else start+float(duration)
    values=(total,start,end,context,crossfade)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        raise ValueError('Audio repair times must be finite numbers')
    maximum=24 if mode=='music' else 6
    if not 0<total<=3600 or not 0<=start<end<=total or not .05<=end-start<=maximum:
        raise ValueError(f'Audio repair needs a .05..{maximum}s interval inside a source up to one hour')
    if not 0<=context<=3 or not 0<=crossfade<=.5: raise ValueError('Context must be 0..3s and crossfade 0...5s')
    seed=42 if seed is None else seed
    if type(seed) is not int or not 0<=seed<2**31: raise ValueError('Invalid repair seed')
    if type(expand) is not int or not 0<=expand<=32: raise ValueError('Mask expansion must be 0..32')
    left=max(0,start-context);right=min(total,end+context)
    maximum_window=30 if mode=='music' else 8
    if right-left>maximum_window: raise ValueError(f'Repair including requested context exceeds {maximum_window}s; narrow the interval/context')
    length=max(10 if mode=='music' else 1,right-left)
    if mode=='general':
        from audio_inpaint_math import mask_span
        mask_span(start-left,end-left,44100,1024,math.ceil(length*44100/1024),expand)
        if (start-left)+(right-end)<.1: raise ValueError('Masked audio repair needs observed surrounding audio; use sfx for whole-clip generation')
    return dict(mode=mode,instruction=instruction,start=start,end=end,window_start=left,window_end=right,
                window_duration=length,relative_start=start-left,relative_end=end-left,
                crossfade=crossfade,context=context,seed=seed,expand=expand)


def plan(mode='general',root=ROOT,hardware=None,cpu_validation=False):
    if mode=='music':
        if cpu_validation: raise RuntimeError('Music repaint CPU validation is not enabled')
        from music_amd_bridge import plan as choose
        result=choose(root,hardware)
        # The runtime requires BF16; reject unsupported devices before launching.
        from media_precision import probe_bf16
        gpu=(hardware or {}).get('media_gpu',(hardware or {}).get('amd_gpu',{}))
        check=gpu if hardware is not None else probe_bf16(root,result['backend'])
        if not check.get('bf16_compute_ok'): raise RuntimeError('Music repaint needs a real BF16 compute probe')
    else:
        from sfx_amd_bridge import plan as choose
        result=choose(root,hardware,cpu_validation)
    return {**result,'engine':'acestep-native-repaint' if mode=='music' else 'mmaudio-masked-flow',
            'max_memory_bytes':12*GIB,'min_free_ram_bytes':4*GIB,'cpu_validation':cpu_validation,
            'experimental':mode!='music','physical_gpu_validated':False}


@contextmanager
def lease(check=lambda:None):
    import service_manager as service
    check()
    token=service.acquire_gpu_lease('audio-inpaint');state=None
    try:
        check();service.quiesce_gpu_workers(None)
        state=service.qwen_gpu_handoff_begin('audio-inpaint',start_guard=check)
        check()
        yield
    finally:
        try: service.qwen_gpu_handoff_end(state)
        finally: service.release_gpu_lease(token)


def _ffmpeg(root,args,work,check):
    from dialogue_portable import _run
    return _run(root,[ffmpeg_path(root),'-v','error','-nostdin','-y','-threads','2',*args],work,check,timeout=600)


def _info(root,path,check):
    from dialogue_portable import _probe
    with tempfile.TemporaryDirectory(prefix='audio_probe_',dir=media_temp(root)) as work:
        info,duration=_probe(root,path,Path(work),check)
    audios=[row for row in info.get('streams',[]) if row.get('codec_type')=='audio']
    return {'has_audio':bool(audios),'audio':audios[0] if audios else {},'duration_seconds':duration}


def generate_window(profile,source,job,root=ROOT,check=lambda:None):
    root=Path(root)
    owned={}
    def command(part):
        check()
        args=[str(python_path(root)),'-B','-I','-X','utf8',str(root/'Agent/audio_inpaint_amd_entry.py'),
              '--source',str(source),'--output',str(part),'--mode',job['mode'],'--prompt',job['instruction'],
              '--start',str(job['relative_start']),'--end',str(job['relative_end']),
              '--duration',str(job['window_duration']),'--seed',str(job['seed']),'--expand',str(job['expand'])]
        if profile.get('cpu_validation'):args.append('--cpu-validation')
        return args
    def validate(path):
        check()
        if not path.is_file() or not 128<=path.stat().st_size<=16*1024**2:raise RuntimeError('Repair worker produced no bounded audio')
        value=_info(root,path,check);row=value['audio'];expected=48000 if job['mode']=='music' else 44100
        if not value['has_audio'] or int(row['sample_rate'])!=expected or int(row['channels']) not in (1,2) or abs(value['duration_seconds']-job['window_duration'])>.15:
            raise RuntimeError('Repair worker output duration/rate/channels differ')
        current=path.lstat()
        if not stat_module.S_ISREG(current.st_mode):raise RuntimeError('Staged audio is not a regular file')
        owned['identity']=(current.st_dev,current.st_ino)
    result=run_generation(profile,command,validate,root=root,timeout=1200,kind='music' if job['mode']=='music' else 'sfx')
    return {**result,'_owned_file_identity':owned['identity']}


def _window(source,destination,job):
    with wave.open(str(source),'rb') as src,wave.open(str(destination),'wb') as dst:
        rate=src.getframerate();channels=src.getnchannels();size=src.getsampwidth()
        left=round(job['window_start']*rate);available=round((job['window_end']-job['window_start'])*rate)
        count=round(job['window_duration']*rate)
        src.setpos(left);data=src.readframes(available)
        if len(data)!=available*channels*size:raise RuntimeError('Source ended before the selected repair window')
        dst.setparams((channels,size,rate,0,'NONE','not compressed'))
        dst.writeframes(data+b'\0'*(max(0,count-available)*channels*size))


def compose_pcm(source,replacement,destination,job,check=lambda:None):
    """Stream unchanged PCM around the only rewritten sample interval."""
    import numpy as np
    from audio_inpaint_math import blend_region
    with wave.open(str(source),'rb') as src,wave.open(str(replacement),'rb') as rep,wave.open(str(destination),'wb') as dst:
        if (src.getframerate(),src.getnchannels(),src.getsampwidth())!=(rep.getframerate(),rep.getnchannels(),rep.getsampwidth()) or src.getsampwidth()!=2:
            raise RuntimeError('Repair PCM format differs from source')
        rate=src.getframerate();channels=src.getnchannels();first=round(job['start']*rate);last=round(job['end']*rate)
        dst.setparams(src.getparams())
        def copy(count):
            while count:
                check();frames=min(32768,count);data=src.readframes(frames)
                if len(data)!=frames*channels*2:raise RuntimeError('Unexpected source PCM length')
                dst.writeframesraw(data);count-=frames
        copy(first);count=last-first
        original=src.readframes(count);rep.setpos(round(job['relative_start']*rate));generated=rep.readframes(count)
        if len(original)!=count*channels*2 or len(generated)!=len(original):raise RuntimeError('Repair interval length differs')
        old=np.frombuffer(original,dtype='<i2').reshape(-1,channels);new=np.frombuffer(generated,dtype='<i2').reshape(-1,channels)
        check();dst.writeframesraw(blend_region(old,new,round(job['crossfade']*rate)).tobytes())
        copy(src.getnframes()-last);check()


def audio_inpaint(input_path,instruction,*,output=None,start=None,end=None,duration=None,context=1.,
                  crossfade=.04,mode='auto',seed=None,expand=8,root=ROOT):
    root=Path(root).resolve();requested_at=time.time();identity=capture(root)
    def check():
        if capture(root)!=identity:raise ProfileLocked('Audio repair login ended before publication')
        _guard(root,requested_at)
        if memory_info()[1]<4*GIB:raise RuntimeError('Audio repair stopped at the free-RAM reserve')
    check()
    source=media_reference(root,input_path)
    info=_info(root,source,check)
    if not info.get('has_audio'):raise ValueError('Source has no audio stream')
    channels=int(info['audio']['channels'])
    if channels not in (1,2):raise ValueError('Localized repair supports mono/stereo; multichannel is never silently downmixed')
    job=request(float(info['duration_seconds']),instruction,start=start,end=end,duration=duration,
                context=context,crossfade=crossfade,mode=mode,seed=seed,expand=expand)
    # Canonical PCM is streamed on disk. Never allocate the whole source in RAM.
    require_space(root,int(info['duration_seconds']*44100*channels*2*3)+64*1024**2,for_outputs=True)
    extension=source.suffix.lower() if source.suffix.lower() in {'.wav','.flac','.mp3','.m4a','.aac','.ogg','.opus','.wma'} else '.wav'
    out=media_output(root,output) if output else private_path(root,'Outputs/EditedAudio')/(source.stem+'_inpainted'+extension)
    if not out.is_relative_to(private_path(root,'Outputs')):raise ValueError('Audio repair output must stay under this account Outputs')
    _contained(root,out);check()
    if out.exists():raise FileExistsError('Repair destination already exists; choose a new output filename')
    out.parent.mkdir(parents=True,exist_ok=True)
    part=out.with_name(out.stem+'.'+uuid.uuid4().hex+'.part'+out.suffix)
    published=False;owned=None;part_identity=None;intermediate=None;intermediate_identity=None;spectral_outputs=[]
    try:
        with tempfile.TemporaryDirectory(prefix='audio_inpaint_',dir=media_temp(root)) as folder:
            folder=Path(folder);canonical=folder/'source.wav';window=folder/'window.wav';replacement=folder/'replacement.wav';mixed=folder/'mixed.wav'
            check();_ffmpeg(root,['-i',str(source),'-map','0:a:0','-vn','-ar','44100','-ac',str(channels),'-c:a','pcm_s16le',str(canonical)],folder,check);check()
            _window(canonical,window,job);check()
            if job['mode']=='speech':
                from media_edit_bridge import audio_inpaint as spectral
                result=spectral(window,instruction,output=folder/'speech.wav',start=job['relative_start'],end=job['relative_end'],
                                context=0,crossfade=crossfade,mode='speech',seed=seed,expand=expand,
                                start_guard=check,ffmpeg_runner=lambda args:_ffmpeg(root,args,folder,check),
                                probe=lambda path:_info(root,path,check),owned_outputs=spectral_outputs)
                backend='experimental-spectrogram-speech';experimental=True
            else:
                expected=private_path(root,'Outputs/Music' if job['mode']=='music' else 'Outputs/SFX')
                prefix='acestep_' if job['mode']=='music' else 'mmaudio_'
                with lease(check):
                    check();profile=plan(job['mode'],root=root);check()
                    result=generate_window(profile,window,job,root=root,check=check)
                    files=result.get('files') or []
                    if len(files)!=1:raise RuntimeError('Repair worker did not produce exactly one file')
                    candidate=Path(files[0]);_contained(root,candidate)
                    if candidate.parent!=expected or not candidate.name.startswith(prefix) or candidate.suffix!='.flac':
                        raise RuntimeError('Repair worker returned an unexpected output namespace')
                    intermediate=candidate;intermediate_identity=tuple(result['_owned_file_identity'])
                    current=candidate.lstat()
                    if not stat_module.S_ISREG(current.st_mode) or (current.st_dev,current.st_ino)!=intermediate_identity:
                        raise RuntimeError('Repair worker output identity changed')
                    check()
                backend=profile['backend']+'/'+profile['engine'];experimental=job['mode']=='general'
            check();generated=media_reference(root,result['files'][0])
            _ffmpeg(root,['-i',str(generated),'-ar','44100','-ac',str(channels),'-c:a','pcm_s16le',str(replacement)],folder,check);check()
            compose_pcm(canonical,replacement,mixed,job,check)
            from media_edit_bridge import _audio_codec_args
            check()
            with part.open('xb'): pass
            stat=part.stat();part_identity=(stat.st_dev,stat.st_ino)
            _ffmpeg(root,['-i',str(mixed),*_audio_codec_args(out),str(part)],folder,check);check()
            stat=part.stat()
            if (stat.st_dev,stat.st_ino)!=part_identity:raise RuntimeError('Staged repair file identity changed')
            verified=_info(root,part,check)
            if not verified.get('has_audio') or abs(float(verified['duration_seconds'])-float(info['duration_seconds']))>.15:
                raise RuntimeError('Final repair duration differs from source')
            _contained(root,out);check();stat=part.stat();owned=(stat.st_dev,stat.st_ino)
            publish_no_replace(part,out);published=True;check()
        return {'files':[str(out)],'source':str(source),'backend':backend,'duration_seconds':verified['duration_seconds'],
                'operations':{**job,'experimental':experimental,'audio_native':job['mode']!='speech',
                    'preservation':'Outside-interval canonical PCM copied unchanged before requested output encoding',
                    'note':('Training-free masked latent flow; quality is experimental, not an inpaint-trained checkpoint.' if job['mode']=='general' else
                            'Native ACE-Step source-conditioned repaint.' if job['mode']=='music' else
                            'Experimental visual spectrogram infill; no speech/voice/word preservation guarantee.')},
                'physical_gpu_validation':'pending'}
    except BaseException:
        if published and out.is_file() and not out.is_symlink():
            stat=out.lstat()
            if (stat.st_dev,stat.st_ino)==owned:out.unlink()
        raise
    finally:
        from dialogue_portable import _remove_owned
        for path,file_identity in spectral_outputs:
            _remove_owned(root,path,file_identity)
        if intermediate is not None and intermediate_identity is not None:
            _remove_owned(root,intermediate,intermediate_identity)
        if part_identity is not None and part.is_file() and not part.is_symlink():
            stat=part.lstat()
            if (stat.st_dev,stat.st_ino)==part_identity:part.unlink()
