"""Root-name compatibility preserves the existing private-reference boundaries."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from test_profile_historical_paths import HistoricalReferenceTests
import profile_paths as paths


class RootRenameTests(HistoricalReferenceTests):
    def setUp(self):
        super().setUp()
        destination=self.root.with_name('PortalAI Windows');self.root.rename(destination);self.root=destination

    def test_legacy_and_new_roots_resolve_after_actual_directory_rename(self):
        workspace=self.activate()
        for name in ('PortableAI','PortalAI','PORTABLEAI','PortalAI Windows','PortalAI Linux','PortalAI Mac'):
            for prefix in ('Z:/','/media/usb/'):
                with self.subTest(name=name,prefix=prefix):
                    expected=workspace/'Outputs/old.png'
                    self.assertEqual(paths.resolve_reference(self.root,prefix+name+'/Outputs/old.png'),expected)
                    self.assertEqual(paths.resolve_reference(self.root,prefix+name+'/Private/Users/'+self.uid+'/Workspace/Outputs/old.png'),expected)

    def test_aliases_do_not_broaden_access(self):
        self.activate()
        for value in ('Z:/Other/Data/private.txt','Z:/PortableAI/PortalAI/Outputs/x',
                      'Z:/PortalAI Mac/PortalAI/Outputs/x',
                      'Z:/PortableAI/Private/Users/'+'c'*32+'/Workspace/Outputs/x',
                      'Z:/PortableAI/Outputs/../../outside','Z:/PortableAI/Models/weights.bin'):
            with self.subTest(value=value), self.assertRaises((paths.ProfileLocked,ValueError)):
                paths.resolve_reference(self.root,value)
        os.environ.pop(paths.EPOCH_ENV)
        with self.assertRaises(paths.ProfileLocked):paths.resolve_reference(self.root,'Z:/PortableAI/Outputs/x')


if __name__=='__main__':unittest.main()
