"""HA adapter contract with a stub host; no connection to the user's HA."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import Mock,AsyncMock,patch

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'app'),str(MODULE/'Runtime/packages')]
from connection_vault import new_connection
from recovery_transport import pairing_request

class HAError(Exception):pass
class Unauthorized(HAError):pass

class HATests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        schema=ModuleType('voluptuous');schema.Schema=lambda *args,**kwargs:object();schema.Optional=lambda v:v;schema.Required=lambda v:v;schema.ALLOW_EXTRA=object()
        web=SimpleNamespace(json_response=lambda data,status=200,headers=None:SimpleNamespace(data=data,status=status,headers=headers))
        storage=ModuleType('homeassistant.helpers.storage');test=self
        class Store:
            def __init__(self,*_):self.saved={};self.fail=False;test.store=self
            async def async_load(self):return {}
            async def async_save(self,value):
                if self.fail:raise OSError('synthetic store failure')
                self.saved=dict(value)
        storage.Store=Store
        events=ModuleType('homeassistant.helpers.event')
        events.async_track_time_interval=lambda hass,callback,interval:(setattr(test,'expire',callback) or Mock())
        http=ModuleType('homeassistant.components.http');http.HomeAssistantView=object
        exceptions=ModuleType('homeassistant.exceptions');exceptions.HomeAssistantError=HAError;exceptions.Unauthorized=Unauthorized
        aiohttp=ModuleType('aiohttp');aiohttp.web=web
        modules={'voluptuous':schema,'probatio':schema,'aiohttp':aiohttp,'homeassistant.components.http':http,
            'homeassistant.exceptions':exceptions,'homeassistant.helpers.storage':storage,'homeassistant.helpers.event':events}
        self.patcher=patch.dict(sys.modules,modules);self.patcher.start()
        directory=MODULE/'RecoveryHelper/ha/custom_components/portalai_recovery'
        spec=importlib.util.spec_from_file_location('synthetic_ha_recovery',directory/'__init__.py',submodule_search_locations=[str(directory)])
        self.integration=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.integration;spec.loader.exec_module(self.integration)
        self.services={}
        self.hass=SimpleNamespace(data={},http=SimpleNamespace(register_view=Mock()),states=SimpleNamespace(async_set=Mock()),
            bus=SimpleNamespace(async_listen_once=Mock()),auth=SimpleNamespace(async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=True))),
            services=SimpleNamespace(async_register=lambda domain,name,callback,schema:self.services.__setitem__(name,callback)))
        await self.integration.async_setup(self.hass,{})
        self.connection=new_connection('https://example.invalid','../PortalAI','Synthetic')
        self.public=pairing_request(self.connection);self.identity=self.connection['device_id']
        self.hub=self.hass.data['portalai_recovery']['receiver']
    async def asyncTearDown(self):
        self.patcher.stop();sys.modules.pop('synthetic_ha_recovery',None);sys.modules.pop('synthetic_ha_recovery.receiver',None)
    def call(self,**data):return SimpleNamespace(context=SimpleNamespace(user_id='synthetic-admin'),data=data)
    async def pair(self):await self.services['pair_device'](self.call(pairing_request=json.dumps(self.public)))
    async def test_every_action_requires_an_authenticated_admin(self):
        for user in (None,SimpleNamespace(is_admin=False)):
            self.hass.auth.async_get_user.return_value=user
            for action in ('pair_device','remove_device','recover_apps'):
                with self.subTest(action=action,user=user),self.assertRaises(Unauthorized):await self.services[action](self.call())
        self.assertEqual(self.hub.approved,{})
    async def test_public_pairing_is_separate_and_persisted_without_credentials(self):
        await self.pair();self.assertIn(self.identity,self.hub.approved)
        text=json.dumps(self.store.saved);self.assertNotIn('PRIVATE KEY',text);self.assertNotIn('example.invalid',text)
        with self.assertRaises(HAError):await self.pair()
    async def test_failed_pairing_save_does_not_grant_authority(self):
        self.store.fail=True
        with self.assertRaises(OSError):await self.pair()
        self.assertEqual(self.hub.approved,{})
    async def test_revoke_requires_successful_storage_then_removes_authority(self):
        await self.pair();self.store.fail=True
        with self.assertRaises(OSError):await self.services['remove_device'](self.call(device_id=self.identity))
        self.assertIn(self.identity,self.hub.approved)
        self.store.fail=False;await self.services['remove_device'](self.call(device_id=self.identity))
        self.assertNotIn(self.identity,self.hub.approved)
    async def test_offline_status_and_service_do_not_claim_recovery(self):
        await self.pair();await self.expire(None)
        self.assertEqual(self.hass.states.async_set.call_args.args[1],'offline')
        with self.assertRaises(HAError):await self.services['recover_apps'](self.call(device_id=self.identity))
    async def test_http_rejects_unbounded_body_and_unknown_operation(self):
        view=self.hass.http.register_view.call_args.args[0]
        request=SimpleNamespace(content_length=9000,headers={},content=SimpleNamespace(readexactly=AsyncMock()))
        self.assertEqual((await view.post(request)).status,401);request.content.readexactly.assert_not_called()
        body=b'{"action":"shell"}';request.content_length=len(body);request.content.readexactly.return_value=body
        self.assertEqual((await view.post(request)).status,401)
    async def test_recovery_dispatch_reports_outcome_and_never_adds_arbitrary_arguments(self):
        await self.pair()
        self.hub.devices[self.identity]={'updated':self.hub.clock(),'status':'idle','pending':None,'reply':None}
        async def acknowledge(_delay):
            state=self.hub.devices[self.identity];pending=state['pending']
            self.assertEqual(set(pending),{'id','expires','delivered'})
            state['reply']={'id':pending['id'],'outcome':'launch_requested'}
        with patch.object(self.integration.asyncio,'sleep',acknowledge):
            await self.services['recover_apps'](self.call(device_id=self.identity))

if __name__=='__main__':unittest.main()
