"""No-model regressions for Radeon cleanup, restoration and precision admission."""
from contextlib import ExitStack
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
sys.path.append(str(ROOT/'Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages'))
import media_edit_bridge as media
import media_precision as precision
import musetalk_amd_entry as muse
import sfx_amd_bridge as sfx


class RadeonRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def lease_context(self,stack,restore_error=None):
        import service_manager as services
        mocked={}
        for name in ('acquire_gpu_lease','qwen_gpu_handoff_begin','qwen_gpu_handoff_end',
                     'quiesce_gpu_workers','release_gpu_lease','start','stop','wait_ready'):
            mocked[name]=stack.enter_context(patch.object(services,name))
        stack.enter_context(patch('radeon_edit.uses_radeon',return_value=True))
        if restore_error:mocked['qwen_gpu_handoff_end'].side_effect=restore_error
        return mocked

    def test_restoration_error_is_visible_and_lease_released(self):
        with ExitStack() as stack:
            calls=self.lease_context(stack,RuntimeError('Qwen unhealthy'))
            with self.assertRaisesRegex(RuntimeError,'Qwen unhealthy'):
                with media._exclusive_comfy('test'):pass
            calls['release_gpu_lease'].assert_called_once_with(calls['acquire_gpu_lease'].return_value)

    def test_tool_error_survives_successful_restoration(self):
        with ExitStack() as stack:
            calls=self.lease_context(stack)
            with self.assertRaisesRegex(ValueError,'tool failed'):
                with media._exclusive_comfy('test'):raise ValueError('tool failed')
            calls['qwen_gpu_handoff_end'].assert_called_once()
            calls['release_gpu_lease'].assert_called_once()

    def mask_case(self,fail=False):
        from PIL import Image
        source=self.root/'source.png';mask=self.root/'mask.png';generated=self.root/'generated.png'
        Image.new('RGB',(64,64),'red').save(source);Image.new('L',(64,64),255).save(mask)
        Image.new('RGB',(64,64),'blue').save(generated)
        residual=self.root/'mask_expanded.png';residual.write_bytes(b'user data')
        seen=[]
        def edit(profile,input_path,instruction,*,mask,seed):
            seen.append(mask);self.assertTrue(mask.is_file())
            self.assertTrue(mask.is_relative_to(self.root/'Cache/MediaEdit'))
            if fail:raise RuntimeError('model failed')
            return {'files':[str(generated)]}
        with patch.object(media,'_root_dir',return_value=self.root),patch('radeon_edit.uses_radeon',return_value=True),\
             patch('radeon_edit.plan',return_value={}),patch('radeon_edit.edit',side_effect=edit):
            if fail:
                with self.assertRaisesRegex(RuntimeError,'model failed'):
                    media._comfy_inpaint_image(source,mask,'change',expand=0)
            else:
                output=media._comfy_inpaint_image(source,mask,'change',expand=0)
                self.assertTrue(output.is_file())
        self.assertEqual(residual.read_bytes(),b'user data')
        self.assertEqual(len(seen),1);self.assertFalse(seen[0].parent.exists())

    def test_expanded_mask_is_unique_portable_and_cleaned(self):self.mask_case()
    def test_expanded_mask_cleaned_on_failure(self):self.mask_case(True)

    def workspace(self):
        job=self.root/'Cache/MuseTalk/rocm_test';job.mkdir(parents=True);(job/'frame.png').write_bytes(b'frame')
        neighbor=job.with_name('rocm_other');neighbor.mkdir();(neighbor/'keep').write_bytes(b'keep')
        output=self.root/'out.mp4';output.write_bytes(b'X'*2048)
        return job,neighbor,output

    def probe_result(self,**changes):
        data={'streams':[{'codec_type':'video','width':256,'height':256},{'codec_type':'audio'}],
              'format':{'duration':'1.0'}}
        data.update(changes)
        return SimpleNamespace(stdout=json.dumps(data).encode())

    def test_only_verified_successful_musetalk_workspace_is_removed(self):
        job,neighbor,output=self.workspace()
        with patch.object(muse.subprocess,'run',return_value=self.probe_result()):
            muse.finish_workspace(job,output,1,self.root)
        self.assertFalse(job.exists());self.assertTrue(neighbor.exists());self.assertTrue(output.exists())

    def test_invalid_musetalk_output_retains_recovery_workspace(self):
        job,neighbor,output=self.workspace()
        with patch.object(muse.subprocess,'run',return_value=self.probe_result(format={'duration':'nan'})):
            with self.assertRaisesRegex(RuntimeError,'duration mismatch'):muse.finish_workspace(job,output,1,self.root)
        self.assertTrue(job.exists());self.assertTrue(neighbor.exists())

    def test_musetalk_cleanup_rejects_unrelated_directory(self):
        job,neighbor,output=self.workspace()
        with self.assertRaisesRegex(RuntimeError,'escaped'):muse.finish_workspace(neighbor.parent,output,1,self.root)
        self.assertTrue(job.exists())

    def test_backend_labels_distinguish_linux_cuda_and_rocm(self):
        for backend,hip,cuda in [('rocm','7.2',None),('cuda',None,'12.8'),('cpu',None,None)]:
            torch=SimpleNamespace(version=SimpleNamespace(hip=hip,cuda=cuda))
            self.assertEqual(precision.execution_backend(torch),backend)
            self.assertIn('cpu-validation',precision.execution_backend(torch,True))

    def test_bf16_checks_real_tensor_result(self):
        torch=MagicMock();torch.version=SimpleNamespace(hip='7.2',cuda=None)
        torch.cuda.is_available.return_value=True;torch.cuda.is_bf16_supported.return_value=True
        torch.all.return_value.item.return_value=True
        self.assertTrue(precision.check_bf16(torch)['bf16_compute_ok'])
        torch.ones.assert_called_once_with((16,16),device='cuda:0',dtype=torch.bfloat16)
        torch.cuda.synchronize.assert_called_once_with(0)
        torch.all.return_value.item.return_value=False
        with self.assertRaisesRegex(RuntimeError,'incorrect values'):precision.check_bf16(torch)

    def test_fp16_success_does_not_admit_sfx_without_bf16(self):
        hw={'system':'Windows','machine':'AMD64','ram_available_bytes':24*sfx.GIB,'gpus':[],
            'amd_gpu':{'available':True,'compute_ok':True,'free_bytes':8*sfx.GIB,'shared_memory':False}}
        with patch.object(precision,'probe_bf16') as probe:
            with self.assertRaisesRegex(RuntimeError,'BF16 GPU compute probe'):sfx.plan(self.root,hardware=hw)
            probe.assert_not_called()

    def test_wrong_backend_probe_is_rejected(self):
        result=SimpleNamespace(returncode=0,stdout='PORTALAI_BF16='+json.dumps({'bf16_compute_ok':True,'backend':'cuda'}),stderr='')
        with patch.object(precision.subprocess,'run',return_value=result):
            self.assertFalse(precision.probe_bf16(self.root,'rocm')['bf16_compute_ok'])


if __name__=='__main__':unittest.main()
