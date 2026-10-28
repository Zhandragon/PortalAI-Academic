"""A rejected unchanged history prefix must not consume every next tool cycle."""
import copy
import queue
import threading
import unittest
from unittest.mock import Mock
from test_chat_context_budget import panel


def fixture():
    p=panel();p.cancel_event=threading.Event();p.ev=queue.Queue();p._check_login=Mock()
    p.session['messages']=[{'role':'user','content':'Keep the original goal.'},
        {'role':'assistant','content':'Observed earlier work.'},
        {'role':'user','content':'Continue the same task.'}]
    p._compact_working_turn=Mock(return_value=False)
    p._summary_transcript=lambda rows: '\n'.join(m['content'] for m in rows)
    def plan():
        return {'state':p.session['context_state'],'estimated_full':9000,'budget':8192,'soft':7000,
            'groups':[{'start':0,'end':2,'cost':2000,'messages':p.session['messages'][:2]},
                      {'start':2,'end':len(p.session['messages']),'cost':3000,'messages':p.session['messages'][2:]}]}
    p._context_plan=plan
    return p


class CompactionRetryTests(unittest.TestCase):
    def test_rejected_prefix_is_not_retried_as_current_turn_grows(self):
        p=fixture();before=copy.deepcopy(p.session['context_state'])
        p._single_completion=Mock(side_effect=RuntimeError('tool markup'))
        for i in range(6):
            p.session['messages'].append({'role':'assistant','content':'new current progress '+str(i)})
            self.assertFalse(p._compact_context_once())
        p._single_completion.assert_called_once()
        self.assertEqual(p.session['context_state'],before)
        p.store.save_session.assert_not_called()
        self.assertEqual(len(p._failed_history_summary_input),64)

    def test_changed_old_evidence_retries_and_success_clears_failure(self):
        p=fixture();p._single_completion=Mock(side_effect=[RuntimeError('empty'), 'Goal and verified work retained.'])
        p._compact_context_once()
        p.session['messages'][1]['content']='A corrected earlier observation.'
        self.assertTrue(p._compact_context_once())
        self.assertEqual(p._single_completion.call_count,2)
        self.assertIsNone(p._failed_history_summary_input)
        self.assertEqual(p.session['context_state']['cursor'],2)
        self.assertEqual(p.session['messages'][1]['content'],'A corrected earlier observation.')

    def test_force_allows_retry_and_empty_or_expanding_results_are_not_committed(self):
        for result in ('','x'*20000):
            with self.subTest(result_size=len(result)):
                p=fixture();p._single_completion=Mock(return_value=result)
                before=copy.deepcopy(p.session)
                p._compact_context_once();p._compact_context_once()
                self.assertEqual(p._single_completion.call_count,1)
                p._compact_context_once(force=True)
                self.assertEqual(p._single_completion.call_count,2)
                self.assertEqual(p.session,before)

    def test_success_is_still_blocked_by_stop_or_revoked_login(self):
        for stopped in (True,False):
            with self.subTest(stopped=stopped):
                p=fixture();before=copy.deepcopy(p.session)
                def completion(*args,**kwargs):
                    if stopped:p.cancel_event.set()
                    else:p._check_login.side_effect=PermissionError('revoked')
                    return 'A valid short summary.'
                p._single_completion=completion
                if stopped:self.assertFalse(p._compact_context_once())
                else:
                    with self.assertRaises(PermissionError):p._compact_context_once()
                self.assertEqual(p.session,before);p.store.save_session.assert_not_called()

    def test_changed_previous_summary_or_budget_allows_new_attempt(self):
        p=fixture();p._single_completion=Mock(side_effect=RuntimeError('rejected'))
        p._compact_context_once();p._compact_context_once()
        p.session['context_state']['summary']='New saved prior facts.'
        p._compact_context_once()
        prior=p._context_plan
        p._context_plan=lambda:{**prior(),'budget':10000}
        p._compact_context_once()
        self.assertEqual(p._single_completion.call_count,3)

    def test_working_checkpoint_progress_is_not_lost_when_history_retry_skips(self):
        p=fixture();p._single_completion=Mock(side_effect=RuntimeError('rejected'))
        p._compact_context_once();p._compact_working_turn.return_value=True
        self.assertTrue(p._compact_context_once())
        p._single_completion.assert_called_once()


if __name__=='__main__':unittest.main()
