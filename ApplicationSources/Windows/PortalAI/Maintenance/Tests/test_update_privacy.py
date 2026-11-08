"""Updater closure checks against real disposable plaintext/account-free profiles."""
import contextlib,json,unittest
from unittest.mock import patch
import test_plain_profiles as plain
import portable_update as update

class UpdatePrivacyTests(unittest.TestCase):
    setUp=plain.PlainProfiles.setUp
    release=plain.PlainProfiles.release
    open=plain.PlainProfiles.open
    write=plain.PlainProfiles.write

    def closed(self,anonymous=False):
        if anonymous:
            actor=self.store.bootstrap_without_account();self.runtime.prepare(actor)
        else:actor=self.open()
        path=self.write();self.runtime.close(actor,writers_stopped=True)
        return actor,path

    @contextlib.contextmanager
    def guard(self):
        with patch('profile_shutdown.verify_stopped',return_value={'stopped':True}),patch('instance_runtime.host_directory',return_value=self.root/'HostFixture'):
            with update.closed_guard(self.root,self.root):yield

    def test_verified_plain_account_can_update_without_changing_content(self):
        actor,path=self.closed();before=path.read_bytes()
        with self.guard():pass
        self.assertEqual(path.read_bytes(),before)

    def test_verified_account_free_mode_can_update(self):
        self.closed(anonymous=True)
        with self.guard():pass

    def test_plain_content_changed_since_close_blocks_update(self):
        actor,path=self.closed();path.write_text('newer unsaved content')
        with self.assertRaises((update.UpdateError,ValueError,RuntimeError)):
            with self.guard():pass
        self.assertEqual(path.read_text(),'newer unsaved content')

    def test_missing_plain_recovery_blob_blocks_update(self):
        actor,path=self.closed();base=path.parents[3]
        blobs=list(base.glob('PlainRecovery/*/*.data'));self.assertTrue(blobs);blobs[0].unlink()
        with self.assertRaises((update.UpdateError,OSError,ValueError,RuntimeError)):
            with self.guard():pass

    def test_encrypted_policy_still_rejects_plaintext_despite_receipt(self):
        actor,path=self.closed();registry=self.store.registry_path
        data=json.loads(registry.read_text());data['slots'][actor.user_id]['encrypted']=True
        registry.write_text(json.dumps(data))
        with self.assertRaises(update.UpdateError):
            with self.guard():pass

    def test_pending_plain_seal_blocks_update(self):
        actor,path=self.closed();base=path.parents[3]
        (base/'seal-pending.json').write_text('{}')
        with self.assertRaises(update.UpdateError):
            with self.guard():pass
