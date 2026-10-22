"""Pinned Python 3.12 music extras, verified using published wheel hashes."""
from import_amd_audio import main

PINS = {'loguru':'0.7.3', 'win32_setctime':'1.2.0',
        'vector_quantize_pytorch':'1.27.20', 'einx':'0.3.0',
        'numba':'0.63.1', 'llvmlite':'0.46.0'}

if __name__ == '__main__':
    main(prefix='amd-music', pins=PINS, relative_dest='Runtime/AMDMusic/packages')
