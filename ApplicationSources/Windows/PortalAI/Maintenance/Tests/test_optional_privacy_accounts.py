"""Synthetic profiles only. Password policy and storage policy are independent."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import local_accounts as accounts
PASSWORD='Synthetic test password only'
NEW='Another synthetic password only'

class OptionalPrivacyAccounts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=accounts.LocalAccounts(self.root)
        self.addCleanup(self.store.logout)
        kdf=patch.object(accounts,'_KDF_N',1024);kdf.start();self.addCleanup(kdf.stop)

    def test_four_modes_for_administrators_and_members(self):
        for encrypted in (True,False):
            for password_required in (True,False):
                with self.subTest(encrypted=encrypted,password_required=password_required):
                    store=accounts.LocalAccounts(self.root/(str(encrypted)+str(password_required)))
                    self.addCleanup(store.logout)
                    password=PASSWORD if password_required else ''
                    admin=store.bootstrap('Owner',password,encrypted=encrypted,password_required=password_required)
                    self.assertEqual((admin.encrypted,admin.password_required),(encrypted,password_required))
                    row=store.create_user(admin,'Member',password,admin_password=password,encrypted=encrypted,password_required=password_required)
                    member=store.login('Member',password)
                    self.assertEqual((member.encrypted,member.password_required),(encrypted,password_required))
                    delegated=store.profile_session(admin,row['user_id'])
                    self.assertEqual(delegated.encrypted,encrypted)
                    with self.assertRaises(accounts.AuthenticationError):store.login('Member','wrong')
                    restarted=accounts.LocalAccounts(store.root);self.addCleanup(restarted.logout)
                    self.assertEqual(restarted.login('Owner',password).profile_key,admin.profile_key)
                    self.assertNotIn(PASSWORD,store.registry_path.read_text())

    def test_account_free_startup_has_persistent_identity_without_password(self):
        actor=self.store.bootstrap_without_account()
        self.assertTrue(actor.anonymous);self.assertFalse(actor.encrypted);self.assertFalse(actor.password_required)
        identity=actor.user_id;self.store.logout(actor)
        self.assertEqual(self.store.login_without_account().user_id,identity)

    def test_passwordless_user_has_no_admin_authority(self):
        admin=self.store.bootstrap('Owner',PASSWORD)
        self.store.create_user(admin,'Public','',admin_password=PASSWORD,encrypted=False,password_required=False)
        member=self.store.login('Public','')
        with self.assertRaises(accounts.AuthorizationError):self.store.list_users(member)
        with self.assertRaises(accounts.AuthorizationError):self.store.profile_session(member,admin.user_id)

    def test_privacy_metadata_is_authenticated(self):
        admin=self.store.bootstrap('Owner',PASSWORD,encrypted=False)
        data=json.loads(self.store.registry_path.read_text())
        data['slots'][admin.user_id]['encrypted']=True
        self.store.registry_path.write_text(json.dumps(data))
        with self.assertRaises(accounts.AuthenticationError):self.store.login('Owner',PASSWORD)

    def test_password_change_preserves_unencrypted_storage(self):
        admin=self.store.bootstrap('Owner',PASSWORD,encrypted=False)
        self.store.create_user(admin,'Member','',admin_password=PASSWORD,encrypted=False,password_required=False)
        member=self.store.login('Member','')
        changed=self.store.change_password(member,'',NEW)
        self.assertFalse(changed.encrypted);self.assertTrue(changed.password_required)
        self.assertFalse(member.active)
        self.assertEqual(self.store.login('Member',NEW).profile_key,changed.profile_key)
        self.store.list_users(admin)

    def test_passwordless_promotion_and_reauthentication(self):
        admin=self.store.bootstrap('Owner','',password_required=False,encrypted=False)
        row=self.store.create_user(admin,'Member','',admin_password='',password_required=False,encrypted=False)
        self.store.promote(admin,row['user_id'],admin_password='',target_password='')
        promoted=self.store.login('Member','')
        self.assertEqual(promoted.role,'admin');self.assertFalse(promoted.password_required)
        with self.assertRaises(accounts.AuthenticationError):self.store.create_user(promoted,'Bad',PASSWORD,admin_password='not empty')

    def test_pending_is_distinct_from_passwordless(self):
        admin=self.store.bootstrap('Owner',PASSWORD)
        row=self.store.create_user(admin,'Pending',None,admin_password=PASSWORD)
        self.assertTrue(row['pending']);self.assertTrue(row['password_required'])
        with self.assertRaises(accounts.AuthenticationError):self.store.login('Pending','')

    def test_encrypted_defaults_remain_legacy_compatible(self):
        admin=self.store.bootstrap('Owner',PASSWORD)
        data=json.loads(self.store.registry_path.read_text())
        slot=data['slots'][admin.user_id]
        self.assertNotIn('encrypted',slot);self.assertNotIn('open_dek',slot)
        self.assertTrue(admin.encrypted);self.assertTrue(admin.password_required)

    def test_shared_and_public_encryption_keys_require_privacy_conversion(self):
        admin=self.store.bootstrap_without_account()
        with self.assertRaises(accounts.AuthorizationError):self.store.change_password(admin,'',NEW)
        self.assertEqual(self.store.login_without_account().user_id,admin.user_id)
        row=self.store.create_user(admin,'Public key','',admin_password='',encrypted=True,password_required=False)
        member=self.store.login('Public key','')
        with self.assertRaises(accounts.AuthorizationError):self.store.change_password(member,'',NEW)
        self.assertFalse(self.store.login('Public key','').password_required)

    def test_orphaned_privacy_staging_is_not_a_fresh_install(self):
        (self.root/'Private/PrivacyChange').mkdir(parents=True)
        self.assertEqual(self.store.status()['state'],'recovery_required')
        with self.assertRaises(accounts.RecoveryRequired):self.store.bootstrap_without_account()

if __name__=='__main__':unittest.main(verbosity=2)
