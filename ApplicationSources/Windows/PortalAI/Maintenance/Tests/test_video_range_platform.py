"""Range cuts stay CPU-capable while generated replacements obey backend limits."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
import video_range_edit_bridge as ranges
import workload_compatibility as workloads


class RangePlatformTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.source=self.root/'source.mp4';self.source.write_bytes(b'fixture')
        self.hw={'system':'Windows','machine':'AMD64','gpus':[],
                 'amd_gpu':{'available':True,'compute_ok':True,'backend':'rocm'}}
        self.info={'duration':8.,'width':1920,'height':1080,'fps':30.,'has_audio':False}

    @staticmethod
    def output(source,destination,**kwargs):
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(b'output');return destination

    def fakes(self,stack):
        stack.enter_context(patch.object(ranges,'_root_dir',return_value=self.root))
        stack.enter_context(patch.object(ranges,'_probe',return_value=self.info))
        self.normalize=stack.enter_context(patch.object(ranges,'_normalize_visual',side_effect=self.output))
        stack.enter_context(patch.object(ranges,'_concat_visual',side_effect=self.output))

    def test_cpu_cut_never_requests_gpu_or_child_inference(self):
        workloads.require_workload('video-range-edit',{'system':'Windows','machine':'AMD64','gpus':[]})
        with ExitStack() as stack:
            self.fakes(stack)
            gate=stack.enter_context(patch.object(workloads,'require_workload'))
            child=stack.enter_context(patch.object(ranges,'_child_ai_tools'))
            result=ranges.video_range_edit(str(self.source),start=1,end=3,mode='cut',drop_audio=True)
        gate.assert_not_called();child.assert_not_called()
        self.assertEqual(result['output_duration_seconds'],6);self.assertEqual(result['resolution'],[1920,1080])
        self.assertTrue(Path(result['files'][0]).is_file())

    def test_radeon_vace_range_routes_to_scaled_video_edit(self):
        workloads.require_workload('video-edit',self.hw)
        def child(args):
            path=Path(args[args.index('--output')+1]);path.write_bytes(b'generated')
            return {'files':[str(path)]}
        with ExitStack() as stack:
            self.fakes(stack);gate=stack.enter_context(patch.object(workloads,'require_workload'))
            stack.enter_context(patch('radeon_edit.uses_radeon',return_value=True))
            run=stack.enter_context(patch.object(ranges,'_child_ai_tools',side_effect=child))
            result=ranges.video_range_edit(str(self.source),'make it sunny',start=1,end=3,mode='vace',drop_audio=True)
        gate.assert_called_once_with('video-edit');args=run.call_args.args[0]
        self.assertEqual(args[0],'video-edit');self.assertEqual(args[args.index('--chunk-frames')+1],'17')
        self.assertLessEqual(max(result['generation_resolution']),320);self.assertEqual(result['output_duration_seconds'],8)
        self.assertEqual(result['resolution'],[1920,1080]);self.assertEqual(result['fps'],30)
        self.assertEqual(result['generation_fps'],16)
        canvases={call.args[1].name:call.kwargs for call in self.normalize.call_args_list}
        for part in ('prefix.mp4','middle.mp4','suffix.mp4'):
            self.assertEqual((canvases[part]['width'],canvases[part]['height'],canvases[part]['fps']),(1920,1080,30))
        self.assertLessEqual(max(canvases['control.mp4']['width'],canvases['control.mp4']['height']),320)

    def test_radeon_unchanged_duration_auto_tail_uses_vace_without_regeneration(self):
        def child(args):
            path=Path(args[args.index('--output')+1]);path.write_bytes(b'generated')
            return {'files':[str(path)]}
        with ExitStack() as stack:
            self.fakes(stack);gate=stack.enter_context(patch.object(workloads,'require_workload'))
            stack.enter_context(patch('radeon_edit.uses_radeon',return_value=True))
            run=stack.enter_context(patch.object(ranges,'_child_ai_tools',side_effect=child))
            result=ranges.video_range_edit(str(self.source),'make it sunny',start=6,end=8,mode='auto',drop_audio=True)
        gate.assert_called_once_with('video-edit');self.assertEqual(run.call_args.args[0][0],'video-edit')
        self.assertEqual(result['mode'],'vace');self.assertEqual(result['output_duration_seconds'],8)
        self.assertIsNotNone(result['auto_reason'])

    def test_cpu_regeneration_is_rejected_before_child_or_staging(self):
        require=workloads.require_workload
        with patch.object(ranges,'_root_dir',return_value=self.root),\
             patch.object(ranges,'_probe',return_value=self.info),\
             patch.object(workloads,'require_workload',side_effect=lambda command:require(command,{**self.hw,'amd_gpu':None})),\
             patch('radeon_edit.uses_radeon',return_value=True),\
             patch.object(ranges,'_child_ai_tools') as child,patch.object(ranges,'_normalize_visual') as normalize:
            with self.assertRaisesRegex(RuntimeError,'no working CUDA or ROCm GPU'):
                ranges.video_range_edit(str(self.source),'new scene',start=1,end=3,mode='regenerate')
        child.assert_not_called();normalize.assert_not_called()

    def test_radeon_regeneration_is_reference_conditioned_and_keeps_canvas(self):
        workloads.require_workload('video',self.hw)
        raw=self.root/'raw.mp4';raw.write_bytes(b'generated')
        with ExitStack() as stack:
            self.fakes(stack);gate=stack.enter_context(patch.object(workloads,'require_workload'))
            stack.enter_context(patch('radeon_edit.uses_radeon',return_value=True))
            stack.enter_context(patch.object(ranges,'_extract_frame',side_effect=lambda src,dest,time:self.output(src,dest)))
            stack.enter_context(patch.object(ranges,'_extract_last_frame',side_effect=self.output))
            run=stack.enter_context(patch.object(ranges,'_child_ai_tools',return_value={'files':[str(raw)]}))
            result=ranges.video_range_edit(str(self.source),'new scene',start=1,end=3,mode='regenerate',drop_audio=True)
        gate.assert_called_once_with('video');self.assertEqual(result['mode'],'regenerate')
        self.assertEqual(result['resolution'],[1920,1080]);self.assertEqual(result['fps'],30)
        self.assertEqual(sum(stage['output_frames'] for stage in result['child_stages']),60)
        for call in run.call_args_list:
            args=call.args[0];self.assertEqual(args[0],'video')
            self.assertTrue(args[1].endswith('.png'));self.assertLessEqual(int(args[args.index('--length')+1]),17)
        self.assertTrue(all(stage['model_frames']<=17 for stage in result['child_stages']))

    def test_regeneration_chunks_round_once_not_once_per_chunk(self):
        for duration in (1.,3.07,20.13,120.):
            for generation_fps,output_fps in ((16,30),(8,24),(16,23.976),(16,16)):
                chunks=list(ranges._regeneration_chunks(duration,generation_fps,output_fps,17))
                total=sum(chunk['seconds'] for chunk in chunks)
                self.assertGreaterEqual(total+1e-8,duration);self.assertLess(total-duration,1/output_fps+1e-8)
                self.assertTrue(all(chunk['model_frames']<=17 for chunk in chunks))

    def test_uncensored_is_not_silently_ignored_by_vace_or_cut(self):
        for mode in ('vace', 'cut'):
            with patch.object(ranges,'_root_dir',return_value=self.root), \
                 patch.object(ranges,'_probe',return_value=self.info), \
                 patch('workload_compatibility.require_workload'), \
                 patch('radeon_edit.uses_radeon',return_value=False), \
                 patch.object(ranges,'_child_ai_tools') as child:
                with self.assertRaisesRegex(ValueError,'only to Wan regeneration'):
                    ranges.video_range_edit(str(self.source),'new scene',start=1,end=3,mode=mode,uncensored=True)
                child.assert_not_called()

    def test_scaled_uncensored_rejected_before_staging(self):
        with patch.object(ranges,'_root_dir',return_value=self.root),\
             patch.object(ranges,'_probe',return_value=self.info),\
             patch('workload_compatibility.require_workload'),patch('radeon_edit.uses_radeon',return_value=True),\
             patch.object(ranges,'_child_ai_tools') as child:
            with self.assertRaisesRegex(ValueError,'no separate uncensored'):
                ranges.video_range_edit(str(self.source),'new scene',start=1,end=3,mode='regenerate',uncensored=True)
        child.assert_not_called()


if __name__=='__main__':unittest.main()
