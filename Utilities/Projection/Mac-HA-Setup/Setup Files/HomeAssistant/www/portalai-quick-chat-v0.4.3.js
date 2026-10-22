// PortalAI quick chat 0.4.3. No credentials or sample state.
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

return {RichChat};
})();
(()=>{
const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const freshId=()=>randomId();
const QUICK_STYLE=`:host{display:block}*{box-sizing:border-box}ha-card{display:block;padding:18px;background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#222);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color,#ddd);font:14px/1.45 var(--paper-font-body1_-_font-family,system-ui)}header{display:flex;align-items:start;gap:12px}header h2{font-size:20px;line-height:1.2;margin:0 0 4px}header p{font-size:12px;color:var(--secondary-text-color,#666);margin:0}header .connection{margin-left:auto}button,textarea{font:inherit}button{min-height:38px;border:1px solid var(--divider-color,#aaa);border-radius:8px;background:transparent;color:inherit;padding:7px 12px;cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}button.primary{color:var(--text-primary-color,#fff);background:var(--primary-color,#167d98);border-color:transparent}button.danger{color:var(--error-color,#b3261e)}button:focus-visible,a:focus-visible,textarea:focus-visible{outline:2px solid var(--primary-color,#167d98);outline-offset:3px}a{color:var(--primary-color,#167d98)}.meta{margin:14px 0 8px;font-size:12px;color:var(--secondary-text-color,#666)}.messages{height:250px;overflow:auto;overscroll-behavior:contain;border:1px solid var(--divider-color,#ddd);border-radius:9px;padding:12px;scrollbar-width:thin}.messages article{margin:0 0 16px;white-space:pre-wrap;overflow-wrap:anywhere}.messages article:last-child{margin-bottom:0}.messages strong{font-size:11px;display:block;margin-bottom:4px}.messages p{margin:0}.messages .user{border-left:3px solid var(--primary-color,#167d98);padding-left:9px}.empty{color:var(--secondary-text-color,#666);padding:14px 0}.compose{margin-top:12px}textarea{display:block;width:100%;resize:vertical;min-height:76px;max-height:200px;padding:10px;border:1px solid var(--divider-color,#aaa);border-radius:8px;background:var(--card-background-color,#fff);color:inherit}.actions{display:flex;align-items:center;gap:8px;margin-top:9px;flex-wrap:wrap}.actions .send{margin-left:auto}.status{font-size:12px;min-height:18px;margin:9px 0 0;overflow-wrap:anywhere}.foot{font-size:11px;color:var(--secondary-text-color,#666);margin:8px 0}.controls{border-top:1px solid var(--divider-color,#ddd);margin-top:12px;padding-top:10px}.controls summary{cursor:pointer}.controls .actions{margin-top:10px}.confirm{padding:12px;background:var(--secondary-background-color,#f4f4f4);border-radius:8px;margin-top:12px}.confirm p{margin:0 0 8px}[hidden]{display:none!important}@media(max-width:420px){ha-card{padding:13px}.messages{height:220px}header h2{font-size:18px}.actions{gap:6px}button{padding:7px 9px}textarea{font-size:16px}}`;

class PortalAIQuickCard extends HTMLElement {
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


})();
