import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.HTMLElement=class {};
globalThis.customElements={get(){return true;},define(){}};
globalThis.document={hidden:false};
const {PortalAILivePanel}=await import('../web/portalai-live-panel.js');
const {RichChat}=await import('../web/rich-chat.js');

test('assistant reasoning precedes escaped answer; result/media slot follows it',()=>{
  const p=Object.create(PortalAILivePanel.prototype);
  p.model={snapshot:{chat:{window:{messagesComplete:true},messages:[{id:'a',role:'assistant',text:'<ANSWER>',truncated:false},{id:'u',role:'user',text:'USER',truncated:false}]}}};
  const html=p.messagesMarkup();
  assert.ok(html.indexOf('data-rich-kind="thinking"')<html.indexOf('&lt;ANSWER&gt;'));
  assert.ok(html.indexOf('&lt;ANSWER&gt;')<html.indexOf('data-rich-kind="results"'));
  assert.equal((html.match(/data-rich-kind="thinking"/g)||[]).length,1);
  assert.equal((html.match(/data-rich-kind="results"/g)||[]).length,2);
});

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.parentElement=null;this.textContent='';this.isConnected=true;}
  append(...nodes){for(const n of nodes){n.remove();n.parentElement=this;this.children.push(n);}}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  addEventListener(){}
  querySelector(tag){return this.children.find(n=>n.tag===tag);}
  querySelectorAll(){return [];}
  closest(){return null;}
}
test('rich nodes stay in their phase slots, retain identity and settle cached streaming at idle',()=>{
  document.createElement=tag=>new Element(tag);
  const slot=kind=>Object.assign(new Element('slot'),{dataset:{message:'m',richKind:kind},groups:new Map(),shadowRoot:new Element('shadow')});
  const before=slot('thinking'),after=slot('results');
  const r=new RichChat({querySelectorAll:()=>[before,after],querySelector:()=>null});
  r.scope='fixture';r.snapshot={chat:{busy:true}};
  r.blocks=new Map([['r',{id:'r',message:'m',kind:'thinking',title:'Thinking',status:'streaming'}],['t',{id:'t',message:'m',kind:'tool',title:'Tool',status:'returned'}]]);
  r.render();assert.deepEqual([...before.groups.keys()],['thinking']);assert.deepEqual([...after.groups.keys()],['tool']);
  const node=r.nodes.get('r');assert.match(node.querySelector('summary').textContent,/streaming/);
  r.snapshot.chat.busy=false;r.render();assert.equal(r.nodes.get('r'),node);assert.match(node.querySelector('summary').textContent,/saved/);
  assert.equal(r.nodes.size,2);
});
