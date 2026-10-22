"""Actual durable Stop files and profile changes at each admission boundary."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import ai_tools as cli
import service_manager as service
import workload_request
from profile_paths import ProfileLocked


class WorkloadRequestTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='Portal queued workload ')
        self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        (self.root/'Agent/.runtime').mkdir(parents=True)

    def stop(self):
        (self.root/'Agent/.runtime/qwen_last_stop.json').write_text(json.dumps({'stopped_at':101}))

    def context(self,kind):
        if kind=='image':return cli._exclusive_gpu('comfyui','image')
        if kind=='voice':return cli._exclusive_gpu(None,'voice')
        if kind=='pipeline':return cli._exclusive_pipeline('dialogue')
        return service.science_workload('protein.minimize',gpu_requested=True,gpu_backend='openmm-opencl')

    def test_stop_before_after_lease_and_inside_handoff_never_enters_work(self):
        for kind in ('image','voice','pipeline','science'):
            for phase in ('before','lease','handoff','ready'):
                with self.subTest(kind=kind,phase=phase), ExitStack() as stack:
                    (self.root/'Agent/.runtime/qwen_last_stop.json').unlink(missing_ok=True)
                    stack.enter_context(patch.object(cli,'root_dir',return_value=self.root))
                    stack.enter_context(patch.object(service,'root_dir',return_value=self.root))
                    stack.enter_context(patch.object(service,'_read_qwen_generation',return_value={}))
                    stack.enter_context(patch.object(workload_request.time,'time',return_value=100))
                    module=service if kind=='science' else cli
                    def acquire(*args,**kwargs):
                        if phase=='lease':self.stop()
                        return 'owned-test-lease'
                    def handoff(*args,start_guard):
                        if phase=='handoff':self.stop()
                        start_guard()
                        if phase=='ready':self.stop()
                        return {'active':False}
                    begin=stack.enter_context(patch.object(module,'qwen_gpu_handoff_begin',side_effect=handoff))
                    end=stack.enter_context(patch.object(module,'qwen_gpu_handoff_end'))
                    release=stack.enter_context(patch.object(module,'release_gpu_lease'))
                    lease=stack.enter_context(patch.object(module,'acquire_gpu_lease',side_effect=acquire))
                    quiesce=stack.enter_context(patch.object(module,'quiesce_gpu_workers'))
                    stop=stack.enter_context(patch.object(cli,'service_stop'))
                    stack.enter_context(patch.object(cli,'_clear_gpu_state'))
                    if phase=='before':self.stop()
                    with self.assertRaisesRegex(RuntimeError,'cancelled by Stop'):
                        with self.context(kind):self.fail('Work ran after Stop')
                    if phase=='before':lease.assert_not_called();release.assert_not_called()
                    else:release.assert_called_once_with('owned-test-lease')
                    if phase in ('before','lease'):
                        begin.assert_not_called();quiesce.assert_not_called();stop.assert_not_called()

    def test_login_change_while_waiting_cannot_start_handoff(self):
        for kind in ('image','pipeline','science'):
            with self.subTest(kind=kind),ExitStack() as stack:
                identity=[('synthetic-user','original-epoch')]
                stack.enter_context(patch.object(workload_request,'capture',side_effect=lambda root:identity[0]))
                stack.enter_context(patch.object(service,'_read_qwen_generation',return_value={}))
                stack.enter_context(patch.object(cli,'root_dir',return_value=self.root))
                stack.enter_context(patch.object(service,'root_dir',return_value=self.root))
                module=service if kind=='science' else cli
                def acquire(*args,**kwargs):identity[0]=('synthetic-user','new-epoch');return 'owned'
                stack.enter_context(patch.object(module,'acquire_gpu_lease',side_effect=acquire))
                begin=stack.enter_context(patch.object(module,'qwen_gpu_handoff_begin'))
                stack.enter_context(patch.object(module,'qwen_gpu_handoff_end'))
                release=stack.enter_context(patch.object(module,'release_gpu_lease'))
                quiesce=stack.enter_context(patch.object(module,'quiesce_gpu_workers'))
                with self.assertRaises(ProfileLocked):
                    with self.context(kind):self.fail('Revoked request executed')
                begin.assert_not_called();quiesce.assert_not_called();release.assert_called_once_with('owned')

    def test_original_request_time_is_retained_across_checks(self):
        with patch.object(workload_request.time,'time',return_value=100), \
             patch.object(service,'_read_qwen_generation',return_value={}):
            check=workload_request.request_guard(self.root)
            check();self.stop()
            with self.assertRaisesRegex(RuntimeError,'cancelled by Stop'):check()

if __name__=='__main__':unittest.main()
