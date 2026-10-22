"""Real synthetic login markers guard the shared native media publication path."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import sdcpp_bridge as native
from profile_paths import UID_ENV,EPOCH_ENV,workspace_root,ProfileLocked


class NativePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='Portal native publication ')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.uid='a'*32;self.epoch='b'*32;self.token='1'*32
        self.marker=self.root/'Private/active-session.json'
        self.marker.parent.mkdir(parents=True)
        self.marker.write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':'open'}))
        self.workspace=workspace_root(self.root,self.uid)
        self.process=Mock(pid=8765);self.process.returncode=0
        self.process.poll.side_effect=lambda:self.process.returncode
        self.process.kill.side_effect=lambda:setattr(self.process,'returncode',-1)
        self.job=Mock();self.validate=Mock();self.part=None

    def revoke(self):
        self.marker.write_text(json.dumps({'user_id':self.uid,'epoch':'c'*32,'state':'open'}))

    def execute(self,stage=None,*,legacy=False):
        if legacy:
            self.marker.unlink();self.marker.parent.rmdir()
        def command(part):
            self.part=part
            return ['synthetic-media-worker',str(part)]
        def launch(*args,**kwargs):
            self.part.write_bytes(b'generated media')
            kwargs['stdout'].write(b'synthetic worker completed\n');kwargs['stdout'].flush()
            if stage=='worker':
                self.process.returncode=None
                def polling():
                    if self.process.returncode is None:self.revoke()
                    return self.process.returncode
                self.process.poll.side_effect=polling
            return self.process
        rename=Path.rename
        def publish(path,destination):
            result=rename(path,destination)
            if stage in ('rename','foreign'):
                if stage=='foreign':
                    sentinel=Path(destination).with_suffix('.foreign')
                    sentinel.write_bytes(b'foreign sentinel')
                    os.replace(sentinel,destination)
                self.revoke()
            return result
        def validate(path):
            self.validate(path)
            if stage=='validation':self.revoke()
            if stage=='collision':
                path.with_name(path.name.replace('.part.','.')).write_bytes(b'foreign preexisting output')
        env={} if legacy else {UID_ENV:self.uid,EPOCH_ENV:self.epoch}
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,env,clear=True))
            stack.enter_context(patch.object(native,'portable_env',return_value=dict(env)))
            stack.enter_context(patch.object(native,'python_path',return_value=self.root/'synthetic-python'))
            stack.enter_context(patch.object(native,'require_space'))
            stack.enter_context(patch.object(native.uuid,'uuid4',return_value=SimpleNamespace(hex=self.token)))
            stack.enter_context(patch.object(native.subprocess,'Popen',side_effect=launch))
            stack.enter_context(patch.object(native,'WorkerJob',return_value=self.job))
            stack.enter_context(patch.object(Path,'rename',publish))
            return native.run_generation({'backend':'cpu','engine':'synthetic-media'},command,validate,
                                         root=self.root,kind='musetalk')

    def outputs(self):return list((self.workspace/'Outputs').rglob('*.mp4'))

    def assert_clean(self):
        self.job.close.assert_called_once();self.process.wait.assert_called_once()
        self.assertFalse(self.part.exists())
        runtime=self.workspace/'Cache/MediaWorkers'
        self.assertFalse((runtime/'sdcpp-active.json').exists())
        self.assertFalse((self.root/'Outputs').exists())

    def test_revocation_during_worker_stops_job_before_validation(self):
        with self.assertRaises(ProfileLocked):self.execute('worker')
        self.validate.assert_not_called();self.process.kill.assert_called_once()
        self.assertEqual(self.outputs(),[]);self.assert_clean()

    def test_revocation_during_validation_never_publishes(self):
        with self.assertRaises(ProfileLocked):self.execute('validation')
        self.validate.assert_called_once();self.assertEqual(self.outputs(),[]);self.assert_clean()

    def test_revocation_during_rename_removes_only_owned_final(self):
        with self.assertRaises(ProfileLocked):self.execute('rename')
        self.assertEqual(self.outputs(),[]);self.assert_clean()

    def test_foreign_replacement_survives_revoked_publication_cleanup(self):
        with self.assertRaises(ProfileLocked):self.execute('foreign')
        outputs=self.outputs();self.assertEqual(len(outputs),1)
        self.assertEqual(outputs[0].read_bytes(),b'foreign sentinel');self.assert_clean()

    def test_preexisting_output_is_not_replaced(self):
        with self.assertRaises(FileExistsError):self.execute('collision')
        outputs=self.outputs();self.assertEqual(len(outputs),1)
        self.assertEqual(outputs[0].read_bytes(),b'foreign preexisting output');self.assert_clean()

    def test_success_publishes_inside_captured_profile(self):
        result=self.execute();output=Path(result['files'][0])
        self.assertTrue(output.is_relative_to(self.workspace/'Outputs'))
        self.assertEqual(output.read_bytes(),b'generated media');self.assert_clean()

    def test_legacy_root_retains_original_output_layout(self):
        result=self.execute(legacy=True);output=Path(result['files'][0])
        self.assertTrue(output.is_relative_to(self.root/'Outputs/Videos/MuseTalk'))
        self.assertEqual(output.read_bytes(),b'generated media')
        self.assertFalse(self.part.exists());self.job.close.assert_called_once()


if __name__=='__main__':unittest.main()
