"""Admission must account for Windows commit, not just physical RAM/VRAM."""
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
import tempfile
import runtime_policy as rp

class ComfyCommitPolicyTests(unittest.TestCase):
    def hardware(self, commit=18, system='Windows', vram=24):
        return dict(system=system, ram_available_bytes=20*rp.GIB, ram_total_bytes=32*rp.GIB,
                    commit_available_bytes=commit*rp.GIB, gpus=[dict(index=0,backend='cuda',total_bytes=vram*rp.GIB)])

    def test_3090_low_commit_uses_validated_bounded_loading(self):
        plan=rp.tool_plan('comfyui', self.hardware())
        self.assertEqual(plan['args'],['--disable-pinned-memory','--vram-headroom','12'])
        self.assertEqual(plan['backend'],'cuda')

    def test_more_commit_retains_normal_loading(self):
        self.assertEqual(rp.tool_plan('comfyui',self.hardware(commit=40))['args'],[])

    def test_commit_budget_independent_of_free_ram(self):
        hw=self.hardware(commit=9);hw['ram_available_bytes']=48*rp.GIB
        with self.assertRaisesRegex(RuntimeError,'Windows commit'):
            rp.tool_plan('comfyui',hw)

    def test_partial_gib_rounds_reserve_up(self):
        hw=self.hardware();hw['commit_available_bytes']-=rp.GIB//4
        self.assertEqual(rp.tool_plan('comfyui',hw)['args'][-1],'13')

    def test_smaller_gpu_does_not_get_impossible_12_gib_reserve(self):
        self.assertEqual(rp.tool_plan('comfyui',self.hardware(vram=8))['args'],['--lowvram'])

    def test_linux_cuda_does_not_receive_windows_policy(self):
        self.assertEqual(rp.tool_plan('comfyui',self.hardware(commit=9,system='Linux'))['args'],[])

    def test_cpu_path_is_unchanged(self):
        hw=self.hardware(commit=9);hw['gpus']=[]
        self.assertEqual(rp.tool_plan('comfyui',hw)['args'],['--cpu'])

    def test_probe_failure_does_not_invent_headroom(self):
        if rp.os.name != 'nt':self.skipTest('Windows API boundary')
        with patch.object(rp.ctypes.windll.kernel32,'GlobalMemoryStatusEx',return_value=0):
            with self.assertRaises(OSError):rp._windows_memory_status()

    def test_detect_hardware_exposes_commit_separately_from_ram(self):
        if rp.os.name != 'nt':self.skipTest('Windows API boundary')
        status=SimpleNamespace(total=32*rp.GIB,available=20*rp.GIB,
                               page_total=48*rp.GIB,page_available=9*rp.GIB)
        with patch.object(rp,'_windows_memory_status',return_value=status), \
             patch.object(rp,'run_probe',return_value='0, Test GPU, 24576, 24576'):
            hw=rp.detect_hardware()
        self.assertEqual(hw['ram_available_bytes'],20*rp.GIB)
        self.assertEqual(hw['commit_total_bytes'],48*rp.GIB)
        self.assertEqual(hw['commit_available_bytes'],9*rp.GIB)
        with self.assertRaisesRegex(RuntimeError,'Windows commit'):
            rp.tool_plan('comfyui',hw)

    def test_each_launch_request_rechecks_available_memory(self):
        with patch.object(rp,'detect_hardware',side_effect=[self.hardware(commit=40),self.hardware(commit=9)]) as detect:
            self.assertEqual(rp.tool_plan('comfyui')['args'],[])
            with self.assertRaisesRegex(RuntimeError,'Windows commit'):rp.tool_plan('comfyui')
        self.assertEqual(detect.call_count,2)

    def test_reservation_boundary_keeps_at_least_four_gib(self):
        hw=self.hardware(commit=10)
        self.assertEqual(rp.tool_plan('comfyui',hw)['args'][-1],'20')
        hw['commit_available_bytes']-=1
        with self.assertRaisesRegex(RuntimeError,'Windows commit'):rp.tool_plan('comfyui',hw)

    def test_radeon_does_not_receive_cuda_commit_flags(self):
        hw=self.hardware(commit=1);hw['gpus']=[]
        hw['amd_gpu']={'available':True,'compute_ok':True,'shared_memory':True,'free_bytes':4*rp.GIB}
        plan=rp.tool_plan('comfyui',hw)
        self.assertEqual(plan['backend'],'rocm')
        self.assertNotIn('--vram-headroom',plan['args'])
        self.assertNotIn('--disable-pinned-memory',plan['args'])
        hw['ram_available_bytes']=11*rp.GIB
        with self.assertRaisesRegex(RuntimeError,'AMD ComfyUI'):rp.tool_plan('comfyui',hw)

    def test_windows_service_passes_flags_without_changing_quality(self):
        if rp.os.name != 'nt':self.skipTest('Windows service boundary')
        import service_manager as service
        with tempfile.TemporaryDirectory(prefix='ComfyCommit-') as folder:
            root=Path(folder);spec=service.SERVICES['comfyui'];work=root/spec['cwd']
            for rel in (spec['python'],spec['main']):
                p=work/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            with patch.object(service,'root_dir',return_value=root), \
                 patch('profile_paths.enabled',return_value=False), \
                 patch.object(service,'tool_plan',side_effect=lambda name:rp.tool_plan(name,self.hardware())), \
                 patch.object(service,'_log_path',return_value=root/'log.txt'), \
                 patch.object(service,'require_space'),patch.object(service,'_remember_pid'), \
                 patch.object(service,'launch_detached',return_value=12345) as launch:
                self.assertEqual(service._launch_comfyui_direct(),12345)
            command=launch.call_args.args[0]
            self.assertIn('--disable-pinned-memory --vram-headroom 12',command)
            for quality_flag in ('--width','--height','--frames','--steps'):
                self.assertNotIn(quality_flag,command)

    def test_commit_refusal_does_not_launch_worker(self):
        if rp.os.name != 'nt':self.skipTest('Windows service boundary')
        import service_manager as service
        with patch('profile_paths.enabled',return_value=False), \
             patch.object(service,'tool_plan',side_effect=lambda name:rp.tool_plan(name,self.hardware(commit=9))), \
             patch.object(service,'launch_detached') as launch:
            with self.assertRaisesRegex(RuntimeError,'Windows commit'):service._launch_comfyui_direct()
        launch.assert_not_called()

if __name__=='__main__':unittest.main()
