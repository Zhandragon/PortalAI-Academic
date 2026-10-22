"""MuseTalk 1.5 in isolated ROCm Python 3.12, with staged model residency.

Pose uses the official DWPose ONNX CPU export. Whisper, VAE, UNet and face
parsing run in separate stages; the large UNet is never resident beside a VAE.
The original CUDA implementation and vendor files are left intact.
"""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference
import argparse
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import shutil
import uuid

ROOT=Path(__file__).resolve().parents[1]


def finish_workspace(job,output,duration,root=ROOT):
    """Remove only this completed job after checking the actual muxed streams."""
    from platform_runtime import ffmpeg_path
    root=Path(root).resolve();job=Path(job);output=Path(output)
    cache=private_path(root, 'Cache/MuseTalk')
    if job.is_symlink() or job.resolve().parent!=cache.resolve() or not job.name.startswith('rocm_') or not job.resolve().is_relative_to(root):
        raise RuntimeError('MuseTalk workspace escaped its portable cache')
    if not output.is_file() or not 1024<output.stat().st_size<256*1024**2:
        raise RuntimeError('MuseTalk did not produce a bounded MP4; workspace retained')
    cp=subprocess.run([str(ffmpeg_path(root,True)),'-v','error','-show_streams','-show_format','-of','json',str(output)],
                      capture_output=True,check=True,timeout=30)
    data=json.loads(cp.stdout);streams=data['streams']
    video=next((s for s in streams if s.get('codec_type')=='video'),None)
    if not video or not 0<min(video['width'],video['height'])<=max(video['width'],video['height'])<=512 or not any(s.get('codec_type')=='audio' for s in streams):
        raise RuntimeError('MuseTalk output stream validation failed; workspace retained')
    actual_duration=float(data['format']['duration'])
    if not math.isfinite(actual_duration) or abs(actual_duration-duration)>.3:
        raise RuntimeError('MuseTalk output duration mismatch; workspace retained')
    shutil.rmtree(job)


def activate():
    sys.path.insert(0,str(ROOT/'Agent'))
    from mmaudio_amd_entry import activate as common
    common(ROOT)
    if os.name=='nt':
        sys.path[:0]=[str(ROOT/'Runtime/AMDMusic/api-packages'),str(ROOT/'Runtime/AMDMusic/packages')]
    sys.path.insert(0,str(ROOT/'Video/MuseTalk'))
    os.environ.update(OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
    import torch
    torch.set_num_threads(2)
    return torch


def release(torch):
    gc.collect()
    if torch.cuda.is_available():torch.cuda.empty_cache()


def face_box(frame,session):
    """DWPose whole-image affine/SimCC decode, matching the official ONNX path."""
    import cv2
    import numpy as np
    h,w=frame.shape[:2];ih,iw=session.get_inputs()[0].shape[2:]
    scale=np.array([w,h],dtype=np.float32)*1.25
    scale=np.array([max(scale[0],scale[1]*iw/ih),max(scale[1],scale[0]*ih/iw)])
    center=np.array([w,h],dtype=np.float32)/2
    ratio=iw/scale[0]
    matrix=np.array([[ratio,0,iw/2-center[0]*ratio],[0,ratio,ih/2-center[1]*ratio]])
    crop=cv2.warpAffine(frame,matrix,(iw,ih),flags=cv2.INTER_LINEAR)
    x=((crop.astype(np.float32)-[123.675,116.28,103.53])/[58.395,57.12,57.375]).astype(np.float32)
    sx,sy=session.run(None,{session.get_inputs()[0].name:x.transpose(2,0,1)[None]})
    confidence=np.minimum(sx.max(-1),sy.max(-1))[0,23:91]
    points=np.stack([sx.argmax(-1),sy.argmax(-1)],-1)[0]/2/[iw,ih]*scale+center-scale/2
    face=points[23:91].astype(np.int32)
    if len(face)!=68 or (confidence>.15).sum()<50:
        raise RuntimeError('No sufficiently confident single face; use a clear front-facing portrait clip')
    x1=max(0,int(face[:,0].min()));x2=min(w,int(face[:,0].max()))
    y2=min(h,int(face[:,1].max()));y1=max(0,int(2*face[29,1]-face[:,1].max()))
    if min(x2-x1,y2-y1)<16:raise RuntimeError('Detected face is too small or outside the frame')
    return x1,y1,x2,y2


def infer(video,audio,output,*,cpu=False,fps=25):
    torch=activate()
    import cv2
    import numpy as np
    import onnxruntime as ort
    from diffusers import AutoencoderKL,UNet2DConditionModel
    from transformers import WhisperModel
    from musetalk.models.unet import PositionalEncoding
    from musetalk.utils.audio_processor import AudioProcessor
    from platform_runtime import ffmpeg_path
    from runtime_policy import require_space
    if os.name=='nt' and not torch.version.hip:raise RuntimeError('MuseTalk AMD requires the isolated ROCm runtime')
    if cpu and torch.cuda.is_available():raise RuntimeError('CPU validation must not mask an available Radeon GPU')
    if not cpu and not torch.cuda.is_available():raise RuntimeError('A real ROCm GPU is required')
    device='cpu' if cpu else 'cuda';dtype=torch.float32 if cpu else torch.float16
    work=ROOT/'Video/MuseTalk';os.chdir(work)
    job=private_path(ROOT, 'Cache/MuseTalk')/('rocm_'+uuid.uuid4().hex);job.mkdir(parents=True)
    require_space(ROOT,1024**3,for_outputs=True)
    ffmpeg=str(ffmpeg_path(ROOT));wav=job/'audio.wav'
    subprocess.run([ffmpeg,'-v','error','-nostdin','-threads','2','-i',str(audio),'-t','8.05',
                    '-ar','16000','-ac','1',str(wav)],check=True,timeout=45)
    import soundfile as sf
    samples,sr=sf.read(wav)
    duration=len(samples)/sr
    if not .2<=duration<=8:raise ValueError('The scaled MuseTalk profile accepts 0.2..8 seconds of audio')
    count=int(duration*fps)
    # Sampling/size are bounded before tensors or frame lists are allocated.
    subprocess.run([ffmpeg,'-v','error','-nostdin','-threads','2','-stream_loop','-1','-i',str(video),
                    '-t',str(duration),'-vf',f'fps={fps},scale=512:512:force_original_aspect_ratio=decrease:force_divisible_by=2',
                    '-frames:v',str(count),str(job/'source_%04d.png')],check=True,timeout=90)
    frames=sorted(job.glob('source_*.png'))
    if len(frames)!=count:raise RuntimeError('Input video did not produce the requested number of frames')
    asset=work/'models/dwpose/dw-ll_ucoco_384.onnx'
    receipt=json.loads((ROOT/'Maintenance/Imports/musetalk-onnx.json').read_text())
    with asset.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if asset.stat().st_size!=receipt['bytes'] or digest!=receipt['sha256']:raise RuntimeError('Pose model integrity failure')
    opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
    session=ort.InferenceSession(str(asset),sess_options=opts,providers=['CPUExecutionProvider'])
    boxes=[face_box(cv2.imread(str(p)),session) for p in frames]
    del session;release(torch);print('stage=pose complete',flush=True)
    with torch.inference_mode():
        processor=AudioProcessor(str(work/'models/whisper'))
        features,length=processor.get_audio_feature(str(wav),weight_dtype=dtype)
        whisper=WhisperModel.from_pretrained(work/'models/whisper',local_files_only=True).to(device,dtype).eval()
        chunks=processor.get_whisper_chunk(features,device,dtype,whisper,length,fps=fps).cpu()
        if len(chunks)!=count:raise RuntimeError('Whisper/video frame alignment mismatch')
        del whisper,features,processor;release(torch);print('stage=whisper complete',flush=True)
        vae=AutoencoderKL.from_pretrained(work/'models/sd-vae',local_files_only=True).to(device,dtype).eval()
        latent=[]
        for path,(x1,y1,x2,y2) in zip(frames,boxes):
            face=cv2.resize(cv2.imread(str(path))[y1:y2,x1:x2],(256,256),interpolation=cv2.INTER_LANCZOS4)
            x=torch.from_numpy(face[:,:,::-1].copy()).permute(2,0,1)[None].to(device,dtype)/255
            masked=x.clone();masked[:,:,128:]=0
            a=vae.encode(masked*2-1).latent_dist.sample()*vae.config.scaling_factor
            b=vae.encode(x*2-1).latent_dist.sample()*vae.config.scaling_factor
            latent.append(torch.cat([a,b],1).cpu())
        del vae,x,masked,a,b;release(torch);print('stage=vae-encode complete',flush=True)
        # Meta construction + mmap assignment avoids a second 3.4 GB weight copy.
        config=json.loads((work/'models/musetalkV15/musetalk.json').read_text())
        with torch.device('meta'):net=UNet2DConditionModel(**config)
        weights=torch.load(work/'models/musetalkV15/unet.pth',map_location='cpu',weights_only=True,mmap=True)
        net.load_state_dict(weights,assign=True);del weights
        net=net.to(device,dtype).eval();pe=PositionalEncoding().to(device,dtype)
        predictions=[]
        for i,value in enumerate(latent):
            pred=net(value.to(device,dtype),torch.tensor([0],device=device),encoder_hidden_states=pe(chunks[i:i+1].to(device,dtype))).sample
            if not torch.isfinite(pred).all():raise RuntimeError('MuseTalk produced non-finite latents')
            predictions.append(pred.cpu())
        del net,pe,pred,latent,chunks;release(torch);print('stage=unet complete',flush=True)
        vae=AutoencoderKL.from_pretrained(work/'models/sd-vae',local_files_only=True).to(device,dtype).eval()
        for i,pred in enumerate(predictions):
            pixels=vae.decode(pred.to(device,dtype)/vae.config.scaling_factor).sample
            if not torch.isfinite(pixels).all():raise RuntimeError('MuseTalk VAE produced invalid pixels')
            face=((pixels/2+.5).clamp(0,1)[0].permute(1,2,0).float().cpu().numpy()*255).round().astype('uint8')[:,:,::-1]
            if not cv2.imwrite(str(job/f'face_{i:04d}.png'),face):raise RuntimeError('Failed to save generated face')
        del vae,predictions,pred,pixels;release(torch);print('stage=vae-decode complete',flush=True)
        from musetalk.utils.face_parsing import FaceParsing
        from musetalk.utils.face_parsing.model import BiSeNet
        from musetalk.utils.face_parsing.resnet import Resnet18
        from musetalk.utils.blending import get_image
        # The complete parser checkpoint includes every ResNet weight. Skip the
        # obsolete ImageNet tar pre-load; strict loading proves no weight is missing.
        class CompleteParser(FaceParsing):
            def model_init(self):
                original=Resnet18.init_weight
                try:
                    Resnet18.init_weight=lambda self,path:None
                    model=BiSeNet('unused')
                finally:Resnet18.init_weight=original
                model.load_state_dict(torch.load(work/'models/face-parse-bisent/79999_iter.pth',
                                                map_location='cpu',weights_only=True),strict=True)
                return model.to(device).eval()
        parser=CompleteParser()
        for i,(path,box) in enumerate(zip(frames,boxes)):
            x1,y1,x2,y2=box
            face=cv2.resize(cv2.imread(str(job/f'face_{i:04d}.png')),(x2-x1,y2-y1))
            blended=get_image(cv2.imread(str(path)),face,box,mode='jaw',fp=parser)
            if blended is None or not cv2.imwrite(str(job/f'result_{i:04d}.png'),blended):
                raise RuntimeError('Face compositing failed')
        del parser;release(torch)
    subprocess.run([ffmpeg,'-v','error','-nostdin','-threads','2','-framerate',str(fps),'-start_number','0',
                    '-i',str(job/'result_%04d.png'),'-i',str(wav),'-c:v','libx264','-threads','2','-pix_fmt','yuv420p',
                    '-c:a','aac','-shortest','-movflags','+faststart','-f','mp4',str(output)],check=True,timeout=90)
    finish_workspace(job,output,duration)
    from media_precision import execution_backend
    print(json.dumps({'backend':execution_backend(torch,cpu),'frames':count,'workspace':str(job),
                      'workspace_cleaned':True}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--video',type=Path,required=True);p.add_argument('--audio',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--cpu-validation',action='store_true')
    p.add_argument('--validation-fps',type=int,choices=[5,25],default=25);a=p.parse_args()
    if a.validation_fps!=25 and not a.cpu_validation:p.error('Reduced FPS is diagnostic-only')
    output=a.output.resolve()
    if not output.is_relative_to(private_path(ROOT, 'Outputs/Videos/MuseTalk')) or output.suffix!='.mp4':p.error('Output must stay in portable MuseTalk outputs')
    infer(a.video.resolve(),a.audio.resolve(),output,cpu=a.cpu_validation,fps=a.validation_fps)
