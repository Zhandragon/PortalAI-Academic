import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

function fixture(){
  class Element {
    constructor(){this.children=[];this.style={};this.dataset={};this.elements=new Map();this.classList={add(){},toggle(){},contains(){return false;}};}
    attachShadow(){return this.shadowRoot=new Element();}
    addEventListener(){} removeEventListener(){} setAttribute(){} toggleAttribute(){} hasAttribute(){return false;}
    querySelector(selector){if(!this.elements.has(selector))this.elements.set(selector,new Element());return this.elements.get(selector);}
    querySelectorAll(){return [];}
    append(...children){this.children.push(...children);} prepend(...children){this.children.unshift(...children);}
    replaceChildren(...children){this.children=children;}
  }
  const classes=new Map(),timers=new Map();let counter=0;
  const context={HTMLElement:Element,Uint8Array,Uint32Array,DataView,TextEncoder,URL,Blob,
    crypto:{getRandomValues:bytes=>webcrypto.getRandomValues(bytes)},
    document:{hidden:false,createElement:()=>new Element(),addEventListener(){}},
    window:{customCards:[],addEventListener(){}},navigator:{userAgent:'Mozilla/5.0 (iPhone)'},
    screen:{width:390,height:844},innerWidth:390,innerHeight:844,
    customElements:{get:n=>classes.get(n),define:(n,c)=>classes.set(n,c)},
    ResizeObserver:class{observe(){}},matchMedia:()=>({matches:false}),
    setTimeout:fn=>{timers.set(++counter,fn);return counter;},clearTimeout:id=>timers.delete(id),Date};
  return {context,classes,timers};
}

for(const [file,tag] of [['portalai-live-v0.5.12.js','portalai-live-panel'],['portalai-quick-chat-v0.4.3.js','portalai-quick-chat'],['portalai-projection-v0.5.12.js','portalai-projection']]){
  test('HTTP-only crypto can construct deployed '+file,()=>{
    const f=fixture();
    const source=fs.readFileSync(new URL('../dist/'+file,import.meta.url),'utf8');
    assert.doesNotMatch(source,/crypto\.randomUUID/);
    vm.runInNewContext(source,f.context);
    const Card=f.classes.get(tag);assert.ok(Card,'registered '+tag);
    const card=new Card();assert.match(card.viewer,/^[0-9a-f]{32}$/);assert.ok(card.shadowRoot);
    if(f.classes.has('portalai-native-workflows'))assert.match(new (f.classes.get('portalai-native-workflows'))().viewer,/^[0-9a-f]{32}$/);
  });
}

test('HTTP-only crypto can acquire and release a real viewer-demand controller',async()=>{
  const f=fixture(),calls=[];
  vm.runInNewContext(fs.readFileSync(new URL('../dist/portalai-live-v0.5.12.js',import.meta.url),'utf8')+'\nglobalThis.Demand=PortalAIViewerDemand;',f.context);
  const demand=new f.context.Demand({callWS:async request=>{calls.push(request);return {accepted:true,lease_seconds:15};}},'a'.repeat(32),'native');
  await demand.connect();assert.equal(demand.connected,true);assert.equal(f.timers.size,1);
  assert.match(calls[0].viewer,/^[0-9a-f]{32}$/);
  await demand.disconnect();assert.equal(f.timers.size,0);assert.equal(calls.at(-1).action,'release');
});

test('bundled native panel keeps workflow active through a short hide and retires it after frozen grace',()=>{
  const f=fixture();let now=100000;f.context.Date={now:()=>now};
  vm.runInNewContext(fs.readFileSync(new URL('../dist/portalai-live-v0.5.12.js',import.meta.url),'utf8'),f.context);
  const panel=new (f.classes.get('portalai-live-panel'))();let background=0,foreground=0,released=0,active;
  panel.page='chat';panel.chatToolsOpen=true;panel._connection={removeEventListener(){}};
  panel.configureRich=()=>{};panel.session={demand:{connected:true,background(){background++;},foreground(){foreground++;}},clear(){released++;panel.session.demand=null;}};
  const workflow={configure(...args){active=args.at(-1);}};panel.shadowRoot.querySelector=()=>workflow;
  f.context.document.hidden=true;panel.visibilityChanged();assert.equal(background,1);assert.equal(active,true);assert.equal(workflow.backgroundDeadline,110000);
  now+=9000;f.context.document.hidden=false;panel.visibilityChanged();assert.equal(foreground,1);assert.equal(active,true);assert.equal(released,0);
  f.context.document.hidden=true;panel.visibilityChanged();now+=10000;f.context.document.hidden=false;panel.visibilityChanged();
  assert.equal(released,1);assert.equal(panel._connection,null);assert.equal(foreground,1);
});

test('bundled projection pauses polling during grace and never resumes a retired connection',async()=>{
  const f=fixture();let now=100000;f.context.Date={now:()=>now};
  vm.runInNewContext(fs.readFileSync(new URL('../dist/portalai-projection-v0.5.12.js',import.meta.url),'utf8'),f.context);
  const card=new (f.classes.get('portalai-projection'))();card.connected=true;card.config={device_id:'a'.repeat(32)};
  let polls=0;const requests=[];card.poll=()=>polls++;card._hass={callWS:async p=>{requests.push(p);return {accepted:true};}};
  f.context.document.hidden=true;card.visibilityChange();await Promise.resolve();assert.equal(card.connected,true);assert.equal(polls,0);
  now+=5000;f.context.document.hidden=false;card.visibilityChange();await Promise.resolve();assert.equal(polls,1);
  f.context.document.hidden=true;card.visibilityChange();now+=10000;f.context.document.hidden=false;card.visibilityChange();await Promise.resolve();
  assert.equal(card.connected,false);assert.equal(polls,1);assert.equal(requests.at(-1).action,'disconnect');
});

test('heartbeat returning across a hide/show cycle cannot create a second renewal loop',async()=>{
  const f=fixture();let renew;
  vm.runInNewContext(fs.readFileSync(new URL('../dist/portalai-live-v0.5.12.js',import.meta.url),'utf8')+'\nglobalThis.Demand=PortalAIViewerDemand;',f.context);
  const demand=new f.context.Demand({callWS:async p=>p.action==='renew'?new Promise(resolve=>renew=resolve):{accepted:true,lease_seconds:15}},'a'.repeat(32),'native');
  await demand.connect();const [id,timer]=[...f.timers.entries()][0];f.timers.delete(id);const pending=timer();
  await demand.background();await demand.foreground();assert.equal(f.timers.size,1);
  renew({accepted:true,lease_seconds:15});await pending;assert.equal(f.timers.size,1);
  await demand.disconnect();assert.equal(f.timers.size,0);
});

function pickerPanel(){
  const f=fixture();vm.runInNewContext(fs.readFileSync(new URL('../dist/portalai-live-v0.5.12.js',import.meta.url),'utf8'),f.context);
  const panel=new (f.classes.get('portalai-live-panel'))();
  const snapshot={view:'view',epoch:'epoch',account:{state:'ready'},chat:{current:'chat'}};
  panel._panel={config:{device_id:'d'.repeat(32)}};panel.model.snapshot=snapshot;panel.model.status='ready';
  panel._connection={addEventListener(){},removeEventListener(){}};panel._hass={connection:panel._connection};
  let renders=0,suspended=0;panel.render=()=>renders++;
  const workflow={suspendPicker(){suspended++;},status(){},buttons(){}};
  const selection={binding:{view:'view',epoch:'epoch'},form:'old-form'};
  panel.beginFilePicker(workflow,selection);
  return {f,panel,workflow,selection,snapshot,renders:()=>renders,suspended:()=>suspended};
}

test('picker survives session expiry without retaining account state or detaching its input',()=>{
  const t=pickerPanel();t.panel.model.drafts.set('chat','private draft');
  t.panel.clearLive('expired');
  assert.ok(t.panel.pickerContext);assert.equal(t.renders(),0);assert.equal(t.suspended(),1);
  assert.equal(t.panel.model.snapshot,null);assert.equal(t.panel.model.drafts.size,0);assert.equal(t.panel._connection,null);
});

test('returning from a long picker requires a new authenticated snapshot of the same conversation',async()=>{
  const t=pickerPanel();t.panel.clearLive('expired');let connects=0;
  t.panel.session={connect(){connects++;t.panel.clearLive('connecting');t.panel.acceptState(t.snapshot);}};
  assert.equal(await t.panel.returnFilePicker(t.workflow,t.selection),true);
  assert.equal(connects,1);assert.equal(t.renders(),0);assert.equal(t.workflow.connection,t.panel._hass.connection);
});

test('picker return refuses account, conversation, device changes and late selections',async()=>{
  for(const change of ['view','epoch','conversation','device','late']){
    const t=pickerPanel();t.panel.clearLive('expired');
    t.panel.session={connect(){const s=structuredClone(t.snapshot);if(change==='conversation')s.chat.current='other';else if(['view','epoch'].includes(change))s[change]='other';else if(change==='device')t.panel._panel.config.device_id='f'.repeat(32);t.panel.clearLive('connecting');t.panel.acceptState(s);}};
    if(change==='late')t.panel.pickerContext=null;
    assert.equal(await t.panel.returnFilePicker(t.workflow,t.selection),false,change);
  }
});

test('HA connection replacement preserves the picker; explicit Disconnect cancels it',()=>{
  const t=pickerPanel();t.panel.session={clear(){t.panel.clearLive('offline');}};
  t.panel.hass={connection:{addEventListener(){},removeEventListener(){}}};
  assert.ok(t.panel.pickerContext);assert.equal(t.renders(),0);
  t.panel.releaseConnection();assert.equal(t.panel.pickerContext,null);
});

test('picker cancellation redraws without submitting or reconnecting an already live session',()=>{
  const t=pickerPanel();t.panel.checkChatSupport=()=>{};
  t.panel.finishFilePicker(t.workflow,t.selection,'',false);
  assert.equal(t.panel.pickerContext,null);assert.equal(t.renders(),1);
});
