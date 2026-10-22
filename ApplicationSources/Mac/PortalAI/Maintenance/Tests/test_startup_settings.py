"""Settings/Startup integration with disposable files and owned lifecycle fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('Agent', 'ControlCenter', 'Maintenance/Tests')]
import chat_model_switch as switch
import effort_policy
import runtime_policy
import settings_page
from lifecycle_control import startup_result
from test_chat_model_switch import Scenario
from test_settings_surfaces_tk import hardware_fixture, INVENTORY
from tk_fixture_cleanup import finish_tk_fixture


class StartupModelTests(unittest.TestCase):
    def configure(self, scenario):
        policy = {'selection': 'qwen4-abliterated-q4', 'backend': 'cpu', 'context_tokens': 8192,
                  'models': [{'id': 'qwen4-abliterated-q4', 'automatic': False}]}
        (scenario.root/'Agent/hardware_profiles.json').write_text(json.dumps(policy))
        scenario.model['id'] = 'qwen4-abliterated-q4'
        scenario.model['label'] = '4B Abliterated'
        return policy

    def test_startup_switches_existing_standard_to_selected_alternate(self):
        with Scenario() as s:
            policy = self.configure(s)
            with patch.object(effort_policy, 'capabilities', return_value={'profiles': {'balanced': s.plan}}):
                result = switch.prepare_startup(s.root)
            self.assertTrue(result['changed'])
            self.assertEqual(result['model']['id'], policy['selection'])
            self.assertEqual(s.admit.call_args.kwargs['policy'], policy)
            s.begin.assert_called_once(); s.idle.assert_called(); s.spawn.assert_called_once()

    def test_startup_reuses_only_the_matching_owned_healthy_model(self):
        with Scenario() as s:
            self.configure(s); s.current = s.identity(s.command)
            with patch.object(effort_policy, 'capabilities', return_value={'profiles': {'balanced': s.plan}}):
                self.assertFalse(switch.prepare_startup(s.root)['changed'])
            s.begin.assert_not_called(); s.spawn.assert_not_called()

    def test_busy_model_and_invalid_selection_stay_untouched(self):
        with Scenario() as s:
            self.configure(s); s.idle.side_effect = RuntimeError('active request')
            with patch.object(effort_policy, 'capabilities', return_value={'profiles': {'balanced': s.plan}}):
                with self.assertRaisesRegex(RuntimeError, 'active request'):switch.prepare_startup(s.root)
            s.begin.assert_not_called(); s.spawn.assert_not_called()
            with patch.object(effort_policy, 'capabilities', return_value={'profiles': {'balanced': {'available': False, 'reason': 'missing selected model'}}}):
                with self.assertRaisesRegex(RuntimeError, 'missing selected'):switch.prepare_startup(s.root)
            s.begin.assert_not_called()

    def test_change_during_startup_cancels_and_restores_previous_model(self):
        with Scenario() as s:
            policy = self.configure(s)
            def change(*args, **kwargs):
                (s.root/'Agent/hardware_profiles.json').write_text(json.dumps({**policy, 'selection': 'auto'}))
                return s.plan
            s.admit.side_effect = change
            with patch.object(effort_policy, 'capabilities', return_value={'profiles': {'balanced': s.plan}}):
                with self.assertRaisesRegex(switch.PreparationCancelled, 'settings changed'):switch.prepare_startup(s.root)
            s.spawn.assert_not_called(); s.restore.assert_called_once_with(s.state)

    def test_changed_context_invalidates_cached_plan_and_larger_resident_context(self):
        with Scenario() as s:
            saved = {**s.plan, 'level':'balanced', 'preview_only':False, 'backend':{},
                     'policy_signature': {'context_tokens':8192}}
            (s.runtime/'hardware_launch_plan.json').write_text(json.dumps(saved))
            self.assertIsNone(switch._saved_admitted_plan(s.root, 'balanced',
                              {'policy_signature': {'context_tokens':4096}}))
            self.assertFalse(switch._matches(s.identity(s.command), s.model, 4096, s.command))

    def test_windows_launcher_delegates_to_guarded_saved_policy(self):
        spec = importlib.util.spec_from_file_location('startup_policy_fixture', ROOT/'Launchers/Start_PortableAI_Native_v15_133.py')
        launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
        result = {'changed':True, 'model':{'id':'qwen4-abliterated-q4', 'label':'4B Abliterated'}}
        with patch.object(switch, 'prepare_startup', return_value=result) as prepare, patch.object(launcher,'log'):
            self.assertEqual(launcher.recover_or_adopt(ROOT, 12)['profile'], 'qwen4-abliterated-q4')
        self.assertEqual(prepare.call_args.kwargs['requested_at'], 12)

    def test_linux_launcher_uses_same_model_and_stop_guard(self):
        import linux_lifecycle
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = {'changed':True, 'model':{'id':'qwen4-abliterated-q4'}}
            with patch.object(switch, 'prepare_startup', return_value=result) as prepare, \
                 patch.object(switch, '_guard') as guard, patch('mission_supervisor.ensure_running', return_value={}):
                state = linux_lifecycle.start_all(root, requested_at=12)
            self.assertTrue(state['success']); self.assertEqual(state['qwen']['profile'], result['model']['id'])
            prepare.assert_called_once_with(root, requested_at=12)
            self.assertEqual(guard.call_count, 2)

    def test_stale_startup_success_cannot_report_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            state = {'success':True, 'started_at':10, 'qwen':{'model':{'id':'qwen4-abliterated-q4'}}}
            completed = subprocess.CompletedProcess([], 0, json.dumps(state), '')
            self.assertFalse(startup_result(folder, completed, 11)['ok'])
            result = startup_result(folder, completed, 10)
            self.assertTrue(result['ok']); self.assertIn('qwen4-abliterated-q4', result['detail'])


class SettingsStartupTkTests(unittest.TestCase):
    def setUp(self):
        try:self.app = tk.Tk()
        except tk.TclError as exc:raise unittest.SkipTest(str(exc))
        self.app.withdraw(); self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.policy_patch = patch.object(settings_page, 'load_effective_policy', return_value=copy.deepcopy(INVENTORY['policy']))
        self.policy_patch.start(); self.addCleanup(self.policy_patch.stop)
        self.page, self.skin = hardware_fixture(self.app)

    def tearDown(self):
        self.page.destroy(); self.page = self.skin = None
        finish_tk_fixture(self.app)
        self.assertEqual(self.errors, [])

    def choose(self, model_id='fixture-small'):
        label = next(label for label, value in self.page.model_ids.items() if value == model_id)
        self.page.variables['selection'].set(label)

    def test_startup_commits_pending_chat_only_and_refreshes_controls(self):
        self.page.on_change = Mock(); self.page.on_save = Mock()
        self.choose(); self.page.variables['voice_engine'].set('piper')
        self.assertTrue(self.page.dirty('chat')); self.assertIn('Pending', self.page.startup_summary())
        with patch.object(settings_page, 'save_settings') as save:
            self.assertTrue(self.page.commit_for_startup())
        self.assertEqual(save.call_args.args[1]['selection'], 'fixture-small')
        self.assertEqual(save.call_args.kwargs['scope'], 'chat')
        self.assertNotIn('voice_engine', save.call_args.args[1])
        self.assertFalse(self.page.dirty('chat')); self.assertTrue(self.page.dirty('media'))
        self.page.on_save.assert_called_once(); self.page.on_change.assert_called()

    def test_failed_save_prevents_startup_and_preserves_pending_choice(self):
        self.choose()
        with patch.object(settings_page, 'save_settings', side_effect=PermissionError('admin required')):
            self.assertFalse(self.page.commit_for_startup())
        self.assertTrue(self.page.dirty('chat')); self.assertIn('admin required', self.page.status.get())

    def test_refresh_updates_clean_fields_and_preserves_unsaved_draft(self):
        self.choose()
        policy = {**INVENTORY['policy'], 'selection':'fixture-large', 'backend':'cpu'}
        with patch.object(settings_page, 'load_effective_policy', return_value=policy):
            self.page.refresh_saved(INVENTORY['models'])
        self.assertEqual(self.page.values('chat')['selection'], 'fixture-small')
        self.assertEqual(self.page.values('chat')['backend'], 'cpu')
        self.assertEqual(self.page.saved_values['selection'], 'fixture-large')
        self.assertTrue(self.page.dirty('chat'))

    def test_startup_clean_page_refreshes_external_selection_without_rewriting(self):
        policy = {**INVENTORY['policy'], 'selection':'fixture-large'}
        with patch.object(settings_page, 'load_effective_policy', return_value=policy), patch.object(settings_page,'save_settings') as save:
            self.assertTrue(self.page.commit_for_startup())
        save.assert_not_called()
        self.assertEqual(self.page.values('chat')['selection'], 'fixture-large')

    def test_startup_merges_external_backend_with_local_model_draft(self):
        self.choose()
        policy = {**INVENTORY['policy'], 'backend':'vulkan', 'context_tokens':4096}
        with patch.object(settings_page, 'load_effective_policy', return_value=policy), patch.object(settings_page,'save_settings') as save:
            self.assertTrue(self.page.commit_for_startup())
        self.assertEqual(save.call_args.args[1], {'selection':'fixture-small','backend':'vulkan','context_tokens':'4096','variant_preference':'standard','vision_routing':'off'})

    def test_missing_selection_stays_explicit_and_new_models_appear(self):
        policy = {**INVENTORY['policy'], 'selection':'missing'}
        with patch.object(settings_page, 'load_effective_policy', return_value=policy):self.page.refresh_saved([])
        self.assertEqual(self.page.values('chat')['selection'], 'missing')
        self.assertIn('Unavailable', self.page.variables['selection'].get())

    def test_stale_hardware_probe_cannot_overwrite_new_selection_or_saved_status(self):
        self.page.probing.add('chat')
        self.page._probe_serial['chat'] = 1
        self.choose(); expected = self.page.status.get()
        self.page.results.put(('chat', 1, 'Old standard model fits'))
        self.page.after_cancel(self.page.poll_id); self.page.poll()
        self.assertEqual(self.page.status.get(), expected)
        self.assertNotIn('chat', self.page.probing)

    def test_busy_startup_disables_only_chat_save_and_selectors(self):
        self.page.set_startup_busy(True)
        self.assertTrue(self.page.save_button.instate(['disabled']))
        self.assertFalse(self.page.section_buttons['media'][1].instate(['disabled']))
        self.assertFalse(self.page.commit_for_startup())
        self.page.set_startup_busy(False)
        self.assertFalse(self.page.save_button.instate(['disabled']))


if __name__ == '__main__':unittest.main()
