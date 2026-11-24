"""Narrow native state receiver; all device-originated messages are inert data."""
import asyncio
import contextlib
import secrets
import re
import time
from aiohttp import web, WSMsgType
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import Unauthorized, HomeAssistantError
from homeassistant.helpers.storage import Store
from .core import NativeHub, LEASE_SECONDS, SCOPE
from .schema import PROTOCOL, MAX_BYTES, fields, decode, encode
from .commands import ChatBridge
from .workflows import WorkflowBridge
from .rich_chat import RichBridge, RichUnavailable

DOMAIN='portalai_native'
CONFIG_SCHEMA=vol.Schema({vol.Optional(DOMAIN):vol.Schema({})},extra=vol.ALLOW_EXTRA)

def identity(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value): raise ValueError('device')
    return value

class NativeReceiver:
    def __init__(self,hass,hub):
        self.hass=hass; self.hub=hub; self.sockets={}; self.subscribers={}; self.pending=0

    async def clear_viewers(self,device,reason='unavailable'):
        for key,row in list(self.subscribers.items()):
            if row['device']!=device: continue
            self.subscribers.pop(key,None)
            row['connection'].subscriptions.pop(row['id'],None)
            with contextlib.suppress(Exception):
                row['connection'].send_event(row['id'],{'protocol':PROTOCOL,'generation':row['generation'],'kind':'invalidate','reason':reason})

    async def publish_viewers(self,device):
        for key,row in list(self.subscribers.items()):
            if row['device']!=device: continue
            user=await self.hass.auth.async_get_user(row['connection'].user.id)
            if self.subscribers.get(key) is not row: continue
            try:
                if user is None or not user.is_admin or not user.is_active: raise PermissionError('revoked')
                state=self.hub.read(device)
                if state['binding']!=row['binding']: raise PermissionError('rebind')
                packet={'protocol':PROTOCOL,'generation':row['generation'],'kind':'snapshot','snapshot':state['snapshot']}
                encode(packet)
                row['connection'].send_event(row['id'],packet)
            except Exception:
                self.subscribers.pop(key,None)
                row['connection'].subscriptions.pop(row['id'],None)
                with contextlib.suppress(Exception):
                    row['connection'].send_event(row['id'],{'protocol':PROTOCOL,'generation':row['generation'],'kind':'invalidate','reason':'unavailable'})

    async def monitor(self):
        try:
            while True:
                await asyncio.sleep(1)
                for device in list(self.hub.devices):
                    try: self.hub.read(device)
                    except PermissionError:
                        await self.clear_viewers(device)
                        if not self.hub.permitted(device) and device in self.sockets: await self.sockets[device].close()
        except asyncio.CancelledError: pass

class NativeDeviceView(HomeAssistantView):
    url='/api/portalai_native/v2'
    name='api:portalai_native:v2'
    requires_auth=False
    def __init__(self,receiver): self.receiver=receiver

    async def get(self,request):
        receiver=self.receiver
        # Browser credentials are never accepted on the device endpoint.
        if request.headers.get('Origin') or request.headers.get('Authorization'): return web.Response(status=403,text='device channel only')
        if receiver.pending>=4 or len(receiver.sockets)>=64: return web.Response(status=503,text='capacity')
        ws=web.WebSocketResponse(max_msg_size=MAX_BYTES,compress=False,autoping=True,heartbeat=5)
        await ws.prepare(request)
        receiver.pending+=1; pending=True; device=None; connection=None
        try:
            await ws.send_json({'protocol':PROTOCOL,'kind':'hello','maxFrameBytes':MAX_BYTES,'leaseSeconds':LEASE_SECONDS})
            async with asyncio.timeout(10):
                hello=decode(await ws.receive_str()); fields(hello,('protocol','kind','device_id'))
                if hello['protocol']!=PROTOCOL or hello['kind']!='hello': raise ValueError('protocol')
                device=identity(hello['device_id'])
                if not receiver.hub.permitted(device): raise PermissionError('grant_required')
                nonce=secrets.token_hex(32)
                await ws.send_json({'protocol':PROTOCOL,'kind':'challenge','challenge':nonce})
                auth=decode(await ws.receive_str()); fields(auth,('protocol','kind','signature'))
                if auth['protocol']!=PROTOCOL or auth['kind']!='authenticate': raise ValueError('protocol')
                receiver.hub.authenticate(device,nonce,auth['signature'])
            old=receiver.sockets.get(device)
            await receiver.clear_viewers(device,'reconnected')
            connection=receiver.hub.attach(device); receiver.sockets[device]=ws
            if old is not None: await old.close()
            receiver.pending-=1; pending=False
            await ws.send_json({'protocol':PROTOCOL,'kind':'authenticated','capabilities':[SCOPE],'leaseSeconds':LEASE_SECONDS})
            rate_start=time.monotonic(); rate_count=0
            async for message in ws:
                if message.type!=WSMsgType.TEXT: break
                now=time.monotonic()
                if now-rate_start>=1: rate_start=now; rate_count=0
                rate_count+=1
                if rate_count>20: raise ValueError('rate')
                value=decode(message.data)
                if type(value) is not dict or value.get('protocol')!=PROTOCOL: raise ValueError('protocol')
                receiver.hub.current(device,connection)
                kind=value.get('kind')
                if kind=='bind':
                    fields(value,('protocol','kind','binding'))
                    await receiver.clear_viewers(device,'account_changed')
                    receiver.hub.bind(device,connection,value['binding'])
                    await ws.send_json({'protocol':PROTOCOL,'kind':'bound','binding':value['binding']})
                elif kind=='snapshot':
                    fields(value,('protocol','kind','snapshot'))
                    ready=receiver.hub.publish(device,connection,value['snapshot'])
                    if ready: await receiver.publish_viewers(device)
                    else: await receiver.clear_viewers(device,'locked')
                    await ws.send_json({'protocol':PROTOCOL,'kind':'accepted','revision':value['snapshot']['revision']})
                elif kind=='invalidate':
                    fields(value,('protocol','kind'))
                    receiver.hub.invalidate(device,connection); await receiver.clear_viewers(device)
                    await ws.send_json({'protocol':PROTOCOL,'kind':'invalidated'})
                else: raise ValueError('unsupported_kind')
        except Exception:
            if not ws.closed:
                with contextlib.suppress(Exception): await ws.send_json({'protocol':PROTOCOL,'kind':'error','reason':'refused'})
        finally:
            if pending: receiver.pending-=1
            if device and connection and receiver.hub.detach(device,connection):
                await receiver.clear_viewers(device)
                if receiver.sockets.get(device) is ws: receiver.sockets.pop(device,None)
            await ws.close()
        return ws

async def async_setup(hass,config):
    store=Store(hass,1,DOMAIN+'.grants'); grants=await store.async_load() or {}
    if type(grants) is not dict: return False
    approved=hass.data['portalai_projection']['receiver'].approved
    hub=NativeHub(approved,grants); receiver=NativeReceiver(hass,hub)
    hass.data[DOMAIN]={'receiver':receiver,'store':store}
    from custom_components.portalai_projection import dispatch
    projection=hass.data['portalai_projection']['receiver']
    hass.data[DOMAIN]['chat']=ChatBridge(hub,projection,dispatch)
    hass.data[DOMAIN]['workflows']=WorkflowBridge(hub,projection,dispatch)
    hass.data[DOMAIN]['rich']=RichBridge(hub,projection,dispatch,hass.data['portalai_projection']['viewer_demand'])
    websocket_api.async_register_command(hass,rich_command)
    hass.http.register_view(NativeDeviceView(receiver))
    websocket_api.async_register_command(hass,subscribe)
    websocket_api.async_register_command(hass,status)
    websocket_api.async_register_command(hass,chat_status)
    websocket_api.async_register_command(hass,chat_command)
    websocket_api.async_register_command(hass,workflow_status)
    websocket_api.async_register_command(hass,workflow_command)
    async def grant(call):
        user=await hass.auth.async_get_user(call.context.user_id) if call.context.user_id else None
        if user is None or not user.is_admin or not user.is_active: raise Unauthorized()
        device=identity(call.data['device_id'])
        if device not in approved: raise HomeAssistantError('Device is not projection-paired')
        updated=dict(hub.grants)
        if call.service=='allow_state': updated[device]=approved[device]['fingerprint']
        else: updated.pop(device,None)
        await store.async_save(updated); hub.grants=updated
        if call.service=='revoke_state':
            hub.invalidate(device); await receiver.clear_viewers(device,'revoked')
            if device in receiver.sockets: await receiver.sockets[device].close()
    schema=vol.Schema({vol.Required('device_id'):str})
    hass.services.async_register(DOMAIN,'allow_state',grant,schema)
    hass.services.async_register(DOMAIN,'revoke_state',grant,schema)
    task=hass.async_create_background_task(receiver.monitor(),'PortalAI native state lease monitor')
    async def stop(_):
        task.cancel()
        for device in list(hub.devices): hub.invalidate(device); await receiver.clear_viewers(device)
        for ws in list(receiver.sockets.values()): await ws.close()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP,stop)
    return True

@websocket_api.websocket_command({vol.Required('type'):'portalai_native/ui_status',vol.Required('device_id'):str})
@websocket_api.require_admin
@websocket_api.async_response
async def workflow_status(hass,connection,msg):
    user=await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active: raise Unauthorized()
    try: connection.send_result(msg['id'],hass.data[DOMAIN]['workflows'].status(identity(msg['device_id'])))
    except (ValueError,PermissionError,RuntimeError) as exc: connection.send_error(msg['id'],'portalai_native_refused',str(exc)[:300])

@websocket_api.websocket_command({vol.Required('type'):'portalai_native/ui',vol.Required('device_id'):str,vol.Required('payload'):dict})
@websocket_api.require_admin
@websocket_api.async_response
async def workflow_command(hass,connection,msg):
    user=await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active: raise Unauthorized()
    try:
        result=await hass.data[DOMAIN]['workflows'].execute(identity(msg['device_id']),user.id,msg['payload'])
        connection.send_result(msg['id'],result)
    except (ValueError,PermissionError,RuntimeError,HomeAssistantError) as exc:
        connection.send_error(msg['id'],'portalai_native_refused',str(exc)[:300])

@websocket_api.websocket_command({vol.Required('type'):'portalai_native/chat_status',vol.Required('device_id'):str})
@websocket_api.require_admin
@websocket_api.async_response
async def chat_status(hass,connection,msg):
    user=await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active: raise Unauthorized()
    connection.send_result(msg['id'],hass.data[DOMAIN]['chat'].status(identity(msg['device_id'])))

@websocket_api.websocket_command({vol.Required('type'):'portalai_native/chat',vol.Required('device_id'):str,
    vol.Required('request_id'):str,vol.Required('viewer'):str,vol.Required('operation'):str,
    vol.Required('binding'):dict,vol.Required('conversation'):str,vol.Optional('text'):str,
    vol.Optional('include_pending_attachments'):bool})
@websocket_api.require_admin
@websocket_api.async_response
async def chat_command(hass,connection,msg):
    user=await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active: raise Unauthorized()
    try:
        payload={key:value for key,value in msg.items() if key not in ('id','type','device_id')}
        result=await hass.data[DOMAIN]['chat'].execute(identity(msg['device_id']),user.id,payload)
        connection.send_result(msg['id'],result)
    except (ValueError,PermissionError,RuntimeError,HomeAssistantError) as exc:
        connection.send_error(msg['id'],'portalai_chat_refused',str(exc)[:300])

@websocket_api.websocket_command({vol.Required('type'):'portalai_native/status',vol.Required('device_id'):str})
@websocket_api.require_admin
@websocket_api.async_response
async def status(hass,connection,msg):
    receiver=hass.data[DOMAIN]['receiver']; device=identity(msg['device_id'])
    user=await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active: raise Unauthorized()
    try: receiver.hub.read(device); ready=True
    except PermissionError: ready=False
    connection.send_result(msg['id'],{'protocol':PROTOCOL,'granted':receiver.hub.permitted(device),'connected':device in receiver.sockets,'ready':ready,'capabilities':[SCOPE] if ready else []})

@websocket_api.websocket_command({vol.Required('type'):'portalai_native/subscribe',vol.Required('device_id'):str})
@websocket_api.require_admin
@websocket_api.async_response
async def subscribe(hass,connection,msg):
    receiver=hass.data[DOMAIN]['receiver']; device=identity(msg['device_id'])
    user=await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active: raise Unauthorized()
    try:
        if len(receiver.subscribers)>=16 or sum(r['device']==device for r in receiver.subscribers.values())>=4: raise PermissionError('capacity')
        generation=secrets.token_hex(16); handshake=receiver.hub.handshake(device,generation)
        key=(id(connection),msg['id'])
        receiver.subscribers[key]={'connection':connection,'id':msg['id'],'device':device,'generation':generation,'binding':handshake['binding']}
        connection.subscriptions[msg['id']]=lambda: receiver.subscribers.pop(key,None)
        connection.send_result(msg['id'],None)
        connection.send_event(msg['id'],handshake)
        state=receiver.hub.read(device)
        connection.send_event(msg['id'],{'protocol':PROTOCOL,'generation':generation,'kind':'snapshot','snapshot':state['snapshot']})
    except PermissionError:
        connection.send_error(msg['id'],'portalai_native_unavailable','Native state is not ready. Check the Aoostar native exporter and approved read scope.')


@websocket_api.websocket_command({vol.Required('type'):'portalai_native/rich',vol.Required('device_id'):str,vol.Required('payload'):dict})
@websocket_api.require_admin
@websocket_api.async_response
async def rich_command(hass,connection,msg):
    user=await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active:raise Unauthorized()
    try:
        device=identity(msg['device_id']);bridge=hass.data[DOMAIN]['rich']
        result=await bridge.execute(device,connection,msg['payload'])
        user=await hass.auth.async_get_user(connection.user.id)
        if user is None or not user.is_admin or not user.is_active:raise PermissionError('Administrator access ended')
        bridge.check(device,connection,msg['payload'])
        connection.send_result(msg['id'],result)
    except RichUnavailable as exc:
        connection.send_error(msg['id'],'portalai_rich_'+exc.code,str(exc))
    except (ValueError,PermissionError,RuntimeError,HomeAssistantError,KeyError):
        # Device-originated errors may contain private paths; return a controlled message.
        connection.send_error(msg['id'],'portalai_rich_unavailable','Rich detail unavailable, expired, or media exceeds 20 MiB. Check both updates, account and viewer connection.')
