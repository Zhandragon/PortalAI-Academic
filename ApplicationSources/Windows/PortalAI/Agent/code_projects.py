"""Bounded external project navigation, reviewed checks, and conflict-aware undo."""
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from workspace_store import Workspace, identifier, read_json, portable_source, source_path, digest

SKIP = {'.git', '.hg', '.svn', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', '.next', 'target', 'Private', 'Vault'}
TEXT = {'.py', '.js', '.jsx', '.ts', '.tsx', '.rs', '.go', '.c', '.h', '.cpp', '.cs', '.java', '.md', '.json', '.toml', '.yaml', '.yml'}
MAX_EDIT = 512 * 1024


def sha(data): return hashlib.sha256(data).hexdigest()


def bounded(path, limit=MAX_EDIT):
    with Path(path).open('rb') as stream: data = stream.read(limit + 1)
    if len(data) > limit: raise ValueError('File exceeds the bounded project read limit')
    return data


def within(folder, name):
    target = (folder / name).resolve()
    if not target.is_relative_to(folder.resolve()): raise ValueError('Project path escapes its registered folder')
    return target


def describe(path, raw):
    text = raw.decode('utf-8-sig', 'replace'); symbols = []; imports = []
    error = None
    if path.suffix.lower() == '.py':
        try:
            tree = ast.parse(raw)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols.append({'name': node.name, 'line': node.lineno, 'kind': type(node).__name__})
                if isinstance(node, ast.Import): imports.extend(n.name for n in node.names)
                if isinstance(node, ast.ImportFrom): imports.append('.' * node.level + (node.module or ''))
        except (SyntaxError, ValueError) as exc: error = str(exc)[:300]
    else:
        for i, line in enumerate(text.splitlines(), 1):
            match = re.search(r'\b(?:function|class|interface|def|fn|func|struct)\s+([\w$]+)', line)
            if match: symbols.append({'name': match[1], 'line': i, 'kind': 'lexical'})
            match = re.search(r'''(?:\bfrom\s*|\brequire\(\s*|\bimport\s*)['"]([^'"\n]+)''', line)
            if match: imports.append(match[1])
    return {'symbols': symbols[:80], 'imports': sorted(set(imports))[:80], 'parse_error': error,
            'test': bool(re.search(r'(^|[/_.-])(test|tests|spec)([/_.-]|$)', path.as_posix(), re.I))}


class CodeProjects(Workspace):
    def __init__(self, root, check=None): super().__init__(root, 'CodeProjects', check)
    def load(self, pid): return read_json(self.path('Projects/' + identifier(pid) + '.json'))
    def list(self):
        return [{'id': row['id'], 'name': row['name'], 'source': row['source'], 'commands': list(row.get('commands', {}))}
                for row in (self.load(pid) for pid in self.records('Projects'))]

    def add(self, name, folder):
        path = Path(folder).resolve()
        if not path.is_dir() or path.parent == path: raise ValueError('Choose one project folder, not an entire drive')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120: raise ValueError('Project name: 1–120 characters')
        with self.lock():
            if len(self.records('Projects')) >= 32: raise ValueError('At most 32 registered code projects')
            row = {'id': self.new_id(), 'name': name.strip(), 'source': portable_source(self.root, path), 'commands': {}}
            self.save('Projects/' + row['id'] + '.json', row); return row

    def folder(self, pid):
        row = self.load(pid); folder = source_path(self.root, row['source']).resolve()
        if not folder.is_dir(): raise FileNotFoundError('Registered project is disconnected or missing')
        return folder

    def scan(self, pid, restart=False):
        """One incremental page, <=100 file reads / 3 seconds; never imports code."""
        folder = self.folder(pid); rel = 'Indexes/' + identifier(pid) + '.json'
        with self.lock('scan-' + pid):
            cache = read_json(self.path(rel)) if self.path(rel).exists() else {}
            if restart or not cache: cache = {'files': {}, 'pending': [''], 'complete': False, 'visited': 0, 'skipped': 0, 'started': time.time()}
            if cache.get('complete'): return {'files': len(cache['files']), 'complete': True, 'notice': 'Cached map; restart to refresh changed files'}
            started = time.monotonic(); reads = 0; entries = 0
            while cache['pending'] and reads < 100 and entries < 1000 and time.monotonic() - started < 3:
                self.check(); name = cache['pending'].pop(0); path = within(folder, name)
                if path.is_symlink() or getattr(path, 'is_junction', lambda: False)(): cache['skipped'] += 1; continue
                if path.is_dir():
                    # Queue is bounded; never descend dependency/output/private trees.
                    with os.scandir(path) as iterator:
                        for entry in iterator:
                            entries += 1
                            if entries > 5000: raise ValueError('Directory too large; register a narrower source folder')
                            if entry.name in SKIP or entry.is_symlink(): continue
                            if entry.is_dir(follow_symlinks=False) or Path(entry.name).suffix.lower() in TEXT:
                                if len(cache['pending']) + len(cache['files']) >= 2500:
                                    raise ValueError('Project map exceeds 2,500 entries; register a narrower source folder')
                                cache['pending'].append(Path(entry.path).relative_to(folder).as_posix())
                elif path.is_file():
                    reads += 1
                    try:
                        raw = bounded(path, 128 * 1024); stat = path.stat()
                        cache['files'][name] = {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': stat.st_mtime_ns, **describe(Path(name), raw)}
                    except (OSError, ValueError) as exc:
                        cache['skipped'] += 1
                        cache['files'][name] = {'unindexed': str(exc)[:120]}
                else: cache['skipped'] += 1
            cache['visited'] += reads; cache['complete'] = not cache['pending']; cache['updated'] = time.time()
            from workspace_store import encoded
            other=sum(self.path('Indexes/'+rid+'.json').stat().st_size for rid in self.records('Indexes') if rid!=pid)
            if other+len(encoded(cache))>8*1024**2:raise ValueError('Project maps reached their shared 8 MiB ceiling; remove an old map first')
            self.save(rel, cache)
            return {'project': pid, 'files': len(cache['files']), 'remaining': len(cache['pending']), 'complete': cache['complete'],
                    'skipped': cache['skipped'], 'notice': 'One bounded scan page. Continue scan until complete; dependency and generated directories are excluded.'}

    def search(self, pid, query='', limit=20):
        if not isinstance(query, str) or len(query) > 1000 or type(limit) is not int or not 1 <= limit <= 40: raise ValueError('Use a short query and limit 1–40')
        self.folder(pid); rel = self.path('Indexes/' + identifier(pid) + '.json')
        if not rel.exists(): return {'results': [], 'complete': False, 'notice': 'Run scan first'}
        cache = read_json(rel); terms = set(re.findall(r'\w+', query.casefold())); rows = []
        for name, row in cache['files'].items():
            self.check()
            words = set(re.findall(r'\w+', (name + ' ' + json.dumps(row.get('symbols', [])) + ' ' + ' '.join(row.get('imports', []))).casefold()))
            score = len(terms & words)
            if not terms or score: rows.append({'file': name, 'score': score, **row})
        rows.sort(key=lambda r: (-r['score'], r['file']))
        selected = rows[:limit]
        modules = {Path(r['file']).stem for r in selected}
        tests = [name for name, row in cache['files'].items() if row.get('test') and
                 (not terms or terms & set(re.findall(r'\w+', name.casefold())) or any(m in imp.split('.') for m in modules for imp in row.get('imports', [])))]
        return {'results': selected, 'suggested_tests': tests[:20], 'complete': cache['complete'], 'indexed_at': cache['updated'],
                'notice': 'Python AST / other-language lexical map and test suggestions; not a complete dependency graph. Read current files before editing.'}

    def set_commands(self, pid, commands):
        # UI-only: neither project tool nor verification tool exposes this grant.
        if not isinstance(commands, dict) or len(commands) > 8: raise ValueError('Supply up to eight named command configurations')
        for name, config in commands.items():
            if not isinstance(config,dict):raise ValueError('Each command configuration must be an object')
            if not re.fullmatch(r'[a-zA-Z][\w-]{0,39}', name): raise ValueError('Use short command names')
            argv = config.get('argv'); inputs = config.get('inputs')
            if not isinstance(argv, list) or not argv or any(not isinstance(v, str) or '\0' in v for v in argv) or len(json.dumps(argv)) > 8192: raise ValueError('Commands require bounded literal argv arrays')
            if not isinstance(inputs, list) or not 1 <= len(inputs) <= 32 or any(not isinstance(n, str) for n in inputs): raise ValueError('Declare 1–32 input files to detect stale test results')
            if type(config.get('timeout', 60)) is not int or not 1 <= config.get('timeout', 60) <= 120: raise ValueError('Timeout must be 1–120 seconds')
        with self.lock():
            row = self.load(pid); row['commands'] = commands; self.save('Projects/' + pid + '.json', row)
        return {'commands': list(commands), 'notice': 'These commands may have side effects. Model tools can now invoke them; outcome-uncertain runs require review.'}

    def inputs(self, pid, names):
        folder = self.folder(pid); result = {}
        for name in names:
            self.check(); result[name] = sha(bounded(within(folder, name), 2 * 1024**2))
        return result

    def run_command(self, pid, name, runtime):
        if runtime._account_role() != 'admin': raise PermissionError('Project commands require administrator role')
        from mission_supervisor import WorkerJob
        from platform_runtime import python_path, worker_process_options
        from runtime_policy import portable_env, require_space
        with self.lock('commands'):
            row = self.load(pid); config = row.get('commands', {}).get(name)
            if not config: raise PermissionError('Approve this named command in Workspace → Code first')
            signature = digest({'project': pid, 'name': name, 'config': config})
            records = self.records('Checks')
            if len(records) >= 128: raise ValueError('Project check history reached 128 records; review it in Workspace')
            for rid in records:
                old = read_json(self.path('Checks/' + rid + '.json'))
                if old['signature'] == signature and old['state'] == 'pending': raise RuntimeError('Earlier check has uncertain side effects; review it before another execution')
            before = self.inputs(pid, config['inputs']); folder = self.folder(pid)
            command = [v.replace('{python}', str(python_path(self.root))).replace('{root}', str(self.root)).replace('{project}', str(folder)) for v in config['argv']]
            rid = self.new_id(); rel = 'Checks/' + rid + '.json'; record = {'id': rid, 'project': pid, 'command': name, 'signature': signature, 'state': 'pending', 'created': time.time()}
            self.save(rel, record); log = self.path('Checks/' + rid + '.log'); proc = job = None
            try:
                with log.open('xb') as out:
                    self.check()
                    proc = subprocess.Popen([str(python_path(self.root)), '-B', '-I', str(self.root / 'Agent/verification_worker.py')],
                        stdin=subprocess.PIPE, stdout=out, stderr=out, cwd=folder, env=portable_env(self.root),
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **worker_process_options())
                    job = WorkerJob(proc); job.limit_memory(2 * 1024**3); job.check(); self.check()
                    proc.stdin.write((json.dumps({'command': command, 'cwd': str(folder)}) + '\n').encode()); proc.stdin.flush(); proc.stdin.close()
                    deadline = time.monotonic() + config.get('timeout', 60)
                    while proc.poll() is None:
                        self.check(); job.check(); require_space(self.root, for_outputs=True)
                        if time.monotonic() > deadline: raise TimeoutError('Project check exceeded its deadline; review uncertain effects')
                        if log.stat().st_size > 65536: raise ValueError('Project check output exceeded 64 KiB; review uncertain effects')
                        time.sleep(.05)
                output = bounded(log, 65536).decode('utf-8', 'replace'); self.check()
                after = self.inputs(pid, config['inputs'])
                result = {'exit_code': proc.returncode, 'output': output, 'project': pid, 'command': name,
                          'inputs': after, 'inputs_unchanged': before == after, 'config_sha256': digest(config), 'receipt': rid}
                if before != after: result['exit_code'] = -1; result['notice'] = 'Declared input files changed during the check; result is not accepted'
                record.update(state='complete', result=result); self.save(rel, record); return result
            finally:
                if job: job.close()
                if proc:
                    if proc.poll() is None: proc.kill()
                    proc.wait(timeout=10)
                log.unlink(missing_ok=True)

    def validate_command_result(self, result):
        self.check(); config = self.load(result['project']).get('commands', {}).get(result['command'])
        if not config or digest(config) != result['config_sha256'] or self.inputs(result['project'], list(result['inputs'])) != result['inputs']:
            raise ValueError('Project check configuration or declared inputs changed; run checks again')

    def review_check(self, rid):
        with self.lock('commands'):
            rel = 'Checks/' + identifier(rid) + '.json'; row = read_json(self.path(rel))
            if row['state'] != 'pending': raise ValueError('This check does not need review')
            row.update(state='reviewed', reviewed=time.time()); self.save(rel, row)
        return 'Uncertain check acknowledged. Any later run is an explicit new execution.'


class Edits(Workspace):
    def __init__(self, root, check=None): super().__init__(root, 'CodeEdits', check)
    def read(self, rid): return read_json(self.path('Items/' + identifier(rid) + '.json'))
    def list(self):
        rows = [self.read(rid) for rid in self.records('Items')]
        return sorted(rows, key=lambda row: row['created'], reverse=True)

    def prepare(self, path, before, after):
        if max(len(before or b''), len(after)) > MAX_EDIT: return None
        rows = self.list()
        if len(rows) >= 128 or sum(row.get('before_bytes',0) for row in rows) + len(before or b'') > 32 * 1024**2:
            raise ValueError('Edit journal is full (128 edits / 32 MiB); review and clear old undo records in Workspace → Code')
        row = {'id': self.new_id(), 'created': time.time(), 'path': portable_source(self.root, path),
               'before': True if before is not None else None, 'before_bytes':len(before or b''),
               'before_sha256': sha(before) if before is not None else None, 'after_sha256': sha(after), 'state': 'pending'}
        from runtime_policy import require_space
        require_space(self.root,len(before or b'')+4*1024**2,for_outputs=True)
        self.save('Items/' + row['id'] + '.json', row)
        if before is not None:
            image=self.path('Images/'+row['id']+'.bin');image.parent.mkdir(parents=True,exist_ok=True)
            self.check();atomic_write(image,before)
        return row

    def before_image(self,row):
        if row['before'] is None:return b''
        raw=bounded(self.path('Images/'+identifier(row['id'])+'.bin'))
        if sha(raw)!=row['before_sha256']:raise ValueError('Undo before-image checksum mismatch')
        return raw

    def discard(self,rid):
        with self.lock():
            row=self.read(rid)
            self.path('Images/'+identifier(rid)+'.bin').unlink(missing_ok=True)
            self.path('Items/'+rid+'.json').unlink()

    def finish(self, row):
        if row:
            row['state'] = 'written'; self.save('Items/' + row['id'] + '.json', row)

    def preview(self, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 32: raise ValueError('Select 1–32 edit IDs')
        rows = sorted((self.read(rid) for rid in ids), key=lambda r: r['created']); grouped = {}
        for row in rows: grouped.setdefault(json.dumps(row['path'], sort_keys=True), []).append(row)
        output = []; conflicts = []
        for group in grouped.values():
            self.check(); first, last = group[0], group[-1]; path = source_path(self.root, first['path'])
            current = bounded(path) if path.exists() else None
            if (sha(current) if current is not None else None) != last['after_sha256']: conflicts.append(str(path))
            before = self.before_image(first)
            patch = ''.join(difflib.unified_diff(before.decode('utf-8', 'replace').splitlines(True), (current or b'').decode('utf-8', 'replace').splitlines(True), fromfile=str(path) + ' (before)', tofile=str(path) + ' (current)'))
            output.append(patch[:8000])
        return {'diff': '\n'.join(output)[:32000], 'conflicts': conflicts, 'notice': 'Preview compares earliest selected before-image to current bytes. Output may be clipped. Undo is one edit at a time, newest first.'}

    def undo(self, rid, runtime):
        if runtime._account_role() != 'admin': raise PermissionError('Undo requires administrator role')
        with self.lock():
            row = self.read(rid); path = runtime.safe_path(str(source_path(self.root, row['path'])))
            if row['state'] not in ('written', 'pending'): raise ValueError('This edit is already undone')
            current = bounded(path) if path.exists() else None
            if current is None or sha(current) != row['after_sha256']: raise ValueError('File changed since this edit; undo refused without changing it')
            self.check()
            if row['before'] is None: path.unlink()
            else: atomic_write(path, self.before_image(row))
            row['state'] = 'undone'; self.save('Items/' + rid + '.json', row)
            writes=getattr(runtime,'_verification_writes',{})
            if row['before'] is None:writes.pop(str(path),None)
            elif str(path) in writes:writes[str(path)]=row['before_sha256']
            return {'success': True, 'path': str(path), 'undone': rid}


def atomic_write(path, data):
    import tempfile
    fd, name = tempfile.mkstemp(prefix='.portalai-edit-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if path.exists(): os.chmod(temp, path.stat().st_mode)
        os.replace(temp, path)
    finally: temp.unlink(missing_ok=True)


def write_tracked(runtime, path, text, before):
    from capability_tools import guard
    check = guard(runtime); journal = Edits(runtime.root, check)
    data = str(text).replace('\n', os.linesep).encode('utf-8')
    from runtime_policy import require_space
    require_space(runtime.root,len(data)+len(before or b'')+4*1024**2,for_outputs=True)
    with journal.lock():
        current = path.read_bytes() if path.exists() else None
        if current != before: raise ValueError('File changed after it was read; inspect it again before editing')
        row = journal.prepare(path, before, data); check(); path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, data)
        journal.finish(row)
    from result_verification import after_write
    receipt = json.loads(after_write(runtime, path, before))
    receipt['undo'] = row['id'] if row else None
    if not row: receipt['undo_notice'] = 'File exceeds 512 KiB; no undo snapshot was retained'
    return json.dumps(receipt, ensure_ascii=False)
