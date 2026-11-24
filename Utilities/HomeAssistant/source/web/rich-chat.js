import { randomId, sha256Hex } from './browser-crypto.js';
// Versioned on-demand reads. Native-state/2 and its strict validators stay unchanged.
const LIMIT=20*1024*1024, CHUNK=24576, BATCH=262144;
const fail=()=>{throw Error('Invalid rich-chat response');};
const fields=(v,keys)=>{if(!v||Object.getPrototypeOf(v)!==Object.prototype||Object.keys(v).sort().join(' ')!==keys.split(' ').sort().join(' '))fail();};
const id=v=>{if(typeof v!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(v))fail();};
const txt=(v,n)=>{if(typeof v!=='string'||!v.isWellFormed()||[...v].length>n)fail();};
const num=v=>{if(!Number.isSafeInteger(v)||v<0||v>LIMIT)fail();};
const mimes=['image/png','image/jpeg','image/gif','image/webp','audio/wav','audio/mpeg','audio/ogg','audio/flac','video/mp4','video/webm','application/octet-stream'];
export function validateRich(reply,p){
  fields(reply,'accepted request_id operation rich');
  if(reply.accepted!==true||reply.request_id!==p.request_id||reply.operation!==p.operation)fail();
  const batch=p.operation==='rich_media_batch',r=reply.rich,extra={rich_index:'blocks truncated',rich_detail:'block text truncated',rich_media:'block offset next size mime name data eof identity',rich_media_batch:'block offset next size mime name data eof identity',rich_preview:'block offset next size mime name data eof identity'}[p.operation];
  fields(r,'protocol binding conversation '+extra);fields(r.binding,'view epoch');
  if(r.protocol!==(batch?2:1)||r.binding.view!==p.binding.view||r.binding.epoch!==p.binding.epoch||r.conversation!==p.conversation)fail();
  if(new TextEncoder().encode(JSON.stringify(reply)).length>(batch?360000:63000))fail();
  if(p.operation==='rich_index'){
    if(!Array.isArray(r.blocks)||r.blocks.length>120||typeof r.truncated!=='boolean')fail();
    const seen=new Set();
    for(const b of r.blocks){fields(b,'id message kind title status');id(b.id);id(b.message);txt(b.title,120);
      if(seen.has(b.id)||!['thinking','tool','media'].includes(b.kind)||!['saved','streaming','pending','returned','cancelled','incomplete','available'].includes(b.status))fail();seen.add(b.id);}
  }else{
    if(r.block!==p.block)fail();
    if(p.operation==='rich_detail'){txt(r.text,16000);if(typeof r.truncated!=='boolean')fail();}
    else{
      const bound=batch?BATCH:CHUNK;
      for(const k of ['offset','next','size'])num(r[k]);txt(r.name,160);txt(r.mime,80);id(r.identity);
      if(typeof r.data!=='string'||r.data.length>Math.ceil(bound/3)*4)fail();
      if(!r.name||/[\\/:\x00]/.test(r.name)||!mimes.includes(r.mime)||r.data.length%4||!/^[A-Za-z0-9+/]*={0,2}$/.test(r.data))fail();
      if(p.operation==='rich_preview'&&(r.size>CHUNK||!r.eof||!['image/jpeg','application/octet-stream'].includes(r.mime)))fail();
      const bytes=atob(r.data).length;
      if(bytes>bound||r.offset!==p.offset||r.next!==r.offset+bytes||r.next>r.size||typeof r.eof!=='boolean'||r.eof!==(r.next===r.size)||!bytes&&!r.eof)fail();
    }
  }return r;
}
const style=`:host{display:block;white-space:normal;margin-top:8px}details{border:1px solid var(--divider-color,#887c6240);border-radius:8px;margin:6px 0;padding:7px}summary{cursor:pointer;min-height:30px;overflow-wrap:anywhere;font:inherit}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto;font:12px/1.5 ui-monospace,monospace;margin:8px 0}small{display:block;opacity:.7}button,a{font:inherit;color:inherit;min-height:36px;margin:4px;padding:5px 10px}img,video{display:block;max-width:100%;max-height:320px;margin:8px auto}img.expanded{max-height:none}audio{max-width:100%;width:100%}a{display:inline-block}p{margin:5px 0;overflow-wrap:anywhere}`;
class RichMessage extends HTMLElement{constructor(){super();this.attachShadow({mode:'open'});this.groups=new Map();}}
if(!customElements.get('portalai-rich-message'))customElements.define('portalai-rich-message',RichMessage);
const element=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};

export class RichChat{
  constructor(root){this.root=root;this.serial=0;this.blocks=new Map();this.nodes=new Map();this.urls=new Map();this.total=0;this.busy=false;this.transfers=0;this.timer=null;this.scope='';}
  clear(){
    this.paused=true;++this.serial;clearTimeout(this.timer);this.timer=null;this.connection=null;this.scope='';this.busy=false;this.transfers=0;
    for(const u of this.urls.values())URL.revokeObjectURL(u.url);this.urls.clear();this.total=0;this.blocks.clear();this.nodes.clear();
    for(const n of this.root.querySelectorAll('portalai-rich-message')){for(const m of n.shadowRoot.querySelectorAll('audio,video'))m.pause();n.shadowRoot.replaceChildren();n.groups.clear();n.scope='';}
    this.root.querySelector('[data-rich-pending]')?.replaceChildren();
    this.notice('');
  }
  configure(connection,device,snapshot,demand,active){
    if(document.hidden||!connection||!snapshot?.chat.current||!demand?.connected){if(this.scope)this.clear();return;}
    const scope=[device,snapshot.view,snapshot.epoch,snapshot.chat.current,demand.viewer].join(':');
    if(this.scope!==scope||this.connection!==connection){this.clear();this.scope=scope;this.connection=connection;this.device=device;this.viewer=demand.viewer;}
    this.snapshot=snapshot;const resume=this.paused;this.paused=!active;
    if(this.paused){clearTimeout(this.timer);this.timer=null;return;}
    this.render();if(resume||!this.timer&&!this.busy)this.refresh();
  }

  async request(operation,extra={}){
    const ticket=this.serial,p={protocol:operation==='rich_media_batch'?2:1,request_id:randomId(),viewer:this.viewer,operation,
      binding:{view:this.snapshot.view,epoch:this.snapshot.epoch},conversation:this.snapshot.chat.current,...extra};
    if(!this.scope||this.paused||document.hidden)throw Error('Viewer disconnected');
    const result=await this.connection.sendMessagePromise({type:'portalai_native/rich',device_id:this.device,payload:p});
    if(ticket!==this.serial||!this.scope||this.paused||document.hidden)throw Error('Viewer disconnected');
    return validateRich(result,p);
  }
  notice(text){const n=this.root.querySelector('[data-rich-notice]');if(n)n.textContent=text;}
  async refresh(){
    if(!this.scope||this.paused||this.busy)return;
    if(this.transfers){this.timer=setTimeout(()=>this.refresh(),1000);return;}const ticket=this.serial;this.busy=true;
    try{
      const r=await this.request('rich_index');if(ticket!==this.serial)return;
      const fresh=new Map(r.blocks.map(b=>[b.id,b]));
      for(const [key,node] of this.nodes)if(!fresh.has(key)){this.dispose(key,node);this.nodes.delete(key);}
      this.blocks=fresh;this.notice(r.truncated?'Some older rich details are outside this view.':'');this.render();
      // Only expanded logs refresh. Collapsed media never fetches bytes.
      for(const [key,node] of this.nodes){const b=this.blocks.get(key);if(this.open(node)&&b?.kind!=='media'&&(!node.loaded||node.loadedStatus!==b.status||['streaming','pending'].includes(b.status)))await this.detail(key,node);}
    }catch(error){if(ticket===this.serial)this.notice(/^portalai_rich_(viewer|state|conversation|host_update|host_connection|host_read|reply)$/.test(error?.code||'')?error.message:'Rich details unavailable. Plain chat remains available; check both updates and the signed-in connection.');}
    finally{if(ticket===this.serial){this.busy=false;if(!this.paused)this.timer=setTimeout(()=>this.refresh(),3000);}}
  }
  dispose(key,node){for(const m of node.querySelectorAll('audio,video'))m.pause();node.remove();const u=this.urls.get(key);if(u){URL.revokeObjectURL(u.url);this.total-=u.size;this.urls.delete(key);}}
  open(node){return node.open&&node.parentElement?.open===true&&node.isConnected;}
  render(){
    const ids=new Set([...this.root.querySelectorAll('portalai-rich-message')].filter(x=>!x.closest('[data-rich-pending]')).map(n=>n.dataset.message));
    const pending=this.root.querySelector('[data-rich-pending]');
    if(pending){
      const missing=[...new Set([...this.blocks.values()].map(b=>b.message))].filter(x=>!ids.has(x));
      for(const n of [...pending.children])if(!missing.includes(n.dataset.message))n.remove();
      for(const id of missing)if(![...pending.children].some(n=>n.dataset.message===id)){const n=document.createElement('portalai-rich-message');n.dataset.message=id;pending.append(n);}
    }
    for(const slot of this.root.querySelectorAll('portalai-rich-message')){
      if(slot.scope!==this.scope){slot.shadowRoot.replaceChildren(element('style',style));slot.groups.clear();slot.scope=this.scope;}
      for(const kind of ['thinking','tool','media']){
        if(slot.dataset.richKind==='thinking'&&kind!=='thinking'||slot.dataset.richKind==='results'&&kind==='thinking')continue;
        const rows=[...this.blocks.values()].filter(b=>b.message===slot.dataset.message&&b.kind===kind);
        let group=slot.groups.get(kind);
        if(!rows.length){if(group){group.remove();slot.groups.delete(kind);}continue;}
        if(!group){group=element('details');group.append(element('summary'));slot.shadowRoot.append(group);slot.groups.set(kind,group);
          group.addEventListener('toggle',()=>{if(group.open){for(const n of group.querySelectorAll('details'))if(n.open)this.load(n.dataset.block,n);}else{for(const m of group.querySelectorAll('audio,video'))m.pause();}});}
        group.querySelector('summary').textContent=({thinking:'Reasoning',tool:'Tool calls',media:'Media & attachments'})[kind]+' ('+rows.length+')';
        for(const b of rows){
          let node=this.nodes.get(b.id);
          if(!node){node=element('details');node.dataset.block=b.id;node.append(element('summary'),element('div'));this.nodes.set(b.id,node);
            node.addEventListener('toggle',()=>{if(this.open(node))this.load(b.id,node);else for(const m of node.querySelectorAll('audio,video'))m.pause();});}
          const status=b.status==='streaming'&&this.snapshot?.chat.busy===false?'saved':b.status;
          node.querySelector('summary').textContent=(b.kind==='thinking'?'Reasoning':b.title)+(b.kind==='media'?'':' · '+status);
          if(node.parentElement!==group){const expanded=node.open&&node.parentElement?.open===true;group.append(node);if(expanded)group.open=true;}
        }
      }
    }
  }
  load(key,node){if(this.blocks.get(key)?.kind==='media')return this.media(key,node);return this.detail(key,node);}
  async detail(key,node){
    if(node.loading||!this.open(node))return;const ticket=this.serial,b=this.blocks.get(key);if(!b)return;
    if(node.loaded&&node.loadedStatus===b.status&&!['streaming','pending'].includes(b.status))return;
    node.loading=true;const body=node.querySelector('div');if(!node.loaded)body.textContent='Loading…';
    try{const r=await this.request('rich_detail',{block:key});if(ticket!==this.serial||!this.blocks.has(key)||!this.open(node))return;
      let pre=body.querySelector('pre');if(!pre){pre=element('pre');body.replaceChildren(pre,element('small'));}const pos=pre.scrollTop;
      pre.textContent=r.text;pre.scrollTop=pos;body.querySelector('small').textContent=r.truncated?'Log shortened to the transfer limit. Full record is available on the Aoostar.':'';node.loaded=true;node.loadedStatus=b.status;
    }catch{if(ticket===this.serial&&this.blocks.has(key)){body.textContent='Log unavailable. Close and reopen to retry.';node.loaded=false;}}
    finally{node.loading=false;}
  }
  async media(key,node,original=false){
    if(node.loading||node.loaded||!this.open(node))return;
    const ticket=this.serial,body=node.querySelector('div');
    if(this.transfers>=1){body.textContent='Another media file is loading. Close and reopen this one afterward.';return;}
    this.transfers++;node.loading=true;let allocated=0;body.textContent='Loading media… 0%';
    try{
      if(!original){
        let preview=null;
        try{preview=await this.request('rich_preview',{block:key,offset:0});}catch{}
        if(ticket!==this.serial||!this.blocks.has(key))return;
        if(this.paused||!this.open(node)){body.textContent='Preview paused. Close and reopen it to load.';return;}
        body.replaceChildren();
        if(preview?.size&&preview.mime==='image/jpeg'){
          if(this.total+preview.size>2*LIMIT)throw Error('Memory limit');
          const blob=new Blob([Uint8Array.from(atob(preview.data),c=>c.charCodeAt(0))],{type:'image/jpeg'});
          const url=URL.createObjectURL(blob);this.urls.set(key,{url,size:blob.size});this.total+=blob.size;
          const img=element('img');img.src=url;img.alt='Image preview';body.append(img);
          body.append(element('small','Small preview. The original attachment is unchanged.'));
        }else body.append(element('p','No small preview available. Load the original for playback or download. Older Aoostar versions require the matching preview update.'));
        const full=element('button','Load original');full.addEventListener('click',()=>{node.loaded=false;this.media(key,node,true);});body.append(full);node.loaded=true;return;
      }
      const prior=this.urls.get(key);if(prior){URL.revokeObjectURL(prior.url);this.total-=prior.size;this.urls.delete(key);}
      let offset=0,meta=null;const chunks=[];
      do{
        if(!this.open(node)||!this.blocks.has(key))throw Error('Closed');
        const r=await this.request('rich_media_batch',{block:key,offset});if(ticket!==this.serial)return;
        if(!meta){meta=r;if(this.total+r.size>2*LIMIT)throw Error('Memory limit');this.total+=r.size;allocated=r.size;}
        else if(r.identity!==meta.identity||r.mime!==meta.mime||r.size!==meta.size||r.name!==meta.name)throw Error('File changed');
        const bytes=Uint8Array.from(atob(r.data),c=>c.charCodeAt(0));chunks.push(bytes);offset=r.next;
        body.textContent='Loading media… '+Math.round(offset/Math.max(r.size,1)*100)+'%';
        if(r.eof)break;
      }while(offset<=LIMIT);
      if(!this.open(node)||ticket!==this.serial)throw Error('Closed');
      const blob=new Blob(chunks,{type:meta.mime}),url=URL.createObjectURL(blob);this.urls.set(key,{url,size:meta.size});allocated=0;
      body.replaceChildren();const mime=meta.mime;
      if(mime.startsWith('image/')){
        const img=element('img');img.src=url;img.alt=meta.name;body.append(img);const toggle=element('button','Expand image');
        toggle.addEventListener('click',()=>{const large=img.classList.toggle('expanded');toggle.textContent=large?'Minimize image':'Expand image';});body.append(toggle);
        img.addEventListener('error',()=>{img.remove();body.prepend(element('p','Preview unavailable. Download the file to open it locally.'));});
      }else if(mime.startsWith('audio/')||mime.startsWith('video/')){
        const player=element(mime.startsWith('audio/')?'audio':'video');player.controls=true;player.preload='metadata';player.autoplay=false;player.src=url;if(player.tagName==='VIDEO')player.playsInline=true;body.append(player);
        player.addEventListener('error',()=>{player.remove();body.prepend(element('p','This browser cannot play the file. Use Download.'));});
      }else body.append(element('p','Download only: this file type is not embedded.'));
      const a=element('a','Download '+meta.name);a.href=url;a.download=meta.name;body.append(a);node.loaded=true;
    }catch{if(ticket===this.serial&&this.blocks.has(key))body.textContent='Media unavailable, changed, too large (20 MiB maximum), or browser memory full. Disconnect clears loaded media; close and reopen to retry.';}
    finally{node.loading=false;if(ticket===this.serial){this.total-=allocated;this.transfers--;}}
  }
}
