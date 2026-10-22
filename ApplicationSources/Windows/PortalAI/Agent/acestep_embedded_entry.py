from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import os
import runpy
import sys
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Agent'))
from profile_paths import capture, private_path
from runtime_policy import portable_env


def profile_api_source(source, root=ROOT):
    """Relocate only private API cache; installed model/code roots stay shared."""
    if capture(root) is None:
        return source
    marker = 'cache_root = os.path.join(project_root, ".cache", "acestep")'
    server = '"acestep.api_server:app"'
    if source.count(marker) != 1 or source.count(server) != 1:
        raise RuntimeError('ACE-Step private cache layout changed; refusing shared-cache startup')
    cache = private_path(root, 'Music/ACE-Step-1.5/.cache/acestep')
    # The upstream CLI passes an import string to uvicorn. Pass this transformed
    # module's app object instead, or uvicorn would import the shared-cache source
    # again and silently undo the private routing.
    return source.replace(marker, 'cache_root = ' + repr(str(cache))).replace(server,'app')


def configure_profile_environment(root=ROOT):
    os.environ.update(portable_env(root))
    if capture(root) is None:
        return
    cache = private_path(root, 'Music/ACE-Step-1.5/.cache/acestep')
    for key, child in [('ACESTEP_TMPDIR','tmp'),('TRITON_CACHE_DIR','triton'),
                       ('TORCHINDUCTOR_CACHE_DIR','torchinductor'),('GRADIO_TEMP_DIR','gradio')]:
        path=cache/child
        path.mkdir(parents=True,exist_ok=True)
        os.environ[key]=str(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=_instance_port('acestep'))
    args = ap.parse_args()

    configure_profile_environment()

    work = Path(args.work).resolve()
    log_path = Path(args.log).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log

    os.chdir(work)
    sys.path.insert(0, str(work))

    print("[PortableAI] ACE-Step direct embedded-Python entry")
    print(f"[PortableAI] cwd={work}")
    print(f"[PortableAI] python={sys.executable}")
    print(f"[PortableAI] API=http://{args.host}:{args.port}")
    print("[PortableAI] start_api_server.bat / uv / .venv intentionally bypassed")

    # PortableAI Windows stability policy:
    #
    # ACE-Step defaults to vLLM for the 5Hz LM on sufficiently large NVIDIA
    # GPUs.  On this Windows stack that path was the last operation recorded
    # before the visible console-process churn.  The official ACE-Step config
    # also supports the native PyTorch backend ("pt"), which preserves the
    # 5Hz language-model features while avoiding the vLLM worker engine.
    #
    # api_server.py loads .env with override=False, so setting the variables
    # here before run_module() reliably wins over ACE-Step's .env defaults.
    os.environ["ACESTEP_LM_BACKEND"] = "pt"
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    print("[PortableAI] ACESTEP_LM_BACKEND=pt (Windows stable mode)")
    print("[PortableAI] TOKENIZERS_PARALLELISM=false")

    # The ACE-Step API CLI reads .env from the project and parses host/port from argv.
    sys.argv = [
        "acestep-api",
        "--host", args.host,
        "--port", str(args.port),
    ]

    try:
        if capture(ROOT) is None:
            runpy.run_module("acestep.api_server", run_name="__main__")
        else:
            entry = work/'acestep/api_server.py'
            source = profile_api_source(entry.read_text(encoding='utf-8'))
            module = types.ModuleType('acestep.api_server')
            module.__file__ = str(entry)
            module.__package__ = 'acestep'
            # FastAPI/Pydantic resolve deferred annotations by module identity.
            # Register the transformed module before defining its model classes.
            sys.modules[module.__name__] = module
            exec(compile(source,str(entry),'exec'),module.__dict__)
            module.main()
    except BaseException:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
