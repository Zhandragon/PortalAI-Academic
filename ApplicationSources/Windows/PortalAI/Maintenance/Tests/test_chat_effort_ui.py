from pathlib import Path
from types import SimpleNamespace
import queue
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'ControlCenter')]
import chat_effort_ui as ui
import native_chat as chat


def controls():
    value = ui.ChatEffortControls.__new__(ui.ChatEffortControls)
    value.panel = SimpleNamespace(root=ROOT, busy=False, ev=queue.Queue(), _notice=Mock(),
                                  settings={'unrelated': 'preserved'}, tool_runtime=SimpleNamespace(set_request_effort=Mock()))
    value.profile = 'balanced'
    value.session_unlocked = False
    value.tools_profile = 'balanced'
    value.active_tools_profile = 'balanced'
    value.active_options = {}
    value.active_plan = None
    value.capability_data = {'profiles': {}}
    value.scale = Mock()
    value._render = Mock()
    value.refresh_capabilities = Mock()
    value._save_model_choice = Mock()
    value.policy = SimpleNamespace(save_preferences=Mock())
    value._module = Mock(return_value=value.policy)
    return value


class ChatEffortUITests(unittest.TestCase):
    def test_locked_profile_does_not_change_preference(self):
        control = controls()
        control.capability_data = {'profiles': {'deep': {
            'available': True, 'locked': True, 'can_apply': False, 'warning': 'May be slow'}}}
        control._changed('2')
        self.assertEqual(control.profile, 'balanced')
        control.policy.save_preferences.assert_not_called()
        control._save_model_choice.assert_not_called()
        self.assertIn('unlock', control.panel._notice.call_args.args[1])

    def test_busy_slider_does_not_change_active_request(self):
        control = controls()
        control.panel.busy = True
        control._changed('0')
        self.assertEqual(control.profile, 'balanced')
        control.policy.save_preferences.assert_not_called()
        control._save_model_choice.assert_not_called()

    def test_busy_checkbox_restores_saved_variant_without_writing(self):
        control = controls()
        control.panel.busy = True
        control._choice_signature = ('qwen4-q4', 'standard')
        control.uncensored = Mock()
        control._variant_changed()
        control._save_model_choice.assert_not_called()
        control.uncensored.set.assert_called_once_with(False)

    def test_failed_checkbox_save_restores_saved_variant(self):
        control = controls()
        control._choice_signature = ('qwen4-q4', 'standard')
        control.uncensored = Mock()
        control.uncensored.get.return_value = True
        control._save_model_choice.side_effect = OSError('drive unavailable')
        control._variant_changed()
        control._save_model_choice.assert_called_once_with(uncensored=True)
        control.uncensored.set.assert_called_once_with(False)
        control.panel._notice.assert_called_once()

    def test_only_chat_preference_is_persisted(self):
        control = controls()
        control.session_unlocked = True
        control._changed('0')
        control._save_model_choice.assert_called_once_with(level='fast')
        self.assertEqual(control.panel.settings, {'unrelated': 'preserved'})
        self.assertEqual(control.profile, 'fast')

    def test_failed_save_does_not_change_selection(self):
        control = controls()
        control._save_model_choice.side_effect = OSError('read only')
        control._changed('0')
        self.assertEqual(control.profile, 'balanced')
        control.panel._notice.assert_called_once()

    def test_tools_preference_is_separate_from_chat(self):
        control = controls()
        self.assertTrue(control._change_tools('fast'))
        control.policy.save_preferences.assert_called_once_with(ROOT, tools='fast')
        self.assertEqual(control.profile, 'balanced')
        self.assertEqual(control.tools_profile, 'fast')

    def test_preparation_propagates_cancellation_and_session_permission(self):
        control = controls()
        control.profile = 'fast'
        control.session_unlocked = True
        cancel = threading.Event()
        result = {'profile': 'fast', 'model': {'id': 'qwen4-q4'},
                  'completion_options': {'max_tokens': 1024,
                      'chat_template_kwargs': {'enable_thinking': False}, 'tools': []}}
        prepare = Mock(return_value=result)
        control._module.return_value = SimpleNamespace(prepare_chat=prepare)
        self.assertTrue(control.prepare_request(cancel))
        self.assertEqual(prepare.call_args.args, (ROOT, 'fast'))
        self.assertIs(prepare.call_args.kwargs['cancel_event'], cancel)
        self.assertTrue(prepare.call_args.kwargs['unlock_slow'])
        self.assertEqual(control.active_options, {'max_tokens': 1024,
            'chat_template_kwargs': {'enable_thinking': False}})
        self.assertIsNone(control.panel._model_context_limit)
        control.panel.tool_runtime.set_request_effort.assert_called_once_with('balanced', True)

    def test_cancelled_preparation_cannot_enable_inference(self):
        control = controls()
        cancel = threading.Event()
        def prepare(*args, **kwargs):
            cancel.set()
            return {'completion_options': {'max_tokens': 8192}}
        control._module.return_value = SimpleNamespace(prepare_chat=prepare)
        self.assertFalse(control.prepare_request(cancel))
        self.assertEqual(control.active_options, {})
        self.assertIsNone(control.active_plan)
        self.assertTrue(control.panel.ev.empty())

    def test_already_cancelled_request_does_not_switch_models(self):
        control = controls()
        cancel = threading.Event()
        cancel.set()
        self.assertFalse(control.prepare_request(cancel))
        control._module.assert_not_called()

    def test_fast_images_require_vision_admission_without_discarding_attachment(self):
        control = controls()
        control.profile = 'fast'
        control.panel.session = {'messages': [{'role': 'user', 'content': 'Inspect this',
            'attachments': [{'path': 'Data/Chat/test.png', 'mime': 'image/png'}]}]}
        prepare = Mock(side_effect=RuntimeError('No matching vision model'))
        control._module.return_value = SimpleNamespace(prepare_chat=prepare)
        with self.assertRaisesRegex(RuntimeError, 'matching vision'):
            control.prepare_request(threading.Event())
        self.assertTrue(prepare.call_args.kwargs['require_vision'])
        self.assertEqual(len(control.panel.session['messages'][0]['attachments']), 1)

    def test_compacted_old_image_does_not_block_text_request(self):
        self.assertFalse(ui.requires_vision({'context_state': {'cursor': 1}, 'messages': [
            {'role': 'user', 'attachments': [{'path': 'old.png'}]}, {'role': 'user', 'content': 'Hello'}]}))

    def test_failed_preparation_executes_no_inference_or_tool(self):
        panel = chat.NativeChat.__new__(chat.NativeChat)
        panel.settings = dict(chat.DEFAULT_SETTINGS)
        panel.effort = SimpleNamespace(prepare_request=Mock(side_effect=RuntimeError('profile locked')))
        panel.cancel_event = threading.Event()
        panel.ev = queue.Queue()
        panel.compact_context_if_needed = Mock()
        panel.stream_completion = Mock()
        panel.tool_runtime = SimpleNamespace(execute=Mock())
        panel.agent_worker('unchanged-session')
        panel.compact_context_if_needed.assert_not_called()
        panel.stream_completion.assert_not_called()
        panel.tool_runtime.execute.assert_not_called()
        self.assertEqual(panel.ev.get()[0], 'error')
        self.assertEqual(panel.ev.get()[0], 'done')

    def test_context_reserves_actual_profile_output_budget(self):
        panel = chat.NativeChat.__new__(chat.NativeChat)
        panel.settings = {'max_output_tokens': 1024}
        panel.effort = SimpleNamespace(active_options={'max_tokens': 8192})
        self.assertEqual(panel._request_output_tokens(), 8192)

    def test_labels_distinguish_model_size(self):
        self.assertEqual(ui.model_label({'id': 'qwen27-q4'}), '27B Abliterated')
        self.assertEqual(ui.model_label({'id': 'qwen4-q4'}), '4B')
        self.assertEqual(ui.model_label({'id': 'qwen1.7-q8'}), '1.7B')

    def test_tool_environment_clears_stale_unlock(self):
        runtime = chat.ToolRuntime.__new__(chat.ToolRuntime)
        source = {'PORTALAI_TOOL_EFFORT': 'deep', 'PORTALAI_TOOL_EFFORT_UNLOCKED': '1', 'OTHER': 'keep'}
        self.assertEqual(runtime._effort_env(source), {'OTHER': 'keep', 'PORTALAI_CHAT_IMAGE_DEFAULTS':'1'})
        runtime.set_request_effort('fast', False)
        self.assertEqual(runtime._effort_env(source), {
            'PORTALAI_TOOL_EFFORT': 'fast', 'PORTALAI_TOOL_EFFORT_UNLOCKED': '0', 'OTHER': 'keep',
            'PORTALAI_CHAT_IMAGE_DEFAULTS':'1'})
        self.assertEqual(source['PORTALAI_TOOL_EFFORT'], 'deep')

    def test_explicit_media_command_parameters_are_not_rewritten(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        python = root / 'Runtime/BootstrapPython/python.exe'
        python.parent.mkdir(parents=True)
        python.touch()
        runtime = chat.ToolRuntime(root, {'tool_timeout_seconds': 30})
        runtime.set_request_effort('fast', False)
        process = Mock(returncode=0)
        process.communicate.return_value = ('done', '')
        command = 'python Agent/ai_tools.py image "example" --width 1024 --height 768 --steps 31'
        with patch.object(chat.subprocess, 'Popen', return_value=process) as popen:
            runtime.shell(command)
        forwarded = popen.call_args.args[0]
        self.assertTrue(forwarded.endswith('Agent/ai_tools.py image "example" --width 1024 --height 768 --steps 31'))
        self.assertEqual(popen.call_args.kwargs['env']['PORTALAI_TOOL_EFFORT'], 'fast')

    def test_explicit_scientific_precision_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('Agent/science_tools.py', 'Runtime/BootstrapPython/python.exe'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            (root / 'Runtime/SciencePackages').mkdir()
            runtime = chat.ToolRuntime(root, {'tool_timeout_seconds': 30})
            runtime.set_request_effort('fast', False)
            process = Mock(returncode=0)
            original = {'tolerance': 1e-10, 'precision': 80, 'iterations': 900}
            def communicate(**kwargs):
                request = next((root / 'Data/Science/Requests').glob('*.json'))
                self.assertEqual(json.loads(request.read_text())['input'], original)
                return '{"success":true}', ''
            process.communicate.side_effect = communicate
            with patch.object(chat.subprocess, 'Popen', return_value=process) as popen:
                self.assertEqual(runtime.science('example', original), '{"success":true}')
            self.assertEqual(popen.call_args.kwargs['env']['PORTALAI_TOOL_EFFORT'], 'fast')
            self.assertEqual(original, {'tolerance': 1e-10, 'precision': 80, 'iterations': 900})


if __name__ == '__main__':
    unittest.main()
