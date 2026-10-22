"""Independent, admin-approved HA channel for a separately armed helper."""
import asyncio
import json
from datetime import datetime,timedelta,timezone
from aiohttp import web
from cryptography.exceptions import InvalidSignature
try:
    import probatio as vol
except ImportError:
    import voluptuous as vol
from homeassistant.components.http import HomeAssistantView
from homeassistant.exceptions import HomeAssistantError,Unauthorized
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_track_time_interval
from .receiver import Receiver,pairing,identity

DOMAIN='portalai_recovery'
CONFIG_SCHEMA=vol.Schema({vol.Optional(DOMAIN):vol.Schema({})},extra=vol.ALLOW_EXTRA)

class RecoveryView(HomeAssistantView):
    url='/api/portalai_recovery/v1'
    name='api:portalai_recovery:v1'
    requires_auth=False  # P-256 challenge and scoped session replace HA tokens.
    def __init__(self,receiver,hass):self.receiver=receiver;self.hass=hass
    async def post(self,request):
        try:
            size=request.content_length
            if request.headers.get('Content-Encoding') or size is None or not 0<size<=8192:raise ValueError('Body limit')
            async with asyncio.timeout(10):raw=await request.content.readexactly(size)
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError('Object required')
            action=value.get('action')
            if action=='challenge':result=self.receiver.challenge(value.get('device_id'))
            elif action=='authenticate':result=self.receiver.authenticate(value)
            elif action=='poll':
                token=request.headers.get('X-PortalAI-Recovery-Session','')
                result=self.receiver.poll(token,value)
                key_id=self.receiver.sessions[token]['id'];state=self.receiver.devices[key_id]
                self.hass.states.async_set('sensor.portalai_recovery_'+key_id[:8],state['status'],
                    {'friendly_name':'PortalAI recovery helper','last_seen':datetime.now(timezone.utc).isoformat(),
                     'note':'A stale last_seen means offline; recovery does not unlock PortalAI accounts.'})
            else:raise ValueError('Unsupported operation')
            return web.json_response(result,headers={'Cache-Control':'no-store'})
        except (ValueError,KeyError,TypeError,PermissionError,InvalidSignature,asyncio.IncompleteReadError,TimeoutError):
            return web.json_response({'error':'Recovery authentication or payload refused'},status=401,headers={'Cache-Control':'no-store'})

async def async_setup(hass,config):
    store=Store(hass,1,DOMAIN+'.devices');saved=await store.async_load() or {}
    approved={}
    for row in saved.values():
        key_id,value=pairing(row);approved[key_id]=value
    receiver=Receiver(approved);hass.data[DOMAIN]={'receiver':receiver,'store':store}
    hass.http.register_view(RecoveryView(receiver,hass))
    edit_lock=asyncio.Lock()
    async def expire_status(_now):
        for key_id in receiver.approved:
            try:receiver.connected(key_id)
            except RuntimeError:
                hass.states.async_set('sensor.portalai_recovery_'+key_id[:8],'offline',{'friendly_name':'PortalAI recovery helper'})
    unsubscribe=async_track_time_interval(hass,expire_status,timedelta(seconds=5))
    hass.bus.async_listen_once('homeassistant_stop',lambda _event:unsubscribe())
    async def human(call):
        user=await hass.auth.async_get_user(call.context.user_id) if call.context.user_id else None
        if user is None or not user.is_admin:raise Unauthorized()
    async def pair(call):
        await human(call)
        async with edit_lock:
            try:
                raw=call.data['pairing_request']
                if len(raw)>4096:raise ValueError('Pairing limit')
                key_id,value=pairing(json.loads(raw))
                if key_id in receiver.approved or len(receiver.approved)>=64:raise ValueError('Already paired or device limit')
            except (ValueError,KeyError,TypeError) as exc:raise HomeAssistantError('Invalid/new recovery pairing required') from exc
            updated={**receiver.approved,key_id:value};await store.async_save(updated);receiver.approved=updated
    async def remove(call):
        await human(call);key_id=identity(call.data['device_id'])
        async with edit_lock:
            updated=dict(receiver.approved);updated.pop(key_id,None)
            await store.async_save(updated);receiver.revoke(key_id)
            hass.states.async_set('sensor.portalai_recovery_'+key_id[:8],'revoked')
    async def recover(call):
        await human(call);key_id=identity(call.data['device_id'])
        try:key=receiver.enqueue(key_id)
        except (ValueError,RuntimeError) as exc:raise HomeAssistantError(str(exc)) from exc
        try:
            for _ in range(350):
                await asyncio.sleep(.1)
                state=receiver.connected(key_id);reply=state['reply']
                if reply and reply['id']==key:
                    if reply['outcome']=='refused_or_uncertain':raise HomeAssistantError('Recovery refused or uncertain. Inspect the helper; do not replay interrupted work.')
                    return
            raise HomeAssistantError('Recovery acknowledgement timed out. Inspect the helper and projection card before another request.')
        except RuntimeError as exc:raise HomeAssistantError('Recovery channel disconnected; outcome uncertain.') from exc
        finally:receiver.cancel_undelivered(key_id,key)
    hass.services.async_register(DOMAIN,'pair_device',pair,vol.Schema({vol.Required('pairing_request'):str}))
    hass.services.async_register(DOMAIN,'remove_device',remove,vol.Schema({vol.Required('device_id'):str}))
    hass.services.async_register(DOMAIN,'recover_apps',recover,vol.Schema({vol.Required('device_id'):str}))
    return True
