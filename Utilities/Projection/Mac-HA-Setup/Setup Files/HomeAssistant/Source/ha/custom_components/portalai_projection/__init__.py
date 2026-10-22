"""HA admin control plus a separately authenticated projection-only uplink."""
import asyncio
import json
import time
import uuid
from aiohttp import web
from cryptography.exceptions import InvalidSignature
try:
    import probatio as vol
except ImportError:
    import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.exceptions import HomeAssistantError,Unauthorized
from homeassistant.helpers.storage import Store
from .receiver import Receiver,pairing,device_id
from .viewer_demand import (install as install_viewer_demand,
    poll_response as viewer_poll_response, screen_request, screen_disconnect)

DOMAIN='portalai_projection'
CONFIG_SCHEMA=vol.Schema({vol.Optional(DOMAIN):vol.Schema({})},extra=vol.ALLOW_EXTRA)


class ProjectionView(HomeAssistantView):
    url='/api/portalai_projection/v1'
    name='api:portalai_projection:v1'
    # Native HA tokens are neither accepted nor needed here. The only accepted
    # authority is a challenge-verified projection key and short-lived session.
    requires_auth=False
    def __init__(self,receiver,hass):self.receiver=receiver;self.hass=hass
    async def post(self,request):
        try:
            token=request.headers.get('X-PortalAI-Session','')
            limit=5700000 if token in self.receiver.sessions else 4096
            if request.headers.get('Content-Encoding') or request.content_length is None or not 0<request.content_length<=limit:raise ValueError('Invalid body size')
            async with asyncio.timeout(10):body=await request.content.readexactly(request.content_length)
            value=json.loads(body)
            if not isinstance(value,dict):raise ValueError('Object required')
            action=value.get('action')
            if action=='challenge':result=self.receiver.challenge(value.get('device_id'))
            elif action=='authenticate':result=self.receiver.authenticate(value)
            elif action=='poll':
                result=self.receiver.poll(token,value)
                identity=self.receiver.sessions[token]['device_id'];state=self.receiver.devices[identity]
                result=await viewer_poll_response(self.hass,self.receiver,identity,result,token=token)
                op=state['status'].get('operation',{})
                if isinstance(op,dict):self.hass.states.async_set('sensor.portalai_projection_'+identity[:8]+'_operation',str(op.get('state','idle'))[:100],{'friendly_name':'PortalAI projection operation','message':str(op.get('message',''))[:500]})
            else:raise ValueError('Unsupported projection operation')
            return web.json_response(result,headers={'Cache-Control':'no-store'})
        except (ValueError,KeyError,TypeError,PermissionError,InvalidSignature,asyncio.IncompleteReadError,TimeoutError):
            return web.json_response({'error':'Projection authentication or payload refused'},status=401,headers={'Cache-Control':'no-store'})


async def async_setup(hass,config):
    store=Store(hass,1,DOMAIN+'.devices');saved=await store.async_load() or {}
    approved={}
    for identity,row in saved.items():
        key,value=pairing({'device_id':identity,**row});approved[key]=value
    receiver=Receiver(approved)
    hass.data[DOMAIN]={'receiver':receiver,'store':store}
    install_viewer_demand(hass)
    hass.http.register_view(ProjectionView(receiver,hass))
    websocket_api.async_register_command(hass,desktop_request)
    async def human(call):
        user=await hass.auth.async_get_user(call.context.user_id) if call.context.user_id else None
        if user is None or not user.is_admin:raise Unauthorized()
    async def pair(call):
        await human(call)
        if len(receiver.approved)>=64:raise HomeAssistantError('Device limit reached; remove an unused device first')
        try:identity,value=pairing(json.loads(call.data['pairing_request']))
        except (ValueError,KeyError,TypeError) as exc:raise HomeAssistantError('Invalid public pairing request') from exc
        if identity in receiver.approved:raise HomeAssistantError('Device already paired; remove it explicitly before replacing its key')
        receiver.approved[identity]=value
        try:await store.async_save(receiver.approved)
        except Exception:receiver.revoke(identity);raise
    async def remove(call):
        await human(call);identity=device_id(call.data['device_id'])
        updated=dict(receiver.approved);updated.pop(identity,None)
        await store.async_save(updated);receiver.revoke(identity)
    async def lifecycle(call):
        await human(call);identity=device_id(call.data['device_id'])
        action='restart' if call.service=='full_restart' else 'force_shutdown'
        payload={'request_id':uuid.uuid4().hex}
        if action=='force_shutdown':
            if call.data.get('confirm')!='UNSAFE SHUTDOWN':raise HomeAssistantError('Unsafe shutdown confirmation required')
            payload['confirm']='UNSAFE SHUTDOWN'
        try: await dispatch(receiver,identity,action,payload)
        except (RuntimeError,ValueError,KeyError,PermissionError) as exc:
            raise HomeAssistantError(str(exc)[:300]) from exc
    hass.services.async_register(DOMAIN,'pair_device',pair,vol.Schema({vol.Required('pairing_request'):str}))
    hass.services.async_register(DOMAIN,'remove_device',remove,vol.Schema({vol.Required('device_id'):str}))
    hass.services.async_register(DOMAIN,'full_restart',lifecycle,vol.Schema({vol.Required('device_id'):str}))
    hass.services.async_register(DOMAIN,'force_shutdown',lifecycle,vol.Schema({vol.Required('device_id'):str,vol.Required('confirm'):vol.In(['UNSAFE SHUTDOWN'])}))
    return True


async def dispatch(receiver,identity,action,payload):
    key=receiver.enqueue(identity,action,payload)
    try:
        for _ in range(80):
            await asyncio.sleep(.1)
            state=receiver.devices.get(identity)
            if state is None:raise HomeAssistantError('Projection disconnected; action outcome unknown')
            reply=state['replies'].get(key)
            if reply is not None:
                if reply.get('error'):raise HomeAssistantError(str(reply['error'])[:300])
                return reply.get('result',{'accepted':True})
        raise HomeAssistantError('Projection acknowledgement timed out. Inspect the screen/status before retrying; effects may have occurred.')
    finally:receiver.forget(identity,key)


@websocket_api.websocket_command({vol.Required('type'):'portalai_projection/request',vol.Required('device_id'):str,
    vol.Required('action'):vol.In(['frame','input','disconnect','status','start']),vol.Optional('payload',default={}):dict})
@websocket_api.require_admin
@websocket_api.async_response
async def desktop_request(hass,connection,msg):
    try:
        receiver=hass.data[DOMAIN]['receiver'];identity=device_id(msg['device_id']);payload=dict(msg['payload']);action=msg['action']
        if len(json.dumps(payload))>60000:raise ValueError('Request too large')
        viewer=connection.user.id+':'+device_id(payload.get('viewer'))
        if action=='disconnect':
            state=receiver.devices.get(identity)
            if state and state['viewer'] and state['viewer'][0]==viewer:state['viewer']=None
            screen_disconnect(hass,connection,identity,payload.get('viewer'))
            result={'disconnected':True}
        elif action=='frame':
            state=receiver.lease(identity,viewer)
            await screen_request(hass,connection,identity,payload.get('viewer'))
            result=({'windows':[],'waiting':True} if time.monotonic()-state['frame_at']>15 else state['frame'] or {'windows':[]})
            selected=payload.get('window')
            if result.get('png') and selected and selected!=result.get('window'):
                await dispatch(receiver,identity,'select_window',{'window':device_id(selected)})
        elif action=='status':result=receiver.connected(identity)['status']
        elif action=='start':result=await dispatch(receiver,identity,'start',{'request_id':uuid.uuid4().hex})
        else:
            state=receiver.lease(identity,viewer)
            if time.monotonic()-state['frame_at']>15:raise RuntimeError('Refresh a current screen before sending input')
            result=await dispatch(receiver,identity,'input',payload)
        connection.send_result(msg['id'],result)
    except (ValueError,KeyError,TypeError,PermissionError,RuntimeError,HomeAssistantError) as exc:
        connection.send_error(msg['id'],'portalai_projection_unavailable',str(exc)[:300])
