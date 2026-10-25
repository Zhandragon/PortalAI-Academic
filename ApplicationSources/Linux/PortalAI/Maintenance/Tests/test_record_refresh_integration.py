"""Real persistence pages under slow I/O, and encrypted dormant-record checks."""
import threading
import time
import unittest
from unittest.mock import patch

import test_persistence_readability_tk as ui
import test_lazy_missions as lazy
from test_settings_surfaces_tk import LIGHT
from record_refresh_fixture import settle_records
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings
from mission_runner import Missions
from mission_schedule import Schedules
from mission_catalog import MissionCatalog
from mission_monitor import armed_status
from mission_supervisor import arm


class PageRefreshTests(unittest.TestCase):
    setUp=ui.PersistenceReadabilityTests.setUp
    tearDown=ui.PersistenceReadabilityTests.tearDown

    def test_mission_catalogue_is_read_once_off_tk_and_hidden_page_stops(self):
        store=Missions(self.root);catalog=MissionCatalog(self.root)
        for n in range(12):
            record=store.create('Synthetic task '+str(n));catalog.mark_origin(record['id'])
        self.sheet=show_mission_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        main=threading.get_ident();calls=[];gate=threading.Event();original=MissionCatalog.rows
        def slow(instance,*args,**kwargs):
            self.assertNotEqual(threading.get_ident(),main)
            calls.append(args);gate.wait(4)
            return original(instance,*args,**kwargs)
        with patch.object(MissionCatalog,'rows',slow):
            self.sheet.refresh_records()
            try:
                start=time.monotonic();turns=0
                while time.monotonic()-start<.35:self.app.update();turns+=1;time.sleep(.01)
                self.assertGreater(turns,10);self.assertEqual(calls,[('All records',)])
                gate.set();settle_records(self.app)
                self.assertEqual(len(self.sheet.mission_tree.get_children()),12)
                self.sheet.pack_forget();self.app.update();count=len(calls)
                end=time.monotonic()+1.8
                while time.monotonic()<end:self.app.update();time.sleep(.01)
                self.assertEqual(len(calls),count)
            finally:gate.set()

    def test_schedule_list_and_selected_detail_never_load_on_tk(self):
        store=Schedules(self.root);s=store.create('Synthetic recurring work')
        original_list=Schedules.list;original_load=Schedules.load;main=threading.get_ident()
        def listed(instance,*args,**kwargs):
            self.assertNotEqual(threading.get_ident(),main)
            time.sleep(.12);return original_list(instance,*args,**kwargs)
        def loaded(instance,*args,**kwargs):
            self.assertNotEqual(threading.get_ident(),main)
            time.sleep(.12);return original_load(instance,*args,**kwargs)
        with patch.object(Schedules,'list',listed),patch.object(Schedules,'load',loaded):
            self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
            self.sheet.schedule_tree.selection_set(s['id']);settle_records(self.app)
            self.assertEqual(self.sheet.schedule_toggle.cget('text'),'Enable')
            self.assertEqual(self.sheet.run_viewer.identity,s['id'])

    def test_new_selection_disables_previous_schedule_controls_while_loading(self):
        store=Schedules(self.root)
        first=store.create('First schedule');second=store.create('Second schedule')
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        self.sheet.schedule_tree.selection_set(first['id']);settle_records(self.app)
        gate=threading.Event();original=Schedules.load
        def held(instance,mid):
            if mid==second['id']:gate.wait(3)
            return original(instance,mid)
        with patch.object(Schedules,'load',held):
            try:
                self.sheet.schedule_tree.selection_set(second['id']);self.app.update()
                self.assertEqual(str(self.sheet.schedule_toggle.cget('state')),'disabled')
                self.assertEqual(str(self.sheet.recovery_toggle.cget('state')),'disabled')
                self.assertEqual(str(self.sheet.record_classification.button.cget('state')),'disabled')
            finally:gate.set()
            settle_records(self.app)
        self.assertEqual(self.sheet.run_viewer.identity,second['id'])
        self.assertEqual(str(self.sheet.schedule_toggle.cget('state')),'normal')


class EncryptedMonitorTests(unittest.TestCase):
    setUp=lazy.LazyMissionTests.setUp
    tearDown=lazy.LazyMissionTests.tearDown
    records=lazy.LazyMissionTests.records
    reopen=lazy.LazyMissionTests.reopen
    assert_dormant=lazy.LazyMissionTests.assert_dormant

    def test_monitor_does_not_restore_unarmed_history(self):
        _,_,records,s=self.records();missions,_=self.reopen()
        with patch.object(Missions,'list',side_effect=AssertionError('Full list forbidden')):
            self.assertEqual(armed_status(missions),[])
        self.assert_dormant(records,s)

    def test_monitor_reads_only_armed_root_and_stop_clears_count(self):
        missions,_,records,s=self.records();arm(self.root,records[0]['id']);missions,_=self.reopen()
        self.assertEqual(armed_status(missions),[records[0]['id']])
        self.assert_dormant(records[1:],s)
        (missions.base/'supervisor.stop').write_text('stop')
        self.assertEqual(armed_status(missions),[])

    def test_index_opens_do_not_request_hydration_but_still_reject_stale_login(self):
        _,_,records,s=self.records();missions,_=self.reopen()
        import profile_hydration
        original=profile_hydration.materialize;requests=[]
        def record(root,relative,*args,**kwargs):
            requests.append(relative);return original(root,relative,*args,**kwargs)
        with patch.object(profile_hydration,'materialize',record):
            self.assertEqual(len(missions.summaries()),3)
        self.assertFalse(any(str(p).startswith('Data/MissionIndex/') for p in requests))
        self.assert_dormant(records,s)
        self.reopen()
        from profile_paths import ProfileLocked
        with self.assertRaises(ProfileLocked):missions.summaries()


if __name__=='__main__':unittest.main()
