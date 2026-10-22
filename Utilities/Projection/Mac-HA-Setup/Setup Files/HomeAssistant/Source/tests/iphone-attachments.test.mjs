import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { isIPhone, attachmentPickerMarkup } from '../web/iphone-attachments.js';

// Exercise the real controller and transfer logic without a browser or host.
globalThis.HTMLElement=class {};
globalThis.customElements={get:()=>true};
const {NativeWorkflows}=await import('../web/native-workflows.js');
const iphone='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Home Assistant/2026.10';
const model=()=>({account:{state:'ready'},view:'view1',epoch:'epoch1',form:'form1',nodes:[
  {id:'chat_attachment',kind:'file',enabled:true,label:'Attach a file'},
  {id:'chat_attach_uploaded',kind:'button',enabled:true,label:'Add uploaded attachment'},
]});
function controller(){
  const w=Object.create(NativeWorkflows.prototype);
  Object.assign(w,{iphone:true,page:'chat',active:true,resumeReady:true,pending:false,uncertain:false,ticket:1,pollTicket:1,model:model(),dirty:new Map([['unrelated_draft','do not submit']]),calls:[],notices:[]});
  w.buttons=()=>{};w.status=s=>w.notices.push(s);
  w.request=async(operation,extra)=>{w.calls.push({operation,...extra});return operation==='file_begin'?{transfer:'transfer1'}:operation==='file_chunk'?{offset:extra.offset+Buffer.from(extra.data,'base64').length}:operation==='file_commit'?{file:'file1'}:{};};
  return w;
}
const file=(name='photo.heic',data='image fixture',type='image/heic')=>new File([data],name,{type});
function selection(w,f=file(),source='photos'){
  w.pickerSelection={ticket:w.ticket,pollTicket:w.pollTicket,binding:w.binding(),form:w.model.form,source};
  return {files:f?[f]:[],value:'fakepath',dataset:{iphoneSource:source}};
}

test('iPhone detection excludes iPad, Android, and desktop regardless of viewport',()=>{
  assert.equal(isIPhone(iphone),true);
  for(const ua of ['Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)','Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15','Mozilla/5.0 (Linux; Android 15)','Mozilla/5.0 (Windows NT 10.0; Win64; x64)',''])assert.equal(isIPhone(ua),false);
});
test('sources use real file inputs: images/videos and unrestricted Files, without forced capture',()=>{
  assert.match(attachmentPickerMarkup, /accept="image\/\*,video\/\*"/);
  assert.match(attachmentPickerMarkup, /<input type="file" data-iphone-source="files"/);
  assert.doesNotMatch(attachmentPickerMarkup,/capture|multiple|webkitdirectory/);
});
test('desktop exposes a drop zone and chooser with automatic token admission',()=>{
  const w=controller();w.iphone=false;
  assert.match(w.node(w.model.nodes[0]),/type="file"/);
  assert.match(w.node(w.model.nodes[0]),/data-drop-field="chat_attachment"/);
  assert.equal(w.node(w.model.nodes[1]),'');
  w.iphone=true;
  assert.match(w.node(w.model.nodes[0]),/data-command="iphone-attach"/);
  assert.equal(w.node(w.model.nodes[1]),'');
  w.page='settings';assert.match(w.node(w.model.nodes[0]),/type="file"/);
});
function drag(w,files,types=['Files'],items=[]){
  const zone={dataset:{dropField:'chat_attachment'},classList:{remove(){},toggle(){}},contains:()=>false};
  return {type:'drop',target:{closest:()=>zone},dataTransfer:{types,files,items},preventDefault(){this.prevented=true;},stopPropagation(){}};
}
test('desktop file drop uploads and attaches once, without submitting drafts',async()=>{
  const w=controller();w.iphone=false;const event=drag(w,[file('desktop.txt','hello','text/plain')]);
  await w.fileDrag(event);assert.equal(event.prevented,true);
  assert.deepEqual(w.calls.map(c=>c.operation),['file_begin','file_chunk','file_commit','invoke']);
  assert.deepEqual(w.calls.at(-1).values,{chat_attachment:'file1'});
  assert.equal(w.dirty.get('unrelated_draft'),'do not submit');
});
test('desktop rejects text, multiple files, folders, disabled and disconnected drop targets',async()=>{
  for(const [files,types,items,mutate] of [
    [[],['text/plain'],[],()=>{}],[[file(),file()],['Files'],[],()=>{}],
    [[file()],['Files'],[{kind:'file',webkitGetAsEntry:()=>({isDirectory:true})}],()=>{}],
    [[file()],['Files'],[],w=>w.active=false],[[file()],['Files'],[],w=>w.pending=true],
    [[file()],['Files'],[],w=>w.model.account.state='locked'],[[file()],['Files'],[],w=>w.model.nodes[0].enabled=false]]){
    const w=controller();w.iphone=false;mutate(w);const event=drag(w,files,types,items);
    await w.fileDrag(event);assert.equal(w.calls.length,0);
    assert.equal(Boolean(event.prevented),types.includes('Files'));
  }
});
test('desktop file chooser resets for repeat selection and uses token admission',async()=>{
  const w=controller();w.iphone=false;
  let received;w.upload=async(...args)=>{received=args;};
  const input={dataset:{field:'chat_attachment'},type:'file',files:[file()],value:'fake'};
  w.click({target:input});w.change({target:input});assert.equal(input.value,'');assert.equal(received[2],true);
});
test('desktop chooser result is rejected after the form or viewer changes',async()=>{
  for(const mutate of [w=>w.model.form='other',w=>w.model.epoch='other',w=>w.pollTicket++]){
    const w=controller();w.iphone=false;const input={type:'file',dataset:{field:'chat_attachment'},files:[file()],value:'fake'};
    w.click({target:input});mutate(w);await w.change({target:input});
    assert.equal(w.calls.length,0);assert.equal(input.value,'');
  }
});
test('chosen photo uploads bytes and checksum, then admits only its token exactly once',async()=>{
  const w=controller(),input=selection(w);
  await w.pickAttachment(input);
  assert.equal(input.value,'');assert.equal(w.pickerSelection,null);
  assert.deepEqual(w.calls.map(x=>x.operation),['file_begin','file_chunk','file_commit','invoke']);
  assert.equal(w.calls[0].name,'photo.heic');assert.equal(w.calls[0].mime,'image/heic');
  assert.equal(w.calls[2].sha256,createHash('sha256').update('image fixture').digest('hex'));
  assert.deepEqual(w.calls[3].values,{chat_attachment:'file1'});
  assert.equal(w.calls[3].action,'chat_attach_uploaded');
  assert.equal(w.dirty.get('unrelated_draft'),'do not submit');
  assert.equal(w.pending,false);assert.equal(w.uncertain,false);
});

test('a returned iPhone selection refreshes the form before the first upload byte',async()=>{
  const w=controller(),input=selection(w);w.pickerOpen=w.pickerSelection;
  let resumed=0,uploaded=0;w.onPickerReturn=async()=>{resumed++;w.active=true;return true;};
  w.pickerStillCurrent=()=>true;w.accept=m=>{w.model=m;w.resumeReady=true;};w.loadAttachmentControls=async()=>{};
  w.request=async(operation)=>{w.calls.push(operation);return {model:{...model(),form:'fresh-form'}};};
  w.upload=async()=>{uploaded++;assert.equal(w.model.form,'fresh-form');};
  await w.pickAttachment(input);clearTimeout(w.timer);
  assert.equal(resumed,1);assert.deepEqual(w.calls,['describe']);assert.equal(uploaded,1);
});

test('failed reconnection and a changed conversation never read or upload the selected file',async()=>{
  for(const connected of [false,true]){
    const w=controller(),input=selection(w);w.pickerOpen=w.pickerSelection;
    w.onPickerReturn=async()=>connected;w.pickerStillCurrent=()=>false;
    w.accept=m=>{w.model=m;w.resumeReady=true;};w.loadAttachmentControls=async()=>{};
    w.request=async()=>({model:model()});w.upload=async()=>assert.fail('No upload permitted');
    await w.pickAttachment(input);assert.match(w.notices.at(-1),/not uploaded/);
  }
});
test('video and Files selections use the same transfer; same filename can be chosen again',async()=>{
  for(const [name,mime,source] of [['clip.mov','video/quicktime','photos'],['document.pdf','application/pdf','files'],['notes.txt','','files']]){
    const w=controller();for(let n=0;n<2;n++)await w.pickAttachment(selection(w,file(name,'data',mime),source));
    assert.equal(w.calls.filter(x=>x.operation==='invoke').length,2);
    assert.equal(w.calls[0].mime,mime||'application/octet-stream');
  }
});
test('canceling or selecting oversized files never sends a host operation',async()=>{
  const w=controller();await w.pickAttachment(selection(w,null));assert.equal(w.calls.length,0);
  await w.pickAttachment(selection(w,{name:'large.mov',size:20*1024*1024+1}));
  assert.equal(w.calls.length,0);assert.match(w.notices.at(-1),/20 MiB/);assert.equal(w.uncertain,false);
});
test('stale picker results cannot target a different account, form, or resumed session',async()=>{
  for(const mutate of [w=>w.model.view='other',w=>w.model.epoch='other',w=>w.model.form='other',w=>w.pollTicket++,w=>w.ticket++,w=>w.active=false,w=>w.resumeReady=false,w=>w.model.account.state='locked',w=>w.model.nodes[1].enabled=false]){
    const w=controller(),input=selection(w);mutate(w);await w.pickAttachment(input);assert.equal(w.calls.length,0);assert.equal(input.value,'');
  }
});
test('invalid chunk receipt halts the upload without commit, admission, or automatic retry',async()=>{
  const w=controller(),request=w.request;w.request=async(op,p)=>{const r=await request(op,p);return op==='file_chunk'?{offset:999}:r;};
  await w.pickAttachment(selection(w));
  assert.deepEqual(w.calls.map(x=>x.operation),['file_begin','file_chunk']);assert.equal(w.uncertain,true);
  await w.pickAttachment(selection(w));assert.equal(w.calls.length,2);
});
test('disconnect while bytes are read and account change after commit prevent admission',async()=>{
  const w=controller();const f={name:'file.txt',type:'',size:1,arrayBuffer:async()=>{w.active=false;w.pollTicket++;return new Uint8Array([1]).buffer;}};
  await w.pickAttachment(selection(w,f));assert.equal(w.calls.length,0);
  const v=controller(),request=v.request;v.request=async(op,p)=>{const r=await request(op,p);if(op==='file_commit')v.model.form='new';return r;};
  await v.pickAttachment(selection(v));assert.equal(v.calls.some(x=>x.operation==='invoke'),false);
});
test('failed admission is uncertain and is never automatically replayed',async()=>{
  const w=controller(),request=w.request;w.request=async(op,p)=>{const r=await request(op,p);if(op==='invoke')throw Error('Outcome unknown');return r;};
  await w.pickAttachment(selection(w));assert.equal(w.uncertain,true);assert.equal(w.pending,false);
  await w.pickAttachment(selection(w));assert.equal(w.calls.filter(x=>x.operation==='invoke').length,1);
});

function pagedController(){
  const w=controller();w.attachmentRequested=true;w.attachmentSearched=false;w.attachmentLoad=null;
  w.model.nodes=[{id:'host_attach',kind:'button',label:'Attach',enabled:true},{id:'page_next',kind:'button',enabled:true}];
  w.accept=m=>{w.model=m;};
  w.request=async(operation,p)=>{w.calls.push({operation,...p});return {model:{...model(),form:'form2'}};};
  return w;
}
test('Attach finds upload controls on the second host page without submitting other fields',async()=>{
  const w=pagedController();assert.equal(w.attachmentReady(),false);
  await w.loadAttachmentControls();
  assert.equal(w.attachmentReady(),true);assert.equal(w.model.form,'form2');
  assert.deepEqual(w.calls,[{operation:'invoke',binding:{view:'view1',epoch:'epoch1'},form:'form1',action:'page_next',values:{}}]);
  assert.equal(w.dirty.get('unrelated_draft'),'do not submit');
  assert.equal(w.attachmentLoad,null);assert.match(w.attachmentNotice(),/^Ready/);
});
test('Attach intercepts the host Attach button even when file fields are on another page',()=>{
  const w=pagedController();assert.match(w.node(w.model.nodes[0]),/data-command="iphone-attach"/);
  w.iphone=false;assert.match(w.node(w.model.nodes[0]),/data-command="desktop-attach"/);
  assert.doesNotMatch(w.node(w.model.nodes[0]),/data-work-action/);
});
test('attachment discovery does not navigate while hidden, locked, pending or awaiting a describe',async()=>{
  for(const mutate of [w=>w.attachmentRequested=false,w=>w.active=false,w=>w.resumeReady=false,w=>w.pending=true,w=>w.uncertain=true,w=>w.fetching='request',w=>w.model.account.state='locked']){
    const w=pagedController();mutate(w);await w.loadAttachmentControls();assert.equal(w.calls.length,0);
  }
});
test('pagination responses are discarded after closing, disconnecting, account or form changes',async()=>{
  for(const mutate of [w=>w.attachmentRequested=false,w=>w.active=false,w=>w.pollTicket++,w=>w.ticket++,w=>w.model.view='new',w=>w.model.form='new']){
    const w=pagedController();let accepted=false;w.accept=()=>accepted=true;
    w.request=async()=>{mutate(w);return {model:{...model(),form:'form2'}};};
    await w.loadAttachmentControls();assert.equal(accepted,false);assert.equal(w.attachmentLoad,null);
  }
});
test('pagination never accepts a different account and does not automatically repeat a failed search',async()=>{
  const w=pagedController();w.request=async()=>{w.calls.push(1);return {model:{...model(),view:'other'}};};
  await w.loadAttachmentControls();await w.loadAttachmentControls();
  assert.equal(w.model.view,'view1');assert.equal(w.calls.length,1);assert.match(w.notices.at(-1),/account changed/);
});
test('missing or disabled controls show an actionable status rather than silently dead choices',async()=>{
  const w=pagedController();w.model.nodes=[];await w.loadAttachmentControls();
  assert.match(w.attachmentNotice(),/Return to conversation tools/);assert.equal(w.calls.length,0);
  w.model=model();w.model.nodes[0].enabled=false;assert.match(w.attachmentNotice(),/current operation/);
});
test('pagination search is bounded and never replays a repeated form',async()=>{
  const w=pagedController();w.request=async()=>{w.calls.push(1);return {model:w.model};};
  await w.loadAttachmentControls();assert.equal(w.calls.length,1);
  const v=pagedController();v.request=async()=>{v.calls.push(1);return {model:{...v.model,form:'form'+(v.calls.length+1)}};};
  await v.loadAttachmentControls();assert.equal(v.calls.length,32);
});

// Minimal DOM surface, with real accept/refresh/buttons/discovery methods.
function refreshController(t){
  const w=controller(),elements=new Map();
  const element=()=>({childNodes:[],dataset:{},querySelectorAll:()=>[],replaceChildren(){this.childNodes=[];}});
  globalThis.document={createElement:()=>({content:element()})};
  w.$=selector=>{if(!elements.has(selector))elements.set(selector,element());return elements.get(selector);};
  w.shadowRoot={querySelectorAll:()=>[]};w.buttons=NativeWorkflows.prototype.buttons;
  w.connection={};w.attachmentRequested=true;w.attachmentSearched=false;
  w.model=null;w.resumeReady=false;
  t.after(()=>{clearTimeout(w.timer);clearTimeout(w.expiry);});
  return w;
}
const controls=(form,nodes=[])=>({...model(),protocol:1,page:'chat',form,nodes});
const nextPage={id:'page_next',kind:'button',enabled:true};

test('failed initial describe clears Loading and shows a recovery instruction',async t=>{
  const w=refreshController(t);let reject;
  w.request=()=>new Promise((_,fail)=>reject=fail);
  const refreshing=w.refresh();assert.match(w.$('[data-attachment-status]').textContent,/Loading/);
  reject(Error('Host dialog blocks controls'));await refreshing;
  assert.equal(w.fetching,null);assert.equal(w.resumeReady,false);
  assert.match(w.$('[data-attachment-status]').textContent,/Check PortalAI for an open dialog/);
  assert.equal(w.notices.at(-1),'Host dialog blocks controls');
});

test('successful modal describe settles with an actionable notice instead of Loading',async t=>{
  const w=refreshController(t);w.request=async()=>({model:controls('modal')});
  await w.refresh();
  assert.equal(w.fetching,null);assert.equal(w.attachmentLoad,null);
  assert.match(w.$('[data-attachment-status]').textContent,/Return to conversation tools/);
  assert.equal(w.attachmentSearched,true);
});

test('closing a modal discovers the new form attachment page without reopening Attach',async t=>{
  const w=refreshController(t);let modal=true;
  w.request=async(operation,p)=>{
    w.calls.push({operation,...p});
    return {model:modal?controls('modal'):operation==='describe'?controls('page1',[nextPage]):controls('page2',model().nodes)};
  };
  await w.refresh();assert.equal(w.attachmentReady(),false);
  modal=false;await w.refresh();
  assert.equal(w.attachmentReady(),true);assert.equal(w.model.form,'page2');
  assert.match(w.$('[data-attachment-status]').textContent,/^Ready/);
  assert.deepEqual(w.calls.filter(c=>c.operation==='invoke'),[{operation:'invoke',binding:{view:'view1',epoch:'epoch1'},form:'page1',action:'page_next',values:{}}]);
});

test('failed pagination is not replayed by same-form polls, even after model expiry',async t=>{
  const w=refreshController(t);let navigations=0;
  w.request=async operation=>{if(operation==='invoke'){navigations++;throw Error('Not available');}return {model:controls('page1',[nextPage])};};
  await w.refresh();await w.refresh();
  w.model=null;w.resumeReady=false;await w.refresh();
  assert.equal(navigations,1);assert.equal(w.attachmentSearched,true);
  assert.doesNotMatch(w.$('[data-attachment-status]').textContent,/Loading/);
});

test('failed describe does not navigate using an older accepted form',async t=>{
  const w=refreshController(t);w.accept(controls('page1',[nextPage]));
  w.request=async operation=>{w.calls.push(operation);throw Error('Host unavailable');};
  await w.refresh();assert.deepEqual(w.calls,['describe']);
  assert.equal(w.notices.at(-1),'Host unavailable');
  assert.doesNotMatch(w.$('[data-attachment-status]').textContent,/Loading/);
});

test('stale failed refresh cannot clear a new request or replace its status',async t=>{
  const w=refreshController(t);let reject;
  w.request=()=>new Promise((_,fail)=>reject=fail);
  const refreshing=w.refresh();w.pollTicket++;w.fetching='new-request';w.status('New session');
  reject(Error('Old failure'));await refreshing;
  assert.equal(w.fetching,'new-request');assert.equal(w.notices.at(-1),'New session');
  assert.equal(w.timer,undefined);
});
