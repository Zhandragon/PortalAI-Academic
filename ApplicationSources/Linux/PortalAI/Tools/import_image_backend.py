"""Install pinned Windows CPU/Vulkan image engines, reusing existing SD1.5 weights."""
import argparse
import json
from import_foundation_assets import install, ROOT, require_space

REVISION = "f89d9b13d730eabeede7314ce49dacd18d3c90c2"
RELEASE = "master-951-f89d9b1"
ASSETS = [
    {"id": "sdcpp-windows-vulkan", "size": 30117011,
     "sha256": "2c5bed22585ff678ff2c9077f5088d55c2d9c0faa948db7f2e689e1ccea701a9"},
    {"id": "sdcpp-windows-cpu", "size": 17536557,
     "sha256": "7c46bc1f4e89b22af9dd70e8d510dea2167c619676d23d313b83deffcd9b1ecc"},
]
for asset in ASSETS:
    backend = asset["id"].removeprefix("sdcpp-windows-")
    asset.update(revision=REVISION, release=RELEASE, archive="zip", payload=".",
                 dest="Runtime/StableDiffusion/windows-"+backend,
                 url=f"https://github.com/leejet/stable-diffusion.cpp/releases/download/{RELEASE}/sd-master-f89d9b1-bin-win-{backend}-x64.zip")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if args.install:
        for asset in ASSETS:
            print(json.dumps(install(asset)), flush=True)
    else:
        print(json.dumps({"assets": ASSETS, "budget": require_space(ROOT, 6*sum(a["size"] for a in ASSETS))}, indent=2))
