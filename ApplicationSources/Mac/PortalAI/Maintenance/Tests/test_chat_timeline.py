"""Actual withdrawn Tk transcript and deterministic lifecycle checks; no account/model."""
from pathlib import Path
import queue,sys,threading,time,tkinter as tk,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('ControlCenter','Agent','Maintenance/Tests')]
import native_chat as chat
import native_chat_timers_v15_128e as timers
from native_rich_chat import observe,Controller
from tk_fixture_cleanup import finish_tk_fixture

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.withdraw();self.addCleanup(finish_tk_fixture,self.app)
        p=self.p=chat.NativeChat.__new__(chat.NativeChat)
        p.app=p.host=self.app;p.chat=tk.Text(self.app);p.chat.pack()
        p.COL={'bg':'#111111','card':'#222222','panel2':'#333333','gold':'#aaaa44','text':'#ffffff',
               'thinking':'#aaccff','tool':'#ccccaa','muted':'#aaaaaa','bad':'#ff8888'}
        p.settings={'show_thinking':True};p.session={'id':'fixture','messages':[]}
        p._trace_blocks=[];p._trace_flush_after=None;p._live_thinking_block=p._live_tool_block=None
        p._stream_pump_budget_ms=1000;p.ev=queue.Queue();p.drop_target=None;p.busy=True
        p.cancel_event=threading.Event();p.store=Mock();p.effort=Mock()
        for name in ('stop_btn','send_btn','session_list','model_lbl'):setattr(p,name,Mock())
        for name in ('_refresh_action_buttons','refresh_sessions_labels_only','refresh_status','update_token_label',
                     '_maybe_schedule_auto_title','_schedule_model_probe','_schedule_memory_maintenance','render_media_card'):
            setattr(p,name,Mock())
        self.errors=[];self.app.report_callback_exception=lambda *args:self.errors.append(args)

    def feed(self,*events):
        for e in events:self.p.ev.put(e)
        while not self.p.ev.empty():self.p._pump()
        self.assertEqual(self.errors,[])

    def transcript(self):
        out=[]
        for kind,value,index in self.p.chat.dump('1.0','end',text=True,window=True):
            if kind=='text':out.append(value)
            elif kind=='window':
                b=next((b for b in self.p._trace_blocks if str(b['frame'])==value),None)
                if b:out.append('['+b['text'].get('1.0','end-1c')+']')
        return ''.join(out)

    def test_fifo_reasoning_prose_tools_and_second_answer(self):
        self.feed(('assistant_start',{'index':0}),('reasoning','THOUGHT'),('content','BEFORE TOOL'),
                  ('tool_start',{'name':'lookup','args':{}}),('tool_result',{'name':'lookup','content':'RESULT'}),
                  ('assistant_start',{'index':2}),('reasoning','NEXT THOUGHT'),('content','FINAL'),('done',None))
        text=self.transcript();terms=['THOUGHT','BEFORE TOOL','Call','RESULT','NEXT THOUGHT','FINAL']
        self.assertEqual(sorted(text.index(x) for x in terms),[text.index(x) for x in terms])
        self.assertTrue(all(b['state']=='done' for b in self.p._trace_blocks));self.assertFalse(self.p.busy)

    def test_history_matches_live_prose_before_tool(self):
        p=self.p;p.busy=False
        p.session['messages']=[{'role':'assistant','reasoning':'THOUGHT','content':'BEFORE TOOL',
                               'tool_calls':[{'id':'c','function':{'name':'lookup','arguments':'{}'}}]},
                              {'role':'tool','tool_call_id':'c','name':'lookup','content':'RESULT'}]
        for render in (p.render_history,p.render_history_incremental):
            render();self.app.update()
            text=self.transcript();self.assertLess(text.index('THOUGHT'),text.index('BEFORE TOOL'))
            self.assertLess(text.index('BEFORE TOOL'),text.index('Call'));self.assertLess(text.index('Call'),text.index('RESULT'))
            self.assertFalse(getattr(p,'_history_render_pending',False))

    def test_loaded_history_cannot_interleave_new_submission_or_regeneration(self):
        p=self.p;p.busy=False;p.session['messages']=[{'role':'user','content':str(i)} for i in range(12)]
        p.render_history_incremental();p._check_login=Mock();p._thread=Mock()
        self.assertEqual(p.submit(remote_text='NEW'),'break');p.regenerate_last();p._thread.assert_not_called()
        self.assertEqual(len(p.session['messages']),12)
        deadline=time.monotonic()+2
        while p._history_render_pending and time.monotonic()<deadline:
            self.app.update();time.sleep(.002)
        self.assertFalse(p._history_render_pending)
        p.send_btn.configure.assert_any_call(state='normal')

    def test_replaced_history_cancels_queued_old_cards(self):
        p=self.p;p.busy=False;p.session['messages']=[{'role':'assistant','reasoning':'OLD'}]*20
        p.render_history_incremental();p.session={'id':'new','messages':[{'role':'user','content':'NEW'}]}
        p.render_history();self.app.update()
        self.assertNotIn('OLD',self.transcript());self.assertIn('NEW',self.transcript())

    def test_history_widget_failure_releases_loading_gate(self):
        p=self.p;p.busy=False;p.session['messages']=[{'role':'assistant','reasoning':'bad widget'}]
        with patch.object(p,'create_trace_block',side_effect=ValueError('fixture')):
            p.render_history_incremental();self.app.update()
        self.assertFalse(p._history_render_pending);p.send_btn.configure.assert_any_call(state='normal')

    def test_timer_uses_phases_and_freezes_at_done_without_waiting_for_tick(self):
        p=self.p;timers._begin_response(p)
        self.feed(('assistant_start',{'index':0}),('reasoning','WORK'))
        self.assertEqual(p._pai128e_timer['current']['title'],'Thinking')
        self.feed(('content','ANSWER'));self.assertEqual(p._pai128e_timer['current']['title'],'Writing')
        self.feed(('done',None));t=p._pai128e_timer
        self.assertFalse(t['active']);self.assertIsNone(t['current']);self.assertIn('Completed',t['steps_label'].cget('text'))
        before=t['total_label'].cget('text')
        with patch.object(timers.time,'monotonic',return_value=time.monotonic()+600):timers._refresh_labels(p)
        self.assertEqual(before,t['total_label'].cget('text'))

    def test_stop_closes_reasoning_and_timer_but_keeps_partial_text(self):
        p=self.p;timers._begin_response(p);self.feed(('reasoning','PARTIAL'))
        p.cancel_event.set();self.feed(('done',None))
        self.assertEqual(p._pai128e_timer['outcome'],'Stopped');self.assertIn('PARTIAL',self.transcript())
        self.assertTrue(all(b['state']=='cancelled' for b in p._trace_blocks))

    def test_error_settles_timer_and_render_failure_does_not_leave_busy(self):
        p=self.p;timers._begin_response(p);self.feed(('reasoning','PARTIAL'),('error','Synthetic failure'))
        p.stop_btn.configure.side_effect=ValueError('destroyed widget');self.feed(('done',None))
        self.assertFalse(p.busy);self.assertFalse(p._pai128e_timer['active'])
        self.assertEqual(p._pai128e_timer['outcome'],'Failed')
        self.assertTrue(all(b['state']!='live' for b in p._trace_blocks))

    def test_pump_burst_boundary_preserves_order(self):
        self.feed(('assistant_start',{'index':0}),*[('reasoning','x') for _ in range(405)],('content','LAST'),('done',None))
        self.assertEqual(self.p._trace_blocks[0]['text'].get('1.0','end-1c'),'x'*405)
        self.assertTrue(self.transcript().rstrip().endswith('LAST'));self.assertFalse(self.p.busy)

    def test_remote_reasoning_stops_streaming_when_answer_starts(self):
        p=self.p;r=Controller.__new__(Controller);r.ex=SimpleNamespace(chat=p,epoch='e');r.refs={};r.sequence=0
        observe(p,'assistant_start',{'index':0});observe(p,'reasoning','WORK')
        blocks,_=r.inventory({'conversation':'fixture'});self.assertEqual(blocks[0]['status'],'streaming')
        observe(p,'content','ANSWER');after,_=r.inventory({'conversation':'fixture'})
        self.assertEqual(after[0]['id'],blocks[0]['id']);self.assertEqual(after[0]['status'],'saved')
        p.session['messages'].append({'role':'assistant','content':'ANSWER','reasoning':'WORK'})
        observe(p,'done',None);p.busy=False;final,_=r.inventory({'conversation':'fixture'})
        self.assertEqual(final[0]['id'],blocks[0]['id']);self.assertEqual(final[0]['status'],'saved')

if __name__=='__main__':unittest.main()
