"""Synthetic media ISOs must not scoop up vendor output or account residue."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
from build_linux_test_disk import project_source_files,SOURCE_EXCLUDED
import build_linux_test_disk as builder
from validation_artifacts import ValidationArtifacts
from profile_paths import ProfileLocked


class Sources(unittest.TestCase):
    def test_linked_partial_output_is_refused_before_native_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve()
            artifacts=ValidationArtifacts(base,str(base/'Maintenance/Validation/review'))
            partial=artifacts.path('fixture.part');partial.write_text('preserve')
            with patch.object(Path,'is_symlink',lambda p:p==partial), \
                 patch.object(builder.pycdlib.PyCdlib,'write') as write:
                with self.assertRaises(ProfileLocked):builder.write_disk({},artifacts,'fixture.iso')
                write.assert_not_called()
            self.assertEqual(partial.read_text(),'preserve')

    def test_source_config_only_and_nested_private_directories_are_pruned(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            for relative in ('main.py','config.json','web/app.js','weights.safetensors','error.log'):
                file=base/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('fixture')
            for excluded in SOURCE_EXCLUDED:
                for prefix in ('','custom_nodes/node/'):
                    file=base/prefix/excluded/'private.json';file.parent.mkdir(parents=True,exist_ok=True);file.write_text('sentinel')
            found={p.relative_to(base).as_posix() for p in project_source_files(base)}
            self.assertEqual(found,{'main.py','config.json','web/app.js'})

    def test_linked_files_directories_and_root_are_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);nested=base/'external';nested.mkdir();(nested/'secret.py').write_text('sentinel')
            linked=base/'source.py';linked.write_text('sentinel')
            with patch.object(Path,'is_symlink',lambda p:p in (linked,nested)):
                self.assertEqual(list(project_source_files(base)),[])
            with patch.object(Path,'is_symlink',lambda p:p==base):
                with self.assertRaisesRegex(ValueError,'Linked project'):list(project_source_files(base))
            with patch.object(Path,'is_symlink',lambda p:p==base.parent):
                with self.assertRaisesRegex(ValueError,'Linked project'):list(project_source_files(base))

    def test_named_upstream_source_packages_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            for relative in ('comfy_api/input/basic_types.py','api/jobs/__init__.py','other/input/user.json'):
                file=base/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('fixture')
            self.assertEqual({p.relative_to(base).as_posix() for p in project_source_files(base)},
                             {'comfy_api/input/basic_types.py','api/jobs/__init__.py'})


if __name__=='__main__':unittest.main()
