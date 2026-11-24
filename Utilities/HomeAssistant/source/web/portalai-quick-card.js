import { randomId, sha256Hex } from './browser-crypto.js';
import { LiveSession } from './live-state.js';
import { patchMarkup } from './patch-dom.js';
import { RichChat } from './rich-chat.js';
const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const freshId=()=>randomId();
const QUICK_STYLE=`:host{display:block}*{box-sizing:border-box}ha-card{display:block;padding:18px;background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#222);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color,#ddd);font:14px/1.45 var(--paper-font-body1_-_font-family,system-ui)}header{display:flex;align-items:start;gap:12px}header h2{font-size:20px;line-height:1.2;margin:0 0 4px}header p{font-size:12px;color:var(--secondary-text-color,#666);margin:0}header .connection{margin-left:auto}button,textarea{font:inherit}button{min-height:38px;border:1px solid var(--divider-color,#aaa);border-radius:8px;background:transparent;color:inherit;padding:7px 12px;cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}button.primary{color:var(--text-primary-color,#fff);background:var(--primary-color,#167d98);border-color:transparent}button.danger{color:var(--error-color,#b3261e)}button:focus-visible,a:focus-visible,textarea:focus-visible{outline:2px solid var(--primary-color,#167d98);outline-offset:3px}a{color:var(--primary-color,#167d98)}.meta{margin:14px 0 8px;font-size:12px;color:var(--secondary-text-color,#666)}.messages{height:250px;overflow:auto;overscroll-behavior:contain;border:1px solid var(--divider-color,#ddd);border-radius:9px;padding:12px;scrollbar-width:thin}.messages article{margin:0 0 16px;white-space:pre-wrap;overflow-wrap:anywhere}.messages article:last-child{margin-bottom:0}.messages strong{font-size:11px;display:block;margin-bottom:4px}.messages p{margin:0}.messages .user{border-left:3px solid var(--primary-color,#167d98);padding-left:9px}.empty{color:var(--secondary-text-color,#666);padding:14px 0}.compose{margin-top:12px}textarea{display:block;width:100%;resize:vertical;min-height:76px;max-height:200px;padding:10px;border:1px solid var(--divider-color,#aaa);border-radius:8px;background:var(--card-background-color,#fff);color:inherit}.actions{display:flex;align-items:center;gap:8px;margin-top:9px;flex-wrap:wrap}.actions .send{margin-left:auto}.status{font-size:12px;min-height:18px;margin:9px 0 0;overflow-wrap:anywhere}.foot{font-size:11px;color:var(--secondary-text-color,#666);margin:8px 0}.controls{border-top:1px solid var(--divider-color,#ddd);margin-top:12px;padding-top:10px}.controls summary{cursor:pointer}.controls .actions{margin-top:10px}.confirm{padding:12px;background:var(--secondary-background-color,#f4f4f4);border-radius:8px;margin-top:12px}.confirm p{margin:0 0 8px}[hidden]{display:none!important}@media(max-width:420px){ha-card{padding:13px}.messages{height:220px}header h2{font-size:18px}.actions{gap:6px}button{padding:7px 9px}textarea{font-size:16px}}`;

export class PortalAIQuickCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:'open'});this.viewer=freshId();this.ticket=0;this.supported=false;this.snapshot=null;this.pending=false;this.uncertain=false;
    this.rich=new RichChat(this.shadowRoot);
    this.session=new LiveSession({onState:s=>this.accept(s),onClear:r=>this.clear(r)});
    this.lost=()=>this.session.clear('offline');
    this.visibilityChanged=()=>{if(document.hidden)this.release();};
    this.shadowRoot.addEventListener('click',event=>this.click(event));
  }
  setConfig(config){
    if(!/^[0-9a-f]{32}$/.test(config?.device_id||''))throw Error('PortalAI quick chat needs device_id');
    if(this.config?.device_id!==config.device_id)this.release();
    this.config={device_id:config.device_id,title:String(config.title||'PortalAI · Aoostar').slice(0,100)};
    if(this.isConnected)this.draw();
  }
  set hass(value){if(this.connection&&this.connection!==value?.connection)this.release();this._hass=value;}
  connectedCallback(){document.addEventListener('visibilitychange',this.visibilityChanged);this.draw();}
  disconnectedCallback(){document.removeEventListener('visibilitychange',this.visibilityChanged);this.release();this.shadowRoot.replaceChildren();}
  getCardSize(){return 8;}
  getGridOptions(){return {columns:12,min_columns:6,rows:8,min_rows:6};}
  $(selector){return this.shadowRoot.querySelector(selector);}
  draw(){
    if(!this.$('ha-card')){
      this.shadowRoot.innerHTML=`<style>${QUICK_STYLE}</style><ha-card><header><div><h2></h2><p>Shared PortalAI session on the Aoostar</p></div><button class="connection" data-action="connect">Connect</button></header><div class="meta">Not connected</div><div class="messages" role="log" aria-label="PortalAI conversation" aria-live="polite"><p class="empty">Connect to read the current signed-in conversation.</p></div><small data-rich-notice></small><div class="compose"><textarea aria-label="Message to PortalAI" maxlength="16384" placeholder="Ask a question or give the next instruction…" disabled></textarea><div class="actions"><a href="/portalai-native">Full interface ↗</a><button data-action="clear">Clear draft</button><button data-action="stop" disabled>Stop</button><button class="primary send" data-action="send" disabled>Send</button></div></div><p class="status" role="status"></p><button data-action="reviewed" hidden>I checked the conversation</button><p class="foot">Same active conversation as the desktop. Draft stays in this browser and clears on disconnect.</p><details class="controls"><summary>PortalAI controls</summary><div class="actions"><button data-action="diagnose">Check connection</button><button data-action="open">Open PortalAI</button><button data-action="restart">Full restart</button><button class="danger" data-action="force">Force shutdown</button></div></details><section class="confirm" hidden><p></p><div class="actions"><button data-action="cancel-control">Cancel</button><button data-action="confirm-control">Confirm</button></div></section></ha-card>`;
      this.$('textarea').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing){e.preventDefault();this.command('send');}});
    }
    this.$('h2').textContent=this.config?.title||'PortalAI · Aoostar';this.buttons();
  }
  release(){this.connection?.removeEventListener('disconnected',this.lost);this.connection=null;this.session.clear('offline');}
  clear(reason){
    this.rich.clear();
    if(reason!=='connecting'){this.connection?.removeEventListener('disconnected',this.lost);this.connection=null;}
    this.ticket++;this.snapshot=null;this.supported=false;this.pending=false;this.uncertain=false;this.control=null;
    if(!this.$('ha-card'))return;
    this.$('textarea').value='';this.$('.messages').replaceChildren();
    const p=document.createElement('p');p.className='empty';p.textContent=reason==='connecting'?'Connecting to PortalAI…':'Connect to read the current signed-in conversation.';this.$('.messages').append(p);
    this.$('.meta').textContent=({connecting:'Connecting…',unavailable:'PortalAI is unavailable',expired:'Connection expired',locked:'PortalAI account locked',invalid:'State rejected'})[reason]||'Not connected';
    this.$('.status').textContent='';this.$('.confirm').hidden=true;this.buttons();
  }
  async connect(){
    if(document.hidden||!this._hass?.connection||!this.config)return;
    this.release();this.connection=this._hass.connection;this.connection.addEventListener('disconnected',this.lost);
    this.session.connect(this.connection,this.config.device_id);
  }
  async checkSupport(){
    const ticket=this.ticket,connection=this.connection;
    try{const result=await connection.sendMessagePromise({type:'portalai_native/chat_status',device_id:this.config.device_id});
      if(ticket!==this.ticket||connection!==this.connection)return;
      this.supported=result.protocol===1&&result.supported===true;
      this.$('.status').textContent=this.supported?'': 'Reading live state. Sending needs the Aoostar quick-chat update.';
    }catch{if(ticket!==this.ticket)return;this.supported=false;this.$('.status').textContent='Reading live state. The quick-chat receiver is not installed yet.';}
    this.buttons();
  }
  accept(snapshot){
    const previous=this.snapshot;
    if(previous&&previous.chat.current!==snapshot.chat.current){this.ticket++;this.$('textarea').value='';this.pending=false;this.uncertain=false;this.$('.status').textContent='Active conversation changed.';}
    this.snapshot=snapshot;
    const title=snapshot.chat.conversations.find(r=>r.id===snapshot.chat.current)?.title||'No conversation selected';
    this.$('.meta').textContent=snapshot.account.displayName+' · '+title+' · '+(snapshot.chat.busy?'Generating…':'Live');
    if(!previous||previous.chat.current!==snapshot.chat.current||JSON.stringify(previous.chat.messages)!==JSON.stringify(snapshot.chat.messages)){
      const messages=this.$('.messages'),pin=messages.scrollHeight-messages.clientHeight-messages.scrollTop<35;
      const rows=snapshot.chat.messages.slice(-60);
      patchMarkup(messages,(rows.length?rows.map(m=>`<article class="${m.role}" data-message="${m.id}"><strong>${m.role==='user'?'You':'PortalAI'}</strong><p>${escape(m.text)}</p>${m.truncated?'<small>Message shortened in this view.</small>':''}<portalai-rich-message data-message="${m.id}"></portalai-rich-message></article>`).join(''):'<p class="empty">No messages in the active conversation yet.</p>')+'<div data-rich-pending></div>');
      if(pin||!previous)messages.scrollTop=messages.scrollHeight;
    }
    this.rich.configure(this.connection,this.config.device_id,snapshot,this.session.demand,true);
    if(!previous)this.checkSupport();
    this.buttons();
  }
  buttons(){
    if(!this.$('ha-card'))return;
    const ready=Boolean(this.snapshot?.chat.current),busy=this.snapshot?.chat.busy===true;
    this.$('textarea').disabled=!ready;
    this.$('[data-action=send]').disabled=!ready||!this.supported||busy||this.pending||this.uncertain;
    this.$('[data-action=stop]').disabled=!ready||!this.supported||!busy||this.pending;
    this.$('[data-action=reviewed]').hidden=!this.uncertain;
    this.$('.connection').textContent=this.connection?'Disconnect':'Connect';
  }
  async command(operation){
    if(this.$('[data-action='+operation+']').disabled||!this.snapshot)return;
    const text=this.$('textarea').value;
    if(operation==='send'&&(!text.trim()||!text.isWellFormed()||[...text].length>8192||new TextEncoder().encode(text).length>32768)){
      this.$('.status').textContent='Enter a message of up to 8192 characters.';return;
    }
    const snapshot=this.snapshot,ticket=this.ticket,request_id=freshId();
    const request={type:'portalai_native/chat',device_id:this.config.device_id,request_id,viewer:this.viewer,operation,binding:{view:snapshot.view,epoch:snapshot.epoch},conversation:snapshot.chat.current,...(operation==='send'?{text}:{})};
    this.pending=true;this.buttons();this.$('.status').textContent=operation==='send'?'Waiting for PortalAI to accept the message…':'Requesting stop…';
    try{
      const reply=await this.connection.sendMessagePromise(request);
      if(ticket!==this.ticket)return;
      if(reply.accepted!==true||reply.request_id!==request_id||reply.operation!==operation)throw Error('Outcome unknown. Check the conversation before sending again.');
      if(operation==='send'&&this.$('textarea').value===text)this.$('textarea').value='';
      this.$('.status').textContent=operation==='send'?'PortalAI accepted the message.':'Stop accepted.';
    }catch(error){
      if(ticket!==this.ticket)return;
      this.$('.status').textContent=String(error.message||'Outcome unknown. Check the conversation before sending again.').slice(0,300);
      this.uncertain=/unknown|uncertain|do not replay|timed out|timeout|connection|disconnected/i.test(this.$('.status').textContent);
    }finally{if(ticket===this.ticket){this.pending=false;this.buttons();}}
  }
  async diagnose(){
    const ticket=this.ticket,connection=this._hass?.connection;
    if(!connection)return;
    this.$('.status').textContent='Checking connection…';
    try{
      const [state,chat]=await Promise.all([
        connection.sendMessagePromise({type:'portalai_native/status',device_id:this.config.device_id}),
        connection.sendMessagePromise({type:'portalai_native/chat_status',device_id:this.config.device_id})
      ]);
      if(ticket!==this.ticket)return;
      this.$('.status').textContent=[state.granted?'HA pairing approved':'HA pairing unavailable',state.connected?'Aoostar state connection online':'Aoostar state connection offline',state.ready?'Account state ready':'Account state unavailable',chat.supported?'Quick-chat handler ready':'Quick-chat handler unavailable'].join(' · ');
    }catch(error){if(ticket===this.ticket)this.$('.status').textContent=String(error.message||'Unable to check connection').slice(0,300);}
  }
  async lifecycle(action){
    const ticket=this.ticket;this.$('.status').textContent='Waiting for the Aoostar…';
    try{
      if(action==='open')await this._hass.connection.sendMessagePromise({type:'portalai_projection/request',device_id:this.config.device_id,action:'start',payload:{viewer:this.viewer}});
      else await this._hass.callService('portalai_projection',action==='restart'?'full_restart':'force_shutdown',{device_id:this.config.device_id,...(action==='force'?{confirm:'UNSAFE SHUTDOWN'}:{})});
      if(ticket===this.ticket)this.$('.status').textContent='Request accepted. Check PortalAI before repeating it.';
    }catch(error){if(ticket===this.ticket)this.$('.status').textContent=String(error.message||'Outcome unknown. Check PortalAI before retrying.').slice(0,300);}
  }
  click(event){
    const action=event.target.closest('button')?.dataset.action;
    if(action==='connect')return this.connection?this.release():this.connect();
    if(action==='send'||action==='stop')return this.command(action);
    if(action==='clear'){this.$('textarea').value='';return;}
    if(action==='reviewed'){this.uncertain=false;this.$('.status').textContent='Review complete. No request has been retried.';this.buttons();return;}
    if(action==='diagnose')return this.diagnose();
    if(action==='open')return this.lifecycle(action);
    if(action==='restart'||action==='force'){
      this.control=action;this.$('.confirm').hidden=false;
      this.$('.confirm p').textContent=action==='restart'?'Close PortalAI normally, wait for profile sealing, and reopen it? This affects everyone using this Aoostar session.':'Force shutdown can interrupt work and profile sealing. Recovery may be required. It will not reopen PortalAI. Continue?';return;
    }
    if(action==='cancel-control'){this.control=null;this.$('.confirm').hidden=true;return;}
    if(action==='confirm-control'&&this.control){const chosen=this.control;this.control=null;this.$('.confirm').hidden=true;return this.lifecycle(chosen);}
  }
}
if(!customElements.get('portalai-quick-chat'))customElements.define('portalai-quick-chat',PortalAIQuickCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==='portalai-quick-chat'))window.customCards.push({type:'portalai-quick-chat',name:'PortalAI quick chat',description:'Compact chat with the active PortalAI account on the Aoostar.'});
