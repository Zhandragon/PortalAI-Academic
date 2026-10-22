from __future__ import annotations
from pathlib import Path
import json, sys, urllib.request, urllib.error, urllib.parse, mimetypes, uuid, time, os, shutil

def bridge_dir() -> Path:
    return Path(__file__).resolve().parent

def root_dir() -> Path:
    # Agent\*.py -> PortableAI root after package is copied into PortableAI\Agent
    return bridge_dir().parent

def load_config() -> dict:
    with open(bridge_dir() / "config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    from instance_runtime import url
    for key, service in (('comfy','comfyui'),('acestep','acestep'),('llm','qwen')):
        if key in config: config[key]['base_url'] = url(service, '/v1' if key == 'llm' else '')
    return config

def resolve_root(rel: str) -> Path:
    from media_paths import media_reference
    from profile_paths import capture
    if capture(root_dir()) is not None:
        return media_reference(root_dir(), rel)
    p = Path(rel)
    return p if p.is_absolute() else root_dir() / p

def emit(obj: dict, exit_code: int = 0):
    # Tool JSON must survive redirected Windows pipes under legacy codepages.
    # ASCII escapes round-trip through json.loads without losing Unicode text.
    print(json.dumps(obj, ensure_ascii=True, indent=2))
    raise SystemExit(exit_code)

def http_json(method: str, url: str, payload=None, timeout=60):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not connect to {url}: {e}") from e

def multipart_upload(url: str, file_path: Path, field_name="image", extra=None, timeout=120):
    boundary = "----PortableAIBridge" + uuid.uuid4().hex
    crlf = b"\r\n"
    chunks = []
    def add_field(name, value):
        chunks.extend([
            f"--{boundary}".encode(), crlf,
            f'Content-Disposition: form-data; name="{name}"'.encode(), crlf, crlf,
            str(value).encode("utf-8"), crlf
        ])
    for k, v in (extra or {}).items():
        add_field(k, v)
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend([
        f"--{boundary}".encode(), crlf,
        f'Content-Disposition: form-data; name="{field_name}"; filename="{file_path.name}"'.encode(), crlf,
        f"Content-Type: {mime}".encode(), crlf, crlf,
        file_path.read_bytes(), crlf,
        f"--{boundary}--".encode(), crlf
    ])
    body = b"".join(chunks)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Upload failed HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}") from e
