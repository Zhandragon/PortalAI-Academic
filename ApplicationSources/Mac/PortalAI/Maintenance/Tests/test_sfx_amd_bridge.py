from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import sfx_amd_bridge as sfx
from workload_compatibility import require_workload


class AMDSfxTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.hw={'system':'Windows','machine':'AMD64','ram_available_bytes':20*sfx.GIB,'gpus':[],
                 'amd_gpu':{'available':True,'compute_ok':True,'bf16_compute_ok':True,'free_bytes':8*sfx.GIB,'shared_memory':True}}
        for name in ('Runtime/AMDAudio/packages/open_clip/__init__.py','Services/MMAudio/weights/mmaudio_small_44k.pth'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()

    def test_shared_memory_profile_and_reserve(self):
        plan=sfx.plan(self.root,hardware=self.hw)
        self.assertEqual(plan['variant'],'small_44k');self.assertEqual(plan['min_free_ram_bytes'],4*sfx.GIB)
        self.hw['ram_available_bytes']=12*sfx.GIB
        with self.assertRaisesRegex(RuntimeError,'18 GiB'):sfx.plan(self.root,hardware=self.hw)

    def test_driver_name_is_not_a_compute_test(self):
        self.hw['amd_gpu']['compute_ok']=False
        with self.assertRaisesRegex(RuntimeError,'compute probe'):sfx.plan(self.root,hardware=self.hw)
        with self.assertRaisesRegex(RuntimeError,'compute probe'):require_workload('sfx',self.hw)

    def test_video_conditioning_uses_the_same_compute_admission(self):
        require_workload('sfx',self.hw)
        require_workload('video-sfx',self.hw)
        with self.assertRaises(RuntimeError):require_workload('video-sfx',{**self.hw,'amd_gpu':{'compute_ok':False}})

    def test_invalid_job_is_rejected_before_process_start(self):
        with patch.object(sfx,'run_generation') as launch:
            for kw in ({'duration':9},{'duration':float('nan')},{'num_steps':0},{'seed':-1},{'cfg_strength':float('inf')}):
                with self.assertRaises(ValueError):sfx.generate({},'rain',**kw)
        launch.assert_not_called()


if __name__=='__main__':unittest.main()
