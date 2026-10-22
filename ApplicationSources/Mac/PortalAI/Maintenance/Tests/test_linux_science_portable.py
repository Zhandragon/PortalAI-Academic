"""Portable science process dispatch and MAFFT wrapper tests; no external programs run."""
import io
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'Agent')]
from Scientific import science_core as science
import mafft_linux


class LinuxScienceDispatchTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='Portal science path with spaces ')
        self.addCleanup(folder.cleanup);self.root=Path(folder.name).resolve()
        self.linux=self.root/'Runtime/MAFFT/linux-x64/mafft'
        self.windows=self.root/'Scientific/External/MAFFT/mafft.bat'
        for path in (self.linux,self.windows):path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
        self.addCleanup(patch.stopall)
        patch.object(science,'os',SimpleNamespace(name='posix')).start()
        self.which=patch.object(science.shutil,'which',return_value=None).start()
        self.run=patch.object(science.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'>a\nAC-G\n>b\nACCG\n','done')).start()

    def request(self):
        return science.op_genome_msa({'sequences':{'a':'acg','b':'accg'},'threads':2,'timeout':35},self.root)

    def test_linux_uses_native_payload_not_existing_windows_batch(self):
        self.assertEqual(science._find_mafft(self.root),str(self.linux))
        self.which.assert_not_called()
        result=self.request();command=self.run.call_args.args[0]
        self.assertEqual(command[:5],[str(self.linux),'--auto','--thread','2',result['input']])
        self.assertNotIn('shell',self.run.call_args.kwargs)
        self.assertEqual(self.run.call_args.kwargs['timeout'],35)
        self.assertEqual(Path(result['input']).read_text(),'>a\nACG\n>b\nACCG\n')
        self.assertEqual(Path(result['file']).read_text(),'>a\nAC-G\n>b\nACCG\n')

    def test_linux_missing_payload_does_not_fall_back_to_windows_batch(self):
        self.linux.unlink()
        self.assertIsNone(science._find_mafft(self.root))
        self.which.assert_called_once_with('mafft')
        with self.assertRaisesRegex(RuntimeError,'operating system'):self.request()
        self.run.assert_not_called()

    def test_windows_keeps_batch_quoting_for_paths_with_spaces(self):
        with patch.object(science,'os',SimpleNamespace(name='nt')):
            result=self.request()
        command=self.run.call_args.args[0]
        self.assertEqual(command[:4],['cmd.exe','/d','/s','/c'])
        self.assertEqual(command[4],subprocess.list2cmdline([str(self.windows),'--auto','--thread','2',result['input']]))

    def test_failed_alignment_does_not_publish_output(self):
        self.run.return_value=subprocess.CompletedProcess([],1,'partial','alignment failed')
        with self.assertRaisesRegex(RuntimeError,'alignment failed'):self.request()
        self.assertFalse((self.root/'Outputs/Science/genomics/msa.fasta').exists())

    def test_empty_alignment_is_not_reported_as_success(self):
        self.run.return_value=subprocess.CompletedProcess([],0,' \n','')
        with self.assertRaisesRegex(RuntimeError,'no alignment'):self.request()
        self.assertFalse((self.root/'Outputs/Science/genomics/msa.fasta').exists())

    def test_linux_kicad_does_not_select_windows_executable(self):
        pe=self.root/'Tools/KiCad/bin/kicad-cli.exe';pe.parent.mkdir(parents=True);pe.write_text('PE fixture')
        self.assertIsNone(science._find_kicad(self.root))
        native=self.root/'Runtime/KiCad/linux-x64/bin/kicad-cli'
        native.parent.mkdir(parents=True);native.write_text('ELF fixture')
        self.assertEqual(science._find_kicad(self.root),str(native))


class MafftWrapperTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='Portal MAFFT portable ')
        self.addCleanup(folder.cleanup);self.root=Path(folder.name).resolve()
        self.folder=self.root/'Cache/MAFFT/job';self.folder.mkdir(parents=True)
        self.payload=self.root/'Runtime/LinuxSystem/genomics'
        self.helpers=self.payload/'usr/lib/mafft/lib/mafft';self.helpers.mkdir(parents=True)
        (self.helpers/'version').write_bytes(b'\x7fELFfixture')
        (self.helpers/'unused.txt').write_text('not an executable')

    def test_private_helpers_use_bundled_loader_and_do_not_export_glibc(self):
        with patch.object(mafft_linux.subprocess,'check_output',return_value='cat\nawk\nsh\nbash\n') as probe, \
             patch.object(mafft_linux,'portable_env',return_value={'PATH':'/host-bin','LD_LIBRARY_PATH':'/unwanted'}):
            command,env=mafft_linux.command_environment(self.folder,self.root)
        loader=self.root/'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
        self.assertEqual(command[0],str(loader));self.assertEqual(command[-1],str(self.payload/'usr/bin/mafft'))
        self.assertNotIn('LD_LIBRARY_PATH',env)
        self.assertEqual(env['MAFFT_TMPDIR'],str(self.folder))
        self.assertEqual(env['MAFFT_BINARIES'],str(self.folder/'bin'))
        self.assertEqual(env['PATH'],str(self.folder/'bin')+':/host-bin')
        self.assertEqual(env['PERL5LIB'],':'.join(str(self.payload/rel) for rel in
            ('usr/share/perl/5.40','usr/lib/x86_64-linux-gnu/perl/5.40')))
        body=(self.folder/'bin/version').read_text()
        self.assertIn(shlex.quote(str(loader)),body)
        self.assertIn(shlex.quote(str(self.helpers/'version')),body)
        self.assertTrue(body.rstrip().endswith('"$@"'))
        self.assertFalse((self.folder/'bin/unused.txt').exists())
        self.assertNotIn('shell',probe.call_args.kwargs)
        self.assertEqual(probe.call_args.args[0][-1],'--list')

    def test_main_uses_ssd_progress_file_and_bounds_reported_progress(self):
        captured={};stderr=io.BytesIO()
        def environment(folder):
            captured['folder']=Path(folder)
            return ['bundled-mafft'],{'PATH':'private'}
        def run(command,env):
            captured['command']=command
            Path(command[2]).write_bytes(b'a'*9000)
            return 7
        with patch.object(mafft_linux,'ROOT',self.root),patch.object(sys,'platform','linux'), \
             patch.object(sys,'argv',['mafft','--auto','input path.fa']), \
             patch.object(sys,'stderr',SimpleNamespace(buffer=stderr)), \
             patch.object(mafft_linux,'command_environment',side_effect=environment), \
             patch.object(mafft_linux.subprocess,'call',side_effect=run):
            self.assertEqual(mafft_linux.main(),7)
        self.assertEqual(captured['command'][0:2],['bundled-mafft','--progress'])
        self.assertEqual(captured['command'][3:],['--auto','input path.fa'])
        self.assertTrue(Path(captured['command'][2]).is_relative_to(self.root/'Cache/MAFFT'))
        self.assertEqual(len(stderr.getvalue()),8000)
        self.assertFalse(captured['folder'].exists())

    def test_main_cleans_job_folder_on_launch_failure(self):
        captured={}
        def environment(folder):captured['folder']=Path(folder);return ['bundled-mafft'],{}
        with patch.object(mafft_linux,'ROOT',self.root),patch.object(sys,'platform','linux'), \
             patch.object(sys,'argv',['mafft']),patch.object(mafft_linux,'command_environment',side_effect=environment), \
             patch.object(mafft_linux.subprocess,'call',side_effect=OSError('cannot start')):
            with self.assertRaisesRegex(OSError,'cannot start'):mafft_linux.main()
        self.assertFalse(captured['folder'].exists())


if __name__=='__main__':unittest.main()
