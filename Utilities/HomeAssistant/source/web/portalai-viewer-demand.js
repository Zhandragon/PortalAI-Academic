import { randomId, sha256Hex } from './browser-crypto.js';
// Import into the CURRENT native/quick-chat/screen cards; do not replace them.
// Construct/connect only after explicit Connect. This never grants control.
export class PortalAIViewerDemand {
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
