from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from media_paths import media_reference, media_output


def main() -> int:
    parser = argparse.ArgumentParser(description="PortableAI one-process MMAudio batch worker")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args()

    request_path = media_reference(ROOT,args.request)
    response_path = media_output(ROOT,args.response)
    response_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import torch
        import torchaudio
        from mmaudio.eval_utils import ModelConfig, all_model_cfg, generate, load_video
        from mmaudio.model.flow_matching import FlowMatching
        from mmaudio.model.networks import MMAudio, get_my_mmaudio
        from mmaudio.model.utils.features_utils import FeaturesUtils

        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

        request = json.loads(request_path.read_text(encoding="utf-8"))
        jobs = request.get("jobs") or []
        if not jobs:
            raise ValueError("MMAudio request contained no jobs.")
        variant = str(request.get("variant") or "large_44k_v2")
        if variant not in all_model_cfg:
            raise ValueError(f"Unknown MMAudio model variant: {variant}")
        if not torch.cuda.is_available():
            raise RuntimeError(
                "MMAudio CUDA is unavailable in its isolated environment. Re-run the installer and verify the NVIDIA driver."
            )

        device = "cuda"
        dtype = torch.bfloat16
        model: ModelConfig = all_model_cfg[variant]
        model.download_if_needed()
        seq_cfg = model.seq_cfg

        net: MMAudio = get_my_mmaudio(model.model_name).to(device, dtype).eval()
        net.load_weights(torch.load(model.model_path, map_location=device, weights_only=True))
        feature_utils = FeaturesUtils(
            tod_vae_ckpt=model.vae_path,
            synchformer_ckpt=model.synchformer_ckpt,
            enable_conditions=True,
            mode=model.mode,
            bigvgan_vocoder_ckpt=model.bigvgan_16k_path,
            need_vae_encoder=False,
        ).to(device, dtype).eval()

        results = []
        with torch.inference_mode():
            for index, job in enumerate(jobs):
                prompt = str(job.get("prompt") or "")
                negative_prompt = str(job.get("negative_prompt") or "")
                duration = float(job.get("duration") or 8.0)
                seed = int(job.get("seed") or 42)
                num_steps = int(job.get("num_steps") or 25)
                cfg_strength = float(job.get("cfg_strength") or 4.5)
                output = media_output(ROOT,str(job["output"]))
                output.parent.mkdir(parents=True, exist_ok=True)

                video_value = job.get("video")
                if video_value:
                    video_path = media_reference(ROOT,str(video_value))
                    if not video_path.is_file():
                        raise FileNotFoundError(video_path)
                    video_info = load_video(video_path, duration)
                    clip_frames = video_info.clip_frames.unsqueeze(0)
                    sync_frames = video_info.sync_frames.unsqueeze(0)
                    duration = float(video_info.duration_sec)
                else:
                    video_path = None
                    clip_frames = None
                    sync_frames = None

                seq_cfg.duration = duration
                net.update_seq_lengths(seq_cfg.latent_seq_len, seq_cfg.clip_seq_len, seq_cfg.sync_seq_len)
                rng = torch.Generator(device=device)
                rng.manual_seed(seed)
                flow_matching = FlowMatching(
                    min_sigma=0, inference_mode="euler", num_steps=num_steps
                )
                audios = generate(
                    clip_frames,
                    sync_frames,
                    [prompt],
                    negative_text=[negative_prompt],
                    feature_utils=feature_utils,
                    net=net,
                    fm=flow_matching,
                    rng=rng,
                    cfg_strength=cfg_strength,
                )
                audio = audios.float().cpu()[0]
                torchaudio.save(str(output), audio, seq_cfg.sampling_rate)
                results.append({
                    "index": index,
                    "output": str(output),
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "duration": duration,
                    "seed": seed,
                    "video": str(video_path) if video_path else None,
                })

        payload = {
            "success": True,
            "backend": "MMAudio",
            "variant": variant,
            "sample_rate": int(seq_cfg.sampling_rate),
            "jobs": results,
            "max_cuda_memory_gb": round(torch.cuda.max_memory_allocated() / (2**30), 3),
        }
        response_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        payload = {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        response_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(payload["traceback"], flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
