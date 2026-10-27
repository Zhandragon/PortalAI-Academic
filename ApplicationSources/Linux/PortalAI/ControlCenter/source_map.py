"""Bounded source inventory and Python outlines; never imports inspected code."""
import ast
import hashlib
import json
from pathlib import Path

PUBLIC = ('Agent', 'ControlCenter', 'Tools', 'Documentation')


def source_map(runtime, path='.', query='', offset=0, limit=40):
    if runtime._account_role() != 'admin':
        raise PermissionError('Source maps require administrator access')
    if not isinstance(path, str) or not isinstance(query, str) or len(query) > 200:
        raise ValueError('path and a short query must be text')
    if type(offset) is not int or not 0 <= offset <= 5000 or type(limit) is not int or not 1 <= limit <= 60:
        raise ValueError('offset must be 0..5000 and limit 1..60')
    root = runtime.root.resolve()
    rel = Path(path)
    if rel.is_absolute() or rel.drive or '..' in rel.parts or (path != '.' and (not rel.parts or rel.parts[0] not in PUBLIC)):
        raise PermissionError('Choose . or a public source path')

    def checked(p):
        for part in (p, *p.parents):
            if part == root: break
            if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
                raise PermissionError('Source maps refuse links')
        if not p.resolve().is_relative_to(root): raise PermissionError('Source path escaped installation')
        if runtime._account_role() != 'admin': raise PermissionError('Administrator access ended')
        return p

    target = checked(root / rel)
    if not target.exists(): raise FileNotFoundError(str(target))
    rows = []; truncated = False; digest = None
    if target.is_file():
        if target.suffix != '.py' or target.stat().st_size > 1024 * 1024:
            raise ValueError('Outlines require a Python source file no larger than 1 MiB')
        raw = checked(target).read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
        lines = text.splitlines(keepends=True); starts = [0]
        for line in lines: starts.append(starts[-1] + len(line))
        def walk(node, prefix=''):
            for child in getattr(node, 'body', ()):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = prefix + child.name
                    if query.casefold() in name.casefold():
                        rows.append({'symbol': name, 'kind': type(child).__name__, 'line': child.lineno,
                                     'offset': starts[child.lineno-1], 'end_offset': starts[child.end_lineno],
                                     'signature': lines[child.lineno-1].strip()[:240]})
                    walk(child, name + '.')
        walk(ast.parse(text))
        mode = 'python_outline'
    else:
        todo = [root / name for name in reversed(PUBLIC)] if path == '.' else [target]
        visited = 0
        while todo and visited < 5000:
            folder = checked(todo.pop())
            if not folder.is_dir(): continue
            for p in sorted(folder.iterdir()):
                visited += 1
                if visited > 5000: truncated = True; break
                if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()): continue
                if p.is_dir():
                    if not p.name.startswith('.') and p.name not in ('__pycache__', 'node_modules', 'vendor'):
                        todo.append(p)
                elif p.suffix in ('.py', '.txt', '.md'):
                    name = p.relative_to(root).as_posix()
                    if query.casefold() in name.casefold(): rows.append({'path': name, 'bytes': checked(p).stat().st_size})
        truncated = truncated or bool(todo)
        rows.sort(key=lambda r: r['path']); mode = 'files'
    checked(target)
    return json.dumps({'mode': mode, 'path': str(target), 'sha256': digest, 'items': rows[offset:offset+limit],
                       'total_items': len(rows), 'next_offset': offset+limit if offset+limit < len(rows) else None,
                       'scan_truncated': truncated,
                       'note': 'Source structure only, not execution or behavior proof. Offsets address read_file text; read the relevant code before editing.'}, ensure_ascii=True)
