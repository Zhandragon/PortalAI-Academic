import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from media_planning import MediaPlanning, assess


class MediaPlanningTests(unittest.TestCase):
    def test_everyday_scene_remains_direct(self):
        planner=MediaPlanning('Create a watercolor of a blue teapot on a table')
        self.assertIsNone(planner.before('generate_image',{'prompt':'blue teapot'}))

    def test_crispr_requires_research_before_any_image_is_launched(self):
        planner=MediaPlanning('Create an image of CRISPR cutting DNA helices')
        runtime=SimpleNamespace(_account_role=Mock(),_media_planning=planner,_execute=Mock())
        from native_chat import ToolRuntime
        result=json.loads(ToolRuntime.execute(runtime,'generate_image',{'prompt':'watercolor blobs'}))
        self.assertTrue(result['planning_required']);self.assertFalse(result['generation_started'])
        runtime._execute.assert_not_called()

    def test_relationships_survive_a_simplified_subprompt(self):
        planner=MediaPlanning('A woman dancing with a man who is a waiter dropping a bottle because he is distracted by her')
        self.assertTrue(planner.before('generate_image',{'prompt':'woman and waiter'})['staged'])

    def test_semantic_uncertainty_requires_references_without_a_keyword(self):
        planner=MediaPlanning('Draw an unfamiliar device')
        with self.assertRaisesRegex(ValueError,'three'):
            planner.call(None,{'action':'plan','subject_risk':'uncertain','constraints':['Correct geometry'],'stages':['Layout']})

    def test_search_results_and_fabricated_citations_do_not_count_as_read_pages(self):
        planner=MediaPlanning('CRISPR');planner.references=['a.png','b.png','c.png']
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
        for url in ('https://a.example/1','https://a.example/2'):
            planner.observe('web',{'action':'read','arguments':{'url':url}},json.dumps({'ok':True,'result':{'text':'real page'}}))
        with self.assertRaisesRegex(ValueError,'independently'):
            planner.call(None,{'action':'plan','subject_risk':'specialized','constraints':['Correct structure'],'stages':['Layout'],
                               'sources':list(planner.fetched),'reference_comparison':'Detailed shared-structure comparison and relevant disagreements.'})

    def test_staged_work_must_continue_from_actual_previous_output(self):
        planner=MediaPlanning('dancing waiter dropping bottle because distracted')
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

    def test_unrelated_tools_and_help_are_not_blocked(self):
        planner=MediaPlanning('CRISPR')
        self.assertIsNone(planner.before('science',{'operation':'help'}))
        self.assertIsNone(planner.before('media_tool',{'command':'image','arguments':['--help']}))


if __name__=='__main__':unittest.main()
