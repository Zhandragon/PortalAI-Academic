"""Two actual STT/model/TTS turns through withdrawn Tk, with synthetic audio ingress."""
import json,os,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
ROOT=Path(__file__).with_name('listener-fixture').resolve()
assert json.loads((ROOT/'fixture-manifest.json').read_text())['no_owner_accounts']
assert Path(sys.executable).resolve()==ROOT/'Runtime/BootstrapPython/python.exe'
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Tools','Maintenance/Tests')]
for key in ('PYTHONHOME','PYTHONPATH','PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH','PORTALAI_ACCOUNT_UNLOCK'):os.environ.pop(key,None)
os.environ.update(PORTABLEAI_ROOT=str(ROOT),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',TEMP=str(ROOT/'Cache/tmp'),TMP=str(ROOT/'Cache/tmp'))
from instance_runtime import InstanceSession
session=InstanceSession(ROOT);session.start()
import service_manager as service
from chat_model_switch import prepare_startup
from chat_voice import VoiceIO,VoiceStopped
from piper_bridge import synthesize
import native_chat as chat
from test_chat_voice import VoiceUITests
report={'passed':False,'physical_microphone':False,'human_audibility_confirmed':False,
        'scope':'Actual withdrawn Tk hands-free loop/event pump, NativeChat agent worker, CPU Whisper, local model and Piper/audio-device playback. Synthetic WAV ingress and minimal submission harness; no owner account.', 'order':[]}
test=VoiceUITests();threads=[];worker=None;p=None
try:
    prepare_startup(ROOT,on_status=lambda msg:print(msg,flush=True))
    wav=synthesize('Please say voice controls are ready.',root=ROOT)['files'][0]
    test.setUp();p=test.prepare();p.settings={**chat.DEFAULT_SETTINGS,'max_output_tokens':64,'temperature':0,'conversation_speak_replies':True,'task_progress_enabled':False}
    p.effort=None;p.active_http=chat.ActiveHTTP();p.tool_runtime=chat.ToolRuntime(ROOT,p.settings)
    p.store=SimpleNamespace(profile=chat.CapturedProfile(ROOT),save_session=lambda row:None)
    p.compact_context_if_needed=lambda:False;p.make_thumbnail=lambda path:None
    # A bounded voice-only probe; the separate tool-handoff smoke tests tool use.
    p._completion_overrides={'tools':[],'tool_choice':'none','chat_template_kwargs':{'enable_thinking':False}}
    def messages():
        return [{'role':'system','content':'Answer the user in one short sentence. Do not use tools.'}]+[
            row for item in p.session['messages'] if (row:=p._api_row(item)) is not None],0
    p.api_messages=messages
    def submit():
        text=p.prompt.get('1.0','end-1c').strip();assert text
        p.prompt.delete('1.0','end');p.busy=True;p.cancel_event.clear()
        p.session['messages'].append({'role':'user','content':text,'attachments':[]})
        report['order'].append('submit')
        thread=threading.Thread(target=p.agent_worker,args=(p.session['id'],),daemon=True);threads.append(thread);thread.start()
    p.submit=submit
    class Capture:
        def drain_pending(self):report['order'].append('drain')
        def close(self):report['order'].append('closed')
    capture=Capture();p._mic_candidates=lambda:[{'name':'synthetic public WAV'}]
    p._open_mic_candidate=lambda candidate:(capture,candidate['name'])
    def check():
        if not p.conversation_active.is_set():raise VoiceStopped()
        p.store.profile.check()
    voice=p._conversation_io=VoiceIO(ROOT,check)
    count=[0];spoken=[]
    def capture_one(*args):
        count[0]+=1;report['order'].append('listen')
        if count[0]>2:p.conversation_active.clear();return None
        return Path(wav)
    p._capture_conversation_utterance=capture_one
    real_transcribe=voice.transcribe
    def transcribe(path):
        text=real_transcribe(path);report['order'].append('transcribe');return text
    voice.transcribe=transcribe
    real_speak=voice.speak
    def speak(text):
        real_speak(text);spoken.append(text);report['order'].append('speak')
        print(json.dumps({'spoken_turn':len(spoken),'text':text,'audio_device_playback':True}),flush=True)
    voice.speak=speak
    with patch.object(chat,'WindowsWaveInStream',Capture):
        worker=threading.Thread(target=p._conversation_loop,daemon=True);worker.start()
        deadline=time.monotonic()+300
        while worker.is_alive() and time.monotonic()<deadline:test.pump();time.sleep(.01)
        assert not worker.is_alive(),'Hands-free loop did not complete two turns'
        test.pump()
    text=p.chat.get('1.0','end');assert len(spoken)==2 and all(reply in text for reply in spoken)
    assert [x for x in report['order'] if x!='drain']==['listen','transcribe','submit','speak']*2+['listen','closed'],report['order']
    p._notice.assert_not_called();assert not test.errors
    report.update(passed=True,turns=2,spoken_replies=spoken,visible_replies_verified=True,automatic_listening_resumed=True)
finally:
    if p is not None:
        p.conversation_active.clear();p.cancel_event.set();p.cancel_http()
        if getattr(p,'_conversation_io',None):p._conversation_io.cancel()
    if worker:worker.join(10)
    for thread in threads:thread.join(10)
    test.doCleanups()
    report['cleanup_stopped_pids']=service._stop_qwen_listener();session.close()
    Path(__file__).with_name('handsfree-live-report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
