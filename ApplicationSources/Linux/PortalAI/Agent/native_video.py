"""Bounded Wan 1.3B text-to-video on native Vulkan or CPU, with CPU T5/VAE."""
import json
import os
from pathlib import Path
import subprocess

from runtime_policy import ROOT, GIB, detect_hardware, portable_path
from platform_runtime import ffmpeg_path
from sdcpp_bridge import engine_plan, run_generation

MODELS = 'Generative/ComfyUI_windows_portable/ComfyUI/models/'
WAN = MODELS+'diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors'
WAN_ALTERNATE = MODELS+'diffusion_models/wan_1.3B_exp_e14.safetensors'
T5 = MODELS+'text_encoders/umt5-xxl-encoder-Q4_K_M.gguf'
VAE = MODELS+'vae/wan_2.1_vae.safetensors'
SIZES = {WAN: 2838303560, T5: 3655145312, VAE: 253815318}


def video_plan(root=ROOT, engine='auto', width=256, height=256, frames=17, fps=8, hardware=None, variant='official'):
    variant = 'official'
    root = Path(root).resolve()
    if variant not in ('official', 'uncensored'): raise ValueError('Unknown small video model variant')
    if engine not in ('auto', 'sdcpp-vulkan', 'sdcpp-cpu'): raise ValueError('Unknown native video engine')
    if any(type(n) is not int for n in (width, height, frames, fps)):
        raise ValueError('Video dimensions/frame count/fps must be integers')
    if min(width, height) < 128 or max(width, height) > 512 or width%16 or height%16:
        raise ValueError('Small video dimensions must be multiples of 16 from 128 to 512')
    if frames < 5 or frames > 33 or (frames-1)%4 or not 1 <= fps <= 24:
        raise ValueError('Small video needs 5..33 frames of the form 4n+1 and 1..24 fps')
    if width*height*frames > 512*512*17:
        raise ValueError('Video profile pixel/frame budget exceeded; reduce dimensions or frames explicitly')
    hw = hardware or detect_hardware()
    plan = engine_plan(root, hw, engine)
    ram_needed = (18 if plan.get('shared_memory') else 14)*GIB
    if hw['ram_available_bytes'] < ram_needed:
        raise RuntimeError('Wan 1.3B requires 14 GiB available RAM, or 18 GiB with shared GPU memory, after chat unload')
    sizes = dict(SIZES)
    model = WAN
    if variant == 'uncensored':
        sizes.pop(WAN, None)
        model = WAN_ALTERNATE
        sizes[model] = 2838077328
    for path, size in sizes.items():
        p = portable_path(root, path)
        if not p.is_file() or p.stat().st_size != size:
            installer = 'import_media_variants.py' if path == WAN_ALTERNATE else 'import_small_video.py'
            raise RuntimeError('Small video model is missing/incomplete: '+path+'; run Tools/'+installer+' --install')
    return {**plan, 'profile': 'wan13-t2v', 'width': width, 'height': height, 'frames': frames, 'fps': fps,
            'model_variant': variant, 'model_path': model,
            'model_label': 'Wan 1.3B experimental uncensored' if variant == 'uncensored' else 'Wan 1.3B standard',
            'min_free_ram_bytes':3*GIB,
            'reason': 'Wan 1.3B text-to-video; quantized CPU text encoder, CPU VAE, bounded automatic diffusion offloading',
            'limitations': 'Silent text-to-video only. Does not replace image-conditioned video, dialogue or VACE editing.' +
                (' Experimental alternate: publisher warns of weaker general-purpose quality; native inference unvalidated.' if variant == 'uncensored' else '')}


def command(plan, root, prompt, negative, seed, output, steps):
    if plan.get('model_variant') == 'uncensored':
        from academic_policy import NOTICE
        raise ValueError(NOTICE)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
        raise ValueError('Video prompt must contain 1..8000 characters')
    if not isinstance(negative, (str, type(None))) or len(negative or '') > 8000:
        raise ValueError('Invalid negative prompt')
    if '<lora:' in (prompt+' '+(negative or '')).lower():
        raise ValueError('No compatible Wan 1.3B LoRAs are configured')
    if type(seed) is not int or not 0 <= seed < 2**63 or type(steps) is not int or not 1 <= steps <= 30:
        raise ValueError('Video needs a nonnegative 63-bit seed and 1..30 steps')
    backend = 'te=cpu,vae=cpu,diffusion='+plan['device'] if plan['backend']=='vulkan' else 'cpu'
    variant = plan.get('model_variant', 'official')
    if variant not in ('official', 'uncensored'): raise ValueError('Unknown small video model variant')
    model = WAN_ALTERNATE if variant == 'uncensored' else WAN
    if plan.get('model_path', model) != model: raise ValueError('Video model does not match the admitted variant')
    args = [plan['executable'], '-M', 'vid_gen', '--diffusion-model', str(portable_path(root,model)),
            '--t5xxl', str(portable_path(root,T5)), '--vae', str(portable_path(root,VAE)),
            '--backend', backend, '--auto-fit', 'on', '--mmap', '-t', str(min(8,os.cpu_count() or 1)),
            '-p', prompt, '-n', negative or '', '-W', str(plan['width']), '-H', str(plan['height']),
            '--video-frames', str(plan['frames']), '--fps', str(plan['fps']), '--steps', str(steps),
            '--seed', str(seed), '--cfg-scale', '6', '--flow-shift', '3', '--sampling-method', 'euler',
            '--diffusion-fa', '--vae-tiling', '--temporal-tiling', '-o', str(output)]
    if plan['backend']=='vulkan': args += ['--max-vram', f"{plan['device']}={plan['max_vram_gib']}"]
    return args


def validate_video(path, plan, root=ROOT):
    if not 1024 <= path.stat().st_size <= 128*1024**2: raise RuntimeError('Invalid video output size')
    probe = ffmpeg_path(root,True)
    cp = subprocess.run([str(probe), '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,nb_read_frames,r_frame_rate', '-of', 'json', str(path)],
        capture_output=True, timeout=45, check=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    rows = json.loads(cp.stdout)['streams']
    if not rows: raise RuntimeError('Video has no decodable stream')
    row = rows[0]
    if (row['width'],row['height'],int(row['nb_read_frames'])) != (plan['width'],plan['height'],plan['frames']):
        raise RuntimeError('Video output dimensions/frame count differ from the requested profile')
    numerator, denominator = map(int,row['r_frame_rate'].split('/'))
    if denominator <= 0 or numerator != plan['fps']*denominator: raise RuntimeError('Unexpected video frame rate')


def generate(plan, prompt, negative=None, seed=52, steps=20, root=ROOT, timeout=1800):
    def sequence(part):
        intermediate = part.with_suffix('.avi')
        return [command(plan,Path(root),prompt,negative,seed,intermediate,steps),
                [str(ffmpeg_path(root)), '-hide_banner', '-nostdin', '-y',
                 '-i', str(intermediate), '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                 '-movflags', '+faststart', '-threads', '2', str(part)]]
    result = run_generation(plan, sequence,
                            lambda part: validate_video(part,plan,root), root=root,timeout=timeout,kind='video')
    return {**result, 'seed': seed, 'steps': steps, 'frames': plan['frames'], 'fps': plan['fps'], 'audio': False}
