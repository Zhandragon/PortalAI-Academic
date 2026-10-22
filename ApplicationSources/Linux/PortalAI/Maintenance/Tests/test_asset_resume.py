"""Interrupted model transfers resume without weakening integrity or disk floors."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
import import_foundation_assets as importer


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body); self.status=status; self.headers=headers or {}


class ResumeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.asset={'id':'synthetic','url':'https://example.invalid/pinned/file','size':6,
                    'sha256':hashlib.sha256(b'abcdef').hexdigest(),'dest':'models/model.bin'}
        self.part=self.root/'Cache/imports/synthetic.part';self.part.parent.mkdir(parents=True)
        self.space=patch.object(importer,'require_space',return_value={'allowed':True}).start()
        self.addCleanup(patch.stopall)

    def test_exact_partial_response_is_appended_and_fully_verified(self):
        self.part.write_bytes(b'abc')
        with patch.object(importer.urllib.request,'urlopen',return_value=Response(b'def',206,{'Content-Range':'bytes 3-5/6'})) as request:
            result=importer.install(self.asset,self.root)
        self.assertEqual(result['status'],'installed-verified')
        self.assertEqual((self.root/'models/model.bin').read_bytes(),b'abcdef')
        self.assertEqual(request.call_args.args[0].headers['Range'],'bytes=3-')

    def test_ignored_range_restarts_instead_of_appending_duplicate_bytes(self):
        self.part.write_bytes(b'abc')
        with patch.object(importer.urllib.request,'urlopen',return_value=Response(b'abcdef')):
            self.assertEqual(importer.download(self.asset,self.part,self.root),6)
        self.assertEqual(self.part.read_bytes(),b'abcdef')

    def test_wrong_range_does_not_touch_retained_partial(self):
        self.part.write_bytes(b'abc')
        with patch.object(importer.urllib.request,'urlopen',return_value=Response(b'def',206,{'Content-Range':'bytes 2-4/6'})):
            with self.assertRaisesRegex(RuntimeError,'range'):
                importer.download(self.asset,self.part,self.root)
        self.assertEqual(self.part.read_bytes(),b'abc')

    def test_corrupt_complete_partial_never_activates_or_redownloads(self):
        self.part.write_bytes(b'badbad')
        with patch.object(importer.urllib.request,'urlopen') as request:
            with self.assertRaisesRegex(RuntimeError,'checksum/size mismatch'):
                importer.install(self.asset,self.root)
            request.assert_not_called()
        self.assertFalse((self.root/'models/model.bin').exists())
        self.assertEqual(self.part.read_bytes(),b'badbad')

    def test_only_brief_permission_conflicts_are_retried(self):
        self.space.side_effect=[PermissionError('busy'),{'allowed':True}]
        with patch.object(importer.time,'sleep') as sleep:
            importer.checked_space(self.root,6)
            sleep.assert_called_once_with(.1)
        self.space.side_effect=RuntimeError('free-space floor')
        with patch.object(importer.time,'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError,'free-space floor'):
                importer.checked_space(self.root,6)
            sleep.assert_not_called()
        self.space.side_effect=PermissionError('permanent')
        with patch.object(importer.time,'sleep') as sleep:
            with self.assertRaises(PermissionError): importer.checked_space(self.root,6)
            self.assertEqual(sleep.call_count,3)


if __name__=='__main__':unittest.main()
