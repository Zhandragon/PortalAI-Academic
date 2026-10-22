"""Repair pins, hostile/missing backups, cancellation and native fallback."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,unittest,zipfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import executable_recovery as r
import chat_model_switch

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.name='LLM/backends/windows-cpu/llama-server.exe';self.path=self.root/self.name
        self.path.parent.mkdir(parents=True);self.data=b'harmless fixture, never executed';self.path.write_bytes(self.data)
        self.row=dict(path=self.name,bytes=len(self.data),sha256=hashlib.sha256(self.data).hexdigest())
    def tearDown(self):self.tmp.cleanup()
    def seed(self):r.register(self.root,[self.row],'verified fixture plan')
    def test_only_verified_installation_files_are_backed_up(self):
        self.path.write_bytes(b'different')
        with self.assertRaisesRegex(ValueError,'installation pin'):self.seed()
        self.assertFalse((self.root/r.FOLDER/'manifest.json').exists())
    def test_missing_file_requires_explicit_restore_and_matches_pin(self):
        self.seed();self.path.unlink();report=r.inspect(self.root,True)
        self.assertFalse(self.path.exists());self.assertTrue(report['missing'][0]['backup_verified'])
        self.assertEqual(r.restore(self.root,[self.name])['restored'],[self.name]);self.assertEqual(self.path.read_bytes(),self.data)
    def test_existing_file_is_never_overwritten(self):
        self.seed();self.path.write_bytes(b'user replacement')
        self.assertTrue(r.restore(self.root,[self.name])['errors']);self.assertEqual(self.path.read_bytes(),b'user replacement')
    def test_corrupt_or_unavailable_backup_leaves_target_absent(self):
        self.seed();self.path.unlink();backup=r._archive(self.root,self.row)
        backup.write_bytes(b'bad backup')
        self.assertFalse(r.inspect(self.root,True)['missing'][0]['backup_available'])
        self.assertTrue(r.restore(self.root,[self.name])['errors']);self.assertFalse(self.path.exists())
        backup.unlink();self.assertTrue(r.restore(self.root,[self.name])['errors'])
    def test_cancel_before_or_during_copy_keeps_missing_target(self):
        self.seed();self.path.unlink()
        for at in (1,3):
            calls=[]
            def guard():
                calls.append(1)
                if len(calls)==at:raise RuntimeError('Stop')
            with self.assertRaisesRegex(RuntimeError,'Stop'):r.restore(self.root,[self.name],guard)
            self.assertFalse(self.path.exists())
    def test_paths_cannot_escape_or_select_private_data(self):
        for name in ('../evil.exe','/evil.exe','Tools/../evil.exe','C:/evil.exe','Tools/x.exe:stream','Tools/NUL.exe','Tools/x. /a.exe'):
            with self.assertRaises(ValueError):r.checked(self.root,name)
        self.assertFalse(r.eligible('Private/Users/x/Workspace/Tools/secret.exe'))
        self.assertFalse(r.eligible('Tools/Cache/download.exe'))
    def test_archive_members_and_checksums_are_enforced(self):
        self.seed();self.path.unlink();backup=r._archive(self.root,self.row)
        with zipfile.ZipFile(backup,'w') as z:z.writestr('../evil.exe',self.data)
        self.assertTrue(r.restore(self.root,[self.name])['errors']);self.assertFalse(self.path.exists())
        with zipfile.ZipFile(backup,'w') as z:z.writestr('file',b'x'*len(self.data))
        self.assertTrue(r.restore(self.root,[self.name])['errors']);self.assertFalse(self.path.exists())
    def test_deduplicated_backups_track_only_installed_paths(self):
        other=self.root/'LLM/backends/windows-vulkan/llama-server.exe';other.parent.mkdir(parents=True);other.write_bytes(self.data)
        r.register(self.root,[self.row,{**self.row,'path':other.relative_to(self.root).as_posix()},{**self.row,'path':'Tools/absent.exe'}],'fixture')
        self.assertEqual(len(list((self.root/r.FOLDER).glob('*.zip'))),1);self.assertEqual(r.inspect(self.root)['registered'],2)
    def test_avast_evidence_only_matches_exact_managed_path(self):
        self.seed();self.path.unlink();xml=self.root/'fixture.xml'
        xml.write_text('<Chest><ChestEntry><OrigFolder>'+str(self.path.parent)+'</OrigFolder><OrigFileName>llama-server.exe</OrigFileName><Virus>IDP.Generic</Virus></ChestEntry><ChestEntry><OrigFolder>C:/Unrelated</OrigFolder><OrigFileName>secret.exe</OrigFileName></ChestEntry></Chest>')
        evidence=r.avast_evidence(self.root,[self.row],xml)
        self.assertEqual(evidence,{self.name:'Avast quarantine record: IDP.Generic'})
        xml.write_text('<!DOCTYPE a []><Chest/>');self.assertEqual(r.avast_evidence(self.root,[self.row],xml),{})
    def test_missing_backups_never_trigger_download_or_execute(self):
        self.seed();self.path.unlink();r._archive(self.root,self.row).unlink()
        with patch('subprocess.Popen') as launch:
            self.assertTrue(r.restore(self.root,[self.name])['errors']);launch.assert_not_called()
    @unittest.skipUnless(os.name=='nt','Windows independent repair')
    def test_standalone_repair_works_without_python_or_portalai_launcher(self):
        self.seed();self.path.unlink();script=ROOT/'Repair PortalAI.exe'
        result=subprocess.run([str(script),'--root',str(self.root),'--check'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('llama-server.exe',result.stdout);self.assertFalse(self.path.exists())
        result=subprocess.run([str(script),'--root',str(self.root),'--restore'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(self.path.read_bytes(),self.data)
        self.assertIn('Re-enable antivirus',result.stdout)
    def test_model_spawn_creates_missing_profile_media_log_directory(self):
        logdir=self.root/'Private/Users/fixture/Workspace/Cache/MediaWorkers'
        with patch('media_paths.media_runtime',return_value=logdir),patch.object(chat_model_switch,'portable_env',return_value={}),patch('subprocess.Popen') as launch:
            chat_model_switch._spawn(self.root,['fixture executable'])
        self.assertTrue((logdir/'chat_effort_model.log').is_file());launch.assert_called_once()

if __name__=='__main__':unittest.main(verbosity=2)
