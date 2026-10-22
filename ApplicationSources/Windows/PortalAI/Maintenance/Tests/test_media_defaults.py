"""Saved route selection, explicit overrides and unchanged post-handoff admission."""
import ast
from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
import media_defaults as defaults
from model_preferences import MEDIA_CHOICES, merge, validate
from media_choices import CHOICES


class MediaDefaultsTests(unittest.TestCase):
    def test_every_saved_choice_has_a_readable_menu_and_explanation(self):
        self.assertEqual(set(CHOICES),set(MEDIA_CHOICES))
        for key,choices in MEDIA_CHOICES.items():
            self.assertEqual(set(CHOICES[key]),set(choices))
            for value in choices:
                label,description=CHOICES[key][value]
                self.assertNotEqual(label,value)
                self.assertGreater(len(description),60)

    def test_old_profiles_default_to_auto_and_explicit_auto_overrides_saved_route(self):
        self.assertEqual(defaults.choice('text_video_engine',policy={}), 'auto')
        policy={'media':{'text_video_engine':'sdcpp-cpu'}}
        self.assertEqual(defaults.choice('text_video_engine',policy=policy),'sdcpp-cpu')
        self.assertEqual(defaults.choice('text_video_engine','auto',policy=policy),'auto')
        with self.assertRaises(ValueError):defaults.choice('music_engine','invented',policy={})
        saved=merge({}, {'media':{'music_engine':'acestep-scaled','reference_video_profile':'vace13'}})
        validate(saved)
        self.assertEqual(saved['media']['music_engine'],'acestep-scaled')

    def test_route_choices_preserve_os_backend_constraints(self):
        for fn,key,large,small in ((defaults.reference_video_scaled,'reference_video_profile','wan22','vace13'),
                                    (defaults.music_scaled,'music_engine','acestep-service','acestep-scaled')):
            win={'system':'Windows','gpus':[{'backend':'cuda','index':0}]}
            for hw,scaled in ((win,False),({'system':'Windows','gpus':[]},True),
                              ({**win,'system':'Linux'},True)):
                self.assertEqual(fn(policy={},hardware=hw),scaled)
                self.assertEqual(fn(small if scaled else large,policy={},hardware=hw),scaled)
                with self.assertRaises(RuntimeError):fn(large if scaled else small,policy={},hardware=hw)
                policy={'media':{key:large if scaled else small}}
                # Explicit Automatic clears a carried preference from another PC.
                self.assertEqual(fn('auto',policy=policy,hardware=hw),scaled)

    def test_music_dispatch_admits_after_lease_and_restores_on_failure(self):
        import music_selection
        tree=ast.parse((ROOT/'Agent/ai_tools.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_generate_selected_music')
        events=[]
        @contextmanager
        def lease(*args,**kwargs):
            kwargs['start_guard']()
            events.append('reclaim')
            try:yield
            finally:events.append('restore')
        args=SimpleNamespace(engine=None,prompt='piano',lyrics=None,instrumental=True)
        namespace={'root_dir':lambda:ROOT,'_exclusive_pipeline':lease,'math':__import__('math')}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'music-route','exec'),namespace)
        with patch.object(music_selection,'request_guard',return_value=lambda:None), \
             patch.object(music_selection,'admit',side_effect=lambda *a,**k:events.append('admit') or {'engine':'acestep-scaled'}), \
             patch('music_amd_bridge.generate',side_effect=RuntimeError('cancelled')):
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                namespace['_generate_selected_music'](args,{},15,'music')
        self.assertEqual(events,['reclaim','admit','restore'])


if __name__=='__main__':unittest.main()
