"""Missing dates must persist without rewriting execution or deletion evidence."""
import json
import time
import unittest
from unittest.mock import patch

import test_mission_catalog as fixtures
from mission_catalog import MissionCatalog
from mission_schedule import Schedules
from profile_paths import ProfileLocked
from record_dates import RecordDates, timestamp


class RecordDateTests(unittest.TestCase):
    setUp = fixtures.MissionCatalogTests.setUp
    stopped = fixtures.MissionCatalogTests.stopped

    def test_missing_creation_fills_once_and_keeps_deleted_checkpoint_hidden(self):
        m = self.stopped()
        path = self.store.folder(m['id']) / 'mission.json'
        m.pop('created_at'); m['updated_at'] = 1000000000
        path.write_text(json.dumps(m))
        self.catalog.delete(m['id'])
        before = path.read_bytes()
        dates = RecordDates(self.root, 'missions', store=self.store)
        first = dates.info(m)
        self.assertAlmostEqual(first['updated_at'], time.time(), delta=5)
        self.assertEqual(first['created_at'], first['updated_at'])
        self.assertTrue(first['created_fallback'])
        self.assertIn('unknown', first['note'])
        metadata = dates.path(m['id']).read_bytes()
        with patch('record_dates.time.time', return_value=time.time()+86400):
            self.assertEqual(RecordDates(self.root, 'missions').info(m), first)
        self.assertEqual(dates.path(m['id']).read_bytes(), metadata)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.catalog.rows('Deleted (recoverable)')), 1)

    def test_schedule_missing_updated_preserves_known_creation_and_all_run_fields(self):
        schedules = Schedules(self.root)
        s = schedules.create('Synthetic dates')
        s.pop('updated_at')
        schedules.path(s['id']).write_text(json.dumps(s))
        before = schedules.path(s['id']).read_bytes()
        dates = RecordDates(self.root, 'schedules', store=schedules.store)
        info = dates.info(s)
        self.assertEqual(info['created_at'], s['created_at'])
        self.assertFalse(info['created_fallback'])
        self.assertTrue(info['updated_fallback'])
        self.assertEqual(schedules.path(s['id']).read_bytes(), before)
        self.assertEqual(dates.info(s), info)
        self.assertNotEqual(dates.path(s['id']), RecordDates(self.root, 'missions').path(s['id']))

    def test_valid_dates_do_not_write_and_invalid_dates_are_not_sort_keys(self):
        m = self.store.create('Valid dates')
        dates = RecordDates(self.root, 'missions')
        self.assertEqual(dates.info(m)['updated_at'], m['updated_at'])
        self.assertFalse(dates.base.exists())
        for invalid in (None, '', 'yesterday', True, 0, -1, float('inf'), float('nan'), 1e100):
            self.assertIsNone(timestamp(invalid))
        m['created_at'] = 'unknown'
        info = dates.info(m)
        self.assertTrue(info['created_fallback'])
        # A later real run update supersedes the presentation correction.
        m['updated_at'] = info['updated_at'] + 60
        self.assertEqual(dates.info(m)['updated_at'], m['updated_at'])

    def test_corrupt_metadata_and_unreadable_records_preserved(self):
        m = self.store.create('Synthetic corrupt metadata'); m.pop('created_at')
        dates = RecordDates(self.root, 'missions')
        path = dates.path(m['id']); path.parent.mkdir(parents=True)
        path.write_text('broken')
        info = dates.info(m)
        self.assertIsNone(info['created_at'])
        self.assertIn('original files preserved', info['note'])
        self.assertEqual(path.read_text(), 'broken')
        bad = {'id': '0'*32, 'error': 'Unreadable file'}
        self.assertIsNone(dates.info(bad)['updated_at'])
        self.assertFalse(dates.path(bad['id']).exists())

    def test_stale_profile_refuses_metadata_write(self):
        m = self.store.create('Profile fence'); m.pop('created_at')
        dates = RecordDates(self.root, 'missions')
        with patch('mission_catalog.capture', return_value=('different', 'login')):
            with self.assertRaises(ProfileLocked): dates.info(m)
        self.assertFalse(dates.base.exists())


if __name__ == '__main__': unittest.main()
