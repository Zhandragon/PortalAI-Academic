"""Chat effort preferences and admission, without launching or reconfiguring models.

Capability previews use total capacity, not current free memory. They are advisory:
the lifecycle owner must reclaim its chat server and call require_chat_plan again
before applying a model. An unlocked slow profile never relaxes admission checks.
"""
from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import copy
import json
import os
from pathlib import Path

import runtime_policy as runtime
from chat_budgets import generation_options

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("fast", "balanced", "deep")
_TOOL_ROUNDS = {"fast": 4, "balanced": 12, "deep": 24}


def _level(value: str) -> str:
    if not isinstance(value, str) or value.lower() not in LEVELS:
        raise ValueError("Effort must be fast, balanced or deep")
    return value.lower()


def load_preferences(root: Path = ROOT) -> dict:
    """Missing/new preference keys have defaults; never rewrite existing policy."""
    from profile_paths import enabled, private_path
    root = Path(root)
    if enabled(root):
        path = private_path(root, 'Data/Chat/effort.json')
        try:
            if path.stat().st_size > 16384: raise ValueError('Effort preferences exceed the bounded size')
            saved = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            saved = {}
        except json.JSONDecodeError:
            saved = {}
    else:
        saved = runtime.load_policy(root).get("effort", {})
    if not isinstance(saved, dict):
        saved = {}
    result = {key: saved[key] if saved.get(key) in LEVELS else "balanced"
              for key in ("chat", "tools")}
    from chat_selection import tier_for_model
    tier = tier_for_model(runtime.load_effective_policy(root).get('selection'))
    if tier: result['chat'] = tier
    return result


def save_preferences(root: Path = ROOT, *, chat: str | None = None,
                     tools: str | None = None) -> dict:
    """Merge only the supplied preferences; session permission is never stored."""
    changes = {key: _level(value) for key, value in (("chat", chat), ("tools", tools))
               if value is not None}
    root = Path(root)
    from profile_paths import enabled, capture, private_path
    if enabled(root):
        context = capture(root)
        saved = load_preferences(root)
        if changes:
            path = private_path(root, 'Data/Chat/effort.json', context=context)
            runtime.atomic_json(path, {**saved, **changes})
        return load_preferences(root)
    policy = runtime.load_policy(root)
    saved = policy.get("effort", {})
    if not isinstance(saved, dict):
        saved = {}
    if changes:
        policy["effort"] = {**saved, **changes}
        runtime.atomic_json(root / "Agent/hardware_profiles.json", policy)
    return load_preferences(root)


def _slow_hardware(backend: dict) -> bool:
    gpu = backend.get("gpu") or {}
    return (backend.get("backend") == "cpu" or not gpu or
            gpu.get("shared_memory", False) or
            int(gpu.get("total_bytes", 0)) < 16 * runtime.GIB)


def _base(level: str, backend: dict, session_unlocked: bool) -> dict:
    slow = level == "deep" and _slow_hardware(backend)
    warning = ("Deep can be very slow on CPU, integrated/shared graphics, or smaller GPUs. "
               "Allow it for this session to continue; memory and storage limits still apply.") if slow else ""
    return {"level": level, "label": level.title(), "available": True,
            "locked": slow and not session_unlocked,
            "can_apply": not slow or bool(session_unlocked),
            "warning": warning, "reason": warning if slow and not session_unlocked else "",
            "backend": backend, "slow_hardware": slow,
            "requires_recheck": True}


def check_chat_permission(level: str, root: Path = ROOT, *, session_unlocked: bool = False,
                          hardware: dict | None = None, policy: dict | None = None,
                          probe: bool = True, require_vision: bool = False) -> dict:
    """Check the slow-hardware session gate before disrupting a running model.

    This deliberately does not admit a model using free memory. The lifecycle owner
    must still call require_chat_plan after reclaiming its owned chat memory.
    """
    level = _level(level)
    root = Path(root).resolve()
    cfg = policy if policy is not None else runtime.load_effective_policy(root)
    hw = hardware if hardware is not None else runtime.detect_hardware()
    backend = runtime.choose_backend(root, hw, cfg.get("backend", "auto"), probe)
    result = _base(level, backend, session_unlocked)
    result['model_preference'] = _model_preference(cfg)
    result['vision_request'] = require_vision
    if require_vision:
        from chat_vision_policy import candidates
        result['model_preference'] = {'explicit': None, 'automatic': list(candidates(level, cfg))}
    result['policy_signature'] = chat_policy_signature(cfg)
    if result["locked"]:
        raise RuntimeError(result["reason"])
    return result


def _model_preference(cfg):
    explicit = cfg.get('selection', 'auto')
    if explicit == 'auto': explicit = None
    return {'explicit': explicit,
            'automatic': [m['id'] for m in runtime.automatic_models(cfg)]}


def chat_policy_signature(cfg):
    """Only settings that affect the loaded chat model; exclude media/storage."""
    return {'selection': cfg.get('selection', 'auto'), 'backend': cfg.get('backend', 'auto'),
            'vision_runtime_revision': runtime.SMALL_VISION_RUNTIME_REVISION,
            'variant_preference': cfg.get('variant_preference', 'standard'),
            'vision_routing': cfg.get('vision_routing', 'off'),
            'profile_id': cfg.get('_profile_id'),
            'context_tokens': int(cfg.get('context_tokens', 8192)),
            'models': copy.deepcopy(cfg.get('models', []))}


def _model_for(level: str, root: Path, hardware: dict, backend: dict, cfg: dict) -> dict:
    cfg = copy.deepcopy(cfg)
    if _model_preference(cfg)['explicit']:
        # Every explicit model choice is pinned, including standard models.
        # UI size changes save a new explicit pair; admission never overrides it.
        if level == 'fast': cfg['context_tokens'] = min(int(cfg.get('context_tokens', 8192)), 8192)
        return runtime.select_model(root, hardware, backend, cfg)['selected']
    # Variant preference is independent of effort; unknown manual-only models stay excluded.
    standard = ('qwen1.7-q8', 'qwen4-q4') if level == 'fast' else ('qwen4-q4', 'qwen1.7-q8') if level == 'balanced' else (
        'qwen27-standard-q4', 'qwen4-q4', 'qwen1.7-q8')
    alternate = ('qwen1.7-abliterated-q8', 'qwen4-abliterated-q4') if level == 'fast' else ('qwen4-abliterated-q4', 'qwen1.7-abliterated-q8') if level == 'balanced' else (
        'qwen27-q4', 'qwen27-q5', 'qwen4-abliterated-q4', 'qwen1.7-abliterated-q8')
    eligible = {m['id'] for m in runtime.automatic_models(cfg)}
    wanted = tuple(m for m in ((alternate + standard) if cfg.get('variant_preference') == 'uncensored'
                              else standard) if m in eligible)
    requested = int(cfg.get("context_tokens", 8192))
    if not 512 <= requested <= 32768:
        raise ValueError("context_tokens must be between 512 and 32768")
    if level == "fast":
        requested = min(requested, 8192)
    contexts = [requested] + [size for size in (8192, 4096, 2048) if size < requested]
    failures = []
    for model_id in wanted:
        for context in contexts:
            candidate = {**cfg, "selection": model_id, "context_tokens": context}
            try:
                selected = runtime.select_model(root, hardware, backend, candidate)['selected']
                preferred = cfg.get('variant_preference', 'standard')
                selected['variant_reason'] = ('Saved ' + preferred + ' preference' if runtime.model_variant(selected) == preferred
                    else 'Standard fallback: no installed uncensored model fits current hardware')
                return selected
            except RuntimeError as exc:
                failures.append(str(exc))
    raise RuntimeError("No installed model fits this effort profile and memory reserves. " +
                       (failures[-1] if failures else "No matching model is configured."))


def _plan(level: str, root: Path, hw: dict, cfg: dict, backend: dict,
          session_unlocked: bool, *, preview: bool, require_vision: bool = False) -> dict:
    result = _base(level, backend, session_unlocked)
    result['policy_signature'] = chat_policy_signature(cfg)
    # Running an installed model may consume reserved output space, but cannot
    # cross the free-space floor. No new weights are downloaded by this policy.
    storage = runtime.storage_budget(root, cfg, for_outputs=True)
    if not storage["allowed"]:
        raise RuntimeError("SSD free-space floor would be crossed; free space before running chat")
    if require_vision:
        from chat_vision_policy import select
        model = select(level, root, hw, backend, cfg)
    else:
        model = _model_for(level, root, hw, backend, cfg)
    result['vision_request'] = require_vision
    context = int(model["context_tokens"])
    round_limit = _TOOL_ROUNDS[level]
    options = generation_options(level, context)
    max_tokens = options['max_tokens']
    thinking = level != 'fast'
    template = options['chat_template_kwargs']
    model = {**model, "label": model.get("label") or Path(model["path"]).stem}
    result.update(selection=model["id"], model=model, context_tokens=context,
                  thinking=thinking, chat_template_kwargs=template,
                  max_tokens=max_tokens, max_tool_rounds=round_limit,
                  tool_round_limit=round_limit, input_token_reserve=context - max_tokens,
                  completion_options=options,
                  policy_overrides={"selection": model["id"], "context_tokens": context},
                  storage=storage, requires_recheck=preview, preview_only=preview)
    command = [backend["executable"], "-m", model["absolute_path"], "-ngl", str(model["gpu_layers"]),
               "-c", str(context), "--parallel", "1", "--jinja", "--metrics",
               "--sleep-idle-seconds", "300", "--host", "127.0.0.1", "--port", str(_instance_port('qwen')),
               "--device", backend["device"]]
    if model["absolute_projector"]:
        command += ["--mmproj", model["absolute_projector"], "--no-mmproj-offload"]
        command += runtime.small_vision_command_options(model)
    result["command"] = command
    if preview:
        result["admission_note"] = "Capacity preview; free memory and backend are checked again before loading."
    return result


def capabilities(root: Path = ROOT, *, hardware: dict | None = None,
                 policy: dict | None = None, probe: bool = True,
                 session_unlocked: bool = False, size_choices: bool = False,
                 require_vision: bool = False) -> dict:
    """Advisory slider choices, keeping current resident chat out of the estimate.

    Total memory is a capacity ceiling, never authorization to allocate it. This
    avoids assuming ownership of other processes or falsely downgrading while our
    model is resident. All choices require fresh admission after an owned unload.
    """
    root = Path(root).resolve()
    hw = hardware if hardware is not None else runtime.detect_hardware()
    cfg = policy if policy is not None else runtime.load_effective_policy(root)
    profiles = {}
    from voice_policy import capabilities as voice_capabilities
    voice = voice_capabilities(root, hw, probe=probe)
    try:
        backend = runtime.choose_backend(root, hw, cfg.get("backend", "auto"), probe)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"hardware": hw, "voice": voice, "profiles": {
            level: {"level": level, "label": level.title(), "available": False,
                    "locked": False, "can_apply": False, "warning": "", "reason": str(exc),
                    "requires_recheck": True, "preview_only": True} for level in LEVELS}}
    capacity = copy.deepcopy(hw)
    capacity["ram_available_bytes"] = int(hw["ram_total_bytes"])
    capacity_backend = copy.deepcopy(backend)
    if capacity_backend.get("gpu"):
        gpu = capacity_backend["gpu"]
        gpu["free_bytes"] = int(gpu.get("total_bytes", gpu.get("free_bytes", 0)))
    for level in LEVELS:
        try:
            profile_cfg = cfg
            if size_choices:
                from chat_selection import choice_changes
                profile_cfg = {**cfg, **choice_changes(root, cfg, level=level)}
            profiles[level] = _plan(level, root, capacity, profile_cfg, capacity_backend,
                                    session_unlocked, preview=True, require_vision=require_vision)
        except (OSError, ValueError, RuntimeError) as exc:
            profiles[level] = {**_base(level, backend, session_unlocked), "available": False,
                               "can_apply": False, "reason": str(exc), "preview_only": True}
    return {"hardware": hw, "profiles": profiles, "voice": voice, "preview_only": True,
            "requires_recheck": True}


def require_chat_plan(level: str, root: Path = ROOT, *, session_unlocked: bool = False,
                      hardware: dict | None = None, policy: dict | None = None,
                      probe: bool = True, require_vision: bool = False) -> dict:
    """Admit against free RAM/VRAM now; call only after owned memory reclamation."""
    level = _level(level)
    root = Path(root).resolve()
    cfg = policy if policy is not None else runtime.load_effective_policy(root)
    hw = hardware if hardware is not None else runtime.detect_hardware()
    backend = runtime.choose_backend(root, hw, cfg.get("backend", "auto"), probe)
    result = _base(level, backend, session_unlocked)
    if result["locked"]:
        raise RuntimeError(result["reason"])
    return _plan(level, root, hw, cfg, backend, session_unlocked, preview=False, require_vision=require_vision)


def tool_preferences(level: str = "balanced") -> dict:
    """Describe separate opt-in tool defaults, not an execution plan.

    These hints do not change dimensions, duration, scientific tolerances or
    hardware routing. Each adapter must enforce its own supported settings and
    admission. Chat effort never changes this preference implicitly.
    """
    level = _level(level)
    return {"level": level, "quality": level,
            "image_steps_by_profile": {"sd15": {"fast": 12, "balanced": 20, "deep": 30}[level],
                                       "flux": None},
            "supported_defaults": {command: {key: values[LEVELS.index(level)]
                                             for key, values in settings.items()}
                                   for command, settings in _TOOL_DEFAULTS.items()},
            "applied": False, "requires_adapter_support": True,
            "requires_hardware_admission": True}


_TOOL_DEFAULTS = {
    "video-small": {"steps": (12, 20, 30)},
    "sfx": {"steps": (12, 25, 40)},
    "video-sfx": {"steps": (12, 25, 40)},
    "transcribe": {"beam_size": (1, 5, 8)},
}


def apply_tool_effort(command: str, args: dict, level: str, *, explicit_options=None,
                      root: Path = ROOT, hardware: dict | None = None,
                      session_unlocked: bool = False, policy: dict | None = None,
                      probe: bool = True) -> dict:
    """Return defaults for supported tools; never overwrite an explicit option.

    If explicit_options is omitted, existing dictionary keys are explicit. The
    CLI supplies its raw flag names because argparse fills in absent defaults.
    Science requests, durations, dimensions, voices and model routes are untouched.
    This does not replace the tool's post-handoff memory/compute admission.
    """
    level = _level(level)
    result = copy.deepcopy(args)
    choices = _TOOL_DEFAULTS.get(str(command), {})
    if not choices or level == "balanced":
        return result
    supplied = set(explicit_options) if explicit_options is not None else {
        "--" + key.replace("_", "-") for key in args}
    updates = {key: values[LEVELS.index(level)] for key, values in choices.items()
               if not any(("--" + key.replace("_", "-")).startswith(flag)
                          for flag in supplied)}
    if updates and level == "deep":
        check_chat_permission("deep", root, session_unlocked=session_unlocked,
                              hardware=hardware, policy=policy, probe=probe)
    result.update(updates)
    return result


def apply_tool_environment(args: dict, argv: list[str], *, root: Path = ROOT,
                           environ: dict | None = None) -> dict:
    """Consume the GUI's captured request effort; standalone CLI keeps its defaults."""
    env = os.environ if environ is None else environ
    if "PORTALAI_TOOL_EFFORT" not in env or str(args.get("cmd", "")) not in _TOOL_DEFAULTS:
        return copy.deepcopy(args)
    # Stop at --, after which option-looking strings are positional user text.
    flags = set()
    for value in argv:
        if value == "--":
            break
        if value.startswith("--"):
            flags.add(value.split("=", 1)[0])
    return apply_tool_effort(str(args.get("cmd", "")), args, env["PORTALAI_TOOL_EFFORT"],
                             explicit_options=flags, root=root,
                             session_unlocked=env.get("PORTALAI_TOOL_EFFORT_UNLOCKED") == "1")


def image_steps(profile: str, explicit: int | None = None, environ: dict | None = None, *,
                root: Path = ROOT, hardware: dict | None = None, policy: dict | None = None,
                probe: bool = True) -> int | None:
    """SD1.5-only sampling effort; distilled FLUX keeps its own workflow settings."""
    if explicit is not None and (type(explicit) is not int or not 1 <= explicit <= 50):
        raise ValueError("Image steps must be an integer between 1 and 50")
    if profile == 'klein4':
        return 4 if explicit is None else explicit
    if profile == "flux":
        if explicit is not None:
            raise ValueError("--steps currently supports the SD1.5 image profile only; FLUX uses its workflow settings")
        return None
    if profile != "sd15":
        raise ValueError("Resolve the image hardware profile before choosing steps")
    if explicit is not None:
        return explicit
    env = os.environ if environ is None else environ
    level = _level(env.get("PORTALAI_TOOL_EFFORT", "balanced"))
    if level == "deep":
        check_chat_permission(level, root, session_unlocked=env.get("PORTALAI_TOOL_EFFORT_UNLOCKED") == "1",
                              hardware=hardware, policy=policy, probe=probe)
    return {"fast": 12, "balanced": 20, "deep": 30}[level]


def sd15_workflow_steps(workflow: dict, steps: int) -> dict:
    """Return a changed copy of the known single-KSampler SD1.5 workflow."""
    if type(steps) is not int or not 1 <= steps <= 50:
        raise ValueError("Image steps must be an integer between 1 and 50")
    result = copy.deepcopy(workflow)
    samplers = [node for node in result.values() if isinstance(node, dict) and node.get("class_type") == "KSampler"]
    if len(samplers) != 1 or not isinstance(samplers[0].get("inputs"), dict):
        raise RuntimeError("SD1.5 workflow must have exactly one supported KSampler")
    samplers[0]["inputs"]["steps"] = steps
    return result
