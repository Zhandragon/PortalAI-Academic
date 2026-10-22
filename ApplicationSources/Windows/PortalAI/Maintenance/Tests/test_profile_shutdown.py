"""Profile shutdown proofs with synthetic processes; never stop live processes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import profile_shutdown as shutdown
import local_accounts as accounts


class ProfileShutdownTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name).resolve()
        self.me=os.getpid()
        self.controller=self.row(self.me,0,1,'Runtime/python.exe')
        self.sleep=patch.object(shutdown.time,'sleep');self.sleep.start();self.addCleanup(self.sleep.stop)

    def row(self,pid,parent=0,start=10,executable='Runtime/python.exe',argv=None):
        return {'pid':pid,'ppid':parent,'start':start,'executable':str(self.root/executable),
                'argv':argv or [str(self.root/executable)],'group':str(self.root/'scope/controller')}

    def snapshot(self,*rows):
        return {row['pid']:row for row in (self.controller,*rows)}

    def test_no_owned_path_and_readonly_verify_preserve_every_file(self):
        base=self.root/'Data/Missions';base.mkdir(parents=True)
        for name,data in [('run-policy.json',{'enabled':True}),('schedule.json',{'enabled':True,'epoch':'unchanged'})]:
            (base/name).write_text(json.dumps(data))
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(shutdown,'_validate'),patch.object(shutdown,'_snapshot',return_value=self.snapshot()) as snapshot,\
             patch.object(shutdown,'_fence') as fence,patch.object(shutdown,'_stop_batch') as kill:
            result=shutdown.stop_owned(self.root,object(),None)
            self.assertTrue(shutdown.verify_stopped(self.root)['stopped'])
        self.assertTrue(result['stopped']);self.assertEqual(snapshot.call_count,4)
        fence.assert_not_called();kill.assert_not_called()
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_foreign_listener_or_root_mention_is_not_owned(self):
        foreign=self.row(101,executable='../other/python.exe',argv=['foreign','--input',str(self.root/'Outputs/file')])
        self.assertEqual(shutdown._select(self.root,self.snapshot(foreign)),{})

    def test_direct_owned_script_and_descendant_are_attributed(self):
        parent=self.row(101,executable='../host/python.exe',argv=['python',str(self.root/'Agent/mission_runner.py')])
        child=self.row(102,parent=101,start=11,executable='../host/sh')
        unrelated=self.row(103,parent=101,start=9,executable='../host/sh')
        self.assertEqual(set(shutdown._select(self.root,self.snapshot(parent,child,unrelated))),{101,102})

    def test_interpreter_command_text_is_not_direct_script_ownership(self):
        foreign=self.row(101,executable='../host/python.exe',
                         argv=['python','-c',str(self.root/'Agent/mission_runner.py')])
        self.assertFalse(shutdown._script_owned(self.root,foreign))
        foreign['argv']=['python','-I','-X','utf8',str(self.root/'Agent/mission_runner.py')]
        self.assertTrue(shutdown._script_owned(self.root,foreign))

    def test_pid_reuse_does_not_keep_old_descendant_owned(self):
        old=self.row(101,executable='../host/sh')
        replacement={**old,'start':20}
        self.assertEqual(shutdown._select(self.root,self.snapshot(replacement),{101:old}),{})

    def test_other_gui_blocks_without_termination(self):
        gui=self.row(101,argv=['python',str(self.root/'ControlCenter/PortableAI_GUI.py')])
        with self.assertRaisesRegex(shutdown.QuiescenceError,'GUI remains'):
            shutdown._select(self.root,self.snapshot(gui))

    def test_fence_precedes_stop_and_final_empty_proof_is_required(self):
        worker=self.row(101);events=[]
        with patch.object(shutdown,'_validate'),\
             patch.object(shutdown,'_snapshot',side_effect=[self.snapshot(worker),self.snapshot(),self.snapshot()]),\
             patch.object(shutdown,'_linux_plan'),\
             patch.object(shutdown,'_fence',side_effect=lambda root:events.append('fence')),\
             patch.object(shutdown,'_stop_batch',side_effect=lambda *args:events.append('stop')):
            result=shutdown.stop_owned(self.root,object(),None)
        self.assertEqual(events,['fence','stop']);self.assertEqual(result['stopped_pids'],[101])
        self.assertEqual(result['mission_policy'],'preserved')

    def test_readonly_verify_never_stops_existing_worker(self):
        with patch.object(shutdown,'_snapshot',return_value=self.snapshot(self.row(101))),\
             patch.object(shutdown,'_stop_batch') as stop,patch.object(shutdown,'_fence') as fence:
            result=shutdown.verify_stopped(self.root)
        self.assertFalse(result['stopped']);self.assertEqual(result['remaining_owned_pids'],[101])
        stop.assert_not_called();fence.assert_not_called()

    def test_inventory_failure_and_reappearing_worker_fail_closed(self):
        with patch.object(shutdown,'_validate'),patch.object(shutdown,'_snapshot',side_effect=OSError('query denied')),\
             patch.object(shutdown,'_fence') as fence:
            with self.assertRaises(OSError):shutdown.stop_owned(self.root,object(),None)
        fence.assert_not_called()
        with patch.object(shutdown,'_validate'),patch.object(shutdown,'_snapshot',return_value=self.snapshot(self.row(101))),\
             patch.object(shutdown,'_linux_plan'),patch.object(shutdown,'_fence'),patch.object(shutdown,'_stop_batch'):
            with self.assertRaisesRegex(shutdown.QuiescenceError,'keep appearing'):
                shutdown.stop_owned(self.root,object(),None)

    def test_marker_change_after_inventory_prevents_stop(self):
        with patch.object(shutdown,'_validate',side_effect=[None,None,shutdown.QuiescenceError('marker changed')]),\
             patch.object(shutdown,'_snapshot',return_value=self.snapshot(self.row(101))),\
             patch.object(shutdown,'_linux_plan'),patch.object(shutdown,'_fence'),patch.object(shutdown,'_stop_batch') as stop:
            with self.assertRaisesRegex(shutdown.QuiescenceError,'marker changed'):
                shutdown.stop_owned(self.root,object(),None)
        stop.assert_not_called()

    def test_linux_foreign_scope_has_no_pid_fallback(self):
        import linux_job
        job=self.root/('other/portalai-job-22-'+'a'*32)
        row=self.row(101);row['group']=str(job)
        with patch.object(linux_job,'delegated_root',return_value=self.root/'scope'):
            with self.assertRaisesRegex(shutdown.QuiescenceError,'different/unverifiable'):
                shutdown._linux_plan(self.root,self.snapshot(row),{101:row})

    def test_linux_host_descendant_outside_cgroup_is_refused_before_fence(self):
        row=self.row(101,executable='../host/sh')
        with self.assertRaisesRegex(shutdown.QuiescenceError,'refusing PID fallback'):
            shutdown._linux_plan(self.root,self.snapshot(row),{101:row})

    def test_model_fence_changes_no_mission_policy_or_marker(self):
        from contextlib import nullcontext
        import service_manager
        base=self.root/'Data/Missions';base.mkdir(parents=True)
        policy=base/'run-policy.json';policy.write_text('{"enabled":true}')
        with patch.object(service_manager,'root_dir',return_value=self.root),\
             patch.object(service_manager,'_qwen_lifecycle_mutex',return_value=nullcontext()):
            shutdown._fence(self.root)
        self.assertEqual(policy.read_text(),'{"enabled":true}')
        generation=json.loads((self.root/'Agent/.runtime/qwen_handoff_generation.json').read_text())
        self.assertEqual(generation['reason'],'explicit-stop')
        self.assertFalse((self.root/'Private').exists())

    def test_linux_job_plan_covers_nested_descendant_without_group_signal(self):
        import linux_job
        base=self.root/'scope';group=base/('portalai-job-22-'+'a'*32)
        group.mkdir(parents=True);(group/'cgroup.kill').touch()
        worker=self.row(101);worker['group']=str(group/'nested')
        with patch.object(linux_job,'delegated_root',return_value=base),\
             patch.object(shutdown.os,'getuid',return_value=group.stat().st_uid,create=True):
            jobs,outside=shutdown._linux_plan(self.root,self.snapshot(worker),{101:worker})
        self.assertEqual(jobs,[group]);self.assertEqual(outside,[])

    def test_real_session_authentication_closing_marker_and_revocation(self):
        with patch.object(accounts,'_KDF_N',1024):
            store=accounts.LocalAccounts(self.root);self.addCleanup(store.logout)
            session=store.bootstrap('FixtureAdmin','synthetic profile test password')
            marker={'user_id':session.user_id,'epoch':'a'*32,'state':'closing','controller_pid':self.me}
            path=self.root/'Private/active-session.json';path.write_text(json.dumps(marker))
            shutdown._validate(self.root,session,marker)
            self.assertEqual(json.loads(path.read_text())['state'],'closing')
            with self.assertRaises(PermissionError):shutdown._validate(self.root,object(),marker)
            with self.assertRaises(shutdown.QuiescenceError):shutdown._validate(self.root,session,{**marker,'state':'open'})
            store.logout(session)
            with self.assertRaises(PermissionError):shutdown._validate(self.root,session,marker)

    @unittest.skipUnless(os.name=='nt','Windows handle ABI test')
    def test_windows_reused_pid_handle_is_never_terminated(self):
        import ctypes
        lib=MagicMock();lib.OpenProcess.return_value=123;lib.WaitForSingleObject.return_value=258
        def times(handle,created,*unused):
            created._obj.dwLowDateTime=2000;created._obj.dwHighDateTime=0;return True
        def image(handle,flags,buffer,size):
            buffer.value=str(self.root/'Runtime/python.exe');return True
        lib.GetProcessTimes.side_effect=times;lib.QueryFullProcessImageNameW.side_effect=image
        with patch.object(ctypes,'WinDLL',return_value=lib):
            with self.assertRaisesRegex(shutdown.QuiescenceError,'identity changed'):
                shutdown._windows_stop(self.row(101,start=1000),self.root)
        lib.TerminateProcess.assert_not_called();lib.CloseHandle.assert_called_once_with(123)


if __name__=='__main__':unittest.main()
