"""Windows path protocol regression on Python 3.12 and 3.13+."""
import os,sys,tempfile,unittest
from pathlib import Path as StandardPath
sys.path.insert(0,str(StandardPath(__file__).resolve().parents[2]/'Agent'))
from portable_fs import Path,native_path

@unittest.skipUnless(os.name=='nt','Windows path protocol')
class PathProtocolTests(unittest.TestCase):
    def test_short_and_relative_paths_do_not_recurse(self):
        for text in ('C:\\folder\\file.txt','relative/file.txt','C:relative','\\root-relative'):
            p=Path(text);self.assertEqual(os.fspath(p),str(p));self.assertEqual(p.is_absolute(),StandardPath(text).is_absolute())
    def test_long_drive_and_unc_paths_get_one_extended_prefix(self):
        for text in ('C:\\'+('segment\\'*45)+'file','\\\\server\\share\\'+('segment\\'*45)+'file'):
            p=Path(text);expected=('\\\\?\\UNC\\'+str(p)[2:]) if text.startswith('\\\\') else '\\\\?\\'+str(p)
            self.assertEqual(os.fspath(p),expected);self.assertEqual(str(Path(expected)),str(p));self.assertTrue(p.is_absolute())
    def test_unicode_paths_use_utf16_length_and_reject_devices(self):
        p=Path('C:\\'+'\U0001f600'*125);self.assertTrue(os.fspath(p).startswith('\\\\?\\'))
        with self.assertRaises(ValueError):Path('\\\\.\\PhysicalDrive0')
    def test_real_long_path_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/('a'*90)/('b'*90)/('c'*90)/'test.txt'
            p.parent.mkdir(parents=True);p.write_text('round trip',encoding='utf-8');self.assertEqual(p.read_text(encoding='utf-8'),'round trip')
            p.unlink()
            for _ in range(3):p=p.parent;p.rmdir()

if __name__=='__main__':unittest.main()
