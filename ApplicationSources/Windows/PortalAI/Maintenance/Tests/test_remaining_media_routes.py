"""CLI integration, compute admission and delayed-Stop regression; no live models."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
import ai_tools as cli
import audio_inpaint_amd_bridge as audio
import dialogue_portable as dialogue
import workload_compatibility as compatibility


class RoutingTests(unittest.TestCase):
    def test_audio_selects_scaled_only_for_radeon_linux(self):
        for scaled in (False, True):
            with self.subTest(scaled=scaled), patch('radeon_edit.uses_radeon', return_value=scaled), \
                    patch.object(audio, 'audio_inpaint', return_value={'scaled':True}) as portable, \
                    patch.object(cli, 'deterministic_audio_inpaint', return_value={'scaled':False}) as existing, \
                    patch.object(cli, 'root_dir', return_value=ROOT):
                result = cli._hardware_audio_inpaint('clip.wav','rain',start=1,end=2,mode='music')
                self.assertEqual(result['scaled'], scaled)
                selected, unused = (portable,existing) if scaled else (existing,portable)
                unused.assert_not_called()
                self.assertEqual(selected.call_args.kwargs['mode'],'music')
                self.assertEqual(selected.call_args.kwargs['end'],2)
                self.assertEqual('root' in selected.call_args.kwargs,scaled)

    def test_dialogue_cli_prepares_before_one_guarded_handoff(self):
        events = []
        request = {'synthetic':True}
        @contextmanager
        def pipeline(reason, *, start_guard):
            events.append('lease'); start_guard()
            yield
            events.append('restore')
        def finish(payload, *unused):
            self.assertTrue(payload['success']); events.append('emit'); raise SystemExit(0)
        with ExitStack() as stack:
            for target, replacement in (
                ('sys.argv',['ai_tools.py','dialogue-video','image.png','hello','--duration','20','--dialogue-start','5']),
                ('effort_policy.apply_tool_environment',lambda args,*a,**k:args),
                ('workload_compatibility.require_workload',Mock()),
                ('profile_tool_hydration.prepare_tool_files',Mock()),
                ('media_paths.image_source',lambda root,path:root/path),
                ('runtime_policy.require_space',Mock()),
                ('model_variants.first_pass',Mock(return_value=('official','fixture standard preference'))),
                ('radeon_edit.uses_radeon',Mock(return_value=True)),
            ): stack.enter_context(patch(target,replacement))
            stack.enter_context(patch.object(cli,'load_config',return_value={}))
            stack.enter_context(patch.object(cli,'root_dir',return_value=ROOT))
            stack.enter_context(patch.object(cli,'emit',side_effect=finish))
            stack.enter_context(patch.object(cli,'_exclusive_pipeline',side_effect=pipeline))
            prepare = stack.enter_context(patch.object(dialogue,'prepare',side_effect=lambda *a:events.append('prepare') or request))
            guard = stack.enter_context(patch.object(dialogue,'check_request',side_effect=lambda *a,**k:events.append('guard')))
            generate = stack.enter_context(patch.object(dialogue,'generate',side_effect=lambda *a,**k:events.append('generate') or {'files':[]}))
            with self.assertRaises(SystemExit) as stopped: cli.main()
            self.assertEqual(stopped.exception.code,0)
        self.assertEqual(events,['prepare','lease','guard','generate','restore','emit'])
        generate.assert_called_once_with(request,root=ROOT)
        self.assertEqual(prepare.call_args.args[1].duration,20.)
        self.assertEqual(prepare.call_args.args[1].dialogue_start,5.)

    def test_scaled_commands_require_real_compute_before_handoff(self):
        for command in ('audio-inpaint','sfx-inpaint','dialogue-video'):
            self.assertIn(command,compatibility.ROCM_MEDIA)
            for system in ('Windows','Linux'):
                with self.subTest(command=command,system=system):
                    hw={'system':system,'machine':'x86_64','gpus':[],
                        'amd_gpu':{'available':True,'compute_ok':False},
                        'media_gpu':{'available':True,'backend':'rocm','compute_ok':False}}
                    with self.assertRaises(RuntimeError): compatibility.require_workload(command,hw)
                    hw['amd_gpu']['compute_ok']=hw['media_gpu']['compute_ok']=True
                    compatibility.require_workload(command,hw)
            compatibility.require_workload(command,{'system':'Windows','machine':'AMD64','gpus':[{'backend':'cuda','index':0}]})

    def test_stop_while_waiting_for_lease_never_starts_handoff(self):
        guard=Mock(side_effect=[None,RuntimeError('Stop requested')])
        with patch('workload_request.request_guard',return_value=lambda:None), \
                patch.object(cli,'acquire_gpu_lease',return_value='owned') as acquire, \
                patch.object(cli,'release_gpu_lease') as release, \
                patch.object(cli,'quiesce_gpu_workers') as quiesce, \
                patch.object(cli,'qwen_gpu_handoff_begin') as begin, \
                patch.object(cli,'qwen_gpu_handoff_end') as end, \
                patch.object(cli,'service_stop') as stop:
            with self.assertRaisesRegex(RuntimeError,'Stop requested'):
                with cli._exclusive_pipeline('fixture',start_guard=guard): self.fail('Executed after Stop')
            acquire.assert_called_once(); release.assert_called_once_with('owned')
            quiesce.assert_not_called(); begin.assert_not_called(); stop.assert_not_called()

    def test_guard_is_forwarded_to_handoff_critical_section(self):
        guard=Mock()
        with patch('workload_request.request_guard',return_value=lambda:None), \
                patch.object(cli,'acquire_gpu_lease',return_value='owned'), \
                patch.object(cli,'release_gpu_lease'),patch.object(cli,'quiesce_gpu_workers'), \
                patch.object(cli,'qwen_gpu_handoff_begin') as begin,patch.object(cli,'qwen_gpu_handoff_end'), \
                patch.object(cli,'service_stop'),patch.object(cli,'_clear_gpu_state'):
            with cli._exclusive_pipeline('fixture',start_guard=guard): pass
            begin.assert_called_once()
            forwarded=begin.call_args.kwargs['start_guard']
            before=guard.call_count;forwarded();self.assertEqual(guard.call_count,before+1)


if __name__=='__main__':unittest.main()
