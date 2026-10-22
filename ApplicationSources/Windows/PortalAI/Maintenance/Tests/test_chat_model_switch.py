from contextlib import contextmanager, ExitStack
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import subprocess
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
import chat_model_switch as switch
import effort_policy


class Scenario:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'Agent/.runtime'
        self.runtime.mkdir(parents=True)
        self.command_file = self.runtime / 'qwen_launch_command.txt'
        self.command_file.write_text('original command')
        self.model = {'id': 'qwen4-q4', 'path': 'LLM/models/small.gguf',
                      'absolute_path': str(self.root / 'LLM/models/small.gguf'),
                      'projector': None, 'context_tokens': 8192}
        self.command = [str(self.root / 'LLM/backend/llama-server.exe'), '-m', self.model['absolute_path'],
                        '-c', '8192', '--device', 'CUDA0', '-ngl', '37']
        self.plan = {'model': self.model, 'command': self.command, 'context_tokens': 8192,
                     'max_tool_rounds': 4, 'completion_options': {'max_tokens': 1024}}
        self.old = self.identity(self.command[:2] + [str(self.root / 'LLM/models/large.gguf')] + self.command[3:], 111)
        self.current = self.old
        self.generation = {}
        self.state = {'active': True, 'generation_token': 'our-token'}
        self.depth = 0
        self.after_spawn = lambda: None
        self.on_mutex = lambda: None
        self.process = Mock(pid=222)
        self.process.poll.return_value = None
        self.process.wait.return_value = 0
        self.spawn = Mock(side_effect=self._spawn)
        self.restore = Mock(side_effect=self._restore)
        self.idle = Mock()
        self.release = Mock()
        self.begin = Mock(side_effect=self._begin)
        self.admit = Mock(return_value=self.plan)
        self.stack = ExitStack()

    @staticmethod
    def identity(command, pid=222):
        return {'open': True, 'portable_qwen': True,
                'listeners': [{'pid': pid, 'portable_qwen': True, 'command_line': list(command)}]}

    @contextmanager
    def mutex(self, **kwargs):
        if self.depth:
            raise AssertionError('Nested lifecycle mutex would deadlock on Linux')
        self.depth += 1
        try:
            self.on_mutex()
            yield
        finally:
            self.depth -= 1

    def _begin(self, reason, start_guard=None):
        with self.mutex():
            if start_guard:
                start_guard()
            self.generation = {'token': 'our-token'}
            self.current = {'open': False, 'portable_qwen': False, 'listeners': []}
        return self.state

    def _spawn(self, root, command):
        self.current = self.identity(command)
        self.after_spawn()
        return self.process

    def _restore(self, state):
        with self.mutex():
            if self.generation.get('token') != state['generation_token']:
                return {'restored': False, 'stale_generation': True}
            self.current = self.old
            self.generation = {}
            return {'restored': True, 'ready': True}

    def __enter__(self):
        values = {
            '_qwen_lifecycle_mutex': self.mutex,
            '_read_qwen_generation': lambda: self.generation,
            '_generation_current': lambda state: self.generation.get('token') == state['generation_token'],
            '_listener_identity': lambda: copy.deepcopy(self.current),
            '_qwen_health_ready': lambda: True,
            'acquire_gpu_lease': lambda *args, **kwargs: 'our-lease',
            'release_gpu_lease': self.release,
            'qwen_gpu_handoff_begin': self.begin,
            'qwen_gpu_handoff_end': self.restore,
            '_remember_qwen_launch': lambda *args: self.command_file.write_text('new command'),
            '_mark_handoff_done': Mock(),
            '_clear_generation_if_current': lambda state: self.generation.clear(),
        }
        for key, value in values.items():
            self.stack.enter_context(patch.object(switch.service, key, value))
        for key, value in {'ROOT': self.root, '_spawn': self.spawn, '_require_idle': self.idle,
                           'require_space': Mock()}.items():
            self.stack.enter_context(patch.object(switch, key, value))
        self.stack.enter_context(patch.object(effort_policy, 'check_chat_permission', return_value={}))
        self.stack.enter_context(patch.object(effort_policy, 'capabilities', return_value={'profiles': {'fast': self.plan}}))
        self.stack.enter_context(patch.object(effort_policy, 'require_chat_plan', self.admit))
        return self

    def __exit__(self, *args):
        self.stack.close()
        self.temp.cleanup()


class ChatModelSwitchTests(unittest.TestCase):
    def test_vision_request_passes_through_existing_owned_handoff_and_admission(self):
        with Scenario() as scenario:
            scenario.model.update(id='qwen-vl2-q4', projector='vision.mmproj')
            scenario.command += ['--mmproj', str(scenario.root/'vision.mmproj'), '--image-min-tokens', '1024']
            result = switch.prepare_chat(scenario.root, 'fast', require_vision=True)
            self.assertTrue(result['changed'])
            self.assertTrue(scenario.admit.call_args.kwargs['require_vision'])
            scenario.begin.assert_called_once()
            scenario.release.assert_called_once_with('our-lease')

    def test_saved_vision_plan_is_not_reused_for_text_request(self):
        with Scenario() as scenario:
            admitted = copy.deepcopy(scenario.plan)
            admitted.update(level='fast', preview_only=False, backend={}, vision_request=True)
            admitted['model'].update(id='qwen-vl2-q4', projector='vision.mmproj', absolute_path=str(scenario.root/'vision.gguf'))
            admitted['command'][2] = admitted['model']['absolute_path']
            admitted['command'] += ['--mmproj', str(scenario.root/'vision.mmproj'), '--image-min-tokens', '1024']
            scenario.current = scenario.identity(admitted['command'])
            (scenario.runtime/'hardware_launch_plan.json').write_text(json.dumps(admitted))
            self.assertTrue(switch.prepare_chat(scenario.root, 'fast')['changed'])
            scenario.begin.assert_called_once()

    def test_admitted_small_vision_fallback_is_reused_without_reload_loop(self):
        with Scenario() as scenario:
            admitted = copy.deepcopy(scenario.plan)
            admitted.update(level='fast', preview_only=False, backend={}, vision_request=True)
            admitted['model'].update(id='qwen-vl2-q4', projector='vision.mmproj', absolute_path=str(scenario.root/'vision.gguf'))
            admitted['command'][2] = admitted['model']['absolute_path']
            admitted['command'] += ['--mmproj', str(scenario.root/'vision.mmproj'), '--image-min-tokens', '1024']
            scenario.current = scenario.identity(admitted['command'])
            (scenario.runtime/'hardware_launch_plan.json').write_text(json.dumps(admitted))
            scenario.model['projector'] = 'larger-vision.mmproj'
            with patch.object(effort_policy, 'check_chat_permission', return_value={'vision_request':True}):
                result = switch.prepare_chat(scenario.root, 'fast', require_vision=True)
            self.assertFalse(result['changed'])
            self.assertEqual(result['model']['id'], 'qwen-vl2-q4')
            scenario.begin.assert_not_called()

    def test_vision_listener_without_minimum_is_replaced_normally(self):
        with Scenario() as scenario:
            scenario.model.update(id='qwen-vl2-q4', projector='vision.mmproj')
            scenario.command += ['--mmproj', str(scenario.root/'vision.mmproj'), '--image-min-tokens', '1024']
            scenario.current = scenario.identity(scenario.command[:-2])
            result = switch.prepare_chat(scenario.root, 'fast', require_vision=True)
            self.assertTrue(result['changed'])
            scenario.begin.assert_called_once()
            scenario.release.assert_called_once_with('our-lease')

    def test_vision_listener_reuse_requires_matching_image_options_and_projector(self):
        with Scenario() as scenario:
            scenario.model.update(id='qwen-vl2-q4', projector='vision.mmproj')
            scenario.command += ['--mmproj', str(scenario.root/'vision.mmproj'), '--image-min-tokens', '1024']
            for mode in ('good','missing','different_minimum','different_projector','unexpected_maximum','tiny_context'):
                command = list(scenario.command)
                if mode=='missing':command=command[:-2]
                elif mode=='different_minimum':command[-1]='512'
                elif mode=='different_projector':command[command.index('--mmproj')+1]=str(scenario.root/'other.mmproj')
                elif mode=='unexpected_maximum':command+=['--image-max-tokens','1024']
                elif mode=='tiny_context':command[command.index('-c')+1]='2048'
                self.assertEqual(switch._matches(scenario.identity(command),scenario.model,8192,scenario.command),mode=='good',mode)

    def test_repeated_matching_vision_reconnect_does_not_reload(self):
        with Scenario() as scenario:
            scenario.model.update(id='qwen-vl2-q4', projector='vision.mmproj')
            scenario.command += ['--mmproj', str(scenario.root/'vision.mmproj'), '--image-min-tokens', '1024']
            scenario.current = scenario.identity(scenario.command)
            for _ in range(3):
                self.assertFalse(switch.prepare_chat(scenario.root,'fast',require_vision=True)['changed'])
            scenario.begin.assert_not_called()
            scenario.spawn.assert_not_called()

    def test_reuses_exact_healthy_owned_model(self):
        with Scenario() as scenario:
            scenario.current = scenario.identity(scenario.command)
            result = switch.prepare_chat(scenario.root, 'fast')
            self.assertFalse(result['changed'])
            scenario.begin.assert_not_called()
            scenario.admit.assert_not_called()
            scenario.spawn.assert_not_called()
            scenario.release.assert_called_once_with('our-lease')

    def test_different_backend_is_not_mistaken_for_optimized_model(self):
        with Scenario() as scenario:
            old_command = list(scenario.command)
            old_command[0] = str(scenario.root / 'LLM/cpu/llama-server.exe')
            scenario.current = scenario.identity(old_command)
            result = switch.prepare_chat(scenario.root, 'fast')
            self.assertTrue(result['changed'])
            scenario.spawn.assert_called_once()

    def test_actually_admitted_small_partial_profile_is_reused(self):
        with Scenario() as scenario:
            admitted = copy.deepcopy(scenario.plan)
            admitted.update(level='fast', preview_only=False, backend={})
            admitted['model'].update(id='qwen1.7-q8', absolute_path=str(scenario.root/'LLM/models/tiny.gguf'))
            admitted['command'][2] = admitted['model']['absolute_path']
            admitted['command'][-1] = '12'
            scenario.current = scenario.identity(admitted['command'])
            (scenario.runtime/'hardware_launch_plan.json').write_text(json.dumps(admitted))
            result = switch.prepare_chat(scenario.root, 'fast')
            self.assertFalse(result['changed'])
            self.assertEqual(result['model']['id'], 'qwen1.7-q8')
            scenario.begin.assert_not_called()
            scenario.admit.assert_not_called()

    def test_saved_profile_without_matching_owned_listener_is_not_reused(self):
        with Scenario() as scenario:
            saved = {**scenario.plan, 'level':'fast', 'preview_only':False, 'backend':{}}
            (scenario.runtime/'hardware_launch_plan.json').write_text(json.dumps(saved))
            result = switch.prepare_chat(scenario.root, 'fast')
            self.assertTrue(result['changed'])
            scenario.admit.assert_called_once()

    def test_foreign_listener_is_not_stopped(self):
        with Scenario() as scenario:
            scenario.current['listeners'][0]['portable_qwen'] = False
            with self.assertRaisesRegex(RuntimeError, 'outside this portable root'):
                switch.prepare_chat(scenario.root, 'fast')
            scenario.begin.assert_not_called()
            scenario.spawn.assert_not_called()
            scenario.restore.assert_not_called()

    def test_busy_inference_rejected_without_handoff(self):
        with Scenario() as scenario:
            scenario.idle.side_effect = RuntimeError('serving another request')
            with self.assertRaisesRegex(RuntimeError, 'another request'):
                switch.prepare_chat(scenario.root, 'fast')
            scenario.begin.assert_not_called()
            scenario.spawn.assert_not_called()

    def test_idle_is_rechecked_inside_handoff_guard(self):
        with Scenario() as scenario:
            scenario.idle.side_effect = [None, RuntimeError('new inference began')]
            with self.assertRaisesRegex(RuntimeError, 'new inference'):
                switch.prepare_chat(scenario.root, 'fast')
            scenario.spawn.assert_not_called()
            self.assertEqual(scenario.current, scenario.old)

    def test_memory_admission_failure_restores_previous_model(self):
        with Scenario() as scenario:
            scenario.admit.side_effect = RuntimeError('Insufficient free RAM')
            with self.assertRaisesRegex(RuntimeError, 'free RAM'):
                switch.prepare_chat(scenario.root, 'fast')
            scenario.restore.assert_called_once_with(scenario.state)
            scenario.spawn.assert_not_called()
            self.assertEqual(scenario.command_file.read_text(), 'original command')

    def test_stop_after_admission_prevents_late_launch_and_restore(self):
        with Scenario() as scenario:
            def admit(*args, **kwargs):
                scenario.generation = {'token': 'stop', 'reason': 'explicit-stop', 'stopped_at': time.time()+1}
                return scenario.plan
            scenario.admit.side_effect = admit
            with self.assertRaises(switch.PreparationCancelled):
                switch.prepare_chat(scenario.root, 'fast')
            scenario.spawn.assert_not_called()
            scenario.restore.assert_not_called()

    def test_cancelled_target_is_cleaned_up_and_previous_model_restored(self):
        with Scenario() as scenario:
            event = threading.Event()
            scenario.after_spawn = event.set
            with self.assertRaises(switch.PreparationCancelled):
                switch.prepare_chat(scenario.root, 'fast', cancel_event=event)
            scenario.process.terminate.assert_called_once()
            scenario.process.wait.assert_called_once()
            scenario.restore.assert_called_once()
            self.assertEqual(scenario.command_file.read_text(), 'original command')

    def test_stop_after_spawn_cleans_target_without_restore(self):
        with Scenario() as scenario:
            def stop():
                scenario.generation = {'token': 'stop', 'reason': 'explicit-stop', 'stopped_at': time.time()+1}
            scenario.after_spawn = stop
            with self.assertRaises(switch.PreparationCancelled):
                switch.prepare_chat(scenario.root, 'fast')
            scenario.process.terminate.assert_called_once()
            scenario.restore.assert_not_called()

    def test_other_owned_process_cannot_satisfy_target_health(self):
        with Scenario() as scenario:
            scenario.after_spawn = lambda: scenario.current['listeners'][0].update(pid=333)
            with self.assertRaisesRegex(RuntimeError, 'different model'):
                switch.prepare_chat(scenario.root, 'fast')
            scenario.process.terminate.assert_called_once()
            scenario.restore.assert_called_once()

    def test_recovery_never_overwrites_newer_generation_metadata(self):
        with Scenario() as scenario:
            scenario.after_spawn = lambda: scenario.current['listeners'][0].update(pid=333)
            def supersede():
                if scenario.process.terminate.called:
                    scenario.generation = {'token': 'new owner'}
                    scenario.command_file.write_text('newer startup command')
            scenario.on_mutex = supersede
            with self.assertRaisesRegex(RuntimeError, 'different model'):
                switch.prepare_chat(scenario.root, 'fast')
            self.assertEqual(scenario.command_file.read_text(), 'newer startup command')
            scenario.restore.assert_not_called()

    def test_image_profile_failure_leaves_current_model_running(self):
        with Scenario() as scenario:
            with self.assertRaisesRegex(RuntimeError, 'attached image'):
                switch.prepare_chat(scenario.root, 'fast', require_vision=True)
            scenario.begin.assert_not_called()
            scenario.spawn.assert_not_called()

    def test_success_publishes_only_after_target_is_healthy(self):
        with Scenario() as scenario:
            result = switch.prepare_chat(scenario.root, 'fast')
            self.assertTrue(result['changed'])
            self.assertEqual(result['model']['id'], 'qwen4-q4')
            self.assertEqual(json.loads((scenario.runtime / 'hardware_launch_plan.json').read_text())['model']['id'], 'qwen4-q4')
            scenario.restore.assert_not_called()
            scenario.release.assert_called_once_with('our-lease')

    def metrics(self, text):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = text.encode()
        return patch.object(switch.urllib.request, 'urlopen', return_value=response)

    def test_metrics_require_both_zero_processing_and_zero_queue(self):
        with self.metrics('llamacpp:requests_processing 0\nllamacpp:requests_deferred 0\n') as request:
            switch._require_idle()
        self.assertTrue(request.call_args.args[0].endswith('/metrics'))
        for text in ('llamacpp:requests_processing 1\nllamacpp:requests_deferred 0\n',
                     'llamacpp:requests_processing 0\nllamacpp:requests_deferred 1\n'):
            with self.metrics(text), self.assertRaisesRegex(RuntimeError, 'another request'):
                switch._require_idle()

    def test_missing_or_invalid_metrics_never_default_to_idle(self):
        for text in ('', 'llamacpp:requests_processing 0\n',
                     'llamacpp:requests_processing NaN\nllamacpp:requests_deferred 0\n',
                     'llamacpp:requests_processing -1\nllamacpp:requests_deferred 0\n',
                     'llamacpp:requests_processing invalid\nllamacpp:requests_deferred 0\n'):
            with self.metrics(text), self.assertRaisesRegex(RuntimeError, 'metrics'):
                switch._require_idle()

    def test_windows_command_parser_preserves_quoted_model_paths(self):
        if switch.os.name != 'nt':
            self.skipTest('Windows CommandLineToArgvW check')
        args = ['C:/Portable AI/llama-server.exe', '-m', 'C:/Portable AI/model name.gguf', '-c', '8192']
        self.assertEqual(switch._argv(subprocess.list2cmdline(args)), args)


if __name__ == '__main__':
    unittest.main()
