"""Slow record I/O must never own Tk; hidden/stale/revoked reads cannot publish."""
import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace

from record_refresh import RecordRefresh
from writer_jobs import WriterJobs
from record_refresh_fixture import settle_records


class RecordRefreshTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('320x160+20+20')
        self.frame=tk.Frame(self.app);self.frame.pack(fill='both',expand=True)
        self.app.update();self.jobs=WriterJobs();self.applied=[];self.errors=[]
        self.allowed=True;self.release=threading.Event()

    def tearDown(self):
        self.release.set()
        for reader in getattr(self.frame,'_record_refreshes',[]):reader.close()
        self.jobs.close();self.assertTrue(self.jobs.wait(5)['stopped'])
        self.app.destroy()

    def check(self):
        if not self.allowed:raise PermissionError('Login ended')

    def reader(self,load):
        return RecordRefresh(self.frame,load,self.applied.append,check=self.check,error=self.errors.append,jobs=self.jobs)

    def pump(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.app.update();time.sleep(.005)

    def test_slow_read_keeps_tk_responsive_and_coalesces_repeated_requests(self):
        calls=[];main=threading.get_ident();beats=[]
        def load(value):
            self.assertNotEqual(threading.get_ident(),main)
            calls.append(value);self.release.wait(3);return value
        reader=self.reader(load)
        def beat():
            beats.append(time.monotonic())
            if not self.release.is_set():self.app.after(15,beat)
        beat();reader.request('a')
        for _ in range(20):reader.request('a')
        self.pump(.3)
        self.assertGreater(len(beats),10);self.assertEqual(calls,['a']);self.assertEqual(self.applied,[])
        self.release.set();settle_records(self.app);self.assertEqual(self.applied,['a'])

    def test_newest_selection_wins_without_concurrent_reads(self):
        calls=[]
        def load(value):
            calls.append(value)
            if value=='a':self.release.wait(3)
            return value
        reader=self.reader(load);reader.request('a');reader.request('b');reader.request('c')
        self.release.set();settle_records(self.app)
        self.assertEqual(calls,['a','c']);self.assertEqual(self.applied,['c'])

    def test_hidden_page_stops_reads_and_discards_inflight_result(self):
        calls=[]
        def load(value):calls.append(value);self.release.wait(3);return value
        reader=self.reader(load);reader.request('a');self.frame.pack_forget();self.app.update()
        reader.request('b');self.release.set();settle_records(self.app)
        self.assertEqual(calls,['a']);self.assertEqual(self.applied,[])
        self.frame.pack();self.app.update();reader.request('c');settle_records(self.app)
        self.assertEqual(self.applied,['c'])

    def test_ended_login_discards_private_result(self):
        reader=self.reader(lambda value:(self.release.wait(3),value)[1]);reader.request('secret')
        self.allowed=False;self.release.set();settle_records(self.app)
        self.assertEqual(self.applied,[]);self.assertIsInstance(self.errors[0],PermissionError)

    def test_writer_shutdown_rejects_late_reads_and_destroy_discards(self):
        reader=self.reader(lambda value:(self.release.wait(3),value)[1]);reader.request('secret')
        reader.close();self.release.set();self.jobs.close();self.assertTrue(self.jobs.wait(5)['stopped'])
        self.pump(.1);self.assertEqual(self.applied,[])
        other=self.reader(lambda value:value);other.request('late')
        self.assertIsInstance(self.errors[-1],RuntimeError);self.assertFalse(other.running)

    def test_unmapped_projection_override_can_refresh(self):
        self.frame.pack_forget();self.app.update()
        self.app._portalai_native_workflow=SimpleNamespace(overrides={'viewer':self.frame})
        reader=self.reader(lambda value:value);reader.request('remote');settle_records(self.app)
        self.assertEqual(self.applied,['remote'])
        self.app._portalai_native_workflow.overrides.clear();reader.request('hidden');settle_records(self.app)
        self.assertEqual(self.applied,['remote'])


if __name__=='__main__':unittest.main()
