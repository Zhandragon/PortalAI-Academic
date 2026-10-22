"""Quick-chat effect boundary using a real disposable authenticated profile."""
import copy
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Maintenance/Tests'),str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
from test_native_ui_state import NativeStateTests
from native_chat_command import Controller,validate


class CommandTests(unittest.TestCase):
    def setUp(self):
        NativeStateTests.setUp(self)
        self.app.grab_current=lambda:None
        self.panel._check_login=self.export.profile.check
        self.panel.pending_attachments=[]
        self.panel.cancel_event=threading.Event()
        self.panel.stop_generation=Mock(side_effect=self.panel.cancel_event.set)
        self.panel.submit=Mock(return_value=True)
        self.controller=Controller(self.export)

    tearDown=NativeStateTests.tearDown

    def payload(self,op='send'):
        return {'request_id':uuid.uuid4().hex,'viewer':'c'*32,'operation':op,
                'binding':{'view':self.export.view,'epoch':self.export.epoch},
                'conversation':self.panel.session['id'],**({'text':'Synthetic quick chat'} if op=='send' else {})}

    def execute(self,p=None,seconds=2):
        return self.controller.execute(p or self.payload(),time.monotonic()+seconds)

    def test_acceptance_waits_for_worker_and_Tk(self):
        p=self.payload();receipt=self.execute(p)
        self.assertIsNone(receipt.poll())
        result=[]
        worker=threading.Thread(target=lambda:result.append(receipt.worker_ready(self.panel.cancel_event)))
        worker.start();self.assertTrue(receipt.ready.wait(1));self.assertFalse(receipt.decided.is_set())
        reply=receipt.poll();worker.join(1)
        self.assertEqual(reply,{'accepted':True,'request_id':p['request_id'],'operation':'send'})
        self.assertEqual(result,[True])
        self.assertIs(self.execute(p),receipt)
        self.panel.submit.assert_called_once()

    def test_conflicting_duplicate_refused(self):
        p=self.payload();self.execute(p);p['text']='Different synthetic text'
        with self.assertRaisesRegex(PermissionError,'conflicting'):self.execute(p)
        self.panel.submit.assert_called_once()

    def test_expired_stale_conversation_binding_loading_busy_attachments_modal(self):
        p=self.payload()
        with self.assertRaises(TimeoutError):self.execute(p,-1)
        for key,value in [('conversation','wrong'),('binding',{'view':'a'*32,'epoch':'b'*32})]:
            bad={**p,key:value}
            with self.assertRaises(PermissionError):self.execute(bad)
        for attr,value in [('_session_load_request',{}),('busy',True),('pending_attachments',[{}]),
                           ('_sheet_overlay',object()),('_inline_edit_frame',object())]:
            original=getattr(self.panel,attr,None);setattr(self.panel,attr,value)
            with self.assertRaises((PermissionError,RuntimeError)):self.execute()
            setattr(self.panel,attr,original)
        self.app.grab_current=lambda:object()
        with self.assertRaises(PermissionError):self.execute()
        self.panel.submit.assert_not_called()

    def test_real_logout_and_account_modal_refuse(self):
        self.app._portalai_account_dialogs=[SimpleNamespace(closed=False)]
        with self.assertRaises(PermissionError):self.execute()
        self.app._portalai_account_dialogs=[]
        self.backend.logout(self.session)
        with self.assertRaises(PermissionError):self.execute()
        self.panel.submit.assert_not_called()
        replacement=self.backend.login('NativeFixture','Synthetic-native-fixture-2026')
        self.runtime.replace_session(replacement)
        self.gate.session=replacement

    def test_changed_account_gate_and_late_rebind_cannot_accept(self):
        receipt=self.execute();receipt.ready.set()
        self.gate.session=object()
        with self.assertRaises(RuntimeError):receipt.poll()
        self.assertTrue(self.panel.cancel_event.is_set())
        self.gate.session=self.session;self.panel.cancel_event.clear()
        receipt=self.execute();receipt.ready.set();self.export.invalidate('switching')
        with self.assertRaises(RuntimeError):receipt.poll()
        self.assertIsNone(receipt.result)

    def test_model_failed_admission_and_expiry_never_ack(self):
        for reason in ('failure','expiry','cancel'):
            self.panel.cancel_event.clear();p=self.payload();receipt=self.execute(p)
            if reason=='failure':receipt.worker_finished()
            elif reason=='expiry':receipt.deadline=time.monotonic()-1
            else:receipt.ready.set();self.panel.cancel_event.set()
            with self.assertRaises(RuntimeError):receipt.poll()
            self.assertIsNone(receipt.result)
            duplicate=self.execute(p)
            with self.assertRaises(RuntimeError):duplicate.poll()
        self.assertEqual(self.panel.submit.call_count,3)

    def test_submit_rejection_and_exception_are_not_receipts(self):
        self.panel.submit.return_value='break';p=self.payload()
        with self.assertRaises(RuntimeError):self.execute(p)
        with self.assertRaises(RuntimeError):self.execute(p)
        self.panel.submit.assert_called_once()
        self.panel.submit.side_effect=OSError('synthetic persistence failure')
        with self.assertRaises(OSError):self.execute()

    def test_stop_during_generation_only_bound_conversation(self):
        self.panel.busy=True;p=self.payload('stop')
        with self.assertRaises(PermissionError):self.execute({**p,'conversation':'different'})
        self.panel.stop_generation.assert_not_called()
        result=self.execute(p);self.assertTrue(result['accepted']);self.assertTrue(self.panel.cancel_event.is_set())
        self.assertEqual(self.execute(p),result);self.panel.stop_generation.assert_called_once()

    def test_cache_retirement_revokes_old_binding(self):
        p=self.payload('stop');self.execute(p)
        for i in range(255):self.controller.receipts[str(i)]=(None,None)
        with self.assertRaisesRegex(RuntimeError,'fresh_binding'):self.execute(self.payload('stop'))
        self.assertEqual(len(self.controller.receipts),0)
        self.export.tick()
        with self.assertRaises(PermissionError):self.execute(p)

    def test_strict_payload_and_unicode_bounds(self):
        p=self.payload();validate(p)
        for text in ('', ' ', 'x'*8193, '\ud800'):
            with self.assertRaises(ValueError):validate({**p,'text':text})
        validate({**p,'text':'\U0001f600'*8192})
        for bad in ({**p,'extra':1},{**p,'viewer':'bad'}, {**p,'binding':{}}, {**p,'operation':'eval'},
                    {**self.payload('stop'),'text':'unexpected'}):
            with self.assertRaises(ValueError):validate(bad)

    def test_attachment_opt_in_keeps_account_dialog_and_late_lock_guards(self):
        self.panel.pending_attachments=[{'name':'synthetic.png'}]
        self.app._portalai_account_dialogs=[SimpleNamespace(closed=False)]
        with self.assertRaises(PermissionError):
            self.execute({**self.payload(),'include_pending_attachments':True})
        self.panel.submit.assert_not_called()
        self.app._portalai_account_dialogs=[]
        self.export.tick()
        receipt=self.execute({**self.payload(),'include_pending_attachments':True})
        receipt.ready.set();self.export.invalidate('switching')
        with self.assertRaises(RuntimeError):receipt.poll()
        self.assertIsNone(receipt.result)
        self.assertTrue(self.panel.cancel_event.is_set())

    def test_attachment_opt_in_real_submit_preserves_draft_and_deduplicates(self):
        # Exercise the installed NativeChat.submit with a real disposable
        # authenticated profile, but stub widgets, storage and inference.
        from native_chat import NativeChat
        import types
        panel=self.panel
        attachment={'name':'synthetic.png','size':8,'path':'synthetic.png'}
        panel.pending_attachments=[attachment]
        panel.settings={};panel._memory_job_running=False;panel.effort=None
        panel.COL={'gold':'gold'};panel.prompt=Mock();panel.store=Mock()
        for name in ('stop_btn','send_btn','session_list','model_lbl'):
            setattr(panel,name,Mock())
        for name in ('update_attachment_label','header','chat_insert','_set_llm_dot',
                     'refresh_sessions_labels_only','update_token_label'):
            setattr(panel,name,Mock())
        panel._thread=Mock(return_value=Mock())
        panel.submit=types.MethodType(NativeChat.submit,panel)
        p={**self.payload(),'include_pending_attachments':True}
        before=len(panel.session['messages'])
        with patch('native_chat_timers_v15_128e._begin_response'):
            receipt=self.execute(p)
        self.assertEqual(len(panel.session['messages']),before+1)
        self.assertEqual(panel.session['messages'][-1]['attachments'],[attachment])
        self.assertEqual(panel.session['messages'][-1]['content'],p['text'])
        self.assertEqual(panel.pending_attachments,[])
        panel.prompt.get.assert_not_called();panel.prompt.delete.assert_not_called()
        self.assertIsNone(receipt.poll())
        receipt.ready.set();self.assertTrue(receipt.poll()['accepted'])
        self.assertIs(self.execute(p),receipt)
        panel._thread.assert_called_once();panel.store.save_session.assert_called_once()
        self.assertEqual(len(panel.session['messages']),before+1)

    def test_slow_vision_loading_is_acknowledged_first_then_rechecked(self):
        from test_chat_handoff import panel as make_panel
        p=make_panel();p.root=self.root;p.session=self.panel.session;p.cancel_event=self.panel.cancel_event
        p._check_login=self.panel._check_login
        receipt=self.execute();self.export.chat=p
        loading=threading.Event();release=threading.Event()
        def prepare(cancel):
            self.assertTrue(receipt.result['accepted'])
            loading.set()
            self.assertTrue(release.wait(2))
            return not cancel.is_set()
        p.effort=SimpleNamespace(prepare_request=prepare,active_plan={})
        def work():
            try:p.agent_worker(p.session['id'],remote_admission=receipt)
            finally:receipt.worker_finished()
        with patch.object(p,'stream_completion',return_value=('Synthetic answer','',[])) as infer:
            worker=threading.Thread(target=work);worker.start()
            self.assertTrue(receipt.ready.wait(1))
            acknowledgement=receipt.poll()
            self.assertTrue(loading.wait(1))
            # Simulate model loading outliving the original delivery TTL.
            receipt.deadline=time.monotonic()-30
            receipt._monitor_preparation()
            self.assertFalse(p.cancel_event.is_set());infer.assert_not_called()
            release.set();self.assertTrue(receipt.prepared.wait(1))
            infer.assert_not_called()
            receipt._monitor_preparation();worker.join(2)
            self.assertFalse(worker.is_alive());infer.assert_called_once()
            self.assertEqual(p.session['messages'][-1]['content'],'Synthetic answer')
            self.assertEqual(receipt.poll(),acknowledgement)

    def test_preparation_still_revokes_on_modal_rebind_account_conversation_and_stop(self):
        for reason in ('modal','rebind','account','conversation','stop'):
            with self.subTest(reason=reason):
                self.panel.cancel_event.clear()
                receipt=self.execute();receipt.ready.set();ack=receipt.poll()
                view=self.export.view;sid=self.panel.session['id']
                if reason=='modal':self.app.grab_current=lambda:object()
                elif reason=='rebind':self.export.view='f'*32
                elif reason=='account':self.gate.locked=True
                elif reason=='conversation':self.panel.session['id']='other'
                else:self.panel.cancel_event.set()
                receipt.prepared.set();receipt._monitor_preparation()
                self.assertTrue(self.panel.cancel_event.is_set())
                self.assertFalse(receipt.worker_prepared(self.panel.cancel_event))
                self.assertFalse(receipt.inference_allowed)
                self.assertEqual(receipt.poll(),ack) # The accepted Send is never replayable.
                receipt.worker_finished()
                self.app.grab_current=lambda:None;self.export.view=view
                self.panel.session['id']=sid;self.gate.locked=False

    def test_finished_preparation_monitor_cannot_cancel_next_request(self):
        receipt=self.execute();receipt.ready.set();receipt.poll();receipt.worker_finished()
        self.export.view='f'*32;self.panel.cancel_event.clear()
        receipt._monitor_preparation()
        self.assertFalse(self.panel.cancel_event.is_set())

    def test_inference_guard_refuses_a_stalled_Tk_loop(self):
        receipt=self.execute();receipt.ready.set();receipt.poll()
        with patch('native_chat_command.time.monotonic',side_effect=[100,105]):
            self.assertFalse(receipt.worker_prepared(self.panel.cancel_event))
        self.assertTrue(self.panel.cancel_event.is_set());self.assertFalse(receipt.inference_allowed)

    def test_model_failure_after_ack_does_not_replay_or_infer(self):
        from test_chat_handoff import panel as make_panel
        p=make_panel();p.root=self.root;p.session=self.panel.session;p.cancel_event=self.panel.cancel_event
        p._check_login=self.panel._check_login
        payload=self.payload();receipt=self.execute(payload);self.export.chat=p
        p.effort=SimpleNamespace(prepare_request=Mock(side_effect=RuntimeError('Synthetic missing projector')),active_plan={})
        def work():
            try:p.agent_worker(p.session['id'],remote_admission=receipt)
            finally:receipt.worker_finished()
        with patch.object(p,'stream_completion') as infer:
            worker=threading.Thread(target=work);worker.start()
            self.assertTrue(receipt.ready.wait(1));ack=receipt.poll();worker.join(2)
            self.assertFalse(worker.is_alive());infer.assert_not_called()
        self.assertEqual(receipt.poll(),ack)
        self.assertIn('Synthetic missing projector',p.session['messages'][-1]['content'])
        self.assertIs(self.execute(payload),receipt);self.panel.submit.assert_called_once()

    def test_no_background_title_after_failed_or_cancelled_admission(self):
        from native_chat import NativeChat
        p=SimpleNamespace(_closing=False,settings={},_title_job_sid=None,
                          _thread=Mock(return_value=Mock()),_auto_title_worker=Mock())
        for reply in (None,{'role':'assistant','content':'partial','cancelled':True},
                      {'role':'assistant','content':'load failed','incomplete':True}):
            p.session={'id':'synthetic','auto_title_pending':True,'messages':[{'role':'user','content':'test'}]+([reply] if reply else [])}
            NativeChat._maybe_schedule_auto_title(p)
            p._thread.assert_not_called()
        p.session['messages'].append({'role':'assistant','content':'Completed answer'})
        NativeChat._maybe_schedule_auto_title(p);p._thread.assert_called_once()


if __name__=='__main__':unittest.main()
