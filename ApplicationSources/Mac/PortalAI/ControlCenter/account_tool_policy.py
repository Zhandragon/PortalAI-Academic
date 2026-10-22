"""Registered media/public-web dispatch without invoking a host shell.

This narrows the application's tool surface. It is not an OS sandbox or a claim
that arbitrary scientific expression/code evaluation is safe for another user.
"""
from pathlib import Path
import argparse
import re

MEDIA_COMMANDS = frozenset({
    'image', 'edit', 'mask', 'inpaint', 'autoedit', 'route', 'video-small', 'video',
    'music-understand', 'music-analyze', 'video-edit', 'video-range-edit', 'media-info', 'audio-edit',
    'audio-mix', 'audio-inpaint', 'video-inpaint', 'video-adjust', 'sfx', 'video-sfx',
    'sfx-inpaint', 'music', 'score-video', 'lip-sync', 'video-dialogue', 'dialogue-video',
    'voice-say', 'voice-design', 'voice-clone', 'voice-custom', 'transcribe', 'mux', 'sound-video',
    'version', 'model-variants',
})

WEB_COMMANDS = frozenset({'search', 'fetch', 'research', 'image', 'image-search', 'download-image', 'selftest'})


class _WebArguments(argparse.ArgumentParser):
    def error(self, message):
        raise PermissionError('Invalid registered web arguments: ' + message)


def _web_arguments(parts):
    """Accept public inputs and bounded controls, never an output path or code."""
    command = parts[0]
    parser = _WebArguments(prog='web_tools ' + command, add_help=False, allow_abbrev=False)
    if command != 'selftest':
        parser.add_argument('input')
    if command in ('search', 'research'):
        parser.add_argument('--limit', type=int)
    if command == 'search': parser.add_argument('--fresh', action='store_true')
    if command in ('fetch', 'research'): parser.add_argument('--max-chars', type=int)
    if command == 'research': parser.add_argument('--fetch-count', type=int)
    if command in ('image', 'image-search'): parser.add_argument('--page-limit', type=int)
    if command == 'download-image': parser.add_argument('--name')
    args = vars(parser.parse_args(parts[1:]))
    if command != 'selftest' and not args['input'].strip():
        raise PermissionError('A public web query or URL is required.')
    # web_tools validates public HTTP(S) destinations, redirects and TLS. It
    # owns output naming under this login's Outputs/WebImages; no CLI parameter
    # here may redirect those writes to another account or the host filesystem.
    for flag, bounds in {'limit': (1, 12), 'max_chars': (1000, 50000),
                         'fetch_count': (0, 5), 'page_limit': (1, 8)}.items():
        if args.get(flag) is not None and not bounds[0] <= args[flag] <= bounds[1]:
            raise PermissionError(f'--{flag.replace("_", "-")} must be {bounds[0]}..{bounds[1]}.')


def registered_media_argv(command, root, boot):
    """Compatibility entry point for the registered media and web command set."""
    from chat_model_switch import _argv
    if not isinstance(command, str) or any(character in command for character in ('\x00', '\n', '\r')):
        raise PermissionError('Multiline or malformed tool commands are not allowed.')
    # The shared instructions historically spell the portable entry point with
    # Windows slashes. Canonicalize only that registered prefix before POSIX
    # tokenization; preserve prompts, file arguments and their quoting.
    known = re.match(r'(?is)^\s*(?:"?\.?[\\/]?Tools[\\/]portable_python\.cmd"?|python(?:\.exe)?|py(?:\.exe)?)\s+(.+)$', command)
    if known:
        arguments = re.sub(r'''^(["']?)(?:\.[\\/])?Agent[\\/](ai_tools|web_tools)\.py(?=["'\s]|$)''',
                           lambda match: match.group(1) + 'Agent/' + match.group(2) + '.py', known.group(1))
        command = 'python ' + arguments
    parts = _argv(command)
    if len(parts) < 3 or any(part in {'&', '&&', '|', '||', ';', '<', '>'} for part in parts):
        raise PermissionError('This account can run registered media and public-web tools, not arbitrary host shell commands.')
    launcher = parts[0].replace('\\', '/').casefold()
    if launcher not in {'python', 'python.exe', 'py', 'py.exe', 'tools/portable_python.cmd', './tools/portable_python.cmd'} and Path(parts[0]).resolve() != Path(boot).resolve():
        raise PermissionError('Use the registered portable Python tool command.')
    script = Path(parts[1].replace('\\', '/'))
    candidate = script if script.is_absolute() else Path(root)/script
    if any('\x00' in part or '\n' in part or '\r' in part for part in parts):
        raise PermissionError('Multiline or malformed tool commands are not allowed.')
    if candidate.resolve() == (Path(root)/'Agent/ai_tools.py').resolve() and parts[2] in MEDIA_COMMANDS:
        target = Path(root)/'Agent/ai_tools.py'
    elif candidate.resolve() == (Path(root)/'Agent/web_tools.py').resolve() and parts[2] in WEB_COMMANDS:
        _web_arguments(parts[2:])
        target = Path(root)/'Agent/web_tools.py'
    else:
        raise PermissionError('This command needs an administrator. This account is limited to registered media/public-web tools and basic science status/help.')
    return [str(boot), str(target), *parts[2:]]
