"""Pinned small MMAudio model, sharing existing VAE/CLIP/Synchformer weights."""
from import_foundation_assets import install
from import_media_assets import asset
import json

ASSET = asset('hkchengrex/MMAudio','eb13a1a98fdbec91753775c57b074ccdfc60587c',
              'weights/mmaudio_small_44k.pth',629946624,
              '11fd92e860a58f0fac972706dd06034e49dceff2e1450bbde5703785c812b0f1',
              'Services/MMAudio/weights/mmaudio_small_44k.pth','mmaudio-small-44k')

if __name__=='__main__': print(json.dumps(install(ASSET)))
