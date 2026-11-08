"""Small regressions for defects found by the r72 logic review; no inference."""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

from test_capability_intelligence import Fixture
from test_chat_model_switch import Scenario


class LogicAuditTests(Fixture):
    def test_confirmed_workflow_step_retains_its_declared_next_target(self):
        from workflows import Workflows
        for target in ('end', 'answer'):
            with self.subTest(target=target):
                calls = []
                def execute(kind, step, args, operation):
                    calls.append(step['id'])
                    if step['id'] == 'first':
                        raise OSError('Reply lost after the effect')
                    return {'success': True}
                store = Workflows(self.root, execute=execute)
                template = store.put({'version': 1, 'name': 'Review branch', 'steps': [
                    {'id': 'first', 'kind': 'tool', 'tool': 'write_file', 'next': target},
                    {'id': 'skip', 'kind': 'tool', 'tool': 'write_file'},
                    {'id': 'answer', 'kind': 'output', 'value': 'done'}]})
                run = store.start(template['id'], {})['id']
                with self.assertRaises(OSError): store.advance(run)
                store.review(run, 'confirmed', {'success': True})
                result = store.advance(run)
                self.assertEqual(calls, ['first'])
                self.assertEqual(result['state'], 'complete')
                self.assertEqual('answer' in result['results'], target == 'answer')

    def test_failed_tool_envelope_stops_workflow_without_automatic_retry(self):
        from workflows import Workflows
        for failure in ({'success': False, 'error': 'Missing runtime'},
                        {'ok': False, 'error': 'Request failed'}):
            with self.subTest(failure=failure):
                calls = []
                def execute(kind, step, args, operation):
                    calls.append(step['id'])
                    return failure
                store = Workflows(self.root, execute=execute)
                template = store.put({'version': 1, 'name': 'Failure gate', 'steps': [
                    {'id': 'science', 'kind': 'tool', 'tool': 'science'},
                    {'id': 'later', 'kind': 'tool', 'tool': 'write_file'}]})
                run = store.start(template['id'], {})['id']
                with self.assertRaisesRegex(RuntimeError, 'error'): store.advance(run)
                row = store.run(run)
                self.assertEqual(row['state'], 'review')
                self.assertEqual(row['pending']['step'], 'science')
                with self.assertRaises(RuntimeError): store.advance(run)
                self.assertEqual(calls, ['science'])

    def test_science_missing_optional_runtime_returns_structured_error(self):
        import native_chat
        (self.root / 'Agent/science_tools.py').touch()
        python = self.root / 'python.exe'
        python.touch()
        runtime = native_chat.ToolRuntime.__new__(native_chat.ToolRuntime)
        runtime.root = self.root
        runtime._account_role = lambda: 'admin'
        with patch.object(native_chat, 'bootstrap_python', return_value=str(python)):
            result = json.loads(runtime.science('help'))
        self.assertFalse(result['success'])
        self.assertIn('runtime', result['error'].lower())

    def test_crlf_write_keeps_one_line_ending_and_exact_undo(self):
        from code_projects import write_tracked, Edits
        path = self.root / 'lines.txt'
        original = b'original\r\n'
        path.write_bytes(original)
        receipt = json.loads(write_tracked(self.runtime, path, 'first\r\nsecond\r\n', original))
        self.assertEqual(path.read_bytes(), ('first'+os.linesep+'second'+os.linesep).encode())
        Edits(self.root).undo(receipt['undo'], self.runtime)
        self.assertEqual(path.read_bytes(), original)

    def test_gpu_only_specialist_does_not_reuse_partial_saved_plan(self):
        import chat_model_switch as switch
        with Scenario() as scenario:
            scenario.plan['model'].update(gpu_layers=64, layers=64)
            scenario.command[-1] = '64'
            admitted = copy.deepcopy(scenario.plan)
            admitted.update(level='fast', preview_only=False, backend={})
            admitted['model']['gpu_layers'] = 12
            admitted['command'][-1] = '12'
            scenario.current = scenario.identity(admitted['command'])
            (scenario.runtime / 'hardware_launch_plan.json').write_text(json.dumps(admitted))
            result = switch.prepare_chat(scenario.root, 'fast', _require_full_gpu=True)
            self.assertTrue(result['changed'])
            self.assertEqual(result['model']['gpu_layers'], 64)
            scenario.admit.assert_called_once()

    def test_gpu_only_specialist_does_not_reuse_partial_preview(self):
        import chat_model_switch as switch
        with Scenario() as scenario:
            scenario.plan['model'].update(gpu_layers=12, layers=64)
            scenario.current = scenario.identity(scenario.command)
            with self.assertRaisesRegex(RuntimeError, 'fully fit'):
                switch.prepare_chat(scenario.root, 'fast', _require_full_gpu=True)
            scenario.spawn.assert_not_called()

    def test_gpu_only_specialist_reuses_fully_loaded_model(self):
        import chat_model_switch as switch
        with Scenario() as scenario:
            scenario.plan['model'].update(gpu_layers=64, layers=64)
            scenario.current = scenario.identity(scenario.command)
            result = switch.prepare_chat(scenario.root, 'fast', _require_full_gpu=True)
            self.assertFalse(result['changed'])
            scenario.begin.assert_not_called()
