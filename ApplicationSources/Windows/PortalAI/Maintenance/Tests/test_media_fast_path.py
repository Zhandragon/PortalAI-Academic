"""Image orchestration shortcuts preserve evidence and execution preconditions."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from media_planning import MediaPlanning, context, result_json
from native_chat import ToolRuntime
from media_tool_api import image_arguments, TOOLS


def assessment(**changes):
    result=dict(understanding='sufficient',reference_scope='appearance',
                fidelity='Recognizable objects in the requested arrangement',
                components=['teapot','table'],relationships=['teapot rests on table'],
                uncertainties=[],rationale='The inspected reference establishes the requested appearance.',
                staged=False,staging_reason='A single scene has no dependent construction stages.')
    return {**result,**changes}


def runtime(planner, result=None):
    return SimpleNamespace(_account_role=Mock(),_media_planning=planner,
                           _execute=Mock(return_value=result or '{"success":true,"files":["Outputs/result.png"]}'))


class FastPathTests(unittest.TestCase):
    def test_simple_request_can_assess_and_generate_in_one_dispatch(self):
        planner=MediaPlanning('A teapot on a table')
        rt=runtime(planner)
        with patch.object(planner,'attach_generated_output',return_value={'images_attached_next_request':True}):
            result=ToolRuntime.execute(rt,'generate_image',{'prompt':'teapot on table','assessment':assessment()})
        rt._execute.assert_called_once()
        self.assertEqual(planner.assessment,assessment())
        self.assertEqual(planner.outputs,['Outputs/result.png'])
        self.assertTrue(result_json(result)['success'])

    def test_unknown_assessment_or_unresolved_references_never_dispatch(self):
        for decision in (None,{},dict(assessment(),understanding='uncertain',uncertainties=['joint geometry']),
                         dict(assessment(),staged=True)):
            with self.subTest(decision=decision):
                planner=MediaPlanning();rt=runtime(planner)
                try:
                    response=ToolRuntime.execute(rt,'generate_image',{'prompt':'object','assessment':decision})
                except ValueError:
                    pass
                else:
                    self.assertFalse(json.loads(response)['generation_started'])
                rt._execute.assert_not_called()
                self.assertIsNone(planner.assessment)

    def test_combined_judgment_is_not_forwarded_as_a_cli_flag(self):
        self.assertEqual(image_arguments({'prompt':'cube','assessment':assessment(),'steps':20}),
                         ['--steps=20','--','cube'])
        with self.assertRaises(ValueError):image_arguments({'prompt':'cube','assessment':None})
        for tool in TOOLS[:2]:
            schema=tool['function']['parameters']['properties']['assessment']
            self.assertIn('reference_scope',schema['properties'])
            self.assertIn('staged',schema['required'])

    def test_combined_plan_is_atomic_and_still_requires_real_evidence(self):
        planner=MediaPlanning();decision=dict(assessment(),understanding='needs_references')
        args=dict(action='plan',assessment=decision,constraints=['Teapot likeness'],stages=['Edit reference'],
                  sources=[],reference_comparison='The inspected reference establishes the handle and lid geometry.')
        with self.assertRaisesRegex(ValueError,'one suitable'):planner.call(None,args)
        self.assertIsNone(planner.assessment);self.assertIsNone(planner.plan)
        planner.references=['actual.png'];planner.inspected.add('actual.png')
        planner.visual={'role':'user','content':[{'type':'image_url'}]}
        result=planner.call(None,args)
        self.assertEqual(result['plan']['assessment'],decision)
        self.assertEqual(result['plan']['references'],['actual.png'])
        self.assertIsNone(planner.visual)
        self.assertEqual(planner.inspected,{'actual.png'})

    def test_failed_plan_keeps_pixels_and_prior_assessment(self):
        planner=MediaPlanning();planner.assessment=assessment();planner.references=['actual.png']
        planner.visual={'role':'user','content':[{'type':'image_url'}]}
        with self.assertRaisesRegex(ValueError,'Read each source'):
            planner.call(None,dict(action='plan',assessment=dict(assessment(),understanding='needs_references'),
                constraints=['Likeness'],stages=['Edit'],sources=['https://not-read.example'],
                reference_comparison='An inspected photograph establishes the requested physical appearance.'))
        self.assertEqual(planner.assessment,assessment());self.assertIsNotNone(planner.visual)

    def test_output_attachment_is_not_an_automatic_review(self):
        planner=MediaPlanning();planner.outputs=['output.png'];planner.inspected.add('output.png')
        planner.visual={'role':'user','content':[{'type':'image_url'}]}
        with patch.object(planner,'call',return_value={'images_attached_next_request':True}):
            planner.attach_generated_output(SimpleNamespace())
        self.assertTrue(planner.output_attachment_pending)
        with self.assertRaisesRegex(ValueError,'next model response'):
            planner.call(None,dict(action='review',passed=['Teapot on table']))
        rt=SimpleNamespace(_media_planning=planner,profile=SimpleNamespace(check=Mock()))
        with patch('native_chat.model_props',return_value={'modalities':{'vision':True}}):
            self.assertIs(context(SimpleNamespace(tool_runtime=rt)),planner.visual)
        checked=planner.call(None,dict(action='review',passed=['Teapot on table']))
        self.assertTrue(checked['complete']);self.assertIsNone(planner.visual)
        self.assertEqual(planner.reviews['output.png']['passed'],['Teapot on table'])

    def test_actual_execution_prepares_bounded_pixels_for_next_response(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'output.png';output.write_bytes(b'fixture')
            planner=MediaPlanning();rt=runtime(planner,json.dumps({'success':True,'files':[str(output)]}))
            rt.root=Path(directory);rt.profile=SimpleNamespace(check=Mock(),resolve=Mock(return_value=output))
            pixels=Mock(width=1024,height=1024)
            pixels.convert.return_value.save.side_effect=lambda target,**kw:target.write(b'jpeg-preview')
            library=Mock();library.open.return_value.__enter__=Mock(return_value=pixels)
            library.open.return_value.__exit__=Mock(return_value=False)
            with patch('native_chat.model_props',return_value={'modalities':{'vision':True}}),patch('media_planning._image_library',return_value=library):
                result=ToolRuntime.execute(rt,'generate_image',dict(prompt='teapot',assessment=assessment()))
                self.assertTrue(planner.output_attachment_pending)
                with self.assertRaisesRegex(ValueError,'next model response'):
                    ToolRuntime.execute(rt,'media_plan',dict(action='review',passed=['Teapot on table']))
                attachment=context(SimpleNamespace(tool_runtime=rt))
                self.assertTrue(attachment['content'][-1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
                ToolRuntime.execute(rt,'media_plan',dict(action='review',passed=['Teapot on table']))
            pixels.thumbnail.assert_called_once_with((768,768));library.open.assert_called_once_with(output)
            self.assertTrue(result_json(result)['success']);self.assertIsNone(planner.visual)

    def test_preview_failure_retains_success_and_requires_manual_inspection(self):
        planner=MediaPlanning();planner.assessment=assessment();rt=runtime(planner)
        with patch.object(planner,'attach_generated_output',side_effect=RuntimeError('vision unavailable')):
            result=ToolRuntime.execute(rt,'generate_image',{'prompt':'teapot'})
        self.assertTrue(result_json(result)['success']);self.assertIn('vision unavailable',result)
        self.assertEqual(planner.outputs,['Outputs/result.png'])
        with self.assertRaisesRegex(ValueError,'Inspect'):
            planner.call(None,dict(action='review',passed=['Looks right']))

    def test_revoked_account_does_not_prepare_or_dispatch(self):
        planner=MediaPlanning();rt=runtime(planner);rt._account_role.side_effect=PermissionError('revoked')
        with self.assertRaises(PermissionError):
            ToolRuntime.execute(rt,'generate_image',{'prompt':'cube','assessment':assessment()})
        rt._execute.assert_not_called();self.assertFalse(planner.outputs)

    def test_no_repeat_attachment_for_metadata_or_replayed_paths(self):
        planner=MediaPlanning();planner.assessment=assessment();planner.outputs=['Outputs/result.png']
        rt=runtime(planner)
        with patch.object(planner,'attach_generated_output') as attach:
            ToolRuntime.execute(rt,'generate_image',{'prompt':'teapot'})
            attach.assert_not_called()

    def test_failed_or_incomplete_final_review_keeps_pixels(self):
        planner=MediaPlanning();planner.assessment=assessment()
        planner.call(None,dict(action='plan',constraints=['Likeness','Pose'],stages=['Edit']))
        planner.observe('generate_image',{},dict(success=True,files=['output.png']))
        planner.inspected.add('output.png');planner.visual={'content':[{'type':'image_url'}]}
        result=planner.call(None,dict(action='review',passed=['Likeness']))
        self.assertEqual(result['unchecked_constraints'],['Pose']);self.assertIsNotNone(planner.visual)
        planner.call(None,dict(action='review',passed=['Likeness'],failed=['Pose']))
        self.assertIsNotNone(planner.visual)
        planner.call(None,dict(action='review',passed=['Likeness','Pose']))
        self.assertIsNone(planner.visual)
        self.assertTrue(planner.call(None,{'action':'status'})['complete'])


if __name__=='__main__':unittest.main()
