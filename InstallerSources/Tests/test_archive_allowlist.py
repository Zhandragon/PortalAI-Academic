"""Install only pinned ZIP members; unused upstream links are inert."""
import hashlib
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Windows'))
import installer_core as core


class ZipAllowlist(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.archive = self.folder / 'fixture.zip'
        self.root = self.folder / 'installed'
        self.root.mkdir()
        self.stop = threading.Event()

    def row(self, member='vendor/module.py', data=b'print("ok")\n', dest='PortalAI Windows/Tools/module.py'):
        return dict(member=member, dest=dest, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())

    def make_archive(self, extras=()):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('vendor/module.py', b'print("ok")\n')
            for name, data, mode in extras:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                archive.writestr(info, data)

    def extract(self, rows=None):
        core.extract_allowlist(self.archive, rows or [self.row()], self.root, self.stop)

    def test_unused_development_links_are_not_opened_followed_or_created(self):
        self.make_archive([
            ('vendor/.dockerignore', b'.gitignore', stat.S_IFLNK | 0o777),
            ('vendor/nested/.clang-format', b'../../../../../outside', stat.S_IFLNK | 0o777),
            ('vendor/LICENSE', b'../LICENSE', stat.S_IFLNK | 0o777),
        ])
        self.extract()
        files = [p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()]
        self.assertEqual(files, ['PortalAI Windows/Tools/module.py'])
        self.assertEqual((self.root / files[0]).read_bytes(), b'print("ok")\n')

    def test_selected_link_is_rejected_before_any_file_is_written(self):
        self.make_archive([('vendor/link', b'module.py', stat.S_IFLNK | 0o777)])
        rows = [self.row(), self.row('vendor/link', b'module.py', 'PortalAI Windows/Tools/link')]
        with self.assertRaisesRegex(core.InstallError, 'Selected archive member is a link: vendor/link'):
            self.extract(rows)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unselected_path_traversal_is_still_rejected(self):
        self.make_archive([('../escape', b'x', stat.S_IFREG | 0o644)])
        with self.assertRaises(core.InstallError):
            self.extract()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_case_colliding_names_are_still_rejected(self):
        self.make_archive([('vendor/MODULE.py', b'x', stat.S_IFREG | 0o644)])
        with self.assertRaisesRegex(core.InstallError, 'duplicate member names'):
            self.extract()

    def test_selected_file_hash_is_still_verified(self):
        self.make_archive()
        row = self.row()
        row['sha256'] = '0' * 64
        with self.assertRaisesRegex(core.InstallError, 'checksum mismatch'):
            self.extract([row])
        self.assertFalse((self.root / row['dest']).exists())

    def test_selected_file_size_is_still_verified(self):
        self.make_archive()
        row = self.row()
        row['bytes'] += 1
        with self.assertRaisesRegex(core.InstallError, 'pinned metadata'):
            self.extract([row])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_files_are_never_overwritten(self):
        self.make_archive()
        path = self.root / self.row()['dest']
        path.parent.mkdir(parents=True)
        path.write_bytes(b'existing')
        with self.assertRaisesRegex(core.InstallError, 'existing installation file'):
            self.extract()
        self.assertEqual(path.read_bytes(), b'existing')

    def test_cancellation_does_not_publish_selected_file(self):
        self.make_archive()
        self.stop.set()
        with self.assertRaises(core.Cancelled):
            self.extract()
        self.assertFalse((self.root / self.row()['dest']).exists())


if __name__ == '__main__':
    unittest.main()
