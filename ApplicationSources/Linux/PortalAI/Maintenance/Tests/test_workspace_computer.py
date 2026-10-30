"""Computer image lifetime and chat authorization; no real desktop inputs."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from desktop_control import Desktop
from capability_tools import computer_context,guard


class ComputerBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.identity=object()
        self.capture=patch('desktop_control.capture',return_value=self.identity);self.capture.start();self.addCleanup(self.capture.stop)
        self.desktop=Desktop(self.root,self.identity);self.addCleanup(self.desktop.revoke)
        self.desktop.observation={'token':'fixture','at':time.monotonic(),'size':(20,10),'image':'fixture-only'}

    def test_revocation_expiry_and_login_change_remove_image(self):
        self.assertIsNotNone(self.desktop.image_message('fixture'))
        self.assertIsNone(self.desktop.image_message('wrong-token'))
        self.desktop.observation['at']-=121
        self.assertIsNone(self.desktop.image_message('fixture'))
        self.desktop.observation['at']=time.monotonic()
        with patch('desktop_control.capture',return_value=object()):self.assertIsNone(self.desktop.image_message('fixture'))
        self.desktop.revoke();self.assertIsNone(self.desktop.image_message('fixture'))

    def test_emergency_monitor_revokes_without_another_model_turn(self):
        user=SimpleNamespace(GetAsyncKeyState=lambda key:0x8000)
        with patch.object(self.desktop,'api',return_value=(user,None)),patch.object(self.desktop,'dpi',return_value=nullcontext()),patch.object(self.desktop,'info',return_value={'pid':42,'created':1}):
            self.desktop.grant(123)
            self.assertTrue(self.desktop.emergency.wait(2))
            self.assertIsNone(self.desktop.image_message('fixture'))
            with self.assertRaisesRegex(PermissionError,'stopped'):self.desktop.check(123,lambda:None)
            self.assertFalse(self.desktop.allowed)

    def test_visual_context_is_current_turn_only_and_vision_required(self):
        runtime=SimpleNamespace(root=self.root)
        observation={'role':'tool','name':'computer','content':json.dumps({'observation':'fixture'})}
        chat=SimpleNamespace(tool_runtime=runtime,session={'messages':[{'role':'user','content':'inspect'},observation]})
        with patch('desktop_control.desktop',return_value=self.desktop),patch('capability_tools.guard',return_value=lambda:None),patch('native_chat.model_props',return_value={'modalities':{'vision':True}}):
            self.assertIsNotNone(computer_context(chat))
            chat.session['messages'].append({'role':'user','content':'new request'})
            self.assertIsNone(computer_context(chat));chat.session['messages'].pop()
            with patch('native_chat.model_props',return_value={}):
                with self.assertRaisesRegex(RuntimeError,'cannot see'):computer_context(chat)
            self.desktop.revoke();self.assertIsNone(computer_context(chat))

    def test_cancel_and_account_recheck_fence_chat_operations(self):
        runtime=SimpleNamespace(root=self.root,profile=SimpleNamespace(check=Mock()),_cancel_epoch=1)
        with patch('account_permissions.require_user') as authenticated:
            check=guard(runtime);check();self.assertEqual(authenticated.call_count,2)
            runtime._cancel_epoch=2
            with self.assertRaisesRegex(RuntimeError,'stopped'):check()
        with patch('account_permissions.require_user',side_effect=PermissionError('login ended')):
            with self.assertRaises(PermissionError):guard(runtime)


if __name__=='__main__':unittest.main()
