// In-memory presentation state. This module never opens a network connection.
import { CATALOG } from './catalog.js';
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

export function validateSnapshot(value) {
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

export class PanelState {
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

export function fixtureSnapshot() {
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
