"""Pinned native Wan 1.3B video profile and quantized text encoder."""
import argparse
import json
from import_foundation_assets import install,ROOT,require_space
from import_media_assets import asset

ASSETS=[
    asset('Comfy-Org/Wan_2.1_ComfyUI_repackaged','123acf1cc74bccbb9bfff8ac1ee72edc08c2341d',
          'split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors',2838303560,
          'be531024cd9018cb5b48c40cfbb6a6191645b1c792eb8bf4f8c1c6e10f924dc5',
          'Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors','wan13-t2v'),
    asset('city96/umt5-xxl-encoder-gguf','b535255bee98c2b0a59ea7c0ae2dcd0c6657b3b7',
          'umt5-xxl-encoder-Q4_K_M.gguf',3655145312,
          '17cf97a5bbbc60a646d6105b832b6f657ce904a8a1ad970e4b59df0c67584a40',
          'Generative/ComfyUI_windows_portable/ComfyUI/models/text_encoders/umt5-xxl-encoder-Q4_K_M.gguf','umt5-q4-video'),
]

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--install',action='store_true');args=p.parse_args()
    budget=require_space(ROOT,sum(a['size'] for a in ASSETS if not (ROOT/a['dest']).exists()))
    if args.install:
        for a in ASSETS:print(json.dumps(install(a)),flush=True)
    else:print(json.dumps({'assets':ASSETS,'budget':budget},indent=2))
