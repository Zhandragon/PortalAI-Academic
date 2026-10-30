"""Regression coverage for retired runtime references and installer forwarding."""
import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from voice_bridge import VoiceBridge
import audit_specialist_filters as audit


def checkpoint_reader():
    # Exercise the actual worker helper without importing its model-dependent
    # startup code. Source-only checkouts need no vendor packages for this test.
    source=ROOT/'Voice/Qwen3-TTS/qwen_tts_runner.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_checkpoint_reads')
    namespace={'contextmanager':contextmanager,'os':os}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
    return namespace['_checkpoint_reads']


class QwenConsolidationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='Qwen portable fixture ')
        self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.voice=self.root/'Voice/Qwen3-TTS'
        self.bridge=object.__new__(VoiceBridge);self.bridge.root=self.root;self.bridge.voice_root=self.voice

    def file(self,relative,text=''):
        p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p

    @unittest.skipUnless(os.name=='nt','Windows runtime routing')
    def test_active_layer_needs_no_legacy_or_venv_launcher(self):
        expected=self.file('Runtime/BootstrapPython/python.exe')
        self.file('Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts/__init__.py')
        self.assertEqual(self.bridge._python(),expected)

    @unittest.skipUnless(os.name=='nt','Windows runtime routing')
    def test_missing_bootstrap_never_uses_old_or_external_pointer(self):
        external=self.file('outside/python.exe')
        self.file('Voice/Qwen3-TTS/python_relative.txt',str(external))
        self.file('Voice/Qwen3-TTS/.venv/Scripts/python.exe')
        self.file('Voice/Qwen3-TTS/python/cpython-old/python.exe')
        self.file('Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts/__init__.py')
        with self.assertRaisesRegex(FileNotFoundError,'BootstrapPython'):self.bridge._python()

    @unittest.skipUnless(os.name=='nt','Windows runtime routing')
    def test_missing_active_packages_fails_even_with_old_packages(self):
        self.file('Runtime/BootstrapPython/python.exe')
        self.file('Voice/Qwen3-TTS/python/cpython-old/Lib/site-packages/qwen_tts/__init__.py')
        with self.assertRaisesRegex(FileNotFoundError,'package|site-packages'):self.bridge._python()

    def test_auditor_uses_active_tree(self):
        relative='Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts'
        self.file(relative+'/__init__.py','ACTIVE = True')
        self.file('Voice/Qwen3-TTS/python/old/qwen_tts/__init__.py','OLD = True')
        with patch.object(audit,'ROOT',self.root),patch.object(audit,'ROUTES',{'voice':[]}),patch.object(audit,'TREES',{'voice':relative}):
            rows=audit.audit()['source_evidence'][0]['files']
        self.assertEqual([r['path'] for r in rows],[relative+'/__init__.py'])

    def test_auditor_fails_on_missing_or_empty_package(self):
        for create in (False,True):
            if create:(self.root/'missing').mkdir()
            with patch.object(audit,'ROOT',self.root),patch.object(audit,'ROUTES',{'voice':[]}),patch.object(audit,'TREES',{'voice':'missing'}):
                with self.assertRaises(FileNotFoundError):audit.audit()

    @unittest.skipUnless(os.name=='nt','Windows checkpoint compatibility')
    def test_checkpoint_reader_uses_pread_and_restores_after_failure(self):
        reader=checkpoint_reader()
        calls=[]
        def safe_open(path,framework,device='cpu',*,backend='mmap'):
            calls.append((path,framework,device,backend));return object()
        module=SimpleNamespace(safe_open=safe_open)
        with patch.dict(sys.modules,{'transformers':SimpleNamespace(modeling_utils=module)}):
            with self.assertRaisesRegex(RuntimeError,'fixture'):
                with reader():
                    module.safe_open('local.safetensors',framework='pt',device='cuda:0')
                    raise RuntimeError('fixture')
        self.assertIs(module.safe_open,safe_open)
        self.assertEqual(calls,[('local.safetensors','pt','cuda:0','pread')])

    def test_checkpoint_reader_preserves_older_reader_api(self):
        reader=checkpoint_reader()
        def safe_open(path,framework):return 'unchanged'
        module=SimpleNamespace(safe_open=safe_open)
        with patch.dict(sys.modules,{'transformers':SimpleNamespace(modeling_utils=module)}):
            with reader():
                self.assertIs(module.safe_open,safe_open)
                self.assertEqual(module.safe_open('local','pt'),'unchanged')

    @unittest.skipUnless(os.name=='nt','PowerShell forwarding')
    def test_legacy_installer_forwards_root_flags_and_exit_status(self):
        legacy=self.file('Setup/Legacy/Install_Qwen3_TTS_Portable.ps1')
        shutil.copy2(ROOT/'Setup/Legacy/Install_Qwen3_TTS_Portable.ps1',legacy)
        self.file('Setup/Qwen3-TTS/Install_or_Repair_Qwen3_TTS.ps1',
            "param([string]$Root,[switch]$SkipCustomVoice,[switch]$VerifyOnly)\n"
            "@{root=$Root;skip=[bool]$SkipCustomVoice;verify=[bool]$VerifyOnly}|ConvertTo-Json -Compress\nexit 17\n")
        for explicit in (False,True):
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(legacy),'-SkipCustomVoice','-VerifyOnly']
            if explicit:command+=['-Root',str(self.root/'recipient with spaces')]
            cp=subprocess.run(command,capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(cp.returncode,17,cp.stderr)
            row=json.loads(cp.stdout);self.assertTrue(row['skip'] and row['verify'])
            self.assertEqual(Path(row['root']),self.root/'recipient with spaces' if explicit else self.root)
        self.assertFalse((self.voice/'python').exists())


if __name__=='__main__':unittest.main()
