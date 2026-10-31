import copy
from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,unittest,tkinter as tk
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
import voice_policy as vp
from voice_preferences import VoicePreferences
from tk_fixture_cleanup import finish_tk_fixture


class VoicePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        hw={'system':'Windows','ram_total_bytes':32*vp.GIB,'ram_available_bytes':vp.GIB,
            'gpus':[{'backend':'cuda','index':0,'total_bytes':24*vp.GIB,'free_bytes':0}]}
        self.hw=hw
        first=vp.capabilities(self.root,hw)
        for row in first['models'].values():
            for name in row['missing_assets']:
                path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        self.capacity=vp.capabilities(self.root,hw)

    def test_capacity_scan_does_not_confuse_resident_model_with_incapability(self):
        self.assertTrue(self.capacity['models']['qwen']['available'])
        self.assertTrue(self.capacity['models']['qwen']['requires_recheck'])
        self.assertEqual(self.capacity['stt']['ram_required_bytes'],3*vp.GIB)

    def test_automatic_links_effort_and_can_be_independent(self):
        self.assertEqual(vp.resolve({},'fast',self.capacity)['id'],'piper')
        self.assertEqual(vp.resolve({},'deep',self.capacity)['id'],'qwen')
        self.assertEqual(vp.resolve({'tts_link_effort':False},'fast',self.capacity)['id'],'qwen')

    def test_manual_selection_never_substitutes_unsupported_model(self):
        hw={**self.hw,'gpus':[]};caps=vp.capabilities(self.root,hw)
        self.assertEqual(vp.resolve({},'deep',caps)['id'],'piper')
        with self.assertRaisesRegex(RuntimeError,'supported'):vp.resolve({'tts_model':'qwen'},'deep',caps)
        self.assertEqual(vp.resolve({'tts_model':'piper','tts_link_effort':False},'deep',self.capacity)['id'],'piper')

    def test_linked_manual_choice_moves_both_directions_unlinked_stays_pinned(self):
        self.assertEqual(vp.effort_for_voice('piper','deep'),'fast')
        self.assertEqual(vp.effort_for_voice('qwen','fast'),'balanced')
        self.assertEqual(vp.effort_for_voice('qwen','deep'),'deep')
        self.assertEqual(vp.after_effort_change({'tts_model':'qwen'},'fast')['tts_model'],'piper')
        self.assertEqual(vp.after_effort_change({'tts_model':'qwen','tts_link_effort':False},'fast')['tts_model'],'qwen')
        self.assertEqual(vp.after_effort_change({},'fast')['tts_model'],'auto')

    def test_missing_assets_are_reported_without_download(self):
        (self.root/'Voice/Piper/models/en_US-joe-medium.onnx').unlink()
        caps=vp.capabilities(self.root,self.hw)
        with self.assertRaisesRegex(RuntimeError,'incomplete'):vp.resolve({'tts_model':'piper'},'fast',caps)
        for bad in ({'tts_model':'outside'},{'tts_link_effort':'false'}):
            with self.assertRaises(ValueError):vp.preferences(bad)

    def test_preferences_are_staged_and_unlink_prevents_mutual_changes(self):
        app=tk.Tk();app.withdraw();self.addCleanup(finish_tk_fixture,app)
        class Skin:
            def row(self,parent,title,build):row=tk.Frame(parent);row.pack();return build(row)
            def combo(self,parent,var,choices):return tk.Entry(parent,textvariable=var)
            def check(self,parent,title,var):return tk.Checkbutton(parent,text=title,variable=var)
            def label(self,parent,text,**kw):return tk.Label(parent,text=text)
        settings={'tts_model':'auto','tts_link_effort':True,'untouched':'yes'}
        panel=SimpleNamespace(settings=copy.deepcopy(settings),effort=SimpleNamespace(profile='balanced',capability_data={'voice':self.capacity}))
        effort={'chat':tk.StringVar(app,value='balanced')}
        controls=VoicePreferences(panel,Skin(),app,effort)
        controls.model.set(vp.LABELS['piper']);self.assertEqual(effort['chat'].get(),'fast')
        effort['chat'].set('deep');self.assertEqual(controls.values()['tts_model'],'qwen')
        controls.linked.set(False);controls.model.set(vp.LABELS['piper'])
        self.assertEqual(effort['chat'].get(),'deep')
        effort['chat'].set('balanced');self.assertEqual(controls.values()['tts_model'],'piper')
        self.assertEqual(panel.settings,settings) # Cancel/preview never writes live preferences.
        self.assertEqual(controls.validated_values(),{'tts_model':'piper','tts_link_effort':False})


if __name__=='__main__':unittest.main()
