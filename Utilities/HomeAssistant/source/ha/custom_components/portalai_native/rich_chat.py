"""Read-only rich-chat/1 over the existing projection command/reply lane."""
from .rich_protocol import validate_request,validate_reply

class RichUnavailable(RuntimeError):
    """Allowlisted public diagnostics; never forward host exception text."""
    def __init__(self, code):
        messages={
            'viewer':'Rich details paused: reconnect this HA viewer.',
            'state':'Rich details paused: waiting for fresh PortalAI state.',
            'conversation':'Rich details paused: the account or conversation changed.',
            'host_update':'Rich details need the Aoostar rich-chat update and companion restart.',
            'host_connection':'Rich details paused: the Aoostar companion is disconnected.',
            'host_read':'Aoostar could not return rich details. Check its GUI dialogs and rich-chat handler.',
            'reply':'Aoostar returned incompatible rich details. Update its rich-chat handler.',
        }
        self.code=code;super().__init__(messages[code])

class RichBridge:
    def __init__(self,hub,projection,dispatch,demand):
        self.hub=hub;self.projection=projection;self.dispatch=dispatch;self.demand=demand;self.pending={}
    def check(self,device,connection,p):
        self.demand.prune()
        key=(device,id(connection),connection.user.id,p['viewer'],'native')
        if key not in self.demand.rows:raise RichUnavailable('viewer')
        try:snapshot=self.hub.read(device)['snapshot']
        except PermissionError:raise RichUnavailable('state') from None
        if {k:snapshot[k] for k in ('view','epoch')}!=p['binding'] or snapshot['chat']['current']!=p['conversation']:
            raise RichUnavailable('conversation')
        try:flag=self.projection.connected(device)['status'].get('native_rich_protocol')
        except (KeyError,RuntimeError):raise RichUnavailable('host_connection') from None
        if type(flag) is not int or flag!=1:raise RichUnavailable('host_update')
    async def execute(self,device,connection,p):
        p=validate_request(p);self.check(device,connection,p)
        # Reads have no effect receipts/controller lease and cannot consume reserved Stop slots.
        if self.pending.get(device,0)>=2:raise RuntimeError('Rich details are busy; try again shortly')
        self.pending[device]=self.pending.get(device,0)+1
        try:
            wire=p
            # Safe mixed-version rollout: older Aoostars retain the existing
            # bounded read, while this browser can use one stable v2 schema.
            capability=self.projection.connected(device)['status'].get('native_media_batch_protocol')
            if p['operation']=='rich_media_batch' and (type(capability) is not int or capability!=1):
                wire={**p,'operation':'rich_media','protocol':1}
            try:result=await self.dispatch(self.projection,device,'native_ui',wire)
            except Exception:raise RichUnavailable('host_read') from None
            self.check(device,connection,p)
            try:
                if wire is not p:
                    validate_reply(result,wire)
                    result={**result,'operation':p['operation'],'rich':{**result['rich'],'protocol':2}}
                return validate_reply(result,p)
            except (ValueError,TypeError,KeyError):raise RichUnavailable('reply') from None
        finally:self.pending[device]=max(0,self.pending.get(device,1)-1)
