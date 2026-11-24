/* Phone/device microphone -> HA speech-to-text -> the current PortalAI chat.
 * Audio and transcripts stay in memory. No background listening or replay.
 * Uses the existing HA preferred pipeline for STT only (never its agent).
 */
(function () {
  'use strict';
  const SAMPLE_LIMIT = 6000;

  function pcmPacket(handler, samples) {
    if (!Number.isInteger(handler) || handler < 0 || handler > 255) throw Error('Invalid audio channel.');
    const bytes = new Uint8Array(1 + samples.length * 2);
    bytes[0] = handler;
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < samples.length; i++) {
      const v = Math.max(-1, Math.min(1, Number.isFinite(samples[i]) ? samples[i] : 0));
      view.setInt16(1 + i * 2, Math.round(v * (v < 0 ? 32768 : 32767)), true);
    }
    return bytes;
  }

  class PhoneCapture {
    constructor(options) {
      Object.assign(this, options);
      this.closed = false; this.finishing = false; this.handler = null;
      this.transcript = null; this.media = null; this.context = null;
      this.subscription = null; this.timers = new Set(); this.socket = this.connection.socket;
      this.timer = options.timer || setTimeout; this.untimer = options.untimer || clearTimeout;
      this.onVisibility = () => { if (this.visibilityTarget?.hidden) this.cancel('Recording stopped when the app went into the background. Nothing was sent.'); };
      this.visibilityTarget?.addEventListener('visibilitychange', this.onVisibility);
    }
    later(fn, delay) {
      const id = this.timer(() => { this.timers.delete(id); if (!this.closed) fn(); }, delay);
      this.timers.add(id); return id;
    }
    valid() { return !this.closed && this.isCurrent() && this.connection.connected && this.connection.socket === this.socket; }
    state(value) { if (!this.closed) this.onState(value); }
    async start() {
      try {
        if (!this.valid()) throw Error('Connect to the current PortalAI chat first.');
        this.state('starting');
        // Construct/resume within the tap gesture for iOS WebKit audio policy.
        this.context = this.createContext();
        const resume = Promise.resolve(this.context.resume());
        // A permission prompt may outlive a rejected resume promise.
        resume.catch(() => {});
        this.later(() => this.fail('Microphone setup timed out. Tap again when ready.'), 30000);
        const stream = await this.getMedia();
        if (this.closed) { stream.getTracks().forEach(t => t.stop()); return; }
        this.media = stream;
        await resume;
        if (!this.valid()) throw Error('The chat changed. Nothing was sent.');
        this.source = this.context.createMediaStreamSource(stream);
        // ScriptProcessor remains available in iOS WKWebView; the output is
        // silent. It avoids requiring an extra worker URL or CSP exception.
        this.processor = this.context.createScriptProcessor(2048, 1, 1);
        this.gain = this.context.createGain(); this.gain.gain.value = 0;
        this.processor.onaudioprocess = event => {
          if (this.finishing || this.closed || this.handler === null) return;
          if (!this.valid()) { this.cancel('The chat or connection changed. Nothing was sent.'); return; }
          try { this.socket.send(pcmPacket(this.handler, event.inputBuffer.getChannelData(0))); }
          catch { this.fail('Audio connection lost. Nothing was sent to PortalAI.'); }
        };
        this.subscription = this.connection.subscribeMessage(event => this.event(event), {
          type: 'assist_pipeline/run', start_stage: 'stt', end_stage: 'stt',
          input: { sample_rate: this.context.sampleRate }, timeout: 90,
        }, { resubscribe: false });
        await this.subscription;
        if (this.closed) this.unsubscribe();
      } catch (error) {
        const permission = error && ['NotAllowedError', 'PermissionDeniedError'].includes(error.name);
        this.fail(permission ? 'Microphone permission was denied. Allow microphone access for Home Assistant on this device.' : String(error?.message || 'Microphone input is unavailable on this device.'));
      }
    }
    event(event) {
      if (this.closed) return;
      if (!this.valid()) { this.cancel('The chat or connection changed. Nothing was sent.'); return; }
      const data = event.data || {};
      if (event.type === 'run-start') {
        if (this.handler !== null) { this.fail('The transcription session restarted. Nothing was sent.'); return; }
        const handler = data.runner_data?.stt_binary_handler_id;
        if (!Number.isInteger(handler) || handler < 0 || handler > 255) { this.fail('Home Assistant did not provide an audio channel.'); return; }
        this.handler = handler;
        for (const id of this.timers) this.untimer(id); this.timers.clear();
        this.source.connect(this.processor); this.processor.connect(this.gain); this.gain.connect(this.context.destination);
        this.state('listening');
        this.later(() => this.finish(), 45000);
      } else if (event.type === 'stt-vad-end') {
        this.finish();
      } else if (event.type === 'stt-end') {
        const text = data.stt_output?.text;
        if (this.transcript !== null) return;
        if (typeof text !== 'string' || !text.trim() || text.length > SAMPLE_LIMIT) { this.fail('No usable speech was recognized. Nothing was sent to PortalAI.'); return; }
        this.transcript = text.trim(); this.finishing = true; this.closeMedia(); this.state('transcribing');
        this.later(() => this.fail('Transcription did not finish. Nothing was sent to PortalAI.'), 45000);
      } else if (event.type === 'error') {
        this.fail('Home Assistant could not transcribe the recording. Nothing was sent to PortalAI.');
      } else if (event.type === 'run-end') {
        // HA sends run-end before its timeout error. Give that error a turn to
        // arrive; only a completed STT result is eligible for one chat send.
        this.later(() => {
          if (!this.valid() || !this.transcript) { this.fail('Transcription ended without a result. Nothing was sent to PortalAI.'); return; }
          const text = this.transcript;
          this.cleanup();
          this.onText(text);
        }, 150);
      }
    }
    finish() {
      if (this.closed || this.finishing || this.handler === null) return;
      this.finishing = true; this.closeMedia(); this.state('transcribing');
      try {
        if (!this.valid()) throw Error();
        this.socket.send(new Uint8Array([this.handler]));
        this.later(() => this.fail('Transcription timed out. Nothing was sent to PortalAI.'), 45000);
      } catch { this.fail('Audio connection lost. Nothing was sent to PortalAI.'); }
    }
    closeMedia() {
      if (this.processor) { this.processor.onaudioprocess = null; try { this.processor.disconnect(); } catch {} }
      try { this.source?.disconnect(); } catch {}
      try { this.gain?.disconnect(); } catch {}
      this.media?.getTracks().forEach(t => t.stop()); this.media = null;
      if (this.context) { try { Promise.resolve(this.context.close()).catch(() => {}); } catch {} this.context = null; }
    }
    unsubscribe() {
      if (this.subscription) Promise.resolve(this.subscription).then(unsub => unsub()).catch(() => {});
      this.subscription = null;
    }
    cleanup() {
      if (this.closed) return;
      this.closed = true; this.closeMedia(); this.unsubscribe();
      this.visibilityTarget?.removeEventListener('visibilitychange', this.onVisibility);
      for (const id of this.timers) this.untimer(id); this.timers.clear();
      this.transcript = null;
    }
    cancel(message = 'Recording cancelled. Nothing was sent.') {
      if (this.closed) return;
      // Cancel may send an end-of-audio marker to free the STT slot, but drops
      // every resulting transcript and can never submit a chat command.
      if (this.handler !== null && !this.finishing && this.connection.socket === this.socket && this.connection.connected) {
        try { this.socket.send(new Uint8Array([this.handler])); } catch {}
      }
      this.cleanup(); this.onError(message);
    }
    fail(message) { if (!this.closed) { this.cleanup(); this.onError(message); } }
  }

  function install(Panel) {
    const p = Panel.prototype;
    if (p.phoneVoiceVersion) return;
    p.phoneVoiceVersion = '0.1.0';
    p.phoneVoiceCurrent = function (guard) {
      const s = this.model?.snapshot;
      return Boolean(guard && !document.hidden && this.isConnected && this.page === 'chat' &&
        this.ready && this._connection === guard.connection && this.actionTicket === guard.ticket &&
        s?.view === guard.view && s?.epoch === guard.epoch && s?.chat.current === guard.chat &&
        !s.chat.busy && !this.chatPending && !this.chatUncertain && !this.chatToolsOpen &&
        !(this.shadowRoot.querySelector('[data-draft]')?.value || '').trim());
    };
    p.cancelPhoneVoice = function (message) {
      this.phoneCapture?.cancel(message); this.phoneCapture = null; this.phoneGuard = null;
      this.phonePhase = ''; this.phoneVoiceUI();
    };
    p.startPhoneVoice = function () {
      if (this.phoneCapture) { this.phoneCapture.finish(); return; }
      const s = this.model?.snapshot;
      const guard = { connection: this._connection, ticket: this.actionTicket, view: s?.view, epoch: s?.epoch, chat: s?.chat.current };
      if (!this.phoneVoiceCurrent(guard) || !this.chatSupported) { this.phoneNotice = 'Connect to an idle chat and send or clear your draft first.'; this.phoneVoiceUI(); return; }
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !Context) {
        this.phoneNotice = 'Microphone input needs the Home Assistant app or a supported browser over HTTPS.'; this.phoneVoiceUI(); return;
      }
      this.phoneGuard = guard;
      const capture = new PhoneCapture({
        connection: guard.connection,
        visibilityTarget: document,
        isCurrent: () => this.phoneVoiceCurrent(guard),
        createContext: () => new Context(),
        getMedia: () => navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false }),
        onState: state => { this.phonePhase = state; this.phoneNotice = ''; this.chatButtons(); },
        onError: message => { if (this.phoneCapture !== capture) return; this.phoneCapture = null; this.phoneGuard = null; this.phonePhase = ''; this.phoneNotice = message; this.chatButtons(); },
        onText: text => { if (this.phoneCapture === capture) this.sendPhoneText(text, guard); },
      });
      this.phoneCapture = capture; capture.start();
    };
    p.sendPhoneText = async function (text, guard) {
      if (!this.phoneVoiceCurrent(guard) || typeof text !== 'string' || !text.trim() || text.length > SAMPLE_LIMIT ||
          (text.isWellFormed && !text.isWellFormed())) { this.cancelPhoneVoice(); return; }
      this.phoneCapture = null; this.phoneGuard = null; this.phonePhase = 'sending';
      this.phoneNotice = 'Sending recognized speech to PortalAI…'; this.chatPending = true; this.chatButtons();
      try {
        const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
        const request = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
        const result = await guard.connection.sendMessagePromise({
          type: 'portalai_native/chat', device_id: this._panel.config.device_id,
          request_id: request, viewer: this.viewer, operation: 'send',
          binding: { view: guard.view, epoch: guard.epoch }, conversation: guard.chat,
          text, // Intentionally no pending attachment opt-in.
        });
        if (guard.ticket !== this.actionTicket || guard.connection !== this._connection) return;
        if (result.accepted !== true || result.request_id !== request || result.operation !== 'send') throw Error();
        this.phoneNotice = 'Speech sent to PortalAI. Follow the response in this chat.';
      } catch {
        if (guard.ticket !== this.actionTicket || guard.connection !== this._connection) return;
        this.chatUncertain = true;
        this.phoneNotice = 'Delivery is uncertain. Check the chat and device state before repeating the command.';
      } finally {
        if (guard.ticket === this.actionTicket && guard.connection === this._connection) {
          this.chatPending = false; this.phonePhase = ''; this.chatButtons();
        }
      }
    };
    p.phoneVoiceUI = function () {
      const actions = this.shadowRoot?.querySelector('.composer .actions');
      if (!actions) return;
      let mic = actions.querySelector('[data-action="phone-voice"]');
      if (!mic) {
        mic = document.createElement('button'); mic.dataset.action = 'phone-voice';
        mic.title = 'Use the microphone on this phone or device'; actions.prepend(mic);
        const cancel = document.createElement('button'); cancel.dataset.action = 'phone-voice-cancel'; cancel.textContent = 'Cancel recording'; actions.append(cancel);
        const note = document.createElement('p'); note.dataset.phoneVoiceNotice = ''; note.setAttribute('role', 'status');
        note.style.cssText = 'font-size:12px;margin:8px 0;overflow-wrap:anywhere'; actions.after(note);
      }
      const phase = this.phonePhase || '';
      const assistantName = String(this._panel?.config?.phone_voice_name || 'PortalAI').slice(0, 60);
      mic.textContent = ({ starting: 'Opening microphone…', listening: 'Finish & send', transcribing: 'Transcribing…', sending: 'Sending speech…' })[phase] || `Talk to ${assistantName}`;
      mic.setAttribute('aria-label', phase === 'listening' ? `Finish recording and send to ${assistantName}` : `Talk to ${assistantName} using this device microphone`);
      mic.setAttribute('aria-pressed', phase === 'listening' ? 'true' : 'false');
      mic.disabled = phase ? phase !== 'listening' : !this.ready || !this.chatSupported || this.chatPending || this.chatUncertain || this.model.snapshot.chat.busy || this.chatToolsOpen ||
        !(this.model.snapshot.chat.current) || Boolean((this.shadowRoot.querySelector('[data-draft]')?.value || '').trim());
      actions.querySelector('[data-action="phone-voice-cancel"]').hidden = !this.phoneCapture || phase === 'sending';
      const status = this.shadowRoot.querySelector('[data-phone-voice-notice]');
      status.textContent = this.phoneNotice || ({ starting: 'Allow microphone access on this device.', listening: 'Listening on this device. Tap Finish & send when done (45-second limit).', transcribing: 'Microphone stopped. Home Assistant is transcribing your speech.' })[phase] || 'Phone microphone · tap to record, then Finish & send. Uses Home Assistant speech-to-text.';
      if (phase) { const send = actions.querySelector('[data-action="send-chat"]'); if (send) send.disabled = true; }
    };
    for (const name of ['render', 'chatButtons']) {
      const original = p[name]; p[name] = function (...args) { const result = original.apply(this, args); this.phoneVoiceUI(); return result; };
    }
    const accept = p.acceptState;
    p.acceptState = function (...args) { const result = accept.apply(this, args); if (this.phoneCapture && !this.phoneVoiceCurrent(this.phoneGuard)) this.cancelPhoneVoice('The chat changed. Nothing was sent.'); this.phoneVoiceUI(); return result; };
    const clear = p.clearLive;
    p.clearLive = function (...args) { this.cancelPhoneVoice(); this.phoneNotice = ''; this.phonePhase = ''; return clear.apply(this, args); };
    const go = p.go;
    p.go = function (...args) { if (args[0] !== 'chat') this.cancelPhoneVoice(); return go.apply(this, args); };
    const input = p.onInput;
    p.onInput = function (...args) {
      const result = input.apply(this, args);
      if (this.phoneCapture && !this.phoneVoiceCurrent(this.phoneGuard)) this.cancelPhoneVoice('Recording cancelled because the draft changed.');
      this.phoneVoiceUI(); return result;
    };
    const click = p.onClick;
    p.onClick = function (event) {
      const action = event.target.closest('button')?.dataset.action;
      if (action === 'phone-voice') return this.startPhoneVoice();
      if (action === 'phone-voice-cancel') return this.cancelPhoneVoice();
      if (this.phoneCapture && ['chat-tools', 'history', 'open-attachments'].includes(action)) this.cancelPhoneVoice();
      return click.call(this, event);
    };
    const command = p.chatCommand;
    p.chatCommand = function (operation) { if (this.phonePhase && operation === 'send') return; return command.call(this, operation); };
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { PhoneCapture, pcmPacket, install };
  else customElements.whenDefined('portalai-live-panel').then(() => install(customElements.get('portalai-live-panel')));
})();
