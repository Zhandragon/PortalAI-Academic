"""HA-authorized chat commands over the existing projection control queue.

The native v2 device socket stays read-only. No browser credentials or arbitrary
services are forwarded to the device. Every effect is bound again at the GUI.
"""
import asyncio
import hashlib
import json
import re
import time


def validate(payload):
    if type(payload) is not dict: raise ValueError('Invalid chat request')
    required={'request_id','viewer','operation','binding','conversation'}
    if payload.get('operation')=='send': required.add('text')
    if payload.get('operation')=='send' and 'include_pending_attachments' in payload:
        if payload['include_pending_attachments'] is not True:raise ValueError('Invalid attachment opt-in')
        required.add('include_pending_attachments')
    if set(payload)!=required or payload.get('operation') not in ('send','stop'):
        raise ValueError('Unsupported chat request')
    for key in ('request_id','viewer'):
        if not isinstance(payload[key],str) or not re.fullmatch('[0-9a-f]{32}',payload[key]): raise ValueError('Invalid request identity')
    binding=payload['binding']
    if type(binding) is not dict or set(binding)!={'view','epoch'}: raise ValueError('Invalid account view')
    for value in binding.values():
        if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',value): raise ValueError('Invalid account view')
    if not isinstance(payload['conversation'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',payload['conversation']):
        raise ValueError('Select a conversation on the Aoostar first')
    if payload['operation']=='send':
        text=payload['text']
        if not isinstance(text,str) or not text.strip() or len(text)>8192: raise ValueError('Enter a message of up to 8192 characters')
        try: size=len(text.encode('utf-8'))
        except UnicodeError: raise ValueError('Invalid message encoding') from None
        if size>32768: raise ValueError('Message is too large')
    return json.loads(json.dumps(payload))


class ChatBridge:
    def __init__(self,hub,projection,dispatch,clock=time.monotonic):
        self.hub=hub; self.projection=projection; self.dispatch=dispatch; self.clock=clock
        self.receipts={}; self.pending={}

    def status(self,device):
        try: state=self.hub.read(device); ready=True
        except PermissionError: state=None; ready=False
        attachments=False
        try:
            peer=self.projection.connected(device); supported=type(peer['status'].get('native_chat_protocol')) is int and peer['status']['native_chat_protocol']==1
            flag=peer['status'].get('native_chat_attachment_protocol');attachments=supported and type(flag) is int and flag==1
        except (KeyError,RuntimeError): supported=False
        return {'supported':supported,'ready':ready,'protocol':1,'shared_session':True,'attachments_supported':attachments}

    def check(self,device,payload):
        snapshot=self.hub.read(device)['snapshot']
        if any(snapshot[key]!=value for key,value in payload['binding'].items()): raise PermissionError('The PortalAI account view changed. Reconnect before sending.')
        if snapshot['chat']['current']!=payload['conversation']: raise PermissionError('The active conversation changed. Review it before sending.')
        return snapshot

    async def execute(self,device,user,payload):
        payload=validate(payload); snapshot=self.check(device,payload)
        now=self.clock()
        self.receipts={key:row for key,row in self.receipts.items() if not row['task'].done() or now-row['at']<900}
        key=(device,payload['request_id'])
        digest=hashlib.sha256(json.dumps([user,payload],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
        previous=self.receipts.get(key)
        if previous:
            if previous['digest']!=digest: raise PermissionError('Request identity was already used')
            return await asyncio.shield(previous['task'])
        if len(self.receipts)>=256: raise RuntimeError('Chat request limit reached. Wait before sending again.')
        if not self.status(device)['supported']: raise RuntimeError('The Aoostar quick-chat update is not ready yet')
        if payload.get('include_pending_attachments') and not self.status(device)['attachments_supported']:
            raise RuntimeError('Sending attachments needs the Aoostar attachment-chat update. No message was sent.')
        if payload['operation']=='send' and (snapshot['chat']['busy'] or self.pending.get(device,0)):
            raise RuntimeError('Wait for the current request or response before sending')
        if self.pending.get(device,0)>=2: raise RuntimeError('A chat operation is already awaiting acknowledgement')
        self.projection.lease(device,user+':'+payload['viewer'])
        self.pending[device]=self.pending.get(device,0)+1
        task=asyncio.create_task(self._execute(device,payload))
        # Retrieve failed outcomes even if the browser goes away while waiting.
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        self.receipts[key]={'at':now,'digest':digest,'task':task}
        return await asyncio.shield(task)

    async def _execute(self,device,payload):
        try:
            self.check(device,payload)
            reply=await self.dispatch(self.projection,device,'native_chat',payload)
            if (type(reply) is not dict or reply.get('accepted') is not True or
                    reply.get('request_id')!=payload['request_id'] or reply.get('operation')!=payload['operation']):
                raise RuntimeError('Chat outcome is unknown. Check the conversation before sending again.')
            return {'accepted':True,'request_id':payload['request_id'],'operation':payload['operation']}
        finally:
            self.pending[device]=max(0,self.pending.get(device,1)-1)
