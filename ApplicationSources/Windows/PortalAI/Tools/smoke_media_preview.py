"""Silent synthetic media UI/HTTP fixture. Never opens an existing account."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'ControlCenter'),str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
from validation_artifacts import ValidationArtifacts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--serve-seconds',type=int,default=0)
    args=parser.parse_args()
    if not 0<=args.serve_seconds<=600:parser.error('Serve time must be 0..600 seconds')
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    synthetic=artifacts.path('fixture-root');output=synthetic/'Outputs';output.mkdir(parents=True,exist_ok=True)
    clip=output/'synthetic-silent.mp4'
    from media_devices import ffmpeg_path
    subprocess.run([str(ffmpeg_path(ROOT)),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i',
        'testsrc2=size=320x180:rate=15','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','8',
        '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(clip)],
        check=True,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    env={k:v for k,v in os.environ.items() if k not in ('PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH')}
    import profile_paths
    env.pop(profile_paths.UID_ENV,None);env.pop(profile_paths.EPOCH_ENV,None)
    with patch.dict(os.environ,{**env,'SDL_AUDIODRIVER':'dummy'},clear=True):
        if args.serve_seconds:
            from media_server import PortableAIOutputHandler
            server=ThreadingHTTPServer(('127.0.0.1',0),partial(PortableAIOutputHandler,
                directory=str(output),portable_root=synthetic,profile_context=None,capability=None))
            timer=threading.Timer(args.serve_seconds,server.shutdown);timer.daemon=True;timer.start()
            print(json.dumps({'synthetic_only':True,'url':f'http://127.0.0.1:{server.server_port}/synthetic-silent.mp4?portal_player=1'}),flush=True)
            try:server.serve_forever(poll_interval=.1)
            finally:timer.cancel();server.server_close()
            return
        import tkinter as tk
        import native_media_player as media
        from smoke_account_panels import capture_window
        from tk_fixture_cleanup import finish_tk_fixture
        app=tk.Tk();app.title('PortalAI synthetic media validation');app.geometry('1000x720+40+40')
        body=tk.Frame(app,bg='#17191c');body.pack(fill='both',expand=True)
        tk.Label(body,text='PortalAI · Synthetic silent media',bg='#17191c',fg='#dfc17b',font=('Georgia',18,'bold')).pack(fill='x',padx=16,pady=16)
        panel=SimpleNamespace(root=synthetic,app=app,_check_login=lambda:None,_closing=False,_thread=threading.Thread,
            COL={'bg':'#17191c','panel2':'#292c30','text':'#ffffff','muted':'#bbbbbb','gold':'#b88a32'})
        original_player,original_probe=media.player_command,media.probe_command
        player=None
        try:
            with patch.object(media,'player_command',side_effect=lambda root,path,title,pos,vol,origin=0:original_player(ROOT,path,title,pos,0,origin)), \
                 patch.object(media,'probe_command',side_effect=lambda root,path:original_probe(ROOT,path)):
                player=media.NativeMediaPlayer(panel,body,clip)
                def pump(seconds):
                    until=time.monotonic()+seconds
                    while time.monotonic()<until:app.update();time.sleep(.02)
                pump(1);player.seek(3);pump(.6);player.toggle();pump(.3)
                shot=capture_window(app,artifacts.path('native-player-dark.png'))
                report={'synthetic_only':True,'production_accounts_opened':False,'silent':True,
                    'duration':player.duration,'position':player.position,'paused':player.paused,'screenshot':shot}
                player.close();report['process_stopped']=player.proc is None;report['reader_stopped']=player.reader is None
                artifacts.path('native-player-report.json').write_text(json.dumps(report,indent=2))
                print(json.dumps(report,indent=2))
        finally:
            if player:player.close();player.widget.destroy()
            player=None;finish_tk_fixture(app)


if __name__=='__main__':main()
