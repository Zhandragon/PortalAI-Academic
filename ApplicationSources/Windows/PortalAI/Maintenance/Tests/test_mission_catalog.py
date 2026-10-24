"""Reversible mission-list deletion never removes checkpoints or changes execution."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
from mission_runner import Missions, process_lock
from mission_catalog import MissionCatalog, VIEWS, LEGACY_TEST_PREFIXES
from mission_supervisor import arm, disarm, read_policy
from mission_schedule import Schedules
from profile_paths import ProfileLocked, UID_ENV, EPOCH_ENV


class MissionCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='Portal mission catalogue ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'Agent').mkdir()
        (self.root / 'Agent/hardware_profiles.json').write_text(json.dumps({'storage': {
            'minimum_free_gib': 0, 'minimum_free_fraction': 0, 'output_reserve_gib': 0}}))
        env = patch.dict(os.environ, {}, clear=False); env.start(); self.addCleanup(env.stop)
        os.environ.pop(UID_ENV, None); os.environ.pop(EPOCH_ENV, None)
        self.store = Missions(self.root)
        self.catalog = MissionCatalog(self.root, store=self.store)

    def stopped(self, objective='A user task', **kwargs):
        row = self.store.create(objective, **kwargs)
        disarm(self.root, row['id'])
        return self.store.load(row['id'])

    def test_default_user_view_excludes_unknown_and_groups_legacy_diagnostics(self):
        ordinary = self.store.create('My weekly research')
        legacy = self.store.create('Stop lifecycle test: do not execute any model actions')
        user = self.store.create('Test my business plan')
        self.catalog.mark_origin(user['id'])
        validation = self.store.create('Explicit synthetic regression')
        self.catalog.mark_origin(validation['id'], 'validation', 'Tools/smoke_fixture.py')
        before = {row['id']: (self.store.folder(row['id'])/'mission.json').read_bytes()
                  for row in (ordinary, legacy, user, validation)}
        self.assertEqual(VIEWS[0], 'User missions only')
        rows = self.catalog.rows(VIEWS[0])
        self.assertEqual({row['mission']['id'] for row in rows}, {user['id']})
        rows = self.catalog.rows('User & unclassified')
        self.assertEqual({row['mission']['id'] for row in rows}, {ordinary['id'], legacy['id'], user['id']})
        origins = {row['mission']['id']: row['origin'] for row in rows}
        self.assertEqual(origins[legacy['id']]['label'], 'Legacy diagnostic')
        self.assertFalse(origins[legacy['id']]['confirmed'])
        self.assertEqual({row['mission']['id'] for row in self.catalog.rows('Diagnostics')},
                         {legacy['id'], validation['id']})
        self.assertEqual(self.catalog.rows('Validation tests'), self.catalog.rows('Diagnostics'))
        self.assertEqual(len(self.catalog.rows('All records')), 4)
        self.assertEqual(before, {mid: (self.store.folder(mid)/'mission.json').read_bytes() for mid in before})

    def test_known_legacy_self_tests_are_diagnostics_but_explicit_user_origin_wins(self):
        diagnostics = [self.store.create(prefix + ' fixture') for prefix in LEGACY_TEST_PREFIXES]
        user = self.store.create(LEGACY_TEST_PREFIXES[0] + ' requested by the user')
        self.catalog.mark_origin(user['id'])
        self.store.create('An ambiguous older mission')
        self.assertEqual({row['mission']['id'] for row in self.catalog.rows('Diagnostics')},
                         {row['id'] for row in diagnostics})
        self.assertEqual({row['mission']['id'] for row in self.catalog.rows(VIEWS[0])}, {user['id']})

    def test_user_origin_is_inherited_by_child_work_without_including_unknown_roots(self):
        parent = self.store.create('User project')
        child = self.store.create('Project subtask', parent=parent['id'], depth=1)
        parent['children'] = [child['id']]; self.store.save(parent)
        self.catalog.mark_origin(parent['id'])
        self.store.create('Unclassified root')
        self.assertEqual({row['mission']['id'] for row in self.catalog.rows(VIEWS[0])},
                         {parent['id'], child['id']})

    def test_delete_and_restore_keep_every_original_byte_and_never_arm(self):
        row = self.stopped()
        folder = self.store.folder(row['id'])
        (folder / 'notes.txt').write_text('User evidence')
        before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        result = self.catalog.delete(row['id'])
        self.assertEqual(result['files_erased'], 0)
        self.assertEqual(self.catalog.rows(VIEWS[0]), [])
        self.assertEqual(len(self.catalog.rows('Deleted (recoverable)')), 1)
        self.assertEqual(len(self.catalog.rows('All records')), 1)
        self.catalog.restore(row['id'])
        self.assertEqual(len(self.catalog.rows('User & unclassified')), 1)
        after = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(read_policy(self.store, row['id'])['enabled'])
        self.assertEqual(self.store.load(row['id'])['status'], 'paused')

    def test_active_and_still_armed_missions_are_refused(self):
        active = self.store.create('Waiting user work')
        with self.assertRaisesRegex(ValueError, 'Stop'): self.catalog.delete(active['id'])
        arm(self.root, active['id'])
        changed = self.store.load(active['id']); changed['status'] = 'paused'; self.store.save(changed)
        with self.assertRaisesRegex(ValueError, 'armed'): self.catalog.delete(active['id'])
        self.assertFalse(self.catalog.path(active['id']).exists())

    def test_changed_checkpoint_or_arming_makes_deleted_record_visible_again(self):
        row = self.stopped()
        self.catalog.delete(row['id'])
        changed = self.store.load(row['id']); changed['objective'] += ' updated'; self.store.save(changed)
        self.assertEqual(len(self.catalog.rows('User & unclassified')), 1)
        self.assertEqual(self.catalog.rows('Deleted (recoverable)'), [])
        self.catalog.delete(row['id'])
        from runtime_policy import atomic_json
        atomic_json(self.store.folder(row['id'])/'run-policy.json', {'enabled': True, 'mode': 'observe'})
        self.assertEqual(len(self.catalog.rows('User & unclassified')), 1)

    def test_stopped_family_is_deleted_together_and_child_path_stays_valid(self):
        parent = self.store.create('Parent')
        child = self.store.create('Child', parent=parent['id'], depth=1)
        parent['children'] = [child['id']]; self.store.save(parent)
        disarm(self.root, parent['id'])
        with self.assertRaisesRegex(ValueError, 'top-level'): self.catalog.delete(child['id'])
        result = self.catalog.delete(parent['id'])
        self.assertEqual(result['records_retained'], 2)
        self.assertEqual(len(self.catalog.rows('Deleted (recoverable)')), 2)
        self.assertEqual(self.store.load(child['id'])['parent'], parent['id'])
        self.catalog.restore(parent['id'])
        self.assertEqual(len(self.catalog.rows('User & unclassified')), 2)

    def test_explicit_validation_origin_is_inherited_by_children(self):
        parent = self.store.create('Explicit fixture')
        child = self.store.create('Fixture child', parent=parent['id'], depth=1)
        parent['children'] = [child['id']]; self.store.save(parent)
        self.catalog.mark_origin(parent['id'], 'validation', 'Tools/fixture.py')
        self.assertEqual(self.catalog.rows(VIEWS[0]), [])
        self.assertEqual(len(self.catalog.rows('Diagnostics')), 2)

    def test_schedule_link_and_external_reference_are_refused(self):
        schedule = Schedules(self.root).create('Scheduled user work')
        row = self.stopped(schedule_id=schedule['id'])
        with self.assertRaisesRegex(ValueError, 'Scheduled'): self.catalog.delete(row['id'])
        ordinary = self.stopped('Independent')
        other = self.store.create('Broken external reference')
        other['children'] = [ordinary['id']]; self.store.save(other)
        with self.assertRaisesRegex(ValueError, 'outside'): self.catalog.delete(ordinary['id'])

    def test_pending_action_evidence_is_retained_without_review_or_replay(self):
        row = self.store.create('Uncertain operation')
        row['pending_action'] = {'action': 'shell', 'command': 'recorded effect'}
        self.store.save(row); disarm(self.root, row['id'])
        before = (self.store.folder(row['id'])/'mission.json').read_bytes()
        self.catalog.delete(row['id']); self.catalog.restore(row['id'])
        self.assertEqual((self.store.folder(row['id'])/'mission.json').read_bytes(), before)
        self.assertEqual(self.store.load(row['id'])['status'], 'needs_review')

    def test_live_worker_lock_refuses_deletion(self):
        row = self.stopped()
        with process_lock(self.store.base/'execution.lock'):
            with self.assertRaises(OSError): self.catalog.delete(row['id'])
        self.assertFalse(self.catalog.path(row['id']).exists())

    def test_catalogue_and_paths_fail_closed_after_login_changes(self):
        private = self.root/'Private'; private.mkdir()
        marker = private/'active-session.json'
        active = {'user_id': 'a'*32, 'epoch': 'b'*32, 'state': 'open'}
        marker.write_text(json.dumps(active))
        with patch.dict(os.environ, {UID_ENV: 'a'*32, EPOCH_ENV: 'b'*32}):
            store = Missions(self.root); catalog = MissionCatalog(self.root, store=store)
            row = store.create('Private user task'); disarm(self.root, row['id'])
            catalog.mark_origin(row['id'])
            self.assertTrue(catalog.path(row['id']).is_relative_to(private/'Users'/('a'*32)/'Workspace'))
            marker.write_text(json.dumps({**active, 'state': 'closed'}))
            for call in (lambda: catalog.rows(), lambda: catalog.delete(row['id']), lambda: catalog.restore(row['id'])):
                with self.assertRaises(ProfileLocked): call()

    def test_revocation_after_catalogue_publication_removes_only_own_new_record(self):
        row = self.stopped()
        original = os.replace
        def replace(source, target):
            original(source, target)
            self.catalog.context = ('revoked', 'login')
        with patch('mission_catalog.os.replace', side_effect=replace):
            with self.assertRaises(ProfileLocked): self.catalog.mark_origin(row['id'])
        self.assertFalse((self.catalog.base/(row['id']+'.json')).exists())
        self.assertTrue((self.store.folder(row['id'])/'mission.json').exists())

    def test_invalid_catalogue_is_visible_and_never_repaired_implicitly(self):
        row = self.stopped()
        path = self.catalog.path(row['id']); path.parent.mkdir(parents=True)
        path.write_text('{invalid')
        self.assertEqual(self.catalog.rows(VIEWS[0]), [])
        self.assertEqual(len(self.catalog.rows('User & unclassified')), 1)
        self.assertTrue(self.catalog.errors)
        with self.assertRaises(ValueError): self.catalog.delete(row['id'])
        self.assertEqual(path.read_text(), '{invalid')


if __name__ == '__main__': unittest.main()
