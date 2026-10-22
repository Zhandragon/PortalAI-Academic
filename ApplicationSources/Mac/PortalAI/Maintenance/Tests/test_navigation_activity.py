"""Navigation, telemetry and popup regressions using synthetic state only."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('ControlCenter','Agent','Tools')]
from activity_monitor import cpu_percent, ActivityCharts
from runtime_activity import owned, label_for, RuntimeActivity, format_processes
from windows_gpu_counters import summarize
from test_settings_surfaces_tk import chat_fixture, button, widgets, LIGHT, INVENTORY
from test_chat_layout_tk import build_panel
from chat_effort_ui import ChatEffortControls
from themed_popup_menu import ThemedPopupMenu
from tk_fixture_cleanup import finish_tk_fixture


class ActivityTests(unittest.TestCase):
    def test_storage_policy_validates_before_any_write_and_preserves_extensions(self):
        import settings_page
        values={'minimum_free_gib':'80','output_reserve_gib':'120','minimum_free_percent':'12'}
        with patch.object(settings_page,'require_admin'), \
             patch.object(settings_page,'load_policy',return_value={'extension':{'keep':True},'storage':{'extra':'retained'}}), \
             patch.object(settings_page.shutil,'disk_usage',return_value=SimpleNamespace(total=1024**4)), \
             patch.object(settings_page,'atomic_json') as write:
            for invalid in ('nan','inf','-1','0','1025'):
                with self.assertRaises(ValueError): settings_page.save_storage_settings(ROOT,{**values,'output_reserve_gib':invalid})
            with self.assertRaises(ValueError): settings_page.save_storage_settings(ROOT,{**values,'minimum_free_percent':'51'})
            write.assert_not_called()
            settings_page.save_storage_settings(ROOT,values)
            policy=write.call_args.args[1]
            self.assertEqual(policy['storage'],{'extra':'retained','minimum_free_gib':80,'output_reserve_gib':120,'minimum_free_fraction':.12})
            self.assertEqual(policy['extension'],{'keep':True})
        with patch.object(settings_page,'require_admin',side_effect=PermissionError), patch.object(settings_page,'atomic_json') as write:
            with self.assertRaises(PermissionError): settings_page.save_storage_settings(ROOT,values)
            write.assert_not_called()

    def test_cpu_delta_first_sample_and_reset_are_not_fake_zero(self):
        self.assertIsNone(cpu_percent(None,(10,3)))
        self.assertIsNone(cpu_percent((10,3),(9,2)))
        self.assertAlmostEqual(cpu_percent((10,3),(20,5)),80)

    def test_busiest_engine_gpu_and_memory_have_distinct_meaning(self):
        result = summarize([('pid_7_luid_1_eng_0',30),('pid_7_luid_1_eng_1',50),
                            ('pid_9_luid_1_eng_0',20),('pid_8_luid_1_eng_0',float('nan'))],
                           [('pid_7_luid_1',2*1024**3)],[('pid_7_luid_1',1024**3)])
        self.assertEqual(result['processes']['7'],{'gpu':50,'dedicated':2,'shared':1})
        self.assertEqual(result['gpu'],50)
        self.assertNotIn('8',result['processes'])

    def test_process_attribution_rejects_neighbor_root_and_hides_prompt(self):
        self.assertTrue(owned(ROOT,ROOT/'Runtime/BootstrapPython/python.exe'))
        self.assertFalse(owned(ROOT,ROOT.parent/(ROOT.name+'-other')/'python.exe'))
        self.assertEqual(label_for('python.exe','"D:/PortableAI/Agent/ai_tools.py" voice-design --text "PRIVATE PROMPT"'), 'ai_tools · voice-design')
        text = format_processes([{'pid':12,'label':'science','cpu':None,'ram':None}],{'12':9})
        self.assertIn('pending',text); self.assertNotIn('9.00',text)

    def test_handoff_tailer_ignores_old_history_preserves_partial_and_rejects_dead_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root/'Agent/.runtime';runtime.mkdir(parents=True)
            log = runtime/'qwen_vram_handoff.log';log.write_text('old BEGIN\n')
            tracker = RuntimeActivity(root,profile=SimpleNamespace(check=Mock()))
            self.assertEqual(tracker.lifecycle([]),([],[]))
            with log.open('a') as stream: stream.write('now BEGIN owned\nnow END restored')
            events = tracker.lifecycle([])[1]
            self.assertEqual(events,['Handoff · now BEGIN owned'])
            with log.open('a') as stream: stream.write('\n')
            self.assertEqual(tracker.lifecycle([])[1],['Handoff · now END restored'])
            (runtime/'gpu_model_state.json').write_text(json.dumps({'pid':77,'service':'fiction','models':['x']}))
            self.assertEqual(tracker.lifecycle([]),([],[]))
            stages,events = tracker.lifecycle([{'pid':77}])
            self.assertIn('fiction',stages[0]);self.assertEqual(len(events),1)
            self.assertEqual(tracker.lifecycle([{'pid':77}])[1],[])
            self.assertIn('released',tracker.lifecycle([])[1][0])

    def test_revoked_profile_stops_observer(self):
        tracker = RuntimeActivity(ROOT,profile=SimpleNamespace(check=Mock(side_effect=PermissionError('ended'))))
        with self.assertRaises(PermissionError):tracker.processes()
        with self.assertRaises(PermissionError):tracker.lifecycle([])

    @unittest.skipUnless(os.name=='nt','Windows process inventory fixture')
    def test_process_deltas_ownership_and_exit_are_observations(self):
        tracker=RuntimeActivity(ROOT,profile=SimpleNamespace(check=Mock()))
        values={11:{'exe':str(ROOT/'Runtime/python.exe'),'identity':1,'cpu':5,'ram':1024},
                12:{'exe':str(ROOT.parent/'Unrelated/python.exe'),'identity':2,'cpu':9,'ram':2048}}
        with patch('portableai_common.iter_processes',return_value=[(11,''),(12,'')]) as processes, \
             patch('portableai_common.process_command_line',return_value='science_tools.py biology.inspect --sequence SECRET'), \
             patch('runtime_activity.process_stats',side_effect=lambda pid:dict(values[pid])), \
             patch('runtime_activity.time.monotonic',side_effect=[10,12,14,16]),patch('runtime_activity.os.cpu_count',return_value=2):
            rows,events=tracker.processes();self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['cpu'])
            self.assertNotIn('SECRET',str(rows)+str(events))
            values[11]['cpu']=7
            rows,events=tracker.processes();self.assertEqual(rows[0]['cpu'],50);self.assertEqual(events,[])
            values[11]['identity']=3
            rows,events=tracker.processes();self.assertIsNone(rows[0]['cpu']);self.assertIn('observed',events[0])
            processes.return_value=[]
            rows,events=tracker.processes();self.assertEqual(rows,[]);self.assertIn('outcome not inferred',events[0])

    def test_new_diagnostics_are_resolvable_with_honest_coverage(self):
        from diagnostic_catalog import resolve, source_rows
        for key in ('biology','protein_design','coupled_physics','radeon','activity','kicad'):
            self.assertEqual(resolve(key)['report_key'],'diagnostic_'+key)
            rows = source_rows(ROOT,key)
            self.assertTrue(rows)
            for row in rows:
                self.assertTrue('Presence only' in row['detail'] or 'Missing:' in row['detail'])


class NavigationTkTests(unittest.TestCase):
    def setUp(self):
        self.app = tk.Tk();self.app.geometry('1040x760+40+40')
        self.errors = [];self.app.report_callback_exception=lambda kind,value,tb:self.errors.append(str(value))
        self.panel = None;self.popup = None

    def tearDown(self):
        if self.popup:self.popup.close()
        if self.panel:
            for name in ('chat_layout','chat_zoom'):
                if getattr(self.panel,name,None):getattr(self.panel,name).close()
            if getattr(self.panel,'_sheet_overlay',None):self.panel._close_sheet()
        finish_tk_fixture(self.app);self.assertEqual(self.errors,[])

    def pump(self,seconds=.1):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.app.update();time.sleep(.01)

    def test_tabs_keep_footer_edits_and_cancel_on_every_page(self):
        self.panel=chat_fixture(self.app);self.pump()
        tabs=self.panel._preferences_tabs
        self.assertEqual(len(tabs.pages),5)
        save=button(self.panel._sheet_overlay,'Save settings');top=save.winfo_rooty()
        for key in tabs.pages:
            tabs.select(key);self.pump()
            self.assertTrue(tabs.pages[key].winfo_ismapped())
            self.assertEqual(sum(p.winfo_ismapped() for p in tabs.pages.values()),1)
            self.assertTrue(save.winfo_ismapped());self.assertEqual(save.winfo_rooty(),top)
        button(self.panel._sheet_overlay,'Cancel').invoke()
        self.panel.store.save_settings.assert_not_called()

    def test_preferences_duplicate_effort_without_saving_on_cancel(self):
        self.panel=chat_fixture(self.app)
        effort=ChatEffortControls.__new__(ChatEffortControls);effort.panel=self.panel
        effort.profile=effort.tools_profile='balanced';effort.session_unlocked=False
        effort.capability_data={};effort.active_plan=None;effort.scale=tk.Scale(self.app)
        effort._render=Mock();effort.refresh_capabilities=Mock();policy=SimpleNamespace(save_preferences=Mock())
        # Chat size/variant now saves through the explicit model-choice route;
        # the effort policy persists only media/science effort.
        effort._save_model_choice=Mock()
        effort._module=Mock(return_value=policy);self.panel.effort=effort;self.panel.busy=False;self.panel.root=ROOT
        self.panel.open_settings();tabs=self.panel._preferences_tabs;tabs.select('effort');self.pump()
        combos=[w for w in widgets(tabs.pages['effort']) if isinstance(w,ttk.Combobox)]
        self.assertEqual(len(combos),2);combos[0].set('fast');combos[1].set('deep')
        button(self.panel._sheet_overlay,'Cancel').invoke();policy.save_preferences.assert_not_called()
        effort._save_model_choice.assert_not_called()
        self.assertEqual(effort.profile,'balanced')
        self.panel.open_settings();tabs=self.panel._preferences_tabs;tabs.select('effort');self.pump()
        combos=[w for w in widgets(tabs.pages['effort']) if isinstance(w,ttk.Combobox)]
        combos[0].set('fast');combos[1].set('balanced');tabs.select('voice')
        button(self.panel._sheet_overlay,'Save settings').invoke()
        effort._save_model_choice.assert_called_once_with(level='fast')
        policy.save_preferences.assert_called_once_with(ROOT,tools='balanced')
        self.assertEqual(effort.profile,'fast')

    def test_collapsed_trace_single_border_and_no_duplicate_chat_scrollbar(self):
        self.panel=build_panel(self.app);self.panel._trace_blocks=[];self.panel._trace_flush_after=None
        self.panel._sheet_overlay=None
        block=self.panel.create_trace_block('thinking','Thinking',collapsed=True,initial='Synthetic detail')
        self.pump()
        self.assertTrue(block['frame']._portalai_conversation_border.simple)
        self.assertFalse(block['head']._portalai_conversation_border.canvas.winfo_ismapped())
        self.panel._set_trace_block_expanded(block,True);self.pump()
        self.assertFalse(block['frame']._portalai_conversation_border.simple)
        self.assertTrue(block['head']._portalai_conversation_border.canvas.winfo_ismapped())
        from portal_frontend_v15136 import upgrade_vertical_scrollbars
        from ornate_ui import FiligreeScrollbar
        upgrade_vertical_scrollbars(self.app,LIGHT);self.pump()
        visible=[w for w in self.panel.chat.frame.winfo_children() if isinstance(w,FiligreeScrollbar) and w.winfo_ismapped()]
        self.assertEqual(len(visible),1)
        self.assertLess(self.panel.history_btn.winfo_rooty(),self.panel.history_pane.winfo_rooty())

    def test_popup_outside_click_and_hidden_root_focus_change_do_not_run_action(self):
        action=Mock();self.popup=ThemedPopupMenu(self.app,lambda:LIGHT)
        self.app.update();self.popup.show(70,80,[{'label':'Synthetic action','command':action}])
        self.pump(.2);self.assertIsNotNone(self.popup.window)
        self.app.event_generate('<ButtonPress-1>',x=900,y=600);self.pump()
        self.assertIsNone(self.popup.window);action.assert_not_called()
        self.app.withdraw();self.popup.show(70,80,[{'label':'Synthetic action','command':action}]);self.pump(.2)
        other=tk.Toplevel(self.app);other.title('Synthetic outside target');other.geometry('180x100+800+40');other.update();other.focus_force()
        self.pump(.3);self.assertIsNone(self.popup.window);self.assertIsNone(self.popup._dismiss_after)
        action.assert_not_called();other.destroy()

    def test_chart_history_is_bounded_and_unavailable_stays_unavailable(self):
        chart=ActivityCharts(self.app,LIGHT);chart.pack(fill='x');self.pump()
        for at in range(80):chart.update_sample({'at':at,'cpu':20,'ram':30,'gpu':None,'vram':None})
        self.assertEqual(len(chart.samples),60)
        self.assertIn('unavailable',chart.labels['gpu'].cget('text'))

    def test_reopening_popup_cancels_old_focus_timers(self):
        self.popup=ThemedPopupMenu(self.app,lambda:LIGHT)
        self.popup.show(70,80,[{'label':'First','command':Mock()}]);old=self.popup.window
        self.popup._later(150,lambda:self.popup._close_if_unfocused(old))
        self.popup.show(80,90,[{'label':'Second','command':Mock()}]);current=self.popup.window
        self.pump(.3);self.assertIs(self.popup.window,current)
        self.popup.close();self.assertFalse(self.popup._timers)


if __name__=='__main__':unittest.main()
