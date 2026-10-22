"""Lazy profile consumers preserve authorization, exports and ordinary tool paths."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
# Code comes from the installed bundle; self.root below is only synthetic data.
# Biology dispatch now imports the first-party Scientific package from this root.
sys.path[:0]=[str(ROOT),str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Tools')]
import admin_profile_access
import maintenance_cleanup
import media_server
import portableai_data_cleanup
import profile_exports
import profile_tool_hydration
import science_tools
from profile_paths import UID_ENV,EPOCH_ENV,ProfileLocked
from profile_workspace import MAGIC,_crypto


class HydrationConsumerTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='Portal hydrate consumer ')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.uid,self.epoch='a'*32,'b'*32
        self.workspace=self.root/'Private/Users'/self.uid/'Workspace'
        self.workspace.mkdir(parents=True)
        self.marker=self.root/'Private/active-session.json'
        self.active={'user_id':self.uid,'epoch':self.epoch,'state':'open'}
        self.marker.write_text(json.dumps(self.active))
        environment=patch.dict(os.environ,{UID_ENV:self.uid,EPOCH_ENV:self.epoch})
        environment.start();self.addCleanup(environment.stop)
        self.calls=[]
        self.hydrate=Mock(side_effect=lambda root,relative=None,recursive=False:self.calls.append((relative,recursive)))
        module=patch.dict(sys.modules,{'profile_hydration':SimpleNamespace(materialize=self.hydrate)})
        module.start();self.addCleanup(module.stop)

    def revoke(self):self.marker.write_text(json.dumps({**self.active,'state':'closed'}))

    def test_mutating_tools_materialize_io_trees_but_inspection_and_cancel_do_not(self):
        for command,options in [('help',{}),('status',{}),('cancel',{}),('preview',{}),('media-info',{}),
                ('route',{}),('version',{}),('science',{'operation':'status'}),('science',{'operation':'help'}),
                ('service',{'action':'stop'}),('service',{'action':'status'})]:
            profile_tool_hydration.prepare_tool_files(self.root,command,**options)
        self.hydrate.assert_not_called()
        for command,options in [('image',{}),('audio-edit',{}),('science',{'operation':'run'}),('service',{'action':'start'})]:
            self.calls.clear()
            profile_tool_hydration.prepare_tool_files(self.root,command,**options)
            self.assertEqual(self.calls,[('Outputs',True),('User Folder',True)])

    def test_failed_hydration_stops_science_before_mutating_dispatch(self):
        self.hydrate.side_effect=ProfileLocked('login ended')
        with patch.object(science_tools,'op_run') as operation:
            with self.assertRaises(ProfileLocked):science_tools.dispatch(self.root,self.root,{'operation':'run'})
        operation.assert_not_called()
        self.assertEqual(self.hydrate.call_count,1)

    def test_science_help_does_not_request_bulk_hydration(self):
        with patch.object(science_tools,'op_help',return_value={'success':True}) as operation:
            self.assertTrue(science_tools.dispatch(self.root,self.root,{'operation':'help'})['success'])
        operation.assert_called_once();self.hydrate.assert_not_called()

    def test_export_hydrates_selected_prefixes_before_inventory(self):
        def restore(root,relative=None,recursive=False):
            self.calls.append((relative,recursive))
            if relative=='Outputs':
                path=self.workspace/'Outputs/Images/old.png'
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'synthetic old output')
        self.hydrate.side_effect=restore
        session=SimpleNamespace(user_id=self.uid,profile_key=b'k'*32)
        target=self.root/'outputs.zip'
        with patch('runtime_policy.require_space'):
            result=profile_exports.export_profile(self.root,session,'outputs',target)
        self.assertTrue(result['verified'])
        self.assertIn(('Outputs',True),self.calls);self.assertIn(('User Folder',True),self.calls)
        self.assertNotIn(('Data/LegacyRecovery',True),self.calls)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.read('Outputs/Images/old.png'),b'synthetic old output')

    def test_revocation_during_export_hydration_prevents_archive_creation(self):
        self.hydrate.side_effect=lambda *a,**kw:self.revoke()
        target=self.root/'outputs.zip'
        with self.assertRaises(ProfileLocked):
            profile_exports.export_profile(self.root,SimpleNamespace(user_id=self.uid,profile_key=b'k'*32),'outputs',target)
        self.assertFalse(target.exists())

    def server(self):
        output=self.workspace/'Outputs';output.mkdir(exist_ok=True)
        handler=partial(media_server.PortableAIOutputHandler,directory=str(output),portable_root=self.root,
                        profile_context=(self.uid,self.epoch),capability='synthetic-capability')
        server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        def close():
            server.shutdown();server.server_close();thread.join(3)
            self.assertFalse(thread.is_alive())
        self.addCleanup(close)
        return 'http://127.0.0.1:'+str(server.server_port)

    def test_preview_hydrates_only_authorized_exact_file_for_get_and_head(self):
        def restore(root,relative=None,recursive=False):
            self.calls.append((relative,recursive))
            if relative=='Outputs/Images/lazy.png':
                self.assertFalse(recursive)
                path=self.workspace/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'lazy media fixture')
        self.hydrate.side_effect=restore
        base=self.server()
        self.hydrate.assert_not_called()
        for method in ('HEAD','GET'):
            with urlopen(Request(base+'/Images/lazy.png?portal_token=synthetic-capability',method=method),timeout=3) as response:
                self.assertEqual(response.status,200)
                self.assertEqual(response.read(),b'' if method=='HEAD' else b'lazy media fixture')
        self.assertEqual([row for row in self.calls if row[0]=='Outputs/Images/lazy.png'],
                         [('Outputs/Images/lazy.png',False)]*2)
        self.assertFalse(any(recursive for _,recursive in self.calls))

    def test_wrong_preview_capability_never_hydrates_and_logout_during_hydrate_denies_response(self):
        base=self.server()
        with self.assertRaises(HTTPError) as error:urlopen(base+'/old.png?portal_token=wrong',timeout=3)
        self.assertEqual(error.exception.code,403);self.hydrate.assert_not_called()
        def restore(root,relative=None,recursive=False):
            if relative=='Outputs/old.png':self.revoke()
        self.hydrate.side_effect=restore
        with self.assertRaises(HTTPError) as error:urlopen(base+'/old.png?portal_token=synthetic-capability',timeout=3)
        self.assertEqual(error.exception.code,403)

    def test_cleanup_restores_output_inventory_before_preview_and_delete(self):
        materialized=False
        def restore(root,relative=None,recursive=False):
            nonlocal materialized
            self.calls.append((relative,recursive))
            if relative=='Outputs' and recursive and not materialized:
                path=self.workspace/'Outputs/WebImages/old.png'
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'old web image')
                materialized=True
        self.hydrate.side_effect=restore
        preview=maintenance_cleanup.preview_cleanup(self.root,'outputs')
        self.assertEqual(preview['files'],1)
        result=maintenance_cleanup.execute_cleanup(self.root,'outputs')
        self.assertTrue(result['success']);self.assertEqual(result['deleted_files'],1)
        self.assertFalse((self.workspace/'Outputs/WebImages/old.png').exists())
        self.assertNotIn(('Data',True),self.calls)

    def test_legacy_cleanup_refuses_account_enabled_bundle_before_any_write(self):
        sentinel=self.root/'Outputs/keep.txt';sentinel.parent.mkdir();sentinel.write_text('keep')
        for apply in (False,True):
            with self.assertRaisesRegex(PermissionError,'signed-in Control Center'):
                portableai_data_cleanup.run(self.root,'outputs',apply)
        self.assertEqual(sentinel.read_text(),'keep')

    def test_admin_stream_uses_resolved_older_generation_blob(self):
        key=b'k'*32;relative='Outputs/old.txt';plain=b'unchanged ciphertext generation fixture'
        source=self.root/'older-blob.enc';nonce=b'n'*12;aad=b'synthetic-bound-path'
        source.write_bytes(MAGIC+nonce+_crypto()[3](key).encrypt(nonce,plain,aad))
        row={'path':relative,'bytes':len(plain),'sha256':hashlib.sha256(plain).hexdigest(),'blob':'old.enc'}
        manifest={'generation':'new generation','files':[row]}
        resolver=Mock(return_value=source)
        store=SimpleNamespace(root=self.root,blob_path=resolver,_key=lambda:key,_aad=lambda path:aad)
        destination=io.BytesIO()
        admin_profile_access._stream_file(store,manifest,row,destination)
        self.assertEqual(destination.getvalue(),plain)
        resolver.assert_called_once_with(manifest,row)


class EncryptedHydrationIntegration(unittest.TestCase):
    def test_incremental_media_export_and_deletion_survive_next_login(self):
        # Real crypto/ledger/broker and loopback media server; only a temporary
        # root and a synthetic process-local key. No user credentials or models.
        from profile_workspace import ProfileWorkspace
        from profile_hydration import HydrationBroker
        with tempfile.TemporaryDirectory(prefix='Portal encrypted hydrate ') as folder:
            root=Path(folder);uid,epoch='c'*32,'d'*32
            session=SimpleNamespace(user_id=uid,profile_key=b'k'*32)
            store=ProfileWorkspace(root,session)
            rows={'Data/Chat/settings.json':b'{}','Outputs/Images/old.png':b'synthetic picture',
                  'Outputs/Transcripts/old.txt':b'old transcript','User Folder/note.txt':b'old user note',
                  'Data/LegacyRecovery/archive.txt':b'leave this historical file encrypted'}
            for relative,content in rows.items():
                path=store.workspace/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            first=store.snapshot()
            (store.workspace/'Data/Chat/settings.json').write_bytes(b'{"changed":true}')
            second=store.snapshot()
            self.assertNotEqual(first['generation'],second['generation'])
            manifest=store.manifest()
            row=next(row for row in manifest['files'] if row['path']=='Outputs/Images/old.png')
            self.assertEqual(row['blob_generation'],first['generation'])
            streamed=io.BytesIO();admin_profile_access._stream_file(store,manifest,row,streamed)
            self.assertEqual(streamed.getvalue(),rows[row['path']])
            store.seal(writers_stopped=True);store.restore(lazy=True)
            self.assertFalse((store.workspace/'Outputs/Images/old.png').exists())
            self.assertTrue((store.workspace/'Data/Chat/settings.json').is_file())
            marker=root/'Private/active-session.json'
            marker.write_text(json.dumps({'user_id':uid,'epoch':epoch,'state':'open','controller_pid':os.getpid()}))
            with patch.dict(os.environ,{UID_ENV:uid,EPOCH_ENV:epoch}):
                broker=HydrationBroker(root,(uid,epoch),lambda:session,lambda value:None)
                try:
                    output=store.workspace/'Outputs';output.mkdir(exist_ok=True)
                    handler=partial(media_server.PortableAIOutputHandler,directory=str(output),portable_root=root,
                                    profile_context=(uid,epoch),capability='fixture-preview-capability')
                    server=ThreadingHTTPServer(('127.0.0.1',0),handler)
                    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
                    try:
                        url=f'http://127.0.0.1:{server.server_port}/Images/old.png?portal_token=fixture-preview-capability'
                        with urlopen(url,timeout=5) as response:self.assertEqual(response.read(),b'synthetic picture')
                    finally:
                        server.shutdown();server.server_close();thread.join(3)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse((store.workspace/'Outputs/Transcripts/old.txt').exists())
                    with patch('runtime_policy.require_space'):
                        exported=profile_exports.export_profile(root,session,'outputs',root/'selected.zip')
                    self.assertEqual(exported['files'],3)
                    with zipfile.ZipFile(root/'selected.zip') as archive:
                        self.assertEqual(archive.read('Outputs/Transcripts/old.txt'),b'old transcript')
                        self.assertEqual(archive.read('User Folder/note.txt'),b'old user note')
                    self.assertFalse((store.workspace/'Data/LegacyRecovery/archive.txt').exists())
                    removed=maintenance_cleanup.execute_cleanup(root,'outputs')
                    self.assertTrue(removed['success']);self.assertEqual(removed['deleted_files'],2)
                finally:broker.close()
            store.seal(writers_stopped=True)
            store.restore(lazy=True)
            store.materialize('Outputs',recursive=True)
            self.assertFalse((store.workspace/'Outputs/Images/old.png').exists())
            self.assertFalse((store.workspace/'Outputs/Transcripts/old.txt').exists())
            store.materialize('Data/LegacyRecovery',recursive=True)
            self.assertEqual((store.workspace/'Data/LegacyRecovery/archive.txt').read_bytes(),rows['Data/LegacyRecovery/archive.txt'])


if __name__=='__main__':unittest.main()
