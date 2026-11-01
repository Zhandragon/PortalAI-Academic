"""Bounded, independent acceptance checks. No model-generated code is executed."""
import ast
import hashlib
import json
import time
from pathlib import Path
from workspace_store import Workspace, identifier, read_json, portable_source, source_path

MAX_FILE = 2 * 1024**2


def file_bytes(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError('Verification reads at most 2 MiB per file; use a focused check')
    return data


def inspect_bytes(path, data):
    """Parsing verifies syntax/structure, never imports the generated program."""
    suffix = Path(path).suffix.lower()
    if suffix == '.py':
        ast.parse(data, filename=str(path))
        return 'Python syntax'
    if suffix == '.json':
        def constant(value): raise ValueError('Non-JSON constant: ' + value)
        def pairs(rows):
            obj = {}
            for key, value in rows:
                if key in obj: raise ValueError('Duplicate JSON key: ' + key)
                obj[key] = value
            return obj
        json.loads(data, parse_constant=constant, object_pairs_hook=pairs)
        return 'JSON syntax and unique keys'
    return 'file readback'


class Verifications(Workspace):
    def __init__(self, runtime, check=None):
        super().__init__(runtime.root, 'Verification', check)
        self.runtime = runtime

    def run(self, checks):
        if not isinstance(checks, list) or not 1 <= len(checks) <= 16:
            raise ValueError('Supply 1–16 explicit checks')
        results = []
        with self.lock():
            if len(self.records('Runs')) >= 256:
                raise ValueError('Verification history reached 256 records; review and clear it in Workspace')
            for spec in checks:
                self.check()
                if not isinstance(spec, dict): raise ValueError('Each check must be an object')
                kind = spec.get('kind')
                item = {'check': spec, 'success': False}
                try:
                    if kind == 'test':
                        from code_projects import CodeProjects
                        item.update(CodeProjects(self.root, self.check).run_command(
                            spec['project'], spec['command'], self.runtime))
                        item['success'] = item.get('exit_code') == 0
                    else:
                        path = self.runtime.safe_path(spec['path'])
                        data = file_bytes(path)
                        item.update(path=portable_source(self.root, path), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
                        if kind == 'file':
                            item['checked'] = inspect_bytes(path, data)
                            item['success'] = bool(data) or spec.get('allow_empty') is True
                        elif kind == 'contains':
                            text = spec.get('text')
                            if not isinstance(text, str) or not 1 <= len(text) <= 4000: raise ValueError('contains needs 1–4000 literal characters')
                            item['success'] = text in data.decode('utf-8-sig')
                        elif kind == 'sha256':
                            item['success'] = item['sha256'] == spec.get('expected')
                        elif kind == 'json_value':
                            inspect_bytes(Path('output.json'),data)
                            value = json.loads(data)
                            pointer = spec.get('pointer', [])
                            if not isinstance(pointer, list) or len(pointer) > 16: raise ValueError('Use a JSON key/index array of at most 16 elements')
                            for key in pointer:
                                if isinstance(value, list) and (type(key) is int or isinstance(key,str) and key.isascii() and key.isdecimal()): value = value[int(key)]
                                elif isinstance(value, dict) and isinstance(key, str): value = value[key]
                                else: raise ValueError('JSON key/index does not match its container')
                            if 'expected_json' in spec:
                                if 'expected' in spec:raise ValueError('Use expected_json alone for json_value; expected is the legacy alternative')
                                literal=spec['expected_json']
                                if not isinstance(literal,str) or not 1<=len(literal)<=4000:raise ValueError('expected_json must be a JSON-encoded string of 1–4000 characters')
                                inspect_bytes(Path('expected.json'),literal.encode('utf-8'))
                                expected=json.loads(literal)
                            elif 'expected' in spec:expected=spec['expected']  # Existing API callers/receipts.
                            else:raise ValueError('json_value requires expected_json, e.g. "10" for number 10')
                            from workspace_store import encoded
                            item['success'] = encoded(value)==encoded(expected)
                        else: raise ValueError('Check kinds: file, contains, sha256, json_value, test')
                except (OSError, ValueError, SyntaxError, KeyError, IndexError, UnicodeError) as exc:
                    item['error'] = str(exc)[:1200]
                self.check(); results.append(item)
            row = {'id': self.new_id(), 'created': time.time(), 'success': all(r['success'] for r in results),
                   'results': results, 'notice': 'Only these predicates were checked. Passing does not prove all user requirements or safety.'}
            from workspace_store import encoded
            used=sum(self.path('Runs/'+rid+'.json').stat().st_size for rid in self.records('Runs'))
            if used+len(encoded(row))>16*1024**2:raise ValueError('Verification history reached 16 MiB; clear completed checks in Workspace')
            self.save('Runs/' + row['id'] + '.json', row)
            return row

    def read(self, rid, *, fresh=False):
        row = read_json(self.path('Runs/' + identifier(rid) + '.json'))
        if fresh:
            for result in row['results']:
                self.check()
                if 'path' in result:
                    path = self.runtime.safe_path(str(source_path(self.root, result['path'])))
                    if hashlib.sha256(file_bytes(path)).hexdigest() != result['sha256']:
                        raise ValueError('Verified file changed; run the check again')
                if result['check']['kind'] == 'test' and result.get('receipt'):
                    from code_projects import CodeProjects
                    CodeProjects(self.root, self.check).validate_command_result(result)
        return row


def begin_request(runtime,session=None,index=-1):
    runtime._verification_writes = {}
    runtime._verification_receipts = []
    runtime._verification_latest = {}
    runtime._verification_overflow = False
    runtime._verification_receipt_overflow = False
    if not session:return
    from workspace_store import digest
    for message in session.get('messages',[])[index+1:]:
        if message.get('role')!='tool' or message.get('execution',{}).get('outcome')!='returned':continue
        try:row=json.loads(message.get('content',''))
        except (TypeError,ValueError):continue
        if not isinstance(row,dict):continue
        if message.get('name') in ('write_file','edit_file') and row.get('success') and row.get('path') and row.get('sha256'):
            name=str(source_path(runtime.root,row['portable_path'])) if row.get('portable_path') else row['path']
            if len(runtime._verification_writes)<64 or name in runtime._verification_writes:runtime._verification_writes[name]=row['sha256']
            else:runtime._verification_overflow=True
        if message.get('name')=='verify' and row.get('id') and isinstance(row.get('results'),list):
            specs=[r['check'] for r in row['results']]
            runtime._verification_latest[digest(specs)]=row['id']
    runtime._verification_receipt_overflow=len(runtime._verification_latest)>16
    runtime._verification_receipts=list(runtime._verification_latest.values())[-16:]



def after_write(runtime, path, before):
    from coding_stall import write_receipt
    receipt = json.loads(write_receipt(path, before))
    receipt['portable_path']=portable_source(runtime.root,path)
    writes = getattr(runtime, '_verification_writes', {})
    if len(writes) >= 64 and str(path) not in writes:runtime._verification_overflow=True
    if len(writes) < 64 or str(path) in writes:
        writes[str(path)] = receipt['sha256']
        runtime._verification_writes = writes
    try:
        data = file_bytes(path)
        receipt['verification'] = {'success': True, 'checked': inspect_bytes(path, data), 'behavior_tested': False}
    except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
        receipt['verification'] = {'success': False, 'error': str(exc)[:1000], 'behavior_tested': False}
    receipt['notice'] = 'File written; inspect verification separately. Runtime behavior and requirements need relevant checks.'
    return json.dumps(receipt, ensure_ascii=False)


def completion_audit(chat):
    """No inference or test execution here; reopen the files actually written."""
    runtime = chat.tool_runtime
    writes = getattr(runtime, '_verification_writes', {})
    failures = ['More than 64 edited files: automatic readback coverage is incomplete.'] if getattr(runtime,'_verification_overflow',False) else []
    for name, expected in writes.items():
        chat._check_login()
        if chat.cancel_event.is_set(): raise RuntimeError('Verification stopped')
        try:
            path = runtime.safe_path(name); data = file_bytes(path)
            if hashlib.sha256(data).hexdigest() != expected: raise ValueError('changed after the last write')
            inspect_bytes(path, data)
        except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
            failures.append(Path(name).name + ': ' + str(exc)[:200])
    receipts = getattr(runtime, '_verification_receipts', [])
    checks = []
    if getattr(runtime,'_verification_receipt_overflow',False):failures.append('More than 16 saved acceptance batches: automatic verification coverage is incomplete.')
    for rid in receipts[-16:]:
        try:
            row = Verifications(runtime, chat._check_login).read(rid, fresh=True)
            checks.append(row)
            if not row['success']: failures.append('Acceptance checks failed: ' + rid)
        except Exception as exc:
            failures.append('Acceptance check is stale/unavailable: ' + str(exc)[:200])
    from task_notebook import request_index
    recent=chat.session.get('messages',[])[request_index(chat.session)+1:]
    if any(r.get('role')=='tool' and r.get('execution',{}).get('dispatched') and r.get('execution',{}).get('effectful') and r.get('execution',{}).get('outcome')=='uncertain' for r in recent):
        failures.append('At least one dispatched tool has an uncertain outcome; inspect its effects before retrying or claiming success.')
    plan = (chat.session.get('task_notebooks') or {}).get(str(request_index(chat.session)))
    if plan:
        for step in plan.get('steps',[]):
            if step.get('status')!='verified':failures.append('The task plan still has unverified or blocked steps.');break
            try:
                proof=Verifications(runtime,chat._check_login).read(step.get('verification',''),fresh=True)
                if not proof['success']:raise ValueError('checks failed')
            except Exception as exc:failures.append('Plan verification is stale or missing: '+str(exc)[:200])
    if failures:
        return '\n\nVerification incomplete: ' + '; '.join(failures[:8]), False
    if writes:
        tests = any(r.get('check', {}).get('kind') == 'test' and r.get('success') for row in checks for r in row['results'])
        return ('\n\nVerification: reopened ' + str(len(writes)) + ' edited file(s); checked supported Python/JSON syntax. ' +
                ('The configured test checks passed; only their stated coverage is verified.' if tests else 'Runtime behavior has not been tested by the verification system.')), True
    return '', True
