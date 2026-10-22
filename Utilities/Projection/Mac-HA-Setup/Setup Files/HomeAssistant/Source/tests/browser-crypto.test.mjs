import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,randomBytes,webcrypto} from 'node:crypto';
import {randomId,sha256Hex} from '../web/browser-crypto.js';

async function withCrypto(value,run){
  const original=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  Object.defineProperty(globalThis,'crypto',{value,configurable:true});
  try{return await run();}finally{Object.defineProperty(globalThis,'crypto',original);}
}
const httpCrypto={getRandomValues:bytes=>webcrypto.getRandomValues(bytes)};
const expected=bytes=>createHash('sha256').update(bytes).digest('hex');

test('HTTP identifiers use CSPRNG bytes and retain the existing UUID format',async()=>{
  let calls=0;
  await withCrypto({getRandomValues:bytes=>{calls++;bytes.fill(255);return bytes;}},()=>{
    assert.equal(randomId(),'ffffffffffff4fffbfffffffffffffff');assert.equal(calls,1);
  });
  await withCrypto(httpCrypto,()=>{
    const ids=Array.from({length:1000},randomId);
    assert.equal(new Set(ids).size,ids.length);
    for(const id of ids)assert.match(id,/^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/);
  });
});

test('missing or failed CSPRNG never falls back to predictable identifiers',async()=>{
  await withCrypto({},()=>assert.throws(randomId));
  await withCrypto({getRandomValues:()=>{throw Error('unavailable');}},()=>assert.throws(randomId,/unavailable/));
});

test('HTTP SHA-256 matches known vectors and every padding boundary',async()=>{
  await withCrypto(httpCrypto,async()=>{
    for(const text of ['', 'abc', 'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq', 'a'.repeat(1000000)]){
      const bytes=new TextEncoder().encode(text);assert.equal(await sha256Hex(bytes),expected(bytes));
    }
    for(const size of [1,2,55,56,57,63,64,65,119,120,121,127,128,129,1024,262143,262144,262145]){
      const bytes=randomBytes(size+11).subarray(7,7+size);
      assert.equal(await sha256Hex(bytes),expected(bytes),'length '+size);
    }
  });
});

test('maximum-size HTTP checksum yields to browser events and enforces the transfer cap',async()=>{
  await withCrypto(httpCrypto,async()=>{
    const bytes=new Uint8Array(20*1024*1024).fill(97);let yielded=false;
    setTimeout(()=>{yielded=true;},0);
    assert.equal(await sha256Hex(bytes),expected(bytes));assert.equal(yielded,true);
    await assert.rejects(sha256Hex(new Uint8Array(bytes.length+1)),/20 MiB/);
    await assert.rejects(sha256Hex('abc'),/bytes/);
  });
});

test('HTTPS uses native SHA-256 and does not hide native digest failures',async()=>{
  await withCrypto(webcrypto,async()=>{
    const bytes=randomBytes(997);assert.equal(await sha256Hex(bytes),expected(bytes));
  });
  await withCrypto({subtle:{digest:()=>Promise.reject(Error('native failed'))}},async()=>{
    await assert.rejects(sha256Hex(new Uint8Array(1)),/native failed/);
  });
});

test('plain HTTP attachment upload and export preserve checksum validation',async()=>{
  globalThis.HTMLElement=class {};
  globalThis.customElements={get:()=>true};
  const {NativeWorkflows}=await import('../web/native-workflows.js');
  const bytes=randomBytes(70000),calls=[],notices=[];
  const w=Object.create(NativeWorkflows.prototype);
  Object.assign(w,{active:true,resumeReady:true,pending:false,uncertain:false,ticket:1,pollTicket:1,
    model:{view:'v',epoch:'e',form:'f'},dirty:new Map(),buttons(){},status:s=>notices.push(s)});
  w.request=async(operation,extra)=>{
    calls.push({operation,...extra});
    return operation==='file_begin'?{transfer:'t'}:operation==='file_chunk'?{offset:extra.offset+Buffer.from(extra.data,'base64').length}:operation==='file_commit'?{file:'f'}:{};
  };
  await withCrypto(httpCrypto,async()=>{
    await w.upload({id:'upload',enabled:true},new File([bytes],'test.bin'));
    assert.deepEqual(calls.map(x=>x.operation),['file_begin','file_chunk','file_chunk','file_chunk','file_commit']);
    assert.equal(calls.at(-1).sha256,expected(bytes));assert.equal(w.dirty.get('upload'),'f');assert.equal(w.uncertain,false);
    // A corrupted export must never be published, including in HTTP mode.
    w.request=async(_op,{offset})=>({size:3,offset,data:Buffer.from('abc').toString('base64'),eof:true,sha256:'0'.repeat(64)});
    let publications=0;globalThis.document={createElement:()=>{publications++;throw Error('unexpected publication');}};
    await w.download({file:'export'});
    assert.equal(publications,0);assert.equal(notices.at(-1),'Export checksum mismatch');
    w.request=async(_op,{offset})=>({size:3,offset,data:Buffer.from('abc').toString('base64'),eof:true,sha256:expected(Buffer.from('abc'))});
    let downloaded;globalThis.document={createElement:()=>({click(){downloaded=this.href;publications++;}})};
    const timeout=globalThis.setTimeout;
    globalThis.setTimeout=fn=>{fn();return 0;};
    try{await w.download({file:'export',name:'test.bin'});}finally{globalThis.setTimeout=timeout;}
    assert.equal(publications,1);assert.match(downloaded,/^blob:/);assert.equal(notices.at(-1),'Export downloaded.');
  });
});

test('disconnect during yielding HTTP hash prevents upload start',async()=>{
  globalThis.HTMLElement=class {};globalThis.customElements={get:()=>true};
  const {NativeWorkflows}=await import('../web/native-workflows.js');
  const w=Object.create(NativeWorkflows.prototype);let requests=0;
  Object.assign(w,{active:true,resumeReady:true,pending:false,uncertain:false,ticket:1,pollTicket:1,
    model:{view:'v',epoch:'e',form:'f'},dirty:new Map(),buttons(){},status(){},request:async()=>{requests++;}});
  await withCrypto(httpCrypto,async()=>{
    setTimeout(()=>{w.active=false;w.pollTicket++;},0);
    await w.upload({id:'upload',enabled:true},new File([new Uint8Array(1024*1024)],'test.bin'));
    assert.equal(requests,0);assert.equal(w.pending,false);
  });
});
