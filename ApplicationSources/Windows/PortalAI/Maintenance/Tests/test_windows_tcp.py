"""Native IPv4/IPv6 ownership and bounded TCP-table parsing regression tests."""
import ctypes
import os
from pathlib import Path
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'Agent'))
import windows_tcp as tcp


class TableTests(unittest.TestCase):
    def test_unknown_rendered_state_keeps_kernel_filtered_listener(self):
        row=tcp.Tcp4Row(0,0,socket.htons(24183),0,0,12345)
        data=(1).to_bytes(4,'little')+bytes(row)
        calls=[]
        def api(buffer,size,ordered,family,table,reserved):
            calls.append((family,table))
            ctypes.cast(size,ctypes.POINTER(tcp.DWORD)).contents.value=len(data)
            if buffer is None:return 122
            ctypes.memmove(buffer,data,len(data));return 0
        rows=tcp._listener_rows(api,socket.AF_INET,tcp.Tcp4Row)
        self.assertEqual(rows[0].pid,12345)
        self.assertTrue(all(table==3 for _,table in calls))

    def test_api_failure_does_not_become_an_empty_success(self):
        with self.assertRaises(OSError):tcp._listener_rows(lambda *a:5,socket.AF_INET,tcp.Tcp4Row)

    def test_buffer_growth_retries_are_bounded(self):
        calls=[]
        def api(buffer,size,*args):
            calls.append(1);ctypes.cast(size,ctypes.POINTER(tcp.DWORD)).contents.value=4096+len(calls)*24
            return 122
        with self.assertRaisesRegex(OSError,'kept changing'):tcp._listener_rows(api,socket.AF_INET,tcp.Tcp4Row)
        self.assertEqual(len(calls),4)

    def test_truncated_table_is_refused(self):
        def api(buffer,size,*args):
            ctypes.cast(size,ctypes.POINTER(tcp.DWORD)).contents.value=4
            if buffer is None:return 122
            ctypes.memmove(buffer,(100).to_bytes(4,'little'),4);return 0
        with self.assertRaisesRegex(OSError,'Truncated'):tcp._listener_rows(api,socket.AF_INET,tcp.Tcp4Row)


@unittest.skipUnless(os.name=='nt','Windows native listener API')
class LiveSocketTests(unittest.TestCase):
    def listener(self,family,address):
        with socket.socket(family,socket.SOCK_STREAM) as server:
            server.bind((address,0));server.listen(4);port=server.getsockname()[1]
            self.assertIn(os.getpid(),tcp.listener_pids(port))
        self.assertNotIn(os.getpid(),tcp.listener_pids(port))

    def test_actual_ipv4_listener(self):self.listener(socket.AF_INET,'127.0.0.1')
    def test_actual_ipv6_listener(self):self.listener(socket.AF_INET6,'::1')

    def test_established_socket_is_not_a_listener(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen(1);port=server.getsockname()[1]
            with socket.create_connection(('127.0.0.1',port)) as client:
                peer,_=server.accept()
                with peer:
                    server.close()
                    self.assertNotIn(os.getpid(),tcp.listener_pids(port))


if __name__=='__main__':unittest.main()
