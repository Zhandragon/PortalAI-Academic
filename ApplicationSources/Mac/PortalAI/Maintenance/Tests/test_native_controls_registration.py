"""A local-only GUI tab must not disable the existing HA page protocol."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
from native_workflow import Controller
from native_workflow_protocol import PAGES, validate_request
from native_workflow_launcher import configure

class NativeControlsRegistration(unittest.TestCase):
    def scope(self,pages):
        controller=Controller.__new__(Controller)
        controller.adapter=SimpleNamespace(publish_endpoint=Mock())
        names=('start_components','run_system_test','diagnose','minimize_to_tray','stop_components',
               'begin_exit_portableai','toggle_theme','show_or_run_component_diagnostic',
               'show_or_run_media_stack_verify','show_dependency_probe_panel','show_general_cleanup_panel',
               'show_or_run_root_hygiene','show_or_run_root_reference_audit','show_or_run_fresh_machine_validator',
               'show_or_run_storage_audit','show_maintenance_delete_confirm')
        scope={name:Mock() for name in names}
        scope.update(diag_choices=[],native_chat_panel=Mock(),persistence_page=object(),
                     tab_pages=pages,settings_page=object(),buttons=[],launcher_panel_state={})
        return SimpleNamespace(_portalai_native_workflow=controller),scope,controller

    def test_real_gui_tab_inventory_keeps_protocol_active(self):
        tree=ast.parse((ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8-sig'))
        pages={n.args[0].value:object() for n in ast.walk(tree)
               if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_make_tab_page'
               and n.args and isinstance(n.args[0],ast.Constant)}
        self.assertIn('donation',pages)
        app,scope,c=self.scope(pages)
        self.assertIs(configure(app,scope),c)
        self.assertTrue(c.complete)
        self.assertEqual(set(c.pages),PAGES)
        self.assertIn('donation',scope['tab_pages'])
        self.assertNotIn('donation',c.pages)
        for key in PAGES:self.assertIs(c.pages[key],pages[key])
        c.adapter.publish_endpoint.assert_called_once()

    def test_missing_protocol_page_still_withdraws_support(self):
        pages={key:object() for key in PAGES-{'controls'}}
        pages['donation']=object()
        app,scope,c=self.scope(pages)
        with self.assertRaisesRegex(RuntimeError,'native_action_registration_incomplete'):
            configure(app,scope)
        self.assertFalse(c.complete)
        c.adapter.publish_endpoint.assert_called_once()

    def test_local_only_page_is_not_a_remote_request(self):
        with self.assertRaisesRegex(ValueError,'Unknown native page'):
            validate_request({'request_id':'a'*32,'viewer':'b'*32,'operation':'describe','page':'donation'})

if __name__=='__main__':unittest.main()
