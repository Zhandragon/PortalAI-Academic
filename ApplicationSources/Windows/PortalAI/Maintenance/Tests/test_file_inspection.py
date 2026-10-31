import json,sqlite3,sys,tempfile,tracemalloc,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
import file_inspection as fi


class FileInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_large_file_page_has_bounded_memory_and_exact_character_offsets(self):
        p=self.root/'large.txt';block='line café\r\n'*4096
        with p.open('w',encoding='utf-8',newline='') as stream:
            for _ in range(256):stream.write(block)
        normalized=block.replace('\r\n','\n');offset=len(normalized)*200+3
        tracemalloc.start()
        try:result=fi.page(p,offset,200);peak=tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
        self.assertLess(peak,2*1024**2)
        self.assertEqual(result['total_chars'],len(normalized)*256)
        self.assertEqual(result['text'],(normalized*2)[3:203]);self.assertEqual(result['next_offset'],offset+200)

    def test_search_matches_across_chunk_boundary_and_paginates_without_duplicates(self):
        p=self.root/'search.txt';text='x'*(fi.CHUNK-2)+'needle'+'y'*100+'needle';p.write_text(text)
        first=fi.search(p,'needle',limit=1);self.assertEqual(first['matches'][0]['offset'],fi.CHUNK-2)
        second=fi.search(p,'needle',offset=first['next_offset'],limit=2)
        self.assertEqual([r['offset'] for r in second['matches']],[len(text)-6]);self.assertTrue(second['complete'])

    def test_cancel_and_changed_file_do_not_report_complete_results(self):
        p=self.root/'text.txt';p.write_text('before')
        with self.assertRaisesRegex(RuntimeError,'Stop'):fi.page(p,check=Mock(side_effect=RuntimeError('Stop')))
        calls=[0]
        def mutate():
            calls[0]+=1
            if calls[0]==1:p.write_text('changed content')
        with self.assertRaisesRegex(RuntimeError,'changed'):fi.page(p,check=mutate)

    def test_csv_json_and_sqlite_samples_are_read_only(self):
        csv=self.root/'data.csv';csv.write_text('name,value\n"two, words",3\n')
        result=fi.preview(csv);self.assertEqual(result['rows'][1],['two, words','3']);self.assertTrue(result['rows_are_sample'])
        p=self.root/'data.json';p.write_text('{"a":1,"b":[2]}');self.assertEqual(fi.preview(p)['keys'],['a','b'])
        db=self.root/'data.db'
        conn=sqlite3.connect(db)
        try:
            conn.execute('CREATE TABLE example(value TEXT)');conn.execute("INSERT INTO example VALUES ('kept')");conn.commit()
        finally:conn.close()
        before=db.read_bytes();result=fi.preview(db)
        self.assertEqual(result['objects'][0]['name'],'example');self.assertEqual(db.read_bytes(),before)

    def test_archive_inventory_never_extracts_paths_or_decompresses_members(self):
        p=self.root/'unsafe-names.zip'
        with zipfile.ZipFile(p,'w') as archive:
            archive.writestr('../outside.txt','source is evidence');archive.writestr('large.txt',b'x'*1000000)
        with patch.object(zipfile.ZipFile,'extract',side_effect=AssertionError('No extraction')):
            result=fi.preview(p)
        self.assertFalse(result['extracted']);self.assertEqual(result['member_count'],2);self.assertFalse((self.root.parent/'outside.txt').exists())

    def test_archive_count_limit_cannot_be_bypassed_by_forged_eocd(self):
        p=self.root/'many.zip'
        with zipfile.ZipFile(p,'w') as z:
            for i in range(513):z.writestr(str(i),'')
        data=bytearray(p.read_bytes());at=data.rfind(b'PK\x05\x06');data[at+8:at+12]=b'\x01\0\x01\0';p.write_bytes(data)
        with patch.object(zipfile,'ZipFile',side_effect=AssertionError('Must reject before zipfile allocates entries')):
            self.assertIn('limit',fi.preview(p)['inventory_error'])

    def test_dispatch_uses_account_path_permissions_before_opening(self):
        runtime=SimpleNamespace(_account_role=Mock(return_value='user'),_cancel_epoch=0,
                                safe_path=Mock(side_effect=PermissionError('Own workspace only')))
        with self.assertRaises(PermissionError):fi.execute(runtime,{'path':'outside'})


if __name__=='__main__':unittest.main()
