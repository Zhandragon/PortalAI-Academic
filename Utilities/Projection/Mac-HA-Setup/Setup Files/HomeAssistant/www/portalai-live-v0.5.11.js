// PortalAI native UI 0.5.11, native workflows. Built from reviewed local modules.
const PANEL_CSS=":host{display:block;height:100dvh;min-height:360px;color:var(--text);font:14px/1.5 'Segoe UI',system-ui,sans-serif;color-scheme:light;--bg:#EEE7DC;--panel:#F8F3EA;--panel2:#E9E0D2;--panel3:#DED1BC;--card:#FFFDF8;--card-hover:#F7F0E5;--text:#202224;--muted:#625E59;--muted2:#7C725F;--accent:#3E91A2;--accent2:#1F6F82;--good:#2E8062;--warn:#9D7027;--bad:#A9514C;--button:#E6DCCB;--button-hover:#D9CBB3;--border:#7B5A22;--gold-mid:#A87D32;--gold-shine:#D9BE78;--outline:#343638;--border-soft:#6E6E6B;--shadow:#1E2022}\n:host([theme=dark]){color-scheme:dark}*{box-sizing:border-box}button,input,textarea,select{font:inherit}button,a,input,textarea,select{outline-offset:4px}button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:2px solid var(--accent)}button,a,select{touch-action:manipulation}button{cursor:pointer}button:disabled{cursor:not-allowed;opacity:.48}button{background:var(--button);color:var(--text);border:1px solid color-mix(in srgb,var(--border) 55%,transparent);border-radius:8px;padding:9px 14px;min-height:40px}button:hover:not(:disabled){background:var(--button-hover)}button.primary{background:var(--accent2);border-color:var(--accent2);color:#fff}button.primary:hover:not(:disabled){background:var(--accent)}button.quiet{background:transparent;border-color:transparent}button.danger{color:var(--bad)}a{color:var(--accent2);text-underline-offset:3px}.app{height:100%;display:flex;flex-direction:column;background:var(--bg);overflow:hidden}.masthead{display:flex;align-items:center;gap:16px;padding:13px 26px 10px;border-top:3px solid var(--gold-mid);position:relative}.masthead:after{content:'';position:absolute;bottom:0;left:26px;right:26px;height:1px;background:linear-gradient(90deg,var(--gold-mid),var(--gold-shine),var(--gold-mid));opacity:.6}.brand{display:flex;align-items:center;gap:10px;margin-right:auto}.brand img{width:38px;height:38px;object-fit:contain}.wordmark{font:600 25px/1.1 Georgia,serif;letter-spacing:1px;color:var(--text)}.brand small{display:block;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-size:9px;margin-top:4px}.header-actions{display:flex;align-items:center;gap:10px}.header-actions a{font-size:12px;white-space:nowrap}.status-chip{font-size:12px;display:flex;gap:7px;align-items:center;color:var(--muted)}.dot{height:7px;width:7px;border-radius:50%;background:var(--warn);display:inline-block}.dot.good{background:var(--good)}.nav{display:flex;gap:3px;padding:12px 25px 10px;overflow:auto;flex:none;scrollbar-width:thin}.nav button{white-space:nowrap;background:transparent;border-color:transparent;font-weight:600;padding:7px 12px;min-height:36px}.nav button[aria-selected=true]{background:var(--accent2);color:#fff;border-color:var(--accent2)}.nav button:hover:not([aria-selected=true]){background:var(--panel2)}.mobile-nav{display:none}.preview-banner{display:flex;align-items:center;gap:10px;background:var(--panel2);border-block:1px solid color-mix(in srgb,var(--border) 22%,transparent);padding:7px 26px;font-size:12px;color:var(--muted)}.preview-banner strong{color:var(--warn);font-size:10px;letter-spacing:1.3px;white-space:nowrap}.preview-banner button{margin-left:auto;padding:1px 8px;min-height:26px;font-size:11px;background:transparent}.workspace{flex:1;min-height:0;overflow:auto;scrollbar-color:var(--gold-mid) transparent;scrollbar-width:thin}.page{max-width:1380px;margin:auto;padding:28px 34px 42px}.page-heading{display:flex;align-items:start;gap:20px;margin-bottom:22px}.page-heading h1{font:600 27px/1.2 Georgia,serif;margin:0 0 7px}.page-heading p{margin:0;color:var(--muted);max-width:760px}.eyebrow{text-transform:uppercase;letter-spacing:2px;font-size:10px;color:var(--muted2);font-weight:650;margin-bottom:10px}.page-heading .pill{margin-left:auto;flex-shrink:0}.pill{border:1px solid color-mix(in srgb,var(--border) 35%,transparent);border-radius:20px;padding:4px 10px;font-size:11px;color:var(--muted);display:inline-flex;gap:7px;align-items:center}.ornate{position:relative;border:1px solid var(--border);border-radius:13px;background:var(--panel);box-shadow:inset 0 0 0 3px color-mix(in srgb,var(--gold-shine) 25%,transparent);padding:25px}.ornate:before{content:'◇';position:absolute;left:50%;top:-11px;color:var(--gold-mid);background:var(--bg);padding:0 12px;line-height:20px}.hero{display:grid;grid-template-columns:1.2fr .8fr;align-items:center;gap:30px;min-height:360px;padding:28px 26px 35px}.hero h1{font:500 clamp(40px,5vw,68px)/1.04 Georgia,serif;letter-spacing:-2px;margin:12px 0 22px}.hero p{font-size:17px;line-height:1.75;color:var(--muted);max-width:580px}.hero img{width:min(100%,280px);justify-self:center;filter:drop-shadow(0 16px 25px #00000018)}.hero .actions{margin-top:26px}.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.intro-row{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;margin:28px 4px}.intro-row section{border-top:1px solid var(--gold-mid);padding-top:16px}.intro-row h2{font:600 17px Georgia,serif;margin:0 0 8px}.intro-row p{margin:0;color:var(--muted);font-size:13px}.muted{color:var(--muted)}.small{font-size:12px}.section-title{font:600 18px Georgia,serif;margin:0 0 15px}.note{color:var(--muted);font-size:12px;margin:14px 0;max-width:880px}.availability{border-left:3px solid var(--gold-mid);padding:10px 15px;background:var(--panel2);color:var(--muted);font-size:12px;margin-bottom:20px}.availability a{margin-left:5px}.section-row{display:flex;align-items:center;gap:12px;margin-bottom:18px}.section-row h2{margin:0;font:600 20px Georgia,serif}.section-row .actions{margin-left:auto}.control-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:25px}.control{padding:20px;text-align:left;min-height:115px;display:flex;flex-direction:column;gap:8px;background:var(--panel);border-color:var(--border);opacity:1!important}.control strong{font:600 18px Georgia,serif}.control span{font-size:12px;color:var(--muted)}.control em{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--warn);font-style:normal}.control.danger{border-color:var(--bad)}.two-columns{display:grid;grid-template-columns:1fr 1fr;gap:20px}.key-values{display:grid;grid-template-columns:minmax(120px,.8fr) 1.2fr;gap:11px;font-size:13px}.key-values dt{color:var(--muted)}.key-values dd{margin:0}.log{font:12px/1.8 ui-monospace,Consolas,monospace;color:var(--muted);padding:17px;background:var(--card);border-radius:7px}.log p{margin:0 0 6px}.subtabs{display:flex;gap:6px;border-bottom:1px solid color-mix(in srgb,var(--gold-mid) 40%,transparent);margin-bottom:22px;padding-bottom:9px}.subtabs button{background:transparent;border-color:transparent}.subtabs button[aria-selected=true]{background:var(--panel2);border-color:var(--border);font-weight:600}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.field{display:flex;flex-direction:column;gap:7px}.field>span{font-weight:600;font-size:13px}.field small{color:var(--muted);font-size:12px}.field select,.field input,input.search,textarea{width:100%;border:1px solid color-mix(in srgb,var(--border) 45%,transparent);border-radius:7px;background:var(--card);color:var(--text);padding:10px 12px;min-height:42px}.form-footer{display:flex;align-items:center;gap:12px;margin-top:25px;border-top:1px solid color-mix(in srgb,var(--gold-mid) 30%,transparent);padding-top:18px}.form-footer .actions{margin-left:auto}.help-detail{padding:14px 17px;border-left:3px solid var(--accent);background:var(--panel2);font-size:12px;margin:20px 0 0}.help-detail strong{display:block;margin-bottom:5px}.data-table{width:100%;border-collapse:collapse;font-size:13px}.data-table th{color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.7px;text-align:left;padding:12px;border-bottom:1px solid var(--border)}.data-table td{padding:18px 12px;border-bottom:1px solid color-mix(in srgb,var(--border) 20%,transparent);vertical-align:middle}.data-table td strong{display:block}.data-table td small{color:var(--muted)}.table-scroll{overflow:auto}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:25px}.metric{border-bottom:2px solid var(--gold-mid);padding:10px 8px 20px}.metric .value{font:36px Georgia,serif;margin:10px 0}.meter{height:6px;background:var(--panel3);border-radius:4px;overflow:hidden}.meter span{height:100%;display:block;background:var(--accent);border-radius:4px}.empty{text-align:center;padding:44px 20px}.empty .empty-symbol{font:36px Georgia,serif;color:var(--gold-mid)}.empty h2{font:600 22px Georgia,serif}.empty p{max-width:530px;margin:10px auto 20px;color:var(--muted)}.page.chat-page{max-width:none;padding:20px 26px;height:100%;display:flex;flex-direction:column}.chat-page .page-heading{margin-bottom:14px;align-items:center}.chat-page .page-heading h1{font-size:23px}.chat-page .page-heading p{font-size:12px}.chat-layout{display:grid;grid-template-columns:235px minmax(0,1fr);gap:16px;flex:1;min-height:0}.history{display:flex;flex-direction:column;min-height:0;padding:14px;background:var(--panel2);border:1px solid color-mix(in srgb,var(--border) 35%,transparent);border-radius:10px}.history .history-heading{display:flex;align-items:center;gap:8px;font:600 17px Georgia,serif;margin:1px 0 15px}.history .history-heading button{margin-left:auto;padding:1px 8px;min-height:28px}.search{font-size:12px!important;padding:8px!important;min-height:34px!important}.history-list{flex:1;overflow:auto;margin-top:13px}.history-item{background:transparent;border:1px solid transparent;display:block;width:100%;text-align:left;padding:12px 10px;margin-bottom:5px}.history-item[aria-current=true]{background:var(--panel);border-color:var(--border)}.history-item strong{display:block;font-size:12px;font-weight:600}.history-item small{display:block;color:var(--muted);font-size:10px;margin-top:4px}.history footer{font-size:11px;color:var(--muted);border-top:1px solid color-mix(in srgb,var(--border) 30%,transparent);padding-top:12px;margin-top:10px}.conversation{display:flex;flex-direction:column;min-height:0;overflow:hidden;border:1px solid var(--border);border-radius:12px;background:var(--panel)}.chat-toolbar{display:flex;gap:5px;align-items:center;padding:8px 12px;border-bottom:1px solid color-mix(in srgb,var(--border) 25%,transparent);flex-wrap:wrap}.chat-toolbar button{font-size:11px;padding:5px 8px;min-height:30px}.chat-toolbar .spacer{flex:1}.transcript{flex:1;min-height:120px;overflow:auto;padding:26px 30px;scrollbar-width:thin}.message{max-width:830px;margin:0 auto 25px}.message .speaker{display:flex;align-items:center;gap:8px;font-size:10px;letter-spacing:1px;font-weight:700;text-transform:uppercase;margin-bottom:9px;color:var(--muted)}.message .speaker img{width:20px;height:20px}.message p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.85;margin:0;font-size:14px}.message.user p{background:var(--panel2);padding:13px 17px;border-radius:10px}.message.assistant p{padding:0 3px}.chat-intro{text-align:center;padding:30px 15px}.chat-intro img{width:84px}.chat-intro h2{font:600 26px Georgia,serif}.chat-intro p{color:var(--muted)}.composer{margin:0 15px 13px;border:1px solid color-mix(in srgb,var(--border) 55%,transparent);background:var(--card);border-radius:11px;padding:12px}.composer textarea{resize:vertical;min-height:70px;max-height:180px;border:0;background:transparent;padding:2px 4px;outline-offset:0;line-height:1.6}.composer .actions{margin-top:8px}.composer .actions button{min-height:32px;padding:5px 10px;font-size:12px}.composer .send{margin-left:auto}.composer .draft-note{font-size:10px;color:var(--muted);margin:5px 4px 0}.context-line{display:flex;gap:10px;align-items:center;font-size:10px;color:var(--muted);padding:0 19px 12px;flex-wrap:wrap}.context-line .meter{width:90px;height:4px}.mobile-history{display:none}.drawer{position:absolute;inset:0;z-index:8;background:#0007;display:flex;justify-content:flex-end}.drawer .sheet{width:min(480px,100%);background:var(--panel);padding:25px;overflow:auto;box-shadow:-8px 0 32px #0003}.drawer .sheet header{display:flex;align-items:center;margin-bottom:20px;gap:10px}.drawer .sheet h2{font:600 23px Georgia,serif;margin:0}.drawer .sheet header button{margin-left:auto}.drawer .sheet .field{margin-bottom:20px}.drawer .sheet p{color:var(--muted)}.help-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:25px}.help-topics{display:flex;flex-direction:column;gap:4px}.help-topics button{text-align:left;background:transparent;border-color:transparent}.help-topics button[aria-current=true]{color:var(--accent2);background:var(--panel2);font-weight:600}.help-copy{line-height:1.9;max-width:800px}.help-copy h2{font:600 27px Georgia,serif}.help-copy h3{font:600 19px Georgia,serif;margin-top:25px}.help-copy p{color:var(--muted)}.help-copy li{margin-bottom:12px}.footer{padding:7px 26px;font-size:10px;color:var(--muted2);border-top:1px solid color-mix(in srgb,var(--border) 25%,transparent);display:flex;justify-content:space-between;gap:10px}.workspace{position:relative}.toast{position:absolute;bottom:45px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:10px 18px;border-radius:8px;font-size:12px;max-width:90%;z-index:10}.hidden{display:none!important}\n@media(max-width:1000px){.nav{padding-inline:15px}.nav button{padding-inline:9px;font-size:12px}.masthead{padding-inline:18px}.page{padding:24px}.status-chip{display:none}.chat-layout{grid-template-columns:200px minmax(0,1fr)}.control-grid{grid-template-columns:repeat(2,1fr)}.transcript{padding:23px 20px}.header-actions a{font-size:11px}}\n@media(max-width:640px) and (orientation:portrait){.masthead{padding:9px 14px;gap:8px}.brand img{width:31px;height:31px}.wordmark{font-size:21px}.brand small{font-size:8px;letter-spacing:1px}.header-actions{gap:2px}.header-actions a{display:none}.header-actions button{padding:5px 9px;min-height:34px;font-size:12px}.nav{display:none}.mobile-nav{display:flex;align-items:center;gap:12px;padding:9px 14px}.mobile-nav select{flex:1;min-width:0;padding:8px;border:1px solid var(--border);border-radius:7px;background:var(--panel);color:var(--text)}.mobile-nav a{font-size:11px}.preview-banner{padding:6px 14px;font-size:10px;gap:7px}.preview-banner strong{font-size:8px;letter-spacing:.7px}.preview-banner button{display:none}.page{padding:23px 17px}.page-heading{gap:10px}.page-heading h1{font-size:25px}.page-heading p{font-size:12px}.page-heading .pill{display:none}.hero{grid-template-columns:1fr;gap:15px;padding:15px 5px}.hero img{grid-row:1;width:130px}.hero h1{font-size:42px;letter-spacing:-1px}.hero p{font-size:14px}.intro-row{grid-template-columns:1fr;gap:17px}.ornate{padding:18px}.form-grid,.two-columns{grid-template-columns:1fr}.control-grid{gap:10px}.control{padding:13px;min-height:130px}.control strong{font-size:16px}.control span{font-size:11px}.form-footer{align-items:start;flex-direction:column}.form-footer .actions{margin-left:0}.subtabs{gap:3px}.subtabs button{font-size:12px;padding:7px}.metrics{gap:10px}.metric .value{font-size:27px}.metric .small{font-size:10px}.page.chat-page{padding:0;height:100%}.chat-page .page-heading{padding:11px 14px;margin:0}.chat-page .page-heading h1{font-size:19px;margin:0}.chat-page .page-heading p{font-size:10px}.chat-layout{display:flex;gap:0}.history{display:none}.history.open{display:flex;position:absolute;left:0;top:0;bottom:0;width:85%;max-width:310px;z-index:7;box-shadow:10px 0 40px #0005;background:var(--panel2)}.conversation{flex:1;border-radius:0;border-inline:0;border-bottom:0;min-width:0}.chat-toolbar{padding:7px 11px;gap:3px;flex-wrap:nowrap;overflow-x:auto;flex-shrink:0}.chat-toolbar button{white-space:nowrap;font-size:10px}.mobile-history{display:inline-block}.chat-toolbar .desktop-extra{display:none}.transcript{padding:21px 16px;min-height:90px}.message{margin-bottom:21px}.message p{font-size:13px;line-height:1.75}.composer{margin:0 10px 9px;padding:8px}.composer textarea{min-height:65px;max-height:125px;font-size:16px}.composer .actions{gap:5px}.composer .actions button{font-size:10px;padding:6px 8px}.composer .draft-note{font-size:9px}.context-line{padding:0 14px 9px;font-size:9px;gap:7px}.context-line .meter{width:50px}.help-layout{grid-template-columns:1fr;gap:10px}.help-topics{flex-direction:row;overflow:auto}.help-topics button{white-space:nowrap;font-size:12px}.help-copy h2{font-size:23px}.footer{padding:5px 14px;font-size:9px}.footer span:last-child{display:none}.drawer .sheet{padding:19px}.section-row{align-items:start}.section-row .actions{max-width:50%}.data-table th,.data-table td{padding:12px 8px}.availability{font-size:11px}}\n:host{height:100%;min-height:0}.app{position:relative}.chat-page .page-heading,.chat-toolbar,.composer,.context-line{flex-shrink:0}.transcript{min-height:0}\n@media(max-height:520px) and (orientation:landscape){.masthead{padding:5px 14px}.brand img{width:25px;height:25px}.wordmark{font-size:19px}.brand small{display:none}.header-actions button{min-height:28px;padding:2px 9px;font-size:11px}.nav{padding:4px 12px;gap:1px}.nav button{min-height:28px;padding:3px 8px;font-size:11px}.preview-banner{padding:3px 14px;font-size:10px}.preview-banner strong{font-size:9px}.preview-banner button{min-height:22px}.footer{display:none}.page.chat-page{padding:7px 12px}.chat-page .page-heading{display:none}.chat-layout{grid-template-columns:180px minmax(0,1fr);gap:10px}.chat-toolbar{padding:3px 7px}.chat-toolbar button{min-height:25px;padding:3px 6px;font-size:10px}.transcript{padding:12px 16px}.message{margin-bottom:12px}.message p{font-size:12px}.message .speaker{margin-bottom:5px}.composer{margin:0 7px 5px;padding:5px}.composer textarea{height:40px;min-height:40px;max-height:65px;font-size:12px;resize:none}.composer .actions{margin-top:0;gap:5px}.composer .actions button{min-height:25px;font-size:10px;padding:3px 8px}.composer .draft-note{display:none}.context-line{font-size:9px;padding:0 13px 4px}.history{padding:9px}.history .history-heading{font-size:14px;margin-bottom:9px}.history footer{font-size:10px}.history-list{margin-top:8px}.history-item{padding:8px}.chat-intro{padding:10px}.chat-intro img{width:40px}.chat-intro h2{font-size:20px}}\n@media(prefers-reduced-motion:no-preference){button{transition:background .12s,color .12s}.page{animation:appear .12s ease-out}@keyframes appear{from{opacity:.65}to{opacity:1}}}\n";
const PANEL_IMAGES={"icon.png":"data:image/png;base64,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","emblem.png":"data:image/png;base64,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","wordmark.png":"data:image/png;base64,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"};
const {randomId,sha256Hex}=(()=>{
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

return {randomId,sha256Hex};
})();
const {CATALOG}=(()=>{
const CATALOG = {
  "surfaces": [
    {
      "desktop_id": "welcome",
      "label": "Welcome",
      "source_modules": [
        "reference/PortalAI/ControlCenter/public_welcome.py",
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py"
      ],
      "scope": "Branding, overview, help; browser-local presentation."
    },
    {
      "desktop_id": "accounts",
      "label": "Accounts",
      "source_modules": [
        "reference/PortalAI/ControlCenter/account_gate.py",
        "reference/PortalAI/ControlCenter/accounts_page.py",
        "reference/PortalAI/ControlCenter/account_ui.py",
        "reference/PortalAI/ControlCenter/account_switch.py",
        "reference/PortalAI/ControlCenter/admin_profile_ui.py",
        "reference/PortalAI/ControlCenter/account_reset_ui.py"
      ],
      "scope": "Real login/enrollment/password/admin/recovery/export/switch/logout flows; staged port, fallback initially."
    },
    {
      "desktop_id": "controls",
      "label": "Controls",
      "source_modules": [
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py",
        "reference/PortalAI/ControlCenter/lifecycle_control.py"
      ],
      "scope": "Six primary buttons, runtime/startup state, Control Log and contextual actions."
    },
    {
      "desktop_id": "chat",
      "label": "Chat",
      "source_modules": [
        "reference/PortalAI/ControlCenter/native_chat.py",
        "reference/PortalAI/ControlCenter/portal_frontend_v15136.py",
        "reference/PortalAI/ControlCenter/chat_catalog.py",
        "reference/PortalAI/ControlCenter/persistent_memory.py",
        "reference/PortalAI/ControlCenter/memory_items_ui.py",
        "reference/PortalAI/ControlCenter/chat_effort_ui.py"
      ],
      "scope": "Transcript, streaming, tools, history, memory, attachments, preferences, media, microphone."
    },
    {
      "desktop_id": "activity",
      "label": "Runtime",
      "source_modules": [
        "reference/PortalAI/ControlCenter/runtime_activity.py",
        "reference/PortalAI/ControlCenter/activity_monitor.py",
        "reference/PortalAI/ControlCenter/windows_gpu_counters.py"
      ],
      "scope": "Read-only account-scoped runtime/CPU/GPU observations; no process argv export."
    },
    {
      "desktop_id": "runtime",
      "label": "Models",
      "source_modules": [
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py",
        "reference/PortalAI/ControlCenter/bundle_inventory.py",
        "reference/PortalAI/ControlCenter/runtime_health.py"
      ],
      "scope": "Installed/loaded/sleeping/healthy state and capability detail; do not conflate them."
    },
    {
      "desktop_id": "installed",
      "label": "Packages",
      "source_modules": [
        "reference/PortalAI/ControlCenter/packages_page.py",
        "reference/PortalAI/ControlCenter/bundle_inventory.py"
      ],
      "scope": "Package/capability inventories and help; file presence does not prove inference."
    },
    {
      "desktop_id": "settings",
      "label": "Settings",
      "source_modules": [
        "reference/PortalAI/ControlCenter/settings_page.py",
        "reference/PortalAI/ControlCenter/settings_style.py",
        "reference/PortalAI/ControlCenter/media_choices.py"
      ],
      "scope": "Chat model and memory / Media defaults subtabs, draft preservation, immediate model-pair save, fit probes."
    },
    {
      "desktop_id": "persistence",
      "label": "Persistence",
      "source_modules": [
        "reference/PortalAI/ControlCenter/persistence_page.py",
        "reference/PortalAI/ControlCenter/mission_settings.py",
        "reference/PortalAI/ControlCenter/schedule_settings.py"
      ],
      "scope": "Missions and Schedules subtabs; explicit reviewed resume, arm/disarm, recoverable list removal."
    },
    {
      "desktop_id": "maintenance",
      "label": "Maintenance",
      "source_modules": [
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py",
        "reference/PortalAI/ControlCenter/maintenance_cleanup.py",
        "reference/PortalAI/ControlCenter/profile_diagnostics.py",
        "reference/PortalAI/ControlCenter/settings_page.py"
      ],
      "scope": "Reports, diagnostics, storage reserves, review-only duplicate scan, cleanup and dependency probes."
    },
    {
      "desktop_id": "help",
      "label": "Help",
      "source_modules": [
        "reference/PortalAI/ControlCenter/help_topics.py",
        "reference/PortalAI/ControlCenter/public_welcome.py",
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py"
      ],
      "scope": "Help topics and branded artwork; browser-local rendering."
    }
  ],
  "themes": {
    "LIGHT_COLORS": {
      "bg": "#EEE7DC",
      "panel": "#F8F3EA",
      "panel2": "#E9E0D2",
      "panel3": "#DED1BC",
      "card": "#FFFDF8",
      "card_hover": "#F7F0E5",
      "text": "#202224",
      "muted": "#625E59",
      "muted2": "#7C725F",
      "accent": "#3E91A2",
      "accent2": "#1F6F82",
      "good": "#2E8062",
      "warn": "#9D7027",
      "bad": "#A9514C",
      "button": "#E6DCCB",
      "button_hover": "#D9CBB3",
      "danger": "#7C403E",
      "danger_hover": "#66312F",
      "border": "#7B5A22",
      "gold_mid": "#A87D32",
      "gold_shine": "#D9BE78",
      "outline": "#343638",
      "border_soft": "#6E6E6B",
      "shadow": "#1E2022",
      "model_bg": "#F3ECE1"
    },
    "DARK_COLORS": {
      "bg": "#111315",
      "panel": "#1C1E20",
      "panel2": "#252729",
      "panel3": "#302D27",
      "card": "#242628",
      "card_hover": "#2D3032",
      "text": "#F2ECE2",
      "muted": "#B7AFA4",
      "muted2": "#9D9282",
      "accent": "#58AFC1",
      "accent2": "#7CC4D3",
      "good": "#63B88E",
      "warn": "#C89B4A",
      "bad": "#D17770",
      "button": "#2A2D2F",
      "button_hover": "#363A3D",
      "danger": "#6C3534",
      "danger_hover": "#83423F",
      "border": "#806027",
      "gold_mid": "#B0863A",
      "gold_shine": "#D6BA70",
      "outline": "#070809",
      "border_soft": "#4B4E50",
      "shadow": "#000000",
      "model_bg": "#101214"
    }
  },
  "media": {
    "CHOICES": {
      "media_variant": {
        "auto": [
          "Automatic | let Nice choose per request",
          "Nice chooses standard or a supported uncensored alternate for each request, independently of the chat model. Hardware, memory and task requirements still apply. Tools use standard when Nice supplies no choice."
        ],
        "standard": [
          "Standard | media default",
          "Use standard media weights unless you explicitly request an alternate for that job. This does not change the chat model. Voice, music and other specialists with no separate variant retain their normal models."
        ],
        "uncensored": [
          "Uncensored | where compatible",
          "Prefer installed uncensored media weights where the requested task and hardware support them. Missing or non-fitting pairs use a reported standard fallback; an explicit unsupported alternate fails. This does not change the chat model."
        ]
      },
      "image_profile": {
        "auto": [
          "Automatic, fit this computer",
          "Selects FLUX on a sufficiently large NVIDIA GPU, otherwise SD1.5. Memory is checked after chat releases it. Klein4 is an explicit choice."
        ],
        "sd15": [
          "SD1.5 | entry level | CPU / GPU",
          "512px native images on Windows/Linux x64. CPU: 8 GiB free RAM; Vulkan: 8 GiB, or 10 GiB on shared memory. CUDA: 3 GiB free VRAM + 5 GiB RAM. Standard or DreamShaper 8 follows your media preference."
        ],
        "klein4": [
          "Klein4 | midrange | CPU / Vulkan",
          "128\u2013512px images and reference editing on Windows/Linux x64. Needs 12 GiB free RAM, or 16 GiB with shared GPU memory. Four steps; CPU is slow. Standard/alternate encoders installed. Physical Radeon/Intel/Linux inference is unvalidated."
        ],
        "flux": [
          "FLUX | high end | NVIDIA CUDA",
          "Larger ComfyUI image workflow: at least 16 GiB free CUDA VRAM + 8 GiB free RAM; alternate encoder requires 20 GiB of each. Native CPU/Vulkan engines do not run this profile; choose Klein4 for those. Linux GPU execution remains unvalidated."
        ]
      },
      "image_engine": {
        "auto": [
          "Automatic, fit this computer",
          "Uses the selected image model and detected hardware. An explicit model still has to fit; choosing Automatic does not bypass memory or device checks."
        ],
        "comfyui": [
          "ComfyUI | NVIDIA / supported Radeon",
          "GPU workflow engine: NVIDIA CUDA, or compute-probed ROCm for SD1.5. Windows/Linux runtime support varies by model; physical Radeon/Linux GPU runs remain unvalidated. Klein4 uses a native engine instead."
        ],
        "sdcpp-vulkan": [
          "Vulkan | Radeon / Intel / NVIDIA",
          "Native SD1.5 or Klein4 on Windows/Linux x64. Requires a working Vulkan device; integrated graphics share system RAM. CPU text encoder/decoder and offloading remain part of the job. Physical Radeon/Intel validation pending."
        ],
        "sdcpp-cpu": [
          "CPU | any supported x64 PC | slow",
          "Native SD1.5 or Klein4 without GPU acceleration on Windows/Linux x64. Needs 8 GiB free RAM for SD1.5 or 12 GiB for Klein4. Keeps model-specific size and step limits."
        ]
      },
      "speech_model": {
        "auto": [
          "Automatic, fit this computer",
          "Chooses Whisper large-v3-turbo when CUDA has at least 3 GiB free VRAM and 6 GiB free RAM; otherwise Whisper Base. Windows/Linux x64. Radeon/Intel use CPU transcription."
        ],
        "base": [
          "Whisper Base | light | CPU / CUDA",
          "Faster, smaller multilingual transcription. Needs 3 GiB free RAM; CPU works on Windows/Linux x64, including Radeon/Intel computers. CUDA acceleration needs at least 1 GiB free VRAM."
        ],
        "large-v3-turbo": [
          "Whisper Turbo | accuracy | CPU / CUDA",
          "Larger multilingual transcription model. Needs 6 GiB free RAM and 3 GiB free VRAM for CUDA. Automatic device selection keeps this model on CPU if CUDA memory is insufficient; CPU is slower. No ROCm or Vulkan transcription path is enabled."
        ]
      },
      "voice_engine": {
        "auto": [
          "Automatic, fit this computer",
          "Tries Qwen after reclaiming chat memory on a capable GPU. Piper is the basic English CPU fallback; it does not replace requested cloning, voice design or another language."
        ],
        "piper": [
          "Piper | basic English | CPU",
          "Lightweight English text-to-speech on Windows/Linux x64. Needs 3 GiB free RAM; one installed voice. No voice cloning or voice design."
        ],
        "qwen": [
          "Qwen3-TTS | expressive | NVIDIA / Radeon",
          "Multilingual speech, with separate cloning/design tools. Windows/Linux CUDA or compute-probed ROCm: 8 GiB free GPU memory + 6 GiB free RAM (12 GiB on shared Radeon memory). Physical Radeon/Linux GPU speech remains unvalidated."
        ]
      },
      "text_video_engine": {
        "auto": [
          "Automatic, fit this computer",
          "For video-small: short, silent text-to-video on Windows/Linux x64. 256px/17 frames by default; 128\u2013512px and 5\u201333 frames within the pixel budget. Needs 14 GiB free RAM, or 18 GiB with shared memory. No reference image or dialogue."
        ],
        "sdcpp-vulkan": [
          "Wan 1.3B | Radeon / Intel / NVIDIA",
          "For video-small: native Vulkan diffusion with CPU text encoding/decoding. Needs 14 GiB free RAM, or 18 GiB on shared graphics. Standard/experimental alternate follows media preference. Physical Radeon/Intel/Linux generation is unvalidated."
        ],
        "sdcpp-cpu": [
          "Wan 1.3B | CPU | very slow",
          "For video-small: silent text-only clips without GPU acceleration. Windows/Linux x64; 14 GiB available RAM. This does not animate an input image or replace a dialogue/video editing model."
        ]
      },
      "reference_video_profile": {
        "auto": [
          "Automatic, fit this computer",
          "For video: Wan 2.2 on Windows NVIDIA; bounded VACE 1.3B on Windows Radeon or Linux CUDA/ROCm. Requires a supported GPU. Does not substitute a text-only video when an image is supplied."
        ],
        "wan22": [
          "Wan 2.2 | high end | Windows NVIDIA",
          "For video: existing large image-to-video CUDA workflow, intended for the 24 GiB GPU tier. Uses matched standard/alternate motion adapters. Actual free-memory admission still applies. This route is not packaged for Radeon or Linux."
        ],
        "vace13": [
          "VACE 1.3B | Radeon / Linux GPU",
          "For video: bounded image-conditioned clips, 128\u2013320px and up to 17 frames. Windows ROCm or Linux CUDA/ROCm: 8 GiB free GPU memory + 16 GiB free RAM (24 GiB shared). Physical GPU generation remains unvalidated; CPU diagnostic success is not a product CPU route."
        ]
      },
      "music_engine": {
        "auto": [
          "Automatic, fit this computer",
          "For music and score-video: compatible ACE-Step GPU first, then MusicGen CPU for explicitly instrumental 1\u201330s requests. No silent loss of vocals or duration. Rechecks free memory after chat unload. Combined dialogue/editing pipelines retain their task-specific routes."
        ],
        "acestep-service": [
          "ACE-Step full | Windows NVIDIA",
          "Existing Windows CUDA service with its 5Hz language model. Longer songs and lyrics, 1\u2013480 seconds without silent truncation. Needs 8 GiB free CUDA memory and 8 GiB free RAM after chat unload; loaded service models still determine fit. No separate uncensored checkpoint or runtime content filter was found."
        ],
        "acestep-scaled": [
          "ACE-Step turbo | Radeon / Linux GPU",
          "Bounded eight-step diffusion with CPU offloading, no 5Hz language model. Windows ROCm or Linux CUDA/ROCm: 6 GiB free GPU memory + 12 GiB free RAM (20 GiB shared), 10\u201330 seconds. Physical GPU inference remains unvalidated; explicit GPU choices never silently switch to CPU."
        ],
        "musicgen-cpu": [
          "MusicGen Small | CPU | instrumentals",
          "Windows/Linux x64 without a GPU. Needs 10 GiB free RAM after chat unload; 1\u201330 seconds, mono 32 kHz, slow. English prompts work best; no sung lyrics. Local standard weights have no separate runtime prompt filter, not a separately abliterated checkpoint. Weights: CC-BY-NC-4.0 (noncommercial)."
        ]
      }
    },
    "TITLES": {
      "media_variant": "Media models",
      "image_profile": "Images",
      "image_engine": "Image engine",
      "speech_model": "Transcription",
      "voice_engine": "Speech output",
      "text_video_engine": "Text-to-video",
      "reference_video_profile": "Image-to-video",
      "music_engine": "Music / video score"
    }
  }
};

return {CATALOG};
})();
const {PanelState,fixtureSnapshot}=(()=>{
// In-memory presentation state. This module never opens a network connection.
const plain = v => v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;
function object(v, keys) {
  if (!plain(v) || Object.keys(v).some(k => !keys.includes(k))) throw new Error('Unexpected state fields');
}
function string(v, max = 160) { if (typeof v !== 'string' || v.length > max) throw new Error('Invalid text'); return v; }
function integer(v) { if (!Number.isSafeInteger(v) || v < 0) throw new Error('Invalid revision'); return v; }
function choice(v, values) { if (!values.includes(v)) throw new Error('Invalid state value'); return v; }
function array(v, max) { if (!Array.isArray(v) || v.length > max) throw new Error('State list too large'); return v; }
function id(v) { if (typeof v !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(v)) throw new Error('Invalid opaque identifier'); return v; }
function percent(v) { if (typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 100) throw new Error('Invalid percentage'); return v; }

function validateSnapshot(value) {
  object(value, ['version','view','epoch','revision','account','runtime','models','packages','chat','settings']);
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 180000) throw new Error('Snapshot too large');
  if (value.version !== 1) throw new Error('Unsupported state version');
  id(value.view); id(value.epoch); integer(value.revision);
  object(value.account, ['state','displayName']);
  choice(value.account.state, ['ready','locked','switching','closing']); string(value.account.displayName);
  // Locked snapshots carry no private fields, including display names.
  if (value.account.state !== 'ready') {
    if (value.account.displayName !== '' || ['runtime','models','packages','chat','settings'].some(k => k in value)) throw new Error('Private state while locked');
    return structuredClone(value);
  }
  object(value.runtime, ['state','cpu','gpu','memory','model']);
  choice(value.runtime.state, ['idle','starting','ready','sleeping','stopping','unavailable']);
  ['cpu','gpu','memory'].forEach(k => percent(value.runtime[k])); string(value.runtime.model);
  for (const row of array(value.models, 100)) {
    object(row, ['id','name','kind','installed','selected','state']); id(row.id); string(row.name); string(row.kind);
    if (typeof row.installed !== 'boolean' || typeof row.selected !== 'boolean') throw new Error('Invalid model flags');
    choice(row.state, ['ready','sleeping','starting','stopped','unavailable']);
  }
  for (const row of array(value.packages, 100)) {
    object(row, ['id','name','purpose','state']); id(row.id); string(row.name); string(row.purpose, 300);
    choice(row.state, ['available','unavailable','unvalidated']);
  }
  object(value.chat, ['conversations','current','messages','busy','contextUsed','contextLimit','replyCap']);
  if (typeof value.chat.busy !== 'boolean') throw new Error('Invalid busy state');
  id(value.chat.current);
  for (const k of ['contextUsed','contextLimit','replyCap']) integer(value.chat[k]);
  if (value.chat.contextLimit < 1 || value.chat.contextLimit > 1048576 || value.chat.replyCap < 1 || value.chat.replyCap > 32768 || value.chat.contextUsed > value.chat.contextLimit) throw new Error('Invalid context budget');
  const ids = new Set();
  for (const row of array(value.chat.conversations, 100)) {
    object(row, ['id','title','updated']); id(row.id); string(row.title); string(row.updated);
    if (ids.has(row.id)) throw new Error('Duplicate conversation'); ids.add(row.id);
  }
  if (!ids.has(value.chat.current)) throw new Error('Unknown conversation');
  for (const row of array(value.chat.messages, 100)) {
    object(row, ['id','role','text']); id(row.id); choice(row.role, ['user','assistant']); string(row.text, 16000);
  }
  object(value.settings, ['selection','variant','backend','context','reply','effort','media']);
  id(value.settings.selection); choice(value.settings.variant, ['standard','uncensored']);
  choice(value.settings.backend, ['auto','cuda','vulkan','cpu']);
  if (![2048,4096,8192,16384,32768].includes(value.settings.context)) throw new Error('Invalid context');
  integer(value.settings.reply); if (value.settings.reply < 1 || value.settings.reply > 32768) throw new Error('Invalid reply cap');
  choice(value.settings.effort, ['Fast','Balanced','Deep']);
  object(value.settings.media, ['media_variant','image_profile','image_engine','speech_model','voice_engine','text_video_engine','reference_video_profile','music_engine']);
  for (const [key, choices] of Object.entries(CATALOG.media.CHOICES)) choice(value.settings.media[key], Object.keys(choices));
  return structuredClone(value);
}

class PanelState {
  constructor() { this.snapshot = null; this.drafts = new Map(); this.settingsDraft = {}; this.status = 'offline'; this.sequence = -1; }
  receive(value) {
    const next = validateSnapshot(value);
    const old = this.snapshot;
    if (old && old.view === next.view && old.epoch === next.epoch && next.revision <= old.revision) throw new Error('Stale snapshot');
    if (!old || old.view !== next.view || old.epoch !== next.epoch || next.account.state !== 'ready') this.clearPrivate();
    this.snapshot = next;
    this.status = next.account.state === 'ready' ? 'ready' : 'locked';
    return next;
  }
  delta(value) {
    object(value, ['version','view','epoch','baseRevision','revision','runtime']);
    if (!this.snapshot || this.status !== 'ready' || value.version !== 1 || value.view !== this.snapshot.view || value.epoch !== this.snapshot.epoch || value.baseRevision !== this.snapshot.revision || value.revision !== value.baseRevision + 1) {
      this.disconnect('resync'); throw new Error('Fresh snapshot required');
    }
    return this.receive({...this.snapshot, revision: value.revision, runtime: value.runtime});
  }
  clearPrivate() { this.drafts.clear(); this.settingsDraft = {}; this.sequence = -1; }
  disconnect(reason = 'offline') { this.clearPrivate(); this.snapshot = null; this.status = reason; }
  draft(conversation, text) {
    if (this.status !== 'ready' || !this.snapshot.chat.conversations.some(c => c.id === conversation)) throw new Error('No active conversation');
    string(text, 16000); this.drafts.set(conversation, text);
  }
  setting(key, value) {
    if (this.status !== 'ready') throw new Error('No active profile');
    if (![...['selection','variant','backend','context','reply','effort'],...Object.keys(CATALOG.media.CHOICES).map(k => `media.${k}`)].includes(key)) throw new Error('Unknown setting');
    const next = this.settings();
    if (key.startsWith('media.')) next.media[key.slice(6)] = value; else next[key] = value;
    validateSnapshot({...this.snapshot, settings:next});
    this.settingsDraft[key] = value;
  }
  settings() {
    if (!this.snapshot?.settings) return null;
    const next = structuredClone(this.snapshot.settings);
    for (const [key,value] of Object.entries(this.settingsDraft)) {
      if (key.startsWith('media.')) next.media[key.slice(6)] = value; else next[key] = value;
    }
    return next;
  }
  resetSettings() { this.settingsDraft = {}; }
}

function fixtureSnapshot() {
  return {version:1, view:'sample-view', epoch:'sample-epoch', revision:1,
    account:{state:'ready',displayName:'Preview account'},
    runtime:{state:'sleeping',cpu:12,gpu:0,memory:36,model:'Sample chat model'},
    models:[
      {id:'sample-chat',name:'Sample chat model',kind:'Chat · selected',installed:true,selected:true,state:'sleeping'},
      {id:'sample-image',name:'Sample image model',kind:'Image generation',installed:true,selected:false,state:'stopped'},
      {id:'sample-voice',name:'Sample speech model',kind:'Speech output',installed:false,selected:false,state:'unavailable'}],
    packages:[{id:'sample-runtime',name:'Chat runtime',purpose:'Local conversation and tool coordination',state:'available'},
      {id:'sample-images',name:'Image tools',purpose:'Generate and edit images',state:'unvalidated'},
      {id:'sample-science',name:'Scientific workbench',purpose:'Analysis and scientific tools',state:'available'}],
    chat:{conversations:[{id:'sample-hello',title:'A faster way to work',updated:'Sample conversation'},
      {id:'sample-notes',title:'Project notes',updated:'Sample conversation'},
      {id:'sample-ideas',title:'Ideas for later',updated:'Sample conversation'}],current:'sample-hello',busy:false,contextUsed:640,contextLimit:8192,replyCap:2048,
      messages:[{id:'sample-user',role:'user',text:'Can this interface feel responsive without streaming the desktop?'},
        {id:'sample-answer',role:'assistant',text:'Yes. The tabs, menus, scrolling, and message draft run here in your browser.\n\nThis is a sample conversation for the interface preview. Nothing here has been sent to the Aoostar. Try switching pages or changing the theme—your draft stays in place.'}]},
    settings:{selection:'auto',variant:'standard',backend:'auto',context:8192,reply:2048,effort:'Balanced',media:{media_variant:'auto',image_profile:'auto',image_engine:'auto',speech_model:'auto',voice_engine:'auto',text_video_engine:'auto',reference_video_profile:'auto',music_engine:'auto'}}};
}

return {PanelState,fixtureSnapshot};
})();
const {VisibilityGrace}=(()=>{
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

return {VisibilityGrace};
})();
const {PortalAIViewerDemand}=(()=>{
// Import into the CURRENT native/quick-chat/screen cards; do not replace them.
// Construct/connect only after explicit Connect. This never grants control.
class PortalAIViewerDemand {
  constructor(hass, deviceId, kind, onLost = () => {}) {
    if (!['native', 'screen'].includes(kind)) throw new Error('Invalid viewer kind');
    this.hass = hass; this.deviceId = deviceId; this.kind = kind; this.onLost = onLost;
    this.epoch = 0; this.activityEpoch=0; this.timer = null; this.viewer = null; this.connected = false;
  }
  request(action, viewer) {
    return this.hass.callWS({type: 'portalai_projection/viewer', device_id: this.deviceId,
      viewer, kind: this.kind, action});
  }
  async connect() {
    if (this.connected) return;
    if (this.viewer) throw new Error('Viewer connection already pending');
    const epoch = ++this.epoch;
    const viewer = randomId();
    this.viewer = viewer;
    try {
      const result = await this.request('acquire', viewer);
      if (epoch !== this.epoch) { await this.request('release', viewer); return; }
      if (result?.accepted !== true || result.lease_seconds !== 15) throw new Error('Viewer protocol mismatch');
      this.connected = true;
      this.schedule(epoch, viewer);
    } catch (error) {
      await this.request('release', viewer).catch(() => {});
      if (epoch === this.epoch) { this.connected = false; this.viewer = null; }
      throw error;
    }
  }
  schedule(epoch, viewer) {
    const activity=this.activityEpoch;clearTimeout(this.timer);
    this.timer = setTimeout(async () => {
      if (epoch !== this.epoch || activity!==this.activityEpoch || !this.connected || this.backgrounded) return;
      try {
        const result = await this.request('renew', viewer);
        if (epoch !== this.epoch || activity!==this.activityEpoch) return;
        if (result?.accepted !== true || result.lease_seconds !== 15) throw new Error('Viewer lease refused');
        if(!this.backgrounded)this.schedule(epoch, viewer);
      } catch (error) {
        if (epoch !== this.epoch || activity!==this.activityEpoch || this.backgrounded) return;
        this.disconnect(); this.onLost(error);
      }
    }, 5000);
  }
  async background() {
    if(!this.connected||this.backgrounded)return;
    this.backgrounded=true;clearTimeout(this.timer);this.timer=null;
    const epoch=this.epoch,activity=++this.activityEpoch;
    try{await this.request('background',this.viewer);}
    catch(error){if(epoch===this.epoch&&activity===this.activityEpoch){this.disconnect();this.onLost(error);}}
  }
  async foreground() {
    if(!this.connected||!this.backgrounded)return;
    const epoch=this.epoch,viewer=this.viewer,activity=++this.activityEpoch;this.backgrounded=false;
    try{
      const result=await this.request('foreground',viewer);
      if(epoch!==this.epoch||activity!==this.activityEpoch||this.backgrounded)return;
      if(result?.accepted!==true)throw new Error('Viewer lease expired; reconnect');
      this.schedule(epoch,viewer);
    }catch(error){if(epoch===this.epoch&&activity===this.activityEpoch){this.disconnect();this.onLost(error);}}
  }
  disconnect() {
    this.backgrounded=false;
    ++this.activityEpoch;
    ++this.epoch; clearTimeout(this.timer); this.timer = null; this.connected = false;
    const viewer = this.viewer; this.viewer = null;
    if (viewer) return this.request('release', viewer).catch(() => {});
    return Promise.resolve();
  }
}

return {PortalAIViewerDemand};
})();
const {LiveSession}=(()=>{
const PROTOCOL = 'portalai-native-state/2';
const MAX_BYTES = 180000;
const fail = () => { throw new Error('Invalid native state'); };
const fields = (v, keys) => {
  if (!v || Object.getPrototypeOf(v) !== Object.prototype || Object.keys(v).length !== keys.length || keys.some(k => !Object.hasOwn(v,k))) fail();
};
const id = v => { if (typeof v !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(v)) fail(); };
const text = (v, max=160) => { if (typeof v !== 'string' || !v.isWellFormed() || [...v].length > max) fail(); };
const choice = (v, values) => { if (!values.includes(v)) fail(); };
const bool = v => { if (typeof v !== 'boolean') fail(); };
const int = (v, min=0, max=Number.MAX_SAFE_INTEGER) => { if (!Number.isSafeInteger(v) || v < min || v > max) fail(); };
const nullable = (v, min, max) => { if (v !== null) int(v,min,max); };
const rows = v => {
  if (!Array.isArray(v) || v.length > 100) fail();
  const seen = new Set();
  for (const row of v) { id(row?.id); if (seen.has(row.id)) fail(); seen.add(row.id); }
  return v;
};
const budget = v => { if (new TextEncoder().encode(JSON.stringify(v)).byteLength > MAX_BYTES) fail(); };
const binding = v => { fields(v,['view','epoch']); id(v.view); id(v.epoch); };

function validateLiveSnapshot(v) {
  budget(v);
  fields(v.account,['state','displayName']);
  choice(v.account.state,['ready','locked','switching','closing']); text(v.account.displayName);
  const base = ['version','view','epoch','revision','account'];
  fields(v,v.account.state === 'ready' ? [...base,'runtime','models','packages','chat','settings'] : base);
  if (v.version !== 2) fail(); id(v.view); id(v.epoch); int(v.revision);
  if (v.account.state !== 'ready') { if (v.account.displayName !== '') fail(); return structuredClone(v); }
  fields(v.runtime,['state','cpu','gpu','memory','model']);
  choice(v.runtime.state,['idle','starting','ready','sleeping','stopping','unavailable']); text(v.runtime.model);
  for (const k of ['cpu','gpu','memory']) {
    const n=v.runtime[k]; if (n !== null && (typeof n !== 'number' || !Number.isFinite(n) || n < 0 || n > 100)) fail();
  }
  for (const r of rows(v.models)) {
    fields(r,['id','name','kind','installed','selected','state']); text(r.name); text(r.kind); bool(r.installed); bool(r.selected);
    choice(r.state,['ready','sleeping','starting','stopped','unavailable']);
  }
  for (const r of rows(v.packages)) {
    fields(r,['id','name','purpose','state']); text(r.name); text(r.purpose,300); choice(r.state,['available','unavailable','unvalidated']);
  }
  const c=v.chat; fields(c,['conversations','current','messages','busy','contextUsed','contextLimit','replyCap','window']);
  rows(c.conversations); rows(c.messages); bool(c.busy);
  for (const r of c.conversations) { fields(r,['id','title','updated']); text(r.title); text(r.updated); }
  if (c.current === null) { if (c.messages.length || c.busy) fail(); }
  else { id(c.current); if (!c.conversations.some(r => r.id === c.current)) fail(); }
  for (const r of c.messages) { fields(r,['id','role','text','truncated']); choice(r.role,['user','assistant']); text(r.text,16000); bool(r.truncated); }
  nullable(c.contextUsed,0,1048576); nullable(c.contextLimit,1,1048576); nullable(c.replyCap,1,32768);
  if (c.contextUsed !== null && c.contextLimit !== null && c.contextUsed > c.contextLimit) fail();
  fields(c.window,['conversationsComplete','messagesComplete']); bool(c.window.conversationsComplete); bool(c.window.messagesComplete);
  const s=v.settings; fields(s,['selection','variant','backend','context','reply','effort','media']);
  id(s.selection); choice(s.variant,['standard','uncensored']); choice(s.backend,['auto','cuda','vulkan','cpu']);
  choice(s.context,[2048,4096,8192,16384,32768]); int(s.reply,1,32768); choice(s.effort,['Fast','Balanced','Deep']);
  fields(s.media,Object.keys(CATALOG.media.CHOICES));
  for (const [k, values] of Object.entries(CATALOG.media.CHOICES)) choice(s.media[k],Object.keys(values));
  return structuredClone(v);
}

// Only an authenticated HA subscription can establish a view. Data never rebinds it.
class LiveSession {
  constructor({onState,onClear,setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}) {
    Object.assign(this,{onState,onClear,setTimer,clearTimer}); this.ticket=0; this.phase='offline';
  }
  clear(reason='offline') {
    ++this.ticket; this.phase='offline'; this.binding=null; this.generation=null; this.revision=null;
    this.clearTimer(this.timer); this.timer=null;
    this.clearTimer(this.waitTimer); this.waitTimer=null;
    const demand=this.demand; this.demand=null; if(demand)demand.disconnect();
    const unsubscribe=this.unsubscribe; this.unsubscribe=null;
    if (unsubscribe) Promise.resolve().then(unsubscribe).catch(() => {});
    this.onClear(reason);
  }
  async connect(connection,device) {
    this.clear('connecting'); const ticket=this.ticket; this.phase='waiting';
    const demand=new PortalAIViewerDemand({callWS:value=>connection.sendMessagePromise(value)},device,'native',
      ()=>{if(ticket===this.ticket)this.clear('unavailable');});
    this.demand=demand;
    try {
      await demand.connect();
      if(ticket!==this.ticket){await demand.disconnect();return;}
      this.onClear('connecting'); // Public account forms may now request describe.
      await this.waitReady(ticket,connection,device);
    } catch (_) {if(ticket===this.ticket)this.clear('unavailable');}
  }
  async waitReady(ticket,connection,device) {
    if(ticket!==this.ticket)return;
    try {
      const state=await connection.sendMessagePromise({type:'portalai_native/status',device_id:device});
      if(ticket!==this.ticket)return;
      if(state.protocol!==PROTOCOL||state.granted!==true)throw Error('Native read permission required');
      if(state.ready!==true){
        this.waitTimer=this.setTimer(()=>this.waitReady(ticket,connection,device),1000);return;
      }
      // Preserve the existing strict handshake and fresh-state expiry. Presence
      // itself never grants an account view and sends no new snapshot messages.
      this.phase='handshake';this.arm(ticket,10000);
      const unsubscribe=await connection.subscribeMessage(value=>this.receive(ticket,value),{type:'portalai_native/subscribe',device_id:device});
      if(ticket!==this.ticket){await unsubscribe();return;}
      this.unsubscribe=unsubscribe;
    } catch (_) {if(ticket===this.ticket)this.clear('unavailable');}
  }
  arm(ticket,ms) {
    this.clearTimer(this.timer);
    this.timer=this.setTimer(() => { if (ticket === this.ticket) this.clear('expired'); },ms);
  }
  receive(ticket,v) {
    if (ticket !== this.ticket) return;
    try {
      budget(v);
      if (v.protocol !== PROTOCOL) fail();
      if (this.phase === 'handshake') {
        fields(v,['protocol','kind','generation','binding','capabilities','maxFrameBytes','leaseSeconds']);
        if (v.kind !== 'handshake' || v.maxFrameBytes !== MAX_BYTES || v.leaseSeconds !== 10 || !Array.isArray(v.capabilities) || v.capabilities.length !== 1 || v.capabilities[0] !== 'native.state.read') fail();
        id(v.generation); binding(v.binding); this.generation=v.generation; this.binding=structuredClone(v.binding); this.phase='snapshot';
        this.arm(ticket,10000); return;
      }
      if (v.generation !== this.generation) fail();
      if (v.kind === 'invalidate') {
        fields(v,['protocol','kind','generation','reason']); text(v.reason); this.clear('unavailable'); return;
      }
      fields(v,['protocol','kind','generation','snapshot']); if (v.kind !== 'snapshot') fail();
      const s=validateLiveSnapshot(v.snapshot);
      if (s.view !== this.binding.view || s.epoch !== this.binding.epoch || (this.revision !== null && s.revision !== this.revision+1)) fail();
      if (s.account.state !== 'ready') { this.clear('locked'); return; }
      this.revision=s.revision; this.phase='ready'; this.arm(ticket,10000); this.onState(s);
    } catch (_) { this.clear('invalid'); }
  }
}

return {LiveSession};
})();
const {patchMarkup}=(()=>{
// Reconcile application-owned, escaped markup without remounting live elements.
// Never pass unescaped device text or remote HTML to this function.
function patchMarkup(parent, html) {
  const template=document.createElement('template'); template.innerHTML=html;
  const sync=(target,source) => {
    let index=0;
    for (const wanted of [...source.childNodes]) {
      let current=target.childNodes[index];
      // Preserve message/media nodes when the bounded transcript window advances.
      if(wanted.nodeType===Node.ELEMENT_NODE&&wanted.hasAttribute('data-message')){
        const key=wanted.getAttribute('data-message');
        const match=[...target.childNodes].slice(index).find(n=>n.nodeType===Node.ELEMENT_NODE&&n.nodeName===wanted.nodeName&&n.getAttribute('data-message')===key);
        if(match&&match!==current){target.insertBefore(match,current||null);current=match;}
        else if(!match&&current?.getAttribute?.('data-message')!==key){target.insertBefore(wanted.cloneNode(true),current||null);index++;continue;}
      }
      if (!current) target.append(wanted.cloneNode(true));
      else if (current.nodeType!==wanted.nodeType || current.nodeName!==wanted.nodeName) current.replaceWith(wanted.cloneNode(true));
      else if (wanted.nodeType===Node.TEXT_NODE) { if (current.data!==wanted.data) current.data=wanted.data; }
      else if (wanted.nodeType===Node.ELEMENT_NODE) {
        for (const attr of [...current.attributes]) if (!wanted.hasAttribute(attr.name)) current.removeAttribute(attr.name);
        for (const attr of wanted.attributes) if (current.getAttribute(attr.name)!==attr.value) current.setAttribute(attr.name,attr.value);
        // RichChat owns this slot, including expanded records still streaming.
        if (!wanted.hasAttribute('data-rich-pending')) sync(current,wanted);
      }
      index++;
    }
    while (target.childNodes.length>index) target.lastChild.remove();
  };
  sync(parent,template.content);
}

return {patchMarkup};
})();
const {RichChat}=(()=>{
// Versioned on-demand reads. Native-state/2 and its strict validators stay unchanged.
const LIMIT=20*1024*1024, CHUNK=24576, BATCH=262144;
const fail=()=>{throw Error('Invalid rich-chat response');};
const fields=(v,keys)=>{if(!v||Object.getPrototypeOf(v)!==Object.prototype||Object.keys(v).sort().join(' ')!==keys.split(' ').sort().join(' '))fail();};
const id=v=>{if(typeof v!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(v))fail();};
const txt=(v,n)=>{if(typeof v!=='string'||!v.isWellFormed()||[...v].length>n)fail();};
const num=v=>{if(!Number.isSafeInteger(v)||v<0||v>LIMIT)fail();};
const mimes=['image/png','image/jpeg','image/gif','image/webp','audio/wav','audio/mpeg','audio/ogg','audio/flac','video/mp4','video/webm','application/octet-stream'];
function validateRich(reply,p){
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

class RichChat{
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
        const rows=[...this.blocks.values()].filter(b=>b.message===slot.dataset.message&&b.kind===kind);
        let group=slot.groups.get(kind);
        if(!rows.length){if(group){group.remove();slot.groups.delete(kind);}continue;}
        if(!group){group=element('details');group.append(element('summary'));slot.shadowRoot.append(group);slot.groups.set(kind,group);
          group.addEventListener('toggle',()=>{if(group.open){for(const n of group.querySelectorAll('details'))if(n.open)this.load(n.dataset.block,n);}else{for(const m of group.querySelectorAll('audio,video'))m.pause();}});}
        group.querySelector('summary').textContent=({thinking:'Thinking',tool:'Tool calls',media:'Media & attachments'})[kind]+' ('+rows.length+')';
        for(const b of rows){
          let node=this.nodes.get(b.id);
          if(!node){node=element('details');node.dataset.block=b.id;node.append(element('summary'),element('div'));this.nodes.set(b.id,node);
            node.addEventListener('toggle',()=>{if(this.open(node))this.load(b.id,node);else for(const m of node.querySelectorAll('audio,video'))m.pause();});}
          node.querySelector('summary').textContent=b.title+(b.kind==='media'?'':' · '+b.status);
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

return {RichChat};
})();
const {isIPhone,attachmentPickerMarkup,attachmentPickerCSS}=(()=>{
// Deliberately excludes iPad, Android, and narrow desktop windows.
const isIPhone = (userAgent = globalThis.navigator?.userAgent || '') => /\biPhone\b/i.test(userAgent);

// Real file inputs remain mounted and receive the user's tap directly. There is
// no async synthetic click, capture attribute, or browser filesystem API.
const attachmentPickerMarkup = `<section class="iphone-attachments" hidden aria-labelledby="attachment-title">
  <h2 id="attachment-title">Attach a file</h2>
  <p data-attachment-status role="status">Loading attachment controls…</p>
  <p>Select one file at a time, up to 20 MiB. It will be added to the current conversation's pending attachments.</p>
  <label class="attachment-choice"><strong>Photos or videos</strong><span>Choose from your photo library</span><input type="file" accept="image/*,video/*" data-iphone-source="photos" aria-label="Photos or videos" disabled></label>
  <label class="attachment-choice"><strong>Browse files</strong><span>iCloud Drive or On My iPhone</span><input type="file" data-iphone-source="files" aria-label="Browse files: iCloud Drive or On My iPhone" disabled></label>
  <p class="attachment-hint">In Files, tap Browse to choose iCloud Drive or On My iPhone. Canceling the picker leaves your attachments unchanged.</p>
  <button data-command="attachment-back">Back to conversation tools</button>
</section>`;

const attachmentPickerCSS = `.iphone-attachments{padding:8px 0 20px}.iphone-attachments h2{margin-top:0}.attachment-choice{position:relative;display:flex;flex-direction:column;gap:4px;padding:16px;margin:12px 0;min-height:76px;border:1px solid var(--gold-mid,#a87d32);border-radius:12px;background:var(--card,#fff);overflow:hidden}.attachment-choice input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.attachment-choice:focus-within{outline:2px solid var(--accent,#3e91a2);outline-offset:3px}.attachment-choice:has(input:disabled){opacity:.5}.attachment-choice span,.attachment-hint{color:var(--muted,#666)}:host([attachment-only]) .nodes{display:none!important}`;

return {isIPhone,attachmentPickerMarkup,attachmentPickerCSS};
})();
(()=>{
const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid=()=>randomId();
// Keep argument lists small even for the negotiated 1 MiB chunk.
const fileBase64=bytes=>{let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(binary);};
const workflowCSS=`:host{display:block;color:var(--text,#222);font:14px/1.5 'Segoe UI',sans-serif}*{box-sizing:border-box}.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.status{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted,#666)}.nodes{display:flex;flex-wrap:wrap;gap:12px;padding:20px;background:var(--panel,#fff);border:1px solid var(--gold-mid,#a87d32);border-radius:14px}.field{flex:1 1 270px;display:flex;flex-direction:column;gap:6px}.wide,h2,.note,.table{flex:1 1 100%;width:100%}h2{font:600 21px Georgia,serif;margin:12px 0 0}.note{white-space:pre-wrap;overflow-wrap:anywhere}.table{overflow:auto}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid var(--panel3,#ddd);white-space:pre-wrap;overflow-wrap:anywhere}button,input,select,textarea{font:inherit;color:inherit;border:1px solid var(--border-soft,#aaa);border-radius:8px;background:var(--card,#fff);min-height:42px;padding:9px 12px}button{cursor:pointer;background:var(--button,#e6dccb)}button:disabled,input:disabled,select:disabled,textarea:disabled{opacity:.5;cursor:not-allowed}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--accent,#3e91a2);outline-offset:3px}textarea{resize:vertical;min-height:110px}input[type=checkbox]{min-height:auto;width:22px;height:22px}.check{flex-direction:row;align-items:center}.nodes[data-page=controls]>button{flex:1 1 260px;min-height:84px;font-weight:600}.nodes[data-page=controls]>button[data-work-action=controls_stop],button[data-work-action=controls_exit]{color:var(--bad,#a9514c)}[hidden]{display:none!important}[data-drop-field]{border:2px dashed var(--border-soft,#aaa);border-radius:12px;padding:14px}[data-drop-field].drag-over{border-color:var(--accent,#3e91a2);background:var(--panel3,#eee)}.empty{padding:20px;border:1px dashed var(--border-soft,#aaa);border-radius:12px}@media(max-width:600px){.nodes{padding:13px}.field{flex-basis:100%}input,select,textarea{font-size:16px}}`;

class NativeWorkflows extends HTMLElement {
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


})();
const {PortalAINativePanel}=(()=>{

// All markup is application-owned. Every state-derived string is escaped.
const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const asset = name => PANEL_IMAGES[name];
const options = (rows, value) => rows.map(([id, label]) => `<option value="${escape(id)}" ${String(id) === String(value) ? 'selected' : ''}>${escape(label)}</option>`).join('');
const controls = [
  ['Startup','Start the selected components for the signed-in account.'],
  ['System Test','Run the existing system checks and show their results.'],
  ['Full Component Diagnosis','Check individual components with their original test scopes.'],
  ['Minimize to tray','Minimize the PortalAI window on the Aoostar.'],
  ['Stop all components','Cancel active work and stop PortalAI-owned components.'],
  ['Exit PortalAI','Seal the active profile and close PortalAI normally.']
];
const help = {
  start: ['Getting started', '<h2>Your workspace, closer to you.</h2><p>Use the page tabs to explore PortalAI. On a phone in portrait mode, use the page selector above the conversation.</p><p>This preview renders the interface in your browser. It does not capture, stream, or control the Aoostar desktop.</p><h3>Try it</h3><ul><li>Type a message draft, visit Settings, then return to Chat.</li><li>Open Preferences or Memory without waiting for a desktop screenshot.</li><li>Switch the color theme. Your unsent draft stays in place.</li></ul>'],
  connection: ['Connection & security', '<h2>Home Assistant stays in control.</h2><p>The intended connection will carry a limited set of approved PortalAI actions and account-scoped results. The Aoostar will not receive a general Home Assistant login or token.</p><p>The existing projection pairing is not permission for new native actions. The native connection and its specific permissions still need implementation and review on both ends.</p><h3>Current build</h3><p>This build has no network client, command dispatcher, credentials, background worker, or command queue. It cannot start a model or send a message. Sample readings do not describe your computer.</p>'],
  controls: ['Controls', '<h2>The same six controls.</h2><p>Startup, System Test, Full Component Diagnosis, Minimize to tray, Stop all components, and Exit PortalAI match the desktop control names.</p><p>The buttons are disabled until their real handlers are connected. Stopping components and exiting are different operations: normal exit must also finish sealing the active profile.</p><p>The future Stop action needs a separate priority path so a busy generation cannot block it.</p>'],
  chat: ['Chat & settings', '<h2>Draft here. Execute on the Aoostar.</h2><p>Your message draft and preview settings live only in this page’s memory. They are not saved to browser storage. Reloading, simulating disconnect, or closing the page clears them.</p><p>Model selection, media selection, conversation preferences, and generation must retain the desktop’s validation rules. The preview exposes local controls without pretending those changes have been saved.</p><h3>Still on the desktop</h3><p>Attachments, voice, memory editing, conversation branching, account management, and real model operations remain pending. Use the existing desktop view for those operations.</p>'],
  privacy: ['Account & privacy', '<h2>A real PortalAI session is required.</h2><p>Signing into Home Assistant does not sign you into PortalAI. The planned adapter must use the active PortalAI account and reject requests from an old account view.</p><p>On account switch, lock, revocation, or disconnect, the native interface must clear transcripts, account details, drafts, and unsaved settings. Late events from the old connection must be discarded.</p><p>This preview includes only made-up conversations and readings. It has not loaded your accounts or private files.</p>'],
  coverage: ['Preview coverage', '<h2>What you can use here.</h2><p>All eleven pages are represented. Navigation, theme, sample history search, message drafts, settings drafts, help, and local menus work in the browser.</p><p>Every operation that changes the Aoostar is disabled. A visible page is not proof that its underlying workflow has been ported.</p><p>The source handoff maps 49 desktop action entries. Connecting those handlers and verifying their permissions is a separate implementation step. The existing projection remains available during that work.</p>']
};

class PortalAINativePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this.model = new PanelState();
    this.page = 'welcome';
    this.theme = 'light';
    this.subpage = {settings:'chat',persistence:'missions',maintenance:'diagnostics'};
    this.topic = 'start';
    this.conversation = 'sample-hello';
    this.search = '';
    this.historyOpen = false;
    this.dialog = null;
    this.scrolls = new Map();
    this.initialized = false;
    this.shadowRoot.addEventListener('click', e => this.onClick(e));
    this.shadowRoot.addEventListener('input', e => this.onInput(e));
    this.shadowRoot.addEventListener('change', e => this.onChange(e));
    this.shadowRoot.addEventListener('keydown', e => this.onKey(e));
  }
  // Home Assistant custom-panel properties are accepted, but this preview
  // deliberately does not subscribe or send commands through hass.connection.
  set hass(value) { this._hass = value; }
  set panel(value) { this._panel = value; }
  set narrow(value) { this.toggleAttribute('narrow', Boolean(value)); }
  connectedCallback() {
    if (!this.initialized) {
      this.preview = this.hasAttribute('preview');
      if (this.preview) this.model.receive(fixtureSnapshot());
      if (matchMedia('(max-width:640px) and (orientation:portrait)').matches) this.page = 'chat';
      this.initialized = true;
    }
    this.applyTheme();
    this.render();
  }
  disconnectedCallback() { this.model.disconnect(); this.initialized = false; this.search = ''; this.dialog = null; this.scrolls.clear(); }
  get ready() { return this.model.status === 'ready'; }
  get fallback() { return '/portal-ai/portalai'; }
  fallbackLink() { return this.preview ? '' : `<a href="${this.fallback}">Desktop view ↗</a>`; }
  disabled(label, classes = '') { return `<button class="${classes}" disabled title="Requires the native Aoostar connection">${escape(label)}</button>`; }
  heading(title, description, badge = '') { return `<div class="page-heading"><div><h1>${escape(title)}</h1><p>${escape(description)}</p></div>${badge ? `<span class="pill">${escape(badge)}</span>` : ''}</div>`; }
  availability() { return `<div class="availability">${this.preview ? 'Preview only. Changes stay in this browser; Aoostar actions are unavailable.' : 'The native Aoostar connection is not installed. Use the existing desktop view for live operations.'} ${this.fallbackLink()}</div>`; }
  empty(title, description) { return `<div class="empty"><div class="empty-symbol" aria-hidden="true">◇</div><h2>${escape(title)}</h2><p>${escape(description)}</p></div>`; }
  applyTheme() {
    this.setAttribute('theme', this.theme);
    const colors = CATALOG.themes[this.theme === 'dark' ? 'DARK_COLORS' : 'LIGHT_COLORS'];
    for (const [name,value] of Object.entries(colors)) this.style.setProperty(`--${name.replaceAll('_','-')}`, value);
  }
  rememberScroll() {
    for (const key of ['workspace','transcript']) {
      const node = this.shadowRoot.querySelector(`.${key}`);
      if (node) this.scrolls.set(`${this.page}:${this.conversation}:${key}`, node.scrollTop);
    }
  }
  go(page) {
    if (!CATALOG.surfaces.some(s => s.desktop_id === page)) return;
    this.rememberScroll(); this.page = page; this.dialog = null; this.historyOpen = false; this.render();
  }
  render() {
    const active = CATALOG.surfaces.find(s => s.desktop_id === this.page);
    this.shadowRoot.innerHTML = `<style>${PANEL_CSS}</style>
      <div class="app"><header class="masthead"><div class="brand"><img src="${asset('icon.png')}" alt=""><div><div class="wordmark">PortalAI</div><small>Control Center</small></div></div>
      <div class="header-actions"><span class="status-chip"><span class="dot"></span>${this.preview ? 'Local preview' : 'Not connected'}</span>${this.fallbackLink()}<button data-action="theme" class="quiet" aria-label="Switch to ${this.theme === 'light' ? 'dark' : 'light'} theme">${this.theme === 'light' ? '☾ Dark' : '☼ Light'}</button></div></header>
      <nav class="nav" role="tablist" aria-label="PortalAI pages">${CATALOG.surfaces.map(s => `<button role="tab" id="tab-${s.desktop_id}" aria-controls="page-content" tabindex="${this.page === s.desktop_id ? 0 : -1}" aria-selected="${this.page === s.desktop_id}" data-page="${s.desktop_id}">${escape(s.label)}</button>`).join('')}</nav>
      <div class="mobile-nav"><select aria-label="PortalAI page" data-page-select>${options(CATALOG.surfaces.map(s => [s.desktop_id,s.label]), this.page)}</select>${this.fallbackLink()}</div>
      <div class="preview-banner"><strong>${this.preview ? 'SAMPLE DATA' : 'OFFLINE'}</strong><span>${this.preview ? 'Interface preview · no connection to your Aoostar' : 'Native interface preview · awaiting the Aoostar adapter'}</span><button data-action="coverage">What works?</button></div>
      <main class="workspace" id="page-content" role="tabpanel" aria-label="${escape(active.label)}" tabindex="0">${this.pageMarkup()}</main>
      <footer class="footer"><span>${this.preview ? 'Preview account · browser memory only' : 'PortalAI native panel · connection pending'}</span><span>Native UI preview 0.1</span></footer>
      ${this.dialog ? this.dialogMarkup() : ''}</div>`;
    if (this.dialog) {
      for (const child of this.shadowRoot.querySelector('.app').children) if (!child.classList.contains('drawer')) child.inert = true;
    }
    for (const key of ['workspace','transcript']) {
      const node = this.shadowRoot.querySelector(`.${key}`);
      if (node) node.scrollTop = this.scrolls.get(`${this.page}:${this.conversation}:${key}`) || 0;
    }
    if (this.dialog) this.shadowRoot.querySelector('[data-action="close-dialog"]')?.focus();
  }
  pageMarkup() {
    const renderers = {welcome:'welcome',accounts:'accounts',controls:'controlsPage',chat:'chat',activity:'runtime',runtime:'models',installed:'packages',settings:'settingsPage',persistence:'persistence',maintenance:'maintenance',help:'helpPage'};
    return `<section class="page ${this.page === 'chat' ? 'chat-page' : ''}">${this[renderers[this.page]]()}</section>`;
  }
  welcome() {
    return `<div class="hero"><div><div class="eyebrow">Your personal AI workspace</div><h1>PortalAI.<br>Right here.</h1><p>A familiar control center, rendered directly in Home Assistant. Open a conversation, explore your settings, and move between pages without waiting for the desktop.</p><div class="actions"><button class="primary" data-page="chat">Open Chat →</button><button data-page="controls">View controls</button></div></div><img src="${asset('emblem.png')}" alt="PortalAI gold portal emblem"></div>
    <div class="intro-row"><section><h2>Responsive by design</h2><p>Typing, scrolling, menus, and navigation happen locally in your browser.</p></section><section><h2>Familiar workspace</h2><p>The eleven PortalAI pages keep their names and share the desktop’s colors and artwork.</p></section><section><h2>A careful connection</h2><p>The planned adapter sends approved actions to the Aoostar while preserving its isolation.</p></section></div>${this.availability()}`;
  }
  accounts() {
    return `${this.heading('Accounts','Your PortalAI identity stays separate from your Home Assistant login.')}${this.availability()}<div class="two-columns"><section class="ornate"><h2 class="section-title">Current account</h2><dl class="key-values"><dt>Display name</dt><dd>${this.ready ? escape(this.model.snapshot.account.displayName) : 'Not connected'}</dd><dt>Session</dt><dd>${this.preview && this.ready ? 'Sample only' : 'No native session'}</dd><dt>Access</dt><dd>Live permissions unavailable</dd></dl><div class="actions">${this.disabled('Switch account')}${this.disabled('Sign out')}</div></section><section class="ornate"><h2 class="section-title">Account management</h2><p class="muted">Use the PortalAI desktop for sign-in, passwords, enrollment, export, and recovery until those workflows are ported.</p><div class="actions">${this.disabled('Manage accounts')}${this.disabled('Export profile')}</div></section></div><p class="note">This preview does not request or retain a password.</p>`;
  }
  controlsPage() {
    return `${this.heading('Controls','Start, inspect, and close your PortalAI workspace.')}${this.availability()}<div class="control-grid">${controls.map(([label,desc],i) => `<button class="control ${i >= 4 ? 'danger' : ''}" disabled><strong>${label}</strong><span>${desc}</span><em>Connection required</em></button>`).join('')}</div><section class="ornate"><h2 class="section-title">Control log</h2><div class="log"><p>No live activity is connected.</p><p>Completed jobs, failures, and cancellation results will appear here after the adapter is installed.</p></div></section>`;
  }
  historyItems() {
    if (!this.ready) return '';
    const rows = this.model.snapshot.chat.conversations.filter(c => c.title.toLocaleLowerCase().includes(this.search.toLocaleLowerCase()));
    return rows.length ? rows.map(c => `<button class="history-item" aria-current="${this.conversation === c.id}" data-conversation="${escape(c.id)}"><strong>${escape(c.title)}</strong><small>${escape(c.updated)}</small></button>`).join('') : '<p class="small muted">No matching sample conversations.</p>';
  }
  chat() {
    if (!this.ready) return `${this.heading('Chat','A native conversation view for PortalAI.')}${this.availability()}${this.empty('No connected conversation','The Aoostar adapter must provide an authenticated account view before your conversations can appear here.')}${this.preview ? '<div class="actions"><button data-action="restore-preview">Restore sample preview</button></div>' : ''}`;
    const chat = this.model.snapshot.chat;
    const title = chat.conversations.find(c => c.id === this.conversation)?.title || 'Conversation';
    const messages = this.conversation === chat.current ? chat.messages : [];
    return `${this.heading('Chat',title,'Sample conversation')}<div class="chat-layout"><aside class="history ${this.historyOpen ? 'open' : ''}" aria-label="Conversation history"><div class="history-heading">Conversations<button class="quiet mobile-history" data-action="history" aria-label="Close history">×</button></div><input class="search" type="search" maxlength="160" aria-label="Search sample conversations" placeholder="Search conversations" value="${escape(this.search)}" data-search><div class="history-list">${this.historyItems()}</div><footer>Sample history · nothing loaded from the Aoostar</footer></aside>
    <div class="conversation"><div class="chat-toolbar"><button class="mobile-history" data-action="history">☰ History</button>${this.disabled('Edit last','desktop-extra')}${this.disabled('Branch','desktop-extra')}<span class="spacer"></span><button data-dialog="preferences">Preferences</button><button data-dialog="memory">Memory</button><button data-dialog="instructions">Instructions</button><button data-dialog="trace" class="desktop-extra">Trace</button></div>
    <div class="transcript" aria-label="Sample messages">${messages.length ? messages.map(m => `<article class="message ${m.role}"><div class="speaker">${m.role === 'assistant' ? `<img src="${asset('icon.png')}" alt="">PortalAI` : 'You'}</div><p>${escape(m.text)}</p></article>`).join('') : `<div class="chat-intro"><img src="${asset('icon.png')}" alt=""><h2>A little room to think.</h2><p>This sample conversation has no messages. Try a local draft below.</p></div>`}</div>
    <div class="composer"><textarea aria-label="Message draft" maxlength="16000" placeholder="Write a local preview draft…" data-draft>${escape(this.model.drafts.get(this.conversation) || '')}</textarea><div class="actions">${this.disabled('+ Attach')}${this.disabled('Microphone')}<button class="quiet" data-action="clear-draft">Clear draft</button>${this.disabled('Send ↑','primary send')}</div><div class="draft-note">Local draft only. Sending requires the Aoostar connection.</div></div>
    <div class="context-line"><span>Sample context</span><div class="meter" aria-hidden="true"><span style="width:${100*chat.contextUsed/chat.contextLimit}%"></span></div><span>${chat.contextUsed.toLocaleString()} / ${chat.contextLimit.toLocaleString()}</span><span>Reply cap ${chat.replyCap.toLocaleString()}</span></div></div></div>`;
  }
  runtime() {
    const runtime = this.model.snapshot?.runtime;
    return `${this.heading('Runtime','Resource use and component activity.',this.preview ? 'Sample readings' : '')}${this.availability()}${runtime ? `<div class="metrics">${[['CPU','cpu'],['GPU','gpu'],['Memory','memory']].map(([label,key]) => `<section class="metric"><span class="small muted">${label} · sample</span><div class="value">${runtime[key]}<span class="small"> %</span></div><div class="meter" aria-label="Sample ${label} ${runtime[key]} percent"><span style="width:${runtime[key]}%"></span></div></section>`).join('')}</div><section class="ornate"><h2 class="section-title">Chat runtime</h2><dl class="key-values"><dt>Selected model</dt><dd>${escape(runtime.model)}</dd><dt>Activity</dt><dd>${escape(runtime.state)}</dd><dt>Live health</dt><dd>Not connected</dd></dl><p class="note">Selected, installed, loaded, sleeping, and healthy are separate states. These readings are illustrative.</p></section>` : this.empty('No live readings','Resource use will appear after a verified account-scoped connection is available.')}`;
  }
  models() {
    const rows = this.model.snapshot?.models;
    return `${this.heading('Models','See which models are installed, selected, and active.')}${this.availability()}${rows ? `<div class="table-scroll"><table class="data-table"><thead><tr><th>Model</th><th>Installed</th><th>Selected</th><th>Activity</th><th>Action</th></tr></thead><tbody>${rows.map(m => `<tr><td><strong>${escape(m.name)}</strong><small>${escape(m.kind)}</small></td><td>${m.installed ? 'Yes' : 'No'}</td><td>${m.selected ? 'Yes' : 'No'}</td><td><span class="pill">${escape(m.state)}</span></td><td>${this.disabled('Inspect')}</td></tr>`).join('')}</tbody></table></div><p class="note">Sample inventory. Installation or selection alone does not confirm that inference works on this computer.</p>` : this.empty('Model inventory unavailable','The native adapter has not supplied an inventory.')}`;
  }
  packages() {
    const rows = this.model.snapshot?.packages;
    return `${this.heading('Packages','Tools and runtimes available to PortalAI.')}${this.availability()}${rows ? `<div class="table-scroll"><table class="data-table"><thead><tr><th>Package</th><th>Purpose</th><th>Validation</th></tr></thead><tbody>${rows.map(p => `<tr><td><strong>${escape(p.name)}</strong><small>Sample package</small></td><td>${escape(p.purpose)}</td><td><span class="pill">${escape(p.state)}</span></td></tr>`).join('')}</tbody></table></div>` : this.empty('Package inventory unavailable','The native adapter has not supplied a package inventory.')}`;
  }
  subtabs(name, rows) { return `<div class="subtabs" aria-label="${escape(name)} sections">${rows.map(([id,label]) => `<button data-subpage="${name}:${id}" aria-selected="${this.subpage[name] === id}">${label}</button>`).join('')}</div>`; }
  field(key, label, rows, hint = '') {
    const setting = this.model.settings();
    const value = key.startsWith('media.') ? setting.media[key.slice(6)] : setting[key];
    return `<label class="field"><span>${escape(label)}</span><select data-setting="${escape(key)}">${options(rows,value)}</select>${hint ? `<small>${escape(hint)}</small>` : ''}</label>`;
  }
  chatFields(compact = false) {
    const fields = [
      this.field('selection','Chat model',[['auto','Automatic'],['sample-chat','Sample chat model']], 'Preview choices only; no installed model is queried.'),
      this.field('variant','Chat variant',[['standard','Standard'],['uncensored','Uncensored']], 'Choose the variant to use with your chat model.'),
      this.field('context','Context budget',[2048,4096,8192,16384,32768].map(n => [n,n.toLocaleString()])),
      this.field('reply','Reply cap',[512,1024,2048,4096,8192,16384,32768].map(n => [n,n.toLocaleString()])),
      this.field('effort','Thinking effort',['Fast','Balanced','Deep'].map(v => [v,v])),
      this.field('backend','Chat backend',[['auto','Automatic'],['cuda','CUDA'],['vulkan','Vulkan'],['cpu','CPU']])
    ];
    return `<div class="${compact ? '' : 'form-grid'}">${(compact ? fields.slice(2,5) : fields).join('')}</div>`;
  }
  settingsPage() {
    if (!this.ready) return `${this.heading('Settings','Account settings and media defaults.')}${this.availability()}${this.empty('Settings unavailable','Connect a real PortalAI account before loading or editing settings.')}`;
    const media = this.model.settings().media;
    return `${this.heading('Settings','Explore the desktop settings as native browser controls.','Local draft')}${this.availability()}${this.subtabs('settings',[['chat','Chat model and memory'],['media','Media defaults']])}<section class="ornate">${this.subpage.settings === 'chat' ? this.chatFields() : `<div class="form-grid">${Object.entries(CATALOG.media.CHOICES).map(([key,choices]) => this.field(`media.${key}`,CATALOG.media.TITLES[key],Object.entries(choices).map(([id,[label]]) => [id,label])) + `<div class="help-detail" data-media-help="${key}"><strong>From the desktop source</strong><span>${escape(choices[media[key]][1])}</span></div>`).join('')}</div>`}<div class="form-footer"><span class="small muted" data-setting-status>${Object.keys(this.model.settingsDraft).length ? 'Preview changes · not saved to the Aoostar' : 'Sample settings · no changes'}</span><div class="actions"><button data-action="reset-settings">Reset draft</button>${this.disabled('Save settings','primary')}</div></div></section><p class="note">Context budget and reply cap are separate. The connected version must retain model fit checks and the account’s real save rules.</p>`;
  }
  persistence() {
    const missions = this.subpage.persistence === 'missions';
    return `${this.heading('Persistence','Review work that may continue beyond a conversation.')}${this.availability()}${this.subtabs('persistence',[['missions','Missions'],['schedules','Schedules']])}<section class="ornate">${this.empty(missions ? 'Mission state is not connected' : 'Schedule state is not connected',missions ? 'Active, paused, and interrupted missions will be listed here. Resuming work will require an explicit, validated action.' : 'Schedules will show their state and next run. Opening this page must never arm or restart a schedule.')}<div class="actions">${this.disabled(missions ? 'Resume selected mission' : 'Arm selected schedule')}${this.disabled(missions ? 'Stop selected mission' : 'Disarm selected schedule')}${this.disabled('Remove from list')}</div></section>`;
  }
  maintenance() {
    const storage = this.subpage.maintenance === 'storage';
    return `${this.heading('Maintenance','Diagnostics, recovery, and shared storage administration.')}${this.availability()}${this.subtabs('maintenance',[['diagnostics','Diagnostics'],['storage','Storage & recovery']])}<section class="ornate"><h2 class="section-title">${storage ? 'Storage administration' : 'Diagnostic tools'}</h2><p class="muted">${storage ? 'Storage and recovery changes need the real PortalAI administrator checks. No profile, vault, or storage path is available in this preview.' : 'Reports must describe which checks actually ran. A successful structural check must not be presented as a successful live model run.'}</p><div class="actions">${(storage ? ['Storage settings','Profile recovery','Export diagnostics'] : ['System Test','Full Component Diagnosis','View reports']).map(label => this.disabled(label)).join('')}</div></section>`;
  }
  helpPage() { return `${this.heading('Help','A guide to this native interface preview.')}<div class="help-layout"><nav class="help-topics" aria-label="Help topics">${Object.entries(help).map(([id,[label]]) => `<button data-topic="${id}" aria-current="${id === this.topic}">${label}</button>`).join('')}</nav><article class="help-copy">${help[this.topic][1]}</article></div>`; }
  dialogMarkup() {
    const contents = {
      preferences: ['Conversation preferences', `${this.ready ? this.chatFields(true) : '<p>No account is connected.</p>'}<p>These are local preview drafts. Save is unavailable until the Aoostar adapter can validate and persist them.</p>${this.disabled('Save preferences','primary')}`],
      memory: ['Memory', '<p>Persistent memory, recall, and selected memory items will use the existing account permissions.</p><p>No account memory has been loaded. The toggles and item editor will be connected after read-only account state is verified.</p>' + this.disabled('Edit memory')],
      instructions: ['Instructions', '<p>Account instructions have not been loaded. Editing and saving will become available with the authenticated native connection.</p>' + this.disabled('Edit instructions')],
      trace: ['Conversation trace', '<p>No inference, tool call, or model stream is running. The visible conversation is sample data.</p><p>Real traces must be limited to the active account view.</p>'],
      coverage: ['Preview status', '<p><strong>Available:</strong> eleven page shells, theme, sample history search, chat drafts, local settings drafts, and menus.</p><p><strong>Pending:</strong> native Aoostar transport, real account state, generation, streaming, lifecycle commands, history editing, memory, attachments, voice, persistence, and maintenance.</p><p>Browser-local controls can be tested now. No live action is enabled.</p>' + (this.preview ? '<button data-action="disconnect-preview">Simulate disconnect & clear drafts</button>' : '')]
    };
    const [title,body] = contents[this.dialog];
    return `<div class="drawer"><section class="sheet" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><header><h2 id="dialog-title">${title}</h2><button class="quiet" data-action="close-dialog" aria-label="Close dialog">×</button></header>${body}</section></div>`;
  }
  onClick(event) {
    const target = event.target.closest('button');
    if (!target || target.disabled) return;
    if (target.dataset.page) return this.go(target.dataset.page);
    if (target.dataset.conversation) { this.rememberScroll(); this.conversation = target.dataset.conversation; this.historyOpen = false; return this.render(); }
    if (target.dataset.subpage) { const [name,value] = target.dataset.subpage.split(':'); this.subpage[name] = value; return this.render(); }
    if (target.dataset.topic) { this.topic = target.dataset.topic; return this.render(); }
    if (target.dataset.dialog) { this.rememberScroll(); this.dialog = target.dataset.dialog; return this.render(); }
    switch (target.dataset.action) {
      case 'theme': this.theme = this.theme === 'light' ? 'dark' : 'light'; this.applyTheme(); target.textContent = this.theme === 'light' ? '☾ Dark' : '☼ Light'; target.setAttribute('aria-label',`Switch to ${this.theme === 'light' ? 'dark' : 'light'} theme`); break;
      case 'coverage': this.rememberScroll(); this.dialog = 'coverage'; this.render(); break;
      case 'close-dialog': this.closeDialog(); break;
      case 'history': this.historyOpen = !this.historyOpen; this.shadowRoot.querySelector('.history')?.classList.toggle('open',this.historyOpen); break;
      case 'clear-draft': this.model.draft(this.conversation,''); this.shadowRoot.querySelector('[data-draft]').value = ''; break;
      case 'reset-settings': this.model.resetSettings(); this.render(); break;
      case 'disconnect-preview': if (this.preview) { this.model.disconnect(); this.search = ''; this.dialog = null; this.scrolls.clear(); this.render(); } break;
      case 'restore-preview': if (this.preview) { this.model.receive(fixtureSnapshot()); this.conversation = 'sample-hello'; this.render(); } break;
    }
  }
  closeDialog() {
    const previous = this.dialog; this.dialog = null; this.render();
    this.shadowRoot.querySelector(previous === 'coverage' ? '[data-action="coverage"]' : `[data-dialog="${previous}"]`)?.focus();
  }
  onInput(event) {
    if (event.target.matches('[data-draft]')) this.model.draft(this.conversation,event.target.value);
    if (event.target.matches('[data-search]')) { this.search = event.target.value; this.shadowRoot.querySelector('.history-list').innerHTML = this.historyItems(); }
  }
  onChange(event) {
    const target = event.target;
    if (target.matches('[data-page-select]')) return this.go(target.value);
    if (!target.dataset.setting) return;
    const key = target.dataset.setting;
    this.model.setting(key,['context','reply'].includes(key) ? Number(target.value) : target.value);
    const status = this.shadowRoot.querySelector('[data-setting-status]');
    if (status) status.textContent = 'Preview changes · not saved to the Aoostar';
    if (key.startsWith('media.')) {
      const media = key.slice(6);
      const description = this.shadowRoot.querySelector(`[data-media-help="${media}"] span`);
      if (description) description.textContent = CATALOG.media.CHOICES[media][target.value][1];
    }
  }
  onKey(event) {
    if (this.dialog) {
      if (event.key === 'Escape') { event.preventDefault(); this.closeDialog(); }
      if (event.key === 'Tab') {
        const nodes = [...this.shadowRoot.querySelectorAll('.sheet button:not(:disabled),.sheet select,.sheet input,.sheet textarea,.sheet a')];
        const first = nodes[0], last = nodes.at(-1), focused = this.shadowRoot.activeElement;
        if (event.shiftKey && focused === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && focused === last) { event.preventDefault(); first?.focus(); }
      }
      return;
    }
    if (event.target.matches('[role="tab"]') && ['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
      event.preventDefault();
      const surfaces = CATALOG.surfaces;
      let index = surfaces.findIndex(s => s.desktop_id === this.page);
      index = event.key === 'Home' ? 0 : event.key === 'End' ? surfaces.length-1 : (index+(event.key === 'ArrowRight' ? 1 : -1)+surfaces.length)%surfaces.length;
      this.go(surfaces[index].desktop_id);
      this.shadowRoot.querySelector(`#tab-${this.page}`)?.focus();
    }
  }
}
if (!customElements.get('portalai-native-panel')) customElements.define('portalai-native-panel',PortalAINativePanel);

return {PortalAINativePanel};
})();
(()=>{
const esc = v => String(v ?? '').replace(/[&<>"']/g,c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = v => v === null ? 'Unavailable' : v.toLocaleString();

class PortalAILivePanel extends PortalAINativePanel {
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
    this.shadowRoot.querySelector('.footer').innerHTML='<span>Home Assistant controls access · browser memory only</span><span>Native UI 0.5.11 · rich chat</span>';
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
    return `${c.window.messagesComplete ? '' : '<p class="note">Partial transcript · earlier messages are not included.</p>'}${c.messages.length ? c.messages.map(m => `<article class="message ${m.role}" data-message="${m.id}"><div class="speaker">${m.role === 'assistant' ? 'PortalAI' : 'You'}</div><p>${esc(m.text)}</p>${m.truncated ? '<small>Message shortened in this view.</small>' : ''}<portalai-rich-message data-message="${m.id}"></portalai-rich-message></article>`).join('') : '<div class="chat-intro"><h2>No messages in this view.</h2><p>Open a conversation in PortalAI on the Aoostar.</p></div>'}<div data-rich-pending></div>`;
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


})();
