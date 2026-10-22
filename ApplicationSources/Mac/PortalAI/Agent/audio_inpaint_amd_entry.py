"""Offline, isolated audio-native inpainting; entered only by the bounded worker."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Agent'))
import argparse
import copy
import gc
import json
import os


def mmaudio(args):
    from mmaudio_amd_entry import activate, configure_offline
    activate(); os.chdir(ROOT / 'Services/MMAudio'); configure_offline()
    import torch
    import open_clip
    import soundfile
    from open_clip.model import CLIP
    from huggingface_hub import hf_hub_download
    from mmaudio.eval_utils import all_model_cfg
    from mmaudio.model.utils.features_utils import FeaturesUtils, patch_clip
    from mmaudio.model.networks import get_my_mmaudio
    from audio_inpaint_math import masked_euler, mask_span
    if os.name == 'nt' and not torch.version.hip:
        raise RuntimeError('Windows scaled audio requires isolated ROCm Torch')
    if args.cpu_validation:
        device, dtype = 'cpu', torch.float32
    else:
        if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
            raise RuntimeError('Audio inpainting requires a compute-probed BF16 device')
        device, dtype = 'cuda', torch.bfloat16
    torch.set_num_threads(2)
    config = all_model_cfg['small_44k']; config.download_if_needed()
    seq = copy.copy(config.seq_cfg); seq.duration = args.duration
    def clear(stage):
        gc.collect()
        if device != 'cpu': torch.cuda.empty_cache()
        print(json.dumps({'stage': stage, 'device': device}), flush=True)
    with torch.inference_mode():
        feature = FeaturesUtils(enable_conditions=False, mode=config.mode)
        repo = 'apple/DFN5B-CLIP-ViT-H-14-384'
        config_path = hf_hub_download(repo, 'open_clip_config.json', local_files_only=True)
        checkpoint = hf_hub_download(repo, 'open_clip_pytorch_model.bin', local_files_only=True)
        with torch.device('meta'): model = CLIP(**json.loads(Path(config_path).read_text())['model_cfg'])
        weights = torch.load(checkpoint, map_location='cpu', weights_only=True, mmap=True)
        model.load_state_dict(weights, strict=True, assign=True); del weights
        model.attn_mask = torch.full((model.context_length, model.context_length), float('-inf')).triu_(1)
        feature.clip_model = patch_clip(model).to(device, dtype).eval(); del model
        feature.tokenizer = open_clip.get_tokenizer('ViT-H-14-378-quickgelu')
        text = feature.encode_text([args.prompt]).cpu()
        negative = feature.encode_text(['music, speech, vocals']).cpu()
        del feature; clear('text-complete')
        audio, rate = soundfile.read(str(args.source), dtype='float32', always_2d=True)
        if rate != 44100 or len(audio) != round(args.duration * rate):
            raise ValueError('Prepared source window has wrong rate or length')
        waveform = torch.from_numpy(audio.mean(axis=1)).to(device, dtype)
        # The target region is not evidence: remove it before encoding context.
        waveform[round(args.start*rate):round(args.end*rate)] = 0
        waveform = torch.nn.functional.pad(waveform, (0, seq.num_audio_frames-len(waveform)))[None]
        encoder = FeaturesUtils(tod_vae_ckpt=config.vae_path, bigvgan_vocoder_ckpt=config.bigvgan_16k_path,
                                enable_conditions=False, mode=config.mode, need_vae_encoder=True).to(device,dtype).eval()
        known = encoder.encode_audio(waveform).mode().transpose(1,2).cpu()
        del encoder, waveform, audio; clear('source-encoded')
        net = get_my_mmaudio(config.model_name)
        weights = torch.load(config.model_path, map_location='cpu', weights_only=True, mmap=True)
        net.load_weights(weights); del weights
        net = net.to(device,dtype).eval(); net.update_seq_lengths(seq.latent_seq_len,seq.clip_seq_len,seq.sync_seq_len)
        if known.shape[1:] != (seq.latent_seq_len, net.latent_dim):
            raise RuntimeError('Source audio encoder/flow latent shape differs')
        known = net.normalize(known.to(device,dtype))
        cond = net.preprocess_conditions(net.get_empty_clip_sequence(1),net.get_empty_sync_sequence(1),text.to(device,dtype))
        empty = net.get_empty_conditions(1,negative_text_features=negative.to(device,dtype))
        rng = torch.Generator(device=device).manual_seed(args.seed)
        noise = torch.randn(known.shape,device=device,dtype=dtype,generator=rng)
        keep = torch.ones_like(known)
        left,right = mask_span(args.start,args.end,rate,1024,seq.latent_seq_len,args.expand)
        keep[:,left:right] = 0
        result = masked_euler(lambda t,x:net.ode_wrapper(t,x,cond,empty,4.5),noise,known,keep,args.steps)
        latent = net.unnormalize(result).cpu()
        del net,noise,known,keep,cond,empty,result,text,negative; clear('masked-flow-complete')
        decoder = FeaturesUtils(tod_vae_ckpt=config.vae_path,bigvgan_vocoder_ckpt=config.bigvgan_16k_path,
                                enable_conditions=False,mode=config.mode,need_vae_encoder=False).to(device,dtype).eval()
        result = decoder.vocode(decoder.decode(latent.to(device,dtype))).float().cpu()[0]
        result = result[..., :round(args.duration*rate)]
        if not torch.isfinite(result).all(): raise RuntimeError('Non-finite audio output')
        soundfile.write(str(args.output),result.numpy().T,rate,format='FLAC',subtype='PCM_16')


def music(args):
    from acestep_amd_entry import activate, import_api
    activate()
    import torch
    import soundfile
    if args.cpu_validation: raise RuntimeError('Music repaint has no CPU-validation generation mode')
    if os.name=='nt' and not torch.version.hip: raise RuntimeError('Windows music repaint requires ROCm')
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported(): raise RuntimeError('Music repaint needs BF16 compute')
    Handler,Params,Config,generate=import_api()
    handler=Handler()
    message,ok=handler.initialize_service(project_root=str(ROOT/'Music/ACE-Step-1.5'),config_path='acestep-v15-turbo',
        device='cuda',use_flash_attention=False,compile_model=False,offload_to_cpu=True,offload_dit_to_cpu=True,
        quantization=None,use_mlx_dit=False)
    if not ok: raise RuntimeError('Music repaint initialization failed: '+message)
    params=music_params(Params,args)
    result=generate(handler,None,params,Config(batch_size=1,allow_lm_batch=False,use_random_seed=False,
                    seeds=[args.seed],audio_format='flac'),save_dir=None)
    if not result.success or len(result.audios)!=1: raise RuntimeError('Music repaint failed: '+str(result.error))
    item=result.audios[0];audio=item['tensor'].detach().float().cpu()
    if audio.ndim!=2 or audio.shape[0] not in (1,2) or not torch.isfinite(audio).all(): raise RuntimeError('Invalid repaint audio')
    soundfile.write(str(args.output),audio.numpy().T,int(item['sample_rate']),format='FLAC',subtype='PCM_16')


def music_params(Params,args):
    return Params(task_type='repaint',src_audio=str(args.source),caption=args.prompt,lyrics='',duration=args.duration,
                  repainting_start=args.start,repainting_end=args.end,seed=args.seed,inference_steps=8,
                  thinking=False,use_cot_metas=False,use_cot_caption=False,use_cot_language=False,
                  enable_normalization=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--prompt',required=True);p.add_argument('--mode',choices=['general','music'],required=True)
    p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True)
    p.add_argument('--duration',type=float,required=True);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--expand',type=int,default=8);p.add_argument('--steps',type=int,default=25)
    p.add_argument('--cpu-validation',action='store_true');args=p.parse_args()
    from media_paths import media_reference
    from profile_paths import private_path
    args.source=media_reference(ROOT,args.source);args.output=args.output.resolve()
    folder=private_path(ROOT,'Outputs/Music' if args.mode=='music' else 'Outputs/SFX')
    if not args.output.is_relative_to(folder) or args.output.suffix!='.flac': raise ValueError('Invalid staged output')
    limit=30 if args.mode=='music' else 8
    if not 1<=args.duration<=limit or not 0<=args.start<args.end<=args.duration: raise ValueError('Invalid bounded interval')
    if not args.source.is_file() or args.source.stat().st_size>12*1024**2: raise ValueError('Prepared window too large')
    (music if args.mode=='music' else mmaudio)(args)


if __name__=='__main__': main()
