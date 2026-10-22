"""Synthetic completion failures retain evidence without replaying tool effects.

No HTTP server, model, real tool, profile or Tk window is used by these cases.
"""
from contextlib import nullcontext
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
from profile_paths import ProfileLocked
import native_chat as chat
from test_chat_handoff import CALL, panel
from test_image_lookup_limits import IMAGE, call


def image_panel(result=None):
    p = panel()
    p.session['messages'][0]['content'] = 'Find a photograph of the exact machine.'
    p.tool_runtime.execute.return_value = json.dumps(result if result is not None else {'images':[IMAGE]})
    return p


def tool_rows(p):
    return [row for row in p.session['messages'] if row['role'] == 'tool']


def final_text(test, p):
    test.assertEqual(p.session['messages'][-1]['role'], 'assistant')
    text = p.session['messages'][-1].get('content', '')
    test.assertTrue(text.strip(), 'A terminal response must leave a visible, saved explanation')
    return text


class CompletionEvidenceTests(unittest.TestCase):
    def test_empty_whitespace_and_reasoning_only_keep_returned_image_candidates(self):
        for content, reasoning in (('', ''), (' \n\t', ''), ('', 'Internal reasoning without an answer.')):
            with self.subTest(content=content, reasoning=reasoning):
                p = image_panel()
                with patch.object(p, 'stream_completion', side_effect=[('', '', [call(1,'exact machine')]),
                                                                       (content, reasoning, [])]) as stream:
                    p.agent_worker('test')
                self.assertEqual(stream.call_count, 2)
                p.tool_runtime.execute.assert_called_once()
                self.assertEqual(len(tool_rows(p)), 1)
                text = final_text(self, p)
                self.assertIn(IMAGE['image_url'], text)
                self.assertIn('exact match has not been verified', text)
                self.assertNotIn(reasoning or '\x00', text)

    def test_empty_answer_without_candidates_does_not_invent_a_match_or_image_url(self):
        p = image_panel({'success':True, 'images':[], 'results':[{'url':IMAGE['page_url']}]})
        with patch.object(p, 'stream_completion', side_effect=[('', '', [call(1,'exact machine')]), ('', '', [])]):
            p.agent_worker('test')
        text = final_text(self, p)
        self.assertIn('No usable image URL', text)
        self.assertIn('exact match has not been verified', text)
        self.assertIn(IMAGE['page_url'], text)
        self.assertNotIn(IMAGE['image_url'], text)
        self.assertIn('not verified image URLs', text)
        p.tool_runtime.execute.assert_called_once()

    def test_first_empty_answer_is_saved_as_a_blocker_not_a_blank_success(self):
        p = panel()
        with patch.object(p, 'stream_completion', return_value=('', 'No visible answer', [])) as stream:
            p.agent_worker('test')
        stream.assert_called_once()
        p.tool_runtime.execute.assert_not_called()
        text = final_text(self, p)
        self.assertRegex(text.lower(), r'empty|no .*answer|no .*response|could not|did not|without')
        p.store.save_session.assert_called()

    def test_generic_completed_tool_survives_summary_timeout_with_saved_diagnostic(self):
        p = panel(); result = '{"success":true,"proof":"ALREADY_DONE","files":["Outputs/result.txt"]}'
        p.tool_runtime.execute.return_value = result
        with patch.object(p, 'stream_completion', side_effect=[('', '', [CALL]), TimeoutError('fixture summary timeout')]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count, 2)
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual([row['content'] for row in tool_rows(p)], [result])
        text = final_text(self, p)
        self.assertRegex(text.lower(), r'timeout|timed out|could not|interrupted|failed')
        self.assertRegex(text.lower(), r'saved|result|review')

    def test_uncertain_tool_timeout_is_recorded_and_never_retried_by_final_fallback(self):
        p = panel(); p.tool_runtime.execute.side_effect = TimeoutError('effect may already have happened')
        with patch.object(p, 'stream_completion', side_effect=[('', '', [CALL]), TimeoutError('final response unavailable')]) as stream:
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(stream.call_count, 2)
        self.assertEqual(len(tool_rows(p)), 1)
        self.assertIn('effect may already have happened', tool_rows(p)[0]['content'])
        final_text(self, p)

    def test_completed_result_is_durable_before_preview_and_preview_failure_is_nonfatal(self):
        p = panel(); result = '{"success":true,"proof":"ALREADY_DONE"}'
        p.tool_runtime.execute.return_value = result
        snapshots = []
        p.store.save_session.side_effect = lambda session:snapshots.append(copy.deepcopy(session))
        def preview(_text):
            self.assertTrue(any(row['role']=='tool' and row['content']==result
                                for saved in snapshots for row in saved['messages']),
                            'Completed tool evidence must be saved before preview construction')
            raise ValueError('fixture thumbnail unavailable')
        p.prepare_media_from_tool_result = preview
        with patch.object(p, 'stream_completion', side_effect=[('', '', [CALL]), ('The saved result is available.', '', [])]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count, 2)
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual([row['content'] for row in tool_rows(p)], [result])
        self.assertIn('fixture thumbnail unavailable', tool_rows(p)[0].get('media_error', ''))
        self.assertEqual(final_text(self, p), 'The saved result is available.')

    def test_preview_failure_then_summary_timeout_does_not_repeat_or_lose_evidence(self):
        p = image_panel()
        p.prepare_media_from_tool_result = Mock(side_effect=ValueError('fixture thumbnail unavailable'))
        with patch.object(p, 'stream_completion', side_effect=[('', '', [call(1,'exact machine')]), TimeoutError('fixture timeout')]):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(len(tool_rows(p)), 1)
        self.assertIn(IMAGE['image_url'], tool_rows(p)[0]['content'])
        self.assertIn(IMAGE['image_url'], final_text(self, p))

    def test_tool_step_limit_leaves_saved_explanation_without_replaying_tool(self):
        p = panel(); p.settings['tool_call_limit'] = 1
        with patch.object(p, 'stream_completion', side_effect=[('', '', [CALL]), ('Call limit reached; one action is saved.', '', [])]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count, 2); p.tool_runtime.execute.assert_called_once()
        self.assertEqual(len(tool_rows(p)), 1)
        self.assertRegex(final_text(self, p).lower(), r'limit|step|review')

    def test_cancel_during_summary_preserves_tool_but_does_not_publish_success_fallback(self):
        p = image_panel()
        replies = [('', '', [call(1,'exact machine')])]
        def response(_messages):
            if replies: return replies.pop(0)
            p.cancel_event.set()
            raise TimeoutError('cancelled fixture')
        with patch.object(p, 'stream_completion', side_effect=response) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count, 2)
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session['messages'][-1]['role'], 'tool')
        self.assertEqual([event for event in p.ev.queue if event[0]=='done'], [('done',None)])
        self.assertFalse(any('Actual image candidates' in str(event) for event in p.ev.queue))

    def test_revoked_login_during_summary_cannot_save_or_emit_candidate_fallback(self):
        p = image_panel(); state = {'active':True}; writes_after_revocation = []
        def check():
            if not state['active']: raise ProfileLocked('fixture login ended')
        p._check_login = check
        p.store.save_session.side_effect = lambda _session:writes_after_revocation.append(not state['active'])
        replies = [('', '', [call(1,'exact machine')])]
        def response(_messages):
            if replies: return replies.pop(0)
            state['active'] = False
            raise TimeoutError('fixture timeout after logout')
        with patch.object(p, 'stream_completion', side_effect=response): p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session['messages'][-1]['role'], 'tool')
        self.assertNotIn(True, writes_after_revocation)
        self.assertFalse(any('Actual image candidates' in str(event) for event in p.ev.queue))

    def test_profile_error_from_preview_is_not_swallowed_as_an_ordinary_media_error(self):
        p = panel(); state = {'active':True}; writes_after_revocation = []
        def check():
            if not state['active']: raise ProfileLocked('fixture login ended')
        def preview(_text):
            state['active'] = False
            raise ProfileLocked('fixture login ended')
        p._check_login = check
        p.prepare_media_from_tool_result = preview
        p.store.save_session.side_effect = lambda _session:writes_after_revocation.append(not state['active'])
        with patch.object(p, 'stream_completion', return_value=('', '', [CALL])) as stream: p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once(); stream.assert_called_once()
        self.assertEqual(len(tool_rows(p)), 1)
        self.assertNotIn('media_error', tool_rows(p)[0])
        self.assertNotIn(True, writes_after_revocation)

    def test_revoked_login_during_successful_final_reply_cannot_save_late_answer(self):
        p = panel(); state = {'active':True}; writes_after_revocation = []
        def check():
            if not state['active']: raise ProfileLocked('fixture login ended')
        p._check_login = check
        p.store.save_session.side_effect = lambda _session:writes_after_revocation.append(not state['active'])
        replies = [('', '', [CALL])]
        def response(_messages):
            if replies: return replies.pop(0)
            state['active'] = False
            return 'A late final answer after logout.', '', []
        with patch.object(p, 'stream_completion', side_effect=response): p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session['messages'][-1]['role'], 'tool')
        self.assertNotIn(True, writes_after_revocation)
        self.assertFalse(any(row.get('content')=='A late final answer after logout.' for row in p.session['messages']))

    def test_tool_result_save_failure_never_continues_inference_or_reexecutes_effect(self):
        p = panel()
        def save(session):
            if any(row['role']=='tool' for row in session['messages']):
                raise OSError('fixture durable storage unavailable')
        p.store.save_session.side_effect = save
        with patch.object(p, 'stream_completion', return_value=('', '', [CALL])) as stream: p.agent_worker('test')
        stream.assert_called_once(); p.tool_runtime.execute.assert_called_once()
        self.assertTrue(any('storage unavailable' in str(event) for event in p.ev.queue))


def controls(p):
    p.busy = False; p.COL = {'gold':'gold', 'good':'green', 'muted':'gray'}
    for name in ('render_history','update_token_label','_set_llm_dot','_notice','_thread',
                 'stop_btn','send_btn','session_list','model_lbl','prompt'):
        setattr(p, name, Mock())
    return p


class ExplicitRegenerationTests(unittest.TestCase):
    def test_regenerate_refuses_completed_and_uncertain_tool_turns_without_removing_evidence(self):
        for suffix in (
            [{'role':'assistant','content':'','tool_calls':[copy.deepcopy(CALL)]},
             {'role':'tool','tool_call_id':CALL['id'],'content':'ALREADY_DONE'},
             {'role':'assistant','content':'Saved result.'}],
            [{'role':'assistant','content':'','tool_calls':[copy.deepcopy(CALL)]}],
            [{'role':'tool','tool_call_id':CALL['id'],'content':'ERROR: timeout; effect uncertain'}],
        ):
            with self.subTest(suffix=suffix):
                p = controls(panel()); p.session['messages'].extend(copy.deepcopy(suffix))
                before = copy.deepcopy(p.session)
                p.regenerate_last()
                self.assertEqual(p.session, before)
                p._thread.assert_not_called(); p.tool_runtime.execute.assert_not_called()
                self.assertFalse(p.busy)
                self.assertTrue(p._notice.called or p.model_lbl.configure.called,
                                'A refused regeneration must explain how to continue safely')

    def test_tools_in_older_turn_do_not_block_regeneration_of_latest_plain_reply(self):
        p = controls(panel())
        p.session['messages'].extend([
            {'role':'assistant','content':'','tool_calls':[copy.deepcopy(CALL)]},
            {'role':'tool','tool_call_id':CALL['id'],'content':'ALREADY_DONE'},
            {'role':'user','content':'Explain that result in one sentence.'},
            {'role':'assistant','content':'Old wording.'}])
        # Live timing is a presentation wrapper; this fixture has no Tk widgets.
        with patch('native_chat_timers_v15_128e._begin_response'):
            p.regenerate_last()
        self.assertEqual(p.session['messages'][-1]['role'], 'user')
        self.assertEqual(len(tool_rows(p)), 1)
        p._thread.assert_called_once()
        p._thread.return_value.start.assert_called_once()
        p.tool_runtime.execute.assert_not_called()


class EventPumpRecoveryTests(unittest.TestCase):
    def fixture(self):
        p = controls(panel()); p.busy = True; p.app = Mock(); p.drop_target = None
        p._stream_pump_budget_ms = 1000
        p._live_thinking_block = None; p._live_tool_block = None
        for name in ('finish_trace_block','append_trace_block','header','chat_insert',
                     'refresh_sessions_labels_only','refresh_status','_maybe_schedule_auto_title',
                     '_schedule_model_probe','_schedule_memory_maintenance'):
            setattr(p, name, Mock())
        p.create_trace_block = Mock(return_value='fixture block')
        return p

    def test_preview_render_failure_rearms_pump_and_does_not_strand_busy_controls(self):
        p = self.fixture()
        p.render_media_card = Mock(side_effect=ValueError('fixture widget failure'))
        p.ev.put(('tool_result',{'name':'shell','content':'ALREADY_DONE','media':[{'path':'Outputs/result.png'}]}))
        p.ev.put(('done',None))
        p._pump()
        self.assertTrue(p.app.after.called, 'Rendering failures must not disable the Tk event pump')
        if p.busy: p._pump()
        self.assertFalse(p.busy)
        p.stop_btn.configure.assert_any_call(state='disabled')
        p.send_btn.configure.assert_any_call(state='normal')

    def test_content_render_failure_cannot_consume_done_before_unlocking_controls(self):
        p = self.fixture()
        p.chat_insert.side_effect = [ValueError('fixture content widget failure'),None,None,None]
        p.ev.put(('content','Completed reply already saved in the session.'))
        p.ev.put(('done',None))
        p._pump()
        self.assertTrue(p.app.after.called)
        if p.busy:p._pump()
        self.assertFalse(p.busy,'An undispatched done event must survive a preceding content-render failure')
        p.send_btn.configure.assert_any_call(state='normal')


class ResponseWatchIntegrationTests(unittest.TestCase):
    def test_progress_uses_gui_queue_and_abort_never_shutdowns_a_newer_socket(self):
        p = panel(); own = Mock(_portalai_owned_socket=None); newer = Mock()
        own_socket = Mock(); newer_socket = Mock()
        p.active_http.conn = own; p.active_http.sock = own_socket
        with patch('chat_progress.ResponseWatch') as factory:
            p._response_watch(own)
        notify,cancel,abort = factory.call_args.args
        self.assertIs(cancel,p.cancel_event)
        notify('Fixture response remains active.')
        self.assertIn(('progress','Fixture response remains active.'),list(p.ev.queue))
        abort(); own_socket.shutdown.assert_called_once(); own.close.assert_not_called()
        own._portalai_owned_socket = own_socket
        p.active_http.conn = newer; p.active_http.sock = newer_socket
        abort()
        self.assertEqual(own_socket.shutdown.call_count,2)
        newer_socket.shutdown.assert_not_called(); newer.close.assert_not_called()
        own.close.assert_not_called()  # The inference thread owns buffered-reader close.

    def test_response_deadline_is_not_a_retryable_transport_failure(self):
        from chat_progress import ResponseStalled
        p = panel(); failure = ResponseStalled(phase='reasoning',reason='idle',elapsed=90,quiet=90)
        with patch.object(p,'_wait_for_model',return_value=True), \
             patch.object(p,'_stream_completion_once',side_effect=failure) as request:
            with self.assertRaises(ResponseStalled):p.stream_completion([])
        request.assert_called_once(); p.tool_runtime.execute.assert_not_called()

    def test_real_stream_touches_watch_for_useful_deltas_not_keepalives(self):
        p = panel(); watch = MagicMock(error=None)
        response = Mock(status=200)
        response.readline.side_effect = [b': keepalive\n',b'data: {"choices":[]}\n',
            b'data: {"choices":[{"delta":{"reasoning_content":"Reasoning"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"Answer"},"finish_reason":"stop"}]}\n',b'']
        connection = Mock(); connection.getresponse.return_value = response
        with patch.object(p,'_response_watch',return_value=watch), \
             patch.object(chat,'model_id',return_value='fixture'), \
             patch.object(chat.http.client,'HTTPConnection',return_value=connection):
            self.assertEqual(p._stream_completion_once([]),('Answer','Reasoning',[]))
        self.assertEqual([item.kwargs['phase'] for item in watch.touch.call_args_list],
                         ['reasoning about the request','writing a reply'])
        watch.__enter__.assert_called_once(); watch.stop.assert_called_once()
        watch.raise_if_expired.assert_called_once()
        self.assertIsNone(p.active_http.conn); self.assertIsNone(p.active_http.sock)

    def test_reply_token_limit_with_unknown_context_keeps_partial_and_actionable_notice(self):
        p = panel()
        def response(_messages):
            p._last_finish_reason = 'length'
            return 'Partial answer with useful information.', '', []
        with patch.object(p,'stream_completion',side_effect=response) as stream:p.agent_worker('test')
        stream.assert_called_once(); p.tool_runtime.execute.assert_not_called()
        text = final_text(self,p)
        self.assertTrue(any(row.get('content') == 'Partial answer with useful information.'
                            and row.get('continuation_checkpoint') for row in p.session['messages']))
        self.assertIn('context capacity is unknown',text)
        self.assertIn('continue',text)


class ToolWaitRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        runtime = chat.ToolRuntime.__new__(chat.ToolRuntime)
        runtime.root = self.root; runtime.settings = {'tool_timeout_seconds':1800}
        runtime.boot = self.root/'Runtime/BootstrapPython/python.exe'
        runtime.boot.parent.mkdir(parents=True); runtime.boot.touch()
        runtime.profile = SimpleNamespace(identity=None, check=Mock())
        runtime._lock = threading.Lock(); runtime._proc = None
        runtime.on_progress = Mock()
        self.runtime = runtime

    def test_registered_web_limits_do_not_shorten_media_or_user_lower_limit(self):
        runtime = self.runtime
        for prefix in ('python Agent/web_tools.py ', r'.\Tools\portable_python.cmd Agent\web_tools.py ',
                       '"'+str(runtime.boot)+'" "'+str(self.root/'Agent/web_tools.py')+'" '):
            for action in ('search','fetch','image-search','download-image','image'):
                with self.subTest(prefix=prefix, action=action):
                    seconds, label = runtime._shell_wait_policy(prefix + action + ' "example"')
                    self.assertEqual(seconds, 90); self.assertEqual(label, 'Web '+action)
            self.assertEqual(runtime._shell_wait_policy(prefix+'research "example"'), (180,'Web research'))
        for command in ('python Agent/ai_tools.py dialogue-video "portrait.png" "Hello"',
                        'python Agent/ai_tools.py autoedit "image.png" "blue shirt"',
                        'arbitrary administrator command', 'python unrelated/web_tools.py search "example"'):
            with self.subTest(command=command):self.assertEqual(runtime._shell_wait_policy(command),(1800,'Tool'))
        runtime.settings['tool_timeout_seconds'] = 30
        self.assertEqual(runtime._shell_wait_policy('python Agent/web_tools.py research "example"'),(30,'Web research'))
        self.assertEqual(runtime._shell_wait_policy('python Agent/ai_tools.py image "example"'),(30,'Tool'))

    def test_progress_polls_same_process_and_returns_original_final_output_once(self):
        runtime = self.runtime; clock = [0.]
        process = Mock(args=['one','registered','command']); count = [0]
        def communicate(*, timeout):
            count[0] += 1; self.assertLessEqual(timeout,1.)
            if count[0] <= 3:
                clock[0] += 10
                raise chat.subprocess.TimeoutExpired(process.args,timeout)
            return '{"success":true,"result":"saved evidence"}', 'diagnostic'
        process.communicate.side_effect = communicate
        with patch.object(chat.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(chat.subprocess,'Popen') as launch:
            output = runtime._communicate(process,90,'Web image-search')
        launch.assert_not_called(); self.assertEqual(process.communicate.call_count,4)
        self.assertEqual(output,('{"success":true,"result":"saved evidence"}','diagnostic'))
        runtime.profile.check.assert_called()
        self.assertEqual(runtime.on_progress.call_count,1)
        self.assertIn('still running',runtime.on_progress.call_args.args[0])
        self.assertIn('not confirmed',runtime.on_progress.call_args.args[0])

    def test_progress_callback_failure_cannot_abandon_owned_running_process(self):
        runtime = self.runtime; clock = [0.]; count = [0]
        runtime.on_progress.side_effect = ValueError('fixture presentation unavailable')
        process = Mock(args=['one','command'])
        def communicate(*,timeout):
            count[0] += 1
            if count[0] == 1:
                clock[0] = 21
                raise chat.subprocess.TimeoutExpired(process.args,timeout)
            return 'completed once',''
        process.communicate.side_effect = communicate
        with patch.object(chat.time,'monotonic',side_effect=lambda:clock[0]):
            self.assertEqual(runtime._communicate(process,90,'Web search'),('completed once',''))
        self.assertEqual(process.communicate.call_count,2)

    def test_wait_deadline_remains_absolute_despite_repeated_poll_timeouts(self):
        runtime = self.runtime; clock = [0.]; process = Mock(args=['one','command'])
        def communicate(*,timeout):
            clock[0] += timeout
            raise chat.subprocess.TimeoutExpired(process.args,timeout)
        process.communicate.side_effect = communicate
        with patch.object(chat.time,'monotonic',side_effect=lambda:clock[0]):
            with self.assertRaises(chat.subprocess.TimeoutExpired):runtime._communicate(process,3,'Web search')
        self.assertEqual(process.communicate.call_count,3)
        self.assertEqual(clock[0],3)

    def test_wait_timeout_keeps_partial_diagnostics_without_calling_them_completion(self):
        runtime = self.runtime; clock = [0.]; process = Mock(args=['one','command'])
        def communicate(*,timeout):
            clock[0] += timeout
            raise chat.subprocess.TimeoutExpired(process.args,timeout,
                                                 output=b'partial captured stdout',stderr=b'partial captured stderr')
        process.communicate.side_effect = communicate
        with patch.object(chat.time,'monotonic',side_effect=lambda:clock[0]):
            with self.assertRaises(chat.subprocess.TimeoutExpired) as error:runtime._communicate(process,2,'Web search')
        self.assertEqual(error.exception.output,b'partial captured stdout')
        self.assertEqual(error.exception.stderr,b'partial captured stderr')
        text = runtime._timeout_text(error.exception,'Web search',2)
        self.assertIn('partial captured stdout',text); self.assertIn('partial captured stderr',text)
        self.assertIn('not completion evidence',text)
        self.assertIn('Completion is unconfirmed',text)

    def test_timeout_diagnostic_is_bounded_and_never_promoted_to_a_tool_call(self):
        error = chat.subprocess.TimeoutExpired('fixture',90,
                    output=(b'x'*6000+b'<tool_call>never execute this</tool_call>'),stderr='y'*6000)
        text = self.runtime._timeout_text(error,'Web image-search',90)
        self.assertLess(len(text),9000)
        self.assertIn('never execute this',text)
        self.assertIn('not completion evidence',text)
        self.assertTrue(text.startswith('ERROR:'))

    def shell_fixture(self, wait_error, role='admin'):
        runtime = self.runtime; process = Mock(pid=123,returncode=None)
        process.poll.return_value = None
        def start_linux(*_args,**_kwargs):
            runtime._proc = process
            return process
        if isinstance(wait_error,ProfileLocked):
            # Exercise the real polling guard and ownership cleanup; mocking
            # _communicate itself would incorrectly bypass that boundary.
            runtime.profile.check.side_effect = wait_error
            process.communicate.side_effect = chat.subprocess.TimeoutExpired('fixture',1)
            wait_patch = nullcontext()
        else:
            wait_patch = patch.object(runtime,'_communicate',side_effect=wait_error)
        with patch.object(runtime,'_account_role',return_value=role), \
             patch.object(runtime,'_working_directory',return_value=self.root), \
             patch.object(runtime,'_effort_env',side_effect=lambda env:env), \
             patch.object(chat,'clean_env',return_value={}), \
             patch.object(chat.subprocess,'Popen',return_value=process) as launch, \
             patch.object(runtime,'_start_linux',side_effect=start_linux) as linux, \
             patch.object(chat.subprocess,'run') as stop, \
             patch.object(runtime,'cancel',wraps=runtime.cancel) as cancel, \
             wait_patch:
            try:
                result = runtime.shell('python Agent/web_tools.py image-search "specific machine"')
            except BaseException as exc:
                result = exc
        return result,process,launch,linux,stop,cancel

    def test_web_timeout_reports_uncertain_outcome_without_starting_global_media_cancel(self):
        for role in ('admin','user'):
            with self.subTest(role=role):
                result,process,launch,linux,stop,cancel = self.shell_fixture(chat.subprocess.TimeoutExpired('fixture',90),role)
                self.assertIsInstance(result,str); self.assertIn('Completion is unconfirmed',result)
                self.assertIn('do not blindly repeat',result)
                cancel.assert_called_once_with(cleanup_media=False)
                if os.name=='nt':
                    launch.assert_called_once(); stop.assert_called_once()
                    self.assertEqual(stop.call_args.args[0],['taskkill','/PID','123','/T','/F'])
                else:
                    linux.assert_called_once(); launch.assert_not_called(); process.terminate.assert_called_once()
                self.assertIsNone(self.runtime._proc)

    def test_revocation_during_web_wait_cancels_owned_process_before_forgetting_it(self):
        for role in ('admin','user'):
            with self.subTest(role=role):
                result,process,launch,linux,stop,cancel = self.shell_fixture(ProfileLocked('fixture login ended'),role)
                self.assertIsInstance(result,ProfileLocked)
                cancel.assert_called_once_with(cleanup_media=False)
                if os.name=='nt':launch.assert_called_once(); stop.assert_called_once()
                else:linux.assert_called_once(); launch.assert_not_called(); process.terminate.assert_called_once()
                self.assertIsNone(self.runtime._proc)


if __name__ == '__main__':
    unittest.main()
