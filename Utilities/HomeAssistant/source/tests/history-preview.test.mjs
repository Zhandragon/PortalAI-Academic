import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.HTMLElement=class {};
globalThis.customElements={get(){return true;},define(){}};
globalThis.document={hidden:false};
const {NativeWorkflows}=await import('../web/native-workflows.js');
const {RichChat,validateRich}=await import('../web/rich-chat.js');
test('History opens the advertised host action once, after fresh controls arrive',async()=>{
  const w=Object.create(NativeWorkflows.prototype);Object.assign(w,{historyRequested:true,resumeReady:false,pending:false,fetching:null,uncertain:false});
  const calls=[];w.invoke=async a=>calls.push(a);w.status=()=>{};
  await w.loadHistory();assert.equal(w.historyRequested,true);assert.equal(calls.length,0);
  w.resumeReady=true;w.model={nodes:[{id:'chat_history',action:'chat_history',enabled:true}]};
  await w.loadHistory();await w.loadHistory();assert.deepEqual(calls,['chat_history']);
});
test('unavailable or uncertain history does not invent or retry a host action',async()=>{
  const w=Object.create(NativeWorkflows.prototype);let calls=0;w.invoke=()=>calls++;w.status=()=>{};
  Object.assign(w,{historyRequested:true,resumeReady:true,model:{nodes:[]}});await w.loadHistory();assert.equal(calls,0);
  w.historyRequested=true;w.uncertain=true;await w.loadHistory();assert.equal(calls,0);
});
test('preview protocol rejects oversized, partial and unexpected MIME responses',()=>{
  const p={operation:'rich_preview',request_id:'x',binding:{view:'v',epoch:'e'},conversation:'c',block:'b',offset:0};
  const rich={protocol:1,binding:p.binding,conversation:'c',block:'b',offset:0,next:3,size:3,mime:'image/jpeg',name:'preview.jpg',data:'/9j/',eof:true,identity:'identity'};
  const reply={accepted:true,request_id:'x',operation:p.operation,rich};assert.equal(validateRich(reply,p),rich);
  for(const patch of [{size:24577},{eof:false},{mime:'text/html'},{offset:1},{protocol:2}])assert.throws(()=>validateRich({...reply,rich:{...rich,...patch}},p));
});
test('tool overlays retain same-account preview cache; account change and disconnect revoke it',()=>{
  const root={querySelectorAll:()=>[],querySelector:()=>null};const r=new RichChat(root),conn={},d={connected:true,viewer:'viewer'};
  r.refresh=()=>{};r.render=()=>{};
  const s={view:'v',epoch:'e',chat:{current:'c'}};
  r.configure(conn,'device',s,d,true);r.urls.set('b',{url:'blob:test',size:10});r.total=10;
  r.configure(conn,'device',s,d,false);assert.equal(r.urls.size,1);assert.equal(r.paused,true);
  r.configure(conn,'device',s,d,true);assert.equal(r.urls.size,1);
  r.configure(conn,'device',{...s,epoch:'different'},d,true);assert.equal(r.urls.size,0);
  r.configure(null,'device',s,d,false);assert.equal(r.scope,'');
});
