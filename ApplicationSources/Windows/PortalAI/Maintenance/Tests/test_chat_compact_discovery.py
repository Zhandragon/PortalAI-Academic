"""Compact help remains usable without prerequisite retrieval or action replay."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
import native_chat as chat
import chat_evidence as evidence
from chat_discovery import recovery_context
from media_tool_api import catalog_response
from tool_contracts import DIALOGUE_VIDEO


def exchange(session, name, args, content):
    cid='call_'+str(len(session['messages']))
    session['messages'] += [
        {'role':'assistant','tool_calls':[{'id':cid,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},
        {'role':'tool','name':name,'tool_call_id':cid,'content':content}]
    return len(session['messages'])-1


class CompactDiscoveryTests(unittest.TestCase):
    def catalog(self, **kwargs):
        with patch('runtime_policy.load_effective_policy',return_value={'media':{'media_variant':'standard'}}):
            return catalog_response(ROOT, **kwargs)

    def test_targeted_catalog_is_short_and_has_complete_execution_help_first(self):
        raw=self.catalog(command='dialogue-video');row=json.loads(raw)
        self.assertLess(len(raw),2400)
        self.assertEqual(next(iter(row)),'execution_help')
        self.assertEqual(row['commands'],['dialogue-video'])
        self.assertEqual(row['execution_help'],DIALOGUE_VIDEO)
        self.assertTrue(row['execution_help_complete'])
        self.assertNotIn('replacement_needed',raw)

    def test_minimum_tool_view_preserves_entire_help_in_one_read(self):
        raw=self.catalog(command='dialogue-video')
        view=evidence.project({'name':'available_tools','content':raw},4,600)
        self.assertLessEqual(len(view),600)
        result=json.loads(view)
        self.assertEqual(result['execution_help'],DIALOGUE_VIDEO)
        self.assertTrue(result['execution_help_complete'])
        self.assertTrue(result['catalog_details_omitted'])
        self.assertNotIn('omitted; exact text',view)

    def test_full_detail_and_global_discovery_remain_available(self):
        full=json.loads(self.catalog(command='dialogue-video',detail='full'))
        summary=json.loads(self.catalog(command='dialogue-video'))
        self.assertIn('capabilities',full)
        self.assertGreater(len(json.dumps(full)),len(json.dumps(summary)))
        self.assertIn('voice-clone',json.loads(self.catalog())['commands'])
        with self.assertRaises(ValueError):self.catalog(command='dialogue-video',detail='typo')

    def test_legacy_large_catalog_history_loop_gets_current_help_without_mutation(self):
        session={'messages':[{'role':'user','content':'Make a 20-second garden video with hello spoken.'}]}
        index=exchange(session,'available_tools',{'command':'dialogue-video'},'x'*8734)
        for offset in (0,311,641,955,1296,0,311):
            exchange(session,'chat_history',{'action':'read','message_id':index,'offset':offset},'saved page')
        before=copy.deepcopy(session);note=recovery_context(session)
        self.assertIn(DIALOGUE_VIDEO,note)
        self.assertIn('7 consecutive history reads',note)
        self.assertIn('does not authorize an action or replay',note)
        self.assertEqual(session,before)

    def test_recovery_resets_on_real_progress_and_new_user_turn(self):
        session={'messages':[{'role':'user','content':'Make a video.'}]}
        for _ in range(2):exchange(session,'available_tools',{'command':'dialogue-video'},'metadata')
        self.assertTrue(recovery_context(session))
        exchange(session,'media_tool',{'command':'dialogue-video','arguments':['picture.png','Hello','--duration','20']},'{"success":true}')
        self.assertEqual(recovery_context(session),'')
        session['messages'].append({'role':'user','content':'Summarize this chat.'})
        self.assertEqual(recovery_context(session),'')

    def test_history_audits_are_not_blocked_or_rewritten(self):
        session={'messages':[{'role':'user','content':'Audit the exact catalog output.'}]}
        raw=self.catalog(command='dialogue-video',detail='full')
        index=exchange(session,'available_tools',{'command':'dialogue-video','detail':'full'},raw)
        for _ in range(7):
            result=json.loads(evidence.execute(session,{'action':'read','message_id':index,'offset':200,'limit':500}))
            self.assertEqual(result['text'],raw[200:700])

    def test_bare_search_paths_survive_as_reported_artifacts(self):
        path=r'D:\Portable\Private\Users\example\Workspace\Data\Chat\Attachments\session\garden.png'
        message={'role':'tool','name':'shell','content':path+'\n'+path}
        self.assertEqual(evidence.reported_fields(message),[('reported_path',path)])
        result=evidence.execute({'messages':[message]},{'action':'artifacts'})
        self.assertIn(path,json.loads(result)['results'][0]['reported_fields'][0])

    def test_runtime_recovery_cue_is_in_admitted_context(self):
        p=SimpleNamespace(session={'id':'fixture','messages':[{'role':'user','content':'Animate a garden.'}]},
            memory=SimpleNamespace(chat_included=lambda sid:True,config={}))
        for _ in range(2):exchange(p.session,'available_tools',{'command':'dialogue-video'},'metadata')
        context=chat.NativeChat._runtime_session_context(p)
        self.assertIn(DIALOGUE_VIDEO,context)

    def test_larger_context_no_longer_automatically_injects_full_manual(self):
        p=SimpleNamespace(root=ROOT,settings={'use_master_instructions':True},
            store=SimpleNamespace(custom_instructions=lambda:'Keep my exact requested wording.'),
            _runtime_context_limit=lambda:32768)
        with patch('runtime_policy.load_effective_policy',return_value={}):
            compact=chat.NativeChat.system_prompt(p)
            p.settings['include_full_manual']=True
            full=chat.NativeChat.system_prompt(p)
        self.assertLess(len(compact),5000)
        self.assertGreater(len(full)-len(compact),30000)
        self.assertIn('Keep my exact requested wording.',compact)
        self.assertIn(DIALOGUE_VIDEO,compact)

    def test_authorization_is_checked_before_catalog_lookup(self):
        runtime=SimpleNamespace(root=ROOT,_account_role=Mock(side_effect=PermissionError('locked')))
        with patch('media_tool_api.catalog_response') as lookup:
            with self.assertRaises(PermissionError):chat.ToolRuntime.execute(runtime,'available_tools',{'command':'dialogue-video'})
        lookup.assert_not_called()

    def test_eight_k_request_keeps_complete_usage_without_catalog_paging(self):
        from test_chat_context_budget import panel
        p=panel();p.root=ROOT;p.store.custom_instructions=lambda:''
        p.system_prompt=lambda:chat.NativeChat.system_prompt(p)
        p.memory.chat_included=lambda _sid:True;p.memory.config={}
        p._runtime_session_context=lambda memory='':chat.NativeChat._runtime_session_context(p,memory)
        p.user_api_message=lambda row:{'role':'user','content':row['content']}
        p.session['messages'][0]['content']='Animate the supplied garden picture for 20 seconds with Hello spoken.'
        raw=self.catalog(command='dialogue-video')
        index=exchange(p.session,'available_tools',{'command':'dialogue-video'},raw)
        with patch('runtime_policy.load_effective_policy',return_value={}):
            messages,estimate=p.api_messages()
        self.assertLessEqual(estimate,p._last_context_meta['budget'])
        tool=next(row for row in messages if row['role']=='tool')
        self.assertEqual(json.loads(tool['content'])['execution_help'],DIALOGUE_VIDEO)
        for offset in (0,311,641,955,1296,0,311):
            exchange(p.session,'chat_history',{'action':'read','message_id':index,'offset':offset},'saved page')
        before=copy.deepcopy(p.session)
        with patch('runtime_policy.load_effective_policy',return_value={}):
            messages,estimate=p.api_messages()
        self.assertLessEqual(estimate,p._last_context_meta['budget'])
        runtime=next(row['content'] for row in messages if row['role']=='system' and 'Host discovery recovery' in row['content'])
        self.assertIn(DIALOGUE_VIDEO,runtime)
        self.assertEqual(p.session,before)

if __name__=='__main__':unittest.main()
