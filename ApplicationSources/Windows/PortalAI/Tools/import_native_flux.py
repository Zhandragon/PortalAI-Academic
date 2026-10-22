"""Install pinned Klein 4B CPU/Vulkan assets without replacing existing models."""
import argparse
import json
from import_foundation_assets import ROOT, install, require_space
from import_media_assets import asset

MODELS = 'Generative/ComfyUI_windows_portable/ComfyUI/models/'
ASSETS = [
asset('leejet/FLUX.2-klein-4B-GGUF', '3b1f5a9dc3abb32238b053aeb3d823c30afdacbd',
          'flux-2-klein-4b-Q4_0.gguf', 2460378560,
          'd1023499ef3f2f82ff7c50e6778495195c1b6cc34835741778868428111f9ff4',
          MODELS+'diffusion_models/flux-2-klein-4b-Q4_0.gguf', 'native-flux-klein4'),
asset('leejet/FLUX.2-klein-4B-GGUF', '3b1f5a9dc3abb32238b053aeb3d823c30afdacbd',
          'README.md', 470, '799c1fed644dd6b43780da277423573ac4560dde275bb5727b82763e9a2721c1',
          'Documentation/Models/FLUX-Klein4-GGUF.md', 'flux-klein4-gguf-card')
]


ASSETS.extend([{'id': 'qwen4-q4', 'url': 'https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf', 'size': 2497280256, 'sha256': '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5', 'dest': 'LLM/models/Qwen3-4B-Q4_K_M.gguf'}, {'id': 'native-flux-standard-vae', 'url': 'https://huggingface.co/Comfy-Org/flux2-klein-9B/resolve/3f62d9d8ae1fec33c6e91453d5c712855b096b55/split_files/vae/flux2-vae.safetensors', 'size': 336211292, 'sha256': '868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3', 'dest': 'Generative/ComfyUI_windows_portable/ComfyUI/models/vae/flux2-vae.safetensors'}])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    require_space(ROOT, sum(a['size'] for a in ASSETS if not (ROOT/a['dest']).exists()), for_outputs=True)
    if args.install:
        for entry in ASSETS:
            print(json.dumps(install(entry)), flush=True)
    else:
        print(json.dumps({'assets': ASSETS, 'standard_encoder': 'LLM/models/Qwen3-4B-Q4_K_M.gguf',
                          'vae': MODELS+'vae/flux2-vae.safetensors'}, indent=2))


if __name__ == '__main__':
    main()
