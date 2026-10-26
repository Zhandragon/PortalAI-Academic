"""Real file transactions on disposable old/current fixtures, without owner accounts."""
from pathlib import Path
import contextlib, hashlib, importlib.util, json, os, tempfile, threading, unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('portable_update',ROOT/'Tools/portable_update.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

class PortableUpdate(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'new';self.target=self.base/'old'
        self.source.mkdir();self.target.mkdir()
        self.put(self.target,u.STAMP,"RELEASE_VERSION = '2026.10.24-r17'\n")
        self.put(self.target,u.BOOT,'# old bootstrap\n')
        self.put(self.target,'Agent/profile_workspace.py','# account-capable fixture\n')
        self.put(self.target,'Agent/config.json','{"owner":"preserve"}')
        self.put(self.target,'Private/Users/test/Vault/blob.enc','opaque-owner-content')
        self.put(self.source,u.STAMP,"RELEASE_VERSION = '2026.10.25-Portable-r44'\n")
        self.put(self.source,u.BOOT,"# guard Maintenance/Updates/PENDING.json\n")
        self.put(self.source,'Agent/profile_workspace.py','# new account-capable fixture\n')
        self.put(self.source,'Agent/config.json','{"default":true}')
        self.put(self.source,'Agent/new.py','# new public module\n')
        self.manifest={'schema':1,'kind':'portalai-public-update','version':'2026.10.25-Portable-r44',
            'edition':'Full','platform':'Windows','compatible_versions':['2026.10.25-Aoostar-r43'],
            'files':[{'path':p.relative_to(self.source).as_posix(),'bytes':p.stat().st_size,'sha256':u.sha(p),'mode':0o644}
                     for p in self.source.rglob('*') if p.is_file()]}
        self.guard=patch.object(u,'closed_guard',lambda *a:contextlib.nullcontext());self.guard.start();self.addCleanup(self.guard.stop)
    def put(self,root,name,data):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data);return p
    def apply(self):return u.apply(self.source,self.target,self.manifest)
    def test_plan_is_read_only(self):
        before=set(self.target.rglob('*'));result=u.plan(self.source,self.target,self.manifest)
        self.assertEqual(result['from_version'],'2026.10.24-r17');self.assertEqual(before,set(self.target.rglob('*')))
    def test_upgrade_preserves_owner_data_and_settings(self):
        self.assertTrue(self.apply()['verified'])
        self.assertEqual((self.target/'Agent/config.json').read_text(),'{"owner":"preserve"}')
        self.assertEqual((self.target/'Private/Users/test/Vault/blob.enc').read_text(),'opaque-owner-content')
        self.assertEqual(u.version(self.target),self.manifest['version'])
        self.assertFalse((self.target/u.PENDING).exists())
    def test_repeat_is_idempotent(self):
        self.apply();self.assertEqual(self.apply()['changed'],0)
    def test_downgrade_refused(self):
        self.put(self.target,u.STAMP,"RELEASE_VERSION='2026.11.01-Portable-r45'")
        with self.assertRaisesRegex(u.UpdateError,'Downgrade'):self.apply()
    def test_cross_stream_same_day_requires_evidence(self):
        self.put(self.target,u.STAMP,"RELEASE_VERSION='2026.10.25-Other-r99'")
        with self.assertRaisesRegex(u.UpdateError,'release streams'):self.apply()
    def test_reviewed_cross_stream_works(self):
        self.put(self.target,u.STAMP,"RELEASE_VERSION='2026.10.25-Aoostar-r43'")
        self.assertTrue(self.apply()['verified'])
    def test_unversioned_legacy_fingerprint(self):
        (self.target/u.STAMP).unlink()
        with self.assertRaisesRegex(u.UpdateError,'Unidentified legacy'):self.apply()
        self.manifest['legacy_fingerprints']=[{'version':'reviewed-legacy-r14','files':{'Agent/profile_workspace.py':u.sha(self.target/'Agent/profile_workspace.py')}}]
        self.assertEqual(self.apply()['from_version'],'reviewed-legacy-r14')
    def test_pre_account_release_refused(self):
        self.put(self.target,u.STAMP,"RELEASE_VERSION='2026.09.01-r2'")
        with self.assertRaisesRegex(u.UpdateError,'account migration'):self.apply()
    def test_payload_tampering_writes_nothing(self):
        self.put(self.source,'Agent/new.py','# tampered')
        with self.assertRaisesRegex(u.UpdateError,'checksum'):self.apply()
        self.assertEqual(u.version(self.target),'2026.10.24-r17')
    def test_unknown_draft_baseline_refused(self):
        self.manifest['files'][0]['expected_before']=['0'*64]
        with self.assertRaisesRegex(u.UpdateError,'baseline'):self.apply()
    def test_paths_reject_private_traversal_aliases(self):
        for name in ['../Agent/a.py','Private/a','Data/a','Agent/.runtime/a','Cache/a','a:stream','CON/a','a./b','HomeAssistant/state/a']:
            with self.subTest(name=name),self.assertRaises(u.UpdateError):u.public(name)
    def test_duplicate_destinations_refused(self):
        self.manifest['files'].append(dict(self.manifest['files'][0]))
        with self.assertRaisesRegex(u.UpdateError,'Duplicate'):self.apply()
    def test_linked_public_file_refused(self):
        p=self.target/'Agent/new.py';os.link(self.target/'Agent/config.json',p)
        with self.assertRaisesRegex(u.UpdateError,'Linked'):self.apply()
    def test_cancel_rolls_back(self):
        stop=threading.Event();stop.set()
        with self.assertRaisesRegex(u.UpdateError,'cancelled'):u.apply(self.source,self.target,self.manifest,stop)
        self.assertEqual(u.version(self.target),'2026.10.24-r17');self.assertFalse((self.target/u.PENDING).exists())
    def test_mid_write_failure_restores_every_original(self):
        original=u.copy_atomic
        def fail(source,p,*args):
            if p==self.target/'Agent/new.py':raise OSError('fixture failure')
            return original(source,p,*args)
        with patch.object(u,'copy_atomic',fail),self.assertRaises(OSError):self.apply()
        self.assertEqual((self.target/u.BOOT).read_text(),'# old bootstrap\n')
        self.assertEqual(u.version(self.target),'2026.10.24-r17');self.assertFalse((self.target/u.PENDING).exists())
    def test_interrupted_journal_blocks_retry_then_recovers(self):
        real_restore=u.restore
        with patch.object(u,'restore',side_effect=RuntimeError('simulated power loss')):
            stop=threading.Event()
            def progress(*a):stop.set()
            with self.assertRaises(RuntimeError):u.apply(self.source,self.target,self.manifest,stop,progress)
        self.assertTrue((self.target/u.PENDING).exists())
        with self.assertRaisesRegex(u.UpdateError,'interrupted'):self.apply()
        real_restore(self.target,u.read_json(self.target/u.PENDING))
        self.assertEqual((self.target/u.BOOT).read_text(),'# old bootstrap\n')
    def test_recovery_preserves_changed_file_and_pending_marker(self):
        with patch.object(u,'restore',side_effect=RuntimeError('power loss')):
            stop=threading.Event()
            def progress(*a):stop.set()
            with self.assertRaises(RuntimeError):u.apply(self.source,self.target,self.manifest,stop,progress)
        self.put(self.target,u.BOOT,'user changed during interruption')
        with self.assertRaisesRegex(u.UpdateError,'Recovery conflict'):u.restore(self.target,u.read_json(self.target/u.PENDING))
        self.assertTrue((self.target/u.PENDING).exists())
    def test_wrong_edition_refused(self):
        self.put(self.target,'PortableAI_Master_Instructions_v45.txt','PORTALAI ACADEMIC INSTRUCTIONS')
        with self.assertRaisesRegex(u.UpdateError,'Edition'):self.apply()
    def test_platform_receipt_mismatch_refused(self):
        self.put(self.target,u.RECEIPT,json.dumps({'platform':'Mac','edition':'Full'}))
        with self.assertRaisesRegex(u.UpdateError,'platform'):self.apply()
    def test_busy_guard_prevents_writes(self):
        with patch.object(u,'closed_guard',side_effect=u.UpdateError('close PortalAI')),self.assertRaises(u.UpdateError):self.apply()
        self.assertFalse((self.target/'Maintenance/Updates').exists())
    def test_staging_inside_target_refused(self):
        with self.assertRaisesRegex(u.UpdateError,'outside'):u.plan(self.target,self.target,self.manifest)

if __name__=='__main__':unittest.main()
