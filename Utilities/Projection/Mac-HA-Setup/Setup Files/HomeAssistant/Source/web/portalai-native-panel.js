import { CATALOG } from './catalog.js';
import { PanelState, fixtureSnapshot } from './state.js';

// All markup is application-owned. Every state-derived string is escaped.
const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const asset = name => new URL(`./assets/${name}`, import.meta.url).href;
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

export class PortalAINativePanel extends HTMLElement {
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
    this.shadowRoot.innerHTML = `<link rel="stylesheet" href="${new URL('./panel.css',import.meta.url).href}">
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
