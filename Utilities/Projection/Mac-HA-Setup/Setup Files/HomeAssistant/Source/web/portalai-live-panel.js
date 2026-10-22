import { randomId, sha256Hex } from './browser-crypto.js';
import { PortalAINativePanel } from './portalai-native-panel.js';
import { LiveSession } from './live-state.js';
import { patchMarkup } from './patch-dom.js';
import { RichChat } from './rich-chat.js';
import { isIPhone } from './iphone-attachments.js';
import { VisibilityGrace } from './visibility-grace.js';
import './native-workflows.js';
const esc = v => String(v ?? '').replace(/[&<>"']/g,c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = v => v === null ? 'Unavailable' : v.toLocaleString();

export class PortalAILivePanel extends PortalAINativePanel {
  constructor() {
    super(); this.preview=false; this.connectionStatus='offline'; this.conversation=null; this.chatToolsOpen=false;this.iphone=isIPhone();
    this.viewer=randomId();this.actionTicket=0;this.chatSupported=false;this.chatPending=false;this.chatUncertain=false;this.chatNotice='';
    this.rich=new RichChat(this.shadowRoot);
    this.session=new LiveSession({onState:s => this.acceptState(s),onClear:r => this.clearLive(r)});
    this.connectionLost=() => this.session.clear('offline');
    this.backgroundGrace=new VisibilityGrace(()=>this.releaseConnection(true));
    this.visibilityChanged=()=>{
      if(!this.backgroundGrace.change(document.hidden))return;
      if(document.hidden)this.session.demand?.background();else this.session.demand?.foreground();
      this.configureWorkflows();
    };
  }
  set hass(value) {
    if (this._connection && this._connection !== value?.connection) this.releaseConnection(Boolean(this.pickerContext));
    this._hass=value;
  }
  connectedCallback() {
    document.addEventListener('visibilitychange',this.visibilityChanged);
    this.preview=false; this.initialized=true; this.applyTheme(); this.render();
  }
  disconnectedCallback() {
    document.removeEventListener('visibilitychange',this.visibilityChanged);
    this.releaseConnection(); this.session.clear(); this.shadowRoot.replaceChildren();
  }
  releaseConnection(preservePicker=false) {
    if(!preservePicker&&this.pickerContext){this.pickerContext.resolve?.(false);this.pickerContext=null;}
    this.backgroundGrace?.reset();
    this._connection?.removeEventListener('disconnected',this.connectionLost);
    this._connection=null; this.session.clear();
  }
  clearLive(reason) {
    if(reason!=='connecting')this.backgroundGrace?.reset();
    this.rich.clear();
    if(reason!=='connecting'){this._connection?.removeEventListener('disconnected',this.connectionLost);this._connection=null;}
    this.chatToolsOpen=false;
    this.actionTicket++;this.chatSupported=false;this.chatAttachmentsSupported=false;this.chatPending=false;this.chatUncertain=false;this.chatNotice='';this.attachmentSubmitted=false;
    this.model.disconnect(); this.connectionStatus=reason;
    this.search=''; this.dialog=null; this.conversation=null; this.historyOpen=false; this.scrolls.clear();
    if(this.pickerContext){
      this.pickerContext.workflow.suspendPicker();
      // Do not detach the native input while Apple's picker owns it.
      for(const node of this.shadowRoot.querySelectorAll('.chat-layout,.page-heading'))node.replaceChildren();
      this.shadowRoot.querySelector('.status-chip').textContent='Attachment selection · connection paused';
      if(reason!=='connecting')this.pickerContext.resolve?.(false);
      return;
    }
    if (this.isConnected) this.render(); else this.shadowRoot.replaceChildren();
  }
  connectLive() {
    if(document.hidden)return;
    const connection=this._hass?.connection, device=this._panel?.config?.device_id;
    if (!connection || !/^[0-9a-f]{32}$/.test(device || '')) { this.session.clear('configuration'); return; }
    this.releaseConnection(); this._connection=connection;
    connection.addEventListener('disconnected',this.connectionLost);
    this.session.connect(connection,device);
  }
  acceptState(snapshot) {
    const previous=this.model.snapshot;
    this.model.snapshot=snapshot; this.model.status='ready'; this.connectionStatus='ready';
    if(this.pickerContext){
      const p=this.pickerContext;
      if(!this.pickerMatches(snapshot)){p.invalid=true;this.clearLive('unavailable');}
      p.resolve?.(!p.invalid);return;
    }
    if (!previous) { this.conversation=snapshot.chat.current;if(this.pickerReturnNotice){this.chatNotice=this.pickerReturnNotice;this.pickerReturnNotice='';} this.render(); this.checkChatSupport(); return; }
    if (previous.chat.current !== snapshot.chat.current) {
      this.attachmentSubmitted=false;
      this.actionTicket++;this.chatPending=false;this.chatUncertain=false;this.chatNotice='';
      this.model.clearPrivate(); this.search=''; this.dialog=null; this.scrolls.clear();
      this.conversation=snapshot.chat.current; this.chatToolsOpen=false; this.render(); return;
    }
    // Preserve the composer node, caret, IME, open dialogs and manual scroll.
    if (this.page === 'chat') {
      this.patch('.history-list',this.historyItems());
      const transcript=this.shadowRoot.querySelector('.transcript');
      const bottom=transcript && transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight < 40;
      if (JSON.stringify(previous.chat.messages) !== JSON.stringify(snapshot.chat.messages) || previous.chat.window.messagesComplete !== snapshot.chat.window.messagesComplete) {
        this.patch('.transcript',this.messagesMarkup());
        if (bottom && transcript) transcript.scrollTop=transcript.scrollHeight;
      }
      this.patch('.context-line',this.contextMarkup());
      const title=this.shadowRoot.querySelector('.page-heading p'); if (title) title.textContent=this.chatTitle();
      const footer=this.shadowRoot.querySelector('.history footer'); if (footer) footer.textContent=this.historyNotice();
    } else if (this.page==='activity') {
      const field={accounts:'account',activity:'runtime',runtime:'models',installed:'packages'}[this.page];
      if (JSON.stringify(previous[field])!==JSON.stringify(snapshot[field])) {
        const workspace=this.shadowRoot.querySelector('.workspace');
        const scroll=workspace.scrollTop; patchMarkup(workspace,this.pageMarkup()); workspace.scrollTop=scroll;
      }
    }
    for (const input of this.shadowRoot.querySelectorAll('[data-setting]')) {
      const key=input.dataset.setting, value=key.startsWith('media.') ? snapshot.settings.media[key.slice(6)] : snapshot.settings[key];
      if (![...input.options].some(o => o.value === String(value))) input.add(new Option(String(value),String(value)));
      input.value=String(value);
    }
    this.configureRich();
    this.chatButtons();
  }
  patch(selector,markup) { const node=this.shadowRoot.querySelector(selector); if (node) patchMarkup(node,markup); }
  render() {
    super.render();
    const liveStyle=document.createElement('style');
    liveStyle.textContent=`:host{height:100dvh}.preview-banner button{display:block;flex-shrink:0}.preview-banner{min-height:38px}.preview-banner>span{min-width:0}
      .chat-page .chat-layout{min-height:420px;flex-shrink:0;grid-template-columns:minmax(0,1fr)}
      .chat-tools-dialog{color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:16px;padding:0;width:min(920px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:hidden;box-shadow:0 16px 60px #0005}
      .chat-tools-dialog[open]{display:flex;flex-direction:column}
      .chat-tools-dialog::backdrop{background:#0007}
      .chat-tools-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid var(--gold-mid);flex-shrink:0}
      .chat-tools-heading h2{font-size:20px;margin:0}.chat-tools-heading button{flex-shrink:0;min-height:44px}
      .chat-tools-body{overflow:auto;overscroll-behavior:contain;min-height:0;padding:0 18px 18px;scrollbar-width:thin}
      @media(max-width:640px){.chat-page .chat-layout{min-height:360px}.chat-tools-dialog{width:calc(100vw - 16px);max-height:calc(100dvh - 16px);border-radius:12px}.chat-tools-heading{padding:10px 12px}.chat-tools-heading h2{font-size:17px}.chat-tools-body{padding:0 10px 12px}.chat-toolbar>span:not(.spacer){display:none}}
    `;
    this.shadowRoot.append(liveStyle);
    const status={offline:'Not connected',connecting:'Connecting…',ready:'Live',unavailable:'Waiting for PortalAI account',expired:'Connection expired',invalid:'State rejected',locked:'PortalAI locked',configuration:'Panel setup needed'}[this.connectionStatus] || 'Not connected';
    this.shadowRoot.querySelector('.status-chip').textContent=status;
    const banner=this.shadowRoot.querySelector('.preview-banner');
    banner.innerHTML=`<strong>${this.ready ? 'LIVE' : 'NATIVE UI'}</strong><span>${esc(status)} · shared Aoostar session</span><button data-action="${this._connection ? 'disconnect-live' : 'connect-live'}">${this._connection ? 'Disconnect' : 'Connect'}</button>`;
    this.shadowRoot.querySelector('.footer').innerHTML='<span>Home Assistant controls access · browser memory only</span><span>Native UI 0.5.12 · rich chat</span>';
    this.configureWorkflows();
    this.configureRich();
    const tools=this.shadowRoot.querySelector('.chat-tools-dialog');
    if(tools){
      tools.addEventListener('close',()=>{if(this.shadowRoot.querySelector('.chat-tools-dialog')!==tools)return;this.chatToolsOpen=false;for(const trigger of this.shadowRoot.querySelectorAll('[aria-controls=chat-tools]'))trigger.setAttribute('aria-expanded','false');this.configureWorkflows();});
      if(this.chatToolsOpen)tools.showModal();
    }
    this.chatButtons();
    for (const node of this.shadowRoot.querySelectorAll('[data-setting]')) node.disabled=true;
    const reset=this.shadowRoot.querySelector('[data-action="reset-settings"]'); if (reset) reset.disabled=true;
    const settingStatus=this.shadowRoot.querySelector('[data-setting-status]'); if (settingStatus) settingStatus.textContent='Saved account settings · read only';
  }
  configureRich(){
    this.rich.configure(this._connection,this._panel?.config?.device_id,this.model.snapshot,this.session.demand,this.page==='chat'&&!this.chatToolsOpen);
  }
  configureWorkflows(){
    if(this.pickerContext)return;
    this.configureRich();
    const active=Boolean(this._connection&&this.session.demand?.connected&&this.backgroundGrace.allowed()&&(this.page!=='chat'||this.chatToolsOpen));
    const workflows=this.shadowRoot.querySelector('portalai-native-workflows');
    if(workflows){
      workflows.onPickerOpen=(w,s)=>this.beginFilePicker(w,s);
      workflows.onPickerReturn=(w,s)=>this.returnFilePicker(w,s);
      workflows.onPickerFinish=(w,s,status,uncertain)=>this.finishFilePicker(w,s,status,uncertain);
      workflows.pickerStillCurrent=()=>Boolean(this.pickerContext&&!this.pickerContext.invalid&&this.pickerMatches(this.model.snapshot));
      workflows.onAttachmentSubmitted=()=>{this.attachmentSubmitted=true;this.checkChatSupport();};
      workflows.backgroundDeadline=this.backgroundGrace.deadline;workflows.configure(this._connection,this._panel?.config?.device_id,this.page,this.viewer,active);
    }
  }
  beginFilePicker(workflow,selection){
    const s=this.model.snapshot;
    this.pickerContext={workflow,selection,device:this._panel.config.device_id,
      view:s?.view,epoch:s?.epoch,conversation:s?.chat.current,invalid:!this.ready};
    this.rich.clear();
  }
  pickerMatches(s){
    const p=this.pickerContext;
    return Boolean(p&&s?.account.state==='ready'&&s.view===p.view&&s.epoch===p.epoch&&s.chat.current===p.conversation&&this._panel?.config?.device_id===p.device);
  }
  async returnFilePicker(workflow,selection){
    const p=this.pickerContext;if(!p||p.workflow!==workflow||p.selection!==selection||p.invalid)return false;
    // iOS may deliver change before visibilitychange. Wait for the app to be
    // visible, then acquire a fresh authenticated subscription, never a Send.
    const until=Date.now()+15000;
    while(document.hidden&&Date.now()<until&&this.pickerContext===p)await new Promise(resolve=>setTimeout(resolve,100));
    if(document.hidden||this.pickerContext!==p)return false;
    this.backgroundGrace.reset();
    this._connection?.removeEventListener('disconnected',this.connectionLost);
    this._connection=this._hass?.connection;if(!this._connection)return false;
    this._connection.addEventListener('disconnected',this.connectionLost);
    const ready=new Promise(resolve=>{p.resolve=resolve;});
    const timeout=setTimeout(()=>p.resolve?.(false),30000);
    this.session.connect(this._connection,p.device);
    const ok=await ready;clearTimeout(timeout);p.resolve=null;
    if(!ok||this.pickerContext!==p||p.invalid||!this.pickerMatches(this.model.snapshot))return false;
    this.chatToolsOpen=true;workflow.connection=this._connection;
    return true;
  }
  finishFilePicker(workflow,selection,status='',uncertain=false){
    const p=this.pickerContext;if(!p||p.workflow!==workflow||p.selection!==selection)return;
    p.resolve?.(false);this.pickerContext=null;
    // Cancellation does not upload. A paused session reconnects normally when
    // the user returns, while an already live session simply redraws.
    if(!this._connection&&!document.hidden){this.pickerReturnNotice=status;this.connectLive();return;}
    this.chatToolsOpen=this.ready;this.render();
    const next=this.shadowRoot.querySelector('portalai-native-workflows');
    if(next&&status){next.status(status);next.uncertain=uncertain;next.buttons();}
    if(this.ready)this.checkChatSupport();
  }
  pageMarkup(){
    if(this.page==='chat')return `<section class="page chat-page">${this.chat()}<dialog class="chat-tools-dialog" id="chat-tools" aria-labelledby="chat-tools-title"><header class="chat-tools-heading"><h2 id="chat-tools-title">Conversation tools</h2><button data-action="close-chat-tools" autofocus>Back to chat</button></header><div class="chat-tools-body"><portalai-native-workflows></portalai-native-workflows></div></dialog></section>`;
    if(this.page==='activity')return `<section class="page">${this.runtime()}<portalai-native-workflows></portalai-native-workflows></section>`;
    const title={welcome:'PortalAI',accounts:'Accounts',controls:'Controls',runtime:'Models',installed:'Packages',settings:'Settings',persistence:'Persistence',maintenance:'Maintenance',help:'Help'}[this.page];
    return `<section class="page">${this.heading(title,'Native controls for the active Aoostar session.')}${this.page==='controls'?'<div class="actions"><button data-action="open-host">Open PortalAI</button><button data-action="restart-host">Full restart</button><button class="danger" data-action="force-host">Force shutdown</button></div>':''}<portalai-native-workflows></portalai-native-workflows></section>`;
  }
  availability() { return `<div class="availability">${this.ready ? 'Live state from the signed-in PortalAI account.' : 'Connect after PortalAI is signed in and the native exporter is running.'} ${this.fallbackLink()}</div>`; }
  welcome() { return `${this.heading('PortalAI','Your familiar workspace, rendered directly in Home Assistant.')}${this.availability()}${this.empty(this.ready ? 'Live state connected' : 'Ready to connect',this.ready ? 'Open Chat, Runtime, Models or Settings to inspect the current account.' : 'The Aoostar sends account-scoped state through its paired connection. Home Assistant remains in control.')}`; }
  accounts() { return `${this.heading('Accounts','Home Assistant and PortalAI use separate sign-ins.')}${this.availability()}<section class="ornate"><h2>Current account</h2><dl class="key-values"><dt>Display name</dt><dd>${this.ready ? esc(this.model.snapshot.account.displayName) : 'Unavailable'}</dd><dt>Access</dt><dd>Read only</dd></dl><p>Use PortalAI on the Aoostar to sign in, switch accounts or lock the profile.</p></section>`; }
  chatTitle() { const c=this.model.snapshot.chat; return c.conversations.find(r => r.id === c.current)?.title || 'No conversation loaded'; }
  historyNotice() { return this.model.snapshot.chat.window.conversationsComplete ? 'Current account history' : 'Partial history · open other conversations on the desktop'; }
  historyItems() {
    if (!this.ready) return '';
    const chat=this.model.snapshot.chat;
    const rows=chat.conversations.filter(r => r.title.toLocaleLowerCase().includes(this.search.toLocaleLowerCase()));
    return rows.map(r => `<div class="history-item" aria-current="${r.id === chat.current}"><strong>${esc(r.title)}</strong><small>${esc(r.updated)}${r.id === chat.current ? ' · Current' : ''}</small></div>`).join('') || '<p class="small muted">No conversations in this view.</p>';
  }
  messagesMarkup() {
    const c=this.model.snapshot.chat;
    return `${c.window.messagesComplete ? '' : '<p class="note">Partial transcript · earlier messages are not included.</p>'}${c.messages.length ? c.messages.map(m => `<article class="message ${m.role}" data-message="${m.id}"><div class="speaker">${m.role === 'assistant' ? 'PortalAI' : 'You'}</div>${m.role === 'assistant' ? `<portalai-rich-message data-rich-kind="thinking" data-message="${m.id}"></portalai-rich-message>` : ''}<p>${esc(m.text)}</p>${m.truncated ? '<small>Message shortened in this view.</small>' : ''}<portalai-rich-message data-rich-kind="results" data-message="${m.id}"></portalai-rich-message></article>`).join('') : '<div class="chat-intro"><h2>No messages in this view.</h2><p>Open a conversation in PortalAI on the Aoostar.</p></div>'}<div data-rich-pending></div>`;
  }
  contextMarkup() {
    const c=this.model.snapshot.chat;
    return `<span>${c.busy ? 'Generating…' : 'Idle'}</span><span>Context ${number(c.contextUsed)} / ${number(c.contextLimit)}</span><span>Reply cap ${number(c.replyCap)}</span>`;
  }
  chat() {
    if (!this.ready) return `${this.heading('Chat','The current PortalAI conversation.')}${this.availability()}${this.empty('No connected conversation','Use Connect above to read the current signed-in account.')}`;
    const current=this.model.snapshot.chat.current;
    return `${this.heading('Chat',this.chatTitle(),'Live')}<div class="chat-layout"><div class="conversation"><div class="chat-toolbar"><button data-action="history" aria-haspopup="dialog" aria-controls="chat-tools" aria-expanded="false">☰ History</button><span>Live desktop conversation</span><span class="spacer"></span><button data-action="chat-tools" aria-controls="chat-tools" aria-haspopup="dialog" aria-expanded="${this.chatToolsOpen}">Conversation tools</button></div><div class="transcript" aria-label="PortalAI messages">${this.messagesMarkup()}</div><small data-rich-notice></small><div class="composer"><textarea aria-label="Message draft" maxlength="16384" ${current === null ? 'disabled' : ''} placeholder="Message PortalAI…" data-draft>${esc(this.model.drafts.get(current) || '')}</textarea><div class="actions"><button data-action="open-attachments" aria-controls="chat-tools" aria-haspopup="dialog" aria-expanded="false">Attach</button><button data-action="clear-draft" ${current === null ? 'disabled' : ''}>Clear draft</button><button data-action="stop-chat" disabled>Stop</button><button data-action="send-chat" class="primary send" disabled>Send ↑</button></div><div class="draft-note"><span data-chat-notice>Draft stays in browser memory.</span> <button data-action="review-chat" hidden>I checked the conversation</button></div></div><div class="context-line">${this.contextMarkup()}</div></div></div>`;
  }
  runtime() {
    const r=this.model.snapshot?.runtime;
    return `${this.heading('Runtime','Latest readings from PortalAI.')}${this.availability()}${r ? `<div class="metrics">${['cpu','gpu','memory'].map(k => `<section class="metric"><span>${esc(k.toUpperCase())}</span><div class="value">${r[k] === null ? 'Unavailable' : r[k].toFixed(1)+'%'}</div></section>`).join('')}</div><section class="ornate"><h2>${esc(r.model || 'No model reported')}</h2><p>${esc(r.state)}</p></section>` : this.empty('Readings unavailable','Connect to the native exporter.')}`;
  }
  models() { return super.models().replace('Sample inventory.','Current account inventory.'); }
  packages() { return super.packages().replaceAll('Sample package','Current inventory'); }
  disabled(label,classes='') { return `<button class="${classes}" disabled title="Use the desktop view; native actions are not connected yet">${esc(label)}</button>`; }
  field(key,label,rows,hint='') {
    const s=this.model.snapshot.settings, value=key.startsWith('media.') ? s.media[key.slice(6)] : s[key];
    if (!rows.some(([id]) => String(id) === String(value))) rows=[...rows,[value,String(value)+' (saved)']];
    return super.field(key,label,rows,hint);
  }
  chatFields(compact=false) {
    let html=super.chatFields(compact);
    if (!compact) {
      const value=this.model.snapshot.settings.selection;
      const rows=new Map([['auto','Automatic'],...this.model.snapshot.models.map(r => [r.id,r.name])]);
      if (!rows.has(value)) rows.set(value,value+' (saved selection)');
      html=html.replace(/(<select data-setting="selection">)[\s\S]*?(<\/select>)/,(_,a,b) => a+[...rows].map(([id,label]) => `<option value="${esc(id)}" ${id === value ? 'selected' : ''}>${esc(label)}</option>`).join('')+b).replace('Preview choices only; no installed model is queried.','Saved selection; availability is reported separately.');
    }
    return html;
  }
  settingsPage() { return super.settingsPage().replace('Explore the desktop settings as native browser controls.','Saved settings for the current account.').replace('Local draft','Read only'); }
  dialogMarkup() { return super.dialogMarkup().replace('These are local preview drafts. Save is unavailable until the Aoostar adapter can validate and persist them.','These are saved account values. Editing is not connected yet.'); }
  helpPage() { return `${this.heading('Help','Live native interface · first stage')}<section class="ornate"><h2>Read the current PortalAI account</h2><p>Connect to see its current conversation, runtime, inventories and saved settings. Text is rendered locally, without desktop screenshots.</p><p>Sending, controls, history loading and other actions still use the desktop view. No native commands are enabled yet.</p><p>Locking PortalAI, changing accounts, disconnecting or expiring the connection clears the account view and local drafts. Reconnect after signing in again.</p></section>`; }
  async checkChatSupport(){
    const ticket=this.actionTicket;
    try{const r=await this._connection.sendMessagePromise({type:'portalai_native/chat_status',device_id:this._panel.config.device_id});if(ticket!==this.actionTicket)return;this.chatSupported=r.protocol===1&&r.supported===true;this.chatAttachmentsSupported=r.attachments_supported===true;}
    catch{if(ticket!==this.actionTicket)return;this.chatSupported=false;}
    this.chatButtons();
  }
  chatButtons(){
    const send=this.shadowRoot.querySelector('[data-action=send-chat]'),stop=this.shadowRoot.querySelector('[data-action=stop-chat]');
    if(!send)return;const active=this.ready&&this.model.snapshot.chat.current;
    send.disabled=!active||!this.chatSupported||this.chatPending||this.chatUncertain||this.model.snapshot.chat.busy||(this.attachmentSubmitted&&!this.chatAttachmentsSupported);
    stop.disabled=!active||!this.chatSupported||!this.model.snapshot.chat.busy;
    const attach=this.shadowRoot.querySelector('[data-action=open-attachments]');if(attach)attach.disabled=!active||this.chatPending||this.chatUncertain||this.model.snapshot.chat.busy;
    const note=this.shadowRoot.querySelector('[data-chat-notice]');if(note)note.textContent=this.chatNotice||(this.attachmentSubmitted&&!this.chatAttachmentsSupported?'Attachment uploaded. Sending it needs the Aoostar attachment-chat update.':!this.chatSupported?'Waiting for the Aoostar chat handler.':this.chatAttachmentsSupported?'Send includes pending attachments in this shared conversation.':'Same active conversation as the desktop.');
    this.shadowRoot.querySelector('[data-action=review-chat]').hidden=!this.chatUncertain;
  }
  async chatCommand(operation){
    const button=this.shadowRoot.querySelector(`[data-action=${operation==='send'?'send-chat':'stop-chat'}]`);if(!button||button.disabled)return;
    const text=this.shadowRoot.querySelector('[data-draft]').value;
    if(operation==='send'&&(!text.trim()||!text.isWellFormed()||[...text].length>8192||new TextEncoder().encode(text).length>32768)){this.chatNotice='Enter a message of up to 8192 characters.';this.chatButtons();return;}
    const s=this.model.snapshot,ticket=this.actionTicket,request_id=randomId();this.chatPending=true;this.chatNotice='Waiting for PortalAI…';this.chatButtons();
    try{const r=await this._connection.sendMessagePromise({type:'portalai_native/chat',device_id:this._panel.config.device_id,request_id,viewer:this.viewer,operation,binding:{view:s.view,epoch:s.epoch},conversation:s.chat.current,...(operation==='send'?{text,...(this.chatAttachmentsSupported?{include_pending_attachments:true}:{})}:{})});if(ticket!==this.actionTicket)return;
      if(r.accepted!==true||r.request_id!==request_id||r.operation!==operation)throw Error('Outcome unknown. Check the conversation before retrying.');
      if(operation==='send')this.attachmentSubmitted=false;
      if(operation==='send'&&this.model.drafts.get(s.chat.current)===text){this.model.drafts.delete(s.chat.current);const draft=this.shadowRoot.querySelector('[data-draft]');if(draft)draft.value='';}this.chatNotice=operation==='send'?'PortalAI accepted the message. Image processing or loading a vision model may take time; do not resend.':'Stop accepted.';
    }catch(e){if(ticket!==this.actionTicket)return;this.chatNotice=String(e.message||'Outcome unknown. Check the conversation.').slice(0,300);this.chatUncertain=/unknown|uncertain|do not replay|timed out|timeout|connection|disconnect/i.test(this.chatNotice);}
    finally{if(ticket===this.actionTicket){this.chatPending=false;this.chatButtons();}}
  }
  async lifecycle(action){
    if(!this._hass?.connection)return;
    if(action!=='open'&&!confirm(action==='restart'?'Close PortalAI normally, wait for profile sealing, and reopen?':'Force shutdown may require profile recovery. It does not reopen PortalAI. Continue?'))return;
    try{if(action==='open')await this._hass.connection.sendMessagePromise({type:'portalai_projection/request',device_id:this._panel.config.device_id,action:'start',payload:{viewer:this.viewer}});
      else await this._hass.callService('portalai_projection',action==='restart'?'full_restart':'force_shutdown',{device_id:this._panel.config.device_id,...(action==='force'?{confirm:'UNSAFE SHUTDOWN'}:{})});
      this.shadowRoot.querySelector('.status-chip').textContent='Request accepted.';
    }catch(e){this.shadowRoot.querySelector('.status-chip').textContent=String(e.message||'Request outcome unknown').slice(0,180);}
  }
  onClick(event) {
    const action=event.target.closest('button')?.dataset.action;
    if (action === 'connect-live') return this.connectLive();
    if (action === 'disconnect-live') return this.releaseConnection();
    if (action === 'send-chat') return this.chatCommand('send');
    if (action === 'stop-chat') return this.chatCommand('stop');
    if (action === 'review-chat'){this.chatUncertain=false;this.chatNotice='No message was retried.';this.chatButtons();return;}
    if (action === 'chat-tools'||action === 'open-attachments'||action === 'history'){
      if(event.target.closest('button').disabled)return;
      const tools=this.shadowRoot.querySelector('.chat-tools-dialog');if(!tools)return;
      tools.querySelector('h2').textContent=action==='history'?'History':'Conversation tools';this.chatToolsOpen=true;event.target.closest('button').setAttribute('aria-expanded','true');tools.showModal();this.configureWorkflows();const workflow=this.shadowRoot.querySelector('portalai-native-workflows');workflow?.setAttachmentMode(action==='open-attachments');workflow?.setHistoryMode(action==='history');return;
    }
    if (action === 'close-chat-tools'){
      this.chatToolsOpen=false;this.shadowRoot.querySelector('.chat-tools-dialog')?.close();this.configureWorkflows();return;
    }
    if (action === 'open-host') return this.lifecycle('open');
    if (action === 'restart-host') return this.lifecycle('restart');
    if (action === 'force-host') return this.lifecycle('force');
    super.onClick(event);
  }
  onChange(event) { if (event.target.dataset.setting) return; super.onChange(event); }
}
if (!customElements.get('portalai-live-panel')) customElements.define('portalai-live-panel',PortalAILivePanel);
