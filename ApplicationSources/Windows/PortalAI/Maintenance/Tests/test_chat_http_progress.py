"""Real loopback HTTP/SSE deadlines; no model, production account, or GUI.

The panel is the existing constructor-free unit fixture. Only deadline lengths
are shortened; native HTTP, readiness, parsing, ownership and monitor cleanup
run unchanged. Servers and their request handlers are joined after each case.
"""
from contextlib import contextmanager
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
import native_chat as chat
import chat_progress
from chat_progress import ResponseStalled, ResponseWatch
from test_chat_handoff import panel


class SyntheticServer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, behavior):
        self.behavior = behavior
        self.release = threading.Event()
        self.headers_ready = threading.Event()
        self.posts = []
        super().__init__(('127.0.0.1', 0), Handler)

    def handle_error(self, request, client_address):
        pass  # Expected disconnects belong to the fixture, not stderr.


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        value = {'status':'ok'} if self.path == '/health' else {'data':[{'id':'synthetic-no-model'}]}
        body = json.dumps(value).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close'); self.end_headers(); self.wfile.write(body)
        self.close_connection = True

    def frame(self, delta=None, finish=None):
        value = {'choices':[{'delta':delta or {}, 'finish_reason':finish}]}
        self.sse(b'data: '+json.dumps(value).encode()+b'\n\n')

    def sse(self, data):
        if self.server.behavior == 'chunked-progress':
            self.wfile.write(f'{len(data):x}\r\n'.encode()+data+b'\r\n')
        else:
            self.wfile.write(data)
        self.wfile.flush()

    def finish(self):
        self.frame(finish='stop'); self.sse(b'data: [DONE]\n\n')
        if self.server.behavior == 'chunked-progress':
            self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.posts.append(json.loads(body))
        self.close_connection = True
        if self.server.behavior == 'headers':
            self.server.headers_ready.set(); self.server.release.wait(1)
            return
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
        if self.server.behavior == 'chunked-progress': self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        self.server.headers_ready.set()
        mode = self.server.behavior
        if mode in ('body', 'owned'):
            self.server.release.wait(1)
            return
        if mode == 'keepalive':
            for _ in range(50):
                self.wfile.write(b': keepalive\n\n'); self.wfile.flush()
                if self.server.release.wait(.02): return
            return
        if mode in ('progress', 'chunked-progress'):
            for index in range(5):
                self.frame({'reasoning_content':f'fixture step {index}. '})
                if self.server.release.wait(.06): return
            self.frame({'content':'A complete synthetic reply.'}); self.finish()
            return
        if mode == 'partial':
            self.frame({'content':'Visible partial evidence.'})
            self.server.release.wait(1)
            return
        if mode == 'terminal-length-open':
            self.frame({'reasoning_content': 'Completed allowance.'}, finish='length')
            self.server.release.wait(1)
            return
        if mode in ('reasoning-resume', 'partial-resume'):
            if len(self.server.posts) < 3:
                delta = {'reasoning_content': 'Working discovery '+str(len(self.server.posts))}
                if mode == 'partial-resume': delta['content'] = 'Visible partial '+str(len(self.server.posts))+'.'
                self.frame(delta, finish='length')
            else:
                self.frame({'content': 'Answer from the retained discoveries.'}, finish='stop')
            return
        if mode == 'tool-fragment':
            self.frame({'tool_calls':[{'index':0,'id':'fixture_incomplete','type':'function',
                                       'function':{'name':'shell','arguments':'{"command":'}}]})
            self.server.release.wait(1)
            return
        raise AssertionError('Unknown synthetic HTTP behavior')


class ActualHTTPProgressTests(unittest.TestCase):
    @contextmanager
    def fixture(self, behavior, *, idle=.18, total=.7):
        server = SyntheticServer(behavior)
        thread = threading.Thread(target=lambda:server.serve_forever(poll_interval=.01), name='PortalAISyntheticHTTP')
        thread.start()
        temporary = tempfile.TemporaryDirectory()
        p = panel(); p.root = Path(temporary.name)
        watches = []
        def watch_factory(*args, **options):
            options.update(idle_timeout=idle, total_timeout=total, progress_interval=.05, tick=.005)
            watch = ResponseWatch(*args, **options); watches.append(watch)
            return watch
        try:
            with patch.object(chat, 'API_HOST', '127.0.0.1'), patch.object(chat, 'API_PORT', server.server_address[1]), \
                    patch.object(chat_progress, 'ResponseWatch', side_effect=watch_factory):
                yield p, server, watches
        finally:
            # Release all server-side waits before joining the listener/handlers.
            server.release.set(); server.shutdown(); server.server_close(); thread.join(1)
            temporary.cleanup()
            self.assertFalse(thread.is_alive())
            for watch in watches:
                watch.stop()
                self.assertFalse(watch._thread.is_alive(), 'HTTP response left a monitor thread alive')

    def assert_stalled_once(self, behavior):
        with self.fixture(behavior) as (p, server, watches):
            started = time.monotonic()
            with self.assertRaises(ResponseStalled): p.stream_completion([{'role':'user','content':'Synthetic fixture only'}])
            self.assertLess(time.monotonic()-started, .8)
            self.assertEqual(len(server.posts), 1, 'A watchdog deadline must not retry inference')
            self.assertEqual(len(watches), 1)
            self.assertTrue(any(event[0]=='progress' for event in p.ev.queue))
            self.assertFalse(any(event[0]=='connection_status' and 'reconnecting' in str(event) for event in p.ev.queue))
            self.assertIsNone(p.active_http.conn); self.assertIsNone(p.active_http.sock)
            p.tool_runtime.execute.assert_not_called()

    def test_stalled_response_headers_are_aborted_without_retry(self): self.assert_stalled_once('headers')
    def test_stalled_response_body_is_aborted_without_retry(self): self.assert_stalled_once('body')

    def test_terminal_length_does_not_wait_for_done_or_open_socket_timeout(self):
        with self.fixture('terminal-length-open') as (p, server, watches):
            started = time.monotonic()
            value = p.stream_completion([{'role': 'user', 'content': 'Synthetic fixture only'}])
            self.assertEqual(value, ('', 'Completed allowance.', []))
            self.assertEqual(p._last_finish_reason, 'length')
            self.assertLess(time.monotonic() - started, .7)
            self.assertIsNone(watches[0].error); self.assertEqual(len(server.posts), 1)

    def test_actual_http_checkpoint_resumption_preserves_context_and_final_answer_pass(self):
        with self.fixture('reasoning-resume') as (p, server, watches):
            p._last_context_meta = {'budget': 16000}
            p.agent_worker('test')
            self.assertEqual(len(server.posts), 3)
            self.assertIn('Working discovery 1', json.dumps(server.posts[1]['messages']))
            self.assertIn('Working discovery 2', json.dumps(server.posts[2]['messages']))
            self.assertEqual(server.posts[1]['messages'][-1]['role'], 'user')
            self.assertEqual(server.posts[2]['messages'][-1]['role'], 'user')
            self.assertNotIn('host continuation control', json.dumps(p.session))
            self.assertEqual(server.posts[2]['chat_template_kwargs'], {'enable_thinking': False})
            self.assertEqual(server.posts[2]['tool_choice'], 'none')
            self.assertEqual(p.session['messages'][-1]['content'], 'Answer from the retained discoveries.')
            self.assertEqual(sum(bool(row.get('continuation_checkpoint')) for row in p.session['messages']), 2)
            p.tool_runtime.execute.assert_not_called()
            self.assertTrue(all(watch.error is None for watch in watches))

    def test_partial_visible_http_output_continues_without_duplicating_deltas(self):
        with self.fixture('partial-resume') as (p, server, watches):
            p._last_context_meta = {'budget': 16000}
            p.agent_worker('test')
            self.assertEqual(len(server.posts), 3)
            visible = ''.join(str(data) for kind, data in p.ev.queue if kind == 'content')
            self.assertEqual(visible.count('Visible partial 1.'), 1)
            self.assertEqual(visible.count('Visible partial 2.'), 1)
            self.assertIn('Answer from the retained discoveries.', visible)
            self.assertIn('Visible partial 1.', json.dumps(server.posts[1]['messages']))
            self.assertEqual(sum(bool(row.get('continuation_checkpoint')) for row in p.session['messages']), 2)
            p.tool_runtime.execute.assert_not_called()
    def test_keepalive_comments_do_not_reset_useful_progress_timeout(self): self.assert_stalled_once('keepalive')

    def test_useful_reasoning_deltas_reset_idle_then_content_finishes(self):
        with self.fixture('progress', idle=.18, total=1) as (p, server, watches):
            content, reasoning, calls = p.stream_completion([{'role':'user','content':'Synthetic fixture only'}])
            self.assertEqual(content, 'A complete synthetic reply.'); self.assertEqual(calls, [])
            self.assertIn('fixture step 4', reasoning); self.assertEqual(len(server.posts), 1)
            self.assertIsNone(watches[0].error)
            self.assertTrue(any('reasoning about the request' in str(event) for event in p.ev.queue))
            count = p.ev.qsize(); watches[0].poll()
            self.assertEqual(p.ev.qsize(), count, 'Finished response emitted a late notice')
            self.assertIsNone(p.active_http.conn); self.assertIsNone(p.active_http.sock)

    def test_chunked_sse_body_retains_http_framing_and_complete_reply(self):
        with self.fixture('chunked-progress', idle=.18, total=1) as (p, server, watches):
            content, reasoning, calls = p.stream_completion([{'role':'user','content':'Synthetic fixture only'}])
            self.assertEqual(content, 'A complete synthetic reply.'); self.assertIn('fixture step 4', reasoning)
            self.assertEqual(calls, []); self.assertEqual(len(server.posts), 1)
            self.assertIsNone(watches[0].error)

    def test_deadline_terminates_only_owned_socket_after_active_pointer_changes(self):
        with self.fixture('owned') as (p, server, watches):
            outcome = {}; finished = threading.Event()
            def infer():
                try: outcome['value'] = p.stream_completion([{'role':'user','content':'Synthetic fixture only'}])
                except BaseException as exc: outcome['error'] = exc
                finally: finished.set()
            worker = threading.Thread(target=infer, name='PortalAISyntheticInference')
            worker.start()
            newer_connection = Mock(); newer_socket = Mock()
            try:
                self.assertTrue(server.headers_ready.wait(1))
                p.active_http.conn = newer_connection; p.active_http.sock = newer_socket
                self.assertTrue(finished.wait(.8), 'Abort did not interrupt the original response reader')
                self.assertIsInstance(outcome.get('error'), ResponseStalled)
                self.assertEqual(len(server.posts), 1)
                newer_socket.shutdown.assert_not_called(); newer_connection.close.assert_not_called()
                self.assertIs(p.active_http.conn, newer_connection); self.assertIs(p.active_http.sock, newer_socket)
            finally:
                server.release.set(); worker.join(2)
                self.assertFalse(worker.is_alive(), 'Synthetic inference reader was not joined')

    def test_partial_tool_arguments_never_execute_when_actual_stream_stalls(self):
        with self.fixture('tool-fragment') as (p, server, watches):
            p.agent_worker('test')
            self.assertEqual(len(server.posts), 1)
            p.tool_runtime.execute.assert_not_called()
            self.assertFalse(any(row.get('tool_calls') for row in p.session['messages']))
            self.assertTrue(p.session['messages'][-1].get('content'))
            self.assertTrue(any('preparing a tool call' in str(event) for event in p.ev.queue))
            self.assertIsInstance(watches[0].error, ResponseStalled)

    def test_visible_partial_reply_remains_visible_and_no_tool_is_replayed(self):
        with self.fixture('partial') as (p, server, watches):
            p.agent_worker('test')
            self.assertEqual(len(server.posts), 1); p.tool_runtime.execute.assert_not_called()
            visible = ''.join(str(data) for kind, data in p.ev.queue if kind=='content')
            self.assertIn('Visible partial evidence.', visible)
            self.assertEqual(visible.count('Visible partial evidence.'), 1)
            self.assertIsInstance(watches[0].error, ResponseStalled)
            self.assertTrue(p.session['messages'][-1].get('content'))
            saved = [row for row in p.session['messages'] if row.get('content')=='Visible partial evidence.']
            self.assertEqual(len(saved), 1); self.assertTrue(saved[0].get('incomplete'))
            self.assertNotIn('tool_calls', saved[0]); self.assertIsNone(p._interrupted_reply)

    def test_partial_reply_is_not_saved_after_profile_revocation(self):
        from profile_paths import ProfileLocked
        with self.fixture('partial') as (p, server, watches):
            active = {'value':True}
            original_put = p.ev.put
            def put(event, *args, **kwargs):
                original_put(event, *args, **kwargs)
                if event == ('content', 'Visible partial evidence.'):
                    active['value'] = False
            def check():
                if not active['value']: raise ProfileLocked('synthetic login revoked')
            p.ev.put = put; p._check_login = check
            p.agent_worker('test')
            p.store.save_session.assert_not_called(); p.tool_runtime.execute.assert_not_called()
            self.assertEqual(len(server.posts), 1)
            self.assertFalse(any(row.get('content')=='Visible partial evidence.' for row in p.session['messages']))

    def test_stop_after_partial_reply_saves_it_once_without_success_blocker(self):
        with self.fixture('partial') as (p, server, watches):
            original_put = p.ev.put
            def put(event, *args, **kwargs):
                original_put(event, *args, **kwargs)
                if event == ('content', 'Visible partial evidence.'):
                    p.cancel_event.set()
            p.ev.put = put
            p.agent_worker('test')
            self.assertEqual(len(server.posts), 1); p.tool_runtime.execute.assert_not_called()
            saved = [row for row in p.session['messages'] if row.get('content')=='Visible partial evidence.']
            self.assertEqual(len(saved), 1); self.assertTrue(saved[0].get('cancelled'))
            self.assertNotIn('tool_calls', saved[0])
            self.assertEqual(sum('Visible partial evidence.' in str(data) for kind,data in p.ev.queue if kind=='content'), 1)
            self.assertFalse(any('Blocker:' in str(data) for kind,data in p.ev.queue if kind=='content'))


if __name__ == '__main__': unittest.main()
