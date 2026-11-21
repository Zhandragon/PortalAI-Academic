"""Real owned child/grandchild cancellation, with no desktop input or model."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from tool_process import ToolProcess
from workspace_services import register,close_all,epoch


@unittest.skipUnless(os.name=='nt','Windows Job Object acceptance')
class ToolStop(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='portal-tool-stop-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.stopped=threading.Event();self.owners=[]
        self.addCleanup(lambda:[o.close() for o in self.owners])

    def check(self):
        if self.stopped.is_set():raise RuntimeError('cancelled')

    def launch(self,code,*,start=True):
        owner=ToolProcess(ROOT,[sys.executable,'-B','-c',code],cwd=self.root,
                          env=os.environ.copy(),check=self.check,python=sys.executable)
        self.owners.append(owner)
        if start:owner.start()
        return owner

    def wait_file(self,path):
        end=time.monotonic()+8
        while not path.exists():
            if time.monotonic()>end:self.fail('Fixture child never started')
            time.sleep(.03)

    def test_stop_kills_detached_grandchild_after_launcher_exits(self):
        pulse=self.root/'pulse'
        child='from pathlib import Path;import time; p=Path('+repr(str(pulse))+');\nwhile True:p.write_text(str(time.time()));time.sleep(.03)'
        parent='import subprocess,sys;subprocess.Popen([sys.executable,"-B","-c",'+repr(child)+'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS)'
        owner=self.launch(parent);owner.process.communicate(timeout=8);self.wait_file(pulse)
        self.assertEqual(owner.process.returncode,0)
        self.assertTrue(owner.job.active())
        started=time.monotonic();self.stopped.set()
        end=started+3
        while not owner.closed and time.monotonic()<end:time.sleep(.02)
        self.assertTrue(owner.closed);self.assertLess(time.monotonic()-started,1.5)
        first=pulse.read_text();time.sleep(.2);self.assertEqual(first,pulse.read_text())

    def test_stop_before_gate_never_executes(self):
        effect=self.root/'should-not-exist'
        owner=self.launch('from pathlib import Path;Path('+repr(str(effect))+').touch()',start=False)
        self.stopped.set()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):owner.start()
        owner.close();self.assertFalse(effect.exists())

    def test_shared_stop_closes_a_different_runtime_resource(self):
        owner=self.launch('import time;time.sleep(60)')
        token=epoch(self.root);register(self.root,owner,expected_epoch=token)
        self.assertEqual(close_all(self.root),[])
        self.assertIsNotNone(owner.process.poll())
        with self.assertRaisesRegex(RuntimeError,'stopped'):register(self.root,object(),expected_epoch=token)
        owner.process.communicate(timeout=3)

    def test_failed_ownership_never_runs_command(self):
        effect=self.root/'unowned-effect'
        with patch('mission_supervisor.WorkerJob',side_effect=RuntimeError('containment refused')):
            with self.assertRaisesRegex(RuntimeError,'containment refused'):
                self.launch('from pathlib import Path;Path('+repr(str(effect))+').touch()')
        self.assertFalse(effect.exists())

    def test_chat_stop_closes_script_and_pauses_other_mission_hooks(self):
        from native_chat import ToolRuntime
        runtime=SimpleNamespace(root=self.root,boot=sys.executable,_lock=threading.RLock(),
            _account_role=lambda:'admin',_working_directory=lambda:self.root,
            profile=SimpleNamespace(identity=None),_agents_used=False)
        p=ToolRuntime._start_linux(runtime,[sys.executable,'-B','-c','import time;time.sleep(60)'],os.environ.copy())
        self.owners.append(p._portalai_owner)
        with patch('desktop_control.revoke'),patch('agent_collaboration.close_profile'),patch('mission_supervisor.pause_all') as pause:
            ToolRuntime.cancel(runtime)
        pause.assert_called_once_with(self.root)
        self.assertIsNotNone(p.poll());p.communicate(timeout=3)

    def test_completed_mission_keeps_detached_child_owned_until_stop(self):
        from mission_runner import Missions
        from mission_supervisor import Supervisor,arm
        (self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{
            'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        store=Missions(self.root);mission=store.create('Synthetic descendant ownership');mid=mission['id']
        arm(self.root,mid);mission.update(status='complete');store.save(mission)
        pulse=self.root/'mission-pulse'
        child='from pathlib import Path;import time;p=Path('+repr(str(pulse))+');\nwhile True:p.write_text(str(time.time()));time.sleep(.03)'
        parent='import subprocess,sys;subprocess.Popen([sys.executable,"-B","-c",'+repr(child)+'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS)'
        owner=ToolProcess(ROOT,[sys.executable,'-B','-c',parent],cwd=self.root,env=os.environ.copy(),check=self.check,monitor=False,python=sys.executable)
        self.owners.append(owner);owner.start();owner.process.communicate(timeout=8);self.wait_file(pulse)
        controller=Supervisor(self.root);controller.worker=owner.process;controller.job=owner.job
        controller.mid=controller.root_id=mid
        controller.finish_worker()
        self.assertEqual(len(controller.effects),1);self.assertTrue(owner.job.active())
        (store.base/'supervisor.stop').touch();self.assertFalse(controller.tick())
        self.assertFalse(owner.job.active());self.assertEqual(controller.effects,[])
        first=pulse.read_text();time.sleep(.2);self.assertEqual(first,pulse.read_text())

    def test_parent_crash_kills_child_tree(self):
        pulse=self.root/'crash-pulse'
        child='from pathlib import Path;import time; p=Path('+repr(str(pulse))+');\nwhile True:p.write_text(str(time.time()));time.sleep(.03)'
        controller='import sys,os,time;sys.path[:0]='+repr([str(ROOT/'Agent'),str(ROOT/'ControlCenter')])+';from tool_process import ToolProcess;o=ToolProcess('+repr(str(ROOT))+',[sys.executable,"-B","-c",'+repr(child)+'],cwd='+repr(str(self.root))+',env=os.environ.copy(),check=lambda:None,python=sys.executable);o.start();time.sleep(1);os._exit(17)'
        p=subprocess.Popen([sys.executable,'-B','-c',controller],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        _,err=p.communicate(timeout=10);self.assertEqual(p.returncode,17,err)
        self.wait_file(pulse);time.sleep(.2);first=pulse.read_text();time.sleep(.2);self.assertEqual(first,pulse.read_text())


if __name__=='__main__':unittest.main()
