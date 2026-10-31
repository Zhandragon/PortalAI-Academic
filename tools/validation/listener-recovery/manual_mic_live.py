"""Actual Whisper transcription into a withdrawn native Mic draft; no model request."""
import json,os,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).with_name('listener-fixture').resolve()
assert json.loads((ROOT/'fixture-manifest.json').read_text())['no_owner_accounts']
assert Path(sys.executable).resolve()==ROOT/'Runtime/BootstrapPython/python.exe'
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Tools','Maintenance/Tests')]
for key in ('PYTHONHOME','PYTHONPATH','PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH','PORTALAI_ACCOUNT_UNLOCK'):os.environ.pop(key,None)
os.environ.update(PORTABLEAI_ROOT=str(ROOT),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',TEMP=str(ROOT/'Cache/tmp'),TMP=str(ROOT/'Cache/tmp'))
from piper_bridge import synthesize
from chat_voice import VoiceIO
from test_chat_voice import VoiceUITests
import native_chat as chat
report={'passed':False,'physical_microphone':False,'scope':'Real CPU Whisper plus native _transcribe_mic and Tk event pump; public synthetic speech input; no chat model needed.'}
test=VoiceUITests();worker=None;p=None
try:
    wav=synthesize('This microphone text should remain in my draft.',root=ROOT)['files'][0]
    test.setUp();p=test.prepare();p.conversation_active.clear()
    p.store=SimpleNamespace(profile=chat.CapturedProfile(ROOT),save_session=lambda row:None)
    p.submit=Mock();voice=p._mic_voice=VoiceIO(ROOT,p.store.profile.check)
    worker=threading.Thread(target=p._transcribe_mic,args=(Path(wav),voice),daemon=True);worker.start()
    deadline=time.monotonic()+180
    while worker.is_alive() and time.monotonic()<deadline:test.pump();time.sleep(.01)
    assert not worker.is_alive(),'Mic transcription did not complete'
    test.pump();text=p.prompt.get('1.0','end').strip()
    assert 'microphone' in text.lower() and 'draft' in text.lower(),text
    assert p._mic_voice is None;p.submit.assert_not_called();p._notice.assert_not_called();assert not test.errors
    report.update(passed=True,text=text,draft_only=True,no_message_sent=True)
finally:
    if p is not None and getattr(p,'_mic_voice',None):p._mic_voice.cancel()
    if worker:worker.join(10)
    test.doCleanups()
    Path(__file__).with_name('manual-mic-live-report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
