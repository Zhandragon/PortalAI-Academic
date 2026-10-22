"""Independent saves and adaptive inventory/mission navigation on synthetic data."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from test_settings_surfaces_tk import LIGHT,DARK
from tk_fixture_cleanup import finish_tk_fixture
import settings_page


class SaveIsolation(unittest.TestCase):
    def test_each_save_preserves_other_sections_and_new_policy_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Agent').mkdir()
            path=root/'Agent/hardware_profiles.json'
            policy={'selection':'auto','backend':'cpu','context_tokens':8192,'media':{'image_profile':'sd15','voice_engine':'piper'},'storage':{'output_reserve_gib':77},'future':{'keep':True}}
            path.write_text(json.dumps(policy))
            with patch.object(settings_page,'inventory',return_value={'models':[]}):
                settings_page.save_settings(root,{'selection':'auto','backend':'vulkan','context_tokens':'4096'},scope='chat')
            saved=json.loads(path.read_text());self.assertEqual(saved['media'],policy['media']);self.assertEqual(saved['storage'],policy['storage'])
            settings_page.save_settings(root,{'image_profile':'auto','image_engine':'auto','speech_model':'base','voice_engine':'piper'},scope='media')
            saved=json.loads(path.read_text());self.assertEqual(saved['backend'],'vulkan');self.assertEqual(saved['context_tokens'],4096)
            self.assertEqual(saved['future'],policy['future']);self.assertEqual(saved['media']['speech_model'],'base')

    def test_media_check_uses_new_choices_without_loading_compute(self):
        with tempfile.TemporaryDirectory() as tmp,patch('runtime_policy.detect_hardware',return_value={'synthetic':True}),patch('media_policy.image_plan',return_value={'profile':'sd15','engine':'sdcpp-cpu'}) as image,patch('media_policy.speech_plan',return_value={'model':'base','device':'cpu'}),patch('tts_policy.tts_plan',return_value={'engine':'piper','device':'cpu'}):
            (Path(tmp)/'Agent').mkdir();(Path(tmp)/'Agent/hardware_profiles.json').write_text('{}')
            choices=dict(image_profile='sd15',image_engine='sdcpp-cpu',speech_model='base',voice_engine='piper')
            result=settings_page.media_fit(Path(tmp),choices)
            self.assertIn('sdcpp-cpu',result)
            self.assertEqual(image.call_args.kwargs['policy']['media'],{
                **choices,'media_variant':'auto','text_video_engine':'auto',
                'reference_video_profile':'auto','music_engine':'auto'})
            self.assertEqual(image.call_args.kwargs['hardware'],{'synthetic':True})


class CompactPanels(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('1220x700+30+30');self.errors=[]
        self.app.report_callback_exception=lambda *args:self.errors.append(args)
    def tearDown(self):finish_tk_fixture(self.app);self.assertEqual(self.errors,[])
    def test_last_button_row_fills_width(self):
        from ui_extensions import ResponsiveGrid
        from elegant_native_ui import ElegantButton
        grid=ResponsiveGrid(self.app,min_cell_width=200,max_columns=3);grid.pack(fill='x')
        items=[grid.add(ElegantButton(grid,text=str(i))) for i in range(5)];self.app.update()
        self.assertEqual(items[-1].winfo_x()+items[-1].winfo_width(),grid.winfo_width())
        self.assertLessEqual(abs(items[-1].winfo_width()-items[-2].winfo_width()),4)
    def test_packages_page_search_columns_navigation_and_theme(self):
        from packages_page import PackagesView
        view=PackagesView(self.app,LIGHT);view.pack(fill='both',expand=True)
        for i in range(35):
            status,detail=view.add(str(i),'Package '+str(i));status.configure(text='INSTALLED');detail.configure(text='Portable synthetic package '+str(i))
        self.app.update();self.assertGreater(view.page_size,8)
        self.assertTrue(view.entries[1][2].winfo_x()>view.entries[0][2].winfo_x())
        view.next.invoke();self.app.update();self.assertEqual(view.page_index,1)
        view.query.set('Package 34');self.app.update();self.assertEqual(view.page_index,0)
        self.assertTrue(view.entries[34][2].winfo_ismapped());self.assertFalse(view.entries[0][2].winfo_ismapped())
        view.select('weights');self.app.update();self.assertTrue(view.diffusion_box.winfo_ismapped())
        view.apply_palette(DARK);self.assertEqual(view.entries[0][3].cget('fg'),DARK['good'])
        view.query.set('');view.select('packages');self.app.geometry('600x700');self.app.update()
        self.assertEqual(view.entries[1][2].winfo_x(),view.entries[0][2].winfo_x())
    def test_persistence_scrolls_locally_and_keeps_admin_boundary(self):
        from persistence_page import PersistencePage
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            page=PersistencePage(self.app,root,LIGHT);page.pack(fill='both',expand=True);page.select();self.app.update()
            mission=page.pages['missions'];self.assertTrue(mission.mission_tree.cget('yscrollcommand'))
            self.app.geometry('600x400');self.app.update();before=mission.skin.canvas.yview()[0]
            label=next(w for w in mission.content.winfo_children()[0].winfo_children() if isinstance(w,tk.Label))
            label.event_generate('<MouseWheel>',delta=-120);self.app.update()
            self.assertGreater(mission.skin.canvas.yview()[0],before)
            page.select('schedules');self.app.update();self.assertTrue(page.pages['schedules'].winfo_ismapped())
            page.destroy()
            with patch('persistence_page.can_admin',return_value=False):
                page=PersistencePage(self.app,root,LIGHT);page.pack();page.select();self.assertEqual(page.pages,{})

if __name__=='__main__':unittest.main()
