"""Academic policy must survive coding focus and disabled optional manuals."""
from pathlib import Path
import importlib.util,sys,unittest
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import native_chat

class EditionPromptScopeTests(unittest.TestCase):
    @unittest.skipUnless((ROOT/'Agent/academic_policy.py').is_file(),'Full edition has no Academic policy')
    def test_academic_policy_survives_each_tool_scope_without_manual(self):
        from academic_policy import POLICY_TEXT
        for scope in ('all','coding','maintenance'):
            panel=SimpleNamespace(root=ROOT,settings={'use_master_instructions':False},
                store=SimpleNamespace(custom_instructions=lambda:''),_request_tool_scope=scope)
            with patch('runtime_policy.load_effective_policy',return_value={}):
                result=native_chat.NativeChat.system_prompt(panel)
            self.assertEqual(result.count(POLICY_TEXT),1,scope)

if __name__=='__main__':unittest.main()
