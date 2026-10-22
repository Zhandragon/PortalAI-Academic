"""Synthetic profile path/preview tests; no models, network or user data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Scientific')]
import media_paths as paths
import profile_paths
import media_server


class ProfileMedia(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.uid = 'a'*32
        self.epoch = 'b'*32
        accounts = self.root/'Private/Accounts'
        accounts.mkdir(parents=True)
        (accounts/'initialized.json').write_text('{}')
        self.active = self.root/'Private/active-session.json'
        self.write_active()
        self.env = patch.dict(os.environ, {profile_paths.UID_ENV:self.uid, profile_paths.EPOCH_ENV:self.epoch})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.workspace = profile_paths.workspace_root(self.root,self.uid)

    def write_active(self, **overrides):
        self.active.write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':'open',**overrides}))

    def test_legacy_and_current_references_converge(self):
        expected = self.workspace/'Outputs/Images/example.png'
        self.assertEqual(paths.media_reference(self.root,'Outputs/Images/example.png'),expected)
        self.assertEqual(paths.media_reference(self.root,self.root/'Outputs/Images/example.png'),expected)
        self.assertEqual(paths.media_reference(self.root,expected),expected)

    def test_old_profile_and_traversal_rejected(self):
        for value in ['Private/Users/'+'c'*32+'/Workspace/Outputs/private.png','Outputs/../../Agent/config.json']:
            with self.subTest(value=value), self.assertRaises((PermissionError,ValueError)):
                paths.media_reference(self.root,value)

    def test_attachment_inputs_use_account_and_hydration_not_cwd(self):
        relative='Data/Chat/Attachments/'+'d'*32+'/photo.png'
        expected=self.workspace/relative
        expected.parent.mkdir(parents=True);expected.write_bytes(b'synthetic image fixture')
        for value in (relative, 'Private/Users/'+self.uid+'/Workspace/'+relative,
                      str(expected), 'E:/PortalAI Windows/Private/Users/'+self.uid+'/Workspace/'+relative):
            with self.subTest(value=value), patch('profile_hydration.materialize') as hydrate:
                self.assertEqual(paths.image_source(self.root,value),expected)
                hydrate.assert_called_once_with(profile_paths.Path(self.root),relative,recursive=True)
        self.assertFalse((self.root/relative).exists())
        with self.assertRaises(FileNotFoundError):paths.image_source(self.root,'Outputs/Edited/missing.png')
        self.write_active(state='closed')
        with self.assertRaises(PermissionError):paths.image_source(self.root,expected)

    def test_public_workflow_and_private_comfy_paths_remain_distinct(self):
        import _common,comfy_bridge
        with patch.object(_common,'root_dir',return_value=self.root):
            self.assertEqual(_common.resolve_root('Workflows/API'),self.root/'Workflows/API')
            self.assertEqual(_common.resolve_root('Outputs/Edited'),self.workspace/'Outputs/Edited')
        with patch.object(comfy_bridge,'root_dir',return_value=self.root), patch.object(_common,'root_dir',return_value=self.root):
            bridge=comfy_bridge.ComfyBridge()
            self.assertEqual(bridge._input_dir(),self.workspace/'Generative/ComfyUI_windows_portable/ComfyUI/input')

    def test_generated_files_cannot_overwrite_shared_program(self):
        with self.assertRaises(PermissionError):
            paths.media_output(self.root,'Agent/config.json')
        self.assertEqual(paths.media_output(self.root,'Outputs/image.png'),self.workspace/'Outputs/image.png')

    def test_legacy_external_file_access_unchanged(self):
        unconfigured = self.root/'legacy'
        unconfigured.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.media_reference(unconfigured,self.root/'external.wav'),self.root/'external.wav')
            self.assertEqual(paths.media_runtime(unconfigured),unconfigured/'Agent/.runtime')
            self.assertIsNone(paths.preview_credentials(unconfigured))

    def test_private_scratch_does_not_move_lifecycle_root(self):
        self.assertEqual(paths.media_runtime(self.root),self.workspace/'Cache/MediaWorkers')
        self.assertEqual(paths.media_temp(self.root),self.workspace/'Cache/tmp')
        self.assertFalse((self.root/'Agent/.runtime').exists())

    def test_stale_epoch_is_rejected(self):
        self.write_active(epoch='d'*32)
        with self.assertRaises(PermissionError):
            paths.media_reference(self.root,'Outputs/new.png')
        with self.assertRaises(PermissionError):
            paths.preview_credentials(self.root)

    def test_locked_installation_has_no_legacy_fallback(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(PermissionError):
            paths.media_output(self.root,'Outputs/new.png')

    def test_preview_capability_stable_per_login_and_rotates_next_login(self):
        first = paths.preview_credentials(self.root)
        self.assertEqual(first,paths.preview_credentials(self.root))
        self.assertNotEqual(first,self.epoch)
        self.assertIn('portal_token='+first,paths.preview_url(self.root,'http://127.0.0.1:8765/a.png'))
        self.epoch='d'*32
        self.write_active()
        with patch.dict(os.environ,{profile_paths.EPOCH_ENV:self.epoch}):
            self.assertNotEqual(first,paths.preview_credentials(self.root))

    def handler(self, token=None):
        handler = object.__new__(media_server.PortableAIOutputHandler)
        handler._portable_root=self.root
        handler._root=self.workspace/'Outputs'
        handler._profile_context=(self.uid,self.epoch)
        handler._capability=paths.preview_credentials(self.root)
        handler.path='/image.png'+(('?portal_token='+token) if token else '')
        return handler

    def test_preview_requires_capability(self):
        handler=self.handler()
        self.assertFalse(handler._authorized())
        handler.path+='?portal_token=wrong'
        self.assertFalse(handler._authorized())
        handler.path='/image.png?portal_token='+handler._capability
        self.assertTrue(handler._authorized())
        handler.path+='&portal_token='+handler._capability
        self.assertFalse(handler._authorized())

    def test_preview_revokes_after_logout_or_output_root_change(self):
        token=paths.preview_credentials(self.root)
        handler=self.handler(token)
        self.assertTrue(handler._authorized())
        handler._root=self.root/'Outputs'
        self.assertFalse(handler._authorized())
        handler._root=self.workspace/'Outputs'
        self.write_active(state='sealing')
        self.assertFalse(handler._authorized())

    def test_capability_probe_rejects_unowned_or_other_profile_listener(self):
        import service_manager as service
        command=[str(self.root/'Runtime/BootstrapPython/python.exe'),'-u',str(self.root/'Agent/media_server.py'),
                 '--root',str(self.workspace/'Outputs'),'--port','8765']
        with patch.object(service,'_listening_pids',return_value=[123]), patch.object(service,'_process_command_line',return_value=command):
            self.assertTrue(paths.owned_preview(self.root,8765))
            command[2]=str(self.root/'Agent/unrelated.py')
            self.assertFalse(paths.owned_preview(self.root,8765))
            command[2]=str(self.root/'Agent/media_server.py')
            command[4]=str(self.root/'Outputs')
            self.assertFalse(paths.owned_preview(self.root,8765))

    def test_head_and_directory_listing_do_not_bypass_auth(self):
        handler=self.handler()
        with patch.object(handler,'send_error') as error:
            handler.do_HEAD()
            error.assert_called_once_with(403,'Preview session is locked or expired')
        with patch.object(handler,'send_error') as error:
            self.assertIsNone(handler.list_directory(str(self.workspace)))
            error.assert_called_once_with(403,'Directory listing is disabled')

    def test_comfy_all_mutable_directories_are_private(self):
        args=paths.comfy_directory_args(self.root)
        self.assertEqual(len(args),8)
        for index,kind in enumerate(('input','output','temp','user')):
            self.assertEqual(args[index*2],'--'+kind+'-directory')
            self.assertTrue(Path(args[index*2+1]).is_relative_to(self.workspace))
            self.assertTrue(Path(args[index*2+1]).is_dir())

    def test_media_bridges_keep_models_shared_and_outputs_private(self):
        import voice_bridge,musetalk_bridge,video_understanding_bridge
        with patch.object(voice_bridge,'root_dir',return_value=self.root):
            voice=voice_bridge.VoiceBridge()
        with patch.object(musetalk_bridge,'root_dir',return_value=self.root):
            muse=musetalk_bridge.MuseTalkBridge()
        with patch.object(video_understanding_bridge,'_root_dir',return_value=self.root):
            video=video_understanding_bridge.VideoUnderstandingBridge()
        self.assertEqual(voice.voice_root,self.root/'Voice/Qwen3-TTS')
        self.assertEqual(muse.work,self.root/'Video/MuseTalk')
        for output in [voice.output_dir,muse.output_dir,video.output_dir,video.cache_dir,muse.runtime]:
            self.assertTrue(output.is_relative_to(self.workspace))

    def test_science_outputs_and_explicit_destinations_scoped(self):
        import science_core
        self.assertEqual(science_core._outdir({},self.root,'genomics'),self.workspace/'Outputs/Science/genomics')
        with self.assertRaises(PermissionError):
            science_core._outdir({'output_dir':'Agent'},self.root,'genomics')

    def test_piper_default_and_requested_outputs_scoped(self):
        import piper_bridge
        self.assertTrue(piper_bridge.output_path(self.root).is_relative_to(self.workspace/'Outputs/Voices'))
        self.assertEqual(piper_bridge.output_path(self.root,'Outputs/Voices/sample.wav'),self.workspace/'Outputs/Voices/sample.wav')
        with self.assertRaises(PermissionError):
            piper_bridge.output_path(self.root,'Agent/overwrite.wav')

    def test_search_cache_is_private(self):
        from web_state import WebState
        self.assertEqual(WebState(self.root).path,self.workspace/'Cache/Web/search.sqlite3')

    def test_recall_reads_only_active_profile_synthetic_history(self):
        import memory_tools
        for base, title in [(self.root,'legacy'),(self.workspace,'current')]:
            folder=base/'Data/Chat/Sessions';folder.mkdir(parents=True)
            (folder/'synthetic.json').write_text(json.dumps({'id':'synthetic','title':title}))
        self.assertEqual([x['title'] for x in memory_tools.sessions(self.root)],['current'])

    def test_ace_cache_transform_preserves_shared_model_root(self):
        import acestep_embedded_entry as ace
        source='project_root = _get_project_root()\ncache_root = os.path.join(project_root, ".cache", "acestep")\ncheckpoint_dir = os.path.join(project_root, "checkpoints")\nuvicorn.run("acestep.api_server:app", workers=1)\n'
        transformed=ace.profile_api_source(source,self.root)
        self.assertIn(repr(str(self.workspace/'Music/ACE-Step-1.5/.cache/acestep')),transformed)
        self.assertIn('checkpoint_dir = os.path.join(project_root, "checkpoints")',transformed)
        self.assertIn('uvicorn.run(app, workers=1)',transformed)
        with self.assertRaises(RuntimeError):
            ace.profile_api_source(source+source,self.root)
        compile(transformed,'synthetic-ace.py','exec')

    def test_ace_current_installed_source_compiles_without_importing_models(self):
        import acestep_embedded_entry as ace
        file=ROOT/'Music/ACE-Step-1.5/acestep/api_server.py'
        transformed=ace.profile_api_source(file.read_text(encoding='utf-8'),self.root)
        compile(transformed,str(file),'exec')

    def test_specialist_does_not_fall_back_after_cross_profile_denial(self):
        import music_understanding_enhanced as enhanced
        bridge=object.__new__(enhanced.EnhancedMusicUnderstandingBridge)
        bridge.root=self.root
        with patch.object(bridge,'_specialist_available') as probe:
            with self.assertRaises(PermissionError):
                bridge.understand('Private/Users/'+'c'*32+'/Workspace/Outputs/private.wav')
            probe.assert_not_called()

    def start_preview(self, output, context, capability, portable_root=None):
        handler=partial(media_server.PortableAIOutputHandler,directory=str(output),
            portable_root=portable_root or self.root,profile_context=context,capability=capability)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        thread.start()
        def close():
            server.shutdown();server.server_close();thread.join(timeout=3)
        self.addCleanup(close)
        return 'http://127.0.0.1:'+str(server.server_port)

    def test_actual_http_requires_auth_and_revokes_epoch(self):
        output=self.workspace/'Outputs';output.mkdir(parents=True)
        (output/'synthetic.txt').write_text('synthetic private media')
        token=paths.preview_credentials(self.root)
        base=self.start_preview(output,(self.uid,self.epoch),token)
        for suffix in ['/synthetic.txt','/__health__']:
            with self.assertRaises(HTTPError) as error:
                urlopen(base+suffix,timeout=2)
            self.assertEqual(error.exception.code,403)
        url=base+'/synthetic.txt?portal_token='+token
        with urlopen(url,timeout=2) as response:
            self.assertEqual(response.read(),b'synthetic private media')
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertIsNone(response.headers['Access-Control-Allow-Origin'])
        with urlopen(Request(url,method='HEAD'),timeout=2) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(response.read(),b'')
        self.write_active(epoch='d'*32)
        with self.assertRaises(HTTPError) as error:
            urlopen(url,timeout=2)
        self.assertEqual(error.exception.code,403)

    def test_actual_legacy_http_remains_available(self):
        legacy=self.root/'legacy';output=legacy/'Outputs';output.mkdir(parents=True)
        (output/'synthetic.txt').write_text('synthetic legacy media')
        with patch.dict(os.environ,{},clear=True):
            base=self.start_preview(output,None,None,legacy)
            with urlopen(base+'/synthetic.txt',timeout=2) as response:
                self.assertEqual(response.read(),b'synthetic legacy media')
                self.assertEqual(response.headers['Access-Control-Allow-Origin'],'*')


if __name__=='__main__':
    unittest.main()
