"""Opt-in, small deterministic capability probes. Never executes generated code."""
import json
from pathlib import Path
import platform
import time
from workspace_store import Workspace, identifier, read_json, digest

SUITE = 1
CASES = [
    ('coding', 'dedup', 'Python stable_unique(xs) must preserve first occurrence order. Which return expression is correct? A: sorted(set(xs)); B: list(dict.fromkeys(xs)); C: list(set(xs)); D: xs.sort(). Return only JSON {"choice":"letter"}.', {'choice': 'B'}),
    ('coding', 'alias', 'Python: rows=[[]]*2; rows[0].append(7). What is rows now? Return only JSON {"rows":...}.', {'rows': [[7], [7]]}),
    ('research', 'dated', 'Sources: [A] 2022 report: Cedar shipped 12 units. [B] 2023 report: Cedar shipped 9 units. How many units did Cedar ship in 2023? Return only JSON {"units":number,"source":"ID"}.', {'units': 9, 'source': 'B'}),
    ('research', 'missing', 'Source [A]: Cedar shipped 9 units in 2023. No prices or revenue are provided. What was its 2023 revenue? Return only JSON {"answer":"insufficient evidence"} if not supported.', {'answer': 'insufficient evidence'}),
    ('tools', 'inspect', 'Choose the next action. User asks what is in report.txt; file contents have not been read. Available: read_file, write_file, shell. Return only JSON {"tool":"name","path":"report.txt"}.', {'tool': 'read_file', 'path': 'report.txt'}),
    ('tools', 'uncertain', 'A payment tool timed out after dispatch; outcome unknown. Choose next step: A retry payment; B claim failure; C inspect transaction status before considering another payment. Return only JSON {"choice":"letter"}.', {'choice': 'C'}),
    ('conversation', 'constraint', 'Return only JSON with the keys greeting and count. greeting must be exactly "Hello". count must be the number of words in "We can work together".', {'greeting': 'Hello', 'count': 4}),
    ('conversation', 'correction', 'Earlier I said my preferred name was Alex. Correction: please call me Morgan. Return only JSON {"name":"my current preferred name"}, substituting the correct name.', {'name': 'Morgan'}),
]


def model_identity(root, mid):
    from runtime_policy import load_effective_policy, portable_path
    model = next(m for m in load_effective_policy(root)['models'] if m['id'] == mid)
    path = portable_path(root, model['path']); stat = path.stat()
    return digest({'id': mid, 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'policy': model})


def machine_identity(hardware):
    return digest({'system': platform.system(), 'machine': platform.machine(), 'processor': platform.processor(),
        'cpu_count': hardware['cpu_count'], 'ram': hardware['ram_total_bytes'],
        'gpus': [{k: g.get(k) for k in ('name', 'backend', 'total_bytes')} for g in hardware.get('gpus', [])]})


class Calibration(Workspace):
    def __init__(self, root, check=None): super().__init__(root, 'ModelCalibration', check)
    def read(self, rid):
        row=read_json(self.path('Runs/' + identifier(rid) + '.json'))
        if row['state']=='running':row={**row,'state':'unfinished','notice':'Saved state does not prove a worker is active. Runs never resume automatically.'}
        return row
    def list(self):
        return sorted((self.read(rid) for rid in self.records('Runs')), key=lambda r: r['created'], reverse=True)

    def run(self, runtime, models, cancel):
        from comparison_workers import installed, plans_for, ModelWorker
        from voice_memory import run_voice_stage
        from chat_model_switch import _require_idle, _owned_listener
        if runtime._account_role() != 'admin': raise PermissionError('Calibration requires administrator role')
        choices = {m['id'] for m in installed(self.root)}
        if not isinstance(models, list) or not 1 <= len(models) <= 3 or len(set(models)) != len(models) or any(m not in choices for m in models):
            raise ValueError('Choose one to three distinct installed model IDs')
        if len(self.records('Runs')) >= 32: raise ValueError('Calibration history reached 32 runs; review and clear old runs first')
        started = time.monotonic()
        def check():
            self.check()
            if cancel.is_set(): raise RuntimeError('Calibration stopped')
            if time.monotonic() - started > 600: raise TimeoutError('Calibration exceeded ten minutes; completed results remain saved')
        def idle():
            check()
            if _owned_listener()['open']: _require_idle()
        row = {'id': self.new_id(), 'created': time.time(), 'suite': SUITE, 'suite_sha256':digest(CASES), 'models': models, 'state': 'running', 'results': [], 'identities': {}, 'plans': {}}
        path = 'Runs/' + row['id'] + '.json'; self.save(path, row)
        def operation(stage_check):
            for mid in models:
                stage_check(); plans, hw = plans_for(self.root, [mid]); row['machine'] = machine_identity(hw)
                row['identities'][mid] = model_identity(self.root, mid)
                if plans[0]['model']['id']!=mid:raise ValueError('Current model policy does not admit '+mid+'; review variant/backend settings')
                before = time.monotonic()
                with ModelWorker(self.root, plans[0], stage_check) as worker:
                    if worker.plan['model']['id']!=mid:raise ValueError('Model admission changed; calibration stopped')
                    row['plans'][mid] = {'backend': worker.plan['backend']['backend'], 'gpu_layers': worker.plan['model']['gpu_layers'],
                                        'context_tokens': worker.plan['context_tokens'], 'load_seconds': round(time.monotonic() - before, 2)}
                    for domain, name, question, expected in CASES:
                        stage_check(); before = time.monotonic(); answer = worker.answer(question)
                        try: actual = json.loads(answer['answer'])
                        except (ValueError, TypeError): actual = None
                        passed = not answer['truncated'] and actual == expected
                        row['results'].append({'model': mid, 'domain': domain, 'case': name, 'passed': passed,
                            'seconds': round(time.monotonic() - before, 3), 'answer': answer['answer'][:3000], 'usage': answer.get('usage', {})})
                        self.save(path, row)
            return row
        try:
            run_voice_stage(self.root, 'model calibration', lambda: None, operation, check=check, handoff_check=idle, require_handoff=True)
            row.update(state='complete', seconds=round(time.monotonic() - started, 2)); self.save(path, row); return row
        except BaseException as exc:
            row.update(state='stopped_or_failed', error=str(exc)[:1500])
            try: self.save(path, row)
            except Exception: pass
            raise

    def recommend(self, domain='overall', max_seconds=30):
        from runtime_policy import detect_hardware, load_effective_policy
        if domain not in ('overall', 'coding', 'research', 'tools', 'conversation'): raise ValueError('Unknown capability domain')
        if type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 120: raise ValueError('Latency budget: 1–120 seconds per short answer')
        machine = machine_identity(detect_hardware()); policy = load_effective_policy(self.root); seen = set(); candidates = []
        for row in self.list():
            self.check()
            if row['state'] != 'complete' or row.get('suite') != SUITE or row.get('suite_sha256')!=digest(CASES) or row.get('machine') != machine or time.time() - row['created'] > 90 * 86400: continue
            for mid in row['models']:
                if mid in seen: continue
                try:
                    if model_identity(self.root, mid) != row['identities'].get(mid): continue
                except (OSError, StopIteration): continue
                seen.add(mid)
                results = [r for r in row['results'] if r['model'] == mid and (domain == 'overall' or r['domain'] == domain)]
                if not results: continue
                seconds = sum(r['seconds'] for r in results) / len(results)
                candidates.append({'model': mid, 'passed': sum(r['passed'] for r in results), 'cases': len(results),
                    'qualified':sum(r['passed'] for r in results)/len(results)>=.75,
                    'mean_seconds': round(seconds, 3), 'within_latency_budget': seconds <= max_seconds, 'run': row['id'], 'plan': row['plans'][mid]})
        candidates.sort(key=lambda r: (not (r['within_latency_budget'] and r['qualified']), -r['passed'] / r['cases'], r['mean_seconds']))
        return {'domain': domain, 'recommendation': candidates[0]['model'] if candidates and candidates[0]['within_latency_budget'] and candidates[0]['qualified'] else None,
            'current_selection': policy.get('selection', 'auto'), 'candidates': candidates,
            'notice': 'Recommendations require >=75% passed within the latency budget. Small deterministic probes, not a general intelligence benchmark. Speed depends on load and offload. Settings are unchanged; Apply is explicit. Hardware admission still applies.'}


def calibration_page(panel):
    store = Calibration(panel.root, panel.check); p = panel.pages['Calibration']
    panel.skin.label(p, 'Optional: eight short checks per model, sequential, at most ten minutes. Starts models only when you click Run; close games first. Stop retains completed results. No extra model downloads.').pack(fill='x')
    models = panel.field(p, 'Installed model IDs (1–3, comma-separated)')
    domain = panel.field(p, 'Capability: overall / coding / research / tools / conversation', 'overall')
    latency = panel.field(p, 'Maximum mean seconds per short answer', '30')
    tree = panel.tree(p, ('Created', 'State', 'Models')); chosen = {}
    def refresh():
        tree.delete(*tree.get_children())
        for row in store.list(): tree.insert('', 'end', iid=row['id'], values=(time.strftime('%Y-%m-%d %H:%M', time.localtime(row['created'])), row['state'], ', '.join(row['models'])))
    def run():
        panel.admin()
        if panel.chat and (panel.chat.busy or panel.chat.conversation_active.is_set()): raise ValueError('Finish chat and stop hands-free before calibration')
        mids = [m.strip() for m in models.get().split(',')]
        panel.job(lambda: store.run(panel.runtime, mids, panel.cancelled), lambda _: refresh())
    def recommend():
        task = domain.get().strip(); seconds = float(latency.get())
        def done(row): chosen.clear(); chosen.update(row)
        panel.job(lambda: store.recommend(task, seconds), done)
    def apply():
        panel.admin(); mid = chosen.get('recommendation')
        if not mid: raise ValueError('Get a current recommendation first')
        if panel.chat and (panel.chat.busy or panel.chat.conversation_active.is_set()): raise ValueError('Finish chat and stop hands-free before changing model settings')
        from tkinter import messagebox
        if not messagebox.askyesno('Apply measured model recommendation','Select '+mid+' for future chat requests? This replaces the current manual/automatic LLM selection; voice settings remain independent.',parent=panel):return
        from model_preferences import save
        save(panel.root, {'selection': mid})
        panel.show('Selected ' + mid + '. It will be admitted at the next chat request. Manual voice and other model settings are preserved.')
    def clear():
        panel.admin()
        from tkinter import messagebox
        if not messagebox.askyesno('Remove calibration report','Remove the selected report? Model files and preferences stay unchanged.',parent=panel):return
        rid = panel.selected(tree); path = store.path('Runs/' + identifier(rid) + '.json')
        path.unlink(); refresh(); panel.show('Selected calibration report removed.')
    def installed():
        from comparison_workers import installed
        panel.job(lambda: installed(panel.root))
    panel.buttons(p, [('List installed models', installed), ('Run optional calibration', run), ('Recommend', recommend),
                     ('Apply recommendation', apply), ('Refresh', refresh), ('View selected', lambda: panel.show(store.read(panel.selected(tree)))), ('Remove selected report', clear)])
    panel.invoke(refresh)
