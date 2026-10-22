"""Focused real launcher rendering on synthetic accounts, never the user's GUI."""
import argparse
import cProfile
import io
import json
from pathlib import Path
import shutil
import sys
import pstats
import time
import threading
import traceback
from collections import Counter
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent','Maintenance/Tests')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from smoke_account_panels import capture_window
from capture_page_fixture import capture_page
import writer_jobs
original_thread=writer_jobs.WriterJobs.thread


def inspect(built,app,destination):
    mark=built['page_watermark']
    built['show_tab']('help');app.update()
    for _ in range(2):
        mark.refresh();app.update()
        assert mark.shown and mark.key.startswith('help') and mark._alpha_signature
        capture_page(app,mark,destination/('help-'+mark.mode_getter()+'.png'))
        built['toggle_theme']();app.update()
    built['show_tab']('chat');panel=built['native_chat_panel'];app.update()
    from profile_paths import private_path
    source=private_path(panel.root,'Outputs/Images/synthetic-preview.png')
    source.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'Maintenance/Validation/PreviewsMedia_20261011/klein4-cpu/synthetic-klein4.png',source)
    from platform_runtime import ffmpeg_path
    import media_devices
    from test_settings_surfaces_tk import widgets
    fixture_thread=writer_jobs.WriterJobs.thread
    def preview_thread(group, **kwargs):
        # Enable only the decoder. Keep the launcher's synthetic status/service
        # suppression in force throughout this disposable visual check.
        return (original_thread if kwargs.get('name')=='PortalAIInlineImage' else fixture_thread)(group,**kwargs)
    with patch.object(writer_jobs.WriterJobs,'thread',preview_thread), \
         patch.object(media_devices,'ffmpeg_path',return_value=ffmpeg_path(ROOT)):
        panel.header('Nice')
        panel.assistant_text("Synthetic rendering check: here's the image.\n",stream=True)
        panel.assistant_text('![Generated image](http://127.0.0.1:8765/Images/',stream=True)
        panel.assistant_text('synthetic-preview.png)',stream=True)
        deadline=time.monotonic()+10
        while not any(hasattr(w,'_portalai_image') for w in widgets(panel.chat)):
            app.update()
            if time.monotonic()>deadline:raise TimeoutError('Inline preview did not publish')
            time.sleep(.02)
        assert len(panel.chat.window_names())==1
        assert '![Generated image]' not in panel.chat.get('1.0','end')
        frame=app.nametowidget(panel.chat.window_names()[0])
        frame._portalai_preview_toggle.invoke();app.update()
        assert not frame._portalai_preview_expanded
        assert frame._portalai_preview_body.winfo_manager()==''
        capture_window(app,destination/'inline-minimized.png')
        frame._portalai_preview_toggle.invoke();app.update()
        assert frame._portalai_preview_expanded
        effort=panel.effort
        effort.active_plan={'profile':'balanced','model':'qwen4-abliterated-q4'}
        effort._render()
        assert effort.details_button.cget('text')=='\u2026'
        assert '\u00b7' in effort.label.cget('text') and '\u00c3' not in effort.label.cget('text')
        for _ in range(2):
            app.update();capture_window(app,destination/('inline-'+mark.mode_getter()+'.png'))
            built['toggle_theme']();app.update()
        for i in range(25):
            panel.create_trace_block('thinking',f'Synthetic historical card {i}',initial='Synthetic saved detail.')
            panel.chat_insert(('Synthetic reply. '*30)+'\n')
        samples=Counter();stopped=threading.Event();main_id=threading.get_ident()
        def sample():
            while not stopped.wait(.05):
                frame=sys._current_frames().get(main_id)
                if frame is not None:
                    samples[' > '.join(f'{Path(f.filename).name}:{f.name}:{f.lineno}' for f in traceback.extract_stack(frame)[-7:])]+=1
        sampler=threading.Thread(target=sample,daemon=True);sampler.start()
        profile=cProfile.Profile();profile.enable();start=time.perf_counter();slices=[]
        for i in list(range(30))+list(range(29,-1,-1)):
            lap=time.perf_counter()
            panel.chat.yview_moveto(i/30);app.update()
            slices.append(time.perf_counter()-lap)
        scroll=time.perf_counter()-start
        stopped.set();sampler.join(1)
        profile.disable();stats=io.StringIO()
        (destination/'scroll-samples.json').write_text(json.dumps({'main_thread_samples':samples.most_common(20),
            'slices':slices},indent=2),encoding='utf-8')
        profile.dump_stats(str(destination/'scroll.prof'))
        summary=pstats.Stats(profile,stream=stats).strip_dirs().sort_stats('cumulative')
        summary.print_stats(45);summary.print_callers('select')
        (destination/'scroll-profile.txt').write_text(stats.getvalue(),encoding='utf-8')
        tabs_profile=cProfile.Profile();tabs_profile.enable();start=time.perf_counter();tab_times=[]
        for tab in ('help','settings','chat','welcome','chat'):
            lap=time.perf_counter()
            built['show_tab'](tab);app.update()
            tab_times.append({'tab':tab,'seconds':time.perf_counter()-lap})
        tabs=time.perf_counter()-start
        tabs_profile.disable();tab_stats=io.StringIO()
        pstats.Stats(tabs_profile,stream=tab_stats).strip_dirs().sort_stats('cumulative').print_stats(45)
        (destination/'tabs-profile.txt').write_text(tab_stats.getvalue(),encoding='utf-8')
        page=built['settings_page'];built['show_tab']('settings');page.tabs.select('media');app.update()
        for key,value in {'media_variant':'standard','text_video_engine':'sdcpp-cpu','reference_video_profile':'vace13',
                          'music_engine':'acestep-scaled'}.items():
            page.variables[key].set(value)
            assert page.media_labels[key].get() != value
        assert page.save('media')
        from runtime_policy import load_effective_policy
        saved=load_effective_policy(panel.root)
        assert saved['media']['music_engine']=='acestep-scaled'
        assert saved['media']['media_variant']=='standard' and saved['variant_preference']=='uncensored'
        for position,name in ((0,'independent-chat-setting'),(.20,'independent-media-setting'),
                              (.45,'media-model-descriptions'),(.9,'video-music-descriptions')):
            page.skin.canvas.yview_moveto(position);app.update()
            capture_window(app,destination/(name+'.png'))
        (destination/'ui-timings.json').write_text(json.dumps({'scroll_seconds':scroll,'scrolls':60,
            'five_tab_changes_seconds':tabs,'tab_times':tab_times,'synthetic_cards':25,'media_defaults_saved':True,
            'independent_variants_saved':True},indent=2))
        panel._writer_jobs.close()
        assert panel.wait_for_writers(5)['stopped']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try:report=run(artifacts.path(),inspector=inspect)
    except Exception as exc:report={'passed':False,'error':str(exc)}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(0 if report.get('passed') else 1)
