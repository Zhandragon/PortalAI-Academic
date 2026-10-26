"""Bounded local input/ack tests; no production accounts or HA connection."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

MODULE=Path(__file__).resolve().parents[1]
PORTAL=default_target()
sys.path[:0]=[str(MODULE/'app'),str(PORTAL/'ControlCenter'),str(PORTAL/'Agent')]
import portalai_target
import projection_worker
import remote_desktop_input as remote


class DeliveryTests(unittest.TestCase):
    def test_reply_completed_during_status_is_sent_in_same_poll(self):
        replies=queue.Queue();reply={'id':'a'*32,'result':{'accepted':True}}
        manager=Mock()
        def status():
            replies.put(reply)
            return {'running':True}
        manager.status.side_effect=status
        client=Mock();client.poll.return_value=[]
        projection_worker.poll_ready(client,manager,None,replies)
        client.poll.assert_called_once_with(None,{'running':True},[reply])

    def test_stalled_input_does_not_block_status_but_still_orders_lifecycle(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                entered.set();release.wait(2)
                data=b'{"accepted":true}'
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=HTTPServer(('127.0.0.1',0),Handler)
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        manager=portalai_target.Manager(PORTAL,Mock());manager.inventory=lambda fresh=False:{}
        manager.windows['window']={'hwnd':1,'class':'TkTopLevel'}
        manager.endpoint=lambda _: {'port':server.server_port,'token':'synthetic'}
        errors=[]
        def input():
            try:manager.input({'viewer':'a'*32,'window':'window'})
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=input);worker.start()
        lifecycle=None
        try:
            self.assertTrue(entered.wait(1))
            manager._operate=lambda *args:None
            def restart():
                manager.lifecycle('restart',{'request_id':uuid.uuid4().hex});finished.set()
            lifecycle=threading.Thread(target=restart);lifecycle.start()
            with patch('profile_shutdown._marker',return_value=None):
                start=time.monotonic();status=manager.status();elapsed=time.monotonic()-start
            self.assertLess(elapsed,.2)
            self.assertEqual(status['operation']['state'],'idle')
            self.assertFalse(finished.is_set(),'Lifecycle overtook unacknowledged input')
        finally:
            release.set();worker.join(3)
            if lifecycle:lifecycle.join(3)
            server.shutdown();server.server_close();serving.join(2)
        self.assertFalse(errors);self.assertTrue(finished.is_set())

    def test_input_expiring_behind_lock_never_dispatches(self):
        manager=portalai_target.Manager(PORTAL,Mock())
        manager.windows['window']={'hwnd':1,'class':'TkTopLevel'}
        errors=[]
        deadline=time.monotonic()+.04
        def run():
            try:manager.input({'viewer':'a'*32,'window':'window'},deadline=deadline)
            except Exception as exc:errors.append(exc)
        with manager.input_lock:
            thread=threading.Thread(target=run);thread.start();time.sleep(.06)
        thread.join(1)
        self.assertIsInstance(errors[0],TimeoutError)
        manager.desktop.validate.assert_not_called()

    def test_validation_cannot_renew_expired_input(self):
        manager=portalai_target.Manager(PORTAL,Mock())
        manager.windows['window']={'hwnd':1,'class':'#32770'}
        manager.desktop.validate.side_effect=lambda _:time.sleep(.04)
        with self.assertRaises(TimeoutError):
            manager.input({'viewer':'a'*32,'window':'window'},deadline=time.monotonic()+.02)
        manager.desktop.input.assert_not_called()

    def test_deadline_is_forwarded_and_only_explicit_ack_succeeds(self):
        manager=portalai_target.Manager(PORTAL,Mock())
        manager.windows['window']={'hwnd':1,'class':'TkTopLevel'}
        manager.endpoint=lambda _: {'port':12345,'token':'synthetic'}
        response=Mock();response.status=200
        connection=Mock();connection.getresponse.return_value=response
        deadline=time.monotonic()+3
        with patch('http.client.HTTPConnection',return_value=connection):
            for value in ({}, {'accepted':False}, ['accepted']):
                response.read.return_value=json.dumps(value).encode()
                with self.assertRaisesRegex(RuntimeError,'Invalid GUI acknowledgement'):
                    manager.input({'viewer':'a'*32,'window':'window'},deadline=deadline)
            value={'accepted':True,'timing_ms':{'queue':12,'apply':1}}
            response.read.return_value=json.dumps(value).encode()
            self.assertEqual(manager.input({'viewer':'a'*32,'window':'window'},deadline=deadline),value)
        sent=json.loads(connection.request.call_args.args[2])
        self.assertEqual(sent['expires_at'],deadline)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        destination=MODULE/'Tests/Validation';destination.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=destination)
        self.app=Mock()
        with patch.object(remote.InputAdapter,'publish_endpoint'):
            self.adapter=remote.InputAdapter(self.app,Path(self.temp.name))
        self.adapter.wake=Mock(return_value=True)
        self.adapter.apply=Mock(return_value=None)

    def tearDown(self):
        self.adapter.closed=True
        self.adapter.server.shutdown();self.adapter.server.server_close()
        self.temp.cleanup()

    def request(self,item,token=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.adapter.server.server_port,timeout=2)
        try:
            conn.request('POST','/input',json.dumps(item),{'Authorization':'Bearer '+(self.adapter.token if token is None else token),'Content-Type':'application/json'})
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()

    def item(self,**extra):
        return {'hwnd':1,'event':{'kind':'text','text':'synthetic'},'request_id':uuid.uuid4().hex,**extra}

    def test_authentication_precedes_queue_and_wake(self):
        status,result=self.request(self.item(),token='incorrect')
        self.assertEqual(status,400);self.assertIn('capability refused',result['error'])
        self.adapter.wake.assert_not_called();self.assertTrue(self.adapter.pending.empty())

    def test_remote_expiry_is_not_reset(self):
        for value in (time.monotonic()-1,float('nan'),float('inf'),True):
            with self.subTest(value=value):
                status,result=self.request(self.item(expires_at=value))
                self.assertEqual(status,400)
        self.adapter.apply.assert_not_called();self.assertTrue(self.adapter.pending.empty())

    def test_wake_is_not_an_ack_and_expired_request_never_applies(self):
        with patch.object(remote,'ACK_TIMEOUT',.08):
            status,result=self.request(self.item())
        self.assertEqual(status,400);self.assertIn('do not replay blindly',result['error'])
        self.assertIsNone(result['timing_ms']['apply'])
        self.adapter.wake.assert_called()
        self.adapter.pump()
        self.adapter.apply.assert_not_called()

    def test_real_queue_ack_timing_and_duplicate_does_not_reapply(self):
        item=self.item();replies=[]
        thread=threading.Thread(target=lambda:replies.append(self.request(item)));thread.start()
        until=time.monotonic()+1
        while self.adapter.pending.empty() and time.monotonic()<until:time.sleep(.001)
        self.assertFalse(self.adapter.pending.empty())
        self.adapter.pump();thread.join(2)
        self.assertEqual(replies[0][0],200);self.assertTrue(replies[0][1]['accepted'])
        self.assertGreaterEqual(replies[0][1]['timing_ms']['queue'],0)
        self.assertGreaterEqual(replies[0][1]['timing_ms']['apply'],0)
        self.assertEqual(self.request(item),replies[0])
        self.adapter.apply.assert_called_once_with(item)

    def test_expired_job_in_queue_is_not_applied(self):
        now=time.monotonic()
        job={'item':self.item(),'done':threading.Event(),'expires':now-1,'queued_at':now-2,'started':False}
        self.adapter.pending.put(job);self.adapter.pump()
        self.assertTrue(job['done'].is_set());self.assertIn('Expired',job['error'])
        self.adapter.apply.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows HWND ownership')
    def test_wake_refuses_foreign_process_or_thread(self):
        # No native call can reach another process, even if an HWND is reused.
        user=Mock()
        self.adapter.hwnd=123;self.adapter.ui_thread=456
        def identity(hwnd,pid):
            pid._obj.value=os.getpid()+1
            return 456
        user.GetWindowThreadProcessId.side_effect=identity
        with patch.object(remote.ctypes,'WinDLL',return_value=user),patch.object(remote.os,'name','nt'):
            self.assertFalse(remote.InputAdapter.wake(self.adapter))
        user.PostMessageW.assert_not_called()
        def wrong_thread(hwnd,pid):
            pid._obj.value=os.getpid()
            return 457
        user.GetWindowThreadProcessId.side_effect=wrong_thread
        with patch.object(remote.ctypes,'WinDLL',return_value=user),patch.object(remote.os,'name','nt'):
            self.assertFalse(remote.InputAdapter.wake(self.adapter))
        user.PostMessageW.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
