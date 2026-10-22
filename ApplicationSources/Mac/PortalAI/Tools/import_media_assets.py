"""Pinned low-memory media assets; SSD reserves and SHA-256 checked before activation."""
from pathlib import Path
import argparse
import json
from import_foundation_assets import install, require_space, ROOT

SD_REPO = "stable-diffusion-v1-5/stable-diffusion-v1-5"
SD_REV = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"
STT_REPO = "Systran/faster-whisper-base"
STT_REV = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"


def asset(repo, revision, filename, size, sha, destination, identity):
    return dict(id=identity, revision=revision, repository=repo,
                url=f"https://huggingface.co/{repo}/resolve/{revision}/{filename}",
                size=size, sha256=sha, dest=destination)


ASSETS = [
{"id": "sd15-license", "revision": "21f890f9da3cfbeaba8e2ac3c425ee9e998d5229",
     "url": "https://raw.githubusercontent.com/CompVis/stable-diffusion/21f890f9da3cfbeaba8e2ac3c425ee9e998d5229/LICENSE",
     "size": 14385, "sha256": "be351ebe7ac01bcdbb018639aadcfd38f136b7dc3f2a3d4d3a24db51d1b210ef",
     "dest": "Documentation/Models/SD15-License.txt"},
{"id": "whisper-license", "revision": "86098128c0b4f24f0e2aa2994de830614b474227",
     "url": "https://raw.githubusercontent.com/openai/whisper/86098128c0b4f24f0e2aa2994de830614b474227/LICENSE",
     "size": 1063, "sha256": "b5d65a59060e68c4ff940e1eddfa6f94b2d68fdf58ed7f4dd57721c997e35e9d",
     "dest": "SpeechToText/models/whisper-base/LICENSE"},
asset(SD_REPO, SD_REV, "README.md", 14461,
          "2079161f9df7524bd9eca5e53ff5911271b8551e0f868b7b5a92b84776df28a3",
          "Documentation/Models/SD15-Model-Card.md", "sd15-card"),
asset(SD_REPO, SD_REV, "v1-5-pruned-emaonly.safetensors", 4265146304,
          "6ce0161689b3853acaa03779ec93eafe75a02f4ced659bee03f50797806fa2fa",
          "Generative/ComfyUI_windows_portable/ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors", "sd15-checkpoint")
]
for filename, size, sha in [
    ("README.md", 1991, "b922acef3616e27b1d416260b63ba7114c732f0315012006781af2da69cd1ebf"),
    ("config.json", 2309, "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a"),
    ("model.bin", 145217532, "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"),
    ("tokenizer.json", 2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
    ("vocabulary.txt", 459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
]:
    ASSETS.append(asset(STT_REPO, STT_REV, filename, size, sha,
                        "SpeechToText/models/whisper-base/" + filename,
                        "whisper-base-" + filename.replace(".", "-")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    budget = require_space(ROOT, sum(a["size"] for a in ASSETS if not (ROOT/a["dest"]).exists()))
    if not args.install:
        print(json.dumps({"assets": ASSETS, "budget": budget}, indent=2))
        return
    for a in ASSETS:
        print(json.dumps(install(a)), flush=True)


if __name__ == "__main__":
    main()
