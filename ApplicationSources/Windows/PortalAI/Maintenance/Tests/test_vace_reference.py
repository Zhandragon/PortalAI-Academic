"""No-model tests for reference generation, admission and cancellation cleanup."""
import ast
from contextlib import contextmanager, ExitStack
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
import vace_reference as ref
from comfy_bridge import ComfyBridge
import radeon_edit


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.source=self.root/'source.png';self.source.write_bytes(b'image')
        self.request={'source':str(self.source),'prompt':'a bird flies','width':320,'height':176,
                      'frames':17,'fps':8,'seed':42,'conditioning':'reference-image'}
        self.profile={'engine':'wan-vace-1.3b','backend':'rocm','max_memory_bytes':12*1024**3,
                      'min_free_ram_bytes':4*1024**3,'cpu_validation':False}
        self.base=json.loads((ROOT/'Workflows/API/Wan2.1_VACE_14B_V2V_API.json').read_text())
        self.bridge=ComfyBridge.__new__(ComfyBridge)
        self.bridge.workflow_file=Mock(side_effect=lambda _:copy.deepcopy(self.base))
        self.bridge.ccfg={}

    def test_generation_removes_video_control_but_keeps_image_and_reference_trim(self):
        generated=ref.configure(self.bridge,self.request,'reference.png')
        self.assertNotIn('8',generated);self.assertNotIn('9',generated)
        self.assertNotIn('control_video',generated['10']['inputs'])
        self.assertEqual(generated['10']['inputs']['reference_image'],['16',0])
        self.assertEqual(generated['16']['inputs']['image'],'reference.png')
        self.assertEqual(generated['12']['inputs']['trim_amount'],['10',3])
        self.assertNotIn('3',generated);self.assertEqual(generated['11']['inputs']['steps'],20)
        self.assertEqual(generated['1']['inputs']['unet_name'],'wan2.1_vace_1.3B_fp16.safetensors')
        self.assertEqual(generated['13']['class_type'],'VAEDecodeTiled')
        edited=copy.deepcopy(self.base)
        self.bridge.configure_vace_video_edit(edited,'source.mp4','edit',fast=False)
        radeon_edit.small_vace(edited)
        self.assertIn('control_video',edited['10']['inputs']);self.assertNotIn('reference_image',edited['10']['inputs'])

    def test_missing_reference_never_silently_becomes_text_generation(self):
        with self.assertRaisesRegex(ValueError,'explicit image reference'):ref.configure(self.bridge,self.request,None)

    def test_input_authorization_precedes_probe_or_job(self):
        with patch.object(ref,'media_reference',side_effect=PermissionError('another profile')),patch.object(ref,'_probe') as probe:
            with self.assertRaises(PermissionError):ref.prepare(self.root,self.source,'prompt')
        probe.assert_not_called()

    def test_defaults_and_explicit_bounds(self):
        with patch.object(ref,'_probe',return_value=({'width':1920,'height':1080},{})):
            result=ref.prepare(self.root,self.source,'prompt')
            self.assertEqual((result['width'],result['height'],result['frames'],result['fps']),(320,176,17,8))
            for kwargs in ({'frames':81},{'frames':18},{'width':512},{'width':319},{'fps':31},{'uncensored':True}):
                with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):ref.prepare(self.root,self.source,'prompt',**kwargs)

    def test_memory_and_compute_admission_never_become_cpu_fallback(self):
        hardware={'system':'Windows','machine':'AMD64','ram_available_bytes':32*1024**3,'gpus':[],
                  'amd_gpu':{'available':True,'compute_ok':True,'free_bytes':7*1024**3,'shared_memory':False,'backend':'rocm'}}
        with self.assertRaisesRegex(RuntimeError,'GPU memory'):radeon_edit.plan('video-edit',root=self.root,hardware=hardware)
        hardware['amd_gpu']['free_bytes']=8*1024**3
        hardware['ram_available_bytes']=15*1024**3
        with self.assertRaisesRegex(RuntimeError,'16 GiB'):radeon_edit.plan('video-edit',root=self.root,hardware=hardware)
        hardware['ram_available_bytes']=32*1024**3
        self.assertEqual(radeon_edit.plan('video-edit',root=self.root,hardware=hardware)['backend'],'rocm')
        with self.assertRaisesRegex(ValueError,'admitted'):
            ref.generate(self.request,{**self.profile,'backend':'cpu'},root=self.root)

    def test_output_validator_rejects_short_frame_count(self):
        output=self.root/'result.mp4';output.write_bytes(b'X'*1024)
        stream={'width':320,'height':176,'avg_frame_rate':'8/1','duration':'2.125','nb_read_frames':'17'}
        with patch.object(ref,'_probe',return_value=(stream,{})):
            self.assertEqual(ref.validate_output(self.root,output,self.request),2.125)
            stream['nb_read_frames']='16'
            with self.assertRaisesRegex(RuntimeError,'frame count'):ref.validate_output(self.root,output,self.request)

    def run_case(self,error=None):
        staged=self.root/'staged.png';staged.write_bytes(b'input')
        self.bridge.stage_input_file=Mock(return_value=('staged.png',staged))
        closed=[];workspaces=[]
        @contextmanager
        def session(*args,**kwargs):
            try:yield
            finally:closed.append(True)
        def run(workflow,destination):
            workspaces.append(destination)
            if error:raise error
            result=destination/'video.mp4';result.write_bytes(b'X'*1024)
            return {'files':[str(result)]}
        self.bridge.run=Mock(side_effect=run)
        with patch('comfy_bridge.ComfyBridge',return_value=self.bridge) as factory,\
             patch('bounded_comfy.session',side_effect=session),patch('runtime_policy.require_space'),\
             patch.object(ref,'validate_output',return_value=17/8):
            # Retain the real exact-file cleanup method on the mocked factory.
            factory.cleanup_staged_file=ComfyBridge.cleanup_staged_file
            if error:
                with self.assertRaises(type(error)):ref.generate(self.request,self.profile,root=self.root)
            else:
                result=ref.generate(self.request,self.profile,root=self.root)
                self.assertEqual(result['conditioning'],'reference-image');self.assertTrue(Path(result['files'][0]).is_file())
        self.assertEqual(closed,[True]);self.assertFalse(staged.exists())
        self.assertTrue(all(not path.exists() for path in workspaces))
        if error:self.assertFalse((self.root/'Outputs').exists())

    def test_success_publishes_only_validated_clip_and_cleans_inputs(self):self.run_case()
    def test_cancellation_closes_owned_session_and_never_publishes(self):self.run_case(KeyboardInterrupt())
    def test_failed_model_closes_owned_session_and_never_publishes(self):self.run_case(RuntimeError('model failed'))

    def test_failed_publication_removes_partial_file_and_never_publishes_final(self):
        from contextlib import nullcontext
        self.bridge.stage_input_file=Mock(return_value=('reference.png',None))
        def run(workflow,destination):
            result=destination/'generated.mp4';result.write_bytes(b'X'*1024)
            return {'files':[str(result)]}
        def failed_copy(source,destination):
            destination.write_bytes(b'partial')
            raise OSError('disk full')
        self.bridge.run=Mock(side_effect=run)
        with patch('comfy_bridge.ComfyBridge',return_value=self.bridge),\
             patch('bounded_comfy.session',return_value=nullcontext()),patch('runtime_policy.require_space'),\
             patch.object(ref,'validate_output',return_value=17/8),patch.object(ref.shutil,'copy2',side_effect=failed_copy):
            with self.assertRaisesRegex(OSError,'disk full'):ref.generate(self.request,self.profile,root=self.root)
        self.assertEqual(list((self.root/'Outputs/Videos').iterdir()),[])

    def revocation_case(self, stage):
        from profile_paths import UID_ENV, EPOCH_ENV, workspace_root, ProfileLocked
        context=('a'*32,'b'*32)
        marker=self.root/'Private/active-session.json';marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({'user_id':context[0],'epoch':context[1],'state':'open'}))
        def revoke():
            marker.write_text(json.dumps({'user_id':context[0],'epoch':context[1],'state':'closing'}))
        workspace=workspace_root(self.root,context[0])
        staged=workspace/'Cache/MediaWorkers/staged.png';staged.parent.mkdir(parents=True)
        staged.write_bytes(b'input')
        self.bridge.stage_input_file=Mock(return_value=('staged.png',staged))
        closed=[];temporary=[]
        @contextmanager
        def session(*args,**kwargs):
            try:yield
            finally:closed.append(True)
        def run(workflow,destination):
            temporary.append(destination)
            generated=destination/'generated.mp4';generated.write_bytes(b'X'*1024)
            if stage=='inference':revoke()
            return {'files':[str(generated)]}
        self.bridge.run=Mock(side_effect=run)
        copy=ref.shutil.copy2;rename=Path.replace
        def copying(source,destination):
            result=copy(source,destination)
            if stage=='copy':revoke()
            return result
        def renaming(source,destination):
            result=rename(source,destination)
            if stage=='rename':revoke()
            return result
        with (patch.dict(os.environ,{UID_ENV:context[0],EPOCH_ENV:context[1]}),
              patch('comfy_bridge.ComfyBridge',return_value=self.bridge) as factory,
              patch('bounded_comfy.session',side_effect=session),patch('runtime_policy.require_space'),
              patch.object(ref,'validate_output',return_value=17/8),
              patch.object(ref.shutil,'copy2',side_effect=copying) as copying_mock,
              patch.object(Path,'replace',renaming)):
            factory.cleanup_staged_file=ComfyBridge.cleanup_staged_file
            with self.assertRaises(ProfileLocked):ref.generate(self.request,self.profile,root=self.root)
            if stage=='inference':copying_mock.assert_not_called()
        self.assertEqual(closed,[True]);self.assertFalse(staged.exists())
        self.assertTrue(all(not path.exists() for path in temporary))
        self.assertEqual(list((workspace/'Outputs').rglob('*.mp4')),[])
        self.assertFalse((self.root/'Outputs').exists())

    def test_revoked_login_after_inference_never_publishes(self):self.revocation_case('inference')
    def test_revoked_login_during_copy_removes_own_partial(self):self.revocation_case('copy')
    def test_revoked_login_during_rename_removes_own_final(self):self.revocation_case('rename')


class ReferenceCliTests(unittest.TestCase):
    def test_scaled_route_reclaims_before_admission_and_propagates_failure(self):
        tree=ast.parse((ROOT/'Agent/ai_tools.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="args.cmd == 'video'"
                  and any(isinstance(v,ast.ImportFrom) and v.module=='radeon_edit' for v in n.body))
        events=[]
        @contextmanager
        def lease(*args):
            events.append('reclaim')
            try:yield
            finally:events.append('restore')
        args=SimpleNamespace(cmd='video',prompt='bird flies',allow_unsynced_speech=False,seed=42,input='reference.png',
                             width=None,height=None,length=None,fps=None,uncensored=False,profile=None)
        namespace={'args':args,'root_dir':lambda:ROOT,'_looks_like_visible_dialogue':lambda text:False,
                   '_exclusive_gpu':lease,'_arm_abort_watchdog':Mock(),'_complete_abort_watchdog':Mock(),
                   '_set_gpu_state':Mock(),'service_stop':Mock(),'emit':Mock(side_effect=StopIteration),
                   '_default_variant':Mock(return_value=('official','fixture'))}
        with patch('media_defaults.reference_video_scaled',return_value=True),\
             patch('radeon_edit.plan',side_effect=lambda *a:events.append('admit') or {'engine':'fixture'}),\
             patch.object(ref,'prepare',return_value={'source':'reference.png'}) as prepare,\
             patch.object(ref,'generate',side_effect=RuntimeError('cancelled')):
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                exec(compile(ast.Module(body=[node],type_ignores=[]),'reference-route','exec'),namespace)
        self.assertEqual(events,['reclaim','admit','restore']);namespace['emit'].assert_not_called()
        namespace['_complete_abort_watchdog'].assert_not_called();prepare.assert_called_once()


if __name__=='__main__':unittest.main()
