"""Synthetic Mac ownership/capture contracts; does not claim native execution."""
from pathlib import Path
import sys,tempfile,types,unittest
from unittest.mock import Mock,patch
MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
import host_runtime,macos_target,macos_desktop,portalai_target

def entry(pid=42,title='PortalAI',rect=(100,100,800,624),number=7,visible=True):
    value=Mock();value.owningApplication.return_value.processID.return_value=pid
    value.title.return_value=title;value.isOnScreen.return_value=visible;value.windowID.return_value=number
    x,y,w,h=rect
    value.frame.return_value=types.SimpleNamespace(origin=types.SimpleNamespace(x=x,y=y),size=types.SimpleNamespace(width=w,height=h))
    return value

class CaptureTests(unittest.TestCase):
    def setUp(self):self.window={'pid':42,'hwnd':1001,'title':'PortalAI','rootx':100,'rooty':124,'width':800,'height':600,'visible':True}
    def test_client_crop_excludes_aqua_titlebar(self):self.assertEqual(macos_desktop.client_crop(self.window,(100,100,800,624)),(0,24,800,600))
    def test_only_exact_owner_and_geometry_selected(self):
        selected=entry()
        value,crop=macos_desktop.choose_window(self.window,[entry(pid=99),entry(rect=(0,0,800,624)),selected])
        self.assertIs(value,selected)
    def test_ambiguous_same_pid_windows_refused(self):
        with self.assertRaises(RuntimeError):macos_desktop.choose_window(self.window,[entry(),entry(number=8)])
    def test_missing_foreign_and_hidden_refused(self):
        for items in ([],[entry(pid=99)],[entry(visible=False)]):
            with self.subTest(items=items),self.assertRaises(RuntimeError):macos_desktop.choose_window(self.window,items)
    def test_borderless_native_title_is_not_identity(self):
        selected=entry(title=None)
        self.assertIs(macos_desktop.choose_window(self.window,[selected])[0],selected)
    def test_nonfinite_partial_and_oversized_refused(self):
        for rect in ((float('nan'),100,800,624),(101,100,800,624),(100,100,1400,900),(100,123,800,600)):
            with self.subTest(rect=rect),self.assertRaises(ValueError):macos_desktop.client_crop(self.window,rect)
    def test_old_gui_without_mac_geometry_fails(self):
        self.window.pop('rootx')
        with self.assertRaises(RuntimeError):macos_desktop.choose_window(self.window,[entry()])
    def test_async_capture_failure_timeout_and_success(self):
        self.assertEqual(macos_desktop.completed_call(lambda cb:cb('image',None)),'image')
        with self.assertRaises(RuntimeError):macos_desktop.completed_call(lambda cb:cb(None,'denied'))
        with self.assertRaises(TimeoutError):macos_desktop.completed_call(lambda cb:None,timeout=.001)
    def test_geometry_changes_discard_frame(self):
        desktop=object.__new__(macos_desktop.Desktop);desktop.validate=Mock()
        desktop.request=Mock(return_value={'windows':[{**self.window,'rootx':101}]})
        with self.assertRaises(RuntimeError):desktop.current(self.window)
    def test_identity_change_or_outside_root_refused(self):
        root=Path('target').resolve();desktop=object.__new__(macos_desktop.Desktop);desktop.manager=types.SimpleNamespace(root=root)
        row={'uid':10,'create_time':1.,'executable':str(root/'Runtime/MacPython/bin/python3.12')}
        window={**self.window,'start':1000000,'executable':row['executable']}
        with patch.dict(sys.modules,macos_process=types.SimpleNamespace(identity=lambda pid:row)),patch.object(macos_desktop.os,'getuid',return_value=10,create=True):
            desktop.validate(window)
            for change in ({'start':999},{'executable':'foreign'}):
                with self.assertRaises(RuntimeError):desktop.validate({**window,**change})
            row['uid']=11
            with self.assertRaises(RuntimeError):desktop.validate(window)

class RuntimeTests(unittest.TestCase):
    def test_architecture_specific_runtime_and_packages(self):
        for arch in ('arm64','x86_64'):
            with patch.object(host_runtime.sys,'platform','darwin'),patch.object(host_runtime.platform,'machine',return_value=arch):
                self.assertIn('MacPython-'+arch,str(host_runtime.python_runtime()))
                self.assertIn('MacPackages-'+arch,host_runtime.package_paths()[1])
    def test_unknown_architecture_refused(self):
        with patch.object(host_runtime.platform,'machine',return_value='other'),self.assertRaises(RuntimeError):host_runtime.mac_arch()
    def test_mac_target_requires_mac_launcher_and_runtime(self):
        with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as folder,patch.object(host_runtime.sys,'platform','darwin'):
            root=Path(folder);self.assertFalse(host_runtime.target_valid(root))
            for name in ('Runtime/MacPython/bin/python3.12','Launchers/portalai_gui_macos.py','Agent/profile_shutdown.py'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
            self.assertTrue(host_runtime.target_valid(root))
    def test_gui_ownership_requires_uid_exact_interpreter_and_script(self):
        root=Path('target').resolve()
        row={'uid':10,'executable':str(root/'Runtime/MacPython/bin/python3.12'),'argv':['python',str(root/'Launchers/portalai_gui_macos.py')]}
        with patch.object(macos_target.os,'getuid',return_value=10,create=True):
            self.assertTrue(macos_target.gui_row(root,row))
            for change in ({'uid':11},{'argv':['python']},{'executable':'/host/python'}):self.assertFalse(macos_target.gui_row(root,{**row,**change}))
    def test_launch_uses_native_bootstrap_new_session(self):
        root=Path('target').resolve();spawn=Mock();preflight=Mock()
        with patch.dict(sys.modules,macos_job=types.SimpleNamespace(preflight=preflight)):
            macos_target.launch(types.SimpleNamespace(root=root),{'PORTALAI_NATIVE_STATE':'2'},popen=spawn)
        preflight.assert_called_once();args,kwargs=spawn.call_args
        self.assertEqual(args[0],[str(root/'Runtime/MacPython/bin/python3.12'),'-B','-I',str(root/'Launchers/portalai_gui_macos.py')])
        self.assertTrue(kwargs['start_new_session']);self.assertNotIn('shell',kwargs)
    def test_mac_dispatch_preserves_target_specific_snapshot(self):
        manager=portalai_target.Manager(Path('target'),desktop=Mock())
        with patch.object(portalai_target.sys,'platform','darwin'),patch('profile_shutdown._mac_snapshot',return_value={}) as snapshot:
            self.assertEqual(manager.inventory(True),{})
        snapshot.assert_called_once_with(manager.root)

if __name__=='__main__':unittest.main()
