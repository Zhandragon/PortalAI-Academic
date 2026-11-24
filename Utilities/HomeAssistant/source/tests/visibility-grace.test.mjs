import test from 'node:test';
import assert from 'node:assert/strict';
import {VisibilityGrace} from '../web/visibility-grace.js';
import {PortalAIViewerDemand} from '../web/portalai-viewer-demand.js';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
test('default browser timers retain their Window receiver',()=>{
  const source=readFileSync(new URL('../web/visibility-grace.js',import.meta.url),'utf8').replace(/^export /gm,'');
  const context={};vm.runInNewContext(`
    function setTimeout(){if(this!==globalThis)throw TypeError('Illegal invocation');return 1;}
    function clearTimeout(){if(this!==globalThis)throw TypeError('Illegal invocation');}
    ${source}
    globalThis.Grace=VisibilityGrace;`,context);
  const grace=new context.Grace(()=>{});assert.doesNotThrow(()=>{grace.change(true);grace.reset();});
});
function fixture(){
  let now=100,count=0,expire=0;const timers=new Map();
  const grace=new VisibilityGrace(()=>expire++,{now:()=>now,setTimer:fn=>{timers.set(++count,fn);return count;},clearTimer:id=>timers.delete(id)});
  return {grace,timers,advance:ms=>now+=ms,expired:()=>expire};
}
test('short hide retains the session and returning cancels expiry',()=>{
  const f=fixture();f.grace.change(true);f.advance(9999);assert.equal(f.grace.change(false),true);
  assert.equal(f.expired(),0);assert.equal(f.timers.size,0);assert.equal(f.grace.deadline,0);
});
test('frozen timers cannot extend grace and repeated hide cannot reset its deadline',()=>{
  const f=fixture();f.grace.change(true);const deadline=f.grace.deadline;f.advance(9000);f.grace.change(true);
  assert.equal(f.grace.deadline,deadline);f.advance(1000);assert.equal(f.grace.change(false),false);assert.equal(f.expired(),1);
  assert.equal(f.timers.size,0);
});
test('explicit disconnect reset never reconnects from a stale callback',()=>{
  const f=fixture();f.grace.change(true);const callback=[...f.timers.values()][0];f.grace.reset();f.advance(20000);callback();assert.equal(f.expired(),0);
});
test('viewer stops renewals in background, renews only on return, and releases immediately on Disconnect',async()=>{
  const calls=[],demand=new PortalAIViewerDemand({callWS:async p=>{calls.push(p.action);return {accepted:true,lease_seconds:15};}},'d'.repeat(32),'native');
  try{
    await demand.connect();await demand.background();assert.equal(demand.timer,null);assert.equal(demand.connected,true);
    await demand.background();assert.deepEqual(calls,['acquire','background']);
    await demand.foreground();assert.ok(demand.timer);await demand.disconnect();assert.equal(demand.timer,null);
    assert.deepEqual(calls,['acquire','background','foreground','release']);
  }finally{await demand.disconnect();}
});
test('expired server grace requires explicit reconnect',async()=>{
  let lost=0;const demand=new PortalAIViewerDemand({callWS:async p=>{if(p.action==='foreground')throw Error('expired');return {accepted:true,lease_seconds:15};}},'d'.repeat(32),'native',()=>lost++);
  await demand.connect();await demand.background();await demand.foreground();assert.equal(lost,1);assert.equal(demand.connected,false);assert.equal(demand.timer,null);
});
