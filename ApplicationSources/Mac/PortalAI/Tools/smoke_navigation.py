"""Actual launcher navigation on a disposable account; never the user's GUI."""
import argparse
import json
from pathlib import Path
import sys
import time
import tkinter as tk

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','Maintenance/Tests','ControlCenter','Agent')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from smoke_account_panels import capture_window
from capture_page_fixture import capture_page


def inspect(built,app,destination):
    original_geometry=app.geometry()
    scroll_checks=[]
    def check_scroll(name,canvas):
        app.update()
        bounds=canvas.bbox('all');content_height=bounds[3]-bounds[1] if bounds else 0
        height=canvas.winfo_height();overflow=content_height>height
        from ornate_ui import FiligreeScrollbar
        assert any(isinstance(w,FiligreeScrollbar) and w.winfo_ismapped() for w in canvas.master.winfo_children()),name
        canvas.yview_moveto(0);canvas.yview_scroll(-100,'units')
        assert canvas.canvasy(0)==0,(name,'negative blank space',canvas.canvasy(0))
        canvas.yview_scroll(100,'units')
        if overflow:
            assert 0<canvas.canvasy(0)<=content_height-height,(name,canvas.canvasy(0),content_height,height)
        else:
            assert canvas.canvasy(0)==0 and canvas.yview()==(0,1),(name,canvas.canvasy(0),canvas.yview())
        scroll_checks.append({'page':name,'content_height':content_height,'viewport_height':height,'overflow':overflow,'passed':True})
        canvas.yview_moveto(0);app.update()
    check_scroll('welcome',built['tab_scroll_canvases']['welcome'])
    expected={'accounts':'Accounts','activity':'Runtime','runtime':'Models','installed':'Packages','settings':'Settings','maintenance':'Maintenance'}
    assert len(built['buttons'])==6
    controls=built['buttons']
    assert [str(b.cget('text')) for b in controls]==['Startup','System Test','Full Component Diagnosis','Minimize to tray','Stop all components','Exit PortalAI']
    watermark=built['page_watermark']
    from test_settings_surfaces_tk import button,widgets
    built['show_tab']('accounts');app.update()
    check_scroll('accounts',built['tab_scroll_canvases']['accounts'])
    assert built['account_page'].win.winfo_ismapped()
    assert not any('Model, hardware' in str(w.cget('text')) for w in widgets(built['ctl']) if 'text' in w.keys())
    button(built['account_page'].win,'Change my password…').invoke();app.update()
    dialogs=[d for d in app._portalai_account_dialogs if not d.closed]
    assert len(dialogs)==1
    dialogs[0].close();app.update()
    watermark.refresh();app.update();assert watermark.shown
    capture_page(app,watermark,destination/'accounts.png')
    built['show_tab']('controls');app.update()
    check_scroll('controls',built['tab_scroll_canvases']['controls'])
    assert built['log_panel'].master is built['controls_tab']
    assert built['log_panel'].winfo_rooty()>built['ctl'].winfo_rooty()
    watermark.refresh();app.update();assert watermark.shown
    assert not built['brand_corner_badges']
    capture_page(app,watermark,destination/'controls.png')
    built['_show_text_report']('Synthetic storage report','Synthetic clipboard test\n'+'test line\n'*26000,ok=False)
    app.update();overlay=built['launcher_panel_state']['overlay']
    watermark.refresh();assert not watermark.shown
    copy=button(overlay,'Copy to clipboard');assert copy.winfo_ismapped()
    assert copy.winfo_rooty()+copy.winfo_height()<app.winfo_rooty()+app.winfo_height()
    # Inspect the actual clipboard call without altering the user's clipboard.
    from unittest.mock import patch
    with patch.object(app,'clipboard_clear'),patch.object(app,'clipboard_append') as copied:
        copy.invoke();assert len(copied.call_args.args[0])>220000
    capture_window(app,destination/'report.png');built['close_launcher_panel']()
    for key,name in expected.items():
        assert str(built['tab_buttons'][key].cget('text')).casefold()==name.casefold()
    # Reproduce Enter -> theme switch -> Leave, including the formerly stale
    # Compact button bindings. The fixture uses real launcher buttons and palettes.
    built['show_tab']('help');app.update();app.focus_force()
    watermark=built['page_watermark']
    for i in range(4):
        for control in (built['theme_toggle_btn'],built['portal_compact_mode'].toggle_button):
            control.event_generate('<Enter>')
        built['toggle_theme']();app.update()
        for control,role in ((controls[0],'accent'),(controls[4],'gold_mid'),(controls[5],'danger')):
            control.event_generate('<Enter>');control.event_generate('<Leave>')
            assert control.cget('bg')==built['COLORS'][role]
        for title in ('Safe Cleanup Plan','Root-only Cleanup'):
            action=button(built['maintenance_panel'],title)
            assert action.cget('bg')==built['COLORS']['gold_mid'] and action.cget('fg')=='#202224'
        for control in (built['theme_toggle_btn'],built['portal_compact_mode'].toggle_button):
            control.event_generate('<Leave>');app.update()
            assert control.cget('bg')==built['COLORS']['button'], (control.cget('text'),control.cget('bg'),built['COLORS']['button'])
            assert control.cget('fg')==built['COLORS']['text']
        watermark.refresh();app.update()
        assert watermark.shown and watermark.key.startswith('help')
        assert built['documentation_panel'].text.tag_cget('title','foreground')==built['COLORS']['muted']
        assert float(watermark.win.attributes('-alpha'))==1
        watermark._clickthrough()
        if i<2:capture_page(app,watermark,destination/('help-'+watermark.mode_getter()+'.png'))
    for key in ('runtime','installed','maintenance','settings','activity'):
        built['show_tab'](key);app.update()
        if key in built['tab_scroll_canvases']:check_scroll(key,built['tab_scroll_canvases'][key])
        if key=='activity':
            # Visually explicit fixture data; no live model/worker is started.
            now=time.monotonic()
            for i in range(60):built['activity_charts'].update_sample({'at':now-295+5*i,'cpu':20+i%30,'ram':42,'gpu':i%55,'vram':33})
            assert built['process_box'].winfo_height()<200, 'Scrollbar enlarged the activity table'
        if key=='maintenance':
            capture_window(app,destination/'maintenance-top.png')
            built['tab_scroll_canvases']['maintenance'].yview_moveto(.7);app.update()
        watermark.refresh();app.update()
        assert watermark.shown and watermark.mode_getter() in watermark.key
        capture_page(app,watermark,destination/(key+'.png'))
    built['show_tab']('chat');panel=built['native_chat_panel']
    from tkinter import ttk
    def check_actions(enabled):
        for name,action in panel.chat_action_buttons.items():
            assert action.instate(['!disabled'] if name in enabled else ['disabled']), name
            color=ttk.Style(app).lookup(action.cget('style'),'foreground',state=('disabled',) if name not in enabled else ())
            assert color==panel.COL['text' if name in enabled else 'muted'],(name,color)
        assert panel.history_btn.instate(['!disabled']) and panel.history_btn.cget('fg')==panel.COL['text']
    defaults={'Validate chat state','Chat Preferences','Memory','Instructions'}
    check_actions(defaults)
    assert panel.manage_attachments_btn.instate(['disabled']) and panel.clear_attachments_btn.instate(['disabled'])
    capture_window(app,destination/'chat-empty.png')
    panel.pending_attachments=[{'name':'synthetic.txt','size':17}];panel.update_attachment_label()
    for action in (panel.manage_attachments_btn,panel.clear_attachments_btn):
        assert action.instate(['!disabled']) and action.cget('fg')==panel.COL['text']
    panel.clear_attachments_btn.invoke()
    assert not panel.pending_attachments and panel.manage_attachments_btn.instate(['disabled'])
    fresh_id=panel.session['id'];sample=panel.store.new_session()
    sample['messages']=[{'role':'user','content':'Synthetic question'}, {'role':'assistant','content':'Synthetic answer'}]
    panel.store.save_session(sample);panel.load_session(sample['id']);app.update()
    check_actions(defaults|{'Edit last','Branch','Copy','Export'})
    panel.busy=True;panel.update_token_label();check_actions(defaults|{'Copy','Export'})
    panel.busy=False;panel.load_session(fresh_id);app.update();check_actions(defaults)
    panel.load_session(sample['id']);app.update()
    capture_window(app,destination/'chat-populated.png')
    panel.chat_insert('Synthetic conversation for layout validation.\n','you')
    panel.create_trace_block('thinking','Thinking',collapsed=True,initial='Synthetic reasoning only')
    panel.create_trace_block('tool','Tool · science',collapsed=True,initial='Synthetic tool result')
    expanded=panel.create_trace_block('tool','Expanded tool',collapsed=False,initial='\n'.join('Synthetic result line '+str(i) for i in range(50)))
    check_actions(defaults|{'Edit last','Branch','Copy','Export','Hide tool trace'})
    panel.chat.see('1.0');app.update();capture_window(app,destination/'chat.png')
    from test_settings_surfaces_tk import button,widgets
    edit=button(panel.host,'Edit last')
    assert panel.history_btn.winfo_rooty()==edit.winfo_rooty()
    assert panel.history_btn.winfo_rootx()<edit.winfo_rootx()
    assert expanded['head']._portalai_conversation_border.simple
    assert not expanded['frame']._portalai_conversation_border.simple
    panel.open_memory_panel();app.update()
    from ornate_ui import FiligreeScrollbar
    from tkinter.scrolledtext import ScrolledText
    preview=next(w for w in widgets(panel._sheet_overlay) if isinstance(w,ScrolledText))
    assert not preview.vbar.winfo_ismapped()
    assert any(isinstance(w,FiligreeScrollbar) and w.winfo_ismapped() for w in preview.frame.winfo_children())
    save=button(panel._sheet_overlay,'Save')
    assert save.winfo_ismapped() and save.winfo_rooty()+save.winfo_height()<panel._sheet_overlay.winfo_rooty()+panel._sheet_overlay.winfo_height()
    capture_window(app,destination/'memory.png');panel._close_sheet()
    panel.open_settings()
    for key in panel._preferences_tabs.pages:
        panel._preferences_tabs.select(key);app.update()
        for title in ('Cancel','Save settings'):
            action=button(panel._sheet_overlay,title)
            assert any(border.widget is action.master for border in panel._sheet_skin.borders)
        capture_window(app,destination/('chat-preferences-'+key+'.png'))
    panel._close_sheet()
    built['open_account_missions']();app.update()
    persistence=built['persistence_page']
    assert persistence.pages['missions'].winfo_toplevel() is app
    check_scroll('missions',persistence.pages['missions'].skin.canvas)
    from tkinter.font import Font
    from portal_frontend_v15136 import portal_display_font
    for subtab in (*persistence.buttons.values(),*built['packages_view'].tabs.values()):
        assert Font(app,font=subtab.cget('font')).actual('family')==portal_display_font(app)
    watermark.refresh();app.update();assert watermark.shown
    capture_page(app,watermark,destination/'missions.png')
    persistence.select('schedules');app.update()
    check_scroll('schedules',persistence.pages['schedules'].skin.canvas)
    watermark.refresh();assert watermark.shown
    capture_page(app,watermark,destination/'schedules.png')
    built['show_tab']('chat');app.geometry('720x820+40+40');app.update()
    capture_window(app,destination/'chat-narrow.png')
    panel.open_settings();panel._preferences_tabs.select('effort');app.update()
    capture_window(app,destination/'preferences-narrow.png');panel._close_sheet()
    built['show_tab']('maintenance');app.update();capture_window(app,destination/'maintenance-narrow.png')
    check_scroll('maintenance-narrow',built['tab_scroll_canvases']['maintenance'])
    watermark.refresh();assert not watermark.shown
    built['show_tab']('persistence');app.update()
    for key in ('missions','schedules'):
        persistence.select(key);app.update();check_scroll(key+'-narrow',persistence.pages[key].skin.canvas)
    app.geometry('1260x1200+40+40');built['show_tab']('welcome');app.update()
    check_scroll('welcome-tall',built['tab_scroll_canvases']['welcome'])
    assert built['tab_scroll_canvases']['welcome'].yview()==(0,1)
    built['show_tab']('maintenance');app.update()
    app.geometry(original_geometry);app.update();watermark.refresh();assert watermark.shown
    # Return the native geometry expected by the continuity fixture.
    app.geometry(original_geometry);app.update()
    (destination/'scroll-checks.json').write_text(json.dumps(scroll_checks,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--theme',default='light',choices=('light','dark'));args=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try:report=run(artifacts.path(),args.theme,inspector=inspect)
    except Exception as exc:report={'passed':False,'error':str(exc)}
    artifacts.path('navigation-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(0 if report.get('passed') else 1)
