"""Real hidden worker, browser and owned-job tests in a disposable workspace."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from web_tool_api import WebClient

PROBE=r'''
import ctypes,json,sys
from pathlib import Path
source=Path(SOURCE_ROOT)
sys.path[:0]=[str(source/'Agent'),str(source/'ControlCenter')]
from web_capabilities import WebSession
class Profile:
    def check(self):pass
    def private(self,name):return Path(__file__).parent/name
init=json.loads(sys.stdin.readline())
session=WebSession(source,Profile(),init['role'])
try:
    for line in sys.stdin:
        request=json.loads(line)
        if request['action']=='browser':
            session._start()
            page=session.context.new_page()
            page.set_content('<title>Hidden worker fixture</title><h1>Ready</h1>')
            result={'title':page.title()}
        else:
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.GetConsoleWindow.restype=ctypes.c_void_p
            result={'console_window':int(kernel.GetConsoleWindow() or 0),'echo':request.get('text')}
        print(json.dumps({'ok':True,'result':result}),flush=True)
finally:session.close()
'''

@unittest.skipUnless(os.name=='nt','Windows console regression')
class HiddenWebWorker(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'Agent').mkdir()
        (self.root/'Agent/web_worker.py').write_text(PROBE.replace('SOURCE_ROOT',repr(str(ROOT))),encoding='utf-8')
        profile=SimpleNamespace(check=lambda:None)
        runtime=SimpleNamespace(root=self.root,boot=ROOT/'Runtime/BootstrapPython/python.exe',profile=profile,
                                _account_role=lambda:'admin',_cancel_epoch=0)
        self.client=WebClient(runtime)
        env=dict(os.environ)
        for key in list(env):
            if key.startswith('PORTALAI_') or key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'):env.pop(key)
        env['TEMP']=env['TMP']=str(self.root)
        self.env=patch('native_chat.clean_env',return_value=env)
        self.env.start()

    def tearDown(self):
        try:self.client.close()
        finally:self.env.stop();self.temp.cleanup()

    def test_console_free_worker_keeps_pipes_and_reuses_owned_process(self):
        real_popen=subprocess.Popen
        with patch('web_tool_api.subprocess.Popen',wraps=real_popen) as launch:
            first=json.loads(self.client.call('probe',{'text':'Unicode: café 日本語'}))
            self.assertEqual(first['result'],{'console_window':0,'echo':'Unicode: café 日本語'})
            process=self.client.process
            second=json.loads(self.client.call('probe',{'text':'second'}))
            self.assertEqual(second['result']['console_window'],0)
            self.assertIs(process,self.client.process)
            launch.assert_called_once()
            options=launch.call_args.kwargs
            self.assertTrue(options['creationflags'] & subprocess.CREATE_NO_WINDOW)
            self.assertFalse(options.get('shell',False))
            self.assertIsNotNone(self.client.job.handle)
        self.client.close()
        self.assertIsNotNone(process.poll())
        self.assertIsNone(self.client.job)

    def test_headless_browser_has_no_visible_owned_windows_and_stop_closes_tree(self):
        result=json.loads(self.client.call('browser',{}))
        self.assertEqual(result['result']['title'],'Hidden worker fixture')
        job=self.client.job
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        from ctypes import wintypes as w
        kernel.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD)]
        buffer=ctypes.create_string_buffer(65536)
        self.assertTrue(kernel.QueryInformationJobObject(job.handle,3,buffer,len(buffer),None))
        count=ctypes.c_uint32.from_buffer(buffer,4).value
        pids=list((ctypes.c_size_t*count).from_buffer(buffer,8))
        self.assertGreaterEqual(len(pids),3,'Expected worker, Playwright driver and Chromium')
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.IsWindowVisible.argtypes=[w.HWND]
        user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
        callback_type=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        visible=[]
        @callback_type
        def visit(hwnd,param):
            pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value in pids and user.IsWindowVisible(hwnd):visible.append(pid.value)
            return True
        user.EnumWindows.argtypes=[callback_type,w.LPARAM]
        self.assertTrue(user.EnumWindows(visit,0))
        self.assertEqual(visible,[])
        # Keep process handles, so PID reuse cannot produce a false shutdown result.
        kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        handles=[kernel.OpenProcess(0x100000,False,pid) for pid in pids]
        self.assertTrue(all(handles))
        try:
            self.client.close()
            for handle in handles:self.assertEqual(kernel.WaitForSingleObject(handle,10000),0)
        finally:
            for handle in handles:
                if handle:kernel.CloseHandle(handle)

if __name__=='__main__':unittest.main()
