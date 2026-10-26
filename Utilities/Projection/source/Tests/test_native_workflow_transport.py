"""Focused transport bounds/priority; synthetic loopback results only."""
import json,queue,sys,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
MOD=Path(__file__).resolve().parents[1];ROOT=MOD.parent/'PortalAI'
sys.path[:0]=[str(MOD/'app'),str(ROOT/'Agent')]
import projection_worker as worker
from portalai_target import Manager


class TransportTests(unittest.TestCase):
    def test_media_batch_bound_queue_order_wakeup_and_idle_pacing(self):
        wake=threading.Event();q=worker.ReplyQueue(wake)
        row=lambda i:{'id':str(i),'result':{'operation':'rich_media_batch','rich':{'protocol':2,'data':'x'*349528}}}
        first,second=row(1),row(2);q.put(first);q.put(second);self.assertTrue(wake.is_set())
        client=Mock();manager=Mock();manager.status.return_value={}
        worker.poll_ready(client,manager,None,q)
        self.assertEqual(client.poll.call_args.args[2],[first]);self.assertEqual(q.get_nowait(),second)
        now=[10.];pacer=worker.PollPacer(lambda:now[0]);pacer.command({'action':'native_ui','payload':{'operation':'rich_media_batch'}})
        self.assertEqual(pacer.delay('active',True),.05)
        self.assertEqual(pacer.delay('standby',True),2);self.assertEqual(pacer.delay('active',False),.65)
        now[0]+=2.1;self.assertEqual(pacer.delay('active',True),.65)

    def test_only_explicit_media_batch_gets_large_local_reply_bound(self):
        m=Manager(ROOT,Mock());m.native_chat_endpoint=Mock(return_value=({'hwnd':100},{'port':23456,'token':'x'*40}))
        p={'request_id':'a'*32,'viewer':'b'*32,'operation':'rich_media_batch','protocol':2}
        reply={'accepted':True,'request_id':p['request_id'],'operation':p['operation'],'rich':{'protocol':2,'data':'x'*349528}}
        response=Mock(status=200);response.read.return_value=json.dumps(reply).encode();connection=Mock();connection.getresponse.return_value=response
        with patch('http.client.HTTPConnection',return_value=connection):self.assertEqual(m.native_ui(p,time.monotonic()+3),reply)
        self.assertEqual(response.read.call_args.args,(360001,));self.assertIsNone(m.viewer)

    def test_upload_burst_has_no_idle_penalty_or_background_polling(self):
        for operation in ('file_begin','file_chunk','file_chunk_v2','file_commit','rich_preview'):
            now=[0.];pacer=worker.PollPacer(lambda:now[0]);pacer.command({'action':'native_ui','payload':{'operation':operation}})
            self.assertEqual(pacer.delay('active',True),.05)
            self.assertEqual(pacer.delay('standby',True),2)
            self.assertEqual(pacer.delay('active',False),.65)
            now[0]=2.1;self.assertEqual(pacer.delay('active',True),.65)

    def test_failed_https_post_closes_connection_without_retry(self):
        from projection_client import Client
        from connection_vault import new_connection
        client=Client(new_connection('https://example.invalid','../PortalAI','Fixture'),MOD/'Runtime/cacert.pem')
        connection=Mock();connection.request.side_effect=OSError('Synthetic connection loss')
        with patch('projection_client.http.client.HTTPSConnection',return_value=connection) as make:
            with self.assertRaises(OSError):client.request({'action':'poll','sequence':1})
        self.assertEqual(make.call_count,1);self.assertEqual(connection.request.call_count,1)
        connection.close.assert_called_once();self.assertIsNone(client.connection)

    def test_utf8_budget_leaves_remainder_in_original_order(self):
        q=queue.Queue();items=[{'id':str(i),'result':{'text':'é'*31800}} for i in range(10)]
        for row in items:q.put(row)
        client=Mock();manager=Mock();manager.status.return_value={}
        worker.poll_ready(client,manager,None,q)
        batch=client.poll.call_args.args[2]
        self.assertLessEqual(len(json.dumps(batch,ensure_ascii=False,separators=(',',':')).encode()),512000)
        self.assertEqual(batch,items[:len(batch)])
        self.assertEqual(q.get_nowait(),items[len(batch)])
        self.assertEqual(len(batch),8)

    def test_oversized_individual_reply_is_explicit_error(self):
        q=queue.Queue();q.put({'id':'a','result':'x'*65001});client=Mock()
        worker.poll_ready(client,Mock(),None,q)
        self.assertIn('do not replay',client.poll.call_args.args[2][0]['error'])

    def test_reply_budget_matches_receiver_serialization_at_boundary(self):
        q=queue.Queue();items=[]
        for i in range(8):
            row={'id':str(i),'result':{'text':''}}
            overhead=len(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode())
            row['result']['text']='x'*(63998-overhead);items.append(row);q.put(row)
        self.assertLessEqual(len(json.dumps(items,separators=(',',':')).encode()),512000)
        self.assertGreater(len(json.dumps(items).encode()),512000)
        client=Mock();worker.poll_ready(client,Mock(),None,q)
        batch=client.poll.call_args.args[2]
        self.assertLessEqual(len(json.dumps(batch,ensure_ascii=False).encode()),512000)
        self.assertEqual(batch,items[:7]);self.assertEqual(q.get_nowait(),items[7])

    def test_priority_is_narrow_and_fixed(self):
        for action in ('controls_stop','controls_exit','chat_stop','account_close'):
            self.assertTrue(worker.priority_command({'action':'native_ui','payload':{'operation':'invoke','action':action}}))
        self.assertFalse(worker.priority_command({'action':'native_ui','payload':{'operation':'invoke','action':'anything_else'}}))

    def test_describe_preserves_lease_large_ack_and_deadline(self):
        m=Manager(ROOT,Mock());endpoint={'port':23456,'token':'x'*40}
        m.native_chat_endpoint=Mock(return_value=({'hwnd':100},endpoint))
        p={'request_id':'a'*32,'viewer':'b'*32,'operation':'describe','page':'chat'}
        reply={'accepted':True,'request_id':p['request_id'],'operation':'describe','message':'x'*6000}
        response=Mock(status=200);response.read.return_value=json.dumps(reply).encode()
        connection=Mock();connection.getresponse.return_value=response
        m._lease('f'*32);lease=m.viewer;deadline=time.monotonic()+3
        with patch('http.client.HTTPConnection',return_value=connection):self.assertEqual(m.native_ui(p,deadline),reply)
        self.assertEqual(m.viewer,lease)
        sent=json.loads(connection.request.call_args.args[2]);self.assertEqual(sent['expires_at'],deadline)
        self.assertEqual(sent['event']['payload'],p)
        self.assertEqual(response.read.call_args.args,(65001,))

    def test_stop_does_not_wait_on_normal_input_lock(self):
        m=Manager(ROOT,Mock());entered=threading.Event();release=threading.Event()
        def hold():
            with m.input_lock:entered.set();release.wait(2)
        thread=threading.Thread(target=hold);thread.start();self.assertTrue(entered.wait(1))
        m.native_chat_endpoint=Mock(return_value=({'hwnd':100},{'port':23456,'token':'x'*40}))
        p={'request_id':'a'*32,'viewer':'b'*32,'operation':'stop'}
        response=Mock(status=200);response.read.return_value=json.dumps({'accepted':True,'request_id':'a'*32,'operation':'stop'}).encode()
        connection=Mock();connection.getresponse.return_value=response
        try:
            start=time.monotonic()
            with patch('http.client.HTTPConnection',return_value=connection):m.native_chat(p,time.monotonic()+1)
            self.assertLess(time.monotonic()-start,.3)
        finally:release.set();thread.join()


if __name__=='__main__':unittest.main()
