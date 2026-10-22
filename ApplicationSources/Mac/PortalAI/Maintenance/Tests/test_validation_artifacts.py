"""Synthetic Linux artifact routing; no VM launch or production account access."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'Agent')]
import validation_artifacts as artifacts
import profile_paths


class ValidationOutputTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.parent=Path(temporary.name).resolve();self.root=self.parent/'PortalAI';self.root.mkdir()
        env=patch.dict(os.environ,{},clear=True);env.start();self.addCleanup(env.stop)
        self.uid='a'*32;self.epoch='b'*32

    def active(self,state='open'):
        marker=self.root/'Private/active-session.json';marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':state}))
        os.environ.update(PORTALAI_PROFILE_ID=self.uid,PORTALAI_PROFILE_EPOCH=self.epoch)
        return marker

    def test_default_active_output_is_private_and_revokes_on_logout(self):
        marker=self.active()
        output=artifacts.ValidationArtifacts(self.root)
        expected=profile_paths.workspace_root(self.root,self.uid)/'Data/Maintenance/LinuxValidation'
        self.assertEqual(output.path('linux-media-guest.json'),expected/'linux-media-guest.json')
        marker.write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':'closed'}))
        with self.assertRaises(profile_paths.ProfileLocked):output.path('late.json')
        self.assertFalse((self.root/'Data').exists())

    def test_default_locked_output_refuses_without_writes(self):
        self.active('closed')
        with self.assertRaises(profile_paths.ProfileLocked):artifacts.ValidationArtifacts(self.root)
        self.assertFalse((self.root/'Private/Users').exists())
        self.assertFalse((self.root/'Data').exists())

    def test_legacy_default_keeps_root_relative_data(self):
        output=artifacts.ValidationArtifacts(self.root)
        self.assertEqual(output.path(),self.root/'Data/Maintenance/LinuxValidation')

    def test_explicit_synthetic_output_is_available_when_profile_locked(self):
        self.active('closed')
        target=self.root/'Maintenance/Validation/unit-fixture'
        output=artifacts.ValidationArtifacts(self.root,target)
        self.assertEqual(output.path('test.json'),target/'test.json')
        self.assertEqual(json.loads((target/artifacts.MARKER).read_text()),artifacts.IDENTITY)
        self.assertEqual(artifacts.ValidationArtifacts(self.root,target).path(),target)
        self.assertFalse((self.root/'Private/Users').exists())

    def test_explicit_external_empty_directory_is_marked(self):
        target=self.parent/'synthetic-output'
        self.assertEqual(artifacts.ValidationArtifacts(self.root,target).path(),target)
        self.assertTrue((target/artifacts.MARKER).is_file())

    def test_explicit_path_cannot_target_private_assets_or_shared_reports(self):
        for relative in ('Private/Users/'+'c'*32+'/Workspace','Data/Maintenance','Runtime/LinuxPython',
                         'Maintenance/Reports','Backups','Cache/LinuxValidation','Maintenance/Validation'):
            with self.subTest(relative=relative),self.assertRaises(ValueError):
                artifacts.ValidationArtifacts(self.root,self.root/relative)
        with self.assertRaises(ValueError):artifacts.ValidationArtifacts(self.root,'relative-output')

    def test_existing_unmarked_content_or_wrong_marker_is_preserved(self):
        target=self.parent/'existing';target.mkdir();keep=target/'keep.txt';keep.write_text('keep')
        with self.assertRaises(ValueError):artifacts.ValidationArtifacts(self.root,target)
        (target/artifacts.MARKER).write_text('{}')
        with self.assertRaises(ValueError):artifacts.ValidationArtifacts(self.root,target)
        self.assertEqual(keep.read_text(),'keep')

    def test_output_cannot_escape_marked_directory(self):
        output=artifacts.ValidationArtifacts(self.root,self.parent/'synthetic')
        with self.assertRaises(ValueError):output.path('../escape.txt')
        with self.assertRaises(ValueError):output.path(str(self.root/'Data/private.txt'))

    def test_readonly_legacy_media_iso_is_reused_without_output_redirection(self):
        output=artifacts.ValidationArtifacts(self.root,self.parent/'synthetic')
        iso=self.root/'Cache/LinuxValidation/media-science.iso';iso.parent.mkdir(parents=True);iso.write_bytes(b'fixture')
        self.assertEqual(artifacts.media_iso(self.root,output),iso)
        self.assertFalse(output.path('media-science.iso').exists())
        self.assertEqual(iso.read_bytes(),b'fixture')

    def test_media_iso_prefers_marked_artifact_then_explicit_input(self):
        output=artifacts.ValidationArtifacts(self.root,self.parent/'synthetic')
        with self.assertRaises(FileNotFoundError):artifacts.media_iso(self.root,output)
        iso=output.path('media-science.iso');iso.write_bytes(b'fixture')
        self.assertEqual(artifacts.media_iso(self.root,output),iso)
        explicit=self.parent/'other.iso';explicit.write_bytes(b'other')
        self.assertEqual(artifacts.media_iso(self.root,output,explicit),explicit)

    def test_external_output_volume_has_its_own_free_space_floor(self):
        output=artifacts.ValidationArtifacts(self.root,self.parent/'synthetic')
        with patch('runtime_policy.require_space') as reserve,\
             patch.object(artifacts.shutil,'disk_usage',return_value=SimpleNamespace(total=100*1024**3,free=6*1024**3)):
            with self.assertRaisesRegex(RuntimeError,'destination free-space'):
                artifacts.require_output_space(self.root,output,2*1024**3)
        reserve.assert_called_once_with(self.root,2*1024**3,for_outputs=False)

    def test_locked_runner_refuses_before_preflight_or_vm(self):
        import run_linux_packaging as runner
        self.active('closed')
        with patch.object(runner,'ROOT',self.root),patch.object(sys,'argv',['run_linux_packaging']),\
             patch.object(runner,'preflight') as preflight,patch.object(runner.subprocess,'Popen') as launch:
            with self.assertRaises(profile_paths.ProfileLocked):runner.main()
        preflight.assert_not_called();launch.assert_not_called()


if __name__=='__main__':unittest.main()
