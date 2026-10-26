"""No HA or production effects: owned-main routing, expiry, lease and receipts."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
import json
from pathlib import Path
import sys
import time
import tempfile
import unittest
from unittest.mock import Mock,patch

MODULE=Path(__file__).resolve().parents[1];ROOT=default_target()
sys.path[:0]=[str(MODULE/'app'),str(ROOT/'Agent')]
import portalai_target as target


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        self.manager=target.Manager(ROOT,Mock())
        self.window={'pid':31,'hwnd':500,'start':100,'class':'TkTopLevel'}
        self.endpoint={'port':2345,'token':'x'*40,'hwnd':500,'native_chat_protocol':1}
        self.manager.native_chat_endpoint=Mock(return_value=(self.window,self.endpoint))
        self.payload={'request_id':'a'*32,'viewer':'b'*32,'operation':'stop','binding':{'view':'c'*32,'epoch':'d'*32},'conversation':'e'*32}
        self.response=Mock(status=200)
        self.response.read.return_value=json.dumps({'accepted':True,'request_id':'a'*32,'operation':'stop'}).encode()
        self.connection=Mock();self.connection.getresponse.return_value=self.response

    def test_no_screenshot_or_popup_dependency_and_absolute_deadline(self):
        self.manager.windows={'wrong-popup':{'hwnd':999}}
        deadline=time.monotonic()+3
        with patch('http.client.HTTPConnection',return_value=self.connection):
            reply=self.manager.native_chat(self.payload,deadline)
        sent=json.loads(self.connection.request.call_args.args[2])
        self.assertEqual(sent['hwnd'],500);self.assertEqual(sent['expires_at'],deadline)
        self.assertEqual(sent['event']['payload'],self.payload);self.assertTrue(reply['accepted'])
        self.manager.native_chat_endpoint.assert_called_once()

    def test_other_controller_cannot_be_taken_over(self):
        self.manager._lease('f'*32)
        with self.assertRaises(PermissionError):self.manager.native_chat(self.payload,time.monotonic()+2)
        self.manager.native_chat_endpoint.assert_not_called()

    def test_expiry_before_and_after_discovery(self):
        with self.assertRaises(TimeoutError):self.manager.native_chat(self.payload,time.monotonic()-1)
        def slow():time.sleep(.04);return self.window,self.endpoint
        self.manager.native_chat_endpoint.side_effect=slow
        with patch('http.client.HTTPConnection') as connection:
            with self.assertRaises(TimeoutError):self.manager.native_chat(self.payload,time.monotonic()+.01)
            connection.assert_not_called()

    def test_owned_process_replacement_is_refused(self):
        self.manager.native_chat_endpoint.side_effect=RuntimeError('Window process was replaced')
        with patch('http.client.HTTPConnection') as connection:
            with self.assertRaises(RuntimeError):self.manager.native_chat(self.payload,time.monotonic()+2)
            connection.assert_not_called()

    def test_exact_ack_and_no_retry(self):
        for reply in ({},{'accepted':True,'request_id':'wrong','operation':'stop'},
                      {'accepted':True,'request_id':'a'*32,'operation':'send'}):
            self.response.read.return_value=json.dumps(reply).encode()
            with patch('http.client.HTTPConnection',return_value=self.connection):
                with self.assertRaises(RuntimeError):self.manager.native_chat(self.payload,time.monotonic()+2)
        self.assertEqual(self.connection.request.call_count,3)

    def test_status_advertises_only_loaded_owned_endpoint(self):
        self.manager.inventory=lambda fresh=False:{}
        with patch('profile_shutdown._marker',return_value=None):
            self.assertEqual(self.manager.status()['native_chat_protocol'],1)
            self.manager.native_chat_endpoint.side_effect=RuntimeError('old GUI')
            self.assertNotIn('native_chat_protocol',self.manager.status())

    def test_background_capture_does_not_acquire_or_renew_control(self):
        self.manager.inventory=lambda fresh=False:{}
        self.manager.desktop.windows.return_value=[]
        self.manager.status=lambda:{}
        self.manager.frame({},background=True)
        self.assertIsNone(self.manager.viewer)
        self.manager._lease('f'*32);before=self.manager.viewer
        self.manager.frame({},background=True)
        self.assertEqual(self.manager.viewer,before)

    def test_discovery_checks_main_HWND_creation_time_and_kernel_identity(self):
        with tempfile.TemporaryDirectory(prefix='native-chat-owned-') as tmp:
            manager=target.Manager(ROOT,Mock());manager.endpoint_dir=Path(tmp)
            row={'pid':31,'start':100,'executable':str(ROOT/'Runtime/BootstrapPython/python.exe'),
                 'argv':[str(ROOT/'ControlCenter/PortableAI_GUI.py')]}
            manager.inventory=lambda fresh=False:{31:row}
            endpoint={**self.endpoint,'pid':31,'start':100}
            path=Path(tmp)/'gui-31.json';path.write_text(json.dumps(endpoint))
            manager.desktop.windows.return_value=[{**self.window,'hwnd':999},self.window]
            window,_=manager.native_chat_endpoint()
            self.assertEqual(window['hwnd'],500)
            manager.desktop.validate.assert_called_once_with({**self.window,'executable':row['executable']})
            manager.desktop.validate.side_effect=RuntimeError('process replaced at kernel check')
            with self.assertRaises(RuntimeError):manager.native_chat_endpoint()
            endpoint['start']=200;path.write_text(json.dumps(endpoint))
            with self.assertRaisesRegex(RuntimeError,'Invalid GUI endpoint'):manager.native_chat_endpoint()


if __name__=='__main__':unittest.main()
