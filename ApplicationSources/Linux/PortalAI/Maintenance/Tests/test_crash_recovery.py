import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
spec=importlib.util.spec_from_file_location('startup_crash',ROOT/'Launchers/Start_PortableAI_Native_v15_133.py')
startup=importlib.util.module_from_spec(spec);spec.loader.exec_module(startup)


class CrashRecoveryTests(unittest.TestCase):
    def test_missing_executable_error_excludes_historical_log(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);log=folder/'log'
            old=b'Old successful model warning\n';log.write_bytes(old+b'Current failed startup\n')
            result=startup.startup_failure(folder/'llama-server.exe',0,log,len(old))
            self.assertIn('disappeared',result)
            self.assertIn('Current failed startup',result)
            self.assertNotIn('Old successful',result)

    def test_linux_rocm_uses_linux_compute_result(self):
        from workload_compatibility import require_workload
        fixture={'system':'Linux','machine':'x86_64','gpus':[],
                 'media_gpu':{'available':True,'compute_ok':True,'backend':'rocm'}}
        with patch('amd_runtime.probe',side_effect=AssertionError('Windows runtime probe')):
            for command in ('lip-sync','video-edit','video-sfx'):require_workload(command,fixture)
        fixture['media_gpu']['compute_ok']=False
        with self.assertRaises(RuntimeError):require_workload('lip-sync',fixture)

    def test_linux_cuda_voice_requires_compute_probe(self):
        from tts_policy import qwen_preflight
        hw={'system':'Linux','gpus':[{'index':0,'backend':'cuda','total_bytes':24*1024**3}]}
        with self.assertRaises(RuntimeError):qwen_preflight(hw)
        hw['media_gpu']={'compute_ok':True};qwen_preflight(hw)


if __name__=='__main__':unittest.main()
