// Deliberately excludes iPad, Android, and narrow desktop windows.
export const isIPhone = (userAgent = globalThis.navigator?.userAgent || '') => /\biPhone\b/i.test(userAgent);

// Real file inputs remain mounted and receive the user's tap directly. There is
// no async synthetic click, capture attribute, or browser filesystem API.
export const attachmentPickerMarkup = `<section class="iphone-attachments" hidden aria-labelledby="attachment-title">
  <h2 id="attachment-title">Attach a file</h2>
  <p data-attachment-status role="status">Loading attachment controls…</p>
  <p>Select one file at a time, up to 20 MiB. It will be added to the current conversation's pending attachments.</p>
  <label class="attachment-choice"><strong>Photos or videos</strong><span>Choose from your photo library</span><input type="file" accept="image/*,video/*" data-iphone-source="photos" aria-label="Photos or videos" disabled></label>
  <label class="attachment-choice"><strong>Browse files</strong><span>iCloud Drive or On My iPhone</span><input type="file" data-iphone-source="files" aria-label="Browse files: iCloud Drive or On My iPhone" disabled></label>
  <p class="attachment-hint">In Files, tap Browse to choose iCloud Drive or On My iPhone. Canceling the picker leaves your attachments unchanged.</p>
  <button data-command="attachment-back">Back to conversation tools</button>
</section>`;

export const attachmentPickerCSS = `.iphone-attachments{padding:8px 0 20px}.iphone-attachments h2{margin-top:0}.attachment-choice{position:relative;display:flex;flex-direction:column;gap:4px;padding:16px;margin:12px 0;min-height:76px;border:1px solid var(--gold-mid,#a87d32);border-radius:12px;background:var(--card,#fff);overflow:hidden}.attachment-choice input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.attachment-choice:focus-within{outline:2px solid var(--accent,#3e91a2);outline-offset:3px}.attachment-choice:has(input:disabled){opacity:.5}.attachment-choice span,.attachment-hint{color:var(--muted,#666)}:host([attachment-only]) .nodes{display:none!important}`;
