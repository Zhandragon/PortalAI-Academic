"""Account-owned background collection monitoring; no persistent embedding worker."""
import os
from pathlib import Path
import threading
import time
from capability_tools import guard
from knowledge_base import Knowledge
from workspace_store import source_path


class FolderSignal:
    def __init__(self,path):
        self.handle=None
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            self.api=ctypes.WinDLL('kernel32',use_last_error=True)
            self.api.FindFirstChangeNotificationW.argtypes=[wintypes.LPCWSTR,wintypes.BOOL,wintypes.DWORD];self.api.FindFirstChangeNotificationW.restype=wintypes.HANDLE
            self.api.FindNextChangeNotification.argtypes=[wintypes.HANDLE];self.api.FindNextChangeNotification.restype=wintypes.BOOL
            self.api.FindCloseChangeNotification.argtypes=[wintypes.HANDLE];self.api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            handle=self.api.FindFirstChangeNotificationW(str(path),True,1|2|8|16)
            if handle and handle!=ctypes.c_void_p(-1).value:self.handle=handle
    def changed(self):
        if self.handle is None:return True  # Bounded periodic sync fallback.
        result=self.api.WaitForSingleObject(self.handle,0)
        if result==0:
            if not self.api.FindNextChangeNotification(self.handle):self.close()
            return True
        if result!=258:self.close();return True
        return False
    def close(self):
        if self.handle is not None:self.api.FindCloseChangeNotification(self.handle);self.handle=None


class KnowledgeMonitor:
    def __init__(self,chat):
        self.chat=chat;self.root=Path(chat.root);self.check_login=guard(chat.tool_runtime)
        self.stopped=threading.Event();self.due={};self.signals={};self.dirty=set();self.status={};self.thread=None
    def idle(self):
        return not self.chat.busy and not self.chat.conversation_active.is_set()
    def check(self):
        self.check_login()
        if self.stopped.is_set():raise RuntimeError('Knowledge monitor stopped')
    def indexing_check(self):
        self.check()
        if not self.idle():raise RuntimeError('Foreground chat or voice takes priority; indexing deferred')
    def tick(self,now=None):
        self.check();now=time.monotonic() if now is None else now
        kb=Knowledge(self.root,self.indexing_check)
        # Metadata reads and signal checks are cheap; imports run only while idle.
        rows=Knowledge(self.root,self.check).list();enabled={r['id']:r for r in rows if r.get('refresh_seconds',0)}
        if len(enabled)>64:raise ValueError('Background monitoring supports at most 64 collections')
        for cid in set(self.signals)-set(enabled):self.signals.pop(cid).close();self.due.pop(cid,None);self.dirty.discard(cid)
        for cid,row in enabled.items():
            if cid not in self.signals:
                self.signals[cid]=FolderSignal(source_path(self.root,row['source']));self.dirty.add(cid);self.due[cid]=now+row['refresh_seconds']
            if self.signals[cid].changed():self.dirty.add(cid)
        if not self.idle():return None
        from runtime_policy import memory_info,require_space
        if memory_info()[1]<2*1024**3:return None
        for cid,row in enabled.items():
            if cid not in self.dirty or now<self.due[cid]:continue
            self.due[cid]=now+row['refresh_seconds'];require_space(self.root,for_outputs=True)
            try:
                result=kb.sync(cid,automatic=True);self.dirty.discard(cid)
                self.status[cid]={'at':time.time(),'state':'synced','result':result};return result
            except Exception as exc:
                self.status[cid]={'at':time.time(),'state':'deferred','detail':str(exc)[:500]};return None
        return None
    def run(self):
        try:
            while not self.stopped.wait(10):
                self.check()
                try:self.tick()
                except Exception as exc:
                    self.check();self.status['monitor']={'state':'deferred','detail':str(exc)[:500]}
        except Exception:pass  # Login revocation and Stop end the monitor.
        finally:
            self.stopped.set()
            for signal in self.signals.values():signal.close()
            self.signals.clear()
            from workspace_services import unregister
            unregister(self.root,self)
    def close(self):self.stopped.set()


def start(chat):
    current=getattr(chat,'_knowledge_monitor',None)
    if current is not None and not current.stopped.is_set():return current
    monitor=KnowledgeMonitor(chat);monitor.check();chat._knowledge_monitor=monitor
    from workspace_services import register,unregister
    register(chat.root,monitor)
    try:monitor.thread=chat._writer_jobs.thread(target=monitor.run,name='PortalAI-document-monitor');monitor.thread.start()
    except Exception:monitor.close();unregister(chat.root,monitor);raise
    return monitor
