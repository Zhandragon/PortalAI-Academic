"""Encrypted disposable records exercise listing, execution selection and Stop."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_profile_hydration as fixtures
from mission_runner import Missions
from mission_schedule import Schedules
from mission_catalog import MissionCatalog
from mission_supervisor import Supervisor, arm, pause_all, read_policy
from profile_workspace import ProfileWorkspace
from profile_paths import ProfileLocked
from runtime_policy import atomic_json


class LazyMissionTests(unittest.TestCase):
    setUp = fixtures.HydrationTests.setUp
    tearDown = fixtures.HydrationTests.tearDown

    def reopen(self):
        self.runtime.close(self.session, writers_stopped=True)
        self.session = self.backend.login(fixtures.OWNER)
        self.runtime.prepare(self.session)
        self.store = ProfileWorkspace(self.root, self.session)
        return Missions(self.root), Schedules(self.root)

    def records(self):
        atomic_json(self.root/'Agent/hardware_profiles.json', {'storage':
            {'minimum_free_gib': 1, 'minimum_free_fraction': .01, 'output_reserve_gib': 0}})
        missions = Missions(self.root); schedules = Schedules(self.root)
        with patch('mission_runner.require_space'), patch('mission_schedule.require_space'):
            records = [missions.create('Synthetic work '+str(i)) for i in range(3)]
            for m in records:
                m['history'] = [{'action': {'action': 'note'}, 'result': 'x' * (1024*1024)}]
                missions.save(m)
            s = schedules.create('Synthetic hourly work', source_mission=records[0]['id'])
            s['history'] = [{'mission': records[0]['id'], 'evidence': 'x' * (1024*1024)}]
            schedules.save(s)
        return missions, schedules, records, s

    def assert_dormant(self, records, schedule):
        base=self.store.workspace/'Data/Missions'
        self.assertTrue(all(not (base/m['id']/'mission.json').exists() for m in records))
        self.assertTrue(all(not (base/m['id']/'mission.previous.json').exists() for m in records))
        self.assertFalse((base/'Schedules'/(schedule['id']+'.json')).exists())

    def test_login_lists_and_search_do_not_decrypt_histories(self):
        _,_,records,s = self.records(); missions,schedules=self.reopen()
        self.assert_dormant(records,s)
        rows=MissionCatalog(self.root).rows('All records', 'Synthetic')
        self.assertEqual(len(rows),3)
        self.assertTrue(all('history' not in row['mission'] for row in rows))
        self.assertEqual(schedules.list(summaries=True)[0]['id'],s['id'])
        self.assertFalse(schedules.any_enabled())
        self.assertEqual(Supervisor(self.root).selection(),([],[]))
        self.assert_dormant(records,s)

    def test_explicit_selection_restores_only_requested_checkpoint(self):
        _,_,records,s=self.records(); missions,schedules=self.reopen()
        m=missions.load(records[1]['id'])
        self.assertEqual(len(m['history'][0]['result']),1024*1024)
        self.assert_dormant([records[0],records[2]],s)
        self.assertFalse((missions.base/records[1]['id']/'mission.previous.json').exists())

    def test_armed_mission_loads_its_children_only(self):
        missions,_,records,s=self.records()
        with patch('mission_runner.require_space'):
            child=missions.create('Child',parent=records[0]['id'],depth=1)
        records[0]['children']=[child['id']];missions.save(records[0]);arm(self.root,records[0]['id'])
        missions,schedules=self.reopen()
        roots,candidates=Supervisor(self.root).selection()
        self.assertEqual(roots,[records[0]['id']])
        self.assertEqual({m['id'] for _,m in candidates},{records[0]['id'],child['id']})
        self.assert_dormant(records[1:],s)

    def test_stale_index_repairs_only_its_record(self):
        missions,_,records,s=self.records()
        records[1]['objective']='Changed outside index'
        atomic_json(missions.base/records[1]['id']/'mission.json',records[1])
        missions,_=self.reopen()
        self.assertEqual(next(m for m in missions.summaries() if m['id']==records[1]['id'])['objective'],'Changed outside index')
        self.assert_dormant([records[0],records[2]],s)

    def test_pending_schedule_occurrence_is_not_duplicated(self):
        missions,schedules,records,s=self.records()
        records[0]['schedule_id']=s['id'];missions.save(records[0])
        s['active_run']=records[0]['id'];s['runs_started']=1;schedules.save(s)
        schedules.enable(s['id'])
        missions,schedules=self.reopen()
        with patch('mission_schedule.require_space'):
            schedules.tick()
        self.assertEqual(schedules.load(s['id'])['runs_started'],1)
        self.assertEqual(schedules.load(s['id'])['active_run'],records[0]['id'])
        self.assertEqual(len(missions.summaries()),3)
        self.assertTrue(all(not (missions.base/m['id']/'mission.json').exists() for m in records[1:]))

    def test_deletion_classification_stays_visible_without_history(self):
        missions,_,records,s=self.records()
        records[1]['status']='complete';missions.save(records[1])
        catalog=MissionCatalog(self.root)
        with patch('mission_catalog.require_space'):
            catalog.classify(records[1]['id'],'user');catalog.delete(records[1]['id'])
        _,_=self.reopen()
        rows=MissionCatalog(self.root).rows('Deleted (recoverable)')
        self.assertEqual([row['mission']['id'] for row in rows],[records[1]['id']])
        self.assert_dormant(records,s)

    def test_summaries_cannot_replace_checkpoints_or_schedule(self):
        _,_,records,s=self.records();missions,schedules=self.reopen()
        with self.assertRaises(ValueError):missions.save(missions.summaries()[0])
        with self.assertRaises(ValueError):schedules.save(schedules.list(summaries=True)[0])
        self.assert_dormant(records,s)

    def test_dormant_id_collision_refused_and_full_list_is_explicit(self):
        _,_,records,s=self.records();missions,_=self.reopen()
        with patch('mission_runner.require_space'),self.assertRaises(ValueError):
            missions.create('Replacement',mission_id=records[0]['id'])
        self.assertEqual(missions.load(records[0]['id'])['objective'],records[0]['objective'])
        self.assertEqual(len(missions.list()),3)

    def test_index_write_failure_does_not_lose_completed_checkpoint(self):
        missions,_,records,_=self.records()
        with patch('mission_index.atomic_json',side_effect=OSError('Index write interrupted')):
            records[0]['status']='complete';missions.save(records[0])
        missions,_=self.reopen()
        self.assertEqual(next(m for m in missions.summaries() if m['id']==records[0]['id'])['status'],'complete')

    def test_stale_profile_cannot_read_index(self):
        missions,_,records,s=self.records();self.reopen()
        with self.assertRaises(ProfileLocked):missions.summaries()

    def test_stop_fences_armed_work_and_schedules(self):
        missions,schedules,records,s=self.records();arm(self.root,records[0]['id']);schedules.enable(s['id'])
        missions,schedules=self.reopen();pause_all(self.root)
        self.assertFalse(read_policy(missions,records[0]['id'])['enabled'])
        self.assertTrue(missions.stopped(missions.load(records[0]['id'])))
        self.assertFalse(schedules.any_enabled())

if __name__=='__main__':unittest.main()
