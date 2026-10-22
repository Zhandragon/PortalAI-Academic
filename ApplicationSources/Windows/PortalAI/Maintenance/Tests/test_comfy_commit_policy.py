"""Admission must account for Windows commit, not just physical RAM/VRAM."""
import unittest
from unittest.mock import patch
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

if __name__=='__main__':unittest.main()
