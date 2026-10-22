from pathlib import Path
import hashlib,sys,tempfile,time,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests')]
import tkinter as tk
from executable_recovery_ui import RecoveryUI
import executable_recovery as r
from writer_jobs import WriterJobs
from test_settings_surfaces_tk import LIGHT,DARK

class RecoveryTkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.app=tk.Tk();self.app.geometry('1000x680')
        self.jobs=WriterJobs();self.colors=LIGHT;self.body=None;self.cancelled=False
        self.name='LLM/backends/windows-cpu/llama-server.exe';self.path=self.root/self.name;self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'fixture');r.register(self.root,[dict(path=self.name,bytes=7,sha256=hashlib.sha256(b'fixture').hexdigest())],'fixture');self.path.unlink()
        def guard_factory(_):
            def guard():
                if self.cancelled:raise PermissionError('Stopped')
            return guard
        self.ui=RecoveryUI(self.app,self.root,jobs=self.jobs,colors=lambda:self.colors,open_panel=self.open,close_panel=self.close,can_show=lambda:True,guard_factory=guard_factory,log=lambda _:None)
    def open(self,*_,**__):
        self.close();self.body=tk.Frame(self.app,bg=self.colors['bg']);self.body.pack(fill='both',expand=True);return self.body
    def close(self):
        if self.body:self.body.destroy();self.body=None
    def flush(self,seconds=.2):
        until=time.monotonic()+seconds
        while time.monotonic()<until:self.app.update();time.sleep(.01)
    def tearDown(self):
        self.jobs.close();self.jobs.wait()
        from tk_fixture_cleanup import finish_tk_fixture
        finish_tk_fixture(self.app);self.tmp.cleanup()
    def test_real_button_restores_only_after_click(self):
        for colors in (LIGHT,DARK):
            self.colors=colors;self.ui.show(r.inspect(self.root,True));self.flush();self.assertFalse(self.path.exists())
        self.ui.proceed_button.invoke();self.flush(.8);self.assertEqual(self.path.read_bytes(),b'fixture')
    def test_stop_between_prompt_and_proceed_prevents_restoration(self):
        self.ui.show(r.inspect(self.root,True));self.cancelled=True;self.ui.proceed_button.invoke();self.flush();self.assertFalse(self.path.exists())
    def test_automatic_monitor_shows_popup_without_repair(self):
        self.ui.request();self.flush(.8);self.assertIsNotNone(self.ui.proceed_button);self.assertFalse(self.path.exists())

if __name__=='__main__':unittest.main(verbosity=2)
