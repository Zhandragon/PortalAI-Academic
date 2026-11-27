"""Optional model admission, actual ordered conditioning and opt-in installation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Tools')]
import qwen_image_edit as qwen
from media_tool_api import edit_arguments,variant_catalog
from media_planning import MediaPlanning
import import_qwen_image_edit as installer
import choose_optional_models as choices
import import_foundation_assets as foundation
from comfy_bridge import ComfyBridge

G=1024**3
def hardware(vram=23,ram=20,commit=35,**kwargs):
    return dict(system='Windows',machine='AMD64',gpus=[{'index':0,'backend':'cuda','free_bytes':vram*G}],
        ram_available_bytes=ram*G,commit_available_bytes=commit*G,**kwargs)

class QwenEditing(unittest.TestCase):
    def plan(self,**kw):
        with patch.object(qwen,'missing_assets',return_value=[]):
            return qwen.plan(ROOT,policy={},hardware=kw.pop('hardware',hardware()),**kw)

    def test_fresh_memory_and_reference_count_admission(self):
        for refs in (1,2,3):
            self.assertTrue(self.plan(references=refs)['qwen'])
        for hw,refs in ((hardware(vram=11),1),(hardware(vram=15),2),(hardware(vram=17),3),
                        (hardware(ram=11),1),(hardware(commit=19),1)):
            self.assertFalse(self.plan(hardware=hw,references=refs)['qwen'])
            with self.assertRaises(RuntimeError):self.plan(hardware=hw,references=refs,profile='qwen-lightning')
        hw=hardware(vram=3);hw['gpus'].append({'index':1,'backend':'cuda','free_bytes':48*G})
        self.assertFalse(self.plan(hardware=hw)['qwen'])

    def test_platform_variant_missing_assets_never_start_a_download(self):
        for key,value in (('system','Linux'),('machine','ARM64')):
            hw=hardware();hw[key]=value
            self.assertFalse(self.plan(hardware=hw)['qwen'])
        self.assertFalse(self.plan(variant='uncensored')['qwen'])
        with patch.object(qwen,'missing_assets',return_value=['model']),patch.object(installer,'install') as download:
            self.assertFalse(qwen.plan(ROOT,hardware=hardware(),policy={})['qwen'])
            with self.assertRaises(RuntimeError):qwen.plan(ROOT,profile='qwen-lightning',hardware=hardware(),policy={})
            download.assert_not_called()

    def test_saved_and_explicit_selection_and_quality_do_not_stack_lora(self):
        self.assertEqual(qwen.preference(ROOT,'auto',{'media':{'edit_profile':'legacy'}}),'legacy')
        self.assertEqual(qwen.preference(ROOT,'qwen-quality',{'media':{'edit_profile':'legacy'}}),'qwen-quality')
        self.assertFalse(self.plan(profile='legacy')['qwen'])
        for profile,steps,cfg in (('qwen-lightning',4,1.0),('qwen-quality',40,4.0)):
            graph=qwen.workflow(['first.png','second.png','third.png'],'Place object 2 on object 1; keep the texture of image 3.',37,self.plan(profile=profile,references=3))
            self.assertEqual(graph['sample']['inputs']['seed'],37)
            self.assertEqual(graph['sample']['inputs']['steps'],steps)
            self.assertEqual(graph['sample']['inputs']['cfg'],cfg)
            self.assertEqual('lightning' in graph,steps==4)
            for i,name in enumerate(('first.png','second.png','third.png'),1):
                self.assertEqual(graph['image'+str(i)]['inputs']['image'],name)
                self.assertEqual(graph['positive']['inputs']['image'+str(i)],['scale'+str(i),0])
            qwen.validate_nodes(graph,{row['class_type']:{} for row in graph.values()})
            with self.assertRaises(RuntimeError):qwen.validate_nodes(graph,{})

    def test_explicit_native_engine_wins_over_automatic_backend(self):
        self.assertFalse(self.plan(engine='sdcpp-cpu')['qwen'])
        with self.assertRaises(ValueError):self.plan(engine='sdcpp-cpu',profile='qwen-lightning')

    def test_literal_argv_and_input_limits(self):
        argv=edit_arguments({'images':['one.png','--two & three.png','four.png'],'instruction':'hold "x" & y',
                             'profile':'qwen-lightning','variant':'standard','seed':9})
        self.assertEqual(argv[-3:],['--','one.png','hold "x" & y'])
        self.assertIn('--reference=--two & three.png',argv)
        for images in ([],['a']*2,['a','b','c','d'],[None]):
            with self.assertRaises(ValueError):edit_arguments({'images':images,'instruction':'edit'})

    def test_flux_receives_all_actual_references(self):
        wf=json.loads((ROOT/'Workflows/API/Flux2_Klein_9B_Image_Edit_Official_FP8.json').read_text())
        bridge=ComfyBridge.__new__(ComfyBridge)
        before=sum(n['class_type']=='ReferenceLatent' for n in wf.values())
        bridge.configure_reference_edit(wf,['one.png','two.png','three.png'],'Arrange them together',42)
        self.assertEqual(sum(n['class_type']=='ReferenceLatent' for n in wf.values()),before+4)
        names={n['inputs'].get('image') for n in wf.values() if n['class_type']=='LoadImage'}
        self.assertTrue({'one.png','two.png','three.png'}<=names)

    def test_direct_planning_keeps_explicit_plan_guards(self):
        args={'images':['one.png','two.png'],'instruction':'combine them'}
        self.assertIsNone(MediaPlanning(mode='direct').before('edit_images',args))
        self.assertIsNotNone(MediaPlanning(mode='guided').before('edit_images',args))
        planner=MediaPlanning(mode='direct');planner.plan={'stages':[{'instruction':'step one'}]}
        # Explicit plans still need the actual staged command and review lifecycle.
        self.assertIsNotNone(planner.before('generate_image',{'prompt':'unrelated'}))

    def test_harness_only_and_unaccepted_selection_never_download(self):
        with patch.object(foundation,'install') as download,patch.object(installer,'install') as qdownload:
            self.assertEqual(choices.install_choices({'selected':[],'accepted':False},ROOT),{'suggested':[],'custom':False})
            with self.assertRaises(ValueError):choices.install_choices({'selected':[installer.ID],'accepted':False},ROOT)
            download.assert_not_called();qdownload.assert_not_called()
            choices.install_choices({'selected':[installer.ID],'accepted':True},ROOT)
            qdownload.assert_called_once_with(ROOT,accepted=True);download.assert_not_called()
        with patch.object(foundation,'install') as download:
            with self.assertRaises(ValueError):installer.install(ROOT)
            download.assert_not_called()

    def test_default_catalog_excludes_new_weights_and_pins_optional_component(self):
        manifest=installer.catalog(ROOT)
        self.assertFalse(manifest['included_by_default'])
        self.assertTrue(manifest['optional'])
        ids={a['id'] for a in manifest['assets']}
        self.assertFalse(ids & {a['id'] for a in foundation.ASSETS})
        component=json.loads((ROOT.parents[2]/'InstallerSources/Windows/qwen_image_edit_component.json').read_text())
        self.assertFalse(component['required'])
        self.assertEqual(ids,{a['id'] for a in component['artifacts']})
        from model_choices import apply_policy,validate_consent
        release=apply_policy({'components':[component]});chosen=release['components']
        with self.assertRaises(ValueError):validate_consent(release,chosen,[],{})
        with self.assertRaises(ValueError):validate_consent(release,chosen,[installer.ID],{})
        validate_consent(release,chosen,[installer.ID],{installer.ID:chosen[0]['model_choice']['review_digest']})

if __name__=='__main__':unittest.main()
