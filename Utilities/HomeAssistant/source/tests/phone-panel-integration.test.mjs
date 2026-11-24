import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

// Small DOM boundary fixture only: panel rendering and command methods below
// are the actual shipping class, not copies/stubs of those methods. No browser,
// microphone, network, credentials or real HA entities are used.
globalThis.HTMLElement = class {};
globalThis.customElements = {get() { return true; }, define() {}};

class Element {
  constructor(tag, attributes = {}) {
    this.tag = tag; this.attributes = attributes; this.dataset = {};
    this.children = []; this.style = {}; this.value = ''; this.disabled = false;
    this.hidden = false; this.textContent = '';
    for (const [key, value] of Object.entries(attributes)) this.setAttribute(key, value);
  }
  setAttribute(key, value) {
    this.attributes[key] = value;
    if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
  }
  matches(selector) {
    const match = /^\[data-([\w-]+)(?:=["']?([^"'\]]+)["']?)?\]$/.exec(selector);
    if (!match) return false;
    const name = match[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    return name in this.dataset && (match[2] === undefined || this.dataset[name] === match[2]);
  }
  closest(selector) { return selector === 'button' && this.tag === 'button' ? this : null; }
  querySelector(selector) { return this.children.find(child => child.matches(selector)) || null; }
  prepend(child) { this.children.unshift(child); }
  append(child) { this.children.push(child); }
  after(child) { this.root.nodes.push(child); }
}

globalThis.document = {hidden: false, createElement: tag => new Element(tag)};
const {PortalAILivePanel} = await import('../web/portalai-live-panel.js');
const {PanelState} = await import('../web/state.js');
const {install} = createRequire(import.meta.url)('../web/phone-voice.cjs');
install(PortalAILivePanel);

function composerFrom(markup) {
  const composer = markup.split('<div class="composer">')[1];
  assert.ok(composer, 'The actual panel must render its composer');
  const actionsMarkup = /<div class="actions">([\s\S]*?)<\/div>/.exec(composer)?.[1];
  assert.ok(actionsMarkup, 'The actual composer must expose its actions');
  const actions = new Element('div');
  for (const match of actionsMarkup.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)) {
    const attributes = Object.fromEntries([...match[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
    const button = new Element('button', attributes); button.textContent = match[2]; actions.append(button);
  }
  const nodes = [];
  for (const name of ['draft', 'chat-notice', 'review-chat']) {
    const selector = name === 'review-chat' ? '[data-action=review-chat]' : `[data-${name}]`;
    assert.match(composer, new RegExp(name === 'review-chat' ? 'data-action="review-chat"' : `data-${name}`));
    nodes.push(new Element(name === 'draft' ? 'textarea' : 'span', name === 'review-chat' ? {'data-action': name} : {[`data-${name}`]: ''}));
  }
  const root = {nodes, querySelector(selector) {
    if (selector === '.composer .actions') return actions;
    return nodes.find(node => node.matches(selector)) || actions.querySelector(selector);
  }};
  actions.root = root;
  return root;
}

test('actual timeline panel hooks add phone control and preserve typed attachment semantics', async () => {
  const panel = Object.create(PortalAILivePanel.prototype);
  panel.model = new PanelState(); panel.model.status = 'ready';
  panel.model.snapshot = {view: 'view', epoch: 'epoch', chat: {
    current: 'chat', busy: false, conversations: [{id: 'chat', title: 'Voice test'}],
    messages: [{id: 'answer', role: 'assistant', text: '<answer>', truncated: false}],
    window: {messagesComplete: true}, contextUsed: 1, contextLimit: 8192, replyCap: 1024,
  }};
  const calls = [];
  Object.assign(panel, {isConnected: true, page: 'chat', conversation: 'chat', actionTicket: 7,
    viewer: 'b'.repeat(32), _panel: {config: {device_id: 'a'.repeat(32)}},
    chatSupported: true, chatAttachmentsSupported: true, attachmentSubmitted: true,
    chatPending: false, chatUncertain: false, chatToolsOpen: false,
    _connection: {async sendMessagePromise(message) {
      calls.push(message); return {accepted: true, request_id: message.request_id, operation: message.operation};
    }},
  });
  const markup = panel.chat();
  assert.ok(markup.indexOf('data-rich-kind="thinking"') < markup.indexOf('&lt;answer&gt;'));
  assert.ok(markup.indexOf('&lt;answer&gt;') < markup.indexOf('data-rich-kind="results"'));
  panel.shadowRoot = composerFrom(markup);
  panel.chatButtons();
  const mic = panel.shadowRoot.querySelector('[data-action=phone-voice]');
  assert.ok(mic); assert.equal(mic.textContent, 'Talk to PortalAI'); assert.equal(mic.disabled, false);
  const draft = panel.shadowRoot.querySelector('[data-draft]');
  draft.value = 'unfinished text'; panel.onInput({target: draft});
  assert.equal(panel.model.drafts.get('chat'), 'unfinished text'); assert.equal(mic.disabled, true);
  draft.value = ''; panel.onInput({target: draft}); assert.equal(mic.disabled, false);

  const guard = {connection: panel._connection, ticket: 7, view: 'view', epoch: 'epoch', chat: 'chat'};
  await panel.sendPhoneText('What lights are on?', guard);
  assert.equal(calls.length, 1); assert.equal(calls[0].type, 'portalai_native/chat');
  assert.deepEqual(calls[0].binding, {view: 'view', epoch: 'epoch'});
  assert.equal(Object.hasOwn(calls[0], 'include_pending_attachments'), false);
  assert.equal(panel.attachmentSubmitted, true, 'Speech must not consume desktop attachments');

  draft.value = 'Here is the attached file'; panel.onInput({target: draft});
  await panel.onClick({target: panel.shadowRoot.querySelector('[data-action=send-chat]')});
  assert.equal(calls.length, 2); assert.equal(calls[1].include_pending_attachments, true);
  assert.equal(panel.attachmentSubmitted, false); assert.equal(draft.value, '');
});
