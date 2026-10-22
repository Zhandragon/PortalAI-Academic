import { randomId, sha256Hex } from './browser-crypto.js';
import { patchMarkup } from './patch-dom.js';
import { isIPhone, attachmentPickerMarkup, attachmentPickerCSS } from './iphone-attachments.js';
const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid=()=>randomId();
// Keep argument lists small even for the negotiated 1 MiB chunk.
const fileBase64=bytes=>{let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(binary);};
const workflowCSS=`:host{display:block;color:var(--text,#222);font:14px/1.5 'Segoe UI',sans-serif}*{box-sizing:border-box}.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.status{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted,#666)}.nodes{display:flex;flex-wrap:wrap;gap:12px;padding:20px;background:var(--panel,#fff);border:1px solid var(--gold-mid,#a87d32);border-radius:14px}.field{flex:1 1 270px;display:flex;flex-direction:column;gap:6px}.wide,h2,.note,.table{flex:1 1 100%;width:100%}h2{font:600 21px Georgia,serif;margin:12px 0 0}.note{white-space:pre-wrap;overflow-wrap:anywhere}.table{overflow:auto}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid var(--panel3,#ddd);white-space:pre-wrap;overflow-wrap:anywhere}button,input,select,textarea{font:inherit;color:inherit;border:1px solid var(--border-soft,#aaa);border-radius:8px;background:var(--card,#fff);min-height:42px;padding:9px 12px}button{cursor:pointer;background:var(--button,#e6dccb)}button:disabled,input:disabled,select:disabled,textarea:disabled{opacity:.5;cursor:not-allowed}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--accent,#3e91a2);outline-offset:3px}textarea{resize:vertical;min-height:110px}input[type=checkbox]{min-height:auto;width:22px;height:22px}.check{flex-direction:row;align-items:center}.nodes[data-page=controls]>button{flex:1 1 260px;min-height:84px;font-weight:600}.nodes[data-page=controls]>button[data-work-action=controls_stop],button[data-work-action=controls_exit]{color:var(--bad,#a9514c)}[hidden]{display:none!important}[data-drop-field]{border:2px dashed var(--border-soft,#aaa);border-radius:12px;padding:14px}[data-drop-field].drag-over{border-color:var(--accent,#3e91a2);background:var(--panel3,#eee)}.empty{padding:20px;border:1px dashed var(--border-soft,#aaa);border-radius:12px}@media(max-width:600px){.nodes{padding:13px}.field{flex-basis:100%}input,select,textarea{font-size:16px}}`;

export class NativeWorkflows extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.viewer=uid();this.ticket=0;this.dirty=new Map();this.pending=false;this.uncertain=false;this.model=null;this.page='controls';this.active=false;this.pollTicket=0;this.resumeReady=false;this.savedDrafts=null;
    this.iphone=isIPhone();this.pickerSelection=null;this.attachmentRequested=false;this.attachmentLoad=null;this.attachmentSearched=false;this.attachmentScope=null;
    this.shadowRoot.innerHTML=`<style>${workflowCSS}${attachmentPickerCSS}</style><div class="bar"><button data-command="refresh">Refresh controls</button><button data-command="reviewed" hidden>I checked the result</button><span class="status" role="status">Connect above to use native controls.</span></div><div class="nodes" hidden></div>${attachmentPickerMarkup}`;
    this.shadowRoot.addEventListener('click',e=>this.click(e));this.shadowRoot.addEventListener('input',e=>this.input(e));this.shadowRoot.addEventListener('change',e=>this.change(e));
    for(const type of ['dragenter','dragover','dragleave','drop'])this.shadowRoot.addEventListener(type,e=>this.fileDrag(e));
    this.shadowRoot.addEventListener('cancel',e=>{if(e.target.dataset.iphoneSource){e.target.value='';this.pickerSelection=null;this.finishPicker();}},true);
  }
  $(s){return this.shadowRoot.querySelector(s);}
  configure(connection,device,page,viewer,active=true){
    if(viewer)this.viewer=viewer;
    if(this.connection===connection&&this.device===device&&this.page===page){this.setActive(active);return;}
    this.reset();this.connection=connection;this.device=device;this.page=page;this.setActive(active);
  }
  setActive(active){
    active=Boolean(active&&this.connection);if(this.active===active)return;
    this.active=active;this.pollTicket++;this.fetching=null;clearTimeout(this.timer);this.timer=null;
    this.resumeReady=false;
    if(!active){
      this.clearPicker();this.attachmentLoad=null;this.attachmentRequested=false;
      this.clearSecrets();
      if(this.model)this.savedDrafts={view:this.model.view,epoch:this.model.epoch,form:this.model.form,
        dirty:new Map([...this.dirty].filter(([key])=>!['secret','file'].includes(this.model.nodes.find(n=>n.id===key)?.kind)))};
    }
    this.buttons();if(active)this.refresh();
  }
  disconnectedCallback(){this.reset();this.connection=null;}
  reset(){this.historyRequested=false;this.clearPicker();this.attachmentLoad=null;this.attachmentRequested=false;this.attachmentSearched=false;this.attachmentScope=null;this.removeAttribute('attachment-only');this.$('.iphone-attachments').hidden=true;this.active=false;this.resumeReady=false;this.savedDrafts=null;this.pollTicket++;this.ticket++;this.fetching=null;this.pendingToken=null;clearTimeout(this.timer);clearTimeout(this.expiry);this.timer=null;this.model=null;this.dirty.clear();this.pending=false;this.uncertain=false;this.$('.nodes').replaceChildren();this.$('.nodes').hidden=true;this.buttons();this.$('.status').textContent='Connect above to use native controls.';}
  clearPicker(){this.pickerSelection=null;this.fileSelection=null;for(const el of this.shadowRoot.querySelectorAll('input[type=file]'))el.value='';}
  beginPicker(selection){
    if(!this.onPickerOpen)return;
    this.pollTicket++;selection.pollTicket=this.pollTicket;this.pickerOpen=selection;
    this.fetching=null;clearTimeout(this.timer);clearTimeout(this.expiry);
    this.onPickerOpen(this,selection);
  }
  suspendPicker(){
    // Keep the actual iOS input mounted until change/cancel, but retain no live
    // account data or command authority while the phone's connection is paused.
    this.active=false;this.resumeReady=false;this.fetching=null;this.attachmentLoad=null;
    clearTimeout(this.timer);clearTimeout(this.expiry);this.model=null;this.dirty.clear();
    this.savedDrafts=null;this.$('.nodes').replaceChildren();this.$('.nodes').hidden=true;
    this.status('Return from the picker to reconnect and check the conversation.');
      this.$('[data-attachment-status]').textContent='Choose a file or cancel. The account and conversation will be checked again on return.';
  }
  finishPicker(selection=this.pickerOpen){
    this.pickerOpen=null;
    if(selection)this.onPickerFinish?.(this,selection,this.$('.status').textContent,this.uncertain);
  }
  setAttachmentMode(open){
    this.attachmentRequested=Boolean(open&&this.page==='chat');this.attachmentSearched=false;
    const enabled=this.attachmentRequested&&this.iphone;this.toggleAttribute('attachment-only',enabled);this.$('.iphone-attachments').hidden=!enabled;
    if(!open){this.clearPicker();this.attachmentLoad=null;}
    this.buttons();if(this.attachmentRequested)this.loadAttachmentControls();
  }
  setHistoryMode(open){
    this.historyRequested=Boolean(open);if(open)this.loadHistory();
  }
  async loadHistory(){
    if(!this.historyRequested||!this.resumeReady||this.pending||this.fetching||this.uncertain)return;
    if(this.model?.nodes.some(n=>n.id==='history_query')){this.historyRequested=false;return;}
    const action=this.model?.nodes.find(n=>(n.action||n.id)==='chat_history'&&n.enabled);
    this.historyRequested=false;
    if(!action){this.status('Open Browse and search all chats in Conversation tools. Install the matching Aoostar history update if it is missing.');return;}
    await this.invoke('chat_history');
  }
  async loadAttachmentControls(){
    if(!this.attachmentRequested||this.attachmentSearched||this.attachmentLoad||this.fetching||!this.active||!this.resumeReady||this.pending||this.uncertain||this.model?.account?.state!=='ready')return;
    this.attachmentSearched=true;
    if(this.attachmentReady()){this.buttons();return;}
    const token=uid(),ticket=this.ticket,pollTicket=this.pollTicket,binding=this.binding();this.attachmentLoad=token;
    const current=()=>this.attachmentLoad===token&&this.attachmentRequested&&this.active&&this.resumeReady&&ticket===this.ticket&&pollTicket===this.pollTicket&&this.model?.view===binding.view&&this.model?.epoch===binding.epoch;
    this.buttons();
    try{
      const seen=new Set();
      // The host appends upload controls after its ordinary widgets. Navigate
      // only its advertised pagination action, with no draft/form values.
      for(let count=0;count<32&&current()&&!this.attachmentReady();count++){
        const form=this.model.form;
        if(seen.has(form))break;seen.add(form);
        const action=this.model.nodes.some(n=>n.id==='history_back'&&n.enabled)?'history_back':'page_next';
        if(!this.model.nodes.some(n=>n.kind==='button'&&(n.action||n.id)===action&&n.enabled))break;
        const reply=await this.request('invoke',{binding,form,action,values:{}});
        if(!current()||this.model.form!==form)return;
        if(reply.model?.view!==binding.view||reply.model?.epoch!==binding.epoch)throw Error('The account changed while loading attachment controls.');
        this.accept(reply.model);
        this.status(reply.model.message||'Attachment controls loaded.');
      }
    }catch(e){if(current())this.status(String(e.message||'Could not load attachment controls.').slice(0,300));}
    finally{if(this.attachmentLoad===token){this.attachmentLoad=null;this.buttons();if(this.active&&this.connection){clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),3000);}}}
  }
  attachmentNotice(){
    if(this.attachmentReady())return 'Ready. Choose Photos or videos, or Browse files.';
    if(this.pending)return 'Uploading or waiting for PortalAI. Please wait.';
    if(this.uncertain)return 'Check the previous result, then tap I checked the result before attaching another file.';
    if(!this.active)return 'Connect to PortalAI to choose an attachment.';
    if(this.attachmentLoad||(this.fetching&&!this.resumeReady))return 'Loading attachment controls…';
    if(!this.resumeReady||!this.model)return 'Attachment controls could not be refreshed. Check PortalAI for an open dialog, or tap Refresh controls.';
    if(this.model?.account?.state!=='ready')return 'Sign in to PortalAI before attaching a file.';
    if(this.model.nodes.some(n=>n.id==='chat_attachment'))return 'Attachments are currently unavailable. Wait for the current operation to finish.';
    return 'Attachment controls are unavailable. Return to conversation tools to check for an open dialog, or tap Refresh controls.';
  }
  attachmentReady(){return this.page==='chat'&&this.active&&this.resumeReady&&!this.pending&&!this.uncertain&&this.model?.account?.state==='ready'&&this.model.nodes.some(n=>n.id==='chat_attachment'&&n.kind==='file'&&n.enabled)&&this.model.nodes.some(n=>(n.action||n.id)==='chat_attach_uploaded'&&n.kind==='button'&&n.enabled);}
  async pickAttachment(input){
    const file=input.files?.[0],selection=this.pickerSelection;input.value='';this.pickerSelection=null;
    try{
      if(!file)return;
      if(!selection||selection.source!==input.dataset.iphoneSource)throw Error('Choose the file again.');
      if(this.pickerOpen===selection&&this.onPickerReturn){
        this.status('Reconnecting and checking the selected conversation…');
        if(!await this.onPickerReturn(this,selection))throw Error('The conversation changed or could not reconnect. The file was not uploaded.');
        // Fresh describe/pagination is read-only apart from changing this
        // viewer's form page. Never reuse a stale form or transfer grant.
        this.active=true;this.resumeReady=false;this.backgroundDeadline=0;
        const reply=await this.request('describe',{page:'chat'});
        if(reply.model?.view!==selection.binding.view||reply.model?.epoch!==selection.binding.epoch)throw Error('The account changed. The file was not uploaded.');
        this.accept(reply.model);this.attachmentRequested=true;this.attachmentSearched=false;
        await this.loadAttachmentControls();
        if(!this.pickerStillCurrent?.())throw Error('The conversation changed. The file was not uploaded.');
      }else if(selection.pollTicket!==this.pollTicket||!this.current(selection.ticket,selection.binding,selection.form))throw Error('The conversation changed or disconnected. Choose the file again after reconnecting.');
      if(!this.attachmentReady())throw Error('Attachment controls are unavailable. The file was not uploaded.');
      this.pickerOpen=null;
      clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),3000);
      await this.upload(this.model.nodes.find(n=>n.id==='chat_attachment'),file,true);
    }catch(error){this.status(String(error.message||'The file was not uploaded.').slice(0,300));}
    finally{this.finishPicker(selection);}
  }
  status(s){this.$('.status').textContent=s;}
  binding(){if(!this.model)throw Error('Reconnect to the native controls.');return {view:this.model.view,epoch:this.model.epoch};}
  async request(operation,extra={}){
    if(!this.active||!this.withinBackgroundGrace())throw Error('Controls are paused. Open the visible controls before using them.');
    const request_id=uid();const reply=await this.connection.sendMessagePromise({type:'portalai_native/ui',device_id:this.device,payload:{request_id,viewer:this.viewer,operation,...extra}});
    if(reply?.accepted!==true||reply.request_id!==request_id||reply.operation!==operation)throw Error('Outcome unknown. Do not replay automatically.');return reply;
  }
  async refresh(){
    if(!this.active||!this.connection||this.fetching||this.attachmentLoad||this.pickerOpen)return;
    if(this.pending){clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),1000);return;}
    const ticket=this.ticket,pollTicket=this.pollTicket,fetchToken=uid();let accepted=false;this.fetching=fetchToken;this.buttons();
    try{
      const reply=await this.request('describe',{page:this.page});if(ticket!==this.ticket||pollTicket!==this.pollTicket||!this.active)return;
      this.accept(reply.model);accepted=true;if(!this.pending&&!this.uncertain)this.status(reply.model.message||'Live controls · '+(reply.model.account.state==='ready'?reply.model.account.displayName:'PortalAI sign-in'));
    }catch(e){if(ticket===this.ticket&&pollTicket===this.pollTicket&&this.active)this.status(String(e.message||'Native controls unavailable').slice(0,300));}
    finally{if(this.fetching===fetchToken)this.fetching=null;if(ticket===this.ticket&&pollTicket===this.pollTicket&&this.active){this.buttons();if(accepted){this.loadAttachmentControls();this.loadHistory();}clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),3000);}}
  }
  accept(m){
    if(!m||m.protocol!==1||m.page!==this.page||!Array.isArray(m.nodes)||m.nodes.length>120)throw Error('Invalid native controls');
    // A closed dialog changes the host form. Discover its attachment page once,
    // but never restart a failed search on ordinary polls or during pagination.
    // Retain the scope through expiry so the same failed form is not replayed.
    const scope=JSON.stringify([m.view,m.epoch,m.form]);
    if(this.attachmentScope!==scope&&!this.attachmentLoad)this.attachmentSearched=false;
    this.attachmentScope=scope;
    const changed=this.model&&(this.model.view!==m.view||this.model.epoch!==m.epoch||this.model.form!==m.form);
    if(changed){this.clearPicker();this.dirty.clear();this.uncertain=false;this.pending=false;this.pendingToken=null;}
    if(this.savedDrafts){const s=this.savedDrafts;this.dirty.clear();if(s.view===m.view&&s.epoch===m.epoch&&s.form===m.form)this.dirty=new Map(s.dirty);this.savedDrafts=null;}
    this.resumeReady=true;this.model=m;clearTimeout(this.expiry);const ticket=this.ticket;
    if(!this.pickerOpen)this.expiry=setTimeout(()=>{if(ticket!==this.ticket)return;this.clearPicker();this.model=null;this.resumeReady=false;this.dirty.clear();this.$('.nodes').replaceChildren();this.$('.nodes').hidden=true;this.buttons();this.status('Native controls expired. Reconnect or refresh.');},10000);
    const markup=m.nodes.map(n=>this.node(n)).join('')+(m.truncated?'<p class="note">More items are available through the page controls.</p>':'');
    patchMarkup(this.$('.nodes'),markup);this.$('.nodes').hidden=false;this.$('.nodes').dataset.page=this.page;
    for(const node of this.$('.nodes').querySelectorAll('[data-field]')){
      const row=m.nodes.find(n=>n.id===node.dataset.field);const value=this.dirty.has(row.id)?this.dirty.get(row.id):row.value;
      if(node.type==='file')continue;
      if(node.type==='checkbox')node.checked=value===true;
      else if(node.value!==String(value??''))node.value=String(value??'');
    }
    this.buttons();
  }
  node(n){
    const id=safe(n.id),label=safe(n.label),disabled=n.enabled?'':' disabled';
    if(this.iphone&&this.page==='chat'){
      if(n.kind==='file'&&n.id==='chat_attachment')return `<div class="field"><span>${label}</span><button data-command="iphone-attach"${disabled}>Attach</button></div>`;
      if(n.kind==='button'&&(n.action||n.id)==='chat_attach_uploaded')return '';
      if(n.kind==='button'&&n.label==='Attach')return `<button data-command="iphone-attach"${disabled}>Attach</button>`;
    }
    if(this.page==='chat'&&n.kind==='button'&&(n.action||n.id)==='chat_attach_uploaded')return '';
    if(this.page==='chat'&&n.kind==='button'&&n.label==='Attach')return `<button data-command="desktop-attach"${disabled}>Choose attachment</button>`;
    if(n.kind==='heading')return `<h2>${label}</h2>`;
    if(n.kind==='note')return `<div class="note">${label}${n.value===undefined?'':'\n'+safe(n.value)}</div>`;
    if(n.kind==='button')return `<button data-work-action="${safe(n.action||n.id)}"${disabled}>${label}</button>`;
    if(n.kind==='download')return `<button data-download="${id}"${disabled}>${label}</button>`;
    if(n.kind==='table')return `<div class="table"><strong>${label}</strong><table><thead><tr>${(n.columns||[]).map(x=>`<th>${safe(x)}</th>`).join('')}</tr></thead><tbody>${(n.rows||[]).map(r=>`<tr>${r.map(x=>`<td>${safe(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    let field;
    if(n.kind==='select')field=`<select data-field="${id}"${disabled}>${(n.options||[]).map(o=>`<option value="${safe(o.value)}">${safe(o.label)}</option>`).join('')}</select>`;
    else if(n.kind==='textarea')field=`<textarea data-field="${id}" maxlength="16000"${disabled}></textarea>`;
    else{const type={secret:'password',number:'number',checkbox:'checkbox',file:'file',text:'text'}[n.kind];if(!type)throw Error('Unknown native control');field=`<input data-field="${id}" type="${type}" autocomplete="off" maxlength="16000"${n.accept?` accept="${safe(n.accept)}"`:''}${['min','max','step'].filter(k=>n[k]!==undefined).map(k=>` ${k}="${safe(n[k])}"`).join('')}${disabled}>`;}
    return `<label ${n.kind==='file'?`data-drop-field="${id}"`:''} class="field ${n.kind==='textarea'?'wide':''} ${n.kind==='checkbox'?'check':''}"><span>${label}</span>${field}${n.kind==='file'?'<small>Drop one file here, or choose a file · up to 20 MiB</small>':''}</label>`;
  }
  async fileDrag(e){
    const zone=e.target.closest?.('[data-drop-field]');
    if(!zone||!Array.from(e.dataTransfer?.types||[]).includes('Files'))return;
    e.preventDefault();e.stopPropagation();
    const node=this.model?.nodes.find(n=>n.id===zone.dataset.dropField&&n.kind==='file');
    const attach=node?.id==='chat_attachment'&&this.page==='chat';
    const ready=this.active&&this.resumeReady&&node?.enabled&&!this.pending&&!this.uncertain&&(!attach||this.attachmentReady());
    if(e.type==='dragleave'){if(!zone.contains?.(e.relatedTarget))zone.classList.remove('drag-over');return;}
    if(e.type!=='drop'){e.dataTransfer.dropEffect=ready?'copy':'none';zone.classList.toggle('drag-over',Boolean(ready));return;}
    zone.classList.remove('drag-over');
    if(!ready){this.status('Connect and wait for the attachment controls before dropping a file.');return;}
    const files=Array.from(e.dataTransfer.files||[]),items=Array.from(e.dataTransfer.items||[]);
    if(files.length!==1||items.some(i=>i.kind==='file'&&i.webkitGetAsEntry?.()?.isDirectory)){
      this.status('Drop one file at a time. Folders are not supported.');return;
    }
    await this.upload(node,files[0],attach);
  }
  values(){const result={};for(const n of this.model?.nodes||[]){if(!n.enabled||!['text','secret','textarea','number','select','checkbox','file'].includes(n.kind))continue;const value=this.dirty.has(n.id)?this.dirty.get(n.id):n.value;if(value!==undefined)result[n.id]=value;}return result;}
  input(e){const id=e.target.dataset.field;if(!id||e.target.type==='file')return;const value=e.target.type==='checkbox'?e.target.checked:e.target.type==='number'?(e.target.value===''?'':Number(e.target.value)):e.target.value;this.dirty.set(id,value);}
  change(e){if(e.target.dataset.iphoneSource)return this.pickAttachment(e.target);this.input(e);const node=this.model?.nodes.find(n=>n.id===e.target.dataset.field);if(!node)return;if(node.kind==='file'){const file=e.target.files?.[0],selection=this.fileSelection;e.target.value='';this.fileSelection=null;if(!file)return;if(!selection||selection.field!==node.id||selection.pollTicket!==this.pollTicket||!this.current(selection.ticket,selection.binding,selection.form)){this.status('The conversation changed or disconnected. Choose the file again.');return;}return this.upload(node,file,this.page==='chat'&&node.id==='chat_attachment');}if(node.on_change)this.invoke(node.on_change);}
  buttons(){
    for(const button of this.$('.nodes').querySelectorAll('button')){
      if(['iphone-attach','desktop-attach'].includes(button.dataset.command)){button.disabled=!this.active||!this.resumeReady||this.model?.account?.state!=='ready'||this.pending||this.uncertain||Boolean(this.attachmentLoad);continue;}
      const node=this.model?.nodes.find(n=>(n.action||n.id)===button.dataset.workAction||n.id===button.dataset.download);
      const stop=['controls_stop','chat_stop','controls_exit','account_close'].includes(button.dataset.workAction);
      button.disabled=!this.active||!this.resumeReady||!node?.enabled||this.uncertain||((this.pending||this.attachmentLoad)&&!stop);
    }
    for(const field of this.$('.nodes').querySelectorAll('[data-field]'))field.disabled=!this.active||!this.resumeReady||!this.model?.nodes.find(n=>n.id===field.dataset.field)?.enabled||this.pending||this.uncertain||Boolean(this.attachmentLoad);
    this.$('[data-command=reviewed]').hidden=!this.uncertain;
    for(const field of this.shadowRoot.querySelectorAll('[data-iphone-source]'))field.disabled=!this.attachmentReady();
    this.$('[data-attachment-status]').textContent=this.attachmentNotice();
  }
  clearSecrets(){for(const n of this.model?.nodes||[])if(n.kind==='secret'){this.dirty.delete(n.id);const el=this.$(`[data-field="${n.id}"]`);if(el)el.value='';}}
  async invoke(action){
    if(!this.active||!this.resumeReady||!this.model||this.uncertain)return;const ticket=this.ticket,binding=this.binding(),form=this.model.form;
    this.attachmentLoad=null;this.attachmentSearched=true;
    const pendingToken=uid();this.pendingToken=pendingToken;this.pending=true;this.buttons();this.status('Waiting for PortalAI…');
    try{const reply=await this.request('invoke',{binding,form,action,values:this.values()});if(!this.current(ticket,binding,form))return;this.dirty.clear();this.savedDrafts=null;this.clearSecrets();if(reply.model)this.accept(reply.model);this.status(reply.message||'PortalAI accepted the action.');await this.refresh();}
    catch(e){if(!this.current(ticket,binding,form))return;this.clearSecrets();this.uncertain=true;this.status(String(e.message||'Outcome unknown. Check PortalAI before trying again.').slice(0,300));}
    finally{if(ticket===this.ticket&&this.pendingToken===pendingToken){this.pending=false;this.pendingToken=null;this.buttons();}}
  }
  current(ticket,binding,form){return ticket===this.ticket&&this.model?.view===binding.view&&this.model?.epoch===binding.epoch&&this.model?.form===form;}
  click(e){
    if(e.target.type==='file'&&e.target.dataset.field){
      if(!this.active||!this.resumeReady||this.pending||this.uncertain||e.target.disabled){e.preventDefault();return;}
      this.fileSelection={ticket:this.ticket,pollTicket:this.pollTicket,binding:this.binding(),form:this.model.form,field:e.target.dataset.field};return;
    }
    if(e.target.dataset.iphoneSource){
      if(!this.attachmentReady()){e.preventDefault();return;}
      this.pickerSelection={ticket:this.ticket,pollTicket:this.pollTicket,binding:this.binding(),form:this.model.form,source:e.target.dataset.iphoneSource};this.beginPicker(this.pickerSelection);return;
    }
    const b=e.target.closest('button');if(!b||b.disabled)return;
    if(b.dataset.command==='desktop-attach')return this.attachmentReady()?this.$('[data-field="chat_attachment"]')?.click():this.setAttachmentMode(true);
    if(b.dataset.command==='iphone-attach')return this.setAttachmentMode(true);
    if(b.dataset.command==='attachment-back')return this.setAttachmentMode(false);
    if(b.dataset.command==='refresh'){this.attachmentSearched=false;return this.refresh();}
    if(b.dataset.command==='reviewed'){this.uncertain=false;this.buttons();this.status('No action was retried.');return;}
    if(b.dataset.workAction)return this.invoke(b.dataset.workAction);if(b.dataset.download)return this.download(this.model.nodes.find(n=>n.id===b.dataset.download));
  }
  withinBackgroundGrace(){return !this.backgroundDeadline||Date.now()<this.backgroundDeadline;}
  async uploadProtocol(){
    try{const s=await this.connection?.sendMessagePromise({type:'portalai_native/ui_status',device_id:this.device});return s?.connected===true&&s.supported===true&&s.upload_protocol===2?2:1;}catch{return 1;}
  }
  async upload(node,file,attach=false){
    if(!this.active||!this.resumeReady||!this.model||!node?.enabled||(attach&&!this.attachmentReady()))return;
    if(this.pending||this.uncertain||file.size>20*1024*1024){this.status('Choose a file of up to 20 MiB when no other action is pending.');return;}
    const ticket=this.ticket,pollTicket=this.pollTicket,binding=this.binding(),form=this.model.form,pendingToken=uid();this.pendingToken=pendingToken;this.pending=true;this.buttons();this.status('Preparing '+file.name+'…');
    const current=()=>this.active&&this.resumeReady&&this.withinBackgroundGrace()&&pollTicket===this.pollTicket&&this.pendingToken===pendingToken&&this.current(ticket,binding,form);
    try{const bytes=new Uint8Array(await file.arrayBuffer());const digest=await sha256Hex(bytes);if(!current())return;
      const protocol=await this.uploadProtocol();if(!current())return;const chunkSize=protocol===2?1048576:24576;
      this.status(`Uploading ${file.name}${protocol===2?'':' (compatibility mode; update Aoostar for faster uploads)'}. Keep Home Assistant open until attached.`);
      const begin=await this.request('file_begin',{binding,form,field:node.id,name:file.name,size:file.size,mime:file.type||'application/octet-stream'});if(!/^[A-Za-z0-9_-]{1,80}$/.test(begin.transfer))throw Error('Invalid upload receipt');
      for(let offset=0;offset<bytes.length;offset+=chunkSize){if(!current())return;const part=bytes.subarray(offset,offset+chunkSize);const data=fileBase64(part);const ack=await this.request(protocol===2?'file_chunk_v2':'file_chunk',{...(protocol===2?{protocol:2}:{}),binding,transfer:begin.transfer,offset,data});if(!current())return;if(ack.offset!==offset+part.length)throw Error('Upload acknowledgement mismatch');this.status(`Uploading ${file.name}: ${Math.round(100*ack.offset/bytes.length)}%${protocol===2?'':' (compatibility mode)'}. Keep Home Assistant open.`);}
      if(!current())return;const end=await this.request('file_commit',{binding,transfer:begin.transfer,sha256:digest});if(!current())return;if(!/^[A-Za-z0-9_-]{1,80}$/.test(end.file))throw Error('Invalid file receipt');
      if(attach){
        if(!this.model.nodes.some(n=>(n.action||n.id)==='chat_attach_uploaded'&&n.enabled))throw Error('Attachment controls changed. Check the conversation before retrying.');
        // Submit only this verified token, never unrelated form drafts or a
        // desktop "Attach" command that would open a dialog on the Aoostar.
        this.status('Upload verified. Saving '+file.name+' to the conversation…');
        const reply=await this.request('invoke',{binding,form,action:'chat_attach_uploaded',values:{[node.id]:end.file}});
        if(!current())return;this.dirty.delete(node.id);if(reply.model)this.accept(reply.model);
        this.onAttachmentSubmitted?.();
        this.status('Attachment submitted: '+file.name+'. Review pending attachments before sending.');
      }else{this.dirty.set(node.id,end.file);this.status('File ready: '+file.name);}
    }catch(e){if(current()){this.uncertain=true;this.status(String(e.message||'Upload failed').slice(0,300));}}
    finally{if(ticket===this.ticket&&this.pendingToken===pendingToken){this.pending=false;this.pendingToken=null;this.buttons();}}
  }
  async download(node){
    if(this.pending||this.uncertain)return;const ticket=this.ticket,binding=this.binding(),form=this.model.form,pendingToken=uid();this.pendingToken=pendingToken;this.pending=true;this.buttons();
    try{let offset=0,total=null,hash=null;const chunks=[];
      while(true){if(!this.current(ticket,binding,form))return;const r=await this.request('file_get',{binding,file:node.file,offset});if(!this.current(ticket,binding,form))return;
        if(!Number.isSafeInteger(r.size)||r.size<0||r.size>20*1024*1024||r.offset!==offset||typeof r.data!=='string'||r.data.length>32768||typeof r.eof!=='boolean'||!(/^[0-9a-f]{64}$/.test(r.sha256)))throw Error('Invalid download chunk');
        if(total!==null&&(total!==r.size||hash!==r.sha256))throw Error('Export changed during download');total=r.size;hash=r.sha256;
        const bytes=Uint8Array.from(atob(r.data),c=>c.charCodeAt(0));if(offset+bytes.length>total||(!bytes.length&&!r.eof))throw Error('Invalid download length');chunks.push(bytes);offset+=bytes.length;
        if(r.eof){if(offset!==total)throw Error('Incomplete download');break;}this.status(`Downloading: ${Math.round(100*offset/total)}%`);
      }
      const result=new Uint8Array(total);let pos=0;for(const c of chunks){result.set(c,pos);pos+=c.length;}const digest=await sha256Hex(result);if(digest!==hash)throw Error('Export checksum mismatch');if(!this.current(ticket,binding,form))return;
      const url=URL.createObjectURL(new Blob([result],{type:'application/octet-stream'}));const a=document.createElement('a');a.href=url;a.download=String(node.name||'PortalAI-export').replace(/[\\/\x00]/g,'_');a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);this.status('Export downloaded.');
    }catch(e){if(this.current(ticket,binding,form))this.status(String(e.message||'Download failed').slice(0,300));}
    finally{if(ticket===this.ticket&&this.pendingToken===pendingToken){this.pending=false;this.pendingToken=null;this.buttons();}}
  }
}
if(!customElements.get('portalai-native-workflows'))customElements.define('portalai-native-workflows',NativeWorkflows);
