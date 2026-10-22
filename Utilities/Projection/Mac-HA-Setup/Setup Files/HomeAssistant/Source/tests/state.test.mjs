import test from 'node:test';
import assert from 'node:assert/strict';
import { PanelState, fixtureSnapshot, validateSnapshot } from '../web/state.js';

test('valid state is copied so later producer mutation cannot change the view', () => {
  const source = fixtureSnapshot();
  const model = new PanelState(); model.receive(source);
  source.chat.messages[0].text = 'changed outside the view';
  assert.notEqual(model.snapshot.chat.messages[0].text, source.chat.messages[0].text);
});
test('runtime updates preserve message and settings drafts', () => {
  const model = new PanelState(); model.receive(fixtureSnapshot());
  model.draft('sample-hello','An unfinished thought'); model.setting('effort','Deep');
  model.delta({version:1, view:'sample-view', epoch:'sample-epoch', baseRevision:1, revision:2, runtime:{...model.snapshot.runtime,cpu:19}});
  assert.equal(model.drafts.get('sample-hello'),'An unfinished thought');
  assert.equal(model.settings().effort,'Deep');
  assert.equal(model.snapshot.settings.effort,'Balanced');
  assert.equal(model.snapshot.runtime.cpu,19);
});
test('account switch clears drafts and never merges old private state', () => {
  const model = new PanelState(); model.receive(fixtureSnapshot());
  model.draft('sample-hello','Old account draft'); model.setting('effort','Deep');
  const next = fixtureSnapshot(); next.view = 'another-view'; next.account.displayName = 'Another account';
  model.receive(next);
  assert.equal(model.drafts.size,0); assert.deepEqual(model.settingsDraft,{});
  assert.equal(model.snapshot.account.displayName,'Another account');
});
test('lock clears private state, and locked payloads cannot carry private fields', () => {
  const model = new PanelState(); model.receive(fixtureSnapshot()); model.draft('sample-hello','private');
  const locked = {version:1,view:'sample-view',epoch:'sample-epoch',revision:2,account:{state:'locked',displayName:''}};
  model.receive(locked);
  assert.equal(model.status,'locked'); assert.equal(model.drafts.size,0); assert.equal(model.snapshot.chat,undefined);
  assert.throws(() => validateSnapshot({...locked,chat:fixtureSnapshot().chat}));
  assert.throws(() => validateSnapshot({...locked,account:{state:'locked',displayName:'private name'}}));
  assert.throws(() => model.draft('sample-hello','late text'));
});
test('disconnect clears transcripts, drafts, and staged settings', () => {
  const model = new PanelState(); model.receive(fixtureSnapshot()); model.draft('sample-hello','private'); model.setting('backend','cpu');
  model.disconnect();
  assert.equal(model.snapshot,null); assert.equal(model.drafts.size,0); assert.deepEqual(model.settingsDraft,{});
  assert.throws(() => model.setting('effort','Deep'));
});
test('out-of-order deltas require a fresh snapshot and clear private UI state', () => {
  for (const change of [{baseRevision:0},{view:'old-view'},{epoch:'old-epoch'},{revision:4},{version:2}]) {
    const model = new PanelState(); model.receive(fixtureSnapshot()); model.draft('sample-hello','private');
    assert.throws(() => model.delta({version:1,view:'sample-view',epoch:'sample-epoch',baseRevision:1,revision:2,runtime:model.snapshot.runtime,...change}));
    assert.equal(model.snapshot,null); assert.equal(model.drafts.size,0); assert.equal(model.status,'resync');
  }
});
test('stale snapshots are rejected without rolling back current state', () => {
  const model = new PanelState(); const current = fixtureSnapshot(); current.revision = 3; model.receive(current);
  assert.throws(() => model.receive(fixtureSnapshot()),/Stale/);
  assert.equal(model.snapshot.revision,3);
});
test('invalid schema, unknown command-like fields, numeric identifiers and missing media settings are rejected', () => {
  const mutations = [s => s.shell = 'anything',s => s.view = 12,s => s.runtime.cpu = 101,s => s.chat.busy = 'false',s => s.chat.current = 'unlisted',s => s.settings.media.image_engine = 'unapproved-engine',s => delete s.settings.media.music_engine,s => s.account.permissions = ['admin']];
  for (const mutate of mutations) { const snapshot = fixtureSnapshot(); mutate(snapshot); assert.throws(() => validateSnapshot(snapshot)); }
});
test('payload budget is measured in UTF-8 bytes, including multibyte model output', () => {
  const snapshot = fixtureSnapshot();
  snapshot.chat.messages = Array.from({length:8},(_,i) => ({id:`m${i}`,role:'assistant',text:'界'.repeat(10000)}));
  assert.throws(() => validateSnapshot(snapshot),/too large/);
});
test('settings and drafts are bounded and unknown conversations cannot receive drafts', () => {
  const model = new PanelState(); model.receive(fixtureSnapshot());
  assert.throws(() => model.draft('not-a-conversation','hello'));
  assert.throws(() => model.draft('sample-hello','x'.repeat(16001)));
  assert.throws(() => model.setting('role','admin'));
  assert.throws(() => model.setting('media.unknown','auto'));
  assert.throws(() => model.setting('media.__proto__','auto'));
  assert.throws(() => model.setting('reply',0));
  model.setting('media.image_profile','klein4');
  assert.equal(model.settings().media.image_profile,'klein4');
  model.resetSettings(); assert.equal(model.settings().media.image_profile,'auto');
});
test('context metrics cannot produce zero denominators or unbounded values', () => {
  for (const [key,value] of [['contextLimit',0],['contextLimit',1048577],['replyCap',0],['replyCap',32769]]) {
    const snapshot = fixtureSnapshot(); snapshot.chat[key] = value;
    assert.throws(() => validateSnapshot(snapshot));
  }
});
test('markup-like model output remains plain state text for escaped rendering', () => {
  const snapshot = fixtureSnapshot(); snapshot.chat.messages[1].text = '<img src=x onerror="alert(1)">';
  assert.equal(validateSnapshot(snapshot).chat.messages[1].text,'<img src=x onerror="alert(1)">');
});
