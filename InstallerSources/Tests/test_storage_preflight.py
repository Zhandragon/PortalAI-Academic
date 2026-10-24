import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT/'Windows'))
import installer_storage as storage
BASE=ROOT
BASH=(shutil.which('bash') if os.name!='nt' else r'C:\Program Files\Git\bin\bash.exe')

class Accounting(unittest.TestCase):
    def test_downloads_with_shared_hash_are_counted_once(self):
        a={'sha256':'a'*64,'bytes':20}
        r=storage.requirement([{'bytes':100}],[a,a],4096)
        self.assertEqual(r['download_bytes'],20)
        self.assertEqual(r['required_bytes'],100+20+2*4095+storage.GIB)

    def test_large_allocation_units_and_large_models(self):
        files=[{'bytes':1},{'bytes':40*storage.GIB}]
        self.assertEqual(storage.requirement(files,[],65536)['required_bytes'],41*storage.GIB+1+2*65535)

    def test_conflicting_download_sizes_fail(self):
        with self.assertRaises(ValueError):storage.requirement([], [{'sha256':'x','bytes':1},{'sha256':'x','bytes':2}])

    def test_missing_nested_directory_uses_existing_destination_parent_without_writing(self):
        with tempfile.TemporaryDirectory(dir=HERE) as t:
            target=Path(t)/'space in name'/'new'
            self.assertEqual(storage.existing_directory(target),Path(t))
            self.assertFalse(target.parent.exists())

    def test_destination_file_is_rejected(self):
        with tempfile.NamedTemporaryFile(dir=HERE) as f:
            with self.assertRaises(OSError):storage.existing_directory(f.name)

    def test_low_space_reports_available_required_and_shortfall(self):
        usage=shutil._ntuple_diskusage(10*storage.GIB,10*storage.GIB-1,1)
        with patch.object(storage,'allocation_unit',return_value=4096),patch.object(storage.shutil,'disk_usage',return_value=usage):
            with self.assertRaisesRegex(OSError,'required.*available.*Need.*more'):storage.check_space(HERE,[{'bytes':5*storage.GIB}],[])

    def test_unknown_free_space_fails_closed(self):
        with patch.object(storage,'allocation_unit',return_value=4096),patch.object(storage.shutil,'disk_usage',side_effect=OSError('disconnected')):
            with self.assertRaisesRegex(OSError,'disconnected'):storage.check_space(HERE,[],[])

    def test_exact_free_space_passes(self):
        need=storage.requirement([{'bytes':30}],[],4096)['required_bytes']
        with patch.object(storage,'allocation_unit',return_value=4096),patch.object(storage.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(need,0,need)):
            self.assertEqual(storage.check_space(HERE,[{'bytes':30}],[])['shortfall_bytes'],0)

    def test_real_destination_query(self):
        self.assertGreater(storage.allocation_unit(HERE),0)
        self.assertIn('available',storage.check_space(HERE,[],[])['message'])

class EngineBoundary(unittest.TestCase):
    def load(self,edition):
        p=BASE/'Windows/installer_core.py'
        spec=importlib.util.spec_from_file_location('core_'+edition,p)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_all_editions_stop_before_download_or_extraction_when_insufficient(self):
        for edition in ['current']:
            with self.subTest(edition=edition),tempfile.TemporaryDirectory(dir=HERE) as t:
                core=self.load(edition);package=Path(t)
                with patch.object(core,'read_manifest',return_value={}),patch.object(core,'plan',return_value=([],[],[{'dest':'PortalAI Windows/a','bytes':1}],100)),patch.object(storage,'check_space',side_effect=OSError('Not enough disk space')),patch.object(core,'fetch') as fetch,patch.object(core,'extract_allowlist') as extract:
                    with self.assertRaisesRegex(OSError,'Not enough disk space'):core.install(package,package,[])
                    fetch.assert_not_called();extract.assert_not_called()
                    self.assertEqual(list(package.iterdir()),[])

    def test_space_is_rechecked_after_downloads_before_extraction(self):
        for edition in ['current']:
            with self.subTest(edition=edition),tempfile.TemporaryDirectory(dir=HERE) as t:
                core=self.load(edition);package=Path(t);(package/'payload.zip').write_bytes(b'')
                manifest={'payload':{'file':'payload.zip','bytes':0,'sha256':'x'}}
                with patch.object(core,'read_manifest',return_value=manifest),patch.object(core,'plan',return_value=([],[{'id':'fixture','bytes':0}],[{'dest':'PortalAI Windows/a','bytes':1}],100)),patch.object(core,'sha256',return_value='x'),patch.object(storage,'check_space',side_effect=[{'message':'enough'},OSError('space consumed by another process')]) as check,patch.object(core,'fetch',return_value=package/'download') as fetch,patch.object(core,'extract_allowlist') as extract:
                    with self.assertRaisesRegex(OSError,'space consumed'):core.install(package,package,[])
                    self.assertEqual(check.call_count,2);fetch.assert_called_once();extract.assert_not_called()
                    self.assertFalse(any(p.name.startswith('.PortalAI-installing') for p in package.iterdir()))

@unittest.skipUnless(BASH and Path(BASH).exists(), 'Bash is needed for native helper tests')
class ShellBoundary(unittest.TestCase):
    def run_helper(self,df_output,base='100',floor='50',output='100',percent='10'):
        with tempfile.TemporaryDirectory(dir=HERE) as t:
            folder=Path(t);bin=folder/'bin';bin.mkdir()
            (bin/'df').write_text("#!/bin/sh\nprintf '%s\\n' '"+df_output+"'\n",encoding='utf-8',newline='\n')
            (bin/'df').chmod(0o755)
            posix=lambda p: ('/'+p.drive[0].lower()+p.as_posix()[2:]) if p.drive else str(p)
            return subprocess.run([BASH,'-c','PATH="$1:/usr/bin:/bin"; export PATH; shift; exec sh "$@"','fixture',posix(bin),posix(ROOT/'Linux/storage-preflight.sh'),posix(folder/'new folder'),base,floor,output,percent],capture_output=True,text=True)

    def test_shell_low_space(self):
        r=self.run_helper('Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture 1000 950 50 95% /target')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('Not enough disk space',r.stdout)

    def test_shell_exact_boundary_and_reserve(self):
        r=self.run_helper('Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture 1000 700 300 70% /target')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_shell_unknown_space(self):
        r=self.run_helper('Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture invalid 0 unknown 0% /target')
        self.assertEqual(r.returncode,2,r.stdout+r.stderr);self.assertIn('Cannot determine',r.stdout)

    def test_shell_invalid_budget(self):
        r=self.run_helper('',base='unknown')
        self.assertEqual(r.returncode,2)

class DownloadDiagnostics(unittest.TestCase):
    def core(self):
        return EngineBoundary().load('current')

    def test_certificate_error_identifies_artifact_and_retains_verification(self):
        import ssl, urllib.error, threading
        core=self.core()
        error=urllib.error.URLError(ssl.SSLCertVerificationError('certificate has expired'))
        item={'id':'fixture-download','url':'https://example.invalid/file'}
        with patch.object(core,'_fetch_one',side_effect=error):
            with self.assertRaisesRegex(core.InstallError,'fixture-download.*https://example.invalid/file.*verification remains enabled'):
                core.fetch(item,HERE,threading.Event(),lambda *args:None)

    def test_verified_bundled_archive_never_uses_network(self):
        import hashlib,threading
        core=self.core()
        with tempfile.TemporaryDirectory(dir=HERE) as t:
            folder=Path(t);data=b'verified bundled download';path=folder/'tool.zip';path.write_bytes(data)
            item={'id':'fixture','bundled_file':'tool.zip','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            with patch.object(core,'fetch') as fetch:
                self.assertEqual(core.download_artifact(item,folder,folder/'cache',threading.Event(),lambda *args:None),path)
                fetch.assert_not_called()

    def test_corrupt_bundled_archive_stops_without_network_fallback(self):
        import threading
        core=self.core()
        with tempfile.TemporaryDirectory(dir=HERE) as t:
            folder=Path(t);(folder/'tool.zip').write_bytes(b'bad')
            item={'id':'fixture','bundled_file':'tool.zip','bytes':3,'sha256':'0'*64}
            with patch.object(core,'fetch') as fetch:
                with self.assertRaisesRegex(core.InstallError,'failed verification'):
                    core.download_artifact(item,folder,folder/'cache',threading.Event(),lambda *args:None)
                fetch.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
