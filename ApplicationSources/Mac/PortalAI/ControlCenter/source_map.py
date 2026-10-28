"""Bounded source discovery and Python outlines; never imports inspected code."""
import hashlib
import json
from source_navigation import PUBLIC, check, public_path, public_files, ranked_files, outline


def source_map(runtime, path='.', query='', offset=0, limit=12, tool=None):
    epoch = getattr(runtime, '_cancel_epoch', None)
    check(runtime, epoch)
    if tool is not None:
        if path!='.' or query or offset:
            raise ValueError('Use tool by itself; follow its returned source paths for further navigation')
        from source_routes import tool_entrypoint
        return json.dumps(tool_entrypoint(runtime,tool),ensure_ascii=True)
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError('query must be at most 200 characters')
    if type(offset) is not int or not 0 <= offset <= 5000 or type(limit) is not int or not 1 <= limit <= 60:
        raise ValueError('offset must be 0..5000 and limit 1..60')
    target = public_path(runtime, path)
    if not target.exists():
        raise FileNotFoundError(str(target))
    rows = []
    truncated = False
    digest = None
    extra = {}
    if target.is_file():
        if target.suffix != '.py' or target.stat().st_size > 1024 * 1024:
            raise ValueError('Outlines require a Python source file no larger than 1 MiB')
        raw = target.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        summary, symbols, imports = outline(text)
        rows = [s for s in symbols if query.casefold() in s['symbol'].casefold()]
        for row in rows:
            row['next_call'] = {'name': 'read_file', 'arguments': {'path': str(target),
                'offset': row['offset'], 'max_chars': min(12000, row['end_offset'] - row['offset'])}}
        extra = {'summary': summary, 'imports': imports, 'total_chars': len(text)}
        from source_routes import references
        refs,refs_limited=references(runtime,text)
        extra.update(local_references=refs,local_references_truncated=refs_limited)
        mode = 'python_outline'
    elif query:
        rows, truncated, used = ranked_files(runtime, target, query)
        mode = 'ranked_files'
        extra = {'bytes_scanned': used, 'ranking': 'Lexical filename, Python symbol and docstring words; not semantic proof.'}
    else:
        files, truncated = public_files(runtime, target)
        rows = [{'path': p.relative_to(runtime.root.resolve()).as_posix(), 'bytes': p.stat().st_size} for p in files]
        mode = 'files'
    check(runtime, epoch)
    return json.dumps({'mode': mode, 'path': str(target), 'sha256': digest, 'items': rows[offset:offset + limit],
        'total_items': len(rows), 'next_offset': offset + limit if offset + limit < len(rows) else None,
        'scan_truncated': truncated, **extra,
        'note': 'Observed source structure, not execution. next_call is an optional read-only navigation suggestion; no call was executed. Offsets address read_file text.'}, ensure_ascii=True)
