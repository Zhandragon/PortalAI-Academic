"""Newest tool evidence stays useful without widening context admission."""
import copy
import json
import unittest
from test_chat_context_budget import panel


def add_read(p, token, chars=7000):
    name = 'call'+str(len(p.session['messages']))
    text = (token+'\n')*((chars//(len(token)+1))+1)
    result = {'path':'Agent/example.py','total_chars':len(text),'offset':0,
              'text':text,'returned_chars':len(text),'next_offset':None,'complete':True}
    p.session['messages'] += [
        {'role':'assistant','content':'','tool_calls':[{'id':name,'type':'function',
         'function':{'name':'read_file','arguments':'{"path":"Agent/example.py","offset":0,"max_chars":8000}'}}]},
        {'role':'tool','name':'read_file','tool_call_id':name,'content':json.dumps(result)}]


class RecentEvidenceTests(unittest.TestCase):
    def test_latest_code_view_is_larger_than_old_views_and_fully_budgeted(self):
        p=panel();p._request_tool_scope='maintenance';p.settings['max_output_tokens']=4096
        for i in range(5):add_read(p,'old_'+str(i))
        add_read(p,'current_code')
        before=copy.deepcopy(p.session)
        api,_=p.api_messages()
        rows=[json.loads(r['content']) for r in api if r['role']=='tool']
        self.assertGreater(len(rows[-1]['text']),2000)
        self.assertLess(len(rows[0]['text']),len(rows[-1]['text']))
        meta=p._last_context_meta
        self.assertLessEqual(meta['estimated_sent'],meta['budget'])
        self.assertGreaterEqual(p._admitted_output_tokens(),256)
        self.assertEqual(p.session,before)
        self.assertEqual(p.settings['max_output_tokens'],4096)
        self.assertEqual(rows[-1]['next_offset'],len(rows[-1]['text']))

    def test_new_user_turn_does_not_promote_old_tool_result(self):
        p=panel();add_read(p,'old')
        p.session['messages'].append({'role':'user','content':'A new question'})
        p._context_plan()
        self.assertIsNone(p._context_recent_tool_index)
        self.assertIsNone(p._context_previous_tool_index)

    def test_caller_and_callee_can_remain_visible_together_within_admission(self):
        p=panel();p._request_tool_scope='maintenance';p.settings['max_output_tokens']=4096
        for name in ('older','callee','caller'):add_read(p,name,2400)
        original=copy.deepcopy(p.session)
        p._context_plan(_tool_limit=600)
        views=[json.loads(p._tool_context(row)) for row in p.session['messages'] if row['role']=='tool']
        self.assertGreater(len(views[-2]['text']),2000)
        self.assertGreater(len(views[-1]['text']),2000)
        self.assertLess(len(views[0]['text']),1000)
        p.api_messages()
        self.assertLessEqual(p._last_context_meta['estimated_sent'],p._last_context_meta['budget'])
        self.assertEqual(p.session,original)

    def test_two_views_shrink_together_when_the_minimum_reply_would_not_fit(self):
        p=panel();p._request_tool_scope='maintenance'
        p.settings.update(context_budget_tokens=2700,max_output_tokens=2048)
        for name in ('prior','latest'):add_read(p,name)
        p.session['messages'][0]['content']='question '*180
        original=copy.deepcopy(p.session)
        try:p.api_messages()
        except RuntimeError as exc:self.assertIn('does not fit',str(exc))
        else:
            self.assertLessEqual(p._last_context_meta['estimated_sent'],2700)
            self.assertGreaterEqual(p._admitted_output_tokens(),256)
        self.assertLess(p._context_recent_tool_char_limit,4000)
        self.assertEqual(p.session,original)

    def test_current_view_respects_configured_cap(self):
        p=panel();p.settings['tool_context_max_chars']=2000;add_read(p,'code')
        p._context_plan(_tool_limit=600)
        self.assertLessEqual(len(p._tool_context(p.session['messages'][-1])),2000)

    def test_small_budget_can_shrink_latest_view_without_bypassing_minimum_reply(self):
        p=panel();p._request_tool_scope='maintenance'
        p.settings.update(context_budget_tokens=2600,max_output_tokens=2048)
        add_read(p,'source')
        # Fixed non-tool context consumes most of this deliberately small budget.
        p.session['messages'][0]['content']='question '*180
        try:
            p.api_messages()
        except RuntimeError as exc:
            self.assertIn('does not fit',str(exc))
        else:
            self.assertLessEqual(p._last_context_meta['estimated_sent'],2600)
            self.assertGreaterEqual(p._admitted_output_tokens(),256)
        self.assertLess(p._context_recent_tool_char_limit,4000)


if __name__=='__main__':unittest.main()
