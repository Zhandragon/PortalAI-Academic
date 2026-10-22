#!/usr/bin/env python3
"""Convert a PortableAI local media path into a loopback preview URL."""

from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import json
from pathlib import Path
from urllib.parse import quote

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = _instance_port('preview')

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".opus"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    path = Path(args.path).expanduser().resolve(strict=False)
    encoded = quote(str(path), safe="")
    url = f"http://{args.host}:{args.port}/media?path={encoded}"

    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        markdown = f"![{path.name}]({url})"
        kind = "image"
    elif ext in VIDEO_EXTS:
        markdown = f"[{path.name}]({url})"
        kind = "video"
    elif ext in AUDIO_EXTS:
        markdown = f"[{path.name}]({url})"
        kind = "audio"
    else:
        markdown = f"[{path.name}]({url})"
        kind = "file"

    print(json.dumps({
        "success": True,
        "path": str(path),
        "kind": kind,
        "url": url,
        "markdown": markdown,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
