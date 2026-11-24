import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {LiveSession,validateLiveSnapshot,PROTOCOL} from '../web/live-state.js';
const fixture=() => JSON.parse(readFileSync(new URL('../aoostar-compatibility-20261012/examples/ready-empty-unknown.json',import.meta.url))).snapshot;
const handshake=s => ({protocol:PROTOCOL,kind:'handshake',generation:'ha_generation',binding:{view:s.view,epoch:s.epoch},capabilities:['native.state.read'],maxFrameBytes:180000,leaseSeconds:10});
const packet=s => ({protocol:PROTOCOL,kind:'snapshot',generation:'ha_generation',snapshot:s});
const sessions=new Set();
test.afterEach(()=>{for(const session of sessions)session.clear();sessions.clear();});
const sendMessagePromise=async request=>request.type==='portalai_projection/viewer'?{accepted:true,lease_seconds:15}:{protocol:PROTOCOL,granted:true,ready:true};
function setup() {
  const states=[],clears=[],timers=new Map(); let next=0;
  const session=new LiveSession({onState:s => states.push(s),onClear:r => clears.push(r),setTimer:fn => {timers.set(++next,fn);return next;},clearTimer:i => timers.delete(i)});
  sessions.add(session);
  const callbacks=[]; const connection={sendMessagePromise,subscribeMessage(cb) {callbacks.push(cb); return Promise.resolve(() => {});}};
  return {session,states,clears,timers,callbacks,connection};
}
test('compatibility v2 empty/unknown state is accepted without invented readings',() => {
  const v=validateLiveSnapshot(fixture()); assert.equal(v.runtime.cpu,null);assert.equal(v.chat.current,null);
});
test('duplicates, extra fields, missing window flags and nonfinite values rejected',() => {
  for (const mutate of [s=>s.unexpected=1,s=>delete s.chat.window,s=>s.runtime.cpu=NaN,s=>s.models=[{id:'x'},{id:'x'}],s=>s.account.displayName='\ud800']) {
    const s=fixture();mutate(s);assert.throws(()=>validateLiveSnapshot(s));
  }
});
test('UTF-8 budget and codepoint counts agree with receiver',() => {
  const s=fixture();s.account.displayName='😀'.repeat(160);assert.doesNotThrow(()=>validateLiveSnapshot(s));
  s.chat.current='c';s.chat.conversations=[{id:'c',title:'c',updated:''}];
  s.chat.messages=Array.from({length:4},(_,i)=>({id:'m'+i,role:'assistant',text:'😀'.repeat(16000),truncated:false}));
  assert.throws(()=>validateLiveSnapshot(s));
});
test('snapshot alone cannot establish a view',async()=>{
  const h=setup();await h.session.connect(h.connection,'device');h.callbacks[0](packet(fixture()));
  assert.equal(h.states.length,0);assert.equal(h.session.phase,'offline');
});
test('fresh handshake accepts consecutive revisions; raw rebind and gaps clear state',async()=>{
  for (const change of [s=>s.view='other',s=>s.epoch='other',s=>s.revision+=2]) {
    const h=setup(),s=fixture();await h.session.connect(h.connection,'device');const cb=h.callbacks[0];
    cb(handshake(s));cb(packet(s));s.revision++;cb(packet(s));assert.equal(h.states.length,2);
    change(s);cb(packet(s));assert.equal(h.session.phase,'offline');assert.equal(h.clears.at(-1),'invalid');
  }
});
test('old callback and rejected subscribe completion cannot clear newer session',async()=>{
  const h=setup(); let rejectOld,subscribed;const started=new Promise(r=>subscribed=r);const pending={sendMessagePromise,subscribeMessage(cb){h.callbacks.push(cb);subscribed();return new Promise((_,reject)=>rejectOld=reject);}};
  const old=h.session.connect(pending,'device');await started;await h.session.connect(h.connection,'device');
  const s=fixture();h.callbacks[1](handshake(s));h.callbacks[1](packet(s));
  h.callbacks[0](packet({...s,view:'old'}));rejectOld(new Error('late'));await old;
  assert.equal(h.session.phase,'ready');assert.equal(h.states.length,1);
});
test('late successful subscription is unsubscribed without replacing active cleanup',async()=>{
  const h=setup();let resolveOld,subscribed,oldClosed=0;const started=new Promise(r=>subscribed=r);const old=h.session.connect({sendMessagePromise,subscribeMessage(){subscribed();return new Promise(r=>resolveOld=r);}},'device');
  await started;await h.session.connect(h.connection,'device');resolveOld(()=>oldClosed++);await old;
  assert.equal(oldClosed,1);assert.equal(h.session.phase,'handshake');
});
test('locked snapshot clears and a late ready snapshot cannot unlock',async()=>{
  const h=setup(),s=fixture();await h.session.connect(h.connection,'device');const cb=h.callbacks[0];cb(handshake(s));cb(packet(s));
  cb(packet({version:2,view:s.view,epoch:s.epoch,revision:s.revision+1,account:{state:'locked',displayName:''}}));
  cb(packet({...s,revision:s.revision+2}));assert.equal(h.session.phase,'offline');assert.equal(h.states.length,1);
});
test('lease timeout and explicit invalidation clear all authority',async()=>{
  for (const expire of [h=>[...h.timers.values()][0](),h=>h.callbacks[0]({protocol:PROTOCOL,kind:'invalidate',generation:'ha_generation',reason:'locked'})]) {
    const h=setup(),s=fixture();await h.session.connect(h.connection,'device');h.callbacks[0](handshake(s));h.callbacks[0](packet(s));expire(h);
    assert.equal(h.session.phase,'offline');assert.equal(h.session.binding,null);assert.equal(h.timers.size,0);
  }
});
