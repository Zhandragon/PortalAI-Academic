from __future__ import annotations
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output

# PORTABLEAI_MUSIC_RUNTIME_COMPAT_v15_108_BEGIN
# PortableAI orchestration now runs under private BootstrapPython 3.12.  Older
# MusicUnderstanding installers placed importable packages directly under a
# CPython-3.13 target directory.  Never inject an ABI-mismatched cp313 tree into
# cp312.  Prefer packages already frozen for the current private runtime; STT's
# python_packages is a known Bootstrap-compatible source for NumPy and related
# pure/Python wheels.
import os as _pai_mu_os
import sys as _pai_mu_sys
from pathlib import Path as _PaiMuPath


def _portableai_music_runtime_compat_v15_108():
    try:
        _root = _PaiMuPath(__file__).resolve().parents[1]
        if _pai_mu_sys.platform.startswith('linux'):
            _pai_mu_sys.path.insert(0,str(_root/'Runtime/LinuxPackages/media'))
            return
        _candidates = []
        _tag = f"cpython-{_pai_mu_sys.version_info.major}{_pai_mu_sys.version_info.minor}-"
        _rt = _root / "MusicUnderstanding" / "runtime"
        if _rt.is_dir():
            for _p in sorted(_rt.iterdir()):
                if _p.is_dir() and _p.name.lower().startswith(_tag):
                    _candidates.append(_p)
        _stt = _root / "SpeechToText" / "python_packages"
        if _stt.is_dir():
            _candidates.append(_stt)
        for _p in reversed(_candidates):
            _s = str(_p)
            if _s not in _pai_mu_sys.path:
                _pai_mu_sys.path.insert(0, _s)
        _pai_mu_os.environ.setdefault("PYTHONNOUSERSITE", "1")
    except Exception:
        # Compatibility setup is best-effort here. The actual feature call will
        # report a precise import error if a required package is still absent.
        pass


_portableai_music_runtime_compat_v15_108()
# PORTABLEAI_MUSIC_RUNTIME_COMPAT_v15_108_END
import json, math, os, shutil, subprocess, sys, platform
from pathlib import Path

VERSION = "15.40d"

def _root_dir() -> Path:
    env = os.environ.get("PORTABLEAI_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent

def _runtime_platform_tag() -> str:
    machine = (platform.machine() or "").lower()
    if os.name == "nt":
        if machine in ("amd64", "x86_64"):
            return "win_amd64"
        if machine in ("arm64", "aarch64"):
            return "win_arm64"
        return "win32"
    return machine or "unknown"

def _runtime_abi_tag() -> str:
    return f"{sys.implementation.cache_tag}-{_runtime_platform_tag()}"

def _private_runtime_dir() -> Path:
    if sys.platform.startswith('linux'):return _root_dir()/'Runtime/LinuxPackages/media'
    return _root_dir() / "MusicUnderstanding" / "runtime" / _runtime_abi_tag()

def _activate_private_runtime() -> Path:
    """Activate only the private dependency directory matching this interpreter ABI."""
    runtime = _private_runtime_dir()
    if runtime.exists():
        rs = str(runtime)
        if rs not in sys.path:
            sys.path.insert(0, rs)
    return runtime

# Activate only after _root_dir and ABI helpers exist.
_activate_private_runtime()

def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

def _find_tool(name: str) -> str:
    if name in ('ffmpeg','ffprobe'):
        from platform_runtime import ffmpeg_path
        candidate=ffmpeg_path(_root_dir(),name=='ffprobe')
        if candidate.is_file():return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    root = _root_dir()
    exe = name + (".exe" if os.name == "nt" else "")
    for p in [
        root/"Tools"/"ffmpeg"/"bin"/exe,
        root/"Tools"/"ffmpeg"/exe,
        root/"ffmpeg"/"bin"/exe,
        Path("C:/ffmpeg/bin")/exe,
    ]:
        if p.exists():
            return str(p)
    raise RuntimeError(f"{name} not found")

def _run(cmd: list[str], timeout: float|None=None, check: bool=True, text: bool=True):
    cp = subprocess.run(cmd, capture_output=True, text=text, timeout=timeout,
                        creationflags=_flags(), shell=False)
    if check and cp.returncode != 0:
        err = cp.stderr if text else (cp.stderr or b"").decode("utf-8","replace")
        raise RuntimeError(f"Command failed ({cp.returncode}):\n{err[-8000:]}")
    return cp

def _probe(path: Path) -> dict:
    cp = _run([_find_tool("ffprobe"),"-v","error","-show_streams","-show_format","-of","json",str(path)],30)
    d = json.loads(cp.stdout or "{}")
    streams = d.get("streams") or []
    aud = [s for s in streams if s.get("codec_type")=="audio"]
    if not aud:
        raise RuntimeError(f"No audio stream found in {path}")
    s = aud[0]
    fmt = d.get("format") or {}
    def f(x, default=0.0):
        try: return float(x)
        except Exception: return default
    duration = f(fmt.get("duration"), 0.0) or f(s.get("duration"),0.0)
    return {
        "duration": duration,
        "codec": s.get("codec_name"),
        "sample_rate": int(float(s.get("sample_rate") or 0)),
        "channels": int(s.get("channels") or 0),
        "channel_layout": s.get("channel_layout"),
        "bit_rate": int(float(s.get("bit_rate") or fmt.get("bit_rate") or 0)),
        "format": fmt.get("format_name"),
    }

def _decode_mono(path: Path, sr: int, start: float|None=None, duration: float|None=None):
    import numpy as np
    cmd=[_find_tool("ffmpeg"),"-hide_banner","-loglevel","error","-nostdin"]
    if start is not None: cmd += ["-ss",f"{max(0.0,start):.3f}"]
    cmd += ["-i",str(path)]
    if duration is not None: cmd += ["-t",f"{max(0.01,duration):.3f}"]
    cmd += ["-vn","-ac","1","-ar",str(sr),"-f","f32le","-"]
    cp=_run(cmd, timeout=max(90, (duration or 300)*2), text=False)
    return np.frombuffer(cp.stdout, dtype="<f4").astype(np.float32, copy=False)

def _analysis_audio(path: Path, duration: float, sr: int=22050):
    import numpy as np
    if duration <= 0 or duration <= 1200:
        y=_decode_mono(path,sr)
        return y, {"strategy":"full","sampled_seconds": round(len(y)/sr,3)}
    seg_len=30.0
    nseg=12
    max_start=max(0.0,duration-seg_len)
    starts=np.linspace(0,max_start,nseg)
    chunks=[_decode_mono(path,sr,float(s),seg_len) for s in starts]
    y=np.concatenate(chunks) if chunks else np.zeros(0,np.float32)
    return y, {"strategy":"distributed","segments":nseg,"segment_seconds":seg_len,
               "sampled_seconds":round(len(y)/sr,3),
               "source_duration_seconds":round(duration,3)}

def _frames(y, n=2048, hop=512):
    import numpy as np
    if len(y) < n:
        y=np.pad(y,(0,n-len(y)))
    count=1+(len(y)-n)//hop
    if count <= 0:
        return y[:n][None,:]
    shape=(count,n); strides=(y.strides[0]*hop,y.strides[0])
    return np.lib.stride_tricks.as_strided(y,shape=shape,strides=strides).copy()

def _stft_features(y, sr=22050, n_fft=2048, hop=512):
    import numpy as np
    fr=_frames(y,n_fft,hop)
    win=np.hanning(n_fft).astype(np.float32)
    spec=np.abs(np.fft.rfft(fr*win[None,:],axis=1)).astype(np.float32)
    power=spec*spec + 1e-12
    freqs=np.fft.rfftfreq(n_fft,1.0/sr).astype(np.float32)
    rms=np.sqrt(np.mean(fr*fr,axis=1)+1e-12)
    mag_sum=np.sum(spec,axis=1)+1e-12
    centroid=np.sum(spec*freqs[None,:],axis=1)/mag_sum
    bandwidth=np.sqrt(np.sum(spec*(freqs[None,:]-centroid[:,None])**2,axis=1)/mag_sum)
    csum=np.cumsum(power,axis=1); total=csum[:,-1]
    target=0.85*total
    ridx=np.argmax(csum>=target[:,None],axis=1)
    rolloff=freqs[ridx]
    flat=np.exp(np.mean(np.log(power),axis=1))/(np.mean(power,axis=1)+1e-12)
    flux=np.zeros(len(spec),np.float32)
    if len(spec)>1:
        d=np.maximum(spec[1:]-spec[:-1],0.0)
        flux[1:]=np.sum(d,axis=1)/(np.sum(spec[1:],axis=1)+1e-12)
    return spec,power,freqs,rms,centroid,bandwidth,rolloff,flat,flux

def _tempo(flux, sr, hop):
    import numpy as np
    x=np.asarray(flux,dtype=np.float64)
    if x.size < 8: return 0.0,0.0
    x=np.maximum(x-np.median(x),0.0)
    x=x-x.mean()
    if np.allclose(x,0): return 0.0,0.0
    ac=np.correlate(x,x,mode="full")[len(x)-1:]
    ac0=float(np.dot(x,x))+1e-12
    ac[0]=0
    lag_min=max(1,int(round(60*sr/(hop*220.0))))
    lag_max=min(len(ac)-1,int(round(60*sr/(hop*50.0))))
    if lag_max<=lag_min: return 0.0,0.0
    lag=lag_min+int(np.argmax(ac[lag_min:lag_max+1]))
    bpm=60.0*sr/(hop*lag)
    conf=float(max(0.0,min(1.0,ac[lag]/ac0)))
    return float(bpm),conf

def _chroma(spec, freqs):
    import numpy as np
    chrom=np.zeros((spec.shape[0],12),np.float64)
    valid=(freqs>=40.0)&(freqs<=5000.0)
    vf=freqs[valid]
    if vf.size==0:return chrom
    midi=np.rint(69+12*np.log2(vf/440.0)).astype(int)
    pcs=np.mod(midi,12)
    vals=spec[:,valid].astype(np.float64)
    for pc in range(12):
        mask=(pcs==pc)
        if np.any(mask): chrom[:,pc]=vals[:,mask].sum(axis=1)
    return chrom/(chrom.sum(axis=1,keepdims=True)+1e-12)

def _key(chroma):
    import numpy as np
    names=["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
    maj=np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88],float)
    minp=np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17],float)
    h=np.mean(chroma,axis=0) if len(chroma) else np.zeros(12)
    if h.sum()<=1e-9:return {"key":None,"mode":None,"confidence":0.0,"pitch_class_profile":{}}
    h=h/(np.linalg.norm(h)+1e-12)
    scores=[]
    for root in range(12):
        for mode,prof in (("major",maj),("minor",minp)):
            p=np.roll(prof,root); p=p/(np.linalg.norm(p)+1e-12)
            scores.append((float(np.dot(h,p)),root,mode))
    scores.sort(reverse=True)
    best,second=scores[0],scores[1]
    conf=max(0.0,min(1.0,(best[0]-second[0])*4.0))
    return {"key":names[best[1]],"mode":best[2],"confidence":round(conf,3),
            "pitch_class_profile":{names[i]:round(float(h[i]),4) for i in range(12)}}

def _sections(chroma, rms, centroid, duration, hop, sr):
    import numpy as np
    if duration<=15 or len(rms)<20:return []
    sec_per_frame=hop/sr
    win=max(1,int(round(8.0/sec_per_frame)))
    feats=[]; times=[]
    for i in range(0,len(rms),win):
        j=min(len(rms),i+win)
        if j-i<max(2,win//3):break
        c=np.mean(chroma[i:j],axis=0) if len(chroma) else np.zeros(12)
        v=np.r_[c, np.mean(rms[i:j])*8.0, np.mean(centroid[i:j])/4000.0]
        v=v/(np.linalg.norm(v)+1e-12)
        feats.append(v); times.append((i+j)*0.5*sec_per_frame)
    changes=[]
    for i in range(1,len(feats)):
        d=1-float(np.dot(feats[i-1],feats[i]))
        if d>0.16: changes.append((d,times[i]))
    changes=sorted(changes,reverse=True)[:10]
    return [round(t,2) for _,t in sorted(changes,key=lambda z:z[1])]

def _core_features(y, sr, source_duration):
    import numpy as np
    if y.size==0: raise RuntimeError("Decoded audio is empty")
    y=np.nan_to_num(y.astype(np.float32),copy=False)
    peak=float(np.max(np.abs(y))+1e-12)
    spec,power,freqs,rms,cent,bw,roll,flat,flux=_stft_features(y,sr)
    chrom=_chroma(spec,freqs)
    key=_key(chrom)
    bpm,beat_conf=_tempo(flux,sr,512)
    rms_db=20*np.log10(np.maximum(rms,1e-8))
    p10,p50,p90=[float(x) for x in np.percentile(rms_db,[10,50,90])]
    silence=float(np.mean(rms_db < -50.0))
    onset_thr=float(np.median(flux)+1.5*np.std(flux))
    onsets=int(np.sum(flux>onset_thr))
    sampled_seconds=max(0.001,len(y)/sr)
    chrom_mean=np.mean(chrom,axis=0)+1e-12
    entropy=float(-np.sum(chrom_mean*np.log2(chrom_mean))/math.log2(12.0))
    return {
      "tempo":{"bpm":round(bpm,2),"beat_regularity":round(beat_conf,3)},
      "tonality":{**key,"tonal_concentration":round(max(0.0,min(1.0,1.0-entropy)),3)},
      "dynamics":{
        "peak_dbfs":round(20*math.log10(max(peak,1e-8)),2),
        "median_rms_dbfs":round(p50,2),
        "rms_p10_dbfs":round(p10,2),
        "rms_p90_dbfs":round(p90,2),
        "dynamic_range_db":round(p90-p10,2),
        "silence_ratio":round(silence,4),
      },
      "spectrum":{
        "spectral_centroid_hz":round(float(np.median(cent)),1),
        "spectral_bandwidth_hz":round(float(np.median(bw)),1),
        "spectral_rolloff_85_hz":round(float(np.median(roll)),1),
        "spectral_flatness":round(float(np.median(flat)),4),
      },
      "rhythm":{
        "onset_density_per_second":round(float(onsets/sampled_seconds),3),
        "onset_count_in_analysis":onsets,
      },
      "structure":{
        "estimated_change_points_seconds":_sections(chrom,rms,cent,source_duration,512,sr)
      }
    }

def _semantic_runtime(root: Path):
    return root/"MusicUnderstanding"/".venv"/"Scripts"/"python.exe", root/"MusicUnderstanding"/"clap_worker.py"

def _semantic(path: Path, device: str, question: str|None):
    root=_root_dir(); py,worker=_semantic_runtime(root)
    if not (py.exists() and worker.exists()):
        return {"available":False,"reason":"CLAP semantic add-on not installed"}
    cmd=[str(py),str(worker),"--input",str(path),"--device",device]
    if question: cmd += ["--question",question]
    cp=_run(cmd, timeout=900, check=False)
    if cp.returncode!=0:
        return {"available":False,"reason":"CLAP worker failed","error":(cp.stderr or cp.stdout or "")[-3000:]}
    try:return json.loads(cp.stdout)
    except Exception:return {"available":False,"reason":"CLAP worker returned invalid JSON"}

class MusicUnderstandingBridge:
    def __init__(self):
        self.root=_root_dir()

    def probe(self) -> dict:
        import importlib.util
        runtime = _activate_private_runtime()
        py,worker=_semantic_runtime(self.root)
        spec = importlib.util.find_spec("numpy")
        return {
          "version":VERSION,
          "ffmpeg":_find_tool("ffmpeg"),
          "ffprobe":_find_tool("ffprobe"),
          "numpy":spec is not None,
          "numpy_source":str(spec.origin) if spec is not None else None,
          "private_runtime":str(runtime),
          "runtime_abi":_runtime_abi_tag(),
          "semantic_clap_installed":py.exists() and worker.exists(),
          "mode":"on-demand"
        }

    def understand(self, input_path: str, question: str|None=None,
                   semantic: bool=True, semantic_device: str="cpu",
                   output_dir: str|None=None) -> dict:
        p=media_reference(self.root, input_path)
        if not p.exists(): raise FileNotFoundError(str(p))
        info=_probe(p)
        y,sampling=_analysis_audio(p,info["duration"],22050)
        core=_core_features(y,22050,info["duration"])
        sem=_semantic(p,semantic_device,question) if semantic else {"available":False,"reason":"disabled"}
        outdir=media_output(self.root, output_dir) if output_dir else private_path(self.root, "Outputs")/"MusicUnderstanding"
        outdir.mkdir(parents=True,exist_ok=True)
        result={
          "version":VERSION,
          "source":str(p),
          "question":question,
          "media":info,
          "analysis_sampling":sampling,
          "features":core,
          "semantic":sem,
          "interpretation_guidance":{
            "confidence_note":"Tempo/key are estimates; CLAP scores are relative similarities, not calibrated probabilities.",
            "outer_model_instruction":"Use these measured/semantic features as evidence. Do not invent instruments, genre, mood, lyrics, or production traits not supported by the returned data."
          }
        }
        stem=p.stem[:80]
        jp=outdir/f"{stem}_music_understanding.json"
        tp=outdir/f"{stem}_music_understanding.txt"
        jp.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        lines=[
          f"Music understanding: {p.name}",
          f"Duration: {info['duration']:.2f}s | codec: {info['codec']} | channels: {info['channels']}",
          f"Tempo: {core['tempo']['bpm']} BPM (regularity {core['tempo']['beat_regularity']})",
          f"Key: {core['tonality']['key']} {core['tonality']['mode']} (confidence {core['tonality']['confidence']})",
          f"Dynamics: median {core['dynamics']['median_rms_dbfs']} dBFS, range {core['dynamics']['dynamic_range_db']} dB",
          f"Spectral centroid: {core['spectrum']['spectral_centroid_hz']} Hz | flatness {core['spectrum']['spectral_flatness']}",
          f"Onset density: {core['rhythm']['onset_density_per_second']}/s",
          f"Change points: {core['structure']['estimated_change_points_seconds']}",
        ]
        if sem.get("available"):
            lines += [
              "Semantic CLAP:",
              "  genres/styles: "+", ".join(f"{x['label']} ({x['score']:.3f})" for x in sem.get("genre",[])[:5]),
              "  moods: "+", ".join(f"{x['label']} ({x['score']:.3f})" for x in sem.get("mood",[])[:5]),
              "  instruments/voices: "+", ".join(f"{x['label']} ({x['score']:.3f})" for x in sem.get("instrumentation",[])[:7]),
            ]
        else:
            lines.append("Semantic CLAP: unavailable ("+str(sem.get("reason","unknown"))+")")
        tp.write_text("\n".join(lines)+"\n",encoding="utf-8")
        result["files"]=[str(jp),str(tp)]
        return result
