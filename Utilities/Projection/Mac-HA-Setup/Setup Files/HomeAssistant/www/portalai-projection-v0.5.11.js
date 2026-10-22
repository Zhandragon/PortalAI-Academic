// PortalAI desktop card 0.5.11. HA-only build; no host changes.
// getRandomValues is available on direct HTTP HA origins as well as HTTPS.
// Do not replace this with Math.random, timestamps, or predictable identifiers.
function randomId() {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  return hex(bytes);
}

const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
const K = new Uint32Array([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
]);
const rotate = (value, bits) => (value >>> bits) | (value << (32 - bits));

// File checksums only: not used for keys, authentication, or transport security.
// SubtleCrypto is HTTPS-only. Keep verification on HTTP using the same SHA-256
// algorithm, bounded to the existing transfer limit and yielding during work.
async function sha256Hex(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.byteLength > 20 * 1024 * 1024)
    throw new Error('Checksum input must be bytes of at most 20 MiB');
  if (typeof globalThis.crypto?.subtle?.digest === 'function')
    return hex(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes)));
  const state = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
  const words = new Uint32Array(64);
  function block(input, offset) {
    for (let i=0;i<16;i++) {
      const p=offset+i*4;
      words[i]=(input[p]<<24)|(input[p+1]<<16)|(input[p+2]<<8)|input[p+3];
    }
    for (let i=16;i<64;i++) {
      const x=words[i-15],y=words[i-2];
      words[i]=words[i-16]+(rotate(x,7)^rotate(x,18)^(x>>>3))+words[i-7]+(rotate(y,17)^rotate(y,19)^(y>>>10));
    }
    let [a,b,c,d,e,f,g,h]=state;
    for (let i=0;i<64;i++) {
      const t1=(h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+K[i]+words[i])>>>0;
      const t2=((rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c)))>>>0;
      h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;
    }
    for (const [i,value] of [a,b,c,d,e,f,g,h].entries()) state[i]+=value;
  }
  const complete=bytes.length-bytes.length%64;
  for (let offset=0;offset<complete;offset+=64) {
    block(bytes,offset);
    if ((offset+64)%262144===0) await new Promise(resolve=>setTimeout(resolve,0));
  }
  const remaining=bytes.length-complete;
  const tail=new Uint8Array(remaining<56?64:128);
  tail.set(bytes.subarray(complete));tail[remaining]=128;
  // The 20 MiB input bound keeps the high 32 bits of the bit length zero.
  new DataView(tail.buffer).setUint32(tail.length-4,bytes.length*8,false);
  for (let offset=0;offset<tail.length;offset+=64) block(tail,offset);
  return Array.from(state,value=>value.toString(16).padStart(8,'0')).join('');
}

// Wall-clock checks also expire a suspended page whose timers did not run.
class VisibilityGrace {
  constructor(expire,{now=()=>Date.now(),setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}={}) {
    Object.assign(this,{expire,now,setTimer,clearTimer});this.deadline=0;this.timer=null;
  }
  reset(){this.clearTimer(this.timer);this.timer=null;this.deadline=0;}
  allowed(){
    if(this.deadline&&this.now()>=this.deadline){this.reset();this.expire();return false;}
    return true;
  }
  change(hidden){
    if(!this.allowed())return false;
    if(!hidden){this.reset();return true;}
    if(!this.deadline){this.deadline=this.now()+10000;this.timer=this.setTimer(()=>this.allowed(),10000);}
    return true;
  }
}

/* Reviewed local HA UI: upstream content is pixels and literal text only. */
class PortalAIDesktop extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'}); this.viewer=randomId();
    this.connected=false; this.connectionEpoch=0; this.queue=Promise.resolve(); this.scale=1; this.fit=true;
    this.shadowRoot.innerHTML=`<style>
      :host{display:block;height:calc(100dvh - 64px);min-height:320px;color:var(--primary-text-color,#eee);font:14px system-ui}
      *{box-sizing:border-box} .shell{height:100%;display:flex;flex-direction:column;background:var(--card-background-color,#161c25);border-radius:12px;overflow:hidden}
      .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px;padding-left:max(10px,env(safe-area-inset-left));padding-right:max(10px,env(safe-area-inset-right))}
      button,select,input{font:inherit;min-height:40px;border:1px solid var(--divider-color,#64748b);border-radius:7px;background:var(--secondary-background-color,#293343);color:inherit;padding:6px 10px}
      button{cursor:pointer}button:disabled{opacity:.45;cursor:default}select{max-width:240px;min-width:0} .title{font-weight:650;margin-right:auto} .status{padding:0 12px 8px;min-height:25px;overflow-wrap:anywhere}
      .viewport{flex:1;min-height:0;overflow:auto;background:#090c11;position:relative;overscroll-behavior:contain;text-align:center;touch-action:pan-x pan-y pinch-zoom}
      canvas{display:block;margin:auto;outline:none;touch-action:none;max-width:none} .entry{display:flex;gap:8px;padding:8px;padding-bottom:max(8px,env(safe-area-inset-bottom))} .entry input{flex:1;min-width:40px;font-size:16px} .keybar{display:flex;gap:6px;overflow:auto;padding:0 8px 8px}
      .note{font-size:12px;opacity:.8;padding:4px 12px} @media(max-height:500px){.bar{padding:4px}.note{display:none}.status{padding-bottom:3px}.entry{padding-top:3px}button,select{min-height:34px}}
      :host(.phone-portrait) .bar{gap:5px;padding:6px}:host(.phone-portrait) .title{width:100%}:host(.phone-portrait) .bar>*{min-height:34px;font-size:12px}
      :host(.phone:not(.more)) .advanced{display:none}:host(.phone) .note{display:none}:host(.phone) .keybar button{font-size:12px;min-height:34px;padding:4px 7px}
    </style><div class="shell"><div class="bar"><span class="title">PortalAI</span><button id="connect">Connect</button><button id="open">Open PortalAI</button><select id="windows" aria-label="PortalAI window"></select><button id="fit">Fit</button><button id="zoom">100%</button><button id="resize">Resize to view</button><button id="right">Right-click: off</button></div><div class="status" role="status">Connect to view the shared PortalAI desktop session.</div><div class="viewport"><canvas tabindex="0" aria-label="Remote PortalAI desktop"></canvas></div><div class="entry"><input type="password" autocomplete="off" spellcheck="false" autocapitalize="off" aria-label="Text to type into the selected PortalAI field" placeholder="Tap a PortalAI field, type here, then Send"><button id="send">Send text</button></div><div class="keybar"></div><div class="note">Shared host desktop session Ã‚Â· Login uses PortalAI's real sign-in screen Ã‚Â· Host desktop must be signed in and unlocked Ã‚Â· Audio and files stay on the host.</div></div>`;
    this.$=s=>this.shadowRoot.querySelector(s);this.canvas=this.$('canvas');this.viewport=this.$('.viewport');
    this.$('#connect').onclick=()=>this.connected?this.disconnect():this.connect();
    this.$('#open').onclick=()=>this.command('start',{request_id:randomId()}).then(()=>this.message('PortalAI is opening. Connect to sign in.')).catch(e=>this.message(e.message));
    this.$('#fit').onclick=()=>{this.fit=true;this.renderProjectionLayout()};this.$('#zoom').onclick=()=>{this.fit=false;this.scale=this.scale>=2?1:this.scale+.25;this.renderProjectionLayout()};
    const pan=document.createElement('button');pan.textContent='Pan: off';pan.onclick=()=>{this.pan=!this.pan;pan.textContent=`Pan: ${this.pan?'on':'off'}`;this.canvas.style.touchAction=this.pan?'pan-x pan-y pinch-zoom':'none'};this.$('.bar').append(pan);
    const auto=document.createElement('button');this.autoResize=true;auto.textContent='Auto resize: on';auto.onclick=()=>{this.autoResize=!this.autoResize;auto.textContent=`Auto resize: ${this.autoResize?'on':'off'}`;this.scheduleResize()};this.$('.bar').append(auto);
    this.deviceSelect=document.createElement('select');this.deviceSelect.setAttribute('aria-label','Remote layout');for(const [value,label] of [['auto','Layout: Auto'],['desktop','Full desktop'],['phone','Phone auto'],['chat','Compact chat']]){const option=document.createElement('option');option.value=value;option.textContent=label;this.deviceSelect.append(option)}this.$('.bar').append(this.deviceSelect);
    this.deviceSelect.onchange=()=>{this.setDeviceClass();this.scheduleResize()};
    this.typingMode=document.createElement('button');this.typingMode.textContent='Keyboard: screen';this.typingMode.onclick=()=>{this.screenTyping=!this.screenTyping;this.$('.entry input').value='';this.updateComposer()};this.$('.entry').prepend(this.typingMode);
    const more=document.createElement('button');more.textContent='More';more.onclick=()=>{this.classList.toggle('more');more.textContent=this.classList.contains('more')?'Less':'More'};this.$('.bar').append(more);
    for(const item of [this.$('#open'),this.$('#windows'),this.$('#zoom'),this.$('#resize'),this.$('#right'),pan,auto])item.classList.add('advanced');
    this.orientationChange=()=>{this.setDeviceClass();this.scheduleResize()};window.addEventListener('orientationchange',this.orientationChange);window.addEventListener('resize',this.orientationChange);this.setDeviceClass();
    this.$('#resize').onclick=()=>this.input({kind:'layout',view:this.phonePortrait()?'portrait_chat':'full',width:Math.max(500,Math.min(1920,this.viewport.clientWidth)),height:Math.max(400,Math.min(1200,this.viewport.clientHeight))});
    this.$('#right').onclick=()=>{this.right=!this.right;this.$('#right').textContent=`Right-click: ${this.right?'on':'off'}`};
    this.$('#windows').onchange=()=>{this.selected=this.$('#windows').value;this.window=null};
    for(const key of ['Enter','Tab','Backspace','Escape','ArrowLeft','ArrowUp','ArrowDown','ArrowRight']){
      const b=document.createElement('button');b.textContent=key;b.onclick=()=>this.input({kind:'key',key});this.$('.keybar').append(b);
    }
    this.$('#send').onclick=()=>{const field=this.$('.entry input');const text=field.value;if(!text||!this.connected||!this.window)return;field.value='';this.input({kind:this.chatComposer()?'chat_submit':'text',text})};
    this.$('.entry input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();this.$('#send').click()}};
    this.canvas.oncontextmenu=e=>e.preventDefault();
    const point=e=>{const r=this.canvas.getBoundingClientRect();return {x:Math.min(this.canvas.width-1,Math.max(0,Math.floor((e.clientX-r.left)*this.canvas.width/r.width))),y:Math.min(this.canvas.height-1,Math.max(0,Math.floor((e.clientY-r.top)*this.canvas.height/r.height)))}};
    this.canvas.onpointerdown=e=>{if(!this.window||this.pan)return;e.preventDefault();if(this.chatComposer())this.$('.entry input').value='';this.screenTyping=true;this.updateComposer();this.canvas.focus();this.canvas.setPointerCapture(e.pointerId);this.down=e.pointerId;this.button=this.right?2:e.button;this.input({kind:'pointer',action:'down',button:this.button,...point(e)})};
    this.canvas.onpointermove=e=>{if(this.down!==e.pointerId)return;if(performance.now()-(this.lastMove||0)<70)return;this.lastMove=performance.now();this.input({kind:'pointer',action:'move',button:this.button,...point(e)})};
    const up=e=>{if(this.down!==e.pointerId)return;this.down=null;this.input({kind:'pointer',action:'up',button:this.button,...point(e)})};this.canvas.onpointerup=up;this.canvas.onpointercancel=up;
    this.canvas.onwheel=e=>{e.preventDefault();this.input({kind:'wheel',delta:-e.deltaY,...point(e)})};
    this.canvas.onkeydown=e=>{if(e.ctrlKey||e.metaKey||e.altKey)return;e.preventDefault();if(e.key.length===1)this.input({kind:'text',text:e.key});else this.input({kind:'key',key:e.key})};
    this.observer=new ResizeObserver(()=>{this.renderProjectionLayout();this.scheduleResize()});this.observer.observe(this.viewport);
    this.backgroundGrace=new VisibilityGrace(()=>this.disconnect());
    this.visibility=()=>this.visibilityChange();document.addEventListener('visibilitychange',this.visibility);
  }
  setConfig(config){if(!/^[0-9a-f]{32}$/.test(config.device_id||''))throw new Error('Set the paired PortalAI device_id in this card');this.config=config;this.$('.title').textContent=config.title||'PortalAI'}
  set hass(value){this._hass=value}
  getCardSize(){return 12}
  visibilityChange(){
    if(!this.connected)return;
    if(!this.backgroundGrace.change(document.hidden))return;
    // Retire reads/input on hide; retain the viewer for the server's 10s grace.
    const epoch=++this.connectionEpoch;clearTimeout(this.timer);clearTimeout(this.resizeTimer);this.timer=null;
    this.queue=Promise.resolve();this.down=null;
    this._hass.callWS({type:'portalai_projection/viewer',device_id:this.config.device_id,viewer:this.viewer,kind:'screen',action:document.hidden?'background':'foreground'})
      .then(()=>{if(this.connected&&epoch===this.connectionEpoch&&!document.hidden)this.poll(epoch);})
      .catch(()=>{if(epoch===this.connectionEpoch)this.disconnect();});
  }
  message(text){this.$('.status').textContent=String(text)}
  command(action,payload={}){if(!this._hass)return Promise.reject(new Error('Home Assistant is not connected'));return this._hass.callWS({type:'portalai_projection/request',device_id:this.config.device_id,action,payload:{...payload,viewer:this.viewer}})}
  input(event){
    if(!this.connected||!this.window)return;
    if(event.kind!=='layout')this.inputError='';
    const window=this.window,epoch=this.connectionEpoch;
    // Never replay a failed input; clear only its error state, not its effects.
    this.queue=this.queue.then(()=>{if(!this.connected||epoch!==this.connectionEpoch||this.window!==window)throw new Error('Input canceled after the view changed');return this.command('input',{window,event})}).catch(e=>{if(epoch!==this.connectionEpoch)return;this.inputError=e.message||String(e);this.message(this.inputError)});
  }
  // Retire outstanding reads, decodes and queued input when the viewer reconnects.
  async connect(){if(this.connected)return;const epoch=++this.connectionEpoch;clearTimeout(this.timer);this.timer=null;this.didResize=false;this.connected=true;this.$('#connect').textContent='Disconnect';this.poll(epoch)}
  disconnect(){this.backgroundGrace?.reset();++this.connectionEpoch;this.connected=false;clearTimeout(this.timer);clearTimeout(this.resizeTimer);this.timer=null;this.resizeTimer=null;this.queue=Promise.resolve();this.$('#connect').textContent='Connect';this.window=null;this.canvas.width=1;this.canvas.height=1;this.command('disconnect').catch(()=>{});this.message('Disconnected. PortalAI keeps its current desktop login. Use Accounts / Exit to seal it.')}
  async poll(epoch=this.connectionEpoch){
    if(!this.connected||epoch!==this.connectionEpoch)return;
    try{
      const frame=await this.command('frame',{window:this.selected});if(!this.connected||epoch!==this.connectionEpoch)return;
      if(!frame.png){this.window=null;this.message(frame.waiting?'Waiting for a fresh PortalAI screen...':'PortalAI is closed. Use Open PortalAI, then sign in.');}
      else {
        if(typeof frame.png!=='string'||frame.png.length>5600000||!/^iVBORw0KGgo[A-Za-z0-9+/=]+$/.test(frame.png)||!Number.isInteger(frame.width)||frame.width<80||frame.width>2560||!Number.isInteger(frame.height)||frame.height<30||frame.height>1600)throw new Error('Invalid screen frame');
        const header=atob(frame.png.slice(0,64));const word=offset=>((header.charCodeAt(offset)*16777216)+(header.charCodeAt(offset+1)<<16)+(header.charCodeAt(offset+2)<<8)+header.charCodeAt(offset+3));if(header.slice(12,16)!=='IHDR'||word(16)!==frame.width||word(20)!==frame.height)throw new Error('PNG header dimensions differ');
        const image=new Image();image.src='data:image/png;base64,'+frame.png;await image.decode();if(!this.connected||epoch!==this.connectionEpoch)return;
        if(image.naturalWidth!==frame.width||image.naturalHeight!==frame.height)throw new Error('Screen dimensions differ');
        this.canvas.width=frame.width;this.canvas.height=frame.height;this.canvas.getContext('2d').drawImage(image,0,0);this.window=frame.window;this.nativeDialog=frame.native_dialog===true;
        if(this.profileOpen!==(frame.profile_open===true)){this.didResize=false;this.screenTyping=false;this.$('.entry input').value=''}this.profileOpen=frame.profile_open===true;this.renderProjectionLayout();this.updateComposer();
        if(!this.didResize){this.didResize=true;this.scheduleResize()}
        const list=this.$('#windows');list.replaceChildren();for(const row of frame.windows||[]){const option=document.createElement('option');option.value=row.id;option.textContent=row.title;list.append(option)}list.value=frame.window;
        this.message(this.inputError||('Connected Ã‚Â· '+frame.width+' Ãƒâ€” '+frame.height+' Ã‚Â· Tap or click the screen to interact'));
      }
    }catch(e){if(!this.connected||epoch!==this.connectionEpoch)return;this.window=null;this.canvas.width=1;this.canvas.height=1;this.message(e.message||String(e))}
    if(this.connected&&epoch===this.connectionEpoch)this.timer=setTimeout(()=>this.poll(epoch),650);
  }
  renderProjectionLayout(){if(this.canvas.width<80)return;const scale=this.fit?Math.min(this.viewport.clientWidth/this.canvas.width,this.viewport.clientHeight/this.canvas.height):this.scale;this.canvas.style.width=Math.max(1,this.canvas.width*scale)+'px';this.canvas.style.height=Math.max(1,this.canvas.height*scale)+'px';this.$('#zoom').textContent=Math.round(scale*100)+'%'}
  phonePortrait(){
    const mode=this.deviceSelect?.value||'auto';if(mode==='chat')return true;if(mode==='desktop')return false;
    const ua=navigator.userAgent;const phone=mode==='phone'||/iPhone|iPod/i.test(ua);if(!phone)return false;
    // Physical orientation takes precedence over the keyboard-reduced viewport.
    if(typeof window.orientation==='number')return Math.abs(window.orientation)!==90;
    if(screen.orientation?.type&&/iPhone|iPod/i.test(ua))return screen.orientation.type.startsWith('portrait');
    return matchMedia('(orientation: portrait)').matches;
  }
  chatComposer(){return this.phonePortrait()&&this.profileOpen&&!this.nativeDialog&&!this.screenTyping}
  updateComposer(){const chat=this.chatComposer();const field=this.$('.entry input');if(field.type!==(chat?'text':'password'))field.value='';field.type=chat?'text':'password';field.placeholder=chat?'Message PortalAI':'Tap a PortalAI field, type here, then Send';field.setAttribute('aria-label',chat?'Message PortalAI':'Text to type into the selected PortalAI field');this.$('#send').textContent=chat?'Send chat':'Send text';if(this.typingMode){this.typingMode.hidden=!(this.phonePortrait()&&this.profileOpen&&!this.nativeDialog);this.typingMode.textContent=chat?'Keyboard: chat':'Keyboard: screen'}}
  setDeviceClass(){const mode=this.deviceSelect?.value||'auto';this.classList.toggle('phone',mode==='phone'||mode==='chat'||(mode==='auto'&&/iPhone|iPod/i.test(navigator.userAgent)));this.classList.toggle('phone-portrait',this.phonePortrait());this.updateComposer()}
  scheduleResize(){clearTimeout(this.resizeTimer);if(this.autoResize&&this.connected&&!this.nativeDialog)this.resizeTimer=setTimeout(()=>this.$('#resize').click(),600)}
  connectedCallback(){this.observer.observe(this.viewport);document.addEventListener('visibilitychange',this.visibility);window.addEventListener('orientationchange',this.orientationChange);window.addEventListener('resize',this.orientationChange)}
  disconnectedCallback(){this.disconnect();clearTimeout(this.resizeTimer);this.observer.disconnect();document.removeEventListener('visibilitychange',this.visibility);window.removeEventListener('orientationchange',this.orientationChange);window.removeEventListener('resize',this.orientationChange)}
}
if(!customElements.get('portalai-projection'))customElements.define('portalai-projection',PortalAIDesktop);
window.customCards=window.customCards||[];window.customCards.push({type:'portalai-projection',name:'PortalAI Projection',description:'Independent portable PortalAI window stream'});

