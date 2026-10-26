"""Native minimize with the real drop hook; current tray callback routing."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[2]

def callbacks(context,names):
    tree=ast.parse((ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8'))
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    class Bind(ast.NodeTransformer):
        def visit_Nonlocal(self,node):return ast.copy_location(ast.Global(names=node.names),node)
    nodes=[Bind().visit(n) for n in main.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==len(names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<launcher-window-callbacks>','exec'),context)
    return context


def native_probe():
    """A separate process is required: the old synchronous call aborts Python."""
    import ctypes,time,tkinter as tk
    from ctypes import wintypes
    sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
    from native_chat import WindowsFileDrop
    app=tk.Tk();app.geometry('320x180+20+20');app.overrideredirect(True)
    target=tk.Frame(app);target.pack(fill='both',expand=True);app.update()
    drop=WindowsFileDrop(app,target,lambda _paths:None)
    assert drop.enabled,'Explorer drop hook was not installed'
    u=ctypes.WinDLL('user32',use_last_error=True)
    u.GetParent.argtypes=[wintypes.HWND];u.GetParent.restype=wintypes.HWND
    u.IsIconic.argtypes=[wintypes.HWND];u.IsIconic.restype=wintypes.BOOL
    def hwnd():return u.GetParent(app.winfo_id()) or app.winfo_id()
    context=dict(app=app,use_custom_chrome=True,_custom_hwnd=hwnd,
                 _ensure_custom_taskbar_style=lambda:None,log=lambda *_:None)
    callbacks(context,{'_iconify_custom'})
    errors=[];cycles=[]
    app.report_callback_exception=lambda typ,val,tb:errors.append(str(val))
    def minimize():
        assert context['_iconify_custom']()
        app.after(60,restore)
    def restore():
        cycles.append(bool(u.IsIconic(hwnd())))
        app.deiconify();app.state('normal')
        if len(cycles)<12:app.after(60,minimize)
        else:app.after(60,finish)
    def finish():
        drop.close();app.destroy()
    app.after(60,minimize);app.after(10000,finish);app.mainloop()
    assert len(cycles)==12 and all(cycles),(cycles,errors)
    assert not errors,errors
    print(json.dumps({'passed':True,'minimize_restore_cycles':len(cycles),'real_drop_hook':True}))


class WindowMinimizeTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows message pump test')
    def test_real_drop_subclass_survives_repeated_taskbar_minimize(self):
        result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__)),'--native-probe'],
            capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    def test_tray_fallback_uses_the_same_safe_taskbar_path(self):
        app=Mock();tray=Mock();tray.show.return_value=False
        c=dict(app=app,tray=tray,os=Mock(name='os'),exit_in_progress=False,account_gate=None,
               tray_hidden=False,restore_from_tray=Mock(),_iconify_custom=Mock(return_value=True),log=Mock())
        c['os'].name='nt';callbacks(c,{'minimize_to_tray'})['minimize_to_tray']()
        c['_iconify_custom'].assert_called_once();app.iconify.assert_not_called();app.withdraw.assert_not_called()

    def test_unavailable_window_does_not_recurse_or_hide_window(self):
        app=Mock();app._portalai_main_ready=True
        c=dict(app=app,use_custom_chrome=True,_custom_hwnd=lambda:None,log=Mock(),minimize_to_tray=Mock())
        callbacks(c,{'_iconify_custom'})
        self.assertFalse(c['_iconify_custom']());c['minimize_to_tray'].assert_not_called();app.withdraw.assert_not_called()

    def test_current_tray_menu_routes_every_action(self):
        names=['restore_from_tray','show_tab','show_help_topic','open_account_missions','start_components',
               'run_system_test','diagnose','open_maintenance_folder','toggle_theme','stop_components','begin_exit_portableai']
        c={name:Mock() for name in names}
        c.update(exit_in_progress=False,account_gate=None,native_chat_panel=Mock(),theme_mode='dark',_portableai_popup=Mock())
        callbacks(c,{'_menu_item','show_tray_context_menu'})
        c['show_tray_context_menu'](10,20)
        items={x['label']:x for x in c['_portableai_popup'].show.call_args.args[2] if x}
        pages={'Open Chat':'chat','Accounts':'accounts','Controls':'controls','Runtime':'activity','Models':'runtime',
               'Packages':'installed','Settings':'settings','Maintenance':'maintenance'}
        actions={'Open Control Center':'restore_from_tray','Startup':'start_components','System Test':'run_system_test',
                 'Full Component Diagnosis':'diagnose','Open Maintenance Reports':'open_maintenance_folder',
                 'Switch to Light mode':'toggle_theme','Stop all components':'stop_components','Exit PortalAI':'begin_exit_portableai',
                 'Persistence':'open_account_missions'}
        self.assertEqual(set(items),set(pages)|set(actions)|{'New Chat','Documentation / Help'})
        for label,page in pages.items():
            c['show_tab'].reset_mock();c['restore_from_tray'].reset_mock();items[label]['command']()
            c['show_tab'].assert_called_once_with(page);c['restore_from_tray'].assert_called_once()
        for label,method in actions.items():
            c[method].reset_mock();items[label]['command']();c[method].assert_called_once()
        items['New Chat']['command']();c['native_chat_panel'].new_chat.assert_called_once()
        items['Documentation / Help']['command']();c['show_help_topic'].assert_called_once_with('quick_start')
        c['_portableai_popup'].reset_mock();c['exit_in_progress']=True
        c['show_tray_context_menu'](10,20);c['_portableai_popup'].show.assert_not_called()

if __name__=='__main__':
    if '--native-probe' in sys.argv:native_probe()
    else:unittest.main()
