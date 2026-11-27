import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from media_planning import MediaPlanning, assess


def judgment(planner, understanding='sufficient', staged=False, **changes):
    value=dict(understanding=understanding, reference_scope='structure', fidelity='Recognizable illustrative shapes',
               components=['Main subject'],relationships=[],uncertainties=[],
               rationale='The requested visible form is understood at this fidelity.',
               staged=staged,staging_reason='Separate dependent actions.' if staged else 'One isolated subject.')
    value.update(changes)
    return planner.call(None,{'action':'assess','assessment':value})


class MediaPlanningTests(unittest.TestCase):
    def test_inspected_appearance_references_get_the_exact_missing_plan_fields(self):
        planner=MediaPlanning();planner.references=['subject.jpg','object.jpg']
        result=judgment(planner,'needs_references',reference_scope='appearance')
        self.assertEqual(result['inspected_reference_count'],2)
        self.assertIn('already inspected',result['next_step'])
        self.assertIn('reference_comparison',result['next_step'])
        self.assertIn('sources may be []',result['next_step'])
        self.assertIn('One stage',result['next_step'])
        self.assertNotIn('guidance',result)
        self.assertEqual(planner.before('media_tool',{'command':'edit','arguments':[]})['next_step'],result['next_step'])

    def test_structure_guidance_preserves_missing_image_and_source_requirements(self):
        planner=MediaPlanning();planner.references=['one.jpg']
        result=judgment(planner,'needs_references',reference_scope='structure',staged=True)
        self.assertIn('2 more',result['next_step'])
        self.assertIn('two independent hosts',result['next_step'])
        self.assertIn('2-6 stages',result['next_step'])
        self.assertTrue(planner.before('generate_image',{})['planning_required'])

    def test_sufficient_assessment_explicitly_continues_to_generation(self):
        result=judgment(MediaPlanning())
        self.assertIn('Generate the requested image or edit now',result['next_step'])
        self.assertNotIn('guidance',result)

    def test_inspection_uses_shipped_browser_pillow_without_science_or_browser_start(self):
        import importlib
        from media_planning import _image_library
        expected=object();directory=Path('fixture-browser-packages').resolve()
        before=list(sys.path)
        def load(name):
            self.assertEqual(name,'PIL.Image')
            if str(directory) not in sys.path:raise ModuleNotFoundError("No module named PIL",name='PIL')
            return expected
        with patch('knowledge_embeddings.packages'),patch('browser_use_runtime.layer',return_value=directory) as layer,patch.object(importlib,'import_module',side_effect=load):
            self.assertIs(_image_library(ROOT),expected)
            layer.assert_called_once_with(ROOT)
        self.assertEqual(sys.path,before)

    def test_inspection_does_not_hide_a_broken_native_library(self):
        import importlib
        from media_planning import _image_library
        with patch('knowledge_embeddings.packages'),patch('browser_use_runtime.layer') as layer,patch.object(importlib,'import_module',side_effect=ModuleNotFoundError('native dependency',name='native_dependency')):
            with self.assertRaises(ModuleNotFoundError):_image_library(ROOT)
            layer.assert_not_called()

    def test_appearance_gap_accepts_one_inspected_reference_without_extra_pages(self):
        planner=MediaPlanning('Create a recognizable portrait')
        result=judgment(planner,'needs_references',reference_scope='appearance',
                        uncertainties=['Facial proportions needed for likeness'])
        self.assertEqual(result['minimum_reference_images'],1)
        args={'action':'plan','constraints':['Recognizable likeness'],
              'stages':['Create the requested portrait'],
              'reference_comparison':'The inspected portrait establishes the face shape, hairline and eye spacing.'}
        with self.assertRaisesRegex(ValueError,'one suitable'):planner.call(None,args)
        planner.references=['portrait.jpg']
        planner.call(None,args)
        self.assertIsNone(planner.before('generate_image',{'prompt':'A portrait'}))

    def test_appearance_scope_still_rejects_fabricated_source_citations(self):
        planner=MediaPlanning();judgment(planner,'needs_references',reference_scope='appearance')
        planner.references=['portrait.jpg']
        with self.assertRaisesRegex(ValueError,'Read each source'):
            planner.call(None,{'action':'plan','constraints':['Likeness'],'stages':['Portrait'],
                              'sources':['https://invented.example'],
                              'reference_comparison':'The inspected portrait establishes the requested visible appearance.'})

    def test_everyday_scene_remains_direct(self):
        planner=MediaPlanning('Create a watercolor of a blue teapot on a table')
        result=judgment(planner,components=['teapot','table'],relationships=['teapot rests on table'])
        self.assertFalse(result['reference_required']);self.assertFalse(result['staged'])
        self.assertEqual(result['minimum_reference_images'],0)
        self.assertEqual(result['minimum_source_hosts'],0)
        self.assertIsNone(planner.before('generate_image',{'prompt':'blue teapot'}))

    def test_unassessed_request_does_not_launch_or_claim_no_references(self):
        planner=MediaPlanning('Show a jacquard loom')
        state=planner.call(None,{'action':'assess'})
        self.assertTrue(state['assessment_required'])
        self.assertIsNone(state['reference_required']);self.assertIsNone(state['staged'])
        runtime=SimpleNamespace(_account_role=Mock(),_media_planning=planner,_execute=Mock())
        from native_chat import ToolRuntime
        result=json.loads(ToolRuntime.execute(runtime,'generate_image',{'prompt':'watercolor blobs'}))
        self.assertTrue(result['planning_required']);self.assertFalse(result['generation_started'])
        runtime._execute.assert_not_called()

    def test_relationships_survive_a_simplified_subprompt(self):
        planner=MediaPlanning('Two jugglers exchange clubs across a seesaw')
        judgment(planner,staged=True,components=['two jugglers','clubs','seesaw'],
                 relationships=['clubs travel between hands','feet balance on opposite ends'])
        self.assertTrue(planner.before('generate_image',{'prompt':'woman and waiter'})['staged'])

    def test_semantic_uncertainty_requires_references_without_a_keyword(self):
        planner=MediaPlanning('Draw the workings of a bandoneon')
        result=judgment(planner,'uncertain',components=['bellows','reed blocks','valves'],
                        uncertainties=['How the valves connect to the reed blocks'],
                        rationale='The internal arrangement is not understood well enough to depict.')
        self.assertTrue(result['reference_required']);self.assertFalse(result['staged'])
        with self.assertRaisesRegex(ValueError,'three'):
            planner.call(None,{'action':'plan','constraints':['Correct geometry'],'stages':['Layout']})

    def test_search_results_and_fabricated_citations_do_not_count_as_read_pages(self):
        planner=MediaPlanning('CRISPR');planner.references=['a.png','b.png','c.png']
        judgment(planner,'needs_references')
        planner.observe('web',{'action':'search','arguments':{'query':'CRISPR'}},json.dumps({'ok':True,'result':{'url':'https://a.example'}}))
        with self.assertRaisesRegex(ValueError,'Read each source'):
            planner.call(None,{'action':'plan','subject_risk':'specialized','constraints':['Correct structure'],'stages':['Layout'],
                               'sources':['https://a.example','https://b.example'],'reference_comparison':'A detailed comparison of shared geometry and the relevant disagreements.'})

    def test_failed_reads_cannot_supply_reference_evidence(self):
        planner=MediaPlanning()
        planner.observe('web',{'action':'read','arguments':{'url':'https://a.example'}},json.dumps({'ok':False}))
        self.assertFalse(planner.fetched)

    def test_independent_sources_and_inspection_are_required(self):
        planner=MediaPlanning('DNA');planner.references=['a.png','b.png','c.png']
        judgment(planner,'needs_references')
        for url in ('https://a.example/1','https://a.example/2'):
            planner.observe('web',{'action':'read','arguments':{'url':url}},json.dumps({'ok':True,'result':{'text':'real page'}}))
        with self.assertRaisesRegex(ValueError,'independently'):
            planner.call(None,{'action':'plan','subject_risk':'specialized','constraints':['Correct structure'],'stages':['Layout'],
                               'sources':list(planner.fetched),'reference_comparison':'Detailed shared-structure comparison and relevant disagreements.'})

    def test_staged_work_must_continue_from_actual_previous_output(self):
        planner=MediaPlanning('dancing waiter dropping bottle because distracted')
        judgment(planner,staged=True)
        planner.call(None,{'action':'plan','subject_risk':'familiar','constraints':['Bottle visibly falling'],
                           'stages':['Establish poses','Edit gaze and bottle']})
        planner.observe('generate_image',{},json.dumps({'success':True,'files':['Outputs/stage1.png']}))
        self.assertIsNotNone(planner.before('generate_image',{'prompt':'start over'}))
        self.assertIsNotNone(planner.before('media_tool',{'command':'edit','arguments':['invented.png','fix bottle']}))
        planner.inspected.add('Outputs/stage1.png')
        planner.call(None,{'action':'review','passed':['Poses established'],'failed':[]})
        self.assertIsNone(planner.before('media_tool',{'command':'edit','arguments':['Outputs/stage1.png','fix bottle']}))

    def test_shell_generation_uses_same_planning_guard(self):
        planner=MediaPlanning('CRISPR')
        self.assertTrue(planner.before('shell',{'command':'python Agent/ai_tools.py image --prompt DNA'})['planning_required'])

    def test_logged_media_output_is_preserved_for_staging(self):
        planner=MediaPlanning()
        planner.observe('media_tool',{'command':'image','arguments':[]},'Progress 100%\n{\n"success":true,"files":["Outputs/a.png"]\n}\nwarning: preview unavailable')
        self.assertEqual(planner.outputs,['Outputs/a.png'])

    def test_review_requires_actual_output_inspection(self):
        planner=MediaPlanning();planner.plan={'stages':['layout','details']};planner.outputs=['a.png']
        with self.assertRaisesRegex(ValueError,'Inspect'):
            planner.call(None,{'action':'review','passed':['all']})

    def test_multiple_images_are_not_mistaken_for_completed_stages(self):
        planner=MediaPlanning('dancing distracted dropping bottle')
        judgment(planner,staged=True)
        planner.call(None,{'action':'plan','subject_risk':'familiar','constraints':['Bottle visibly falling'],
                           'stages':['Layout','Bottle action']})
        planner.observe('generate_image',{},json.dumps({'success':True,'files':['a.png','b.png']}))
        planner.inspected.update(['a.png','b.png'])
        planner.call(None,{'action':'review','passed':['Layout correct']})
        self.assertFalse(planner.call(None,{'action':'status'})['complete'])
        planner.call(None,{'action':'review','passed':['Layout correct']})
        self.assertEqual(planner.completed_stages,1)
        planner.observe('media_tool',{'command':'edit'},json.dumps({'success':True,'files':['c.png']}))
        planner.inspected.add('c.png');planner.call(None,{'action':'review','passed':['Bottle visibly falling']})
        self.assertTrue(planner.call(None,{'action':'status'})['complete'])

    def test_text_only_model_cannot_claim_visual_inspection(self):
        with patch('native_chat.model_props',return_value={'modalities':{}}):
            with self.assertRaisesRegex(RuntimeError,'cannot inspect'):
                MediaPlanning().call(None,{'action':'inspect','paths':['a.png']})

    def test_final_review_paraphrases_return_exact_missing_labels_without_regeneration(self):
        planner=MediaPlanning();judgment(planner)
        planner.call(None,{'action':'plan','constraints':['Blue cup on a table','Handle visible'],'stages':['Compose']})
        planner.observe('generate_image',{},json.dumps({'success':True,'files':['a.png']}))
        planner.inspected.add('a.png')
        result=planner.call(None,{'action':'review','passed':['Cup looks blue','Handle visible']})
        self.assertEqual(result['unchecked_constraints'],['Blue cup on a table'])
        self.assertIn('same inspected output',result['next_step'])
        self.assertEqual(planner.completed_stages,0)
        self.assertFalse(planner.call(None,{'action':'status'})['complete'])
        planner.call(None,{'action':'review','passed':['Blue cup on a table','Handle visible']})
        self.assertEqual(planner.outputs,['a.png'])
        self.assertTrue(planner.call(None,{'action':'status'})['complete'])

    def test_final_review_failure_requires_edit_even_when_all_labels_accounted_for(self):
        planner=MediaPlanning();judgment(planner)
        planner.call(None,{'action':'plan','constraints':['Blue cup','Handle visible'],'stages':['Compose']})
        planner.observe('generate_image',{},json.dumps({'success':True,'files':['a.png']}))
        planner.inspected.add('a.png')
        result=planner.call(None,{'action':'review','passed':['Blue cup'],'failed':['Handle visible']})
        self.assertEqual(result['unchecked_constraints'],[])
        self.assertIn('Edit failed constraints',result['next_step'])
        self.assertEqual(planner.completed_stages,0)
        self.assertFalse(planner.call(None,{'action':'status'})['complete'])

    def test_simple_generated_image_can_be_reviewed_without_creating_a_plan(self):
        planner=MediaPlanning();judgment(planner)
        planner.observe('generate_image',{},json.dumps({'success':True,'files':['a.png']}))
        with self.assertRaisesRegex(ValueError,'Inspect'):
            planner.call(None,{'action':'review','passed':['Requested composition visible']})
        planner.inspected.add('a.png')
        result=planner.call(None,{'action':'review','passed':['Requested composition visible']})
        self.assertTrue(result['complete']);self.assertFalse(result['plan_required'])
        self.assertIsNone(planner.plan)
        self.assertTrue(planner.call(None,{'action':'status'})['complete'])
        with self.assertRaisesRegex(ValueError,'do not create a plan after generation'):
            planner.call(None,{'action':'plan','constraints':['New plan'],'stages':['Repeat']})

    def test_simple_failed_review_stays_incomplete_until_edited_and_inspected(self):
        planner=MediaPlanning();judgment(planner)
        planner.observe('generate_image',{},json.dumps({'success':True,'files':['a.png']}))
        planner.inspected.add('a.png')
        result=planner.call(None,{'action':'review','failed':['Object missing']})
        self.assertFalse(result['complete']);self.assertFalse(planner.call(None,{'action':'status'})['complete'])
        planner.observe('media_tool',{'command':'edit'},json.dumps({'success':True,'files':['b.png']}))
        with self.assertRaisesRegex(ValueError,'Inspect'):
            planner.call(None,{'action':'review','passed':['Object added']})
        planner.inspected.add('b.png');planner.call(None,{'action':'review','passed':['Object added']})
        self.assertTrue(planner.call(None,{'action':'status'})['complete'])

    def test_unrelated_tools_and_help_are_not_blocked(self):
        planner=MediaPlanning('CRISPR')
        self.assertIsNone(planner.before('science',{'operation':'help'}))
        self.assertIsNone(planner.before('media_tool',{'command':'image','arguments':['--help']}))

    def test_same_topic_can_have_different_fidelity_needs(self):
        decorative=MediaPlanning('Abstract DNA-themed wallpaper')
        judgment(decorative,fidelity='Decorative curves, no anatomical claim',components=['curved ribbons'])
        self.assertIsNone(decorative.before('generate_image',{'prompt':decorative.request}))
        precise=MediaPlanning('Explain the precise attachment of this assembly')
        judgment(precise,'needs_references',fidelity='Accurate attachment geometry',
                 uncertainties=['Orientation of the attaching parts'])
        self.assertTrue(precise.before('generate_image',{'prompt':'ribbons'})['reference_required'])

    def test_critical_uncertainty_requires_references_even_if_marked_sufficient(self):
        result=judgment(MediaPlanning(),'sufficient',uncertainties=['Unknown joint orientation'])
        self.assertTrue(result['reference_required'])

    def test_missing_or_malformed_fields_never_grant_generation(self):
        valid=judgment(MediaPlanning())['assessment']
        variants=[{},None,'familiar',dict(valid,staged='false'),dict(valid,components=[]),
                  dict(valid,uncertainties=None),dict(valid,rationale='')]
        variants += [{k:v for k,v in valid.items() if k!=field} for field in valid]
        for value in variants:
            with self.subTest(value=value):
                planner=MediaPlanning()
                with self.assertRaises(ValueError):planner.call(None,{'action':'assess','assessment':value})
                self.assertTrue(planner.before('generate_image',{})['assessment_required'])

    def test_query_does_not_replace_recorded_judgment(self):
        planner=MediaPlanning('An unfamiliar artifact')
        expected=judgment(planner,'uncertain')
        self.assertEqual(planner.call(None,{'action':'assess','brief':'a simple dot'}),expected)

    def test_all_registered_visual_routes_require_assessment(self):
        planner=MediaPlanning('ordinary scene')
        for command in ('image','edit','inpaint','autoedit','video','video-small','dialogue-video'):
            with self.subTest(command=command):
                self.assertTrue(planner.before('media_tool',{'command':command,'arguments':[]})['assessment_required'])
                self.assertTrue(planner.before('shell',{'command':'python Agent/ai_tools.py '+command})['assessment_required'])
        self.assertIsNone(planner.before('media_tool',{'command':'music','arguments':[]}))

    def test_plan_cannot_bypass_assessment_or_shorten_required_stages(self):
        planner=MediaPlanning()
        args={'action':'plan','subject_risk':'familiar','constraints':['Correct poses'],'stages':['Layout']}
        with self.assertRaisesRegex(ValueError,'semantic assessment'):planner.call(None,args)
        judgment(planner,staged=True)
        with self.assertRaisesRegex(ValueError,'2-6'):planner.call(None,args)
        self.assertIsNone(planner.plan)

    def test_familiar_complex_scene_needs_stages_without_research(self):
        planner=MediaPlanning('Two jugglers exchange clubs across a seesaw')
        assessment=judgment(planner,staged=True)['assessment']
        result=planner.call(None,{'action':'plan','constraints':['Clubs between hands'],
                                 'stages':['Layout people and seesaw','Edit throws and catches']})
        self.assertFalse(result['plan']['reference_required']);self.assertEqual(result['plan']['references'],[])
        with self.assertRaisesRegex(ValueError,'fixed'):judgment(planner,staged=False)
        self.assertEqual(planner.call(None,{'action':'assess','assessment':assessment})['assessment'],assessment)

    def test_reference_plan_accepts_inspection_and_two_read_sources(self):
        planner=MediaPlanning('A bandoneon interior')
        judgment(planner,'uncertain')
        planner.references=['a.png','b.png','c.png']  # inspection state; vision capability tested separately
        for url in ('https://a.example/1','https://b.example/2'):
            planner.observe('web',{'action':'read','arguments':{'url':url}},{'ok':True,'result':{}})
        result=planner.call(None,{'action':'plan','constraints':['Valve attachment'],
            'stages':['Construct verified arrangement'],'sources':list(planner.fetched),
            'reference_comparison':'Shared valve attachments agree; view orientation differs between the sources.'})
        self.assertTrue(result['plan']['reference_required'])
        self.assertIsNone(planner.before('generate_image',{'prompt':'Construct verified arrangement'}))

    def test_guidance_has_no_case_specific_prescriptions(self):
        from media_planning import GUIDANCE, TOOL
        text=GUIDANCE+' '+json.dumps(TOOL)
        self.assertNotIn('CRISPR',text);self.assertNotIn('waiter',text)
        self.assertIn('uncertainties',text);self.assertIn('whole user request',text)


if __name__=='__main__':unittest.main()
