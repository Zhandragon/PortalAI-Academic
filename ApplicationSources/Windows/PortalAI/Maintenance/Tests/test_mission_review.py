"""Review guidance reaches planning without changing budgets, effects or epochs."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_runner import Missions, MissionContextError
from mission_context import build_messages
from mission_schedule import Schedules, epoch

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.store=Missions(self.root)
    def mission(self,pending=None):
        m=self.store.create('Inspect the source report','observe',12)
        m.update(status='needs_review',error='Report format was unexpected',pending_action=pending)
        self.store.save(m);return m
    def test_replan_receives_current_guidance_and_original_problem(self):
        m=self.mission();before=(m['mode'],m['max_steps'],m['steps'],m['objective'])
        result=self.store.review(m['id'],'The report is CSV. Inspect the first row.',expected_updated_at=m['updated_at'])
        self.assertEqual(result['status'],'queued')
        self.assertEqual((result['mode'],result['max_steps'],result['steps'],result['objective']),before)
        def unavailable(*args):raise OSError('No server; use conservative count')
        messages=build_messages(self.store,result,'Planner',[], '',8192,api=unavailable)
        context=json.loads(messages[1]['content'])
        self.assertEqual(context['review_instructions'],result['review_instructions'])
        self.assertEqual(context['reviewed_problem']['reported_error'],'Report format was unexpected')
        with patch.object(self.store,'execute',wraps=self.store.execute) as execute:
            self.store.run(m['id'],model=lambda saved:{'action':'complete','text':saved['review_instructions']})
            self.assertEqual(execute.call_count,1)
    def test_unresolved_effect_keeps_pending_error_stop_and_budget(self):
        action={'action':'note','text':'Unknown outcome'};m=self.mission(action);self.store.stop(m['id'])
        result=self.store.review(m['id'],'Check the existing output before doing anything else.')
        self.assertEqual(result['pending_action'],action);self.assertEqual(result['steps'],0)
        self.assertEqual(result['status'],'needs_review');self.assertTrue(self.store.stopped(result))
        self.assertEqual(result['error'],m['error'])
        with patch.object(self.store,'execute') as execute:self.store.run(m['id']);execute.assert_not_called()
    def test_skip_and_retry_preserve_review_evidence(self):
        for resolution in ('skip','retry'):
            action={'action':'note','text':resolution};m=self.mission(action)
            result=self.store.review(m['id'],'Use the corrected input.',resolution)
            self.assertIsNone(result['pending_action']);self.assertEqual(result['steps'],int(resolution=='skip'))
            self.assertEqual(result['review_history'][-1]['pending_action'],action)
            self.assertEqual(result['review_history'][-1]['resolution'],resolution)
            self.assertEqual(result['review_history'][-1]['previous_error'],m['error'])
    def test_stop_after_review_and_during_save_stays_authoritative(self):
        m=self.mission();original=self.store.save
        def stop_during_save(value):
            self.store.stop(value['id']);original(value)
        with patch.object(self.store,'save',side_effect=stop_during_save):result=self.store.review(m['id'],'Correct the date.')
        self.assertTrue(self.store.stopped(result))
        with patch.object(self.store,'execute') as execute:
            self.assertEqual(self.store.run(m['id'])['status'],'paused');execute.assert_not_called()
    def test_scheduled_review_does_not_enable_or_change_future_runs(self):
        schedules=Schedules(self.root);s=schedules.create('Repeat original task',first_run_at=0)
        schedules.enable(s['id']);schedules.tick();s=schedules.load(s['id']);m=self.store.load(s['active_run'])
        m.update(status='needs_review',error='Needs input');self.store.save(m);schedules.tick()
        previous_epoch=epoch(self.root)
        result=self.store.review(m['id'],'Use CSV for this occurrence.')
        self.assertEqual(result['status'],'queued');self.assertEqual(epoch(self.root),previous_epoch)
        self.assertFalse(schedules.enabled(schedules.load(s['id'])))
        self.assertEqual(schedules.load(s['id'])['objective'],'Repeat original task')
        schedules.enable(s['id']);self.assertTrue(schedules.enabled(schedules.load(s['id'])))
        self.assertEqual(schedules.load(s['id'])['active_run'],m['id'])
    def test_saved_guidance_survives_compaction_and_revisions(self):
        m=self.mission();m['history']=[{'action':{'action':'note','text':'noise'*1000},'result':'log'*3000} for _ in range(20)];self.store.save(m)
        first=self.store.review(m['id'],'First guidance')
        first.update(status='needs_review',error='Second problem');self.store.save(first)
        result=self.store.review(m['id'],'Current guidance')
        self.assertEqual([x['instructions'] for x in result['review_history']],['First guidance','Current guidance'])
        def api(*args):raise OSError('Offline')
        context=json.loads(build_messages(self.store,result,'Planner',[],'',8192,api=api)[1]['content'])
        self.assertTrue(context['context_compacted']);self.assertEqual(context['review_instructions'],'Current guidance')
        self.assertEqual(len(self.store.load(m['id'])['history']),20)
        result['review_instructions']='x'*8000
        with self.assertRaises(MissionContextError):build_messages(self.store,result,'Planner',[],'',2048,api=api)
    def test_invalid_stale_active_and_locked_updates_leave_original(self):
        m=self.mission();p=self.store.folder(m['id'])/'mission.json';before=p.read_bytes()
        for text,resolution in [('',None),('x'*8001,None),('Valid','invented')]:
            with self.assertRaises(ValueError):self.store.review(m['id'],text,resolution)
            self.assertEqual(p.read_bytes(),before)
        with self.assertRaises(ValueError):self.store.review(m['id'],'Valid',expected_updated_at=0)
        with self.store.lock(m['id']):
            with self.assertRaises(OSError):self.store.review(m['id'],'Valid')
        self.assertEqual(p.read_bytes(),before)
        for state in ('running','queued','waiting','complete','budget_exhausted'):
            m['status']=state;self.store.save(m)
            with self.assertRaises(ValueError):self.store.review(m['id'],'Valid')
    def test_save_failure_does_not_clear_stop_or_pending(self):
        m=self.mission({'action':'note','text':'Pending'});self.store.stop(m['id'])
        with patch.object(self.store,'save',side_effect=OSError('Full disk')):
            with self.assertRaises(OSError):self.store.review(m['id'],'Correct input','skip')
        current=self.store.load(m['id']);self.assertTrue(self.store.stopped(current))
        self.assertEqual(current['pending_action'],m['pending_action']);self.assertNotIn('review_instructions',current)

if __name__=='__main__':unittest.main()
