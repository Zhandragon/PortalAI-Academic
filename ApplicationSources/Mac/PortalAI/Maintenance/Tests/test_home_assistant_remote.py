"""Remote boundary/lifecycle tests use only disposable roots and fake processes."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'HomeAssistant')]
import portalai_bridge as bridge
import remote_lifecycle


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()

    def test_exact_bridge_identity_only(self):
        exe=str(self.root/'Runtime/BootstrapPython/pythonw.exe')
        argv=[exe,'-B','-I',str(self.root/'HomeAssistant/portalai_bridge.py')]
        self.assertTrue(remote_lifecycle.is_bridge(self.root,{'executable':exe,'argv':argv}))
        for args in (argv+['--anything'],[exe,'-c','print("portalai_bridge.py")'],[exe,'-B','-I',str(self.root/'evil/portalai_bridge.py')]):
            self.assertFalse(remote_lifecycle.is_bridge(self.root,{'executable':exe,'argv':args}))

    def test_force_fence_disables_old_mission_policy(self):
        from mission_supervisor import read_policy
        class Store:
            root=self.root
            def folder(s,mid):return s.root/mid
        store=Store();(self.root/'mission').mkdir()
        p=self.root/'mission/run-policy.json';p.write_text('{"enabled":true}')
        self.assertTrue(read_policy(store,'mission')['enabled'])
        remote_lifecycle.force_fence(self.root)
        self.assertFalse(read_policy(store,'mission')['enabled'])
        p.write_text(json.dumps({'enabled':True,'remote_stop_epoch':remote_lifecycle.stop_epoch(self.root)}))
        self.assertTrue(read_policy(store,'mission')['enabled'])
        remote_lifecycle.force_fence(self.root)
        self.assertFalse(read_policy(store,'mission')['enabled'])

    def test_force_fence_disables_old_schedule_epoch(self):
        from mission_schedule import epoch
        with patch('mission_schedule.private_path',side_effect=lambda root,rel:Path(root)/rel):
            first=epoch(self.root);remote_lifecycle.force_fence(self.root)
            self.assertNotEqual(first,epoch(self.root))

    def test_malformed_fence_fails_closed(self):
        remote_lifecycle.force_fence(self.root)
        (self.root/'HomeAssistant/state/forced-stop.json').write_text('{}')
        with self.assertRaises((ValueError,KeyError)):remote_lifecycle.stop_epoch(self.root)

    def test_environment_has_no_profile_authority(self):
        with patch.dict(os.environ,{'PORTALAI_ACCOUNT_UNLOCK':'secret','PORTALAI_PROFILE_EPOCH':'epoch','UNRELATED':'safe'}):
            result=remote_lifecycle.clean_environment()
        self.assertFalse(any(k.startswith('PORTALAI_') for k in result));self.assertEqual(result['UNRELATED'],'safe')

    def test_lifecycle_confirmation_and_deduplication(self):
        manager=bridge.Manager(self.root,object());key=uuid.uuid4().hex
        with self.assertRaises(PermissionError):manager.lifecycle('force_shutdown',{'request_id':key})
        with patch('portalai_bridge.threading.Thread') as thread:
            first=manager.lifecycle('restart',{'request_id':key})
            self.assertEqual(first,manager.lifecycle('restart',{'request_id':key}))
            self.assertEqual(thread.call_count,1)
            with self.assertRaises(RuntimeError):manager.lifecycle('restart',{'request_id':uuid.uuid4().hex})

    def test_one_viewer_and_stale_window(self):
        manager=bridge.Manager(self.root,object());manager._lease('a'*32)
        with self.assertRaises(PermissionError):manager._lease('b'*32)
        with self.assertRaises(ValueError):manager.input({'viewer':'a'*32,'window':'missing','event':{}})

    def test_unsealed_restart_refuses_reopen(self):
        manager=bridge.Manager(self.root,object())
        row={'pid':42,'start':100,'executable':str(self.root/'Runtime/BootstrapPython/pythonw.exe'),
             'argv':[str(self.root/'ControlCenter/PortableAI_GUI.py')]}
        class Desktop:
            def windows(s,rows):return [{'pid':42,'hwnd':1,'width':800,'height':600,'class':'TkTopLevel'}]
            def close(s,window):pass
        manager.desktop=Desktop();manager.inventory=lambda fresh=False:{42:row};manager.owned=lambda rows:{}
        marker={'state':'open','epoch':'a'*32,'user_id':'b'*32}
        with patch('profile_shutdown._marker',return_value=marker),patch.object(manager,'_launch') as launch:
            manager._operate('restart',uuid.uuid4().hex)
        self.assertEqual(manager.operation['state'],'failed');launch.assert_not_called()

    def test_force_kills_only_owned_and_keeps_recovery(self):
        manager=bridge.Manager(self.root,object())
        owned={'pid':42,'ppid':0,'start':100,'executable':str(self.root/'Runtime/app.exe'),'argv':[]}
        foreign={'pid':43,'ppid':0,'start':100,'executable':str(Path(os.environ.get('SystemRoot','/os'))/'foreign.exe'),'argv':[]}
        rows={42:owned,43:foreign};manager.inventory=lambda fresh=False:dict(rows)
        def stop(row,root):self.assertEqual(row['pid'],42);rows.pop(42)
        evidence=self.root/'Private/recovery.enc';evidence.parent.mkdir();evidence.write_bytes(b'retain')
        with patch('profile_shutdown._windows_stop',side_effect=stop),patch('profile_shutdown._fence'):
            manager._operate('force_shutdown',uuid.uuid4().hex)
        self.assertEqual(manager.operation['state'],'complete');self.assertEqual(evidence.read_bytes(),b'retain');self.assertIn(43,rows)

    def test_sealed_restart_waits_before_launch(self):
        from unittest.mock import Mock
        manager=bridge.Manager(self.root,Mock())
        row={'pid':42,'start':100,'executable':str(self.root/'Runtime/BootstrapPython/pythonw.exe'),
             'argv':[str(self.root/'ControlCenter/PortableAI_GUI.py')]}
        manager.desktop.windows.return_value=[{'pid':42,'hwnd':1,'width':800,'height':600,'class':'TkTopLevel'}]
        manager.inventory=lambda fresh=False:{42:row}
        manager.owned=Mock(side_effect=[{42:row},{}])
        marker={'state':'open','epoch':'a'*32,'user_id':'b'*32}
        def launch():
            self.assertEqual(manager.owned.call_count,2)
            manager.desktop.close.assert_called_once()
        with patch('profile_shutdown._marker',side_effect=[marker,{**marker,'state':'closed'}]),patch.object(manager,'_launch',side_effect=launch) as launched,patch('portalai_bridge.time.sleep'),patch('profile_shutdown._windows_stop') as killed:
            manager._operate('restart',uuid.uuid4().hex)
        self.assertEqual(manager.operation['state'],'complete');launched.assert_called_once();killed.assert_not_called()

    def test_restart_timeout_does_not_force_or_reopen(self):
        from unittest.mock import Mock
        manager=bridge.Manager(self.root,Mock())
        row={'pid':42,'start':100,'executable':str(self.root/'Runtime/BootstrapPython/pythonw.exe'),
             'argv':[str(self.root/'ControlCenter/PortableAI_GUI.py')]}
        manager.desktop.windows.return_value=[{'pid':42,'hwnd':1,'width':800,'height':600,'class':'TkTopLevel'}]
        manager.inventory=lambda fresh=False:{42:row};manager.owned=lambda rows:rows
        with patch('profile_shutdown._marker',return_value=None),patch.object(manager,'_launch') as launched,patch('portalai_bridge.time.monotonic',side_effect=[1,182]),patch('profile_shutdown._windows_stop') as killed:
            manager._operate('restart',uuid.uuid4().hex)
        self.assertEqual(manager.operation['state'],'failed');launched.assert_not_called();killed.assert_not_called()

    def test_mutual_tls_required_and_fixed_json_protocol(self):
        from setup_pairing import create
        folder=self.root/'pair';create(folder,'127.0.0.1','127.0.0.1',18791)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(folder/'server.crt',folder/'server.key')
        context.load_verify_locations(folder/'ca.crt');context.verify_mode=ssl.CERT_REQUIRED
        class Manager:
            def status(s):return {'running':False}
        server=bridge.Server(('127.0.0.1',0),bridge.Handler,context,'127.0.0.1',Manager())
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'https://127.0.0.1:{server.server_port}/v1/request'
        request=urllib.request.Request(url,data=b'{"action":"status"}',headers={'Content-Type':'application/json'})
        client=ssl.create_default_context(cafile=str(folder/'ca.crt'))
        try:
            with self.assertRaises((ssl.SSLError,urllib.error.URLError,OSError)):urllib.request.urlopen(request,context=client,timeout=3)
            client.load_cert_chain(folder/'client.crt',folder/'client.key')
            with urllib.request.urlopen(request,context=client,timeout=3) as response:
                self.assertEqual(json.load(response),{'running':False})
                self.assertEqual(response.headers['Cache-Control'],'no-store')
            wrong=urllib.request.Request(url,data=b'{"action":"shell","payload":{}}')
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(wrong,context=client,timeout=3)
        finally:server.shutdown();server.server_close();thread.join(4)


if __name__=='__main__':unittest.main()
