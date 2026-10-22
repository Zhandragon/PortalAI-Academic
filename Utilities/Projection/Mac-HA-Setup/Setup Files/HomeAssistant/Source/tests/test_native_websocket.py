"""Real aiohttp socket tests with the HA registration/auth shell stubbed.

Device signatures are tested with real P-256 separately in test_native_receiver.
This suite tests wire framing, replacement, rejection and subscriber cleanup.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from aiohttp import web, ClientSession, WSServerHandshakeError
from aiohttp.test_utils import TestServer

ROOT=Path(__file__).resolve().parents[1]
def module(name,**attrs):
    m=types.ModuleType(name);m.__dict__.update(attrs);sys.modules[name]=m;return m
vol=module('voluptuous',Schema=lambda *a,**k:None,Optional=lambda v:v,Required=lambda v:v,ALLOW_EXTRA=object())
module('homeassistant');module('homeassistant.components')
module('homeassistant.components.websocket_api',websocket_command=lambda *a:lambda fn:fn,require_admin=lambda fn:fn,async_response=lambda fn:fn)
module('homeassistant.components.http',HomeAssistantView=object)
module('homeassistant.const',EVENT_HOMEASSISTANT_STOP='stop')
module('homeassistant.exceptions',Unauthorized=PermissionError,HomeAssistantError=RuntimeError)
module('homeassistant.helpers');module('homeassistant.helpers.storage',Store=object)
spec=importlib.util.spec_from_file_location('native_web_test',ROOT/'ha/custom_components/portalai_native/__init__.py',submodule_search_locations=[str(ROOT/'ha/custom_components/portalai_native')])
native=importlib.util.module_from_spec(spec);sys.modules[spec.name]=native;spec.loader.exec_module(native)
PROTOCOL=native.PROTOCOL

class SocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.device='a'*32
        self.hub=native.NativeHub({self.device:{'fingerprint':'test'}},{self.device:'test'})
        self.hub.authenticate=lambda device,nonce,signature: self.assertEqual(signature,'test-signature')
        self.receiver=native.NativeReceiver(None,self.hub)
        app=web.Application();app.router.add_get('/api/portalai_native/v2',native.NativeDeviceView(self.receiver).get)
        self.server=TestServer(app);await self.server.start_server();self.client=ClientSession()
        self.url=self.server.make_url('/api/portalai_native/v2')
    async def asyncTearDown(self):
        await self.client.close();await self.server.close()
    async def connect(self):
        ws=await self.client.ws_connect(self.url);hello=await ws.receive_json(timeout=2);self.assertEqual(hello['kind'],'hello')
        await ws.send_json({'protocol':PROTOCOL,'kind':'hello','device_id':self.device})
        challenge=await ws.receive_json(timeout=2);self.assertEqual(challenge['kind'],'challenge')
        await ws.send_json({'protocol':PROTOCOL,'kind':'authenticate','signature':'test-signature'})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'],'authenticated');return ws
    async def state(self,ws):
        s=json.loads((ROOT/'aoostar-compatibility-20261012/examples/ready-empty-unknown.json').read_text())['snapshot']
        await ws.send_json({'protocol':PROTOCOL,'kind':'bind','binding':{k:s[k] for k in ('view','epoch')}})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'],'bound')
        await ws.send_json({'protocol':PROTOCOL,'kind':'snapshot','snapshot':s})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'],'accepted');return s
    async def test_real_socket_bind_snapshot_and_invalidate(self):
        ws=await self.connect();await self.state(ws);self.assertIsNotNone(self.hub.read(self.device)['snapshot'])
        await ws.send_json({'protocol':PROTOCOL,'kind':'invalidate'})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'],'invalidated')
        with self.assertRaises(PermissionError):self.hub.read(self.device)
        await ws.close()
    async def test_machine_endpoint_rejects_browser_origin_and_ha_token(self):
        for headers in ({'Origin':'https://example.invalid'},{'Authorization':'Bearer test'}):
            with self.assertRaises(WSServerHandshakeError) as result:await self.client.ws_connect(self.url,headers=headers)
            self.assertEqual(result.exception.status,403)
    async def test_ungranted_pairing_is_rejected(self):
        self.hub.grants={};ws=await self.client.ws_connect(self.url);await ws.receive_json(timeout=2)
        await ws.send_json({'protocol':PROTOCOL,'kind':'hello','device_id':self.device})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'],'error');await ws.close()
    async def test_commands_and_duplicate_keys_close_channel(self):
        for raw in ('{"protocol":"'+PROTOCOL+'","kind":"command"}','{"protocol":"'+PROTOCOL+'","kind":"invalidate","kind":"invalidate"}'):
            ws=await self.connect();await self.state(ws);await ws.send_str(raw)
            self.assertEqual((await ws.receive_json(timeout=2))['kind'],'error');await ws.close()
            self.assertNotIn(self.device,self.hub.devices)
    async def test_new_socket_survives_old_socket_cleanup(self):
        old=await self.connect();await self.state(old);new=await self.connect();await self.state(new)
        self.assertIsNotNone(self.hub.read(self.device)['snapshot']);await old.close()
        self.assertIsNotNone(self.hub.read(self.device)['snapshot']);await new.close()
    async def test_locked_state_clears_browser_subscriber(self):
        ws=await self.connect();s=await self.state(ws);events=[]
        connection=types.SimpleNamespace(subscriptions={42:None},send_event=lambda id,v:events.append(v))
        self.receiver.subscribers['test']={'device':self.device,'connection':connection,'id':42,'generation':'test'}
        locked={k:s[k] for k in ('version','view','epoch','revision')};locked['revision']+=1;locked['account']={'state':'locked','displayName':''}
        await ws.send_json({'protocol':PROTOCOL,'kind':'snapshot','snapshot':locked})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'],'accepted')
        self.assertEqual(events[0]['kind'],'invalidate');self.assertFalse(connection.subscriptions);self.assertFalse(self.receiver.subscribers)
        await ws.close()

if __name__=='__main__':unittest.main()
