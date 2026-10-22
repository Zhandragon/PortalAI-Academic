"""Long tasks, explicit budgets and follow-up evidence without a live model/account."""
import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent'), str(Path(__file__).parent)]
import chat_working_memory as working
import native_chat as chat
from test_chat_working_context import fixture
from test_chat_handoff import panel


def call(n, command=None, name='shell', args=None):
    return {'id': f'call_{n}', 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(args or {'command': command or f'action {n}'})}}


def exchange(p, n, content=None):
    c = call(n)
    p.session['messages'].extend([
        {'role':'assistant', 'content':f'Next step {n}: assemble the dialogue video.', 'tool_calls':[c]},
        {'role':'tool', 'name':'shell', 'tool_call_id':c['id'], 'content':content or json.dumps({
            'success':True, 'output_path':f'Outputs/Video/part_{n}.mp4', 'logs':'large log '*1500})}])


def assert_pairs(test, api):
    pending = set()
    for row in api:
        if row['role'] in ('user', 'assistant'):
            test.assertFalse(pending, 'Unpaired call before next turn')
        pending.update(c['id'] for c in row.get('tool_calls') or [])
        if row['role'] == 'tool':
            test.assertIn(row['tool_call_id'], pending)
            pending.remove(row['tool_call_id'])
    test.assertFalse(pending)


class RollingResumeTests(unittest.TestCase):
    def test_140_step_task_rolls_within_eight_k_context_and_keeps_exact_log(self):
        p = fixture(); p._runtime_context_limit = lambda:8192
        p.session['messages'][0]['content'] = 'Animate the edited image into a 20-second dialogue video.'
        summaries = []
        def summarize(messages, **kwargs):
            self.assertLessEqual(chat.estimate_tokens(messages)+kwargs['max_tokens']+500, 7372)
            summaries.append(messages)
            return ('Goal: produce a 20-second dialogue video. The source edit is saved as Outputs/Edited/original.png. '
                    'Scene segments are completed; assemble remaining segments, check duration and dialogue, then return final video.')
        with patch.object(p, '_single_completion', side_effect=summarize):
            for n in range(140):
                exchange(p, n)
                original = copy.deepcopy(p.session['messages'])
                p.compact_context_if_needed()
                api, estimated = p.api_messages()
                self.assertLessEqual(estimated, 7372)
                self.assertEqual(p.session['messages'], original)
                assert_pairs(self, api)
        self.assertGreater(len(summaries), 10)
        self.assertLess(len(api), 30)
        self.assertEqual(len(p.session['messages']), 281)
        p.session['messages'].append({'role':'user','content':'Continue where you left off.'})
        api, _ = p.api_messages(); text = json.dumps(api)
        self.assertIn('20-second dialogue video', text)
        self.assertIn('Outputs/Video/part_139.mp4', text)
        self.assertIn('assemble remaining segments', text)
        self.assertIn('Outputs/Edited/original.png', text)
        assert_pairs(self, api)

    def test_failed_summary_still_produces_honest_bounded_working_evidence(self):
        p = fixture()
        for n in range(20): exchange(p, n)
        original = copy.deepcopy(p.session['messages'])
        with patch.object(p, '_single_completion', side_effect=TimeoutError('unavailable')):
            self.assertTrue(p.compact_context_if_needed(force=True))
        checkpoint = p.session['context_state']['working_turns']['0']
        self.assertTrue(checkpoint['fallback'])
        self.assertIn('quoted evidence', checkpoint['summary'])
        self.assertIn('Outputs/Video/part_18.mp4', checkpoint['evidence'])
        self.assertEqual(original, p.session['messages'])
        api, _ = p.api_messages(); assert_pairs(self, api)

    def test_cancel_or_revoked_login_prevents_checkpoint_commit(self):
        for revoke in (False, True):
            p=fixture()
            for n in range(15): exchange(p,n)
            before=copy.deepcopy(p.session)
            def summarize(*args, **kwargs):
                if revoke: p._check_login=Mock(side_effect=PermissionError('revoked'))
                else: p.cancel_event.set()
                return 'Do not commit under a stale epoch.'
            with patch.object(p,'_single_completion',side_effect=summarize):
                if revoke:
                    with self.assertRaises(PermissionError):p.compact_context_if_needed(force=True)
                else:self.assertFalse(p.compact_context_if_needed(force=True))
            self.assertEqual(p.session,before)

    def test_checkpoint_invalidates_when_covered_source_changes(self):
        p=fixture()
        for n in range(15):exchange(p,n)
        with patch.object(p,'_single_completion',return_value='Old note'):
            p.compact_context_if_needed(force=True)
        self.assertIsNotNone(working.checkpoint_for(p.session,0,len(p.session['messages'])))
        p.session['messages'][2]['content']='Corrected source evidence'
        self.assertIsNone(working.checkpoint_for(p.session,0,len(p.session['messages'])))

    def test_interrupted_batch_is_not_compacted_as_complete_and_api_gets_uncertain_receipt(self):
        p=fixture()
        for n in range(15):exchange(p,n)
        p.session['messages'].extend([
            {'role':'assistant','tool_calls':[call('missing'),call('missing2')],'content':''},
            {'role':'tool','name':'shell','tool_call_id':'call_missing','content':'first finished'}])
        original=copy.deepcopy(p.session['messages'])
        with patch.object(p,'_single_completion',return_value='Completed earlier stages'):
            p.compact_context_if_needed(force=True)
        self.assertLess(p.session['context_state']['working_turns']['0']['cursor'],31)
        p.session['messages'].append({'role':'user','content':'Continue'})
        api,_=p.api_messages();assert_pairs(self,api)
        self.assertIn('may already have had effects',json.dumps(api))
        self.assertEqual(p.session['messages'][:-1],original)

    def test_explicit_budget_counts_individual_calls_and_gives_final_answer(self):
        p=panel();p.settings['tool_call_limit']=2
        p.effort=SimpleNamespace(active_plan={'max_tool_rounds':1},prepare_request=lambda event:True)
        with patch.object(p,'stream_completion',side_effect=[('', '', [call(1),call(2),call(3)]),('Two actions done; third awaits continuation.','',[])]) as stream:
            p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,2)
        self.assertEqual(stream.call_count,2)
        rows=[m for m in p.session['messages'] if m['role']=='tool']
        self.assertIn('NOT executed',rows[2]['content'])
        self.assertFalse(rows[2]['execution']['dispatched'])
        self.assertEqual(p.session['context_state']['last_run']['calls'],2)
        self.assertEqual(p.session['messages'][-1]['content'],'Two actions done; third awaits continuation.')

    def test_unlimited_runs_over_fifty_calls_and_effort_cannot_override_it(self):
        p=panel();p.settings['tool_call_limit']=0
        p.effort=SimpleNamespace(active_plan={'max_tool_rounds':4},prepare_request=lambda event:True)
        replies=[('', '', [call(i)]) for i in range(60)]+[('Finished sixty actions','',[])]
        with patch.object(p,'stream_completion',side_effect=replies):p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,60)
        self.assertEqual(p.session['messages'][-1]['content'],'Finished sixty actions')

    def test_internal_history_reads_do_not_consume_tool_budget(self):
        p=panel();p.settings['tool_call_limit']=1
        replies=[('', '', [call(i,name='chat_history',args={'action':'artifacts'})]) for i in range(5)]
        replies += [('', '', [call(6)]),('Done','',[])]
        with patch.object(p,'stream_completion',side_effect=replies):p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session['context_state']['last_run']['history_reads'],5)
        self.assertEqual(p.session['messages'][-1]['content'],'Done')

    def test_followup_reuses_returned_or_uncertain_action_without_extra_history_read(self):
        for failure in (None,TimeoutError('May have created output')):
            p=panel()
            if failure:p.tool_runtime.execute.side_effect=failure
            with patch.object(p,'stream_completion',side_effect=[('', '', [call(1,'render video')]),('Incomplete; verify rendered output.','',[])]):
                p.agent_worker('test')
            p.session['messages'].append({'role':'user','content':'Continue from where you left off'})
            with patch.object(p,'stream_completion',side_effect=[('', '', [call(2,'render video')]),('Use the saved result','',[])]):
                p.agent_worker('test')
            p.tool_runtime.execute.assert_called_once()
            result=p.session['messages'][-2]['content']
            self.assertIn('NOT executed again',result)
            self.assertIn('May have created output' if failure else 'ALREADY_DONE',result)
            # Explicit new work is not silently treated as continuation.
            p.session['messages'].append({'role':'user','content':'Render the video again with the same settings'})
            with patch.object(p,'stream_completion',side_effect=[('', '', [call(3,'render video')]),('Attempted again','',[])]):
                p.agent_worker('test')
            self.assertEqual(p.tool_runtime.execute.call_count,2)

    def test_dispatch_receipt_is_saved_before_effectful_tool_and_survives_missing_return(self):
        p=panel()
        def execute(*args):
            row=p.session['messages'][-1]
            self.assertTrue(row['execution_receipts']['call_1']['dispatched'])
            self.assertGreaterEqual(p.store.save_session.call_count,2)
            return 'Done'
        p.tool_runtime.execute.side_effect=execute
        with patch.object(p,'stream_completion',side_effect=[('', '', [call(1)]),('Done','',[])]):p.agent_worker('test')
        p.session['messages']=p.session['messages'][:2]+[{'role':'user','content':'Resume'}]
        prior=working.prior_action_results(p.session,2)
        self.assertEqual(prior[('shell',json.dumps({'command':'action 1'},sort_keys=True))],1)

    def test_setting_migration_preserves_explicit_nondefault_choice(self):
        for loaded,wanted in [({},0),({'tool_step_limit':12},0),({'tool_step_limit':30},30),({'tool_call_limit':100},100)]:
            settings=dict(loaded);working.migrate_settings(settings,loaded)
            self.assertEqual(working.tool_call_limit(settings),wanted)


if __name__=='__main__':unittest.main()
