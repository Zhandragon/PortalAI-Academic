"""Memory-bounded MMAudio inference with sequential feature/model residency."""
import gc
import json
from pathlib import Path
import subprocess


def video_frames(root,path,duration,size,fps,sync=False):
    """Decode only the requested interval at the final tensor resolution."""
    import numpy as np
    import torch
    from platform_runtime import ffmpeg_path
    count=int(duration*fps)
    scale=(f'scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}' if sync
           else f'scale={size}:{size}:flags=bicubic')
    command=[str(ffmpeg_path(root)),'-v','error','-nostdin','-threads','2','-i',str(path),'-t',str(duration),
             '-vf',f'fps={fps},{scale}','-frames:v',str(count),'-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    # ffmpeg is constrained to count*size*size bytes, independent of source size/duration.
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=90)
    expected=count*size*size*3
    if len(result.stdout)!=expected:raise RuntimeError('Video is shorter than the requested SFX duration or has missing frames')
    tensor=torch.from_numpy(np.frombuffer(result.stdout,dtype=np.uint8).copy().reshape(count,size,size,3))
    tensor=tensor.permute(0,3,1,2).float().div_(255)[None]
    return tensor.mul_(2).sub_(1) if sync else tensor


def generate(args,root,device,dtype):
    import torch
    import open_clip
    import soundfile
    from torchvision.transforms import Normalize
    from mmaudio.eval_utils import all_model_cfg
    from mmaudio.model.utils.features_utils import FeaturesUtils,patch_clip
    from mmaudio.ext.synchformer import Synchformer
    from mmaudio.model.networks import get_my_mmaudio
    from mmaudio.model.flow_matching import FlowMatching
    def clear():
        gc.collect()
        if device!='cpu':torch.cuda.empty_cache()
    def stage(name):print(json.dumps({'stage':name,'device':device}),flush=True)
    config=all_model_cfg[args.variant];config.download_if_needed()
    with torch.inference_mode():
        # Construct only one feature model at a time. FeaturesUtils normally loads
        # CLIP, Synchformer and the audio VAE together with the diffusion network.
        features=FeaturesUtils(enable_conditions=False,mode=config.mode)
        from huggingface_hub import hf_hub_download
        from open_clip.model import CLIP
        repo='apple/DFN5B-CLIP-ViT-H-14-384'
        config_file=hf_hub_download(repo,'open_clip_config.json',local_files_only=True)
        clip_config=json.loads(Path(config_file).read_text())['model_cfg']
        checkpoint=hf_hub_download(repo,'open_clip_pytorch_model.bin',local_files_only=True)
        # No random initialization or duplicate 4 GB state dictionary allocation.
        with torch.device('meta'):clip_model=CLIP(**clip_config)
        weights=torch.load(checkpoint,map_location='cpu',weights_only=True,mmap=True)
        clip_model.load_state_dict(weights,strict=True,assign=True);del weights
        clip_model.attn_mask=torch.full((clip_model.context_length,clip_model.context_length),float('-inf')).triu_(1)
        features.clip_model=patch_clip(clip_model).to(device,dtype).eval();del clip_model
        features.clip_preprocess=Normalize([.48145466,.4578275,.40821073],[.26862954,.26130258,.27577711])
        features.tokenizer=open_clip.get_tokenizer('ViT-H-14-378-quickgelu')
        text=features.encode_text([args.prompt]).cpu();negative=features.encode_text([args.negative_prompt]).cpu()
        clip=sync=None
        if args.video:
            frames=video_frames(root,args.video,args.duration,384,8).to(device,dtype)
            clip=features.encode_video_with_clip(frames,batch_size=1).cpu();del frames
        del features;clear();stage('clip-complete')
        if args.video:
            features=FeaturesUtils(enable_conditions=False,mode=config.mode)
            features.synchformer=Synchformer()
            weights=torch.load(config.synchformer_ckpt,weights_only=True,map_location='cpu',mmap=True)
            features.synchformer.load_state_dict(weights);del weights
            features=features.to(device,dtype).eval()
            frames=video_frames(root,args.video,args.duration,224,25,sync=True).to(device,dtype)
            sync=features.encode_video_with_sync(frames,batch_size=1).cpu()
            del features,frames;clear();stage('synchformer-complete')
        net=get_my_mmaudio(config.model_name)
        weights=torch.load(config.model_path,map_location='cpu',weights_only=True,mmap=True)
        net.load_weights(weights);del weights
        net=net.to(device,dtype).eval()
        seq=config.seq_cfg;seq.duration=args.duration
        net.update_seq_lengths(seq.latent_seq_len,seq.clip_seq_len,seq.sync_seq_len)
        if clip is None:clip=net.get_empty_clip_sequence(1)
        if sync is None:sync=net.get_empty_sync_sequence(1)
        cond=net.preprocess_conditions(clip.to(device,dtype),sync.to(device,dtype),text.to(device,dtype))
        empty=net.get_empty_conditions(1,negative_text_features=negative.to(device,dtype))
        rng=torch.Generator(device=device).manual_seed(args.seed)
        x=torch.randn(1,net.latent_seq_len,net.latent_dim,device=device,dtype=dtype,generator=rng)
        fm=FlowMatching(min_sigma=0,inference_mode='euler',num_steps=args.num_steps)
        result=fm.to_data(lambda t,value:net.ode_wrapper(t,value,cond,empty,args.cfg_strength),x)
        latent=net.unnormalize(result).cpu()
        del net,x
        del cond,empty,result,clip,sync,text,negative
        clear();stage('diffusion-complete')
        decoder=FeaturesUtils(tod_vae_ckpt=config.vae_path,bigvgan_vocoder_ckpt=config.bigvgan_16k_path,
                              enable_conditions=False,mode=config.mode,need_vae_encoder=False).to(device,dtype).eval()
        audio=decoder.vocode(decoder.decode(latent.to(device,dtype))).float().cpu()[0]
        if not torch.isfinite(audio).all():raise RuntimeError('Generated SFX contains non-finite samples')
        soundfile.write(args.portalai_output,audio.numpy().T,seq.sampling_rate,format='FLAC',subtype='PCM_16')
        stage('audio-complete')
