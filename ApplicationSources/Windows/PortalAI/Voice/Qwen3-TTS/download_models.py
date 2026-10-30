from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
MODELS.mkdir(parents=True, exist_ok=True)

# Keep Hugging Face's own cache metadata inside PortableAI during installation.
os.environ.setdefault("HF_HOME", str(ROOT / "hf_cache"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(ROOT / "hf_cache" / "hub"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

REPOS = [
    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
]

for repo in REPOS:
    name = repo.split("/")[-1]
    dest = MODELS / name
    print(f"\n=== Downloading {repo} ===")
    print(f"Destination: {dest}")
    snapshot_download(
        repo_id=repo,
        local_dir=str(dest),
        resume_download=True,
    )

print("\nAll Qwen3-TTS voice models are present locally.")
