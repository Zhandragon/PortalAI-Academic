"""Review summaries must be short, actionable, scoped and faithful to evidence."""
import copy
import unittest
from mission_review_issue import SECTION, summary
from mission_monitor import render


class ReviewIssueTests(unittest.TestCase):
    def mission(self, error, action=None, **kwargs):
        return dict(id='a'*32, status='needs_review', error=error, pending_action=action, **kwargs)

    def test_restricted_read_explains_problem_and_path_without_raw_traceback(self):
        m=self.mission('PermissionError: Mission file reads are restricted to source/documentation',
                       {'action':'read_file','path':r'workspace\business\GROWTH_PLAYBOOK.md'})
        before=copy.deepcopy(m);text=summary(m)
        self.assertIn('even in Full mode',text);self.assertIn('What to do:',text)
        self.assertIn('GROWTH_PLAYBOOK.md',text);self.assertNotIn('PermissionError',text)
        self.assertEqual(m,before);self.assertLess(len(text),850)

    def test_uncertain_effect_never_recommends_unconditional_retry(self):
        m=self.mission('FileNotFoundError: partial result',{'action':'shell','command':'secret command'})
        text=summary(m)
        self.assertIn('may already have taken effect',text)
        self.assertIn('only after checking',text);self.assertNotIn('secret command',text)

    def test_known_planning_context_and_resource_problems(self):
        cases=[('Repeated identical actions without progress','same action'),
               ('MissionContextError: Mission context exceeds its input budget','available context'),
               ('ValueError: Model did not return an action object','usable next action'),
               ('RuntimeError: out of memory','enough memory'),
               ('ConnectionRefusedError: connection refused','could not be reached'),
               ('Child missions need attention: '+'b'*32,'subtask')]
        for error,expected in cases:
            with self.subTest(error=error):self.assertIn(expected,summary(self.mission(error)))

    def test_unknown_error_remains_attributed_and_bounded(self):
        text=summary(self.mission('Traceback (most recent call last):\n'+('details\n'*800)+'StrangeError: '+'x'*1000))
        self.assertIn('Reported problem: StrangeError',text)
        self.assertNotIn('Traceback',text);self.assertLess(len(text),950)

    def test_healthy_execution_and_uncommitted_preview_do_not_become_review_issues(self):
        m={'id':'a'*32,'status':'running','pending_action':{'action':'shell'}}
        text=summary(m,{'preview':'PermissionError: fix by granting access'})
        self.assertIn('No review is currently requested',text);self.assertNotIn('granting access',text)
        self.assertIn('No review issue is recorded',summary({'id':'a'*32,'status':'complete'}))

    def test_latest_saved_issue_survives_review_and_is_labeled_historical(self):
        m={'id':'a'*32,'status':'queued','review_history':[
            {'at':1,'previous_error':'Old irrelevant fault'},
            {'at':20,'previous_error':'Repeated identical actions without progress'}]}
        text=summary(m,{'events':[{'at':10,'phase':'needs_review','message':'Old activity failure'}]})
        self.assertIn('Reviewed earlier',text);self.assertIn('same action',text)
        self.assertIn('No review is currently requested',text);self.assertNotIn('Old irrelevant',text)

    def test_schedule_links_current_mission_but_not_an_older_run(self):
        s={'id':'b'*32,'status':'needs_review','active_run':'a'*32,'error':'Active run requires review/resume'}
        m=self.mission('Repeated identical actions without progress')
        text=summary(m,schedule=s);self.assertIn('In Missions:',text);self.assertIn('Enable the schedule',text)
        self.assertIn('Mission ID: '+'a'*32,text)
        old={'id':'c'*32,'status':'complete'}
        text=summary(old,schedule=s,historical=True)
        self.assertIn('No review issue is recorded',text);self.assertNotIn('Enable',text)

    def test_schedule_setup_failure_and_reviewed_but_disabled_run(self):
        s={'id':'b'*32,'status':'needs_review','error':'FileNotFoundError: model file'}
        self.assertIn('could not prepare',summary(schedule=s))
        m={'id':'a'*32,'status':'queued'};s['active_run']=m['id']
        self.assertIn('still paused',summary(m,schedule=s))
        self.assertIn('Enable when ready',summary(m,schedule=s))

    def test_agent_pause_and_budget_have_different_next_steps(self):
        m=self.mission('Need the sales report',agent_pause=True);m['status']='paused'
        self.assertIn('Nice paused',summary(m));self.assertIn('sales report',summary(m))
        m.update(status='budget_exhausted',agent_pause=False)
        self.assertIn('cannot be resumed',summary(m))
        self.assertIn('remaining heartbeat',summary(m,schedule={'autonomous_recovery':True}))

    def test_overview_leads_with_issue_before_long_objective(self):
        m=self.mission('Repeated identical actions without progress');m['objective']='OBJECTIVE_SENTINEL'*1000
        text=render('Overview',m,{},{});self.assertLess(text.index('What to do:'),text.index('OBJECTIVE_SENTINEL'))
        self.assertNotIn('OBJECTIVE_SENTINEL',render(SECTION,m,{},{}))

    def test_paused_pending_effect_still_requires_review_and_removed_schedule_requires_restore(self):
        m=self.mission('Interrupted action',{'action':'web','operation':'submit'});m['status']='paused'
        s={'id':'b'*32,'status':'removed','active_run':m['id']}
        text=summary(m,schedule=s)
        self.assertIn('Needs review',text);self.assertIn('Restore it before enabling',text)
        self.assertIn('only after checking',text)


if __name__=='__main__':unittest.main()
