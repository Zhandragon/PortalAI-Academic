"""Disposable UI fixtures: no production account authentication or mutations."""
import gc,sys,tempfile,tkinter as tk,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests')]
from account_ui import AccountController,_Dialog,show_login
from account_privacy_ui import privacy_fields,show_privacy
from test_account_presentation_tk import LIGHT,DARK
from tk_fixture_cleanup import finish_tk_fixture

class PrivacyUI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=tk.Tk();self.app.geometry('640x700-10000-10000')
        self.controller=AccountController(Path(self.temp.name),Mock())
        self.app._portalai_account_root=ROOT;self.app.update()

    def tearDown(self):
        remaining=finish_tk_fixture(self.app,jobs=(self.controller.jobs,))
        self.app=None;self.controller=None;gc.collect();self.assertEqual(remaining,0)

    def test_password_fields_and_consequences_follow_selected_policy(self):
        dialog=_Dialog(self.app,'Privacy fixture',LIGHT,jobs=self.controller.jobs)
        password=dialog.entry('Password',secret=True);confirm=dialog.entry('Confirm',secret=True)
        controls=privacy_fields(dialog,password,confirm,administrator=True)
        password.set('synthetic');confirm.set('synthetic');controls.set_values(False,False)
        self.app.update();self.assertEqual(password.get(),'');self.assertEqual(confirm.get(),'')
        self.assertTrue(password._entry_widget.instate(['disabled']))
        self.assertEqual(controls(),{'encrypted':False,'password_required':False})
        controls.set_values(False,True);self.assertFalse(password._entry_widget.instate(['disabled']))
        dialog.close();del password,confirm,controls,dialog

    def test_per_account_role_warning_and_narrow_themes(self):
        actor=SimpleNamespace(username='Owner',role='admin',active=True)
        self.controller.backend.list_users.return_value=[
            dict(username='Owner',role='admin',user_id='a'*32,pending=False,encrypted=True,password_required=True),
            dict(username='Member',role='user',user_id='b'*32,pending=False,encrypted=False,password_required=False)]
        gate=SimpleNamespace(app=self.app,root=Path(self.temp.name),colors=DARK,controller=self.controller,session=actor,on_shutdown_status=None)
        dialog=show_privacy(gate,lock_application=Mock(),exit_application=Mock());self.app.update()
        picker=next(w for w in dialog.rounded_controls if w.winfo_class()=='TCombobox')
        picker.set('Member');self.app.update()
        descriptions=[str(w.cget('text')) for w in dialog.body.winfo_children() if isinstance(w,tk.Label)]
        self.assertTrue(any('Anyone using this installation' in t for t in descriptions))
        self.assertFalse(any('Anyone can use this administrator account' in t for t in descriptions))
        self.assertLessEqual(dialog.surface.card.winfo_width(),self.app.winfo_width())
        self.assertLessEqual(dialog.surface.card.winfo_height(),self.app.winfo_height())
        dialog.close();del dialog,picker,gate

    def test_account_free_startup_opens_once_without_a_password_form(self):
        actor=SimpleNamespace(user_id='a'*32,username='Shared',role='admin',active=True,anonymous=True,encrypted=False,password_required=False)
        self.controller.backend.status.return_value={'state':'locked','auto_profile':actor.user_id,'users':[dict(user_id=actor.user_id,username='Shared',role='admin',pending=False,encrypted=False,password_required=False,anonymous=True)]}
        self.controller.backend.login_without_account.return_value=actor
        prepare=Mock(return_value={'ready':True,'user_id':actor.user_id})
        self.app.after(4000,lambda:[d.close() for d in list(getattr(self.app,'_portalai_account_dialogs',())) if not d.busy])
        result=show_login(self.app,self.controller,LIGHT,prepare_session=prepare)
        self.assertIs(result,actor);self.controller.backend.login_without_account.assert_called_once_with()
        self.controller.backend.login.assert_not_called();prepare.assert_called_once_with(actor)

if __name__=='__main__':unittest.main()
