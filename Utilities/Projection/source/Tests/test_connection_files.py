from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from connection_files import delete_saved_connection


class SavedConnectionDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.connections = self.root / 'Connections'
        self.connections.mkdir()
        self.selected = self.connections / ('a' * 32 + '.enc')
        self.pairing = self.connections / ('a' * 32 + '.public-pairing.json')
        self.other = self.connections / ('b' * 32 + '.enc')
        self.selected.write_bytes(b'encrypted test fixture')
        self.pairing.write_text('{"public":"test fixture"}', encoding='utf-8')
        self.other.write_bytes(b'keep this connection')

    def tearDown(self):
        self.temp.cleanup()

    def test_deletes_only_selected_connection_and_pairing_export(self):
        result = delete_saved_connection(self.connections, self.selected)
        self.assertEqual(result, {
            'connection_removed': True,
            'pairing_removed': True,
            'pairing_error': None,
        })
        self.assertFalse(self.selected.exists())
        self.assertFalse(self.pairing.exists())
        self.assertTrue(self.other.exists())

    def test_missing_pairing_export_is_allowed(self):
        self.pairing.unlink()
        result = delete_saved_connection(self.connections, self.selected)
        self.assertTrue(result['connection_removed'])
        self.assertFalse(result['pairing_removed'])
        self.assertTrue(self.other.exists())

    def test_rejects_path_outside_connections_folder(self):
        outside = self.root / 'outside.enc'
        outside.write_bytes(b'keep outside file')
        with self.assertRaises(ValueError):
            delete_saved_connection(self.connections, outside)
        self.assertTrue(outside.exists())
        self.assertTrue(self.selected.exists())

    def test_rejects_non_connection_file(self):
        not_connection = self.connections / 'notes.txt'
        not_connection.write_text('keep', encoding='utf-8')
        with self.assertRaises(ValueError):
            delete_saved_connection(self.connections, not_connection)
        self.assertTrue(not_connection.exists())
        self.assertTrue(self.selected.exists())


if __name__ == '__main__':
    unittest.main()
