"""A baseline's missing root manuals must never propagate to the next backup."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
from snapshot_owned import required_master_paths


class MasterSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_includes_current_and_future_txt_md_without_baseline(self):
        names={'PortableAI_Master_Instructions_v45.txt','PortableAI_Master_Instructions_v100.md'}
        for name in names:(self.root/name).write_text('Current public instructions')
        (self.root/'personal.txt').write_text('Must not be included')
        (self.root/'PortableAI_Master_Instructions_v45.txt.bak').write_text('Not an active manual')
        self.assertEqual(required_master_paths(self.root),names)

    def test_missing_manual_refuses_silent_incomplete_backup(self):
        with self.assertRaises(FileNotFoundError):required_master_paths(self.root)

    def test_matching_directory_is_not_a_backup_file(self):
        (self.root/'PortableAI_Master_Instructions_v45.txt').mkdir()
        with self.assertRaises(ValueError):required_master_paths(self.root)

    def test_linked_manual_is_rejected_before_reading_its_target(self):
        (self.root/'PortableAI_Master_Instructions_v45.txt').write_text('Fixture')
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaises(ValueError):required_master_paths(self.root)

    def test_revision_matching_does_not_include_private_lookalikes(self):
        (self.root/'portableai_master_instructions_v46.TXT').write_text('Fixture')
        (self.root/'PortableAI_Master_Instructions_private.txt').write_text('Private')
        self.assertEqual(required_master_paths(self.root),{'portableai_master_instructions_v46.TXT'})


if __name__=='__main__':unittest.main()
