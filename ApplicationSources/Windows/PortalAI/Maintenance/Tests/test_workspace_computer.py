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
from desktop_control import Desktop,key_codes
from capability_tools import computer_context,guard,dispatch


class ComputerBoundaries(unittest.TestCase):
    def test_common_key_aliases_share_the_same_bounded_codes(self):
        self.assertEqual(key_codes(['Control','l']),key_codes(['CTRL','L']))
        self.assertEqual(key_codes(['Return']),key_codes(['ENTER']))
        self.assertEqual(key_codes(['Escape']),key_codes(['ESC']))
        for invalid in ([],['unknown'],['CTRL']*5,[1]):
            with self.assertRaises(ValueError):key_codes(invalid)

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

    def test_text_model_can_use_accessibility_without_pixel_controls(self):
        runtime=SimpleNamespace(root=self.root)
        target=Mock();target.call.return_value={'elements':[]}
        with patch('account_permissions.require_admin'),patch('desktop_control.desktop',return_value=target),patch('native_chat.model_props',return_value={}):
            for action in ('state','invoke','set_value','elements','click_element','type','keypress','windows','status'):
                dispatch(runtime,'computer',{'action':action,'target':'Fixture control [1]'},check=lambda:None)
                self.assertFalse(target.call.call_args.args[1]['visual'])
            for action in ('screenshot','click','drag','scroll'):
                with self.assertRaisesRegex(RuntimeError,'text accessibility'):dispatch(runtime,'computer',{'action':action},check=lambda:None)

    def test_accessibility_observation_does_not_attach_an_image(self):
        self.desktop.observation={'token':'fixture','at':time.monotonic(),'backend':'open-computer-use'}
        self.assertIsNone(self.desktop.image_message('fixture'))

    def test_named_target_cannot_combine_another_controls_label_and_id(self):
        self.desktop.observation.update(window=123,targets={'Slippi Launcher [56]':'56','Other folder [66]':'66'})
        with patch.object(self.desktop,'dpi',return_value=nullcontext()),patch.object(self.desktop,'check',return_value={}),patch.object(self.desktop,'focus') as focus:
            with self.assertRaisesRegex(ValueError,'exact named target'):
                self.desktop.call('click_element',{'window':123,'observation':'fixture','target':'Slippi Launcher [66]'},lambda:None)
            focus.assert_not_called()
            self.assertEqual(self.desktop.observation['token'],'fixture')

    def test_focus_queue_attachment_is_released_on_account_cancellation(self):
        user=Mock();kernel=Mock();user.IsIconic.return_value=False
        user.GetForegroundWindow.return_value=999;user.GetWindowThreadProcessId.side_effect=[2,3]
        user.AttachThreadInput.return_value=True;kernel.GetCurrentThreadId.return_value=1
        with patch.object(self.desktop,'api',return_value=(user,kernel)),patch.object(self.desktop,'check',side_effect=[{},PermissionError('login ended')]):
            with self.assertRaises(PermissionError):self.desktop.focus(123,lambda:None)
        self.assertEqual([c.args for c in user.AttachThreadInput.call_args_list],[(1,2,True),(1,3,True),(1,3,False),(1,2,False)])
        user.SetActiveWindow.assert_not_called()

    def test_model_dispatch_rejects_bare_element_ids_before_desktop_input(self):
        runtime=SimpleNamespace(root=self.root)
        target=Mock()
        with patch('account_permissions.require_admin'),patch('desktop_control.desktop',return_value=target),patch('native_chat.model_props',return_value={}):
            for action in ('invoke','set_value','click_element'):
                with self.assertRaises(ValueError):dispatch(runtime,'computer',{'action':action,'element':'56'},check=lambda:None)
            target.call.assert_not_called()

    def test_shared_stop_fences_a_separate_workspace_runtime(self):
        from workspace_services import close_all
        runtime=SimpleNamespace(root=self.root,profile=SimpleNamespace(check=Mock()),_cancel_epoch=1)
        with patch('account_permissions.require_user'):
            check=guard(runtime);close_all(self.root)
            with self.assertRaisesRegex(RuntimeError,'stopped'):check()


if __name__=='__main__':unittest.main()
