import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../web/portalai-projection.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function fixture(){
  const timers=new Map(),classes=new Map(),requests=[],decodes=[],messages=[],inputs=[];let id=0,draws=0;
  const context={HTMLElement:class {},window:{customCards:[]},customElements:{get:n=>classes.get(n),define:(n,c)=>classes.set(n,c)},
    setTimeout:fn=>{timers.set(++id,fn);return id;},clearTimeout:id=>timers.delete(id),atob,
    Image:class{constructor(){this.naturalWidth=80;this.naturalHeight=30;}decode(){const d=deferred();decodes.push(d);return d.promise;}}};
  vm.runInNewContext(source,context);
  const card=Object.create(classes.get('portalai-projection').prototype);
  Object.assign(card,{connected:false,connectionEpoch:0,queue:Promise.resolve(),canvas:{width:1,height:1,getContext:()=>({drawImage(){draws++;}})},
    $:()=>({}),message:m=>messages.push(m),command(action,payload){
      if(action==='frame'){const d=deferred();requests.push(d);return d.promise;}
      if(action==='input')inputs.push(payload);return Promise.resolve({});
    }});
  return {card,timers,requests,decodes,messages,inputs,draws:()=>draws};
}
test('repeated reconnects retain exactly one continuing poll loop',async()=>{
  const f=fixture();await f.card.connect();
  for(let n=0;n<10;n++){f.card.disconnect();await f.card.connect();}
  for(const r of f.requests)r.resolve({waiting:true});await flush();
  assert.equal(f.timers.size,1);
  f.card.disconnect();assert.equal(f.timers.size,0);
});
test('an old rejection cannot erase the current screen or publish an old error',async()=>{
  const f=fixture();await f.card.connect();f.card.disconnect();await f.card.connect();
  f.card.canvas.width=900;f.card.window='current';const count=f.messages.length;
  f.requests[0].reject(Error('old failure'));await flush();
  assert.equal(f.card.canvas.width,900);assert.equal(f.card.window,'current');assert.equal(f.messages.length,count);
  assert.equal(f.timers.size,0);
});
test('an old decoded image cannot paint into a new connection',async()=>{
  const f=fixture();await f.card.connect();
  const header=Buffer.alloc(48);Buffer.from([137,80,78,71,13,10,26,10]).copy(header);header.write('IHDR',12);header.writeUInt32BE(80,16);header.writeUInt32BE(30,20);
  f.requests[0].resolve({png:header.toString('base64'),width:80,height:30,window:'old'});await flush();assert.equal(f.decodes.length,1);
  f.card.disconnect();await f.card.connect();f.decodes[0].resolve();await flush();
  assert.equal(f.draws(),0);assert.equal(f.card.window,null);assert.equal(f.timers.size,0);
});
test('queued input never crosses reconnect even when the selected window is unchanged',async()=>{
  const f=fixture(),gate=deferred();await f.card.connect();f.card.window='same';f.card.queue=gate.promise;
  f.card.input({kind:'text',text:'old queued input'});const oldQueue=f.card.queue;
  f.card.disconnect();await f.card.connect();f.card.window='same';gate.resolve();await oldQueue;
  assert.equal(f.inputs.length,0);
  f.card.input({kind:'key',key:'Enter'});await f.card.queue;assert.equal(f.inputs.length,1);
});
test('a retired timer cannot issue a request on the new connection',async()=>{
  const f=fixture();await f.card.connect();f.requests[0].resolve({waiting:true});await flush();
  const callback=[...f.timers.values()][0];f.card.disconnect();await f.card.connect();const before=f.requests.length;
  await callback();assert.equal(f.requests.length,before);
});
test('ordinary Connect is idempotent and Disconnect cancels polling and resize timers',async()=>{
  const f=fixture();await f.card.connect();await f.card.connect();assert.equal(f.requests.length,1);
  f.requests[0].resolve({waiting:true});await flush();assert.equal(f.timers.size,1);
  f.card.resizeTimer=999;f.timers.set(999,()=>{});f.card.disconnect();assert.equal(f.timers.size,0);
});
