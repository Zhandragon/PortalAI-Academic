import asyncio,base64,importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parent.parent/'ha/custom_components'
pkg=types.ModuleType('rich_fixture');pkg.__path__=[str(ROOT/'portalai_native')];sys.modules['rich_fixture']=pkg
from rich_fixture.rich_chat import RichBridge, RichUnavailable
spec=importlib.util.spec_from_file_location('demand_fixture',ROOT/'portalai_projection/viewer_demand.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setup_bridge(self):
        self.device='d'*32;self.connection=types.SimpleNamespace(user=types.SimpleNamespace(id='admin'))
        self.book=d.DemandBook({self.device:{'fingerprint':'paired'}},lambda _:True)
        self.p={'protocol':1,'request_id':'a'*32,'viewer':'b'*32,'operation':'rich_index','binding':{'view':'v','epoch':'e'},'conversation':'chat'}
        self.hub=Mock();self.hub.read.return_value={'snapshot':{'view':'v','epoch':'e','chat':{'current':'chat'}}}
        self.projection=Mock();self.projection.connected.return_value={'status':{'native_rich_protocol':1}}
        self.reply={'accepted':True,'operation':'rich_index','request_id':'a'*32,'rich':{'protocol':1,'binding':self.p['binding'],'conversation':'chat','blocks':[],'truncated':False}}
        self.calls=[]
        async def dispatch(*args):self.calls.append(args);return self.reply
        self.bridge=RichBridge(self.hub,self.projection,dispatch,self.book)
    def acquire(self):self.book.change(self.device,self.connection,self.p['viewer'],'native','acquire')
    async def test_no_viewer_no_reads_and_exact_connection(self):
        self.setup_bridge()
        with self.assertRaises(RichUnavailable):await self.bridge.execute(self.device,self.connection,self.p)
        self.acquire();other=types.SimpleNamespace(user=self.connection.user)
        with self.assertRaises(RichUnavailable):await self.bridge.execute(self.device,other,self.p)
        self.assertEqual(self.calls,[])
        self.assertEqual(await self.bridge.execute(self.device,self.connection,self.p),self.reply)
        self.projection.lease.assert_not_called()
    async def test_disconnect_account_change_pairing_revoke_after_dispatch(self):
        for mutation in ('viewer','account','pairing'):
            self.setup_bridge();self.acquire()
            async def dispatch(*args):
                if mutation=='viewer':self.book.change(self.device,self.connection,self.p['viewer'],'native','release')
                elif mutation=='account':self.hub.read.return_value['snapshot']['epoch']='changed'
                else:self.book.approved.clear()
                return self.reply
            self.bridge.dispatch=dispatch
            with self.assertRaises(RichUnavailable):await self.bridge.execute(self.device,self.connection,self.p)
            self.assertEqual(self.bridge.pending[self.device],0)
    async def test_strict_reply_and_bounded_read_capacity(self):
        self.setup_bridge();self.acquire();self.bridge.pending[self.device]=2
        with self.assertRaises(RuntimeError):await self.bridge.execute(self.device,self.connection,self.p)
        self.bridge.pending[self.device]=0;self.reply['rich']['url']='http://untrusted'
        with self.assertRaises(RichUnavailable):await self.bridge.execute(self.device,self.connection,self.p)
        self.assertEqual(self.bridge.pending[self.device],0)

    async def test_media_batch_and_safe_legacy_rollout(self):
        for current in (True,False):
            self.setup_bridge();self.acquire()
            self.p.update(operation='rich_media_batch',protocol=2,block='file',offset=0)
            if current:self.projection.connected.return_value['status']['native_media_batch_protocol']=1
            chunk=b'x'*(262144 if current else 24576)
            async def dispatch(_,device,action,wire):
                self.assertEqual(wire['operation'],'rich_media_batch' if current else 'rich_media')
                return {'accepted':True,'request_id':wire['request_id'],'operation':wire['operation'],
                        'rich':{'protocol':wire['protocol'],'binding':wire['binding'],'conversation':wire['conversation'],
                                'block':'file','offset':0,'next':len(chunk),'size':605208,'mime':'video/mp4','name':'fixture.mp4',
                                'data':base64.b64encode(chunk).decode(),'eof':False,'identity':'same-file'}}
            self.bridge.dispatch=dispatch
            result=await self.bridge.execute(self.device,self.connection,self.p)
            self.assertEqual(result['operation'],'rich_media_batch');self.assertEqual(result['rich']['protocol'],2)
            self.assertEqual(result['rich']['next'],len(chunk));self.projection.lease.assert_not_called()

    async def test_diagnostics_distinguish_missing_support_from_host_failure_without_leaking_text(self):
        self.setup_bridge();self.acquire();self.projection.connected.return_value={'status':{}}
        with self.assertRaises(RichUnavailable) as found:await self.bridge.execute(self.device,self.connection,self.p)
        self.assertEqual(found.exception.code,'host_update')
        self.projection.connected.return_value={'status':{'native_rich_protocol':1}}
        async def fail(*args):raise RuntimeError('private-path-and-token-fixture')
        self.bridge.dispatch=fail
        with self.assertRaises(RichUnavailable) as found:await self.bridge.execute(self.device,self.connection,self.p)
        self.assertEqual(found.exception.code,'host_read');self.assertNotIn('private-path',str(found.exception))

if __name__=='__main__':unittest.main()
