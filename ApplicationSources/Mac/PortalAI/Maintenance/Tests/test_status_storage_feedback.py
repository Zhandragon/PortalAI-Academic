"""Sleeping model semantics and live storage summaries without real accounts."""
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('ControlCenter', 'Agent')]
import runtime_health
import settings_page
from test_settings_surfaces_tk import INVENTORY, LIGHT
from tk_fixture_cleanup import finish_tk_fixture


class HealthFeedbackTests(unittest.TestCase):
    def setUp(self): runtime_health._reset_for_test()
    def tearDown(self): runtime_health._reset_for_test()

    def test_sleep_retains_selected_model_without_claiming_handoff_or_readiness(self):
        with patch.object(runtime_health, '_port_open', return_value=True), \
             patch.object(runtime_health, '_http_json', return_value={
                 'model_path': 'Qwen3-4B.gguf', 'is_sleeping': True}) as probe:
            state = runtime_health.qwen_health(force=True)
        self.assertTrue(state['online'])
        self.assertFalse(state['ready'])
        self.assertEqual(state['model'], 'Qwen3-4B.gguf')
        self.assertNotIn('handoff', state['detail'])
        probe.assert_called_once_with('/props', .35)  # Never wake for a status display.

    def test_sleep_overrides_previously_ready_state_and_can_wake(self):
        with patch.object(runtime_health, '_port_open', return_value=True), \
             patch.object(runtime_health, '_http_json', side_effect=[
                 {'is_sleeping': False}, {'data': [{'id': '4B'}]},
                 {'is_sleeping': True},
                 {'is_sleeping': False}, {'data': [{'id': '4B'}]}]):
            self.assertTrue(runtime_health.qwen_health(force=True)['ready'])
            self.assertFalse(runtime_health.qwen_health(force=True)['ready'])
            self.assertTrue(runtime_health.qwen_health(force=True)['ready'])


class StorageFeedbackTests(unittest.TestCase):
    def test_refresh_after_writes_and_deletion_preserves_draft(self):
        app = tk.Tk(); app.withdraw()
        try:
            with patch.object(settings_page, 'inventory', return_value=INVENTORY), \
                 patch.object(settings_page, 'can_admin', return_value=False):
                page = settings_page.StorageReservesPage(app, ROOT, LIGHT)
            page.variables['output_reserve_gib'].set('123')
            budget = dict(INVENTORY['storage'])
            for free in (179, 165, 190):
                budget['free_bytes'] = free*1024**3
                page.refresh_budget(budget)
                self.assertIn(f'Free: {free:.2f} GiB', page.budget_label.cget('text'))
                self.assertEqual(page.variables['output_reserve_gib'].get(), '123')
        finally: finish_tk_fixture(app)


if __name__ == '__main__': unittest.main()
