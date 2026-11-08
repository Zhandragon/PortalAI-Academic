"""Real Tk composer/event pump, isolated store and workers; no inference or account."""
from pathlib import Path
import sys, threading, tkinter as tk, unittest
from unittest.mock import Mock
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('ControlCenter', 'Agent', 'Maintenance/Tests')]
from chat_followups import FollowupQueue
import test_chat_timeline as timeline


class QueueTests(unittest.TestCase):
    def test_stop_and_failure_pause_but_explicit_send_now_resumes(self):
        q=FollowupQueue();q.add('next', [])
        self.assertFalse(q.completed(cancelled=True))
        q.send_now();self.assertTrue(q.completed(cancelled=True))
        self.assertFalse(q.completed(failed=True))

    def test_scope_change_discards_private_pending_text(self):
        q=FollowupQueue();q.bind(('profile-a','chat'));q.add('private',[])
        q.bind(('profile-b','chat'));self.assertIsNone(q.peek())
        q.add('other',[]);q.bind(('profile-b','different'));self.assertIsNone(q.peek())

    def test_edit_keeps_next_position_and_attachment_snapshot(self):
        q=FollowupQueue();attachment={'name':'original'}
        q.add('first',[attachment]);q.add('second',[]);attachment['name']='changed'
        edited=q.take_for_edit();self.assertEqual(edited.attachments[0]['name'],'original')
        self.assertTrue(q.paused);q.add('edited',edited.attachments)
        self.assertEqual([x.text for x in q.items],['edited','second']);self.assertFalse(q.paused)


class FollowupUITests(unittest.TestCase):
    setUp = timeline.TimelineTests.setUp

    def panel(self):
        p=self.p;p.COL.update(panel='#111111',good='#00ff00');p.prompt=tk.Text(self.app)
        p._check_login=Mock();p._notice=Mock();p._resize_prompt=Mock();p.update_attachment_label=Mock()
        p.pending_attachments=[];p._memory_job_running=False;p.memory=Mock()
        p.header=Mock();p.chat_insert=Mock();p._set_llm_dot=Mock();p._thread=Mock();p.session['title']='New chat'
        self.started=[]
        def start(**kwargs):
            self.started.append(p.session['messages'][-1]['content'])
            worker=Mock();worker.is_alive.return_value=False;return worker
        p._thread.side_effect=start
        return p

    def test_busy_send_queues_without_changing_active_transcript(self):
        p=self.panel();p.prompt.insert('1.0','Follow up');p.pending_attachments=[{'name':'image','size':12}]
        p.submit();q=p._followup_state()
        self.assertEqual(q.peek().text,'Follow up');self.assertEqual(p.session['messages'],[])
        self.assertEqual(p.prompt.get('1.0','end').strip(),'');self.assertEqual(p.pending_attachments,[])
        p.store.save_session.assert_not_called();self.assertEqual(self.started,[])
        p._refresh_followup_controls();p.send_btn.configure.assert_called_with(state='normal',text='Queue')

    def test_natural_completion_sends_fifo_and_preserves_new_draft(self):
        p=self.panel();q=p._followup_state();q.add('first',[]);q.add('second',[])
        p.prompt.insert('1.0','unfinished draft');p.ev.put(('done',None));p._pump();self.app.update()
        self.assertEqual(self.started,['first']);self.assertEqual(q.peek().text,'second')
        self.assertEqual(p.prompt.get('1.0','end').strip(),'unfinished draft')
        p.ev.put(('done',None));p._pump();self.app.update()
        self.assertEqual(self.started,['first','second']);self.assertIsNone(q.peek())
        self.assertEqual([m['content'] for m in p.session['messages']],['first','second'])

    def test_send_now_waits_for_real_worker_cleanup_before_clearing_cancel(self):
        p=self.panel();q=p._followup_state();q.add('next',[]);q.send_now();p.cancel_event.set()
        emitted,release=threading.Event(),threading.Event()
        def worker():p.ev.put(('done',None));emitted.set();release.wait(3)
        thread=threading.Thread(target=worker);p._active_request_worker=thread;thread.start()
        try:
            self.assertTrue(emitted.wait(2));p._pump()
            self.assertTrue(p.busy);self.assertTrue(p.cancel_event.is_set());self.assertEqual(self.started,[])
        finally:release.set();thread.join(3)
        p._pump();self.app.update()
        self.assertEqual(self.started,['next']);self.assertFalse(p.cancel_event.is_set())

    def test_cancelled_completion_requires_explicit_resume(self):
        p=self.panel();q=p._followup_state();q.add('next',[]);p.cancel_event.set()
        p.ev.put(('done',None));p._pump();self.app.update()
        self.assertTrue(q.paused);self.assertEqual(self.started,[])
        p.send_queued_now();self.assertEqual(self.started,['next'])

    def test_persistence_failure_retains_queue_and_rolls_back_user_turn(self):
        p=self.panel();p.busy=False;q=p._followup_state();entry=q.add('next',[])
        p.store.save_session.side_effect=OSError('disk full');p._drain_followups()
        self.assertIs(q.peek(),entry);self.assertTrue(q.paused);self.assertEqual(p.session['messages'],[])
        self.assertEqual(p.session['title'],'New chat');self.assertEqual(self.started,[])

    def test_worker_start_failure_does_not_duplicate_persisted_turn(self):
        p=self.panel();p.busy=False;q=p._followup_state();q.add('next',[]);q.add('later',[])
        p._thread.side_effect=None;p._thread.return_value.start.side_effect=RuntimeError('cannot start')
        p._drain_followups()
        self.assertEqual([m['content'] for m in p.session['messages']],['next'])
        self.assertEqual(q.peek().text,'later');self.assertTrue(q.paused)
        p._pump();self.assertFalse(p.busy)

    def test_edit_then_send_restores_fifo_without_replacing_a_draft(self):
        p=self.panel();q=p._followup_state();q.add('first',[]);q.add('second',[])
        p.prompt.insert('1.0','existing');p.edit_queued_followup();self.assertEqual(q.peek().text,'first')
        p.prompt.delete('1.0','end');p.edit_queued_followup();p.prompt.insert('end',' edited');p.submit()
        self.assertEqual([x.text for x in q.items],['first edited','second']);self.assertFalse(q.paused)

    def test_unfinished_attachment_import_and_full_queue_preserve_draft(self):
        p=self.panel();p.prompt.insert('1.0','keep me');p._attachment_imports=1;p.submit()
        self.assertIsNone(p._followup_state().peek())
        p._attachment_imports=0
        for _ in range(32):p._followup_state().add('existing',[])
        p.submit();self.assertEqual(p.prompt.get('1.0','end').strip(),'keep me')

    def test_remote_request_is_not_silently_queued_when_busy(self):
        p=self.panel();self.assertEqual(p.submit(remote_text='remote'),'break')
        self.assertIsNone(p._followup_state().peek());self.assertEqual(self.started,[])


if __name__=='__main__':unittest.main()
