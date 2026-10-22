"""Offline InstructPix2Pix on ROCm; masked edits preserve unselected source pixels."""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--mask',type=Path)
    p.add_argument('--instruction',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--steps',type=int,default=20);p.add_argument('--seed',type=int,default=42);p.add_argument('--cpu-validation',action='store_true')
    a=p.parse_args()
    if not a.output.resolve().is_relative_to(private_path(ROOT, 'Outputs/Images')):p.error('Output must stay in portable image outputs')
    from musetalk_amd_entry import activate
    torch=activate()
    from PIL import Image,ImageOps
    from diffusers import StableDiffusionInstructPix2PixPipeline,EulerAncestralDiscreteScheduler
    if os.name=='nt' and not torch.version.hip:raise RuntimeError('Editing loaded a non-ROCm Torch')
    if a.cpu_validation and torch.cuda.is_available():raise RuntimeError('CPU diagnostic must not hide a working Radeon device')
    if not a.cpu_validation and not torch.cuda.is_available():raise RuntimeError('Radeon compute is unavailable')
    device='cpu' if a.cpu_validation else 'cuda';dtype=torch.float32 if a.cpu_validation else torch.float16
    image=ImageOps.exif_transpose(Image.open(a.source)).convert('RGB')
    original_size=image.size
    scale=min(1,512/max(image.size));size=tuple(max(64,int(v*scale)//8*8) for v in image.size)
    image=image.resize(size,Image.Resampling.LANCZOS)
    pipe=StableDiffusionInstructPix2PixPipeline.from_pretrained(ROOT/'Models/InstructionEdit',variant='fp16',
          torch_dtype=dtype,local_files_only=True,safety_checker=None,feature_extractor=None,requires_safety_checker=False)
    pipe.scheduler=EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
    pipe.enable_attention_slicing();pipe.enable_vae_slicing()
    if a.cpu_validation:pipe.to('cpu')
    else:pipe.enable_model_cpu_offload(gpu_id=0,device='cuda')
    with torch.inference_mode():
        result=pipe(a.instruction,image=image,num_inference_steps=a.steps,guidance_scale=7.5,image_guidance_scale=1.5,
                    generator=torch.Generator(device=device).manual_seed(a.seed)).images[0]
    if a.mask:
        mask=ImageOps.exif_transpose(Image.open(a.mask)).convert('L')
        if mask.size!=original_size:raise ValueError('The source and mask dimensions must match')
        mask=mask.resize(size,Image.Resampling.NEAREST)
        if mask.getextrema()[1]==0:raise ValueError('The supplied or detected mask is empty')
        result=Image.composite(result,image,mask)
    result.convert('RGB').save(a.output,format='PNG')

if __name__=='__main__':main()
