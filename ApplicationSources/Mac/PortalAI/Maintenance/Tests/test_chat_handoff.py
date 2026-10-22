from contextlib import ExitStack, nullcontext
import copy
import http.client
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"Agent"), str(ROOT/"ControlCenter")]
import native_chat as chat
import model_connection as transport
import service_manager as services


def panel():
    p = chat.NativeChat.__new__(chat.NativeChat)
    p.settings = {**chat.DEFAULT_SETTINGS, "tool_step_limit": 3}
    p.cancel_event = threading.Event(); p.active_http = chat.ActiveHTTP(); p.ev = queue.Queue()
    p.session = {"id": "test", "messages": [{"role": "user", "content": "Test"}]}
    p.store = SimpleNamespace(save_session=Mock())
    p.tool_runtime = SimpleNamespace(execute=Mock(return_value='{"success":true,"proof":"ALREADY_DONE"}'))
    p.compact_context_if_needed = lambda: False
    p.prepare_media_from_tool_result = lambda _: []
    p.api_messages = lambda: (copy.deepcopy(p.session["messages"]), 0)
    return p


CALL = {"id": "call_one", "type": "function", "function": {"name": "shell", "arguments": '{"command":"one authorized action"}'}}


class ChatContinuationTests(unittest.TestCase):
    def test_reconnection_retries_only_summary_not_completed_tool(self):
        for error in (transport.ModelNotReady("Loading model"), ConnectionRefusedError("restarting")):
            p = panel(); requests = []
            responses = [("", "", [CALL]), error, ("Result ALREADY_DONE", "", [])]
            def respond(messages):
                requests.append(messages); r = responses.pop(0)
                if isinstance(r, Exception): raise r
                return r
            with patch.object(p, "_wait_for_model", return_value=True), patch.object(p, "_stream_completion_once", side_effect=respond), patch.object(p.cancel_event, "wait", return_value=False):
                p.agent_worker("test")
            p.tool_runtime.execute.assert_called_once()
            self.assertEqual(requests[1], requests[2])
            self.assertEqual(requests[2][-1]["role"], "tool")
            self.assertEqual(p.session["messages"][-1]["content"], "Result ALREADY_DONE")
            self.assertFalse(any(e[0] == "error" for e in list(p.ev.queue)))

    def test_cancel_after_tool_saves_result_without_next_inference(self):
        p = panel()
        def tool(*args): p.cancel_event.set(); return "ALREADY_DONE"
        p.tool_runtime.execute.side_effect = tool
        with patch.object(p, "stream_completion", return_value=("", "", [CALL])) as stream:
            p.agent_worker("test")
        stream.assert_called_once(); p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session["messages"][-1]["content"], "ALREADY_DONE")

    def fake_stream(self, frames):
        response = Mock(status=200)
        response.readline.side_effect = [*(b"data: "+json.dumps(f).encode()+b"\n" for f in frames), b""]
        conn = Mock(); conn.getresponse.return_value = response
        return conn

    def test_dropped_stream_never_executes_partial_tool_call(self):
        p = panel()
        conn = self.fake_stream([{"choices": [{"delta": {"tool_calls": [{"index": 0, **CALL}]}}]}])
        with patch.object(p, "_wait_for_model", return_value=True), patch.object(chat, "model_id", return_value="test"), patch.object(chat.http.client, "HTTPConnection", return_value=conn):
            p.agent_worker("test")
        p.tool_runtime.execute.assert_not_called()
        self.assertTrue(any("Incomplete tool calls" in str(e) for e in list(p.ev.queue)))
        self.assertFalse(any(row.get('tool_calls') or row.get('role') == 'tool' for row in p.session['messages']))
        self.assertEqual(p.session['messages'][-1]['role'], 'assistant')
        self.assertTrue(p.session['messages'][-1]['incomplete'])
        self.assertIn('Incomplete tool calls', p.session['messages'][-1]['content'])

    def test_streamed_server_error_is_not_success(self):
        p = panel(); conn = self.fake_stream([{"error": {"message": "model failed"}}])
        with patch.object(p, "_wait_for_model", return_value=True), patch.object(chat, "model_id", return_value="test"), patch.object(chat.http.client, "HTTPConnection", return_value=conn):
            p.agent_worker("test")
        p.tool_runtime.execute.assert_not_called()
        self.assertTrue(any("stream error" in str(e) for e in list(p.ev.queue)))

    def test_terminal_tool_call_is_preserved(self):
        p = panel(); conn = self.fake_stream([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, **CALL}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}])
        with patch.object(p, "_wait_for_model", return_value=True), patch.object(chat, "model_id", return_value="test"), patch.object(chat.http.client, "HTTPConnection", return_value=conn):
            self.assertEqual(p.stream_completion([])[2], [CALL])
        payload = json.loads(conn.request.call_args.kwargs['body'])
        self.assertIs(payload['parallel_tool_calls'], False)

    def test_malformed_last_call_blocks_complete_batch_without_retry_or_bad_history(self):
        p = panel()
        bad = {'id': 'call_bad', 'type': 'function', 'function': {'name': 'shell', 'arguments': '{"command":'}}
        conn = self.fake_stream([
            {'choices': [{'delta': {'tool_calls': [{'index': 0, **CALL}, {'index': 1, **bad}]}}]},
            {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]}])
        with patch.object(p, '_wait_for_model', return_value=True), patch.object(chat, 'model_id', return_value='test'), patch.object(chat.http.client, 'HTTPConnection', return_value=conn) as factory:
            p.agent_worker('test')
        factory.assert_called_once()
        p.tool_runtime.execute.assert_not_called()
        self.assertFalse(any(row.get('tool_calls') for row in p.session['messages']))
        self.assertIn('No tools from this response were run', p.session['messages'][-1]['content'])
        self.assertTrue(p.session['messages'][-1]['tool_validation_error'])

    def test_length_finish_blocks_even_complete_looking_call(self):
        p = panel()
        conn = self.fake_stream([
            {'choices': [{'delta': {'tool_calls': [{'index': 0, **CALL}]}}]},
            {'choices': [{'delta': {}, 'finish_reason': 'length'}]}])
        with patch.object(p, '_wait_for_model', return_value=True), patch.object(chat, 'model_id', return_value='test'), patch.object(chat.http.client, 'HTTPConnection', return_value=conn):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_not_called()
        self.assertIn("'length'", p.session['messages'][-1]['content'])

    def test_worker_preflight_rejects_missing_id_unknown_name_and_nonobject_args(self):
        for edit in ({'id': ''}, {'function': {'name': 'unknown', 'arguments': '{}'}},
                     {'function': {'name': 'shell', 'arguments': '[]'}},
                     {'function': {'name': 'shell', 'arguments': '{"command":NaN}'}}):
            with self.subTest(edit=edit):
                p = panel(); bad = {**copy.deepcopy(CALL), 'id': 'call_bad', **edit}
                with patch.object(p, 'stream_completion', return_value=('', '', [CALL, bad])):
                    p.agent_worker('test')
                p.tool_runtime.execute.assert_not_called()
                self.assertFalse(any(row.get('tool_calls') for row in p.session['messages']))

    def test_duplicate_actions_block_whole_batch(self):
        p = panel(); repeated = {**copy.deepcopy(CALL), 'id': 'call_two'}
        with patch.object(p, 'stream_completion', return_value=('', '', [CALL, repeated])):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_not_called()
        self.assertIn('repeats an identical action', p.session['messages'][-1]['content'])

    def test_completed_tool_id_cannot_be_replayed_in_a_later_response(self):
        p = panel()
        with patch.object(p, 'stream_completion', side_effect=[('', '', [CALL]), ('', '', [CALL])]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count, 2)
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(len([m for m in p.session['messages'] if m['role'] == 'tool']), 1)
        self.assertIn('automatic replay was blocked', p.session['messages'][-1]['content'])

    def test_historical_malformed_arguments_have_safe_api_view_without_mutation(self):
        p = panel()
        bad = {'id': 'call_bad', 'type': 'function', 'function': {'name': 'shell', 'arguments': '{"command":'}}
        original = {'role': 'assistant', 'content': 'Prior response', 'tool_calls': [copy.deepcopy(CALL), bad]}
        saved = copy.deepcopy(original)
        api = p._api_row(original)
        self.assertEqual(original, saved)
        self.assertEqual(api['tool_calls'][0], CALL)
        repaired = json.loads(api['tool_calls'][1]['function']['arguments'])
        self.assertEqual(repaired['original_unparsed_arguments'], bad['function']['arguments'])
        self.assertIn('review evidence', api['content'])
        tool = {'role': 'tool', 'tool_call_id': CALL['id'], 'content': 'ALREADY_DONE'}
        p._trim_tool_context = lambda text: text
        self.assertEqual(p._api_row(tool), tool)
        p.session['messages'].extend([original, tool])
        with patch.object(p, 'stream_completion', return_value=('Reviewed saved results', '', [])):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_not_called()

    def test_historical_invalid_metadata_fails_early_without_mutation(self):
        p = panel(); original = {'role': 'assistant', 'tool_calls': [{**CALL, 'id': ''}]}
        saved = copy.deepcopy(original)
        with self.assertRaisesRegex(RuntimeError, 'Start a new chat'):
            p._api_row(original)
        self.assertEqual(original, saved)

    def test_historical_non_json_constant_cannot_poison_repaired_api_arguments(self):
        p = panel()
        original = {'role': 'assistant', 'tool_calls': [copy.deepcopy(CALL)]}
        original['tool_calls'][0]['function']['arguments'] = float('nan')
        api = p._api_row(original)
        raw = api['tool_calls'][0]['function']['arguments']
        parsed = chat._tool_arguments(raw)
        self.assertEqual(parsed['original_unparsed_arguments'], 'nan')

    def test_cancel_interrupts_socket_before_connection_close(self):
        p = panel(); p.active_http.conn = conn = Mock(); p.active_http.sock = sock = Mock()
        p.cancel_http()
        sock.shutdown.assert_called_once(); conn.close.assert_called_once()
        self.assertIsNone(p.active_http.conn); self.assertIsNone(p.active_http.sock)


class ReadinessTests(unittest.TestCase):
    def test_stop_during_loading_wait_does_not_submit_completion(self):
        cancel = threading.Event(); active = chat.ActiveHTTP(); c = Mock()
        c.getresponse.return_value = Mock(status=503)
        with patch.object(transport.http.client, "HTTPConnection", return_value=c):
            self.assertFalse(transport.wait_for_ready(cancel, active, lambda _: cancel.set(), 5))
        c.request.assert_called_once_with("GET", "/health", headers={"Accept": "application/json"})

    def test_timeout_does_not_claim_ready(self):
        with self.assertRaisesRegex(TimeoutError, "results remain saved"):
            transport.wait_for_ready(threading.Event(), chat.ActiveHTTP(), Mock(), timeout=0)

    def test_loading_then_ready_is_reported_as_recovery(self):
        cancel = threading.Event(); c = Mock(); events = []
        c.getresponse.side_effect = [Mock(status=503), Mock(status=200)]
        with patch.object(transport.http.client, "HTTPConnection", return_value=c), patch.object(cancel, "wait", return_value=False):
            self.assertTrue(transport.wait_for_ready(cancel, chat.ActiveHTTP(), events.append, 5))
        self.assertEqual(len(events), 2); self.assertIn("ready", events[-1])


class BackendReadinessTests(unittest.TestCase):
    def test_handoff_stop_refuses_foreign_or_mixed_listeners(self):
        for paths in (("C:/Other/llama-server.exe",),
                      (str(ROOT/"LLM/llamacpp/llama-server.exe"), "C:/Other/llama-server.exe"),
                      (str(ROOT.parent/(ROOT.name+"-other")/"llama-server.exe"),)):
            with patch.object(services, "_listening_pids", return_value=list(range(1, len(paths)+1))), patch.object(services, "_process_image_path", side_effect=paths), patch.object(services, "_run_hidden") as kill:
                with self.assertRaisesRegex(RuntimeError, "outside this portable root"):
                    services._stop_qwen_listener()
            kill.assert_not_called()

    def test_handoff_stop_rechecks_ownership_before_kill(self):
        with patch.object(services, "_listening_pids", return_value=[42]), patch.object(services, "_process_image_path", side_effect=[str(ROOT/"LLM/llamacpp/llama-server.exe"), "C:/Other/app.exe"]), patch.object(services, "_run_hidden") as kill:
            with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                services._stop_qwen_listener()
        kill.assert_not_called()

    def test_handoff_completion_waits_for_model_health(self):
        events = []; state = {"active": True, "command_line": "saved", "cwd": "root"}
        def health(**_): events.append("health"); return events.count("health") == 2
        with ExitStack() as stack:
            stack.enter_context(patch.object(services, "_generation_current", return_value=True))
            stack.enter_context(patch.object(services, "_start_qwen_command", return_value=42))
            stack.enter_context(patch.object(services, "_qwen_health_ready", side_effect=health))
            stack.enter_context(patch.object(services, "_listener_identity", return_value={"portable_qwen": True}))
            stack.enter_context(patch.object(services, "_mark_handoff_done", side_effect=lambda *a: events.append("done")))
            stack.enter_context(patch.object(services, "_clear_generation_if_current"))
            stack.enter_context(patch.object(services, "_qwen_handoff_log"))
            stack.enter_context(patch.object(services.time, "sleep"))
            result = services.qwen_gpu_handoff_end(state)
        self.assertEqual(events, ["health", "health", "done"])
        self.assertTrue(result["ready"])

    def test_new_generation_cancels_readiness_without_clearing_it(self):
        with patch.object(services, "_generation_current", side_effect=[True, False]), patch.object(services, "_qwen_health_ready", return_value=False), patch.object(services.time, "sleep"):
            self.assertFalse(services._wait_handoff_ready({}))

    def test_foreign_listener_cannot_satisfy_readiness(self):
        with patch.object(services, "_generation_current", return_value=True), patch.object(services, "_qwen_health_ready", return_value=True), patch.object(services, "_listener_identity", return_value={"portable_qwen": False}):
            with self.assertRaisesRegex(RuntimeError, "not owned"):
                services._wait_handoff_ready({})

    def test_stale_generation_cannot_launch_server(self):
        with patch.object(services, "_qwen_lifecycle_mutex", return_value=nullcontext()), patch.object(services, "_generation_current", return_value=False), patch.object(services, "launch_detached") as launch:
            with self.assertRaisesRegex(RuntimeError, "superseded"):
                services._start_qwen_command("saved", "root", state={})
        launch.assert_not_called()


if __name__ == "__main__": unittest.main()
