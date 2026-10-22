"""Cross-platform transitions use real selectors with synthetic devices/assets.

These cases prove policy and task boundaries, not inference on physical hardware.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from runtime_policy import GIB
import media_defaults
import music_selection
import music_cpu
import tts_policy
import radeon_edit


def hardware(system,backend,*,free=12,ram=24,shared=False,compute=True):
    gpu={'available':True,'compute_ok':compute,'bf16_compute_ok':compute,'backend':backend,
         'index':0,'free_bytes':int(free*GIB),'total_bytes':24*GIB,'shared_memory':shared}
    return {'system':system,'machine':'x86_64','gpus':[gpu] if backend in ('cuda','vulkan') else [],
            'ram_available_bytes':int(ram*GIB),'amd_gpu':gpu if backend=='rocm' else {},
            'media_gpu':gpu if backend in ('rocm','cuda') else {}}


class HardwareMediaTransitions(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='Portal hardware transitions ')
        self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        # Minimal public file fixtures. No model import or output generation.
        for relative in (tts_policy.PIPER_MODEL,tts_policy.PIPER_MODEL+'.json',
                         'Voice/Piper/packages/piper/__init__.py','Voice/Piper/packages/onnxruntime/__init__.py',
                         'Runtime/LinuxPackages/extras/piper/__init__.py','Runtime/LinuxPackages/media/onnxruntime/__init__.py',
                         'Runtime/ProteinDesign/windows-cpu/torch/__init__.py','Runtime/LinuxTorch/cpu/torch/__init__.py',
                         'Runtime/AMDMusic/packages/loguru/__init__.py','Runtime/AMDMusic/api-packages/diffusers/__init__.py',
                         'Runtime/AMDAudio/packages/numpy/__init__.py','Runtime/LinuxPackages/media/loguru/__init__.py',
                         'Runtime/LinuxPackages/media/diffusers/__init__.py','Runtime/LinuxPackages/media/numpy/__init__.py',
                         'Music/ACE-Step-1.5/checkpoints/acestep-v15-turbo/config.json',
                         'Music/ACE-Step-1.5/checkpoints/vae/config.json',
                         'Music/ACE-Step-1.5/checkpoints/Qwen3-Embedding-0.6B/config.json'):
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        self.music={'prompt':'piano','lyrics':'','duration':15,'instrumental':True,'root':self.root,'policy':{}}

    def test_auto_routes_follow_each_machine_without_retaining_the_previous_backend(self):
        cases=[('Windows','cuda','acestep-service',False,'qwen'),
               ('Windows','rocm','acestep-scaled',True,'qwen'),
               ('Windows','vulkan','musicgen-cpu',True,'piper'),
               ('Linux','cuda','acestep-scaled',True,'qwen'),
               ('Linux','rocm','acestep-scaled',True,'qwen'),
               ('Linux','cpu','musicgen-cpu',True,'piper'),
               ('Windows','cuda','acestep-service',False,'qwen')]
        with patch.object(music_cpu,'assets'):
            for system,backend,music,reference,voice in cases:
                with self.subTest(system=system,backend=backend):
                    hw=hardware(system,backend)
                    self.assertEqual(music_selection.admit(hardware=hw,**self.music)['engine'],music)
                    scaled=media_defaults.reference_video_scaled(root=self.root,policy={},hardware=hw)
                    self.assertEqual(scaled,reference)
                    if scaled and backend in ('cuda','rocm'):
                        self.assertEqual(radeon_edit.plan('video-edit',root=self.root,hardware=hw)['engine'],'wan-vace-1.3b')
                    elif scaled:
                        with self.assertRaisesRegex(RuntimeError,'compute probe'):
                            radeon_edit.plan('video-edit',root=self.root,hardware=hw)
                    self.assertEqual(tts_policy.tts_plan(self.root,hardware=hw,policy={})['engine'],voice)

    def test_manual_choices_refuse_an_incompatible_move_instead_of_becoming_automatic(self):
        win=hardware('Windows','cuda');linux=hardware('Linux','cuda')
        for hw,bad_music,bad_reference in ((win,'acestep-scaled','vace13'),(linux,'acestep-service','wan22')):
            with self.assertRaises(RuntimeError):
                music_selection.admit(hardware=hw,**{**self.music,'policy':{'media':{'music_engine':bad_music}}})
            with self.assertRaises(RuntimeError):
                media_defaults.reference_video_scaled(root=self.root,hardware=hw,policy={'media':{'reference_video_profile':bad_reference}})
            self.assertEqual(media_defaults.reference_video_scaled('auto',root=self.root,hardware=hw,
                             policy={'media':{'reference_video_profile':bad_reference}}),hw['system']=='Linux')

    def test_low_memory_fallbacks_preserve_task_and_explicit_selections(self):
        with patch.object(music_cpu,'assets'):
            for system,backend in (('Windows','cuda'),('Windows','rocm'),('Linux','cuda'),('Linux','rocm')):
                hw=hardware(system,backend,free=2)
                with self.subTest(system=system,backend=backend):
                    self.assertEqual(music_selection.admit(hardware=hw,**self.music)['engine'],'musicgen-cpu')
                    for change in ({'lyrics':'sing this','instrumental':False},{'duration':31}):
                        with self.assertRaises(ValueError):music_selection.admit(hardware=hw,**{**self.music,**change})
                    explicit='acestep-service' if system=='Windows' and backend=='cuda' else 'acestep-scaled'
                    with self.assertRaises(RuntimeError):music_selection.admit(explicit,hardware=hw,**self.music)
                    with self.assertRaisesRegex(RuntimeError,'English only'):
                        tts_policy.tts_plan(self.root,language='Japanese',hardware=hw,policy={})
                    with self.assertRaises(RuntimeError):tts_policy.tts_plan(self.root,engine='qwen',hardware=hw,policy={})

    def test_shared_memory_and_failed_compute_probe_do_not_count_as_dedicated_gpu(self):
        for system in ('Windows','Linux'):
            hw=hardware(system,'rocm',shared=True,ram=11)
            with patch.object(music_cpu,'assets'):
                self.assertEqual(music_selection.admit(hardware=hw,**self.music)['engine'],'musicgen-cpu')
            with self.assertRaisesRegex(RuntimeError,'24 GiB'):
                radeon_edit.plan('video-edit',root=self.root,hardware=hw)
            self.assertEqual(tts_policy.tts_plan(self.root,hardware=hw,policy={})['engine'],'piper')
            hw=hardware(system,'rocm',compute=False)
            with self.assertRaisesRegex(RuntimeError,'compute probe'):
                radeon_edit.plan('video-edit',root=self.root,hardware=hw)
            self.assertEqual(tts_policy.tts_plan(self.root,hardware=hw,policy={})['engine'],'piper')

if __name__=='__main__':unittest.main()
