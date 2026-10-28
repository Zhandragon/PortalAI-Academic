"""Bounded, read-only public-source navigation. Never imports inspected code."""
import ast
import hashlib
import json
import re
from collections import deque
from pathlib import Path

PUBLIC = ('Agent', 'ControlCenter', 'Tools', 'Documentation', 'Maintenance/Tests')
SKIP = {'__pycache__', 'node_modules', 'vendor'}
EXTENSIONS = {'.py', '.txt', '.md'}
MAX_ENTRIES = 5000


def check(runtime, epoch):
    if runtime._account_role() != 'admin':
        raise PermissionError('Public source access requires administrator access')
    check_cancel(runtime, epoch)


def check_cancel(runtime, epoch):
    """Cheap cancellation during pure in-memory work; never authorizes file access."""
    if getattr(runtime, '_cancel_epoch', None) != epoch:
        raise RuntimeError('Source lookup cancelled')


def public_path(runtime, path='.'):
    """Accept returned absolute paths or installation-relative paths, never aliases."""
    epoch = getattr(runtime, '_cancel_epoch', None)
    check(runtime, epoch)
    target = _resolve_public_path(runtime.root.resolve(), path)
    check(runtime, epoch)
    return target


def _resolve_public_path(root, path):
    """Filesystem checks only. Internal scans must check access before every read."""
    if not isinstance(path, str) or not path or len(path) > 4096:
        raise ValueError('path must be a public source path')
    rel = Path(path.replace('\\', '/'))
    if '..' in rel.parts:
        raise PermissionError('Parent traversal is not a public source path')
    if rel.is_absolute():
        try:
            rel = rel.relative_to(root)
        except ValueError:
            raise PermissionError('Absolute source path must be inside this installation') from None
    if rel.drive or (rel.parts and not any(rel.parts[:len(Path(p).parts)] == Path(p).parts for p in PUBLIC)):
        raise PermissionError('Choose . or a path under Agent, ControlCenter, Tools, Documentation or Maintenance/Tests')
    target = root / rel
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise PermissionError('Source navigation refuses links')
    if not target.resolve().is_relative_to(root):
        raise PermissionError('Source path escaped installation')
    return target


def public_files(runtime, target):
    epoch = getattr(runtime, '_cancel_epoch', None)
    root = runtime.root.resolve()
    if not target.exists():
        raise FileNotFoundError(str(target))
    if target.is_file():
        return [target], False
    # Visit each public root before bundled programs' deeper trees can exhaust
    # the bounded inventory. This also makes direct directory scans breadth-first.
    todo = deque(root / name for name in PUBLIC) if target == root else deque([target])
    files = []
    visited = 0
    order = lambda p: (len(p.relative_to(root).parts), p.as_posix())
    while todo:
        folder = todo.popleft()
        check(runtime, epoch)
        if not folder.exists():
            continue
        _resolve_public_path(root, str(folder))
        for p in sorted(folder.iterdir()):
            check_cancel(runtime, epoch)
            visited += 1
            if visited > MAX_ENTRIES:
                check(runtime, epoch)
                return sorted(files, key=order), True
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                continue
            if p.is_dir():
                if not p.name.startswith('.') and p.name not in SKIP:
                    todo.append(p)
            elif p.suffix in EXTENSIONS and not p.name.startswith('.'):
                files.append(p)
    check(runtime, epoch)
    return sorted(files, key=order), False


def terms(value):
    # Lexical, not semantic: underscores/camel case separate code words.
    value = re.sub(r'([a-z])([A-Z])', r'\1 \2', value)
    return set(re.findall(r'[^\W_]+', value.casefold(), re.UNICODE))


def outline(text):
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    bom = text.startswith('\ufeff')
    tree = ast.parse(text.removeprefix('\ufeff'))
    rows = []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append({'module': '.' * node.level + (node.module or ''),
                            'names': [a.name for a in node.names][:20], 'line': node.lineno})
        elif isinstance(node, ast.Import):
            imports.extend({'module': a.name, 'names': [], 'line': node.lineno} for a in node.names)

    def walk(node, prefix=''):
        for child in getattr(node, 'body', ()):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                rows.append({'symbol': name, 'kind': type(child).__name__, 'line': child.lineno,
                             'offset': starts[child.lineno - 1] + int(bom and child.lineno == 1), 'end_offset': starts[child.end_lineno],
                             'signature': lines[child.lineno - 1].strip()[:240],
                             'summary': (ast.get_docstring(child) or '').split('\n')[0][:200]})
                walk(child, name + '.')
    walk(tree)
    return (ast.get_docstring(tree) or '')[:400], rows, imports[:80]


def ranked_files(runtime, target, query):
    """Rank observed filename, symbol and docstring words; report all scan bounds."""
    epoch = getattr(runtime, '_cancel_epoch', None)
    files, truncated = public_files(runtime, target)
    root = runtime.root.resolve()
    wanted = terms(query)
    # Inspect filename candidates first, so a byte cap cannot hide them.
    files.sort(key=lambda p: (-len(wanted & terms(p.name)), len(p.relative_to(root).parts), p.as_posix()))
    rows = []
    used = 0
    skipped = 0
    for p in files:
        check(runtime, epoch)
        name = p.relative_to(root).as_posix()
        size = p.stat().st_size
        filename_terms = wanted & terms(name)
        exact = bool(query and query.casefold() in name.casefold())
        symbols = []
        summary = ''
        digest = None
        if p.suffix == '.py' and size <= 1024 * 1024 and used + size <= 16 * 1024 * 1024:
            raw = _resolve_public_path(root, str(p)).read_bytes()
            used += len(raw)
            digest = hashlib.sha256(raw).hexdigest()
            try:
                summary, symbols, _ = outline(raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n'))
            except (SyntaxError, UnicodeError, ValueError, RecursionError):
                pass
        elif p.suffix == '.py':
            skipped += 1
        matched = [s for s in symbols if wanted & terms(s['symbol'] + ' ' + s['summary'])]
        matched.sort(key=lambda s: (-len(wanted & terms(s['symbol'] + ' ' + s['summary'])), s['line']))
        description_terms = wanted & terms(summary)
        coverage = filename_terms | description_terms
        for s in matched:
            coverage |= wanted & terms(s['symbol'] + ' ' + s['summary'])
        score = 12 * len(coverage) + 5 * len(filename_terms) + 3 * len(description_terms) + 8 * exact
        if not query or score:
            rows.append({'path': name, 'absolute_path': str(p), 'bytes': size, 'sha256': digest,
                         'score': score, 'matched_terms': sorted(coverage), 'summary': summary,
                         'symbols': matched[:4],
                         'next_call': {'name': 'source_map', 'arguments': {'path': name}}})
    check(runtime, epoch)
    rows.sort(key=lambda r: (-r['score'], r['path']))
    return rows, truncated or bool(skipped), used


def progress_guidance(messages):
    """Use call metadata only, never elevate source/tool-result prose to policy."""
    calls = []
    for row in list(messages or ())[-32:]:
        if not isinstance(row, dict) or row.get('role') != 'assistant':
            continue
        for call in row.get('tool_calls') or ():
            name = (call.get('function') or {}).get('name')
            if isinstance(name, str):
                calls.append(name)
    if not calls:
        return ''
    last_write = max((i for i, name in enumerate(calls) if name in ('edit_file', 'write_file')), default=-1)
    recent = calls[last_write + 1:]
    if sum(name in ('source_search', 'source_map') for name in recent) >= 5:
        return ('\nCoding progress: repeated source discovery without an edit attempt. '
                'Do not guess another function name. Use a ranked source_map result, read its relevant symbol and imports, '
                'then reproduce the failure with the supplied test command. Once the cause is evidenced, make one small repair and test it. '
                'If a tool rejects an argument, correct the call instead of repeating it. This is guidance, not permission or proof of an edit.')
    if last_write >= 0:
        return '\nCoding progress: a write was attempted. Inspect its receipt and verify the current bytes with tests before claiming success.'
    return ''
