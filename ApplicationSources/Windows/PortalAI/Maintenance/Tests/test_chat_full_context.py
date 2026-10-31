"""Real default prompts/catalog across effort levels, with no private account I/O."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import native_chat as chat
import runtime_policy
from chat_budgets import generation_options
from chat_tool_menu import compact_menu, Selection, load
from test_chat_context_budget import panel


def full_panel(level='fast', capacity=8192):
    p=panel();p.root=ROOT
    p._tool_selection=Selection();p.cancel_event=threading.Event()
    p.session['title']='Hands-free context regression'
    p.session['messages']=[{'role':'user','content':'Hey, Nice. Are you there?','attachments':[]}]
    p.store.custom_instructions=lambda:''
    p.memory.config={'enabled':True};p.memory.chat_included=lambda *_:True;p.memory.chat_recall_enabled=lambda *_:True
    p.system_prompt=lambda:chat.NativeChat.system_prompt(p)
    p._runtime_session_context=lambda text:chat.NativeChat._runtime_session_context(p,text)
    p._runtime_context_limit=lambda:capacity
    p.tool_runtime=SimpleNamespace(root=ROOT,_account_role=lambda:'admin',_working_directory=lambda:ROOT/'User Folder')
    p.effort=SimpleNamespace(active_options=generation_options(level,capacity),active_tools_profile=level,
                             active_plan={'context_tokens':capacity})
    from coding_stall import CodingStall
    from task_progress import TaskProgress
    p._coding_stall=CodingStall(False)
    p._task_progress=TaskProgress(True,p.session['messages'][0]['content'])
    return p


class FullContextTests(unittest.TestCase):
    def setUp(self):
        policy=patch.object(runtime_policy,'load_effective_policy',return_value=runtime_policy.load_policy(ROOT))
        policy.start();self.addCleanup(policy.stop)

    def test_greeting_and_followup_fit_all_efforts_and_supported_full_contexts(self):
        for capacity in (4096,8192,16384,32768):
            for level in ('fast','balanced','deep'):
                for handsfree in (False,True):
                    with self.subTest(capacity=capacity,level=level,handsfree=handsfree):
                        p=full_panel(level,capacity);p.settings['conversation_speak_replies']=handsfree
                        before=copy.deepcopy(p.session)
                        for turn in range(2):
                            api,total=p.api_messages();meta=p._last_context_meta
                            self.assertLessEqual(total,meta['budget'])
                            self.assertGreaterEqual(p._admitted_output_tokens(),256)
                            self.assertIn('Your conversational name is Nice',api[0]['content'])
                            self.assertEqual(meta['safety_tokens'],500)
                            self.assertGreater(meta['checkpoint_reserve'],0)
                            if turn==0:
                                self.assertEqual(p.session,before)
                                p.session['messages'] += [{'role':'assistant','content':"Yes, I'm here. How can I help?"},
                                                          {'role':'user','content':'Can you hear me in hands-free mode?'}]
                            else:
                                self.assertEqual([r['content'] for r in api if r['role']=='user'],
                                                 [r['content'] for r in p.session['messages'] if r['role']=='user'])

    def test_tools_keep_every_schema_and_permission_scope_without_mutation(self):
        original=copy.deepcopy(chat.TOOLS)
        compact=compact_menu(chat.TOOLS)
        self.assertEqual(len(compact),len(original))
        for before,after in zip(original,compact):
            self.assertEqual({k:v for k,v in before['function'].items() if k!='description'},
                             {k:v for k,v in after['function'].items() if k!='description'})
        self.assertEqual(chat.TOOLS,original)
        self.assertLess(chat.estimate_tokens(compact),chat.estimate_tokens(original)*.75)
        for scope in ('all','coding','maintenance'):
            p=full_panel();p._request_tool_scope=scope
            names={r['function']['name'] for r in chat._scoped_tools(p)}
            self.assertIn('chat_history',names);self.assertIn('read_file',names)
            self.assertEqual('generate_image' in names,scope=='all')
        unknown={'type':'function','function':{'name':'future_tool','description':'Keep this contract','parameters':{}}}
        self.assertEqual(compact_menu([unknown]),[unknown])

    def test_custom_instructions_and_academic_policy_survive(self):
        p=full_panel();p.store.custom_instructions=lambda:'Use metric units and retain source citations.'
        api,_=p.api_messages();prompt=api[0]['content']
        self.assertIn(p.store.custom_instructions(),prompt)
        if (ROOT/'Agent/academic_policy.py').exists():
            from academic_policy import instruction_suffix
            self.assertIn(instruction_suffix(ROOT).strip(),prompt)

    def test_oversize_current_turn_is_not_silently_cut(self):
        p=full_panel();p.session['messages'][0]['content']='User instructions '*4000
        original=copy.deepcopy(p.session)
        with patch.object(p,'_api_row') as serialize:
            with self.assertRaisesRegex(RuntimeError,'current request does not fit'):p.api_messages()
        serialize.assert_not_called();self.assertEqual(original,p.session)

    def test_small_hardware_contexts_never_overstate_server_capacity(self):
        for capacity in (512,1024,2048):
            for level in ('fast','balanced','deep'):
                p=full_panel(level,capacity)
                p.settings['context_budget_tokens']=32768
                budget,actual=p._effective_context_budget()
                self.assertEqual(actual,capacity);self.assertLess(budget,capacity)
                with self.assertRaisesRegex(RuntimeError,'current request does not fit'):p.api_messages()

    def test_props_accept_small_runtime_not_large_training_context(self):
        for capacity in (512,1024,2048,4096,8192):
            self.assertEqual(chat.context_limit_from_props({'default_generation_settings':{'n_ctx':capacity},'n_ctx_train':131072}),capacity)
        self.assertIsNone(chat.context_limit_from_props({'n_ctx_train':131072}))

    def test_unknown_context_cannot_invent_a_larger_window(self):
        p=full_panel();p._runtime_context_limit=lambda:None
        for configured in (0,32768):
            p.settings['context_budget_tokens']=configured
            with self.assertRaisesRegex(RuntimeError,'Cannot verify'):p.api_messages()

    def test_next_request_refreshes_context_after_effort_switch_or_voice_reload(self):
        p=full_panel('deep',32768)
        p._runtime_context_limit=lambda:chat.NativeChat._runtime_context_limit(p)
        p._model_context_limit=32768;p._model_context_checked=chat.time.time()
        with patch.object(chat,'model_props',return_value={'default_generation_settings':{'n_ctx':8192}}) as props:
            p.api_messages();self.assertEqual(p._last_context_meta['model_limit'],8192)
            self.assertEqual(props.call_count,1)
            props.return_value={'default_generation_settings':{'n_ctx':2048}}
            with self.assertRaises(RuntimeError):p.api_messages()
            self.assertEqual(p._last_context_meta['model_limit'],2048)
            self.assertEqual(props.call_count,2)

    def test_plain_chat_has_small_index_and_only_core_tools(self):
        p=full_panel();api,_=p.api_messages()
        self.assertEqual({r['function']['name'] for r in chat._request_tools(p)},
                         {'tool_help','chat_history','chat_checkpoint'})
        self.assertLess(p._last_context_meta['estimated_input'],2600)
        self.assertNotIn('dialogue-video',api[0]['content'])
        self.assertNotIn('Current media defaults:',api[0]['content'])

    def test_selected_tools_receive_full_original_schemas_and_only_relevant_workflows(self):
        p=full_panel()
        for names,required,absent in [(['read_file','edit_file'],'File workflow:','Media workflow:'),
                                     (['media_tool'],'Media workflow:','File workflow:'),
                                     (['web'],'Research workflow:','Media workflow:'),
                                     (['computer'],'Desktop workflow:','Research workflow:')]:
            load(p,{'tools':names},chat._scoped_tools(p))
            api,_=p.api_messages();menu=chat._request_tools(p)
            self.assertEqual({r['function']['name'] for r in menu},set(names)|{'tool_help',*('chat_history','chat_checkpoint')})
            self.assertIn(required,api[0]['content']);self.assertNotIn(absent,api[0]['content'])
            for name in names:
                self.assertEqual(next(r for r in menu if r['function']['name']==name),
                                 next(r for r in chat.TOOLS if r['function']['name']==name))

    def test_selection_does_not_leak_to_new_turn_or_chat(self):
        p=full_panel();load(p,{'tools':['web']},chat._scoped_tools(p))
        p.session['messages'].append({'role':'user','content':'Hello again'})
        self.assertNotIn('web',{r['function']['name'] for r in chat._request_tools(p)})
        load(p,{'tools':['web']},chat._scoped_tools(p));p.session['id']='different-chat'
        self.assertNotIn('web',{r['function']['name'] for r in chat._request_tools(p)})

    def test_scope_bad_names_cancel_and_login_cannot_load_tools(self):
        p=full_panel();p._request_tool_scope='coding'
        for args in ({'tools':['web']},{'tools':['read_file','read_file']},{'tools':['__import__']},
                     {'tools':['read_file'],'permission':'admin'},{'tools':['read_file']*5}):
            with self.assertRaises(ValueError):load(p,args,chat._scoped_tools(p))
        p.cancel_event.set()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):load(p,{'tools':['read_file']},chat._scoped_tools(p))
        p.cancel_event.clear()
        with patch.object(p,'_check_login',side_effect=PermissionError('revoked')):
            with self.assertRaises(PermissionError):load(p,{'tools':['read_file']},chat._scoped_tools(p))
        self.assertEqual(p._tool_selection.names,())

    def test_too_large_load_retains_previous_selection_and_history(self):
        p=full_panel();load(p,{'tools':['read_file']},chat._scoped_tools(p))
        before=copy.deepcopy(p.session);p._runtime_context_limit=lambda:2048
        with self.assertRaisesRegex(ValueError,'Select fewer tools'):load(p,{'tools':['media_tool','web','computer','science']},chat._scoped_tools(p))
        self.assertEqual(p._tool_selection.names,('read_file',));self.assertEqual(before,p.session)

    def test_post_admission_stop_rolls_selection_back(self):
        p=full_panel();real=p._context_plan
        def stop():
            result=real();p.cancel_event.set();return result
        with patch.object(p,'_context_plan',side_effect=stop):
            with self.assertRaises(RuntimeError):load(p,{'tools':['read_file']},chat._scoped_tools(p))
        self.assertEqual(p._tool_selection.names,())


if __name__=='__main__':unittest.main()
