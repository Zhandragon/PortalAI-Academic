"""Isolated Windows audio/Stop-all probe; no production accounts or model loads."""
import argparse,ast,json,os,queue,shutil,subprocess,sys,threading,time
from pathlib import Path
from unittest.mock import Mock,patch
HERE=Path(__file__).resolve().parent
def prepare(installed, source):
    if source is None:raise ValueError('--source must identify the reviewed ApplicationSources/Windows/PortalAI checkout')
    source=source.resolve()
    root=installed/'Maintenance/Validation/Voice-Stop-r71-20261107/live-fixture'
    root.mkdir(parents=True,exist_ok=False)
    for folder in ('Agent','ControlCenter','Launchers','Tools','Maintenance/Tests'):
        for path in (source/folder).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.json','.txt') and '__pycache__' not in path.parts:
                dest=root/path.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    for path in (installed/'Runtime/BootstrapPython').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            dest=root/path.relative_to(installed);dest.parent.mkdir(parents=True,exist_ok=True);os.link(path,dest)
    for name in ('voice_echo_capture.exe','voice_echo_capture.json'):
        shutil.copy2(installed/'Tools'/name,root/'Tools'/name)
    (root/'Agent/instance-settings.json').write_text(json.dumps({'name':'Voice stop verification','ports':{'qwen':0}}))
    # Exact GUI basename exercises the helper's GUI exclusion in the live process inventory.
    shutil.copy2(__file__,root/'ControlCenter/PortableAI_GUI_probe.py')
    entry=root/'ControlCenter/control_center_bootstrap.py'
    entry.write_text('import runpy\nfrom pathlib import Path\nrunpy.run_path(str(Path(__file__).with_name("PortableAI_GUI_probe.py")),run_name="__main__")\n')
    (root/'Agent/voice_worker.py').write_text('import time\ntime.sleep(120)\n')
    return root

def run(root):
    sys.path[:0]=[str(root/p) for p in ('Agent','ControlCenter','Tools','Maintenance/Tests')]
    import tkinter as tk
    from test_chat_voice import VoiceUITests
    from test_shutdown_lifecycle_tk import gui_callbacks
    from chat_voice import VoiceIO,VoiceStopped
    from voice_echo import EchoCapture
    from writer_jobs import WriterJobs
    import service_manager as service
    from runtime_policy import atomic_json
    fixture=VoiceUITests();fixture.setUp();p=fixture.prepare();app=fixture.app
    app.title('PortalAI · isolated voice-stop verification');app.geometry('760x400+40+40');app.deiconify()
    p._writer_jobs=WriterJobs();p.mic_stream=p.mic_proc=None;p.mic_stop_event=threading.Event()
    p._stop_embedded_media=Mock();p.root=root
    voice=p._conversation_io=VoiceIO(root,lambda:None)
    capture=EchoCapture(root,check=voice.check_capture)
    p.conversation_capture_stream=capture
    state={'active':True,'generation_token':'voice-stop-live-probe','started_at':time.time()}
    atomic_json(root/'Agent/.runtime/qwen_handoff_generation.json',{'token':state['generation_token'],'started_at':state['started_at']})
    restoring=threading.Event();restored=[]
    def speech_finished(*args):
        restoring.set()
        restored.append(service._wait_handoff_ready(state,timeout=40))
    voice.speak=speech_finished
    def conversation():
        try:p._speak_interruptible(voice,'Playback already finished',capture,'Windows AEC')
        except VoiceStopped:pass
        finally:capture.close();voice.cancel()
    p.conversation_thread=p._thread(target=conversation,daemon=True);p.conversation_thread.start()
    assert restoring.wait(2)
    py=root/'Runtime/BootstrapPython/python.exe'
    worker=subprocess.Popen([str(py),str(root/'Agent/voice_worker.py')],creationflags=subprocess.CREATE_NO_WINDOW)
    events=queue.Queue();jobs=WriterJobs();logs=[]
    context=dict(app=app,root=root,native_chat_panel=p,startup_gate=Mock(),control_progress=Mock(),
        _release_chat_audio_before_process_cleanup=p.release_audio_capture,_stop_legacy_openwebui_quiet=lambda:None,
        Path=Path,bootstrap_python=lambda r:str(py),threading=threading,sys=sys,os=os,subprocess=subprocess,
        gui_jobs=jobs,event_q=events,log=logs.append)
    gui_callbacks(context)
    ticks=[];finished=False;result={}
    def tick():
        ticks.append(time.monotonic())
        if not finished:app.after(20,tick)
    app.after(20,tick)
    try:
        p.stop_conversation_mode();context['stop_components']()
        deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            app.update();time.sleep(.01)
            try:kind,data=events.get_nowait()
            except queue.Empty:continue
            if kind=='stop_result':result=data;break
        assert result.get('ok'),result
        assert app.winfo_exists() and worker.poll() is not None
        assert capture.proc.poll() is not None
        p._writer_jobs.close();assert p._writer_jobs.wait(5)['stopped']
        assert restored==[False],restored
        gaps=[b-a for a,b in zip(ticks,ticks[1:])]
        assert len(ticks)>5 and max(gaps)<1.0,(len(ticks),max(gaps,default=0))
        assert not fixture.errors,fixture.errors
        evidence={'passed':True,'root':str(root),'gui_survived':True,'actual_windows_aec_closed':True,
            'actual_stop_helper_passed':True,'owned_worker_terminated':True,'restoration_cancelled_by_stop':True,
            'ticks':len(ticks),'largest_tick_gap_seconds':max(gaps),'production_accounts_opened':False,
            'model_loaded':False,'detail':result['detail']}
        (root.parent/'live-stop-result.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps(evidence),flush=True)
    finally:
        finished=True;voice.request_cancel();capture.close()
        (root/'Agent/.runtime/qwen_handoff_generation.json').unlink(missing_ok=True)
        p.wait_audio_release();p.conversation_thread.join(5)
        p._writer_jobs.close();p._writer_jobs.wait(5);jobs.close();jobs.wait(5)
        if worker.poll() is None:worker.terminate();worker.wait(5)
        fixture.doCleanups()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--prepare',action='store_true');parser.add_argument('--source',type=Path);args=parser.parse_args()
    if args.prepare:print(prepare(args.root,args.source))
    else:run(args.root)
