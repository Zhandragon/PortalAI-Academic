'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { PhoneCapture, pcmPacket, install } = require('../web/phone-voice.cjs');

function rig(overrides = {}) {
  let clock = 0, id = 0;
  const timers = new Map(), sent = [], errors = [], texts = [], phases = [];
  const media = { stopped: 0, getTracks() { return [{ stop: () => this.stopped++ }]; } };
  const visibility = { hidden: false, listeners: new Set(), addEventListener(_, f) { this.listeners.add(f); }, removeEventListener(_, f) { this.listeners.delete(f); }, hide() { this.hidden = true; for (const f of this.listeners) f(); } };
  const processor = { connect() {}, disconnect() {} };
  const context = { sampleRate: 48000, closed: 0, destination: {}, resume: async () => {}, close() { this.closed++; return Promise.resolve(); },
    createMediaStreamSource: () => ({ connect() {}, disconnect() {} }), createScriptProcessor: () => processor, createGain: () => ({ gain: {}, connect() {}, disconnect() {} }) };
  let callback, unsubscribed = 0, current = true, subscription;
  const connection = { connected: true, socket: { send: value => sent.push(value) },
    subscribeMessage(cb, message, options) { callback = cb; subscription = { message, options }; return Promise.resolve(() => { unsubscribed++; }); } };
  const capture = new PhoneCapture({ connection, visibilityTarget: visibility, isCurrent: () => current, createContext: () => context, getMedia: async () => media,
    onState: state => phases.push(state), onError: err => errors.push(err), onText: text => texts.push(text),
    timer: (fn, ms) => { timers.set(++id, { at: clock + ms, fn }); return id; }, untimer: key => timers.delete(key), ...overrides });
  return { capture, context, connection, media, processor, sent, errors, texts, phases, visibility,
    get subscription() { return subscription; }, get unsubscribed() { return unsubscribed; },
    changeChat() { current = false; },
    event(type, data = {}) { callback({ type, data }); },
    async start() { await capture.start(); callback({ type: 'run-start', data: { runner_data: { stt_binary_handler_id: 3 } } }); },
    advance(ms) { clock += ms; for (const [key, value] of [...timers]) if (value.at <= clock) { timers.delete(key); value.fn(); } },
    audio(samples = [0.5, -0.5]) { processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => Float32Array.from(samples) } }); },
  };
}

test('PCM16 packets clamp, encode signed little-endian and include channel prefix', () => {
  const packet = pcmPacket(7, [0, 1, -1, 9, -9, NaN]);
  assert.equal(packet[0], 7);
  const d = new DataView(packet.buffer);
  assert.deepEqual(Array.from({ length: 6 }, (_, i) => d.getInt16(1 + i * 2, true)), [0, 32767, -32768, 32767, -32768, 0]);
  assert.throws(() => pcmPacket(256, []));
});

test('STT only; actual sample rate; no reconnection replay; one transcript despite duplicate events', async () => {
  const r = rig(); await r.start(); r.audio(); r.capture.finish(); r.capture.finish(); r.audio();
  assert.deepEqual(r.subscription.message, { type: 'assist_pipeline/run', start_stage: 'stt', end_stage: 'stt', input: { sample_rate: 48000 }, timeout: 90 });
  assert.deepEqual(r.subscription.options, { resubscribe: false });
  assert.equal(r.sent.length, 2); assert.deepEqual([...r.sent[1]], [3]);
  assert.equal(r.media.stopped, 1); assert.equal(r.context.closed, 1);
  r.event('stt-end', { stt_output: { text: ' Turn on all the truck lights ' } });
  r.event('stt-end', { stt_output: { text: 'duplicate' } });
  r.event('run-end'); r.event('run-end'); r.advance(150); await Promise.resolve();
  assert.deepEqual(r.texts, ['Turn on all the truck lights']); assert.equal(r.unsubscribed, 1); assert.equal(r.visibility.listeners.size, 0);
});

test('late microphone permission after cancellation closes the granted stream', async () => {
  let grant; const r = rig({ getMedia: () => new Promise(resolve => { grant = resolve; }) });
  const pending = r.capture.start(); r.capture.cancel(); grant(r.media); await pending;
  assert.equal(r.media.stopped, 1); assert.equal(r.context.closed, 1); assert.equal(r.subscription, undefined); assert.equal(r.texts.length, 0);
});

test('permission denial reports a useful message and releases audio', async () => {
  const r = rig({ getMedia: async () => { throw Object.assign(Error(), { name: 'NotAllowedError' }); } });
  await r.capture.start(); assert.match(r.errors[0], /permission was denied/); assert.equal(r.context.closed, 1); assert.equal(r.subscription, undefined);
});

test('backgrounding cancels immediately and ignores completed speech', async () => {
  const r = rig(); await r.start(); r.visibility.hide(); r.event('stt-end', { stt_output: { text: 'turn on lights' } }); r.event('run-end'); r.advance(1000);
  assert.equal(r.media.stopped, 1); assert.equal(r.texts.length, 0); assert.match(r.errors[0], /background/);
});

test('changing chat while transcribing drops the result', async () => {
  const r = rig(); await r.start(); r.capture.finish(); r.changeChat(); r.event('stt-end', { stt_output: { text: 'turn on lights' } }); r.event('run-end'); r.advance(150);
  assert.equal(r.texts.length, 0); assert.match(r.errors[0], /chat or connection changed/);
});

test('replacing the websocket cancels capture without sending to the new socket', async () => {
  const r = rig(); await r.start(); let sends = 0; r.connection.socket = { send() { sends++; } }; r.audio();
  assert.equal(sends, 0); assert.equal(r.texts.length, 0); assert.equal(r.capture.closed, true);
});

test('a timeout error after run-end never sends a transcript', async () => {
  const r = rig(); await r.start(); r.capture.finish(); r.event('stt-end', { stt_output: { text: 'turn on lights' } }); r.event('run-end'); r.event('error', { code: 'timeout' }); r.advance(150);
  assert.equal(r.texts.length, 0); assert.equal(r.errors.length, 1);
});

test('automatic VAD stops microphone; missing run-end has a bounded timeout', async () => {
  const r = rig(); await r.start(); r.event('stt-vad-end'); r.event('stt-end', { stt_output: { text: 'turn on lights' } }); r.advance(45000);
  assert.equal(r.media.stopped, 1); assert.equal(r.texts.length, 0); assert.equal(r.capture.closed, true);
});

test('STT result without VAD also closes capture and times out without run-end', async () => {
  const r = rig(); await r.start(); r.event('stt-end', { stt_output: { text: 'turn on lights' } }); r.advance(45000);
  assert.equal(r.media.stopped, 1); assert.equal(r.texts.length, 0); assert.equal(r.capture.closed, true);
});

test('silent, oversized and incomplete transcription never reach chat', async () => {
  for (const text of ['', ' '.repeat(10), 'a'.repeat(6001)]) {
    const r = rig(); await r.start(); r.event('stt-end', { stt_output: { text } }); r.event('run-end'); r.advance(150); assert.equal(r.texts.length, 0);
  }
  const r = rig(); await r.start(); r.event('run-end'); r.advance(150); assert.equal(r.texts.length, 0); assert.equal(r.capture.closed, true);
});

test('recording limit sends one end marker, then transcription timeout cleans up', async () => {
  const r = rig(); await r.start(); r.advance(45000); assert.deepEqual(r.sent.map(v => [...v]), [[3]]); r.advance(45000);
  assert.equal(r.capture.closed, true); assert.equal(r.texts.length, 0);
});

function panelRig() {
  global.document = { hidden: false };
  class Panel {
    render() {} chatButtons() {} acceptState() {} clearLive() {} go() {} onInput() {} onClick() {} chatCommand() {}
  }
  install(Panel);
  const panel = new Panel(), calls = [], draft = { value: '' };
  const connection = { sendMessagePromise: async message => { calls.push(message); return { accepted: true, request_id: message.request_id, operation: message.operation }; } };
  Object.assign(panel, { isConnected: true, page: 'chat', ready: true, _connection: connection, actionTicket: 5, viewer: 'viewer', _panel: { config: { device_id: 'device' } },
    model: { snapshot: { view: 'view', epoch: 'epoch', chat: { current: 'chat', busy: false } } },
    shadowRoot: { querySelector: s => s === '[data-draft]' ? draft : null }, chatSupported: true });
  const guard = { connection, ticket: 5, view: 'view', epoch: 'epoch', chat: 'chat' };
  return { panel, connection, guard, calls, draft };
}

test('recognized speech uses existing exact chat binding, excluding pending attachments', async () => {
  const r = panelRig(); await r.panel.sendPhoneText('Turn on all the truck lights', r.guard);
  assert.equal(r.calls.length, 1); const call = r.calls[0];
  assert.equal(call.type, 'portalai_native/chat'); assert.equal(call.conversation, 'chat'); assert.deepEqual(call.binding, { view: 'view', epoch: 'epoch' });
  assert.equal(call.text, 'Turn on all the truck lights'); assert.equal('include_pending_attachments' in call, false); assert.match(call.request_id, /^[a-f0-9]{32}$/);
  assert.equal(r.panel.chatPending, false); assert.match(r.panel.phoneNotice, /Speech sent/);
});

test('changed binding, draft, background or busy chat blocks submission', async () => {
  for (const change of [r => r.panel.actionTicket++, r => r.panel.model.snapshot.epoch = 'new', r => r.panel.model.snapshot.chat.current = 'new',
    r => r.draft.value = 'unsent draft', r => r.panel.model.snapshot.chat.busy = true, () => { document.hidden = true; }]) {
    const r = panelRig(); change(r); await r.panel.sendPhoneText('Turn on all the truck lights', r.guard); assert.equal(r.calls.length, 0);
  }
});

test('uncertain command delivery is never retried or presented as completed', async () => {
  const r = panelRig(); r.connection.sendMessagePromise = async message => { r.calls.push(message); throw Error('lost'); };
  await r.panel.sendPhoneText('Turn on all the truck lights', r.guard); await r.panel.sendPhoneText('Turn on all the truck lights', r.guard);
  assert.equal(r.calls.length, 1); assert.equal(r.panel.chatUncertain, true); assert.match(r.panel.phoneNotice, /uncertain/); assert.equal(r.panel.chatPending, false);
});

test('stale acknowledgment cannot update a newly selected account/chat', async () => {
  const r = panelRig(); r.connection.sendMessagePromise = async message => { r.panel.actionTicket++; r.panel.phoneNotice = 'new account'; return { accepted: true, request_id: message.request_id, operation: message.operation }; };
  await r.panel.sendPhoneText('Turn on all the truck lights', r.guard); assert.equal(r.panel.phoneNotice, 'new account');
});
