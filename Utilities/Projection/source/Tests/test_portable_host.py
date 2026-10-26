"""Cross-OS relative settings and restart/login race contracts."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import sys,tempfile,unittest,uuid
from unittest.mock import patch,Mock

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'app'),str(default_target()/'Agent')]
import host_runtime,portalai_target

class PortableTests(unittest.TestCase):
    def test_default_target_with_projection_inside_utilities(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'PortalAI'
            (root/'Agent').mkdir(parents=True)
            (root/'Agent/profile_shutdown.py').touch()
            (root/'PortalAI.exe').touch();(root/'PortalAI.sh').touch()
            with patch.object(host_runtime,'MODULE',base/'Utilities/PortalAI-Projection'):
                self.assertEqual(host_runtime.default_target(),root)
                self.assertEqual(host_runtime.resolve_target('../../PortalAI'),root)

    def test_default_target_does_not_search_unrelated_parent_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            with patch.object(host_runtime,'MODULE',base/'Unrelated/PortalAI-Projection'):
                self.assertEqual(host_runtime.default_target(),base/'Unrelated/PortalAI')

    def test_existing_adjacent_target_remains_preferred(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'Utilities/PortalAI'
            (root/'Agent').mkdir(parents=True)
            (root/'Agent/profile_shutdown.py').touch()
            (root/'PortalAI.exe').touch();(root/'PortalAI.sh').touch()
            with patch.object(host_runtime,'MODULE',base/'Utilities/PortalAI-Projection'):
                self.assertEqual(host_runtime.default_target(),root)

    def test_windows_settings_resolve_on_either_host(self):
        self.assertEqual(host_runtime.resolve_target('..\\PortalAI'),host_runtime.resolve_target('../PortalAI'))
        self.assertEqual(host_runtime.resolve_target('../PortalAI'),MODULE.parent/'PortalAI')

    def test_absolute_settings_are_not_portable(self):
        for path in ('D:\\PortalAI','/home/user/PortalAI','//server/share/PortalAI'):
            with self.assertRaises(ValueError):host_runtime.resolve_target(path)

    def test_login_during_restart_must_still_be_sealed(self):
        with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as folder:
            root=Path(folder);manager=portalai_target.Manager(root,Mock())
            row={'pid':42,'start':100,'executable':str(root/'runtime/python'),'argv':[]}
            manager.inventory=lambda fresh=False:{42:row};manager.owned=lambda rows:{}
            manager.desktop.windows.return_value=[{'pid':42,'hwnd':1,'width':800,'height':600,'class':'TkTopLevel'}]
            markers=[{'state':'closed','epoch':'a'*32},{'state':'open','epoch':'b'*32}]
            with patch.object(portalai_target,'gui_row',return_value=True),patch('profile_shutdown._marker',side_effect=markers),patch.object(manager,'_launch') as launch:
                manager._operate('restart',uuid.uuid4().hex)
            self.assertEqual(manager.operation['state'],'failed');launch.assert_not_called()

if __name__=='__main__':unittest.main()
