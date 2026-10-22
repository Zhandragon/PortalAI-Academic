"""Resolve private files for one captured PortalAI login, keeping asset paths stable.

These checks isolate application paths, not the host OS. Profile keys never travel
in the environment. A locked installation refuses private-file access; legacy
single-user installations keep their existing paths until migration is committed.
"""
from __future__ import annotations

import json
import os
from pathlib import PurePosixPath, PureWindowsPath
from portable_fs import Path
import re

UID_ENV = 'PORTALAI_PROFILE_ID'
EPOCH_ENV = 'PORTALAI_PROFILE_EPOCH'
PRIVATE_PREFIXES = (
    'Data', 'Outputs', 'User Folder', 'Logs', 'Benchmarks', 'Patch/Videos',
    'Cache/MuseTalk', 'Cache/Web', 'Cache/WebTests', 'Cache/Gradio',
    'Cache/tmp', 'Cache/Temp', 'Cache/ScaledEditValidation',
    'PortableCache/Qwen3-TTS/Temp', 'PortableCache/Science',
    'Cache/MediaEdit', 'Cache/MAFFT', 'Cache/ComfyWorkers',
    'Cache/LinuxWorkers', 'Cache/Whisper/runtime',
    'Cache/MediaWorkers',
    'Music/ACE-Step-1.5/.cache', 'Music/ACE-Step-1.5/gradio_outputs',
    'MusicUnderstanding/cache/demucs',
    'OpenWebUI/data', 'OpenWebUI/.runtime', 'SpeechToText/.runtime',
    'Agent/.runtime/dialogue', 'Agent/.runtime/mmaudio_jobs',
    'Agent/.runtime/video_range_edit', 'Agent/.runtime/tmp',
    'Generative/ComfyUI_windows_portable/ComfyUI/input',
    'Generative/ComfyUI_windows_portable/ComfyUI/output',
    'Generative/ComfyUI_windows_portable/ComfyUI/temp',
    'Generative/ComfyUI_windows_portable/ComfyUI/user',
)


class ProfileLocked(PermissionError):
    pass


def enabled(root):
    root = Path(root)
    base = root / 'Private/Accounts'
    evidence=('Private/active-session.json','Private/Users','Private/migration-pending.json',
              'Private/migration-complete.json','Private/profile-initialization.json','Private/Reset')
    if any((root/path).exists() for path in evidence):return True
    try:
        if base.exists():
            return not base.is_dir() or any(path.name!='registry.lock' for path in base.iterdir())
    except OSError:return True  # Unreadable account state is locked, never legacy.
    return False


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ProfileLocked('Invalid profile identity')
    return value


def workspace_root(root, user_id):
    root = Path(root).resolve()
    path = root / 'Private/Users' / _identifier(user_id) / 'Workspace'
    _contained(root, path)
    return path


def _contained(root, path):
    """Reject links/junctions, including ones whose target stays in the bundle."""
    root = Path(root).resolve()
    path = Path(path)
    if not path.is_relative_to(root):
        raise ProfileLocked('Private path escapes the portable root')
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ProfileLocked('Linked private paths are not supported')
    if not path.resolve().is_relative_to(root):
        raise ProfileLocked('Private path escapes the portable root')
    return path


def capture(root, environ=None):
    env = os.environ if environ is None else environ
    uid, epoch = env.get(UID_ENV), env.get(EPOCH_ENV)
    if not uid and not epoch and not enabled(root):
        return None
    uid = _identifier(uid)
    epoch = _identifier(epoch)
    marker = Path(root) / 'Private/active-session.json'
    _contained(Path(root).resolve(), marker)
    try:
        if marker.stat().st_size > 16384:
            raise ValueError('Oversized session marker')
        active = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ProfileLocked('PortalAI is locked; sign in through the Control Center') from None
    if active.get('user_id') != uid or active.get('epoch') != epoch or active.get('state') != 'open':
        raise ProfileLocked('This login ended or its workspace needs recovery')
    return (uid, epoch)


def _relative(value):
    text = str(value).replace('\\', '/')
    rel = PurePosixPath(text)
    if (rel.is_absolute() or PureWindowsPath(text).drive or '..' in rel.parts or not rel.parts or
            ':' in text or any(part.endswith(('.', ' ')) or
                re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)
                for part in rel.parts)):
        raise ValueError('Expected a relative private path')
    return rel.as_posix()


def is_private(relative):
    relative = _relative(relative)
    return any(relative.casefold() == prefix.casefold() or
               relative.casefold().startswith(prefix.casefold() + '/') for prefix in PRIVATE_PREFIXES)


def private_path(root, relative, *, context=None, hydrate=True):
    root = Path(root).resolve()
    relative = _relative(relative)
    if not is_private(relative):
        raise ValueError('Path is not a declared private-data location: ' + relative)
    active = capture(root)
    if context is not None and active != context:
        raise ProfileLocked('The captured login is no longer active')
    base = root if active is None else workspace_root(root, active[0])
    path = base / relative
    _contained(root, path)
    if hydrate and active is not None:
        from profile_hydration import materialize
        materialize(root, relative)
        if capture(root) != active:
            raise ProfileLocked('The captured login ended during file restoration')
        _contained(root, path)
    return path


def _migrated_reference_target(relative):
    """Use the reviewed migration scope for old references, including Windows case.

    Import lazily: migration itself imports the basic path checks above. Only
    declared scope names are normalized; filenames within a scope stay intact.
    """
    from profile_migration import HISTORICAL_FILES, HISTORICAL_ROOTS, RUNTIME_PUBLIC, _source_target
    relative = _relative(relative)
    folded = relative.casefold()
    for filename in HISTORICAL_FILES:
        if folded == filename.casefold():
            relative = filename
            break
    else:
        scopes = (*HISTORICAL_ROOTS, *PRIVATE_PREFIXES, 'Agent/.runtime')
        for scope in sorted(scopes, key=len, reverse=True):
            if folded == scope.casefold() or folded.startswith(scope.casefold() + '/'):
                relative = scope + relative[len(scope):]
                break
    if relative.startswith('Agent/.runtime/'):
        tail = relative[len('Agent/.runtime/'):]
        if '/' not in tail:
            public = next((name for name in RUNTIME_PUBLIC if name.casefold() == tail.casefold()), None)
            if public is not None:
                relative = 'Agent/.runtime/' + public
            elif tail.casefold().endswith('.lock'):
                relative = 'Agent/.runtime/' + tail[:-5] + '.lock'
    try:
        return _source_target(relative)
    except ValueError:
        # A validated but undeclared source remains a shared bundle asset.
        return None


def resolve_reference(root, value, *, allow_external=False, hydrate=True):
    """Resolve saved private-data references without editing stored chat messages.

    New references contain immutable IDs. They cannot select another profile.
    External files are accepted only at explicit user attachment/export boundaries.
    """
    root = Path(root).resolve()
    def private_reference(relative, context=None):
        active = capture(root)
        if context is not None and active != context:
            raise ProfileLocked('The captured login ended')
        path = private_path(root, relative, context=active, hydrate=False)
        if active is not None and hydrate:
            from profile_hydration import materialize
            materialize(root, relative, recursive=True)
            if capture(root) != active:
                raise ProfileLocked('The captured login ended during file restoration')
            _contained(root, path)
        return path
    accounts_enabled = enabled(root)
    text = str(value).replace('\\', '/')
    path = Path(text)
    def moved_drive():
        old = PureWindowsPath(text)
        if not old.drive:
            old = PurePosixPath(text)
        if not old.is_absolute(): return None
        # These are names of this distribution, not arbitrary folder aliases.
        # Only already-recognized private suffixes below can be relocated;
        # immutable profile identity, hydration and containment checks still run.
        # Absolute paths saved by earlier builds can refer to any of the
        # supported per-platform bundle names. Accept only these reviewed
        # aliases; the private suffix, active user/epoch, and containment
        # checks below remain mandatory.
        names={root.name.casefold(), 'portalai', 'portableai',
               'portalai windows', 'portalai linux', 'portalai mac'}
        matches = [i for i, part in enumerate(old.parts) if part.casefold() in names]
        if len(matches) != 1 or matches[0] + 1 >= len(old.parts): return None
        relative = '/'.join(old.parts[matches[0]+1:])
        if (is_private(relative) or relative.casefold().startswith('private/users/') or
                (accounts_enabled and _migrated_reference_target(relative) is not None)):
            return relative
        return None
    if path.is_absolute():
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = moved_drive()
            if relative is not None:
                pass
            elif allow_external:
                return path.resolve()
            else:
                raise ProfileLocked('File is outside this PortalAI installation') from None
    elif PureWindowsPath(text).drive or PurePosixPath(text).is_absolute():
        # After moving drives, only recognized portable private-data suffixes are
        # remapped. Never reinterpret an arbitrary absolute external path.
        relative = moved_drive()
        if relative is None:
            raise ProfileLocked('External path is not portable')
    else:
        relative = _relative(text)
    if relative.casefold().startswith('private/'):
        parts = PurePosixPath(relative).parts
        current = capture(root)
        if (current is None or len(parts) < 5 or parts[:2] != ('Private', 'Users') or
                parts[2] != current[0] or parts[3] != 'Workspace'):
            raise ProfileLocked('Another profile is not accessible in this login')
        return private_reference('/'.join(parts[4:]), context=current)
    if accounts_enabled:
        target = _migrated_reference_target(relative)
        if target is not None:
            return private_reference(target)
    if is_private(relative):
        return private_reference(relative)
    candidate = root / relative
    _contained(root, candidate)
    return candidate
