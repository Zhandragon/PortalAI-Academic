"""Structured calls for compact/full models use literal argv and existing guards."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('Agent','ControlCenter')]
import native_chat
import media_tool_api as api
from tool_protocol import read_only_tool_attempt


class MediaToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='Portal media tool fixture ')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        with patch.object(native_chat,'bootstrap_python',return_value=ROOT/'Runtime/BootstrapPython/python.exe'):
            self.tool=native_chat.ToolRuntime(self.root,{'tool_timeout_seconds':30})

    def test_image_explicit_variant_translates_without_shell_or_prompt_interpretation(self):
        text='a teapot; & echo "do not execute" $(x)\nbright studio'
        with patch.object(self.tool,'media_tool',return_value='output') as media:
            self.assertEqual(self.tool.execute('generate_image',{'prompt':text,'variant':'uncensored'}),'output')
        command,args=media.call_args.args
        self.assertEqual(command,'image');self.assertEqual(args[-2:],['--',text])
        self.assertIn('--uncensored',args);self.assertNotIn('--profile',args)
        self.assertEqual(api.image_arguments({'prompt':'cube','variant':'uncensored','profile':'flux'}),
                         ['--uncensored','--profile','flux','--','cube'])
        self.assertEqual(api.image_arguments({'prompt':'cube','variant':'uncensored','profile':'auto'}),
                         ['--uncensored','--profile','auto','--','cube'])
        self.assertEqual(api.image_arguments({'prompt':'red sunset'}),['--','red sunset'])
        self.assertIn('--official',api.image_arguments({'prompt':'flower','variant':'standard'}))

    def test_no_admin_shell_even_for_metacharacters(self):
        child=Mock(returncode=0);child.communicate.return_value=('synthetic result','')
        args=['--prompt','a & b; $(c)', '--uncensored']
        with patch.object(native_chat.subprocess,'Popen',return_value=child) as start:
            self.assertEqual(self.tool.execute('media_tool',{'command':'image','arguments':args}),'synthetic result')
        self.assertFalse(start.call_args.kwargs['shell'])
        self.assertEqual(start.call_args.args[0][-len(args):],args)
        self.assertIsNone(self.tool._proc)

    def test_one_off_profile_override_is_explicit_and_validated(self):
        self.assertEqual(api.image_arguments({'prompt':'cube','profile':'sd15','override_saved_profile':True}),
                         ['--profile','sd15','--override-saved-profile','--','cube'])
        for fields in ({'override_saved_profile':True},{'profile':'flux','override_saved_profile':'true'},
                       {'profile':'auto','override_saved_profile':1}):
            with self.assertRaises(ValueError):api.image_arguments({'prompt':'cube',**fields})

    def test_invalid_commands_and_arguments_never_spawn(self):
        with patch.object(native_chat.subprocess,'Popen') as start:
            for args in ({'command':'science','arguments':['run']},{'command':'image;whoami'},
                         {'command':'image','arguments':'--prompt hi'},{'command':'image','arguments':['\x00']}):
                with self.assertRaises((PermissionError,ValueError)):self.tool.execute('media_tool',args)
            for args in ({'prompt':''},{'prompt':'x','width':True},{'prompt':'x','variant':'random'},{'prompt':'x','command':'whoami'}):
                with self.assertRaises(ValueError):self.tool.execute('generate_image',args)
            start.assert_not_called()

    def test_actual_worker_argv_receives_literal_prompt_and_variant(self):
        # Real child process, synthetic worker: proves routing without loading media models.
        (self.root/'Agent').mkdir()
        (self.root/'Agent/ai_tools.py').write_text('import sys,json,os;print(json.dumps({"argv":sys.argv[1:],"saved_image_defaults":os.environ.get("PORTALAI_CHAT_IMAGE_DEFAULTS")}))')
        self.tool.boot=ROOT/'Runtime/BootstrapPython/python.exe'
        result=json.loads(self.tool.execute('generate_image',{'prompt':'teapot & "flower"','variant':'uncensored','width':512}))
        self.assertEqual(result['argv'][0],'image');self.assertEqual(result['argv'][-2:],['--','teapot & "flower"'])
        self.assertIn('--uncensored',result['argv'])
        self.assertNotIn('--profile',result['argv'])
        self.assertEqual(result['saved_image_defaults'], '1')

    def test_generated_image_arguments_are_accepted_by_real_cli_parser(self):
        import ai_tools
        arguments=api.image_arguments({'prompt':'--a literal prompt', 'negative':'--literal negative',
                                       'variant':'uncensored','steps':3,'width':512})
        with patch.object(sys,'argv',['ai_tools.py','image',*arguments]), \
             patch.object(ai_tools,'load_config',side_effect=RuntimeError('parser accepted arguments')):
            with self.assertRaisesRegex(RuntimeError,'parser accepted arguments'):ai_tools.main()

    def test_video_and_music_overrides_are_accepted_by_real_cli_parser(self):
        import ai_tools
        for argv in (['video-small','sunrise','--engine','sdcpp-cpu'],
                     ['video','reference.png','wind','--profile','vace13'],
                     ['music','piano','--engine','acestep-scaled'],
                     ['score-video','clip.mp4','piano','--engine','acestep-service']):
            with patch.object(sys,'argv',['ai_tools.py',*argv]), \
                 patch.object(ai_tools,'load_config',side_effect=RuntimeError('parser accepted arguments')):
                with self.assertRaisesRegex(RuntimeError,'parser accepted arguments'):ai_tools.main()

    def test_stop_or_profile_revocation_before_spawn_is_fail_closed(self):
        original=self.tool._effort_env
        def cancelled(env):
            result=original(env);self.tool._cancel_epoch=1;return result
        with patch.object(self.tool,'_effort_env',side_effect=cancelled),patch.object(native_chat.subprocess,'Popen') as start:
            with self.assertRaisesRegex(RuntimeError,'cancelled'):self.tool.media_tool('image',['--prompt','teapot'])
            start.assert_not_called()
        with patch.object(self.tool,'_account_role',side_effect=PermissionError('revoked')):
            with self.assertRaises(PermissionError):self.tool.execute('generate_image',{'prompt':'teapot'})

    def test_tools_and_variants_visible_to_every_context_and_no_effect_replay(self):
        names={tool['function']['name'] for tool in native_chat.TOOLS}
        self.assertTrue({'science','generate_image','media_tool','available_tools'}<=names)
        self.assertFalse(read_only_tool_attempt('generate_image',{'prompt':'x'},self.root))
        self.assertFalse(read_only_tool_attempt('media_tool',{'command':'image'},self.root))
        self.assertTrue(read_only_tool_attempt('available_tools',{},self.root))
        with patch('runtime_policy.load_effective_policy',return_value={'variant_preference':'uncensored','media':{'media_variant':'standard'}}):
            result=json.loads(self.tool.execute('available_tools',{'command':'image'}))
        self.assertEqual(result['chat_variant'],'uncensored')
        self.assertEqual(result['media_variant'],'standard')
        self.assertEqual(result['media_defaults']['media_variant'],'standard')
        self.assertEqual(result['commands'],['image'])
        self.assertTrue(any(row['uncensored'] for row in result['variants']['models'] if 'uncensored' in row))
        for command in ('generate_image','image'):
            self.assertTrue(any(row['id']=='flux-klein' for row in api.variant_catalog(self.root,command)['models']))
        self.assertEqual(api.variant_catalog(self.root,'version')['models'],[])
        self.assertTrue(any(row['status']=='not_applicable' for row in api.variant_catalog(self.root,'science')['models']))


if __name__ == '__main__':unittest.main()
