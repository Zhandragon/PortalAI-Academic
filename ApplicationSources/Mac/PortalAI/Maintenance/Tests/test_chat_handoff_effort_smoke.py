"""The real GUI preparation is shared with headless handoff checks."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('handoff_effort_smoke', ROOT/'Tools/smoke_chat_handoff.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class HandoffEffortSmokeTests(unittest.TestCase):
    def test_real_gui_preparation_keeps_test_fence_fast_budget_and_tool_default(self):
        panel = SimpleNamespace(root=ROOT, session={'messages': []}, ev=Mock(), tool_runtime=Mock())
        controls = smoke.headless_effort(panel, 'fast', 12345.0)
        plan = {'profile': 'fast', 'model': {'id': 'qwen4-q4'}, 'max_tool_rounds': 4,
                'completion_options': {'max_tokens': 1024, 'chat_template_kwargs': {'enable_thinking': False}}}
        with patch('chat_model_switch.prepare_chat', return_value=plan) as prepare:
            self.assertTrue(controls.prepare_request(threading.Event()))
        self.assertEqual(prepare.call_args.kwargs['requested_at'], 12345.0)
        self.assertFalse(prepare.call_args.kwargs['unlock_slow'])
        self.assertEqual(controls.active_options, plan['completion_options'])
        self.assertIs(controls.active_plan, plan)
        panel.tool_runtime.set_request_effort.assert_called_once_with('balanced', False)
        panel.ev.put.assert_called_with(('effort_applied', plan))

    def test_cancelled_request_does_not_prepare_or_change_tools(self):
        panel = SimpleNamespace(root=ROOT, session={'messages': []}, ev=Mock(), tool_runtime=Mock())
        controls = smoke.headless_effort(panel, 'fast', 12345.0)
        cancel = threading.Event(); cancel.set()
        with patch('chat_model_switch.prepare_chat') as prepare:
            self.assertFalse(controls.prepare_request(cancel))
        prepare.assert_not_called()
        panel.tool_runtime.set_request_effort.assert_not_called()


if __name__ == '__main__':
    unittest.main()
