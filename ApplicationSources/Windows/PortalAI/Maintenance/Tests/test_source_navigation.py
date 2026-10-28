"""Behavioral navigation checks using unrelated synthetic source features."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ('ControlCenter', 'Agent', 'Tools')]
from source_map import source_map
from source_navigation import public_path, progress_guidance
from maintenance_tools import source_search


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in ('Agent', 'ControlCenter', 'Tools', 'Documentation', 'Private'):
            (self.root / folder).mkdir()
        self.rt = SimpleNamespace(root=self.root, _account_role=lambda: 'admin', _cancel_epoch=0)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
        return path

    def test_rank_finds_symbol_in_unexpected_filename_without_importing_it(self):
        self.put('Agent/zeta.py', '"""Portable archive extraction."""\nraise RuntimeError("NEVER EXECUTE")\ndef unpack_archive(): pass\n')
        self.put('Agent/archive_notes.py', 'def unrelated(): pass\n')
        rows = json.loads(source_map(self.rt, query='archive extraction', limit=2))['items']
        self.assertEqual(rows[0]['path'], 'Agent/zeta.py')
        self.assertEqual(rows[0]['symbols'][0]['symbol'], 'unpack_archive')
        self.assertEqual(rows[0]['next_call']['arguments']['path'], 'Agent/zeta.py')

    def test_absolute_returned_paths_round_trip_between_tools(self):
        p = self.put('Agent/codec.py', 'def encode_packet():\n    return 42\n')
        found = json.loads(source_search(self.rt, 'encode_packet'))['matches'][0]
        result = json.loads(source_map(self.rt, path=found['path']))
        self.assertEqual(result['path'], str(p))
        args = result['items'][0]['next_call']['arguments']
        text = p.read_text(encoding='utf-8')
        self.assertEqual(text[args['offset']:args['offset']+args['max_chars']], text)

    def test_search_all_roots_and_nested_files_avoids_first_file_starvation(self):
        self.put('Agent/a.py', '# unique_token\n' * 30)
        self.put('Tools/nested/b.py', '# unique_token\n')
        rows = json.loads(source_search(self.rt, 'unique_token', limit=2))['matches']
        self.assertEqual(len({r['path'] for r in rows}), 2)
        self.assertTrue(any(r['path'].endswith('b.py') for r in rows))

    def test_exact_single_file_search_keeps_paging(self):
        self.put('Agent/a.py', 'token\ntoken\ntoken\n')
        rows = json.loads(source_search(self.rt, 'token', path='Agent/a.py', offset=6, limit=2))['matches']
        self.assertEqual([r['match_offset'] for r in rows], [6, 12])

    def test_bundled_deep_tree_does_not_starve_other_public_roots(self):
        for i in range(30):
            self.put(f'Agent/dependency/{i}.py', 'x=0')
        self.put('Documentation/feature.txt', 'needle')
        with patch('source_navigation.MAX_ENTRIES', 8):
            result = json.loads(source_search(self.rt, 'needle'))
            from source_navigation import public_files
            files, truncated = public_files(self.rt, self.root)
        self.assertTrue(truncated)
        self.assertEqual(files[0].name, 'feature.txt')
        self.assertEqual(len(result['matches']), 1)
        self.assertTrue(result['matches'][0]['path'].endswith('feature.txt'))
        self.assertFalse(result['complete'])

    def test_bom_outline_offsets_match_read_file_text(self):
        p = self.put('Agent/codec.py', '\ufeffclass Codec:\n    def décoder(self):\n        return 3\n')
        text = p.read_text(encoding='utf-8')
        result = json.loads(source_map(self.rt, path=str(p)))
        self.assertEqual(result['total_chars'], len(text))
        self.assertEqual(result['items'][0]['offset'], 1)
        for row in result['items']:
            snippet = text[row['offset']:row['end_offset']]
            self.assertTrue(snippet.lstrip().startswith(('class ', 'def ')))
        found = json.loads(source_search(self.rt, 'Codec.décoder', path=str(p)))['matches'][0]
        self.assertTrue(text[found['match_offset']:].startswith('def décoder'))

    def test_bom_ranked_symbol_positions_match_source_text(self):
        p = self.put('Agent/codec.py', '\ufeffdef decode_packet(): return 1\n')
        row = json.loads(source_map(self.rt, query='decode packet'))['items'][0]
        self.assertEqual(row['symbols'][0]['offset'], 1)
        self.assertTrue(p.read_text(encoding='utf-8')[row['symbols'][0]['offset']:].startswith('def '))

    def test_empty_guess_returns_observed_candidates_across_roots(self):
        self.put('Agent/wrong.py', 'def unrelated(): pass')
        self.put('ControlCenter/implementation.py', '"""Packet decoder implementation."""\ndef decode_packet(): pass')
        result = json.loads(source_search(self.rt, 'class PacketDecoder', path='Agent/wrong.py'))
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['suggested_files'][0]['path'], 'ControlCenter/implementation.py')
        self.assertIn('not matches', result['suggestion_note'])
        self.assertLessEqual(len(result['suggested_files']), 3)

    def test_failed_private_lookup_never_invokes_suggestion_scan(self):
        with patch('source_navigation.ranked_files') as scan:
            with self.assertRaises(PermissionError):
                source_search(self.rt, 'secret', path='Private')
            scan.assert_not_called()

    def test_outline_includes_imports_and_unicode_character_offsets(self):
        p = self.put('Agent/cafe.py', '# café\nfrom urllib.parse import urlsplit\nclass Café:\n    def décoder(self):\n        """Decode input bytes."""\n        return 3\n')
        result = json.loads(source_map(self.rt, path=str(p), query='décoder'))
        self.assertEqual(result['imports'][0]['module'], 'urllib.parse')
        row = result['items'][0]
        self.assertEqual(row['summary'], 'Decode input bytes.')
        self.assertTrue(p.read_text(encoding='utf-8')[row['offset']:].lstrip().startswith('def décoder'))

    def test_private_other_root_and_parent_traversal_stay_denied(self):
        for path in ('Private/a.py', str(self.root/'Private/a.py'), str(self.root.parent/'other/Agent/a.py'),
                     'Agent/../ControlCenter/a.py', 'Agent\\..\\Private\\a.py'):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                public_path(self.rt, path)

    def test_root_and_backslash_paths_are_equivalent(self):
        p = self.put('Agent/codec.py', 'x=1')
        self.assertEqual(public_path(self.rt, 'Agent\\codec.py'), p)
        self.assertEqual(public_path(self.rt, str(self.root)), self.root)

    def test_symlink_never_opens_private_source(self):
        target = self.put('Private/secret.py', 'def secret_value(): pass')
        link = self.root/'Agent/link.py'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Host does not permit symlink creation')
        with self.assertRaises(PermissionError):
            source_map(self.rt, str(link))
        self.assertEqual(json.loads(source_map(self.rt, query='secret'))['items'], [])

    def test_oversized_file_is_not_parsed_and_scan_is_labeled(self):
        self.put('Agent/huge.py', '# data\n' * 160000)
        with patch('source_navigation.outline', side_effect=AssertionError('Must not parse')):
            result = json.loads(source_map(self.rt, query='huge'))
        self.assertTrue(result['scan_truncated'])
        self.assertIsNone(result['items'][0]['sha256'])

    def test_cancel_during_scan_prevents_publication(self):
        self.put('Agent/a.py', 'def target(): pass')
        import source_navigation
        original = source_navigation.outline
        def stop(text):
            self.rt._cancel_epoch += 1
            return original(text)
        with patch('source_navigation.outline', side_effect=stop), self.assertRaisesRegex(RuntimeError, 'cancelled'):
            source_map(self.rt, query='target')

    def test_role_revocation_during_scan_prevents_publication(self):
        self.put('Agent/a.py', 'def target(): pass')
        import source_navigation
        original = source_navigation.outline
        def revoke(text):
            self.rt._account_role = lambda: 'guest'
            return original(text)
        with patch('source_navigation.outline', side_effect=revoke), self.assertRaises(PermissionError):
            source_map(self.rt, query='target')

    def test_progress_uses_call_metadata_and_never_tool_prose(self):
        self.assertEqual(progress_guidance([{'role':'tool','content':'source_search '*100}]), '')
        row = {'role':'assistant','tool_calls':[{'function':{'name':'source_search'}}]}
        guide = progress_guidance([row]*5)
        self.assertIn('repeated source discovery', guide)
        self.assertNotIn('web_capabilities', guide)
        write = {'role':'assistant','tool_calls':[{'function':{'name':'edit_file'}}]}
        self.assertIn('write was attempted', progress_guidance([row]*5+[write]))
        self.assertNotIn('repeated source discovery', progress_guidance([row]*5+[write]))

    def test_public_tests_are_searchable_without_exposing_maintenance_records(self):
        p=self.put('Maintenance/Tests/test_packet.py','def test_packet_decode(): pass\n')
        self.put('Maintenance/Validation/private.py','def private_value(): pass\n')
        self.assertEqual(json.loads(source_search(self.rt,'test_packet_decode'))['matches'][0]['path'],str(p))
        self.assertEqual(json.loads(source_map(self.rt,query='packet decode'))['items'][0]['path'],'Maintenance/Tests/test_packet.py')
        self.assertEqual(json.loads(source_map(self.rt,path=str(p)))['items'][0]['symbol'],'test_packet_decode')
        for path in ('Maintenance','Maintenance/Validation','Maintenance/TestsOther','Maintenance/Tests/../Validation'):
            with self.subTest(path=path),self.assertRaises(PermissionError):public_path(self.rt,path)

    def test_revocation_after_read_prevents_next_file_read_and_publication(self):
        self.put('Agent/a.py','def needle(): pass')
        self.put('Agent/b.py','def needle(): pass')
        original=Path.read_bytes
        for mode in ('stop','role'):
            self.rt._cancel_epoch=0;self.rt._account_role=lambda:'admin';reads=[]
            def read(path):
                value=original(path);reads.append(path.name)
                if mode=='stop':self.rt._cancel_epoch+=1
                else:self.rt._account_role=lambda:'guest'
                return value
            with self.subTest(mode=mode),patch.object(Path,'read_bytes',read),self.assertRaises((PermissionError,RuntimeError)):
                source_map(self.rt,query='needle')
            self.assertEqual(reads,['a.py'])

    def test_literal_search_rechecks_after_read_before_returning_matches(self):
        self.put('Agent/a.py','needle')
        original=Path.read_bytes
        def read(path):
            value=original(path);self.rt._account_role=lambda:'guest';return value
        with patch.object(Path,'read_bytes',read),self.assertRaises(PermissionError):
            source_search(self.rt,'needle',limit=1)

    def test_truncated_inventory_rechecks_authority_before_return(self):
        self.put('Agent/a.py','x=1')
        original=Path.iterdir
        def listing(path):
            values=list(original(path));self.rt._account_role=lambda:'guest';return iter(values)
        from source_navigation import public_files
        with patch('source_navigation.MAX_ENTRIES',0),patch.object(Path,'iterdir',listing),self.assertRaises(PermissionError):
            public_files(self.rt,self.root)


if __name__ == '__main__':
    unittest.main()
