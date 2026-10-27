"""Development-only checks for factual, current-account environment context."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import native_chat as chat


class HostEnvironmentTests(unittest.TestCase):
    def panel(self, role='admin'):
        root=Path(__file__).resolve().parent/'disposable host'
        self.role=role
        tools=SimpleNamespace(root=root,_account_role=lambda:self.role,
            _working_directory=lambda:root/'Private/Users/synthetic/Workspace')
        return SimpleNamespace(tool_runtime=tools,session={'id':'synthetic','messages':[]},
            memory=SimpleNamespace(config={},chat_included=lambda _:False))

    def facts(self,panel):
        text=chat.NativeChat._runtime_session_context(panel)
        return json.loads(next(line.split(': ',1)[1] for line in text.splitlines()
                               if line.startswith('- observed_execution_environment: ')))

    def test_app_root_and_shell_cwd_are_distinct_observed_paths(self):
        panel=self.panel();facts=self.facts(panel)
        self.assertEqual(facts['application_root'],str(panel.tool_runtime.root.resolve()))
        self.assertEqual(facts['shell_working_directory'],str(panel.tool_runtime._working_directory()))
        self.assertNotEqual(facts['application_root'],facts['shell_working_directory'])
        self.assertIn('subject to OS permissions',facts['file_access'])
        self.assertIn('no automatic elevation',facts['shell_access'])

    def test_role_is_checked_again_and_standard_guest_never_advertise_admin_edits(self):
        panel=self.panel();self.assertEqual(self.facts(panel)['account_role'],'admin')
        for role in ('user','guest'):
            self.role=role;facts=self.facts(panel)
            self.assertEqual(facts['account_role'],role)
            self.assertEqual(facts['shell_access'],'registered commands only')
            self.assertIn('no file edits',facts['file_access'])

    def test_ended_account_fails_before_publishing_context_or_resolving_workspace(self):
        panel=self.panel()
        panel.tool_runtime._account_role=Mock(side_effect=PermissionError('ended'))
        panel.tool_runtime._working_directory=Mock()
        with self.assertRaises(PermissionError):self.facts(panel)
        panel.tool_runtime._working_directory.assert_not_called()

    def test_no_runtime_does_not_invent_permissions(self):
        panel=self.panel();del panel.tool_runtime
        self.assertNotIn('observed_execution_environment',chat.NativeChat._runtime_session_context(panel))

    def test_tool_scope_is_explicit_and_does_not_change_other_requests(self):
        normal=self.panel();coding=self.panel();coding._request_tool_scope='coding'
        before=chat._request_tools(normal)
        names={row['function']['name'] for row in chat._request_tools(coding)}
        self.assertEqual(names,{'chat_history','chat_checkpoint','shell','read_file','write_file','edit_file','list_dir'})
        self.assertIs(chat._request_tools(normal),before)
        self.assertIs(before,chat.TOOLS)
        normal._request_tool_scope='unknown'
        self.assertIs(chat._request_tools(normal),chat.TOOLS)

    def test_focused_tools_leave_room_for_actual_source_without_relaxing_reserves(self):
        from test_chat_context_recovery import small_panel,exchange
        panel=small_panel();environment=self.panel()
        panel.root=environment.tool_runtime.root;panel.tool_runtime=environment.tool_runtime
        panel._request_tool_scope='coding';panel.settings['max_output_tokens']=1024
        panel.store.custom_instructions=lambda:''
        panel.system_prompt=lambda:chat.NativeChat.system_prompt(panel)
        panel.memory.chat_included=lambda _:False;panel.memory.config={}
        panel._runtime_session_context=lambda memory='':chat.NativeChat._runtime_session_context(panel,memory)
        snippet='def target():\n    return "SOURCE MUST REMAIN VISIBLE"\n'+'# ordinary source line\n'*60
        exchange(panel,snippet,argument='source search')
        with patch('runtime_policy.load_effective_policy',return_value={}):
            api,estimate=panel.api_messages()
        self.assertLessEqual(estimate,7372)
        self.assertEqual(panel._last_context_meta['checkpoint_reserve'],737)
        self.assertEqual(panel._last_context_meta['safety_tokens'],500)
        self.assertEqual(panel._last_context_meta['output_reserve'],1024)
        self.assertTrue(any(row.get('content')==snippet for row in api))

    def test_usable_tool_page_is_not_reduced_for_a_second_headroom_discount(self):
        from test_chat_context_recovery import small_panel,exchange
        panel=small_panel();panel.settings['max_output_tokens']=1024
        snippet='UNIQUE_SOURCE_PAGE\n'+'function source text\n'*40
        exchange(panel,snippet,argument='source search')
        initial=panel._context_plan()
        # Fill fixed instructions to place this request above the old 90%
        # threshold, but safely below the existing request budget.
        extra=initial['budget']-200-initial['estimated_sent']
        old_prompt=panel.system_prompt()
        panel.system_prompt=lambda:old_prompt+'x'*(4*extra)
        api,estimate=panel.api_messages()
        self.assertGreater(estimate,int(panel._last_context_meta['budget']*.90))
        self.assertLessEqual(estimate,panel._last_context_meta['budget'])
        self.assertTrue(any(row.get('content')==snippet for row in api))
        self.assertEqual(panel._last_context_meta['safety_tokens'],500)

    def test_explicit_debugging_is_not_prohibited_by_tool_syntax_guidance(self):
        text=chat.NativeChat._runtime_session_context(self.panel())
        self.assertIn('requested environment inspection or code repair',text)
        self.assertNotIn('Do not search application source',text)

    def test_real_prompt_with_observed_environment_still_recovers_in_eight_k_context(self):
        from test_chat_context_recovery import small_panel,exchange
        from test_chat_rolling_resume import assert_pairs
        panel=small_panel();environment=self.panel()
        panel.root=environment.tool_runtime.root;panel.tool_runtime=environment.tool_runtime
        panel.store.custom_instructions=lambda:''
        panel.system_prompt=lambda:chat.NativeChat.system_prompt(panel)
        panel.memory.chat_included=lambda _:False;panel.memory.config={}
        panel._runtime_session_context=lambda memory='':chat.NativeChat._runtime_session_context(panel,memory)
        panel.session['messages'][0]['content']='Inspect the source, repair it and verify the resulting code.'
        exchange(panel,'SOURCE_READ_RECEIPT\n'+'source line\n'*10000,argument='source search')
        original=json.dumps(panel.session['messages'])
        with patch('runtime_policy.load_effective_policy',return_value={}):
            panel.compact_context_if_needed();api,estimate=panel.api_messages()
        self.assertLessEqual(estimate,7372)
        self.assertIn('observed_execution_environment',json.dumps(api))
        self.assertIn('SOURCE_READ_RECEIPT',json.dumps(api))
        self.assertEqual(json.dumps(panel.session['messages']),original)
        assert_pairs(self,api)

if __name__=='__main__':unittest.main()
