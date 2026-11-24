// User-agent substitution exists ONLY in this local fixture, never the bundle.
const device=new URLSearchParams(location.search).get('device')||'iphone';
const scenario=new URLSearchParams(location.search).get('scenario');
let blocked=['modal','read-error'].includes(scenario);
if(device==='iphone')Object.defineProperty(navigator,'userAgent',{value:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148'});
await import('/full.js');
const snapshot={version:2,view:'a'.repeat(32),epoch:'b'.repeat(32),revision:1,account:{state:'ready',displayName:'Local test account'},runtime:{state:'ready',cpu:1,gpu:0,memory:10,model:'Fixture'},models:[],packages:[],
  settings:{selection:'auto',variant:'standard',backend:'auto',context:8192,reply:2048,effort:'Balanced',media:{media_variant:'auto',image_profile:'auto',speech_model:'auto',voice_engine:'auto',image_engine:'auto',text_video_engine:'auto',reference_video_profile:'auto',music_engine:'auto'}},
  chat:{conversations:[{id:'conversation',title:'Attachment preview',updated:''}],current:'conversation',messages:[{id:'msg1',role:'assistant',text:'Local test only. Attach a fixture file to test the picker.',truncated:false}],busy:false,contextUsed:10,contextLimit:8192,replyCap:2048,window:{conversationsComplete:true,messagesComplete:true}}};
const model={protocol:1,page:'chat',view:snapshot.view,epoch:snapshot.epoch,form:'form1',account:snapshot.account,nodes:[
  {id:'host_attach',kind:'button',action:'host_attach',label:'Attach',enabled:true},
  {id:'chat_attachment',kind:'file',label:'Attach a file (20 MiB maximum)',value:'',enabled:true},
  {id:'chat_attach_uploaded',kind:'button',label:'Add uploaded attachment',enabled:true},
  {id:'other_field',kind:'text',label:'Other conversation field',value:'',enabled:true},
]};
const result=document.createElement('pre');result.style='position:fixed;bottom:0;left:0;z-index:2000;background:white;color:black;font:12px monospace;max-width:100vw;white-space:pre-wrap';
let uploads=0,page=1;const operations=[];
const describe=()=>page===1?{...structuredClone(model),form:'page1',message:'Controls 1 of 2',nodes:[model.nodes[0],{id:'page_next',kind:'button',label:'Next controls',enabled:true}]}:{...structuredClone(model),form:'page2',message:'Controls 2 of 2'};
let generation=0;
const connection={addEventListener(){},removeEventListener(){},async subscribeMessage(callback){
  const gen='fixture'+(++generation);let revision=0;
  callback({protocol:'portalai-native-state/2',kind:'handshake',generation:gen,binding:{view:snapshot.view,epoch:snapshot.epoch},capabilities:['native.state.read'],maxFrameBytes:180000,leaseSeconds:10});
  const publish=()=>callback({protocol:'portalai-native-state/2',kind:'snapshot',generation:gen,snapshot:{...structuredClone(snapshot),revision:++revision}});
  publish();const timer=setInterval(publish,2000);return ()=>clearInterval(timer);
},async sendMessagePromise(m){
  if(m.type==='portalai_native/status')return {protocol:'portalai-native-state/2',granted:true,ready:true};
  if(m.type==='portalai_native/chat_status')return {protocol:1,supported:true,attachments_supported:true};
  if(m.type==='portalai_native/rich')return {accepted:true,request_id:m.payload.request_id,operation:m.payload.operation,rich:{protocol:1,binding:m.payload.binding,conversation:m.payload.conversation,blocks:[],truncated:false}};
  const p=m.payload;if(!p)return {accepted:true,lease_seconds:15};
  const reply={accepted:true,request_id:p.request_id,operation:p.operation};
  if(p.operation==='describe'){
    if(blocked&&scenario==='read-error')throw Error('Fixture host controls read failed');
    if(blocked)return {...reply,model:{...structuredClone(model),form:'modal',message:'Fixture host dialog is open',nodes:[{id:'dialog',kind:'note',label:'Chat instructions (fixture)',enabled:false}]}};
    return {...reply,model:describe()};
  }
  if(p.operation==='invoke'&&p.action==='page_next'){
    if(Object.keys(p.values).length)throw Error('Pagination must not submit drafts');
    page=2;result.textContent='Controls page 2 loaded without submitting drafts';return {...reply,model:describe()};
  }
  operations.push(p.operation);
  if(p.operation==='file_begin')return {...reply,transfer:'transfer1'};
  if(p.operation==='file_chunk')return {...reply,offset:p.offset+atob(p.data).length};
  if(p.operation==='file_commit')return {...reply,file:'file1'};
  if(p.operation==='invoke'){
    if(p.action!=='chat_attach_uploaded'||Object.keys(p.values).join()!=='chat_attachment')throw Error('Unexpected action/values');
    uploads++;result.textContent='PASS: attachment submissions='+uploads+'; '+operations.join(' → ');return {...reply,model:describe()};
  }
  throw Error('Unexpected operation');
}};
document.body.style.margin='0';const panel=document.createElement('portalai-live-panel');
panel._panel={config:{device_id:'d'.repeat(32)}};document.body.append(panel,result);
panel._hass={connection};panel.page='chat';panel.connectLive();
result.textContent='Fixture: '+device+'; no live host connection';
// Visible controls let automation test lifecycle invalidation without injecting
// state into the production UI.
const change=document.createElement('button');change.textContent='Test account switch';change.style='position:fixed;top:0;right:0;z-index:2000';
change.onclick=()=>{snapshot.epoch='f'.repeat(32);model.epoch=snapshot.epoch;panel.acceptState(structuredClone(snapshot));};document.body.append(change);
const expire=document.createElement('button');expire.textContent='Simulate picker connection loss';expire.style='position:fixed;top:32px;right:0;z-index:2000';
expire.onclick=()=>{panel.session.clear('expired');result.textContent='Fixture connection expired; no file sent';};document.body.append(expire);
const closeDialog=document.createElement('button');closeDialog.textContent='Close fixture host dialog';closeDialog.style='position:fixed;top:64px;right:0;z-index:2000';
closeDialog.onclick=()=>{blocked=false;result.textContent='Host dialog closed; waiting for ordinary polling';};
if(blocked)document.body.append(closeDialog);
panel.shadowRoot.addEventListener('click',event=>{
  if(event.target.closest('button')?.dataset.action==='open-attachments'){
    for(const control of [expire,change,...(blocked?[closeDialog]:[])]){control.style='';panel.shadowRoot.querySelector('.chat-tools-heading').append(control);}
  }
});
