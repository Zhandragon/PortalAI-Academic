"""Test the narrow ROCm loader scope without importing any tensor libraries."""
import ast
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
from comfy_safetensors import windows_rocm_cpu_reader


class ScopedReaderTests(unittest.TestCase):
    def modules(self):
        module=ModuleType('safetensors');module.safe_open=Mock(return_value='reader')
        torch=ModuleType('safetensors.torch');torch.safe_open=Mock(return_value='torch-reader')
        return module,torch

    def test_cpu_pt_only_defaults_to_public_pread_and_explicit_choices_survive(self):
        module,torch=self.modules();original=module.safe_open;torch_original=torch.safe_open
        with patch.dict(sys.modules,{'safetensors':module,'safetensors.torch':torch}):
            with windows_rocm_cpu_reader(True,windows=True):
                for framework in ('pt','torch','pytorch'):
                    module.safe_open('weights',framework=framework,device='cpu')
                    original.assert_called_with('weights',framework=framework,device='cpu',backend='pread')
                module.safe_open('weights','pt')
                original.assert_called_with('weights','pt',backend='pread')
                module.safe_open('weights',framework='pt',device=None)
                original.assert_called_with('weights',framework='pt',device=None,backend='pread')
                module.safe_open('weights',framework='pt',device='cuda')
                original.assert_called_with('weights',framework='pt',device='cuda')
                module.safe_open('weights',framework='np',device='cpu')
                original.assert_called_with('weights',framework='np',device='cpu')
                torch.safe_open('weights',framework='pt',device='cpu',backend='mmap')
                torch_original.assert_called_with('weights',framework='pt',device='cpu',backend='mmap')
                # 0.8.0 currently requires a keyword, but invalid or future
                # positional calls must pass through without duplicate kwargs.
                module.safe_open('weights','pt','cpu','mmap')
                original.assert_called_with('weights','pt','cpu','mmap')
                torch.safe_open('weights','pt','cpu','pread')
                torch_original.assert_called_with('weights','pt','cpu','pread')
            self.assertIs(module.safe_open,original);self.assertIs(torch.safe_open,torch_original)

    def test_linux_and_nvidia_are_untouched(self):
        module,torch=self.modules();original=module.safe_open;torch_original=torch.safe_open
        with patch.dict(sys.modules,{'safetensors':module,'safetensors.torch':torch}):
            for rocm,windows in ((False,True),(True,False),(False,False)):
                with windows_rocm_cpu_reader(rocm,windows=windows):
                    self.assertIs(module.safe_open,original);self.assertIs(torch.safe_open,torch_original)

    def test_late_torch_alias_restored_even_on_failure(self):
        module,_=self.modules();original=module.safe_open
        with patch.dict(sys.modules,{'safetensors':module}):
            sys.modules.pop('safetensors.torch',None)
            with self.assertRaisesRegex(RuntimeError,'synthetic failure'):
                with windows_rocm_cpu_reader(True,windows=True):
                    self.assertNotIn('safetensors.torch',sys.modules)
                    late=ModuleType('safetensors.torch');late.safe_open=module.safe_open
                    sys.modules['safetensors.torch']=late
                    raise RuntimeError('synthetic failure')
            self.assertIs(module.safe_open,original);self.assertIs(late.safe_open,original)

    def test_no_early_torch_import_and_entry_scopes_comfy_execution(self):
        source=(ROOT/'Agent/comfy_safetensors.py').read_text();tree=ast.parse(source)
        imports=[alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
        self.assertNotIn('torch',imports);self.assertNotIn('safetensors.torch',imports)
        entry=ast.parse((ROOT/'Agent/comfy_amd_entry.py').read_text())
        contexts=[node for node in ast.walk(entry) if isinstance(node,ast.With) and
                  any(isinstance(item.context_expr,ast.Call) and isinstance(item.context_expr.func,ast.Name)
                      and item.context_expr.func.id=='windows_rocm_cpu_reader' for item in node.items)]
        self.assertEqual(len(contexts),1)
        self.assertTrue(any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                            and node.func.attr=='run_path' for node in ast.walk(contexts[0])))


if __name__=='__main__':unittest.main()
