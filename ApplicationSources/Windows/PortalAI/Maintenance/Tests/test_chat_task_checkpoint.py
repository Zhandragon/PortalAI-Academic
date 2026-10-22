"""Proactive checkpoint cycles preserve tool budgets, evidence and Stop/login gates."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(Path(__file__).parent)]
import native_chat as chat
import chat_task_checkpoint as checkpoint
from profile_paths import ProfileLocked
from test_chat_reasoning_continuation import fixture,responses
from test_chat_handoff import CALL
from test_chat_working_context import fixture as context_fixture


def note_call(n=1,summary='Step checked; output ready.',next_step='Inspect the saved output.',ids=None):
    return {'id':'checkpoint_'+str(n),'type':'function','function':{'name':'chat_checkpoint','arguments':json.dumps({
        'summary':summary,'next_step':next_step,'uncertainty':'Verify quality before declaring success.','evidence_ids':ids or []})}}


class TaskCheckpointTests(unittest.TestCase):
    def test_cycles_resume_automatically_preserve_evidence_and_never_execute_checkpoint_as_external_tool(self):
        p=fixture();seen=[]
        p.tool_runtime.execute.return_value='{"success":true,"output":"Outputs/ALREADY_DONE.mp4"}'
        with patch.object(p,'stream_completion',side_effect=responses(p,[
                ('tool_calls','','',[CALL]),('tool_calls','','',[note_call(ids=[2])]),
                ('stop','Finished using ALREADY_DONE.','',[])],seen)):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session['messages'][-1]['content'],'Finished using ALREADY_DONE.')
        usage=p.session['context_state']['last_run']
        self.assertEqual(usage['calls'],1);self.assertEqual(usage['checkpoints'],1)
        record=p.session['context_state']['working_turns']['0']
        self.assertTrue(record['model_requested']);self.assertIn('ALREADY_DONE',record['evidence'])
        q=context_fixture();q.session=copy.deepcopy(p.session)
        api,_=q.api_messages()
        self.assertIn('Step checked',json.dumps(api));self.assertIn('ALREADY_DONE',json.dumps(api))
        self.assertFalse(any(event[0]=='error' for event in p.ev.queue))

    def test_checkpoint_compacts_without_calling_the_summarizer(self):
        p=fixture();seen=[]
        with patch.object(p,'_single_completion',side_effect=AssertionError('No summarizer needed')), \
             patch.object(p,'stream_completion',side_effect=responses(p,[
                ('tool_calls','','',[note_call()]),('stop','Done.','',[])],seen)):
            p.agent_worker('test')
        self.assertEqual(p.session['messages'][-1]['content'],'Done.')

    def test_checkpoint_does_not_reset_finite_tool_budget(self):
        p=fixture();p.settings['tool_call_limit']=1;seen=[]
        with patch.object(p,'stream_completion',side_effect=responses(p,[
                ('tool_calls','','',[note_call()]),('tool_calls','','',[CALL]),('stop','Done.','',[])],seen)):
            p.agent_worker('test')
        self.assertFalse(seen[1]['no_tools']);self.assertTrue(seen[2]['no_tools'])
        self.assertEqual(p.session['context_state']['last_run']['calls'],1)

    def test_checkpoint_does_not_clear_prior_action_receipts(self):
        p=fixture();seen=[];again=copy.deepcopy(CALL);again['id']='call_again'
        with patch.object(p,'stream_completion',side_effect=responses(p,[
                ('tool_calls','','',[CALL]),('tool_calls','','',[note_call()]),
                ('tool_calls','','',[again]),('stop','Done.','',[])],seen)):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertIn('NOT executed again',json.dumps(p.session))

    def test_identical_idle_checkpoint_yields_final_answer_only(self):
        p=fixture();seen=[]
        with patch.object(p,'stream_completion',side_effect=responses(p,[
                ('tool_calls','','',[note_call(1)]),('tool_calls','','',[note_call(2)]),
                ('stop','Blocked on missing input.','',[])],seen)):
            p.agent_worker('test')
        self.assertTrue(seen[2]['no_tools']);p.tool_runtime.execute.assert_not_called()
        self.assertIn('same checkpoint',json.dumps(seen[-1]['api']))

    def test_configurable_idle_limit_and_zero_count_limit(self):
        for limit in (2,0):
            p=fixture();p.settings['checkpoint_no_tool_limit']=limit;seen=[]
            rows=[('tool_calls','','',[note_call(i,summary=f'Discovery {i}.')]) for i in range(3)]
            rows.append(('stop','Finished.','',[]))
            with patch.object(p,'stream_completion',side_effect=responses(p,rows,seen)):
                p.agent_worker('test')
            self.assertEqual(seen[-1]['no_tools'],bool(limit))

    def test_only_new_tool_results_renew_idle_checkpoint_budget(self):
        cycle=checkpoint.Cycle(1);note={'summary':'a','next_step':'b'}
        self.assertFalse(cycle.checkpoint(note))
        cycle.progress('chat_history',{},'read');self.assertTrue(cycle.checkpoint({'summary':'c'}))
        cycle.progress('read_file',{'path':'x'},'new result');self.assertFalse(cycle.checkpoint(note))
        cycle.progress('read_file',{'path':'x'},'new result');self.assertTrue(cycle.checkpoint({'summary':'c'}))

    def test_mixed_batch_cannot_execute_an_action_before_checkpoint_validation(self):
        p=fixture();seen=[]
        with patch.object(p,'stream_completion',side_effect=responses(p,[('tool_calls','','',[CALL,note_call()])],seen)):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_not_called()
        self.assertTrue(any(event[0]=='error' for event in p.ev.queue))

    def test_invalid_or_invented_evidence_does_not_commit_checkpoint(self):
        p=fixture();seen=[]
        with patch.object(p,'stream_completion',side_effect=responses(p,[('tool_calls','','',[note_call(ids=[999])])],seen)):
            p.agent_worker('test')
        self.assertNotIn('working_turns',p.session['context_state'])
        p.tool_runtime.execute.assert_not_called()

    def test_stop_before_commit_does_not_reactivate(self):
        p=fixture();seen=[];original=checkpoint.commit
        def stop(*args):
            record=original(*args);p.cancel_event.set();return record
        with patch.object(checkpoint,'commit',side_effect=stop),patch.object(p,'stream_completion',side_effect=responses(p,[
                ('tool_calls','','',[note_call()])],seen)) as stream:
            p.agent_worker('test')
        stream.assert_called_once();self.assertNotIn('working_turns',p.session['context_state'])

    def test_revoked_login_before_commit_does_not_reactivate(self):
        p=fixture();seen=[];active=[True];original=checkpoint.commit
        def check():
            if not active[0]:raise ProfileLocked('Login ended')
        def revoke(*args):
            record=original(*args);active[0]=False;return record
        p._check_login=check
        with patch.object(checkpoint,'commit',side_effect=revoke),patch.object(p,'stream_completion',side_effect=responses(p,[
                ('tool_calls','','',[note_call()])],seen)) as stream:
            p.agent_worker('test')
        stream.assert_called_once();self.assertNotIn('working_turns',p.session['context_state'])
        self.assertEqual(p.store.save_session.call_count,1)

    def test_budget_guidance_is_in_admitted_request_and_reports_estimates(self):
        p=context_fixture();p.settings['tool_call_limit']=7
        p.session['context_state']['last_run']={'calls':3,'checkpoints_since_tool':1}
        api,estimate=p.api_messages();meta=p._last_context_meta
        row=next(row for row in api if 'Cycle allowance:' in row.get('content',''))
        self.assertIn(f"{meta['output_reserve']} generated tokens",row['content'])
        self.assertIn('tool calls left 4',row['content'])
        self.assertIn('checkpoints before a new tool result 3',row['content'])
        self.assertIn('No live remaining-token counter',row['content'])
        self.assertLessEqual(chat.estimate_tokens(row),280)
        self.assertLessEqual(estimate,meta['budget'])


if __name__=='__main__':unittest.main()
