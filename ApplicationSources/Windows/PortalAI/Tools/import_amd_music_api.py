"""API imports matching the installed ACE-Step source; isolated from CUDA."""
from import_amd_audio import main

PINS = {'diffusers':'0.36.0', 'transformers':'4.57.6', 'huggingface_hub':'0.36.1',
        'frozendict':'2.4.7', 'importlib_metadata':'8.7.1', 'zipp':'3.23.0',
        'peft':'0.18.1'}

if __name__ == '__main__':
    main(prefix='amd-music-api', pins=PINS, relative_dest='Runtime/AMDMusic/api-packages')
