from contextlib import nullcontext
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
spec=importlib.util.spec_from_file_location('effort_smoke_cleanup',ROOT/'Tools/smoke_chat_effort.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


class EffortSmokeCleanupTests(unittest.TestCase):
    def test_user_stop_prevents_any_cleanup_restart(self):
        report={}
        with patch.object(smoke,'_guard',side_effect=smoke.PreparationCancelled('Stop')), \
             patch.object(smoke.service,'acquire_gpu_lease') as lease, \
             patch.object(smoke.service,'release_gpu_lease'), \
             patch.object(smoke.service,'qwen_gpu_handoff_begin') as begin:
            smoke.restore_baseline('original',{}, {},1,report)
        lease.assert_not_called();begin.assert_not_called()
        self.assertIn('Stop',report['baseline_restoration_skipped'])

    def test_new_listener_is_left_untouched(self):
        report={}
        with patch.object(smoke,'_guard'), \
             patch.object(smoke.service,'acquire_gpu_lease',return_value='lease'), \
             patch.object(smoke.service,'release_gpu_lease'), \
             patch.object(smoke.service,'_qwen_lifecycle_mutex',return_value=nullcontext()), \
             patch.object(smoke,'_owned_listener',return_value={'open':True,'listeners':[{'pid':2}]}), \
             patch.object(smoke.service,'qwen_gpu_handoff_begin') as begin:
            smoke.restore_baseline('original',{'listeners':[{'pid':1}]},{},1,report)
        begin.assert_not_called()
        self.assertIn('identity changed',report['baseline_restoration_skipped'])

    def test_stop_after_handoff_prevents_metadata_write_and_restore(self):
        report={};identity={'open':True,'listeners':[{'pid':2,'command_line':['new']}]}
        def guard(root,started_at,**kwargs):
            if kwargs.get('state'):raise smoke.PreparationCancelled('Stop')
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(smoke,'_guard',side_effect=guard), \
             patch.object(smoke.service,'acquire_gpu_lease',return_value='lease'), \
             patch.object(smoke.service,'release_gpu_lease'), \
             patch.object(smoke.service,'_qwen_lifecycle_mutex',side_effect=lambda:nullcontext()), \
             patch.object(smoke,'_owned_listener',return_value=identity), \
             patch.object(smoke,'_require_idle'), \
             patch.object(smoke.service,'qwen_gpu_handoff_begin',return_value={
                 'active':True,'state_path':str(Path(folder)/'state.json')}) as begin, \
             patch.object(smoke.service,'qwen_gpu_handoff_end') as end, \
             patch.object(smoke.service,'_remember_qwen_launch') as remember:
            smoke.restore_baseline(['original'],identity,{},1,report)
        begin.assert_called_once();end.assert_not_called();remember.assert_not_called()
        self.assertIn('Stop',report['baseline_restoration_skipped'])


if __name__=='__main__':unittest.main()
