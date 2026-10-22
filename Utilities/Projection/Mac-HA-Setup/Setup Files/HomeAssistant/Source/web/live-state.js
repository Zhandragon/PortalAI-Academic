import { PortalAIViewerDemand } from './portalai-viewer-demand.js';
import { CATALOG } from './catalog.js';
export const PROTOCOL = 'portalai-native-state/2';
export const MAX_BYTES = 180000;
const fail = () => { throw new Error('Invalid native state'); };
const fields = (v, keys) => {
  if (!v || Object.getPrototypeOf(v) !== Object.prototype || Object.keys(v).length !== keys.length || keys.some(k => !Object.hasOwn(v,k))) fail();
};
const id = v => { if (typeof v !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(v)) fail(); };
const text = (v, max=160) => { if (typeof v !== 'string' || !v.isWellFormed() || [...v].length > max) fail(); };
const choice = (v, values) => { if (!values.includes(v)) fail(); };
const bool = v => { if (typeof v !== 'boolean') fail(); };
const int = (v, min=0, max=Number.MAX_SAFE_INTEGER) => { if (!Number.isSafeInteger(v) || v < min || v > max) fail(); };
const nullable = (v, min, max) => { if (v !== null) int(v,min,max); };
const rows = v => {
  if (!Array.isArray(v) || v.length > 100) fail();
  const seen = new Set();
  for (const row of v) { id(row?.id); if (seen.has(row.id)) fail(); seen.add(row.id); }
  return v;
};
const budget = v => { if (new TextEncoder().encode(JSON.stringify(v)).byteLength > MAX_BYTES) fail(); };
const binding = v => { fields(v,['view','epoch']); id(v.view); id(v.epoch); };

export function validateLiveSnapshot(v) {
  budget(v);
  fields(v.account,['state','displayName']);
  choice(v.account.state,['ready','locked','switching','closing']); text(v.account.displayName);
  const base = ['version','view','epoch','revision','account'];
  fields(v,v.account.state === 'ready' ? [...base,'runtime','models','packages','chat','settings'] : base);
  if (v.version !== 2) fail(); id(v.view); id(v.epoch); int(v.revision);
  if (v.account.state !== 'ready') { if (v.account.displayName !== '') fail(); return structuredClone(v); }
  fields(v.runtime,['state','cpu','gpu','memory','model']);
  choice(v.runtime.state,['idle','starting','ready','sleeping','stopping','unavailable']); text(v.runtime.model);
  for (const k of ['cpu','gpu','memory']) {
    const n=v.runtime[k]; if (n !== null && (typeof n !== 'number' || !Number.isFinite(n) || n < 0 || n > 100)) fail();
  }
  for (const r of rows(v.models)) {
    fields(r,['id','name','kind','installed','selected','state']); text(r.name); text(r.kind); bool(r.installed); bool(r.selected);
    choice(r.state,['ready','sleeping','starting','stopped','unavailable']);
  }
  for (const r of rows(v.packages)) {
    fields(r,['id','name','purpose','state']); text(r.name); text(r.purpose,300); choice(r.state,['available','unavailable','unvalidated']);
  }
  const c=v.chat; fields(c,['conversations','current','messages','busy','contextUsed','contextLimit','replyCap','window']);
  rows(c.conversations); rows(c.messages); bool(c.busy);
  for (const r of c.conversations) { fields(r,['id','title','updated']); text(r.title); text(r.updated); }
  if (c.current === null) { if (c.messages.length || c.busy) fail(); }
  else { id(c.current); if (!c.conversations.some(r => r.id === c.current)) fail(); }
  for (const r of c.messages) { fields(r,['id','role','text','truncated']); choice(r.role,['user','assistant']); text(r.text,16000); bool(r.truncated); }
  nullable(c.contextUsed,0,1048576); nullable(c.contextLimit,1,1048576); nullable(c.replyCap,1,32768);
  if (c.contextUsed !== null && c.contextLimit !== null && c.contextUsed > c.contextLimit) fail();
  fields(c.window,['conversationsComplete','messagesComplete']); bool(c.window.conversationsComplete); bool(c.window.messagesComplete);
  const s=v.settings; fields(s,['selection','variant','backend','context','reply','effort','media']);
  id(s.selection); choice(s.variant,['standard','uncensored']); choice(s.backend,['auto','cuda','vulkan','cpu']);
  choice(s.context,[2048,4096,8192,16384,32768]); int(s.reply,1,32768); choice(s.effort,['Fast','Balanced','Deep']);
  fields(s.media,Object.keys(CATALOG.media.CHOICES));
  for (const [k, values] of Object.entries(CATALOG.media.CHOICES)) choice(s.media[k],Object.keys(values));
  return structuredClone(v);
}

// Only an authenticated HA subscription can establish a view. Data never rebinds it.
export class LiveSession {
  constructor({onState,onClear,setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}) {
    Object.assign(this,{onState,onClear,setTimer,clearTimer}); this.ticket=0; this.phase='offline';
  }
  clear(reason='offline') {
    ++this.ticket; this.phase='offline'; this.binding=null; this.generation=null; this.revision=null;
    this.clearTimer(this.timer); this.timer=null;
    this.clearTimer(this.waitTimer); this.waitTimer=null;
    const demand=this.demand; this.demand=null; if(demand)demand.disconnect();
    const unsubscribe=this.unsubscribe; this.unsubscribe=null;
    if (unsubscribe) Promise.resolve().then(unsubscribe).catch(() => {});
    this.onClear(reason);
  }
  async connect(connection,device) {
    this.clear('connecting'); const ticket=this.ticket; this.phase='waiting';
    const demand=new PortalAIViewerDemand({callWS:value=>connection.sendMessagePromise(value)},device,'native',
      ()=>{if(ticket===this.ticket)this.clear('unavailable');});
    this.demand=demand;
    try {
      await demand.connect();
      if(ticket!==this.ticket){await demand.disconnect();return;}
      this.onClear('connecting'); // Public account forms may now request describe.
      await this.waitReady(ticket,connection,device);
    } catch (_) {if(ticket===this.ticket)this.clear('unavailable');}
  }
  async waitReady(ticket,connection,device) {
    if(ticket!==this.ticket)return;
    try {
      const state=await connection.sendMessagePromise({type:'portalai_native/status',device_id:device});
      if(ticket!==this.ticket)return;
      if(state.protocol!==PROTOCOL||state.granted!==true)throw Error('Native read permission required');
      if(state.ready!==true){
        this.waitTimer=this.setTimer(()=>this.waitReady(ticket,connection,device),1000);return;
      }
      // Preserve the existing strict handshake and fresh-state expiry. Presence
      // itself never grants an account view and sends no new snapshot messages.
      this.phase='handshake';this.arm(ticket,10000);
      const unsubscribe=await connection.subscribeMessage(value=>this.receive(ticket,value),{type:'portalai_native/subscribe',device_id:device});
      if(ticket!==this.ticket){await unsubscribe();return;}
      this.unsubscribe=unsubscribe;
    } catch (_) {if(ticket===this.ticket)this.clear('unavailable');}
  }
  arm(ticket,ms) {
    this.clearTimer(this.timer);
    this.timer=this.setTimer(() => { if (ticket === this.ticket) this.clear('expired'); },ms);
  }
  receive(ticket,v) {
    if (ticket !== this.ticket) return;
    try {
      budget(v);
      if (v.protocol !== PROTOCOL) fail();
      if (this.phase === 'handshake') {
        fields(v,['protocol','kind','generation','binding','capabilities','maxFrameBytes','leaseSeconds']);
        if (v.kind !== 'handshake' || v.maxFrameBytes !== MAX_BYTES || v.leaseSeconds !== 10 || !Array.isArray(v.capabilities) || v.capabilities.length !== 1 || v.capabilities[0] !== 'native.state.read') fail();
        id(v.generation); binding(v.binding); this.generation=v.generation; this.binding=structuredClone(v.binding); this.phase='snapshot';
        this.arm(ticket,10000); return;
      }
      if (v.generation !== this.generation) fail();
      if (v.kind === 'invalidate') {
        fields(v,['protocol','kind','generation','reason']); text(v.reason); this.clear('unavailable'); return;
      }
      fields(v,['protocol','kind','generation','snapshot']); if (v.kind !== 'snapshot') fail();
      const s=validateLiveSnapshot(v.snapshot);
      if (s.view !== this.binding.view || s.epoch !== this.binding.epoch || (this.revision !== null && s.revision !== this.revision+1)) fail();
      if (s.account.state !== 'ready') { this.clear('locked'); return; }
      this.revision=s.revision; this.phase='ready'; this.arm(ticket,10000); this.onState(s);
    } catch (_) { this.clear('invalid'); }
  }
}
