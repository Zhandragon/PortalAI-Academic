"""Apply chat effort between requests with owned, generation-fenced model recovery."""
from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import json
import math
import os
from pathlib import Path
import shlex
import re
import subprocess
import time
import urllib.request
import uuid

import service_manager as service
from runtime_policy import ROOT, atomic_json, portable_env, require_space


class PreparationCancelled(RuntimeError):
    pass


def _guard(root, requested_at, cancel_event=None, state=None):
    if cancel_event is not None and cancel_event.is_set():
        raise PreparationCancelled('Chat preparation cancelled')
    generation = service._read_qwen_generation() or {}
    if generation.get('reason') == 'explicit-stop' and generation.get('stopped_at', 0) >= requested_at:
        raise PreparationCancelled('Model preparation cancelled by Stop')
    for name in ('qwen_last_stop.json', 'native_startup_state.json'):
        path = root / 'Agent/.runtime' / name
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('stopped_at', 0) >= requested_at:
                raise PreparationCancelled('Model preparation cancelled by Stop')
    if state is not None and not service._generation_current(state):
        raise PreparationCancelled('Model preparation was superseded')


def _owned_listener():
    result = service._listener_identity()
    rows = result.get('listeners', [])
    if result['open'] and (not rows or any(not row.get('portable_qwen') for row in rows)):
        raise RuntimeError(('Port 8080 has a listener outside this portable root; it was left untouched').replace('Port 8080', 'Port '+str(_instance_port('qwen'))))
    return result


def _argv(command):
    if isinstance(command, list):
        return command
    if os.name != 'nt':
        return shlex.split(command)
    import ctypes
    api = ctypes.WinDLL('shell32', use_last_error=True)
    api.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    api.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    pointer = api.CommandLineToArgvW(str(command), ctypes.byref(count))
    if not pointer:
        raise OSError('Cannot parse the owned model command')
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(pointer)


def _matches(identity, model, context, command=None, expected_pid=None):
    path = model.get('absolute_path') or str(ROOT / model.get('path', ''))
    if not path or not identity.get('listeners'):
        return False
    for row in identity['listeners']:
        if expected_pid is not None and int(row.get('pid', 0)) != int(expected_pid):
            return False
        args = _argv(row.get('command_line', ''))
        try:
            from runtime_policy import small_vision_settings
            image_settings = small_vision_settings(model)
            if image_settings and (int(context) < image_settings['min_context_tokens'] or
                    '--image-min-tokens' not in args or
                    int(args[args.index('--image-min-tokens') + 1]) != image_settings['image_min_tokens']):
                return False
            if Path(args[args.index('-m') + 1]).resolve() != Path(path).resolve():
                return False
            if int(args[args.index('-c') + 1]) != int(context):
                return False
            if command:
                # Linux command lines may start with our explicit glibc loader.
                executable = Path(command[0]).resolve()
                if not any(Path(value).resolve() == executable for value in args[:5]):
                    return False
                for flag in ('--device', '-ngl', '--mmproj', '--image-min-tokens', '--image-max-tokens'):
                    wanted = command[command.index(flag) + 1] if flag in command else None
                    actual = args[args.index(flag) + 1] if flag in args else None
                    if flag == '--mmproj' and wanted is not None and actual is not None:
                        if Path(actual).resolve() != Path(wanted).resolve():
                            return False
                    elif wanted != actual:
                        return False
                if ('--no-mmproj-offload' in command) != ('--no-mmproj-offload' in args):
                    return False
        except (ValueError, IndexError, RuntimeError):
            return False
    return True


def _require_idle():
    # If another client is generating, do not interrupt its inference to change profiles.
    # Every supported launch enables metrics. /slots can be disabled independently,
    # and idle slots alone do not rule out requests waiting in the server queue.
    with urllib.request.urlopen(_instance_url('qwen', '/metrics'), timeout=3) as response:
        raw = response.read(256001)
    if len(raw) > 256000:
        raise RuntimeError('Qwen activity metrics exceeded the bounded read limit; model left running')
    text = raw.decode('utf-8', errors='strict')
    for name in ('requests_processing', 'requests_deferred'):
        matches = re.findall(r'^llamacpp:' + name + r'(?:\{[^\n]*\})?\s+(\S+)(?:\s+\S+)?\s*$', text, flags=re.M)
        try:
            values = [float(value) for value in matches]
        except ValueError as exc:
            raise RuntimeError('Qwen activity metrics are invalid; model left running') from exc
        if not values or any(not math.isfinite(value) or value < 0 for value in values):
            raise RuntimeError('Qwen activity metrics are missing or invalid; model left running')
        if any(value != 0 for value in values):
            raise RuntimeError('Qwen is serving or queuing another request. Retry the effort change when it finishes')


def _spawn(root, command):
    argv = list(command)
    cwd = root
    env = portable_env(root)
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        from platform_runtime import linux_elf_command
        argv, native_cwd = linux_elf_command(root, argv)
        cwd = native_cwd or root
        env.pop('LD_LIBRARY_PATH', None)
    from media_paths import media_runtime
    log = media_runtime(root) / 'chat_effort_model.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('ab') as output:
        output.write(('\nEffort model startup ' + time.ctime() + '\n').encode())
        output.flush()
        kwargs = dict(cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output,
                      stderr=output, close_fds=True, start_new_session=os.name != 'nt')
        if os.name == 'nt':
            try:
                return subprocess.Popen(argv, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except OSError:
                pass
        return subprocess.Popen(argv, creationflags=flags, **kwargs)


def _result(profile, plan, changed):
    from chat_budgets import generation_options
    # Reusing an admitted model must not freeze an older inference budget or
    # template default. This changes no loading/memory/ownership decision.
    context = (plan.get('model') or {}).get('context_tokens') or plan.get('context_tokens')
    options = generation_options(profile, context) if context else plan['completion_options']
    return {'profile': profile, 'model': plan['model'], 'changed': changed,
            'completion_options': options,
            'max_tool_rounds': plan.get('max_tool_rounds', plan.get('tool_round_limit', 12))}


def _saved_admitted_plan(root, profile, permission):
    """Reuse the actually admitted profile, not the UI's total-capacity ceiling."""
    try:
        saved = json.loads((root / 'Agent/.runtime/hardware_launch_plan.json').read_text(encoding='utf-8'))
        if (saved.get('level') != profile or saved.get('preview_only', True) or
            saved.get('vision_request', False) != permission.get('vision_request', False) or
            not isinstance(saved.get('model'), dict) or not isinstance(saved.get('command'), list) or
            not isinstance(saved.get('completion_options'), dict)):
            return None
        before, current = saved.get('backend') or {}, permission.get('backend') or {}
        if ('policy_signature' in permission and
                saved.get('policy_signature') != permission['policy_signature']):
            return None
        if any(before.get(key) != current.get(key) for key in ('backend', 'device', 'executable')):
            return None
        preference = permission.get('model_preference')
        if preference is not None:
            model_id = saved['model'].get('id')
            explicit = preference.get('explicit')
            if (explicit and model_id != explicit) or (not explicit and model_id not in preference.get('automatic', [])):
                return None
        return saved
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def prepare_startup(root, *, requested_at=None, on_status=None):
    """Apply saved Settings using the same owned, idle, Stop-fenced handoff as chat."""
    from runtime_policy import load_effective_policy
    return prepare_chat(root, 'balanced', requested_at=requested_at, on_status=on_status,
                        _policy=load_effective_policy(root))


def prepare_chat(root, profile, unlock_slow=False, cancel_event=None, requested_at=None, on_status=None,
                 require_vision=False, _policy=None):
    """Never replay a tool; this is called once before a chat request starts."""
    from effort_policy import capabilities, check_chat_permission, require_chat_plan
    root = Path(root).resolve()
    if root != ROOT.resolve():
        raise ValueError('Chat switching requires this portable root')
    requested_at = time.time() if requested_at is None else requested_at
    notify = on_status or (lambda message: None)
    policy_args = {} if _policy is None else {'policy': _policy}
    if require_vision:
        policy_args['require_vision'] = True
    def guard(state=None):
        _guard(root, requested_at, cancel_event, state)
        if _policy is not None:
            from runtime_policy import load_effective_policy
            from effort_policy import chat_policy_signature
            if chat_policy_signature(load_effective_policy(root)) != chat_policy_signature(_policy):
                raise PreparationCancelled('Chat settings changed during Startup; retry Startup with the new settings')
    guard()
    permission = check_chat_permission(profile, root=root, session_unlocked=unlock_slow, **policy_args)
    require_space(root, for_outputs=True)
    lease = None
    state = None
    process = None
    saved = {}
    try:
        notify('Checking chat effort and waiting for available model memory…')
        while lease is None:
            guard()
            try:
                lease = service.acquire_gpu_lease('chat-effort', timeout=.3)
            except TimeoutError:
                continue
        preview = capabilities(root, session_unlocked=unlock_slow, **policy_args)['profiles'][profile]
        if preview.get('available') is False:
            raise RuntimeError(preview.get('reason') or 'The selected chat model is unavailable')
        if require_vision and not (preview.get('model') or {}).get('projector'):
            raise RuntimeError('This chat includes an attached image, but the selected effort profile has no vision model. '
                               'Choose a vision-capable model or Automatic in Settings, then use Balanced or Deep. '
                               'Your attachments remain saved.')
        with service._qwen_lifecycle_mutex():
            guard()
            current = _owned_listener()
            saved_plan = _saved_admitted_plan(root, profile, permission)
            if (saved_plan and current['open'] and service._qwen_health_ready() and
                (not require_vision or saved_plan['model'].get('projector')) and
                _matches(current, saved_plan['model'], saved_plan['context_tokens'], saved_plan['command'])):
                return _result(profile, saved_plan, False)
            if current['open'] and service._qwen_health_ready() and _matches(
                    current, preview.get('model', {}), preview.get('context_tokens', 8192), preview.get('command')):
                return _result(profile, preview, False)
            if current['open']:
                _require_idle()
        notify('Reclaiming the current model memory for ' +
               ('image vision' if require_vision else profile.title() + ' effort') + '…')
        # The guard runs inside the same mutex that protects handoff from Stop.
        def before_handoff():
            guard()
            if _owned_listener()['open']:
                _require_idle()
        state = service.qwen_gpu_handoff_begin('chat-effort-' + profile, start_guard=before_handoff)
        if not state.get('active'):
            with service._qwen_lifecycle_mutex():
                guard()
                if _owned_listener()['open']:
                    raise RuntimeError('Could not safely capture the current model for an effort change')
                state = {'active': False, 'generation_token': 'effort-' + uuid.uuid4().hex}
                service._write_qwen_generation({'token': state['generation_token'], 'reason': 'chat-effort'})
        guard(state)
        # Do not admit a large model using advisory total memory from the UI.
        plan = require_chat_plan(profile, root=root, session_unlocked=unlock_slow, **policy_args)
        if require_vision and not plan['model'].get('projector'):
            raise RuntimeError('Available memory cannot fit a vision model for this attached image. '
                               'Free memory or use a vision-capable computer; the attachment was preserved.')
        guard(state)
        for name in ('qwen_launch_command.txt', 'qwen_launch_executable.txt', 'hardware_launch_plan.json'):
            path = root / 'Agent/.runtime' / name
            saved[path] = path.read_bytes() if path.exists() else None
        command = plan['command']
        command_line = subprocess.list2cmdline(command) if os.name == 'nt' else shlex.join(command)
        with service._qwen_lifecycle_mutex():
            guard(state)
            if _owned_listener()['open']:
                raise RuntimeError('Another model claimed the listener during preparation')
            process = _spawn(root, command)
            service._remember_qwen_launch(command_line, command[0])
        notify('Loading ' + str(plan['model']['id']) + ' (' + profile.title() + ')…')
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            guard(state)
            if process.poll() is not None:
                raise RuntimeError('Effort model exited before readiness. See Agent/.runtime/chat_effort_model.log')
            identity = _owned_listener()
            if identity['open'] and service._qwen_health_ready():
                if not _matches(identity, plan['model'], plan['model']['context_tokens'], command, process.pid):
                    raise RuntimeError('A different model answered the readiness check')
                with service._qwen_lifecycle_mutex():
                    guard(state)
                    atomic_json(root / 'Agent/.runtime/hardware_launch_plan.json', plan)
                    service._mark_handoff_done(state, 'effort-model-ready')
                    service._clear_generation_if_current(state)
                return _result(profile, plan, True)
            time.sleep(.25)
        raise TimeoutError('Effort model did not become healthy within five minutes')
    except BaseException:
        # Popen owns an exact OS process handle on Windows, not an arbitrary port/PID.
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        restore = False
        if state:
            # A newer Stop/start must also own launch metadata. Do not race it
            # after a stale generation check outside the lifecycle mutex.
            with service._qwen_lifecycle_mutex():
                if service._generation_current(state):
                    for path, data in saved.items():
                        if data is None:
                            path.unlink(missing_ok=True)
                        else:
                            path.write_bytes(data)
                    if state.get('active'):
                        restore = True
                    else:
                        service._clear_generation_if_current(state)
            # qwen_gpu_handoff_end acquires its own mutex and rechecks generation;
            # keep it outside this mutex (Linux flock is not reentrant).
            if restore:
                notify('Restoring the previous model after the effort change was interrupted…')
                service.qwen_gpu_handoff_end(state)
        raise
    finally:
        service.release_gpu_lease(lease)
