"""Local rejection cannot become an external-effect receipt or block correction."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import native_chat as chat
from test_chat_handoff import panel

class Runtime(SimpleNamespace):
    preflight=chat.ToolRuntime.preflight
    execute=chat.ToolRuntime.execute

def call(number,name,args):
    return ('','',[{'id':'call_'+str(number),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}])

class PreflightTests(unittest.TestCase):
    def fixture(self):
        p=panel();p.settings['tool_step_limit']=10
        p.tool_runtime=Runtime(root=p.root,_account_role=Mock(),_execute=Mock(return_value='{"success":true}'))
        return p

    def test_same_edit_runs_after_assessment_then_real_duplicate_is_blocked(self):
        p=self.fixture();edit={'command':'edit','arguments':['source.jpg','Add a small object']}
        assessment={'understanding':'sufficient','reference_scope':'appearance','fidelity':'An illustrative edit',
            'components':['subject','object'],'relationships':['object beside subject'],'uncertainties':[],
            'rationale':'The inspected subject and object establish the requested appearance.',
            'staged':False,'staging_reason':'One local edit.'}
        responses=[call(1,'media_tool',edit),call(2,'media_plan',{'action':'assess','assessment':assessment}),
                   call(3,'media_tool',edit),call(4,'media_tool',edit),('Done','',[])]
        with patch.object(p,'stream_completion',side_effect=responses):p.agent_worker('test')
        p.tool_runtime._execute.assert_called_once_with('media_tool',edit)
        rows=[r for r in p.session['messages'] if r['role']=='tool']
        self.assertFalse(rows[0]['execution']['dispatched'])
        self.assertFalse(rows[0]['execution']['effectful'])
        self.assertTrue(rows[2]['execution']['dispatched'])
        self.assertIn('NOT executed again',rows[3]['content'])

    def test_invalid_web_arguments_never_create_dispatch_receipts(self):
        p=self.fixture();bad={'action':'download','arguments':{'json':{'url':'https://example.org/image.jpg'}}}
        good={'action':'download','arguments':{'url':'https://example.org/image.jpg'}}
        responses=[call(1,'web',bad),call(2,'web',good),('Done','',[])]
        with patch.object(p,'stream_completion',side_effect=responses):p.agent_worker('test')
        p.tool_runtime._execute.assert_called_once_with('web',good)
        rows=[r for r in p.session['messages'] if r['role']=='tool']
        for row in rows[:1]:
            self.assertIn('Missing web argument',row['content'])
            self.assertFalse(row['execution']['dispatched'])
            self.assertFalse(row['execution']['effectful'])

    def test_corrective_schema_requires_fields_without_mutating_shared_definition(self):
        from web_tool_api import TOOL,corrective_tool
        tool=corrective_tool('download');schema=tool['function']['parameters']
        self.assertEqual(schema['properties']['action']['enum'],['download'])
        self.assertEqual(schema['properties']['arguments']['required'],['url'])
        self.assertEqual(schema['required'],['action','arguments'])
        self.assertNotIn('required',TOOL['function']['parameters']['properties']['arguments'])
        self.assertEqual(corrective_tool('fill')['function']['parameters']['properties']['arguments']['required'],['page','value'])
        self.assertIsNone(corrective_tool('unknown'))

    def test_corrective_schema_applies_to_one_request_and_then_restores_tools(self):
        p=self.fixture();bad={'action':'download','arguments':{'purpose':'reference'}}
        good={'action':'download','arguments':{'url':'https://example.org/image.jpg'}}
        responses=iter([call(1,'web',bad),call(2,'web',good),('Done','',[])])
        observed=[]
        def complete(*args,**kwargs):
            repair=getattr(p,'_web_argument_repair',None)
            observed.append(repair)
            if repair is not None:
                with patch('chat_tool_menu.request_menu',return_value=[{'function':{'name':'web'}},{'function':{'name':'media_plan'}}]):
                    menu=chat._request_tools(p)
                self.assertIs(menu[0],repair)
                self.assertEqual(menu[1]['function']['name'],'media_plan')
            return next(responses)
        with patch.object(p,'stream_completion',side_effect=complete):p.agent_worker('test')
        self.assertIsNone(observed[0]);self.assertIsNotNone(observed[1]);self.assertIsNone(observed[2])
        self.assertIsNone(p._web_argument_repair)
        p.tool_runtime._execute.assert_called_once_with('web',good)

    def test_repeated_invalid_arguments_stop_after_one_schema_correction(self):
        p=self.fixture();bad={'action':'download','arguments':{'purpose':'reference'}}
        with patch.object(p,'stream_completion',side_effect=[call(1,'web',bad),call(2,'web',bad)]) as complete:
            p.agent_worker('test')
        self.assertEqual(complete.call_count,2)
        p.tool_runtime._execute.assert_not_called()
        self.assertTrue(p.session['messages'][-1]['incomplete'])
        self.assertIn('schema-guided correction',p.session['messages'][-1]['content'])
        self.assertIsNone(p._web_argument_repair)

    def test_dispatched_timeout_still_prevents_automatic_duplicate(self):
        p=self.fixture();args={'action':'download','arguments':{'url':'https://example.org/image.jpg'}}
        p.tool_runtime._execute.side_effect=TimeoutError('Outcome uncertain')
        with patch.object(p,'stream_completion',side_effect=[call(1,'web',args),call(2,'web',args),('Unable to verify','',[])]):
            p.agent_worker('test')
        p.tool_runtime._execute.assert_called_once()
        rows=[r for r in p.session['messages'] if r['role']=='tool']
        self.assertTrue(rows[0]['execution']['dispatched'])
        self.assertEqual(rows[0]['execution']['outcome'],'uncertain')
        self.assertIn('NOT executed again',rows[1]['content'])

if __name__=='__main__':unittest.main()
