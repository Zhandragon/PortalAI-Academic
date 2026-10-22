import asyncio,base64,importlib.util,json,time,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
w=load('upload_workflows','ha/custom_components/portalai_native/workflows.py')
r=load('upload_receiver','ha/custom_components/portalai_projection/receiver.py')
d=load('upload_demand','ha/custom_components/portalai_projection/viewer_demand.py')
def chunk(size=1048576,**extra):
    return dict(request_id='a'*32,viewer='b'*32,operation='file_chunk_v2',protocol=2,binding={'view':'v','epoch':'e'},transfer='t',offset=0,data=base64.b64encode(b'x'*size).decode(),**extra)

class UploadTests(unittest.IsolatedAsyncioTestCase):
    def test_strict_v2_and_unchanged_legacy_limits(self):
        p=chunk();self.assertEqual(w.validate_request(p),p)
        for bad in [chunk(1048577),{**p,'protocol':True},{**p,'protocol':'2'},{**p,'other':1},{**p,'data':'invalid!'}, {**p,'offset':True}]:
            with self.assertRaises(ValueError):w.validate_request(bad)
        p.pop('protocol');p['operation']='file_chunk'
        with self.assertRaises(ValueError):w.validate_request(p)
        p['data']=base64.b64encode(b'x'*24576).decode();w.validate_request(p)
    async def test_negotiation_bulk_capacity_stop_and_cancel_cleanup(self):
        gate=asyncio.Event();host={'native_ui_protocol':1,'native_file_upload_protocol':2}
        async def dispatch(_,device,action,p):
            await gate.wait();return dict(accepted=True,request_id=p['request_id'],operation=p['operation'],offset=1048576)
        bridge=w.WorkflowBridge(SimpleNamespace(permitted=lambda d:True,read=lambda d:{'snapshot':{'view':'v','epoch':'e'}}),SimpleNamespace(connected=lambda d:{'status':host},lease=lambda *a:None),dispatch)
        bridge.views['d']={'at':time.monotonic(),'binding':{'view':'v','epoch':'e'},'ready':True}
        self.assertEqual(bridge.status('d')['upload_protocol'],2)
        task=asyncio.create_task(bridge.execute('d','u',chunk()));await asyncio.sleep(0)
        with self.assertRaisesRegex(RuntimeError,'already pending'):await bridge.execute('d','u',chunk())
        stop=asyncio.create_task(bridge.execute('d','u',dict(request_id='c'*32,viewer='b'*32,operation='invoke',binding={'view':'v','epoch':'e'},form='f',action='chat_stop',values={})))
        await asyncio.sleep(0);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertNotIn('d',bridge.bulk_pending);gate.set();await stop
        self.assertEqual(bridge.pending['d'],0);self.assertEqual(bridge.safety_pending['d'],0)
        for flag in [None,True,2.0,'2',1]:
            host['native_file_upload_protocol']=flag
            self.assertEqual(bridge.status('d')['upload_protocol'],1)
            with self.assertRaises(RuntimeError):bridge.check('d',chunk(1))
    def test_poll_budget_defers_second_chunk_without_losing_stop_or_reply_identity(self):
        rec=r.Receiver({'d':{}});state={'updated':time.monotonic(),'queue':[],'replies':{},'status':{'native_file_upload_protocol':2}}
        rec.devices['d']=state;rec.sessions['token']={'device_id':'d','expires':time.monotonic()+60,'sequence':0}
        first=rec.enqueue('d','native_ui',chunk());second=rec.enqueue('d','native_ui',chunk())
        stop=rec.enqueue('d','native_ui',{'operation':'invoke','action':'chat_stop'})
        reply=rec.poll('token',{'sequence':1,'status':state['status']})
        self.assertEqual([x['id'] for x in reply['commands']],[stop,first]);self.assertLess(len(json.dumps(reply).encode()),1800000)
        self.assertEqual([x['id'] for x in state['queue']],[second]);self.assertNotIn(second,state['replies'])
        reply=rec.poll('token',{'sequence':2,'status':state['status']});self.assertEqual(reply['commands'][0]['id'],second)
        state['queue']=[]
        expired=rec.enqueue('d','native_ui',chunk());state['queue'][0]['expires']=0
        self.assertEqual(rec.poll('token',{'sequence':3})['commands'],[]);self.assertNotIn(expired,state['replies'])
    def test_large_exception_does_not_apply_to_ordinary_commands(self):
        rec=r.Receiver();rec.devices['d']={'updated':time.monotonic(),'queue':[],'replies':{},'status':{'native_file_upload_protocol':2}}
        for action,p in [('input',chunk()),('native_ui',{**chunk(),'operation':'invoke'}),('native_ui',{**chunk(),'protocol':True})]:
            with self.assertRaises(ValueError):rec.enqueue('d',action,p)

class GraceTests(unittest.TestCase):
    def fixture(self):
        now=[100.];book=d.DemandBook({'a'*32:{'fingerprint':'fp'}},lambda _:True,clock=lambda:now[0]);connection=SimpleNamespace(user=SimpleNamespace(id='u'))
        def change(action):book.change('a'*32,connection,'b'*32,'native',action)
        change('acquire');return now,book,change
    def test_server_holds_ten_seconds_without_phone_timers_and_cannot_be_renewed_while_hidden(self):
        now,book,change=self.fixture();change('background');now[0]+=9;change('background');change('renew');change('acquire')
        self.assertTrue(book.packet('a'*32)['native']);now[0]+=1;self.assertFalse(book.packet('a'*32)['native'])
        with self.assertRaises(PermissionError):change('foreground')
    def test_return_inside_grace_and_explicit_release(self):
        now,book,change=self.fixture();change('background');now[0]+=9;change('foreground');now[0]+=2
        self.assertTrue(book.packet('a'*32)['native']);change('release');self.assertFalse(book.packet('a'*32)['native'])
    def test_pairing_revocation_still_clears_immediately(self):
        now,book,change=self.fixture();change('background');book.approved.clear();self.assertFalse(book.packet('a'*32)['native'])

if __name__=='__main__':unittest.main()
