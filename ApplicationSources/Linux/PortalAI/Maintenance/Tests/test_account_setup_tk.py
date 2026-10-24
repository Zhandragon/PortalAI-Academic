"""Setup UI with disposable user input and mocked application operations."""
from pathlib import Path
import sys,tempfile,json,time,tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests')]
from test_settings_surfaces_tk import LIGHT,button
from tk_fixture_cleanup import finish_tk_fixture
from writer_jobs import WriterJobs
from account_setup_ui import show_setup

class SetupUITests(unittest.TestCase):
    def exercise_setup(self, enabled):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        app=tk.Tk();app.geometry('1000x760+40+40');errors=[];app.report_callback_exception=lambda *x:errors.append(x)
        jobs=WriterJobs();gate=SimpleNamespace(app=app,root=root,colors=LIGHT,locked=False,session=SimpleNamespace(active=True,role='admin'),controller=SimpleNamespace(jobs=jobs))
        path=root/'setup.json';path.write_text('{}')
        receipt={'verified':True,'mission_id':'a'*32,'schedule_id':'b'*32,'connections':['test'],'schedule_enabled':enabled,'mission_armed':enabled}
        try:
            with patch('account_setup.load_request',return_value={'id':'c'*32}) as load,patch('account_setup.apply',return_value=receipt) as apply,patch('account_setup.check_connections',return_value={'test':{'status':'verified'}}),patch('profile_paths.private_path',side_effect=lambda r,p:r/p):
                dialog=show_setup(gate,path,apply_requested=True)
                deadline=time.monotonic()+5
                while not hasattr(app,'_portalai_last_account_setup') and time.monotonic()<deadline:app.update();time.sleep(.02)
                self.assertTrue(hasattr(app,'_portalai_last_account_setup'));apply.assert_called_once()
                self.assertEqual(load.call_args.args[0],str(path));self.assertIn('a'*32,dialog.status.get())
                self.assertIn('Schedule is enabled.' if enabled else 'Schedule is paused.',dialog.status.get())
                if enabled:self.assertNotIn('Schedule is paused.',dialog.status.get())
                button(dialog.win,'Close').invoke()
        finally:
            jobs.close();self.assertTrue(jobs.wait(3)['stopped'])
            for dialog in getattr(app,'_portalai_account_dialogs',[]):
                if not dialog.closed:dialog.busy=False;dialog.close()
            finish_tk_fixture(app)
        self.assertEqual(errors,[])

    def test_new_request_runs_once_and_shows_paused_records(self):self.exercise_setup(False)

    def test_repeated_request_shows_preserved_activation(self):self.exercise_setup(True)

if __name__=='__main__':unittest.main()
