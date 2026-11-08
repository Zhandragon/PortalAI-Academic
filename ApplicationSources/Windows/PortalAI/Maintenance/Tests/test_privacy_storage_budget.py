"""Configured SSD reserves apply to both plaintext snapshots and conversion."""
import contextlib,json,unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_plain_profiles as plain
import test_privacy_conversion as conversion
from profile_workspace import ProfileWorkspace

@contextlib.contextmanager
def budget(root,free):
    policy=root/'Agent/hardware_profiles.json';policy.parent.mkdir(exist_ok=True)
    policy.write_text('{}')
    (root/'Agent/storage_reserve.json').write_text(json.dumps({'minimum_free_gib':50}))
    value={'storage':{'minimum_free_gib':10,'minimum_free_fraction':0,'output_reserve_gib':5}}
    usage=SimpleNamespace(total=500*1024**3,free=free*1024**3,used=(500-free)*1024**3)
    with patch('runtime_policy.load_policy',return_value=value),patch('shutil.disk_usage',return_value=usage):yield

class PlainBudget(unittest.TestCase):
    setUp=plain.PlainProfiles.setUp
    release=plain.PlainProfiles.release
    open=plain.PlainProfiles.open
    write=plain.PlainProfiles.write

    def test_configured_reserve_allows_snapshot_between_50_and_80_gib(self):
        actor=self.open();path=self.write()
        with budget(self.root,70):self.assertTrue(ProfileWorkspace(self.root,actor).snapshot()['verified'])
        self.assertTrue(path.exists())

    def test_configured_reserve_still_blocks_snapshot_below_50_gib(self):
        actor=self.open();path=self.write()
        with budget(self.root,49),self.assertRaisesRegex(RuntimeError,'reserve'):
            ProfileWorkspace(self.root,actor).snapshot()
        self.assertTrue(path.exists())

class ConversionBudget(unittest.TestCase):
    setUp=conversion.PrivacyConversion.setUp
    release=conversion.PrivacyConversion.release
    runtime=conversion.PrivacyConversion.runtime
    initialize=conversion.PrivacyConversion.initialize
    change=conversion.PrivacyConversion.change
    assert_open=conversion.PrivacyConversion.assert_open

    def test_configured_reserve_allows_verified_privacy_conversion(self):
        self.initialize()
        with budget(self.root,70):self.assertTrue(self.change(False,False)['verified'])
        # Fixture policy is intentionally limited to the preceding mocked preflight.
        (self.root/'Agent/hardware_profiles.json').unlink()
        self.assert_open('',False)

    def test_configured_reserve_blocks_conversion_before_transaction(self):
        self.initialize()
        with budget(self.root,49),self.assertRaisesRegex(RuntimeError,'reserve'):
            self.change(False,False)
        self.assertFalse((self.root/'Private/privacy-change.json').exists())
