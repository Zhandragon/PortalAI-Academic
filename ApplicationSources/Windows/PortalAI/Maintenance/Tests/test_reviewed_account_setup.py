"""Reviewed first-account migration; synthetic data and credentials only."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent'), str(ROOT/'Tools')]
import local_accounts
import reviewed_account_setup as setup
from profile_migration import legacy_inventory
from profile_workspace import ProfileWorkspace

PASSWORD = 'Synthetic first-account password'


class ReviewedSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'PortalAI Windows'
        (self.root/'Agent').mkdir(parents=True)
        config = json.loads((ROOT/'Agent/hardware_profiles.json').read_text())
        # Tiny disposable fixtures do not need the production model/output reserve.
        config['storage'] = {'minimum_free_gib': 1, 'minimum_free_fraction': 0,
                             'output_reserve_gib': 0}
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps(config))
        self.data = self.root/'Data/Chat/Sessions/one.json'
        self.data.parent.mkdir(parents=True)
        self.data.write_text('{"synthetic": "preserve my conversation"}')
        self.content = self.data.read_bytes()
        self.backend = local_accounts.LocalAccounts(self.root)
        self.addCleanup(self.backend.logout)
        factor = patch.object(local_accounts, '_KDF_N', 1024)
        factor.start(); self.addCleanup(factor.stop)
        # The fixture has no processes; production keeps the real ownership check.
        for name in ('stop_owned', 'verify_stopped'):
            check = patch('profile_shutdown.'+name, return_value={'stopped': True})
            check.start(); self.addCleanup(check.stop)
        self.ticket = self.root/setup.TICKET

    def authorize(self):
        backup = self.root/'Maintenance/Patches/fixture'
        backup.mkdir(parents=True)
        source = self.root/'Agent/fixture.py'
        source.write_text('# Synthetic source verification fixture\n')
        blob = source.read_bytes()
        with zipfile.ZipFile(backup/'source.zip', 'w') as archive:
            archive.writestr('Agent/fixture.py', blob)
        manifest = {'files': [{'path': 'Agent/fixture.py', 'bytes': len(blob),
                              'sha256': hashlib.sha256(blob).hexdigest()}],
                    'archive_sha256': hashlib.sha256((backup/'source.zip').read_bytes()).hexdigest()}
        (backup/'manifest.json').write_text(json.dumps(manifest))
        shutil.copytree(backup, self.base/'recovery/source')
        (self.base/'recovery/private').mkdir()
        ticket = {'kind': setup.KIND, 'phase': 'ready',
                  'inventory_digest': self.backend.private_inventory()['digest'],
                  'source_backup': 'Maintenance/Patches/fixture',
                  'source_mirror': 'recovery/source', 'recovery_directory': 'recovery/private'}
        self.ticket.parent.mkdir(parents=True, exist_ok=True)
        self.ticket.write_text(json.dumps(ticket))
        return ticket

    def test_unreviewed_legacy_copy_stays_in_recovery(self):
        self.assertEqual(self.backend.status()['state'], 'recovery_required')
        self.assertIsNone(setup.inspect(self.root, self.backend))
        with self.assertRaises(RuntimeError):
            setup.provision_reviewed(self.root, 'Owner', PASSWORD)
        self.assertFalse(self.backend.registry_path.exists())

    def test_changed_inventory_cannot_create_an_account(self):
        self.authorize(); self.data.write_text('changed after review')
        self.assertIsNone(setup.inspect(self.root, self.backend))
        with self.assertRaises(RuntimeError):
            setup.provision_reviewed(self.root, 'Owner', PASSWORD)
        self.assertFalse(self.backend.registry_path.exists())

    def test_existing_account_cannot_be_replaced_by_ready_ticket(self):
        self.authorize()
        session = self.backend.initialize_existing('Existing', PASSWORD,
                          self.backend.private_inventory()['digest'])
        self.backend.logout(session)
        before = self.backend.registry_path.read_bytes()
        self.assertIsNone(setup.inspect(self.root, self.backend))
        with self.assertRaises(RuntimeError):
            setup.provision_reviewed(self.root, 'Replacement', PASSWORD)
        self.assertEqual(before, self.backend.registry_path.read_bytes())

    def test_changed_source_refuses_setup_before_initialization(self):
        self.authorize(); (self.root/'Agent/fixture.py').write_text('# changed')
        with self.assertRaises(RuntimeError):
            setup.provision_reviewed(self.root, 'Owner', PASSWORD)
        self.assertFalse(self.backend.registry_path.exists())
        self.assertEqual(self.data.read_bytes(), self.content)

    def test_recovery_path_cannot_escape_drive_parent(self):
        ticket = self.authorize(); ticket['recovery_directory'] = '../outside'
        self.ticket.write_text(json.dumps(ticket))
        self.assertIsNone(setup.inspect(self.root, self.backend))

    def test_setup_preserves_data_and_verifies_encrypted_external_backup(self):
        self.authorize()
        self.assertEqual(setup.inspect(self.root, self.backend)['mode'], 'create')
        result = setup.provision_reviewed(self.root, 'Owner', PASSWORD)
        self.assertTrue(result['verified']); self.assertTrue(result['external_recovery_verified'])
        self.assertTrue(Path(result['external_recovery_path']).is_file())
        self.assertEqual(json.loads(self.ticket.read_text())['phase'], 'complete')
        self.assertIsNone(setup.inspect(self.root, self.backend))
        self.assertFalse(self.data.exists())
        self.assertEqual(legacy_inventory(self.root)['files'], [])
        session = self.backend.login('Owner', PASSWORD)
        store = ProfileWorkspace(self.root, session)
        store.restore()
        self.assertEqual((store.workspace/'Data/Chat/Sessions/one.json').read_bytes(), self.content)
        store.seal(writers_stopped=True); self.backend.logout(session)

    def test_failed_external_backup_retains_original_and_authenticated_resume_works(self):
        self.authorize()
        with patch('account_reset_ui.export_reset_plan', side_effect=OSError('fixture backup failure')):
            with self.assertRaises(OSError):
                setup.provision_reviewed(self.root, 'Owner', PASSWORD)
        self.assertEqual(self.data.read_bytes(), self.content)
        self.assertEqual(setup.inspect(self.root, self.backend), {'mode': 'resume', 'owner': 'Owner'})
        with self.assertRaises(Exception):
            setup.provision_reviewed(self.root, 'Owner', 'incorrect fixture password')
        self.assertEqual(self.data.read_bytes(), self.content)
        result = setup.provision_reviewed(self.root, 'Owner', PASSWORD)
        self.assertTrue(result['verified']); self.assertTrue(result['external_recovery_verified'])
        self.assertEqual(legacy_inventory(self.root)['files'], [])

    def test_setup_form_opens_preserved_profile_and_populates_accounts(self):
        import tkinter as tk
        from tkinter import ttk
        import account_ui
        from profile_runtime import ProfileRuntime
        from test_account_presentation_tk import LIGHT
        from tk_fixture_cleanup import finish_tk_fixture
        self.authorize()
        app = tk.Tk(); app.geometry('1000x780-10000-10000')
        controller = account_ui.AccountController(self.root, self.backend)
        runtime = ProfileRuntime(self.root, self.backend,
                                 quiesce=lambda *_: {'stopped': True})
        errors = []
        app.report_callback_exception = lambda *error: errors.append(error)
        def submit():
            dialog = app._portalai_account_dialogs[-1]
            entries = [w for w in dialog.body.winfo_children()
                       if isinstance(w, (tk.Entry, ttk.Entry))]
            for entry, value in zip(entries, ('Owner', PASSWORD, PASSWORD)):
                entry.insert(0, value)
            next(b for b, _ in dialog.buttons
                 if b.cget('text') == 'Create initial administrator').invoke()
        def timeout():
            errors.append('Synthetic setup timed out')
            for dialog in app._portalai_account_dialogs:
                dialog.busy = False; dialog.close()
        app.after(100, submit)
        timer = app.after(15000, timeout)
        session = None
        try:
            session = account_ui.show_login(app, controller, LIGHT,
                                            prepare_session=runtime.prepare)
            app.after_cancel(timer)
            self.assertEqual(errors, [])
            self.assertIsNotNone(session)
            store = ProfileWorkspace(self.root, session)
            self.assertEqual((store.workspace/'Data/Chat/Sessions/one.json').read_bytes(), self.content)
            page = account_ui.show_accounts(app, controller, session, LIGHT, page=True)
            labels = [button.cget('text') for button, _ in page.buttons]
            self.assertIn('Create standard account…', labels)
            self.assertEqual({u['username'] for u in self.backend.list_users(session)}, {'Owner', 'Guest'})
        finally:
            controller.jobs.close(); controller.jobs.wait(5)
            if session is not None: runtime.close(session, writers_stopped=True)
            elif runtime._process_lock is not None:
                runtime._process_lock.__exit__(None, None, None)
            finish_tk_fixture(app, jobs=(controller.jobs,))


if __name__ == '__main__':
    unittest.main()
