"""Small boundary checks independent of hardware and production accounts."""
import sys,time,unittest
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
from native_workflow import Controller,resolve_tk_value
from native_workflow_protocol import validate_request,PAGES


class WorkflowGuards(unittest.TestCase):
    def test_tk_variable_handles_resolve_before_native_form_publication(self):
        class FakeTk:
            def getvar(self,name):
                if name=='PY_VAR_7':return 'Readable field label'
                if name=='PY_VAR8':return ('First choice','Second choice')
                raise tk.TclError('unknown variable')
            class Tcl:
                @staticmethod
                def call(command,value,separator):
                    assert command=='join' and separator==' '
                    return separator.join(value)
            tk=Tcl()
        widget=FakeTk()
        self.assertEqual(resolve_tk_value(widget,'PY_VAR_7'),'Readable field label')
        self.assertEqual(resolve_tk_value(widget,'PY_VAR8'),'First choice Second choice')
        self.assertEqual(resolve_tk_value(widget,'PY_VAR_99'),'')
        self.assertEqual(resolve_tk_value(widget,'ordinary text'),'ordinary text')

    def test_launcher_does_not_register_duplicate_persistence_navigation(self):
        from native_workflow_launcher import configure as configure_launcher
        class FakeController:
            def configure(self,**kwargs):self.configured=kwargs
        persistence=object();controller=FakeController()
        controller.adapter=SimpleNamespace(publish_endpoint=Mock())
        app=SimpleNamespace(_portalai_native_workflow=controller)
        names=('start_components','run_system_test','diagnose','minimize_to_tray','stop_components',
               'begin_exit_portableai','toggle_theme','show_or_run_component_diagnostic',
               'show_or_run_media_stack_verify','show_dependency_probe_panel','show_general_cleanup_panel',
               'show_or_run_root_hygiene','show_or_run_root_reference_audit','show_or_run_fresh_machine_validator',
               'show_or_run_storage_audit','show_maintenance_delete_confirm')
        scope={name:(lambda *args,**kwargs:None) for name in names}
        scope.update({'diag_choices':[],'native_chat_panel':None,'persistence_page':persistence,
                      'tab_pages':dict.fromkeys(PAGES),'settings_page':object(),'buttons':[],
                      'launcher_panel_state':SimpleNamespace(get=lambda key:None)})
        result=configure_launcher(app,scope)
        callbacks=result.configured['callbacks']
        self.assertNotIn('persistence_missions',callbacks)
        self.assertNotIn('persistence_schedules',callbacks)
        self.assertIs(result.persistence,persistence)

    def test_registration_requires_all_pages_and_safety_actions(self):
        c=Controller.__new__(Controller);c.adapter=Mock();c.complete=True
        callbacks={key:(key,lambda:None,{'controls'}) for key in ('controls_startup','controls_stop','controls_exit','chat_stop')}
        c.configure(dict.fromkeys(PAGES),callbacks,Mock(),Mock())
        self.assertEqual(set(c.pages),PAGES)
        with self.assertRaises(RuntimeError):c.configure({},callbacks,Mock(),Mock())
        self.assertFalse(c.complete);c.adapter.publish_endpoint.assert_called_once()

    def test_download_rechecks_live_account_at_http_publication(self):
        c=Controller.__new__(Controller)
        ex=SimpleNamespace(view='a',epoch='b',allowed=Mock(return_value=True))
        row={'binding':('a','b'),'expires':time.monotonic()+2}
        c.app=SimpleNamespace(_portalai_native_exporter=ex);c.files=SimpleNamespace(rows={'file':row})
        reply={'operation':'file_get','file':'file','data':'private'}
        self.assertTrue(c.response_current(reply))
        ex.allowed.return_value=False;self.assertFalse(c.response_current(reply))
        ex.allowed.return_value=True;ex.epoch='c';self.assertFalse(c.response_current(reply))
        ex.epoch='b';row['expires']=0;self.assertFalse(c.response_current(reply))
        c.files.rows.clear();self.assertFalse(c.response_current(reply))

    def test_no_arbitrary_action_arguments_or_file_path_request(self):
        base={'request_id':'a'*32,'viewer':'b'*32,'operation':'invoke',
              'binding':{'view':'c','epoch':'d'},'form':'form','action':'button','values':{}}
        self.assertEqual(validate_request(base),base)
        for extra in ({'call':'os.system'},{'path':'D:/private'},{'values':{'x':{'code':'run'}}}):
            with self.assertRaises(ValueError):validate_request({**base,**extra})

    def test_public_model_cannot_be_published_after_authority_rotation(self):
        c=Controller.__new__(Controller);c.public=('new','epoch')
        self.assertFalse(c.response_current({'model':{'view':'old','epoch':'epoch','account':{'state':'locked'}}}))


if __name__=='__main__':unittest.main()
