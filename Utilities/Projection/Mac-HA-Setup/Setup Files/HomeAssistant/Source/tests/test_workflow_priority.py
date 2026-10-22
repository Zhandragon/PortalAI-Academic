"""Regression checks for reserved Stop/Exit capacity, without host actions."""
import asyncio
import importlib.util
from pathlib import Path
import time
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
w=load('workflows','ha/custom_components/portalai_native/workflows.py')
r=load('receiver','ha/custom_components/portalai_projection/receiver.py')

def request(index,action='controls_startup'):
    return {'request_id':f'{index:032x}','viewer':'b'*32,'operation':'invoke',
            'binding':{'view':'v','epoch':'e'},'form':'f','action':action,'values':{}}

class PriorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_and_unsupported_are_distinct_without_dispatch(self):
        hub=types.SimpleNamespace(permitted=lambda d:True)
        def offline(device): raise RuntimeError('Projection offline or screen stale')
        projection=types.SimpleNamespace(connected=offline)
        bridge=w.WorkflowBridge(hub,projection,None)
        self.assertEqual(bridge.status('d')['reason'],'offline')
        with self.assertRaisesRegex(RuntimeError,'offline'):
            bridge.check('d',{'operation':'describe'})
        projection.connected=lambda d:{'status':{}}
        self.assertEqual(bridge.status('d')['reason'],'unsupported')
        with self.assertRaisesRegex(RuntimeError,'connected Aoostar'):
            bridge.check('d',{'operation':'describe'})
        projection.connected=lambda d:{'status':{'native_ui_protocol':1}}
        self.assertTrue(bridge.status('d')['supported'])
        hub.permitted=lambda d:False
        with self.assertRaises(PermissionError): bridge.status('d')

    async def test_saturation_retains_stop_capacity_and_account_checks(self):
        gate=asyncio.Event();calls=[];leases=[]
        async def dispatch(projection,device,action,payload):
            calls.append(payload['request_id']);await gate.wait()
            return {'accepted':True,'request_id':payload['request_id'],'operation':'invoke'}
        projection=types.SimpleNamespace(connected=lambda d:{'status':{'native_ui_protocol':1}},lease=lambda d,v:leases.append(v))
        hub=types.SimpleNamespace(permitted=lambda d:True,read=lambda d:{'snapshot':{'view':'v','epoch':'e'}})
        bridge=w.WorkflowBridge(hub,projection,dispatch)
        bridge.views['d']={'at':time.monotonic(),'binding':{'view':'v','epoch':'e'},'ready':True}
        tasks=[asyncio.create_task(bridge.execute('d','u',request(i))) for i in range(4)]
        await asyncio.sleep(0);await asyncio.sleep(0)
        with self.assertRaises(RuntimeError):await bridge.execute('d','u',request(4))
        # Full ordinary receipt capacity must not prevent a safety request.
        receipt=next(iter(bridge.receipts.values()))
        bridge.receipts.update({('old',str(i)):receipt for i in range(508)})
        stop=request(5,'controls_stop');exit_request=request(6,'controls_exit')
        tasks.extend([asyncio.create_task(bridge.execute('d','u',p)) for p in (stop,exit_request,stop)])
        await asyncio.sleep(0);await asyncio.sleep(0)
        self.assertEqual(len(calls),6);self.assertEqual(len(leases),6)
        with self.assertRaises(RuntimeError):await bridge.execute('d','u',request(7,'chat_stop'))
        with self.assertRaises(PermissionError):await bridge.execute('d','u',{**stop,'values':{'x':'different'}})
        with self.assertRaises(PermissionError):await bridge.execute('d','u',{**stop,'binding':{'view':'wrong','epoch':'e'}})
        gate.set();await asyncio.gather(*tasks)
        self.assertEqual(bridge.pending['d'],0);self.assertEqual(bridge.safety_pending['d'],0)

    async def test_transport_reserves_slots_and_bounds_future_replies(self):
        receiver=r.Receiver();state={'updated':time.monotonic(),'queue':[],'replies':{}}
        receiver.devices['d']=state
        for _ in range(30):receiver.enqueue('d','native_ui',request(1))
        with self.assertRaises(RuntimeError):receiver.enqueue('d','native_ui',request(2))
        stop=receiver.enqueue('d','native_ui',request(3,'controls_stop'))
        self.assertEqual(state['queue'][0]['id'],stop)
        receiver.enqueue('d','native_ui',request(4,'controls_exit'))
        with self.assertRaises(RuntimeError):receiver.enqueue('d','native_ui',request(5,'chat_stop'))
        state['queue']=[];state['replies']={str(i):None for i in range(62)}
        with self.assertRaises(RuntimeError):receiver.enqueue('d','native_ui',request(6))
        receiver.enqueue('d','native_ui',request(7,'controls_stop'))
        receiver.enqueue('d','native_ui',request(8,'controls_exit'))
        with self.assertRaises(RuntimeError):receiver.enqueue('d','native_ui',request(9,'chat_stop'))

if __name__=='__main__':unittest.main()
