"""Pinned synthetic packages exercise the actual installer without network or models."""
import hashlib,json,sys,tempfile,threading,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Windows'))
import installer_core as core

class ProgressTests(unittest.TestCase):
    def test_selected_bytes_count_download_write_and_verification(self):
        events=[];m=core.InstallationProgress(lambda **e:events.append(e),[{'bytes':10}],[{'bytes':20},{'bytes':30}])
        m.start('download','model',10);m.advance('model',4,10);m.finish()
        m.start('install','files',50);m.file({'dest':'a'},8,20);m.file({'dest':'a'},20,20);m.file({'dest':'b'},30,30);m.finish()
        m.start('verify','files',50);m.file({'dest':'a'},20,20);m.file({'dest':'b'},30,30);m.finish()
        self.assertEqual(events[-1]['overall_done'],110);self.assertEqual(events[-1]['overall_total'],110)
        self.assertEqual([e['overall_done'] for e in events],sorted(e['overall_done'] for e in events))

    def test_real_write_callbacks_keep_hash_and_cancellation_guards(self):
        import io
        data=b'probe'*100;row={'dest':'data','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()};events=[]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'file';stop=threading.Event()
            core.write_verified(io.BytesIO(data),target,row,stop,lambda *args:events.append(args))
            self.assertEqual(target.read_bytes(),data);self.assertEqual(events[-1][1:],(len(data),len(data)))
            stop.set()
            with self.assertRaises(core.Cancelled):core.write_verified(io.BytesIO(data),Path(tmp)/'cancelled',row,stop,lambda *args:None)
            self.assertFalse((Path(tmp)/'cancelled').exists())
            with self.assertRaises(core.InstallError):core.write_verified(io.BytesIO(b'x'*len(data)),Path(tmp)/'bad',row,threading.Event(),lambda *args:None)
            self.assertFalse((Path(tmp)/'bad').exists())

if __name__=='__main__':unittest.main()
