"""Bounded Linux-only guest checks with disposable UI and no real accounts."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import json,os,subprocess,sys,time,traceback

MODULE=Path(__file__).resolve().parents[1];PORTAL=default_target()
sys.path[:0]=[str(MODULE/'app'),str(MODULE/'Runtime/LinuxPackages'),str(PORTAL/'Agent'),str(PORTAL/'ControlCenter')]

def menu_and_close():
    import tkinter as tk
    import threading,tempfile
    from unittest.mock import patch
    from remote_desktop_input import InputAdapter
    from profile_shutdown import _snapshot
    import portalai_target
    portalai_target.configure(PORTAL)
    app=tk.Tk();app.geometry('650x480');chosen=[];closed=[]
    menu=tk.Menu(app,tearoff=False);menu.add_command(label='Disabled',state='disabled',command=lambda:chosen.append(False));menu.add_separator();menu.add_command(label='Synthetic menu action',command=lambda:chosen.append(True))
    app.update();row=_snapshot()[os.getpid()];errors=[];state={}
    def close():closed.append(True);app.destroy()
    app.protocol('WM_DELETE_WINDOW',close)
    with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as folder:
        adapter=InputAdapter(app,folder);manager=portalai_target.Manager(PORTAL);manager.endpoint_dir=Path(folder);manager.inventory=lambda fresh=False:{os.getpid():row}
        def worker():
            try:
                time.sleep(.5);frame=manager.frame({'viewer':'synthetic-linux-viewer'})
                item=manager.windows[frame['window']]
                assert item['class']=='Menu' and frame['native_dialog'],item
                for action in ('move','down','up'):manager.input({'viewer':'synthetic-linux-viewer','window':frame['window'],'event':{'kind':'pointer','action':action,'x':20,'y':state['menu_y']}})
                time.sleep(.25)
                main=next(w for w in manager.windows.values() if w['class']=='TkTopLevel')
                manager.desktop.close(main)
            except Exception:errors.append(traceback.format_exc());state['failed']=True
        def post():
            menu.post(70,70);menu.update();state['menu_y']=int(menu.yposition(2))+8
        def poll():
            if state.get('failed'):app.destroy()
            else:app.after(40,poll)
        app.after(50,post);app.after(100,poll);app.after(120,lambda:threading.Thread(target=worker,daemon=True).start());app.after(12000,app.quit)
        with patch.object(portalai_target,'gui_row',side_effect=lambda root,r:r['pid']==os.getpid()):app.mainloop()
    if errors:raise RuntimeError('\n'.join(errors))
    assert chosen==[True] and closed==[True],(chosen,closed)
    print('Linux owned menu selection and normal WM_DELETE_WINDOW callback passed',flush=True)

def owned_stop():
    from linux_job import prepare_delegation,preflight,LinuxJob
    from profile_shutdown import _snapshot
    from linux_target import stop_owned,gui_row
    from portalai_target import Manager
    prepare_delegation();preflight()
    script=PORTAL/'ControlCenter/control_center_bootstrap.py'
    # The isolated guest contains a deliberately disposable script at the
    # genuine entry path; validate the exact loader mapping and argv contract.
    script.write_text('import time;time.sleep(60)\n')
    process=subprocess.Popen([str(PORTAL/'Runtime/LinuxPython/run-python'),'-B','-I',str(script)])
    manager=Manager(PORTAL,object())
    try:
        time.sleep(.15);row=_snapshot()[process.pid];assert gui_row(PORTAL,row)
        altered={**row,'argv':[str(script)]};assert not gui_row(PORTAL,altered)
        stop_owned(manager,{process.pid:row});process.wait(timeout=3)
        assert process.returncode!=0
    finally:
        if process.poll() is None:process.terminate();process.wait(3)
    # A direct host shell is accepted only inside the root's delegated job.
    worker=subprocess.Popen(['/bin/sh','-c','sleep 60'],stdin=subprocess.DEVNULL)
    job=LinuxJob(worker)
    try:
        rows=_snapshot();selected={pid:r for pid,r in rows.items() if Path(r['group']).is_relative_to(job.group)}
        assert selected
        stop_owned(manager,selected);worker.wait(timeout=3)
    finally:job.close()
    print('Linux exact loader identity, pidfd stop and owned cgroup cancellation passed',flush=True)

def boot_scope():
    import importlib.util,uuid
    from unittest.mock import patch
    from linux_job import delegated_root,current_group
    parent=delegated_root();base=parent/('projection-boot-'+uuid.uuid4().hex);base.mkdir()
    (base/'cgroup.procs').write_text(str(os.getpid()));os.environ['PORTALAI_CGROUP_ROOT']=str(base)
    seen=[]
    spec=importlib.util.spec_from_file_location('projection_boot_fixture',MODULE/'app/projection_boot.py');module=importlib.util.module_from_spec(spec)
    with patch('runpy.run_path',side_effect=lambda path,**kwargs:seen.append(path)):spec.loader.exec_module(module)
    assert seen==[str(MODULE/'app/projection_ui.py')]
    assert current_group()==base/'portalai-controller' and 'memory' in (base/'cgroup.subtree_control').read_text().split()
    print('Companion moves only itself into its controller before enabling delegated memory; GUI then opens',flush=True)

def main():
    if len(sys.argv)>1:
        if sys.argv[1]=='menus':menu_and_close()
        elif sys.argv[1]=='stop':owned_stop()
        elif sys.argv[1]=='boot':boot_scope()
        return
    native=PORTAL/'Runtime/LinuxSystem/rootfs';lib=native/'usr/lib/x86_64-linux-gnu'
    log=(MODULE/'Tests/Validation/xvfb.log').open('wb')
    x=subprocess.Popen([str(lib/'ld-linux-x86-64.so.2'),'--library-path',str(lib),str(native/'usr/bin/Xvfb'),':9','-screen','0','1280x1000x24','-nolisten','tcp','-ac','-extension','GLX','-fp',str(native/'usr/share/fonts/X11/misc')],stdout=log,stderr=log)
    os.environ['DISPLAY']=':9';os.environ['FONTCONFIG_FILE']=str(MODULE/'Runtime/LinuxFonts/fonts.conf')
    checks=[]
    try:
        import tkinter as tk
        for _ in range(50):
            try:app=tk.Tk();app.destroy();break
            except tk.TclError:
                if x.poll() is not None:raise RuntimeError((MODULE/'Tests/Validation/xvfb.log').read_text())
                time.sleep(.1)
        commands=[('protocol',[str(MODULE/'Tests/test_projection.py')]),('outbound',[str(MODULE/'Tests/smoke_outbound_desktop.py')]),('dropdown',[str(MODULE/'Tests/smoke_combobox.py')]),('menus',[str(__file__),'menus']),('stop',[str(__file__),'stop']),('boot',[str(__file__),'boot'])]
        for name,args in commands:
            cp=subprocess.run([str(PORTAL/'Runtime/LinuxPython/run-python'),'-B','-I',*args],capture_output=True,text=True,timeout=55,env=os.environ)
            checks.append({'name':name,'passed':cp.returncode==0,'stdout':cp.stdout[-3000:],'stderr':cp.stderr[-4500:]})
            print('PROJECTION_LINUX_CHECK='+json.dumps(checks[-1]),flush=True)
        # Real companion UI constructs using its own interpreter and packages.
        cp=subprocess.run([str(MODULE/'Runtime/LinuxPython/run-python'),'-B','-I','-c',
            "import sys,tkinter as tk;sys.path.insert(0,'/PortalAI-Projection/app');from projection_ui import Window;r=tk.Tk();w=Window(r);r.update();assert r.winfo_width()>=620;r.destroy();print('Companion UI and bundled Tk passed')"],capture_output=True,text=True,timeout=15)
        checks.append({'name':'companion-ui','passed':cp.returncode==0,'stdout':cp.stdout,'stderr':cp.stderr})
    except Exception:checks.append({'name':'guest','passed':False,'error':traceback.format_exc()})
    finally:
        x.terminate();x.wait(5);log.close()
        print('PROJECTION_LINUX_RESULT='+json.dumps({'passed':bool(checks) and all(c['passed'] for c in checks),'checks':checks,'physical_linux':False,'ha_green':False}),flush=True)

if __name__=='__main__':main()
