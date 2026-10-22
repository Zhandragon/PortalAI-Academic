import asyncio
import importlib.util
from pathlib import Path
import types
import unittest

spec=importlib.util.spec_from_file_location('quick_commands',Path(__file__).resolve().parents[1]/'ha/custom_components/portalai_native/commands.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def request(operation='send'):
    return {'request_id':'a'*32,'viewer':'b'*32,'operation':operation,'binding':{'view':'v','epoch':'e'},'conversation':'chat',**({'text':'Test message'} if operation=='send' else {})}

class QuickChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state={'view':'v','epoch':'e','chat':{'current':'chat','busy':False}}
        self.calls=[];self.lease_calls=[];self.ready=True;self.supported=True
        def read(device):
            if not self.ready:raise PermissionError('No fresh state')
            return {'snapshot':self.state}
        async def dispatch(receiver,device,action,payload):
            self.calls.append((action,payload))
            return {'accepted':True,'request_id':payload['request_id'],'operation':payload['operation']}
        self.dispatch=dispatch
        self.projection=types.SimpleNamespace(connected=lambda d:{'status':{'native_chat_protocol':1 if self.supported else 0}},lease=lambda d,v:self.lease_calls.append(v))
        self.bridge=module.ChatBridge(types.SimpleNamespace(read=read),self.projection,dispatch)

    async def test_send_uses_only_projection_native_chat_and_existing_lease(self):
        result=await self.bridge.execute('device','user',request())
        self.assertTrue(result['accepted']);self.assertEqual(self.calls[0][0],'native_chat')
        self.assertEqual(self.lease_calls,['user:'+('b'*32)])

    async def test_attachment_opt_in_requires_negotiated_host_support(self):
        p={**request(),'include_pending_attachments':True}
        with self.assertRaisesRegex(RuntimeError,'attachment-chat update'):await self.bridge.execute('device','user',p)
        self.assertFalse(self.calls)
        self.projection.connected=lambda d:{'status':{'native_chat_protocol':1,'native_chat_attachment_protocol':1}}
        self.assertTrue(self.bridge.status('device')['attachments_supported'])
        self.assertTrue((await self.bridge.execute('device','user',p))['accepted'])
        self.assertIs(self.calls[0][1]['include_pending_attachments'],True)

    def test_attachment_opt_in_is_send_only_and_strict_boolean(self):
        for p in [{**request(),'include_pending_attachments':False},{**request(),'include_pending_attachments':1},{**request('stop'),'include_pending_attachments':True}]:
            with self.assertRaises(ValueError):module.validate(p)

    async def test_duplicate_is_not_reexecuted_and_conflicting_duplicate_refused(self):
        await self.bridge.execute('device','user',request());await self.bridge.execute('device','user',request())
        self.assertEqual(len(self.calls),1)
        for user,payload in [('other',request()),('user',{**request(),'text':'Different'})]:
            with self.assertRaises(PermissionError):await self.bridge.execute('device',user,payload)

    async def test_expired_account_or_conversation_refuses_without_dispatch(self):
        for change in [lambda:setattr(self,'ready',False),lambda:self.state.update(epoch='changed'),lambda:self.state['chat'].update(current='other')]:
            self.setUp();change()
            with self.assertRaises(PermissionError):await self.bridge.execute('device','user',request())
            self.assertFalse(self.calls)

    async def test_busy_send_rejected_stop_accepted(self):
        self.state['chat']['busy']=True
        with self.assertRaises(RuntimeError):await self.bridge.execute('device','user',request())
        self.assertTrue((await self.bridge.execute('device','user',request('stop')))['accepted'])

    async def test_unsupported_host_or_other_controller_refused(self):
        self.supported=False
        with self.assertRaises(RuntimeError):await self.bridge.execute('device','user',request())
        self.supported=True
        def refuse(*args):raise PermissionError('Another viewer')
        self.projection.lease=refuse
        with self.assertRaises(PermissionError):await self.bridge.execute('device','user',request())
        self.assertFalse(self.calls)

    async def test_simultaneous_duplicate_shares_one_pending_effect(self):
        gate=asyncio.Event()
        async def slow(*args):await gate.wait();return await self.dispatch(*args)
        self.bridge.dispatch=slow
        one=asyncio.create_task(self.bridge.execute('device','user',request()))
        await asyncio.sleep(0)
        two=asyncio.create_task(self.bridge.execute('device','user',request()))
        gate.set();await asyncio.gather(one,two);self.assertEqual(len(self.calls),1)

    async def test_timeout_is_not_retried_on_repeat(self):
        async def fail(*args):self.calls.append('failed');raise RuntimeError('Outcome unknown')
        self.bridge.dispatch=fail
        for _ in range(2):
            with self.assertRaises(RuntimeError):await self.bridge.execute('device','user',request())
        self.assertEqual(len(self.calls),1)

    async def test_no_false_success_from_unmatched_host_ack(self):
        async def wrong(*args):return {'accepted':True,'request_id':'wrong','operation':'send'}
        self.bridge.dispatch=wrong
        with self.assertRaisesRegex(RuntimeError,'unknown'):await self.bridge.execute('device','user',request())

    async def test_lock_between_request_and_dispatch_refuses(self):
        original=self.bridge.check;count=0
        def check(*args):
            nonlocal count
            count+=1
            if count>1:raise PermissionError('Locked')
            return original(*args)
        self.bridge.check=check
        with self.assertRaises(PermissionError):await self.bridge.execute('device','user',request())
        self.assertFalse(self.calls)

    def test_schema_rejects_extra_fields_wrong_types_and_oversized_text(self):
        for p in [{**request(),'service':'light.turn_on'},{**request(),'text':'x'*8193},{**request(),'text':'\ud800'},
                  {**request(),'text':'  '},{**request(),'request_id':'../bad'},{**request('stop'),'text':'ignored'},
                  {**request(),'binding':{'view':'v','epoch':'e','account':'other'}},{**request(),'conversation':None}]:
            with self.assertRaises(ValueError):module.validate(p)
        self.assertEqual(module.validate({**request(),'text':'😀'*8192})['text'],'😀'*8192)

if __name__=='__main__':unittest.main()
