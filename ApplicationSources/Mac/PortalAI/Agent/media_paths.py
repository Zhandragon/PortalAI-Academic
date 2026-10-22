"""Private media paths without changing the shared model/program root."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import quote

from profile_paths import capture, enabled, private_path, resolve_reference, workspace_root


def media_reference(root, value):
    """Legacy external paths still work before local accounts are initialized."""
    if enabled(root) or capture(root) is not None:
        return resolve_reference(root, value)
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(root) / path).resolve()


def media_runtime(root):
    if capture(root) is None:
        return Path(root) / 'Agent/.runtime'
    return private_path(root, 'Cache/MediaWorkers')


def media_temp(root):
    path = private_path(root, 'Cache/tmp')
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_output(root, value):
    path = media_reference(root, value)
    current = capture(root)
    if current is not None and not path.is_relative_to(workspace_root(root, current[0])):
        raise PermissionError('Generated files must stay in this profile workspace')
    return path


def image_source(root, value):
    """Resolve/hydrate a referenced input before any model handoff or worker.

    Never use cwd-relative Path.resolve for profile files: Data/... belongs to
    the captured account, and old absolute portable paths may need relocation.
    """
    path = media_reference(root, value)
    if not path.is_file():
        raise FileNotFoundError('Media input is not an available file: ' + str(path))
    return path


def comfy_directory_args(root):
    if capture(root) is None:
        return []
    args = []
    for kind in ('input', 'output', 'temp', 'user'):
        path = private_path(root, 'Generative/ComfyUI_windows_portable/ComfyUI/' + kind)
        path.mkdir(parents=True, exist_ok=True)
        args.extend(['--' + kind + '-directory', str(path)])
    return args


def preview_credentials(root):
    """Capability is private while open; never use the public epoch as a secret."""
    context = capture(root)
    if context is None:
        return None
    path = private_path(root, 'Cache/MediaWorkers/preview-' + context[1] + '.json', context=context)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation prevents concurrent tool calls from replacing the
        # capability of an already-running server in this same login.
        with path.open('x', encoding='utf-8') as handle:
            value = {'epoch': context[1], 'token': secrets.token_urlsafe(32)}
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        pass
    if path.stat().st_size > 4096:
        raise PermissionError('Invalid preview capability')
    for attempt in range(20):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            break
        except json.JSONDecodeError:
            if attempt == 19:
                raise PermissionError('Preview capability is incomplete') from None
            time.sleep(.01)
    if value.get('epoch') != context[1] or not isinstance(value.get('token'), str) or len(value['token']) < 32:
        # A previous login capability must not authorize this session. Rotation
        # is explicit at login; do not replace a stale file under live readers.
        raise PermissionError('Preview capability belongs to an earlier login')
    return value['token']


def preview_url(root, url):
    token = preview_credentials(root)
    if token is None:
        return url
    return url + ('&' if '?' in url else '?') + 'portal_token=' + quote(token, safe='')


def owned_preview(root, port):
    """Never disclose a profile capability while probing an unrelated listener."""
    if capture(root) is None:
        return True
    import service_manager as service
    from chat_model_switch import _argv
    try:
        pids=service._listening_pids(int(port))
        if not pids:
            return False
        root=Path(root).resolve()
        expected=root/'Agent/media_server.py'
        output=private_path(root,'Outputs')
        for pid in pids:
            args=_argv(service._process_command_line(pid) or '')
            if not args or not Path(args[0]).resolve().is_relative_to(root):
                return False
            if not any(Path(arg).resolve()==expected for arg in args[1:] if not arg.startswith('-')):
                return False
            if args.count('--root')!=1 or args.count('--port')!=1:
                return False
            if (Path(args[args.index('--root')+1]).resolve()!=output or
                    int(args[args.index('--port')+1])!=int(port)):
                return False
        return True
    except (OSError,ValueError,IndexError,TypeError):
        return False
