"""Run inside the offline Linux packaging guest only."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

ROOT=Path('/portable');sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Runtime/LinuxPackages/gui')]


def main():
    report={'passed':False,'checks':[]};x=None
    try:
        from platform_runtime import ffmpeg_path
        for executable in (ffmpeg_path(ROOT),ffmpeg_path(ROOT,True),ROOT/'Runtime/QEMU/linux-x64/bin/qemu-system-x86_64'):
            cp=subprocess.run([str(executable),'-version' if 'qemu' not in executable.name else '--version'],capture_output=True,timeout=20)
            if cp.returncode:raise RuntimeError(executable.name+': '+cp.stderr.decode(errors='replace')[-1600:])
            report['checks'].append({'name':executable.name,'output':cp.stdout.decode(errors='replace').splitlines()[0]})
        native=ROOT/'Runtime/LinuxSystem/rootfs';lib=native/'usr/lib'
        loader=lib/'x86_64-linux-gnu/ld-linux-x86-64.so.2';libpath=str(lib/'x86_64-linux-gnu')+':'+str(lib)
        xlog=(ROOT/'Data/xvfb.log').open('wb')
        x=subprocess.Popen([str(loader),'--library-path',libpath,str(native/'usr/bin/Xvfb'),':9','-screen','0','1280x900x24',
                            '-nolisten','tcp','-ac','-extension','GLX','-fp',str(native/'usr/share/fonts/X11/misc')],stdout=xlog,stderr=xlog)
        os.environ['DISPLAY']=':9';os.environ['FONTCONFIG_PATH']=str(native/'etc/fonts')
        import tkinter as tk
        for attempt in range(40):
            try:app=tk.Tk();app.destroy();break
            except tk.TclError:
                if x.poll() is not None:raise RuntimeError((ROOT/'Data/xvfb.log').read_text())
                time.sleep(.1)
        original=tk.Tk.mainloop
        def inspect(app,*args,**kwargs):
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:app.update();time.sleep(.05)
            labels=[]
            def scan(widget):
                try:
                    text=widget.cget('text')
                    if text:labels.append(str(text))
                except tk.TclError:pass
                for child in widget.winfo_children():scan(child)
            scan(app)
            report['checks'].append({'name':'original-themed-gui','widgets_with_text':len(labels),'tabs':[s for s in labels if s.lower() in ('controls','installed','settings','runtime','help')]})
            if len(labels)<25:raise RuntimeError('GUI did not construct its normal pages')
            app.destroy()
        tk.Tk.mainloop=inspect
        sys.argv=['PortableAI_GUI.py','--root',str(ROOT)]
        runpy.run_path(str(ROOT/'ControlCenter/PortableAI_GUI.py'),run_name='__main__')
        report['passed']=True
    except BaseException as exc:
        if isinstance(exc,SystemExit) and exc.code in (None,0) and any(x['name']=='original-themed-gui' for x in report['checks']):report['passed']=True
        else:
            import traceback
            report['error']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        if x and x.poll() is None:x.terminate();x.wait(timeout=5)
        print('PORTAL_PACKAGING_RESULT='+json.dumps(report),flush=True)

if __name__=='__main__':main()
