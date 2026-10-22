import ast
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'ControlCenter')); sys.path.insert(0, str(ROOT/'Agent'))
from account_gate import GUIAccountGate


class AccountGateTests(unittest.TestCase):
    def gate(self):
        gate = GUIAccountGate.__new__(GUIAccountGate)
        gate.root=ROOT; gate.session=SimpleNamespace(user_id='1'*32); gate.locked=True
        gate.gui_jobs=Mock(); gate.gui_jobs.wait.return_value={'stopped':True}
        gate.controller=Mock(); gate.controller.jobs.wait.return_value={'stopped':True}
        gate.chat=Mock(); gate.chat.wait_for_writers.return_value={'stopped':True}
        gate.stop_owned=Mock(return_value={'stopped':True}); gate.runtime=Mock()
        gate._explicit_stop_verified=False
        return gate

    def test_background_timeout_cannot_be_sealed_or_reported_stopped(self):
        gate=self.gate(); gate.chat.wait_for_writers.return_value={'stopped':False}
        with self.assertRaisesRegex(RuntimeError,'chat writers'): gate._quiesce(gate.session,None)
        gate.runtime.close.assert_not_called()

    def test_rechecks_owned_processes_after_all_writers_join(self):
        gate=self.gate(); calls=[]
        gate.stop_owned.side_effect=lambda *_:(calls.append('stop') or {'stopped':True})
        gate.gui_jobs.wait.side_effect=lambda *_:(calls.append('gui') or {'stopped':True})
        gate.controller.jobs.wait.side_effect=lambda *_:(calls.append('accounts') or {'stopped':True})
        gate.chat.wait_for_writers.side_effect=lambda *_:(calls.append('chat') or {'stopped':True})
        self.assertTrue(gate._quiesce(gate.session,None)['stopped'])
        self.assertEqual(calls,['stop','gui','accounts','chat','stop'])

    def test_startup_does_not_disarm_missions(self):
        gate=self.gate(); gate.gui_jobs=None
        with patch('account_gate.subprocess.run') as run:
            gate._quiesce(gate.session,None)
        run.assert_not_called()

    def test_explicit_exit_requires_json_success_before_sealing(self):
        gate=self.gate()
        with patch('account_gate.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"success":false}')):
            with self.assertRaises(RuntimeError): gate.close()
        gate.runtime.close.assert_not_called()
        with patch('account_gate.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"success":true}')) as run:
            gate.close(); gate.close()
        self.assertEqual(run.call_count,1)
        self.assertNotIn('PORTALAI_ACCOUNT_UNLOCK',run.call_args.kwargs['env'])
        self.assertEqual(gate.runtime.close.call_count,2)

    def test_presentation_failure_still_closes_all_writer_gates_and_cancels_chat(self):
        gate=self.gate();gate.app=Mock();gate.colors={}
        with patch('account_presentation.lock_account_surfaces',side_effect=RuntimeError('synthetic presentation failure')):
            with self.assertRaises(RuntimeError):gate.lock()
        self.assertTrue(gate.locked)
        gate.controller.jobs.close.assert_called_once();gate.gui_jobs.close.assert_called_once()
        gate.chat.shutdown.assert_called_once();gate.app.withdraw.assert_called_once()
        gate.runtime.close.assert_not_called()

    def test_shutdown_presentation_status_failure_cannot_abort_verification(self):
        gate=self.gate();gate.on_shutdown_status=Mock(side_effect=RuntimeError('synthetic UI unavailable'))
        self.assertTrue(gate._quiesce(gate.session,None)['stopped'])
        self.assertEqual(gate.stop_owned.call_count,2)
        self.assertTrue(gate.on_shutdown_status.called)

    def test_login_gate_precedes_every_private_gui_consumer(self):
        source=(ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        guard=next(n for n in main.body if isinstance(n,ast.If) and any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=='account_gate' and call.func.attr=='login' for call in ast.walk(n.test)))
        private_calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and getattr(n.func,'id',None) in ('NativeChat','SettingsPage','Missions')]
        self.assertTrue(private_calls)
        self.assertTrue(all(n.lineno>guard.end_lineno for n in private_calls))
        self.assertIn('if not account_gate.login():',ast.get_source_segment(source,guard))
        self.assertTrue(any(isinstance(n,ast.Return) for n in guard.body))
        self.assertFalse(any(isinstance(n,ast.If) and any(isinstance(c,ast.Call) and getattr(c.func,'id',None)=='accounts_enabled' for c in ast.walk(n.test)) for n in main.body))


if __name__=='__main__': unittest.main()
