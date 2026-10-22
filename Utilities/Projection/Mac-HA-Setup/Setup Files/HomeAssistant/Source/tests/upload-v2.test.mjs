import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
globalThis.HTMLElement=class {};
globalThis.customElements={get:()=>true};
const {NativeWorkflows}=await import('../web/native-workflows.js');
function fixture(capability={connected:true,supported:true,upload_protocol:2}){
  const w=Object.create(NativeWorkflows.prototype),calls=[],notices=[];
  Object.assign(w,{active:true,resumeReady:true,ticket:1,pollTicket:1,page:'chat',dirty:new Map([['draft','retain me']]),
    model:{view:'v',epoch:'e',form:'f',account:{state:'ready'},nodes:[{id:'chat_attachment',kind:'file',enabled:true},{id:'chat_attach_uploaded',kind:'button',enabled:true}]},
    connection:{sendMessagePromise:async()=>capability},buttons(){},status:s=>notices.push(s)});
  w.request=async(operation,extra)=>{
    calls.push({operation,...extra});
    if(operation==='file_begin')return {transfer:'t'};
    if(operation.startsWith('file_chunk'))return {offset:extra.offset+Buffer.from(extra.data,'base64').length};
    if(operation==='file_commit')return {file:'done'};
    return {};
  };
  return {w,calls,notices};
}
test('5 MiB photo uses five chunks, preserves every byte/hash and admits only its token',async()=>{
  const {w,calls}=fixture(),bytes=Uint8Array.from({length:5*1024*1024},(_,i)=>i%251);
  await w.upload(w.model.nodes[0],new File([bytes],'photo.heic',{type:'image/heic'}),true);
  const chunks=calls.filter(p=>p.operation==='file_chunk_v2');assert.equal(chunks.length,5);
  assert.equal(Math.ceil(bytes.length/24576),214);
  assert.ok(chunks.every(p=>p.protocol===2&&Buffer.from(p.data,'base64').length===1048576));
  assert.deepEqual(Buffer.concat(chunks.map(p=>Buffer.from(p.data,'base64'))),Buffer.from(bytes));
  assert.equal(calls.at(-2).sha256,createHash('sha256').update(bytes).digest('hex'));
  assert.deepEqual(calls.at(-1).values,{chat_attachment:'done'});assert.equal(w.dirty.get('draft'),'retain me');
});
test('old or malformed capability and status errors retain the 24 KiB protocol',async()=>{
  for(const cap of [{},{connected:true,supported:true,upload_protocol:'2'},{connected:false,supported:true,upload_protocol:2},null]){
    const {w,calls,notices}=fixture(cap);if(cap===null)w.connection.sendMessagePromise=async()=>{throw Error('old HA');};
    await w.upload(w.model.nodes[0],new File([new Uint8Array(50000)],'file.bin'),true);
    assert.equal(calls.filter(p=>p.operation==='file_chunk').length,3);
    assert.ok(notices.some(s=>s.includes('compatibility mode')));
  }
});
test('mismatched chunk ACK stops without downgrade, commit, admission or replay',async()=>{
  const {w,calls}=fixture(),request=w.request;
  w.request=async(op,p)=>{const reply=await request(op,p);if(op==='file_chunk_v2')reply.offset--;return reply;};
  await w.upload(w.model.nodes[0],new File([new Uint8Array(2*1048576)],'file.bin'),true);
  assert.deepEqual(calls.map(p=>p.operation),['file_begin','file_chunk_v2']);assert.equal(w.uncertain,true);
});
test('changed account during negotiation never begins the transfer',async()=>{
  const {w,calls}=fixture();w.connection.sendMessagePromise=async()=>{w.model.epoch='changed';return {connected:true,supported:true,upload_protocol:2};};
  await w.upload(w.model.nodes[0],new File(['x'],'file.bin'),true);assert.equal(calls.length,0);
});
test('hidden upload can continue within grace but cannot continue after a frozen deadline',async()=>{
  for(const expired of [false,true]){
    const {w,calls}=fixture(),request=w.request;
    w.backgroundDeadline=Date.now()+10000;
    w.request=async(op,p)=>{const reply=await request(op,p);if(op==='file_chunk_v2'&&expired)w.backgroundDeadline=Date.now()-1;return reply;};
    await w.upload(w.model.nodes[0],new File([new Uint8Array(1048577)],'file.bin'),true);
    assert.equal(calls.filter(p=>p.operation==='file_chunk_v2').length,expired?1:2);
    assert.equal(calls.some(p=>p.operation==='invoke'),!expired);
  }
});
